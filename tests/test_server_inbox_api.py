"""Inbox and interruption budget tests.

Pure budget decisions run on a frozen clock; the HTTP-seam tests walk
list, accept, dismiss, restore, and the cap, the way the manager and the
later agent systems (#13, #14) will meet them.
"""

import json
import sqlite3
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.inbox.budget import decide_budget
from agentdesk.inbox.core import UnknownCard
from agentdesk.inbox.service import evaluate
from agentdesk.inbox.store import InboxStore

MORNING = datetime(2026, 11, 11, 9, 0, 0).astimezone()      # outside quiet hours
EVENING = datetime(2026, 11, 11, 20, 0, 0).astimezone()     # inside quiet hours


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance_to(self, when: datetime) -> None:
        self.now = when.timestamp()

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_budget_is_quiet_during_quiet_hours():
    assert decide_budget(EVENING, 0) == "queue"
    late_night = EVENING.replace(hour=23)
    assert decide_budget(late_night, 0) == "queue"
    early = MORNING.replace(hour=7)
    assert decide_budget(early, 0) == "queue"


def test_budget_notifies_within_the_day_and_caps_at_three():
    assert decide_budget(MORNING, 0) == "notify"
    assert decide_budget(MORNING, 2) == "notify"
    assert decide_budget(MORNING, 3) == "queue"


def test_quiet_hour_boundaries_are_pinned():
    # Exactly 18:00 is already quiet; the minute before it is not.
    assert decide_budget(MORNING.replace(hour=17, minute=59), 0) == "notify"
    assert decide_budget(MORNING.replace(hour=18, minute=0), 0) == "queue"
    # Exactly 08:00 is already working hours; the minute before is not.
    assert decide_budget(MORNING.replace(hour=7, minute=59), 0) == "queue"
    assert decide_budget(MORNING.replace(hour=8, minute=0), 0) == "notify"


def test_notified_today_rolls_over_at_local_midnight():
    clock = FakeClock(MORNING)
    store = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    store.record_notification("card", 1)
    late = MORNING.replace(hour=23, minute=59)
    clock.advance_to(late)
    assert store.notified_today(late) == 1  # today's spend is today's ledger
    next_day = (MORNING + timedelta(days=1)).replace(hour=0)
    clock.advance_to(next_day)
    assert store.notified_today(next_day) == 0  # it does not carry over


def test_concurrent_spends_cannot_overspend_the_day():
    # The ledger read, the decision and the spend used to be separate
    # lock-scoped calls, so two near-simultaneous evaluations could both
    # pass the cap check. One serialized decide-and-spend ends that.
    clock = FakeClock(MORNING)
    store = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    cards = [store.add("suggestion", f"origin {i}", f"card {i}") for i in range(2)]
    spent: list[bool] = []

    def tab() -> None:
        spent.append(store.spend_notification(
            [c.id for c in cards], MORNING, quiet_hours=False, cap=1))

    threads = [threading.Thread(target=tab), threading.Thread(target=tab)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert spent.count(True) == 1
    assert store.notified_today(MORNING) == 1  # one digest row, not two


def test_quiet_hours_queue_then_digest_on_first_morning_read(tmp_path):
    clock = FakeClock(EVENING)
    store = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    store.add("suggestion", "You asked for this breakdown 5 times.", "Save it as one click?")
    tally = evaluate(store, EVENING)
    assert tally == {"notified": 0, "queued": 1, "digest": False}

    clock.advance_to(MORNING.replace(hour=8, minute=5))
    tally = evaluate(store, MORNING.replace(hour=8, minute=5))
    assert tally["notified"] == 1
    card = store.waiting()[0]
    assert card.notified_ts is not None
    # One notification was spent, not zero and not a second one.
    assert store.notified_today(MORNING) == 1


def test_daily_cap_three_then_the_fourth_queues_silently(tmp_path):
    clock = FakeClock(MORNING)
    store = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    statuses = []
    for i in range(4):
        store.add("suggestion", f"origin {i}", f"card {i}")
        statuses.append(evaluate(store, MORNING))
    assert [t["notified"] for t in statuses] == [1, 1, 1, 0]
    assert statuses[3]["queued"] == 1
    assert store.notified_today(MORNING) == 3


def test_batch_of_queued_cards_spends_one_digest_notification(tmp_path):
    clock = FakeClock(EVENING)
    store = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    for i in range(3):
        store.add("suggestion", f"origin {i}", f"card {i}")
        evaluate(store, EVENING)  # quiet: everything queues
    clock.advance_to(MORNING.replace(hour=8, minute=5))
    tally = evaluate(store, MORNING.replace(hour=8, minute=5))
    assert tally == {"notified": 3, "queued": 0, "digest": True}
    assert store.notified_today(MORNING) == 1  # one spend covers the batch


@pytest.fixture()
def env(tmp_path):
    clock = FakeClock(MORNING)
    store = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    booted = server_harness.Booted(inbox_store=store)
    booted.clock = clock
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _add(env, auth, **overrides):
    payload = {
        "kind": "suggestion",
        "origin": "You asked for this breakdown 5 times in two weeks.",
        "title": "Turn the channel report into one click?",
        "body": "It would build the same table from channel-weekly.xlsx.",
        "actionLabel": "Accept skill",
    }
    payload.update(overrides)
    status, _h, body = env.post_json("/inbox/cards", payload, auth)
    assert status == 201
    return json.loads(body)


def test_inbox_endpoints_require_a_session(env):
    status, _h, _b = env.post_json("/inbox/cards", {}, env.host_header())
    assert status == 401


def test_cards_list_accept_dismiss_and_dismissal_is_immediate(env, auth):
    card = _add(env, auth)
    status, _h, body = env.request("GET", "/widgets/inbox", auth)
    assert json.loads(body)["waiting"] == 1

    status, _h, body = env.post_json(f"/inbox/cards/{card['id']}/dismiss", {}, auth)
    payload = json.loads(body)
    assert status == 200  # no confirmation step: dismissal is one act
    assert payload["status"] == "dismissed"
    assert json.loads(env.request("GET", "/widgets/inbox", auth)[2])["waiting"] == 0

    # Decide-once (the #44 mail guard, now for every kind): a decided
    # card answers 409 instead of re-deciding, and restore is the way back.
    status, _h, body = env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    assert status == 409
    assert json.loads(body)["card"]["status"] == "dismissed"
    status, _h, _b = env.post_json(f"/inbox/dismissed/{card['id']}/restore", {}, auth)
    assert status == 200
    status, _h, body = env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    assert status == 200
    assert json.loads(body)["status"] == "accepted"


def test_every_card_type_carries_its_origin_line(env, auth):
    for kind in ("suggestion", "skill_proposal", "update_consent", "brief"):
        payload = _add(env, auth, kind=kind, origin=f"origin for {kind}")
        assert payload["origin"] == f"origin for {kind}"
        assert payload["kind"] == kind


def test_time_bound_cards_carry_their_window_and_expire_visibly(env, auth):
    card = _add(env, auth, kind="brief", origin="Before your 14:00.", windowHours=2)
    assert card["windowHours"] == 2
    assert card["expired"] is False
    env.clock.advance(3 * 3600)
    payload = json.loads(env.request("GET", "/widgets/inbox", auth)[2])
    assert payload["waiting"] == 1  # still there: nothing expires silently
    page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
    assert "window passed" in page
    assert "Time window: 2h" in page


def test_a_string_window_hours_is_refused_at_the_boundary(env, auth):
    # A string window would otherwise be stored and raise in is_expired on
    # every page that shows the rail count: the card constructor refuses
    # it, and the route answers 400 instead of bricking the reads.
    status, _h, body = env.post_json(
        "/inbox/cards",
        {"kind": "brief", "origin": "Before your 14:00.", "title": "Q4 review",
         "windowHours": "2"},
        auth,
    )
    assert status == 400
    assert "window hours" in json.loads(body)["error"]


def test_dismissed_cards_recover_within_30_days_and_are_gone_after(env, auth):
    recoverable = _add(env, auth)
    gone = _add(env, auth, title="Old news")
    env.post_json(f"/inbox/cards/{recoverable['id']}/dismiss", {}, auth)
    env.post_json(f"/inbox/cards/{gone['id']}/dismiss", {}, auth)

    env.clock.advance_to(MORNING + timedelta(days=29))
    status, _h, body = env.post_json(f"/inbox/dismissed/{recoverable['id']}/restore", {}, auth)
    assert status == 200
    assert json.loads(body)["status"] == "waiting"

    # Gone was dismissed on the same morning: it leaves the window one day
    # after its neighbour, and the answer says the window passed.
    env.clock.advance_to(MORNING + timedelta(days=31))
    status, _h, body = env.post_json(f"/inbox/dismissed/{gone['id']}/restore", {}, auth)
    assert status == 410
    assert "30-day" in json.loads(body)["error"]


def test_empty_inbox_renders_the_good_empty_state(env, auth):
    status, _h, body = env.request("GET", "/inbox", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "Nothing needs your attention" in page
    assert "/what-this-touches" in page  # the link to recent activity
    assert "recoverable here for 30 days" in page


def test_rail_carries_the_inbox_count(env, auth):
    assert 'href="/inbox"' in env.request("GET", "/", auth)[2].decode("utf-8")
    _add(env, auth)
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert '<span class="count">1</span>' in page
    # The pill rides inside the Inbox link: one rail row, and the
    # accessible name carries the waiting number. The label rides in a
    # .rail-label span so the collapsed rail can drop the words and keep
    # the count.
    assert "<span class=\"rail-label\">Inbox</span><span class=\"count\">1</span></a>" in page


def test_unknown_card_is_a_404(env, auth):
    status, _h, _b = env.post_json("/inbox/cards/nope/dismiss", {}, auth)
    assert status == 404
