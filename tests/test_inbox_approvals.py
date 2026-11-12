"""Approvals vocabulary on inbox cards (ticket #41), ported from the
teammate's approvals module: editable drafts, snooze with auto-return on
evaluation (their tick), more-info with an instruction. The store-level
behavior runs on a frozen clock; the routes run over the real HTTP seam.
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.inbox.service import evaluate
from agentdesk.inbox.snooze import SNOOZE_TOMORROW, snooze_until
from agentdesk.inbox.store import InboxStore

MORNING = datetime(2026, 11, 11, 9, 0, 0).astimezone()


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance_to(self, when: datetime) -> None:
        self.now = when.timestamp()

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(clock) -> InboxStore:
    return InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)


# -- snooze math ---------------------------------------------------------

def test_snooze_one_hour_adds_exactly_one_hour():
    at = datetime(2026, 11, 11, 14, 30).astimezone()
    assert snooze_until(at, "1h") == (at + timedelta(hours=1)).timestamp()


def test_snooze_tomorrow_is_always_the_next_days_morning():
    # "Tomorrow" is literal: the next calendar day's 08:00 local, the
    # moment quiet hours end, whenever you snooze.
    afternoon = datetime(2026, 11, 11, 14, 0).astimezone()
    assert snooze_until(afternoon, SNOOZE_TOMORROW) == \
        datetime(2026, 11, 12, 8, 0, 0).astimezone().timestamp()
    # Before 08:00 included: tomorrow means tomorrow, not this morning.
    early = datetime(2026, 11, 11, 6, 30).astimezone()
    assert snooze_until(early, SNOOZE_TOMORROW) == \
        datetime(2026, 11, 12, 8, 0, 0).astimezone().timestamp()


def test_snooze_tomorrow_pins_eight_local_across_spring_forward():
    # 2027-03-14 is the US spring-forward. The wall hour must stay 08:00:
    # computing the day first and pinning the hour after keeps the offset
    # honest on zones that shift (and is ordinary arithmetic on UTC).
    eve = datetime(2027, 3, 13, 14, 0).astimezone()
    until = snooze_until(eve, SNOOZE_TOMORROW)
    back = datetime.fromtimestamp(until)  # naive, this machine's local
    assert (back.year, back.month, back.day) == (2027, 3, 14)
    assert (back.hour, back.minute) == (8, 0)


def test_snooze_rejects_an_unknown_choice():
    with pytest.raises(ValueError):
        snooze_until(MORNING, "next week")


# -- store: draft, snooze, more-info ------------------------------------

def test_edit_draft_updates_the_card_and_keeps_it_waiting():
    clock = FakeClock(MORNING)
    store = _store(clock)
    card = store.add("suggestion", "origin", "title", draft="first draft")
    updated = store.edit_draft(card.id, "the polished draft")
    assert updated.draft == "the polished draft"
    assert updated.status == "waiting"
    assert store.get(card.id).draft == "the polished draft"


def test_cards_may_be_created_with_a_draft():
    store = _store(FakeClock(MORNING))
    card = store.add("suggestion", "origin", "title", draft="day one draft")
    assert store.get(card.id).draft == "day one draft"


def test_a_store_from_an_earlier_build_gains_the_new_columns():
    # The previous release's cards table, without draft or snoozed_until.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS cards ("
        " id TEXT PRIMARY KEY, kind TEXT NOT NULL, origin TEXT NOT NULL,"
        " title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',"
        " action_label TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,"
        " created_ts REAL NOT NULL, window_hours REAL, notified_ts REAL,"
        " dismissed_ts REAL, accepted_ts REAL,"
        " meta TEXT NOT NULL DEFAULT '{}')"
    )
    conn.execute(
        "INSERT INTO cards (id, kind, origin, title, status, created_ts, meta)"
        " VALUES ('old-1', 'suggestion', 'origin', 'title', 'waiting', 1.0, '{}')"
    )
    store = InboxStore(conn, FakeClock(MORNING))  # ensure_schema migrates
    card = store.get("old-1")
    assert card.draft == ""
    assert card.snoozed_until is None
    store.snooze("old-1", MORNING.timestamp() + 60)
    assert store.get("old-1").snoozed_until == MORNING.timestamp() + 60


def test_a_future_snooze_hides_the_card_from_waiting():
    clock = FakeClock(MORNING)
    store = _store(clock)
    card = store.add("suggestion", "origin", "title")
    store.snooze(card.id, clock() + 3600)
    assert store.waiting() == []
    # The card is not gone, and not decided: only hidden until due.
    assert store.get(card.id).status == "waiting"
    # Dedupe callers (briefs, the consolidator) still see it, so hiding
    # a card for an hour cannot mint a twin.
    assert [c.id for c in store.waiting(include_snoozed=True)] == [card.id]


def test_a_due_snooze_is_visible_again_and_evaluation_clears_it():
    clock = FakeClock(MORNING)
    store = _store(clock)
    card = store.add("suggestion", "origin", "title")
    store.snooze(card.id, clock() + 60)
    clock.advance(120)
    # Due (snoozed_until in the past): visible in the waiting set again.
    assert [c.id for c in store.waiting()] == [card.id]
    returned = []
    evaluate(store, MORNING + timedelta(seconds=120),
             on_snooze_return=returned.append)
    assert [c.id for c in returned] == [card.id]
    assert store.get(card.id).snoozed_until is None
    assert store.get(card.id).status == "waiting"


def test_evaluation_does_not_return_a_snooze_that_is_still_running():
    clock = FakeClock(MORNING)
    store = _store(clock)
    card = store.add("suggestion", "origin", "title")
    store.snooze(card.id, clock() + 3600)
    returned = []
    evaluate(store, MORNING, on_snooze_return=returned.append)
    assert returned == []
    assert store.get(card.id).snoozed_until == clock() + 3600


def test_a_due_snooze_is_reported_once_no_matter_how_often_evaluation_runs():
    # /inbox and /widgets/inbox can evaluate concurrently; the clear is
    # conditional (only a still-snoozed row counts), so a return is
    # reported, and logged, exactly once.
    clock = FakeClock(MORNING)
    store = _store(clock)
    card = store.add("suggestion", "origin", "title")
    store.snooze(card.id, clock() - 1)  # already due
    assert [c.id for c in store.return_due_snoozes()] == [card.id]
    assert store.return_due_snoozes() == []


def test_more_info_attaches_the_instruction_and_returns_the_card():
    clock = FakeClock(MORNING)
    store = _store(clock)
    card = store.add("suggestion", "origin", "title")
    store.snooze(card.id, clock() + 3600)
    updated = store.more_info(card.id, "show the totals first")
    assert updated.meta["instruction"] == "show the totals first"
    assert updated.snoozed_until is None
    assert updated.status == "waiting"


# -- card payload --------------------------------------------------------

def test_card_payload_exposes_draft_and_snooze_state():
    clock = FakeClock(MORNING)
    store = _store(clock)
    card = store.add("suggestion", "origin", "title", draft="the draft")
    payload = store.get(card.id).to_json(clock())
    assert payload["draft"] == "the draft"
    assert payload["snoozedUntil"] is None
    store.snooze(card.id, clock() + 3600)
    payload = store.get(card.id).to_json(clock())
    assert payload["snoozedUntil"] == clock() + 3600


# -- HTTP seam: the three actions ----------------------------------------

@pytest.fixture()
def env(tmp_path):
    clock = FakeClock(MORNING)
    store = _store(clock)
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
        "draft": "Summarize channel-weekly.xlsx into a one-page table.",
    }
    payload.update(overrides)
    status, _h, body = env.post_json("/inbox/cards", payload, auth)
    assert status == 201
    return json.loads(body)


def test_edit_endpoint_updates_the_draft_and_audits_edited(env, auth):
    card = _add(env, auth)
    status, _h, body = env.post_json(
        f"/inbox/cards/{card['id']}/edit", {"draft": "the edited draft"}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["draft"] == "the edited draft"
    assert payload["status"] == "waiting"
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    edit_rows = [e for e in entries if e["action"] == "inbox.edited"]
    assert len(edit_rows) == 1
    assert edit_rows[0]["target"] == card["id"]
    assert "the edited draft" in edit_rows[0]["detail"]


def test_edit_endpoint_keeps_a_plain_text_preview_not_the_markup(env, auth):
    card = _add(env, auth)
    env.post_json(f"/inbox/cards/{card['id']}/edit",
                  {"draft": "<b>channel</b> &nbsp; report\n\nsummary"}, auth)
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    detail = [e for e in entries if e["action"] == "inbox.edited"][0]["detail"]
    assert "<b>" not in detail
    assert "channel report summary" in detail


def test_edit_endpoint_rejects_a_missing_draft(env, auth):
    card = _add(env, auth)
    status, _h, body = env.post_json(f"/inbox/cards/{card['id']}/edit", {}, auth)
    assert status == 400
    assert "draft" in json.loads(body)["error"]


def test_snooze_endpoint_hides_the_card_and_audits_snoozed(env, auth):
    card = _add(env, auth)
    status, _h, body = env.post_json(
        f"/inbox/cards/{card['id']}/snooze", {"choice": "1h"}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["snoozedUntil"] == env.clock() + 3600
    count = json.loads(env.request("GET", "/widgets/inbox", auth)[2])
    assert count["waiting"] == 0
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    snooze_rows = [e for e in entries if e["action"] == "inbox.snoozed"]
    assert len(snooze_rows) == 1
    assert snooze_rows[0]["target"] == card["id"]


def test_snooze_endpoint_tomorrow_choice_uses_the_next_morning(env, auth):
    card = _add(env, auth)
    status, _h, body = env.post_json(
        f"/inbox/cards/{card['id']}/snooze", {"choice": "tomorrow"}, auth)
    assert status == 200
    expected = datetime(2026, 11, 12, 8, 0, 0).astimezone().timestamp()
    assert json.loads(body)["snoozedUntil"] == expected


def test_snooze_endpoint_rejects_an_unknown_choice(env, auth):
    card = _add(env, auth)
    status, _h, _b = env.post_json(
        f"/inbox/cards/{card['id']}/snooze", {"choice": "next week"}, auth)
    assert status == 400


def test_a_returned_snooze_is_audited_as_pending(env, auth):
    card = _add(env, auth)
    env.post_json(f"/inbox/cards/{card['id']}/snooze", {"choice": "1h"}, auth)
    env.clock.advance(2 * 3600)
    count = json.loads(env.request("GET", "/widgets/inbox", auth)[2])
    assert count["waiting"] == 1  # back in the visible waiting set
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    pending_rows = [e for e in entries if e["action"] == "inbox.pending"]
    assert len(pending_rows) == 1
    assert pending_rows[0]["target"] == card["id"]


def test_more_info_endpoint_attaches_the_instruction_and_audits(env, auth):
    card = _add(env, auth)
    status, _h, body = env.post_json(
        f"/inbox/cards/{card['id']}/more-info",
        {"instruction": "show the margin column too"}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["meta"]["instruction"] == "show the margin column too"
    assert payload["status"] == "waiting"
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    info_rows = [e for e in entries if e["action"] == "inbox.more-info"]
    assert len(info_rows) == 1
    assert "show the margin column too" in info_rows[0]["detail"]


def test_more_info_endpoint_rejects_an_empty_instruction(env, auth):
    card = _add(env, auth)
    status, _h, _b = env.post_json(
        f"/inbox/cards/{card['id']}/more-info", {"instruction": "  "}, auth)
    assert status == 400


def test_actions_accept_form_posts_and_redirect_back(env, auth):
    card = _add(env, auth)
    form = "draft=the+form+draft".encode("utf-8")
    status, headers, _b = env.request(
        "POST", f"/inbox/cards/{card['id']}/edit",
        {"Cookie": auth["Cookie"], "Host": f"127.0.0.1:{env.port}",
         "Content-Type": "application/x-www-form-urlencoded",
         "Content-Length": str(len(form))},
        body=form)
    assert status == 303
    assert headers["Location"] == "/inbox"
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    assert any(e["action"] == "inbox.edited" for e in entries)


def test_accept_and_dismiss_are_audited_with_the_decision_vocabulary(env, auth):
    card = _add(env, auth)
    env.post_json(f"/inbox/cards/{card['id']}/dismiss", {}, auth)
    other = _add(env, auth, title="second")
    env.post_json(f"/inbox/cards/{other['id']}/accept", {}, auth)
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    assert any(e["action"] == "inbox.denied" and e["target"] == card["id"]
               for e in entries)
    assert any(e["action"] == "inbox.approved" and e["target"] == other["id"]
               for e in entries)


# -- inbox page forms ----------------------------------------------------

def test_inbox_page_renders_the_three_new_forms(env, auth):
    card = _add(env, auth)
    page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
    assert f"action='/inbox/cards/{card['id']}/edit'" in page
    assert f"action='/inbox/cards/{card['id']}/snooze'" in page
    assert f"action='/inbox/cards/{card['id']}/more-info'" in page
    assert "the draft lives here" in page or "name='draft'" in page
    assert "name='choice'" in page
    assert "<option value='1h'>" in page
    assert "<option value='tomorrow'>" in page
    assert "name='instruction'" in page


def test_every_card_kind_renders_its_own_label(env, auth):
    for kind, label in (
        ("update_consent", "Update needs your OK"),
        ("brief", "Before your meeting"),
        ("feature_request", "Feature request"),
    ):
        card = _add(env, auth, kind=kind, title=f"the {kind} card")
        page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
        assert label in page
        assert f"the {kind} card" in page


def test_snoozed_cards_are_hidden_from_the_inbox_page(env, auth):
    card = _add(env, auth)
    env.post_json(f"/inbox/cards/{card['id']}/snooze", {"choice": "1h"}, auth)
    page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
    assert "Turn the channel report into one click?" not in page


def test_inbox_page_ages_cards_by_the_store_clock_not_the_wall_clock(env, auth):
    # The store's one-clock rule: the page judges windows and age by the
    # same clock that set them. The window below is far in the future by
    # wall time but passed by the (advanced) store clock.
    _add(env, auth, kind="brief", windowHours=24 * 400)
    env.clock.advance(24 * 401 * 3600)
    page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
    assert "window passed" in page
