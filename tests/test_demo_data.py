"""Sample data for the demo desk (ticket #68): the switch, the seed, the
honest clear, and every card action on a sample card, end to end.

The switch lives in settings beside the others and is not a data source:
no 409 semantics, no watcher to stop. Turning it on seeds labelled
sample cards into the real inbox store and writes sample fixtures under
the app's own sample folder in the data dir; turning it off removes
exactly what the Sample markers identify. Every seeded surface says
Sample, so no sample content can be mistaken for live data.
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.excel.xlsx import parse_workbook_bytes
from agentdesk.inbox.core import UnknownCard
from agentdesk.inbox.store import InboxStore
from agentdesk.server import demo_data

MORNING = datetime(2026, 11, 11, 9, 0, 0).astimezone()

SAMPLE_CARD_IDS = (
    "sample-update",
    "sample-brief",
    "sample-feature-request",
    "sample-update-consent",
)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(clock) -> InboxStore:
    return InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A booted desk on a temp data dir: the demo seed writes real files,
    so AGENTDESK_DATA points at a folder this test owns."""
    clock = FakeClock(MORNING)
    store = _store(clock)
    data_dir = tmp_path / "desk-data"
    monkeypatch.setenv("AGENTDESK_DATA", str(data_dir))
    booted = server_harness.Booted(inbox_store=store)
    booted.clock = clock
    booted.data_dir = data_dir
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _toggle(env, auth):
    return env.post_json("/settings/toggle", {"key": "sample_data"}, auth)


def _every_card(inbox: InboxStore):
    return inbox.waiting(include_snoozed=True) + inbox.dismissed() + [
        c for c in inbox.all_cards() if c.status == "accepted"
    ]


# -- the switch ------------------------------------------------------------

def test_sample_data_is_off_by_default_and_answers_the_toggle(env, auth):
    values = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values["sample_data"] is False
    status, _h, body = _toggle(env, auth)
    assert status == 200
    assert json.loads(body) == {"key": "sample_data", "value": True}
    values = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values["sample_data"] is True


def test_the_settings_page_renders_the_plain_sample_data_switch(env, auth):
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert ">Sample data</span>" in page
    assert "data-setting='sample_data'" in page


def test_toggling_sample_data_writes_its_audit_rows(env, auth):
    _toggle(env, auth)
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    assert any(e["action"] == "demo.seeded" for e in entries)
    _toggle(env, auth)  # back off
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    assert any(e["action"] == "demo.cleared" for e in entries)
    # The demo turns are decisions: they show on the activity page.
    page = env.request("GET", "/activity", auth)[2].decode("utf-8")
    assert "<b>sample on</b>" in page
    assert "<b>sample off</b>" in page


# -- seeding ---------------------------------------------------------------

def test_sample_sales_rows_are_100_crm_deals():
    rows = demo_data._sample_sales_rows()
    assert rows[0] == ["Deal", "Region", "Stage", "Amount", "Close date", "Owner"]
    assert len(rows) == 101
    body = rows[1:]
    assert len(body) == 100
    for row in body:
        assert len(row) == 6
        deal, region, stage, amount, close_date, owner = row
        assert isinstance(deal, str) and deal and not deal.startswith("Sample")
        assert isinstance(region, str) and region
        assert isinstance(stage, str) and stage
        assert isinstance(amount, float)
        assert isinstance(close_date, str) and len(close_date) == 10 and close_date[4] == "-"
        assert isinstance(owner, str) and owner and not owner.startswith("Sample")
    # Every deal is a different deal: no name repeats.
    assert len({row[0] for row in body}) == len(body)
    # Deterministic: two calls match, and workbook bytes round-trip the same rows
    assert demo_data._sample_sales_rows() == rows
    assert parse_workbook_bytes(demo_data.sample_workbook_bytes()) == rows


def test_toggling_on_seeds_labelled_cards_of_each_kind(env, auth):
    _toggle(env, auth)
    cards = {c.id: c for c in _every_card(env.server.inbox)}
    kinds = {
        "sample-update": "suggestion",
        "sample-brief": "brief",
        "sample-feature-request": "feature_request",
        "sample-update-consent": "update_consent",
    }
    for card_id, kind in kinds.items():
        assert card_id in cards, f"missing seeded card {card_id}"
        card = cards[card_id]
        assert card.kind == kind
        assert card.id.startswith(demo_data.CARD_ID_PREFIX)
        assert card.meta.get("sample") is True
        assert card.origin.startswith("Sample data:")
        assert card.status == "waiting"
    consent = cards["sample-update-consent"]
    assert consent.meta.get("pluginId")
    assert consent.meta.get("scope")


def test_toggling_on_writes_the_sample_fixtures_under_the_data_dir(env, auth):
    _toggle(env, auth)
    folder = env.data_dir / "sample"
    workbook = folder / "sample-sales.xlsx"
    assert workbook.exists()
    rows = parse_workbook_bytes(workbook.read_bytes())  # the real reader
    assert rows[0] == ["Deal", "Region", "Stage", "Amount", "Close date", "Owner"]
    assert len(rows) == 101
    # The sample marker is the folder, the file name and the sheet; the
    # desk tags the cell once, so the rows carry no prefix.
    assert not any(str(r[0]).startswith("Sample") for r in rows[1:])
    calendar = json.loads((folder / "sample-calendar.json").read_text("utf-8"))
    assert calendar["events"]
    assert all(e["id"].startswith("sample-") for e in calendar["events"])
    mails = sorted((folder / "sample-mail").glob("*.eml"))
    assert len(mails) >= 3
    for path in mails:
        raw = path.read_text("utf-8")
        assert path.name.startswith("sample-")  # the file name says it
        _head, sep, body = raw.partition("\n\n")
        assert sep == "" or body.strip() == ""  # header-only: no bodies ever


def test_the_sample_cards_render_with_a_sample_tag_and_origin(env, auth):
    _toggle(env, auth)
    page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
    assert page.count("tag-sample") >= len(SAMPLE_CARD_IDS)
    assert "Sample data:" in page


def test_the_dismissed_shelf_labels_sample_cards_too(env, auth):
    # Two seeded titles carry no sample wording, so a bare shelf row
    # would surface them unlabelled. Every shelf row for a sample card
    # carries the same Sample tag the waiting card does.
    _toggle(env, auth)
    for card_id in SAMPLE_CARD_IDS:
        assert env.post_json(f"/inbox/cards/{card_id}/dismiss", {}, auth)[0] == 200
    page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
    assert "Nothing needs your attention" in page  # the waiting set is empty
    assert page.count("tag-sample") >= len(SAMPLE_CARD_IDS)  # the shelf rows


def test_seeding_twice_keeps_one_of_each_sample_card(env, auth):
    _toggle(env, auth)
    demo_data.seed(env.server.inbox, env.data_dir)  # a defensive re-seed
    ids = [c.id for c in _every_card(env.server.inbox)]
    assert sorted(i for i in ids if i.startswith(demo_data.CARD_ID_PREFIX)) \
        == sorted(SAMPLE_CARD_IDS)


# -- clearing --------------------------------------------------------------

def test_toggling_off_removes_sample_cards_in_every_state_and_keeps_user_cards(env, auth):
    _toggle(env, auth)
    status, _h, _b = env.post_json("/inbox/cards", {
        "kind": "suggestion", "origin": "You asked for this twice.",
        "title": "Keep me", "body": "a real card of the user's own",
    }, auth)
    assert status == 201
    assert env.post_json("/inbox/cards/sample-update/accept", {}, auth)[0] == 200
    assert env.post_json("/inbox/cards/sample-brief/dismiss", {}, auth)[0] == 200
    status, _h, body = _toggle(env, auth)
    assert status == 200 and json.loads(body)["value"] is False
    remaining = _every_card(env.server.inbox)
    assert not [c for c in remaining if demo_data.is_seed_card(c)]
    assert any(c.title == "Keep me" for c in remaining)


def test_a_user_card_flagged_sample_in_meta_survives_the_clear(env, auth):
    # The meta flag renders a card as Sample; it must never mark one for
    # deletion. A client-supplied {"sample": true} on the user's own card
    # keeps its 30-day recovery like every other card they made.
    _toggle(env, auth)
    status, _h, _b = env.post_json("/inbox/cards", {
        "kind": "suggestion", "origin": "You asked for this twice.",
        "title": "Mine, flagged by mistake",
        "meta": {"sample": True},
    }, auth)
    assert status == 201
    _toggle(env, auth)  # off
    remaining = _every_card(env.server.inbox)
    assert any(c.title == "Mine, flagged by mistake" for c in remaining)
    assert not [c for c in remaining if demo_data.is_seed_card(c)]


def test_clear_deletes_only_the_id_prefix_not_the_meta_flag(tmp_path):
    clock = FakeClock(MORNING)
    store = _store(clock)
    demo_data.seed(store, tmp_path)
    flagged = store.add("suggestion", "origin", "user card, meta-flagged",
                        card_id="card-user-1", meta={"sample": True})
    cleared = demo_data.clear(store, tmp_path)
    assert cleared["cards"] == len(SAMPLE_CARD_IDS)
    ids = [c.id for c in store.all_cards()]
    assert ids == [flagged.id]
    # The flag still renders, it just never deletes.
    assert demo_data.is_sample_card(flagged) and not demo_data.is_seed_card(flagged)


def test_toggling_off_removes_the_sample_folder_and_nothing_else(env, auth):
    _toggle(env, auth)
    keep = env.data_dir / "user-notes.txt"
    keep.write_text("mine", encoding="utf-8")
    _toggle(env, auth)
    assert not (env.data_dir / "sample").exists()
    assert keep.exists()


def test_clear_on_a_fresh_desk_is_a_no_op(tmp_path):
    result = demo_data.clear(_store(FakeClock(MORNING)), tmp_path)
    assert result["cards"] == 0
    assert not (tmp_path / "sample").exists()


# -- the empty state ---------------------------------------------------------

def test_an_empty_inbox_offers_the_sample_switch_as_a_plain_form(env, auth):
    page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
    assert "Show me what this looks like with sample data" in page
    assert "action='/settings/toggle'" in page
    assert "name='key'" in page
    assert "value='sample_data'" in page


def test_the_offer_is_gone_once_sample_data_is_on(env, auth):
    _toggle(env, auth)
    for card_id in SAMPLE_CARD_IDS:
        assert env.post_json(f"/inbox/cards/{card_id}/dismiss", {}, auth)[0] == 200
    page = env.request("GET", "/inbox", auth)[2].decode("utf-8")
    assert "Show me what this looks like with sample data" not in page


def test_the_empty_state_form_post_seeds_and_redirects_back(env, auth):
    form = b"key=sample_data"
    status, headers, _b = env.request(
        "POST", "/settings/toggle",
        {"Cookie": auth["Cookie"], "Host": f"127.0.0.1:{env.port}",
         "Content-Type": "application/x-www-form-urlencoded",
         "Content-Length": str(len(form))},
        body=form)
    assert status == 303
    assert headers["Location"] == "/inbox"
    values = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values["sample_data"] is True
    assert [c.id for c in _every_card(env.server.inbox) if c.id.startswith("sample-")]


# -- every card action on the sample cards -----------------------------------

def test_every_card_action_works_on_the_sample_cards_and_audits(env, auth):
    _toggle(env, auth)

    # accept: the update card
    status, _h, body = env.post_json("/inbox/cards/sample-update/accept", {}, auth)
    assert status == 200
    assert json.loads(body)["status"] == "accepted"

    # edit: the brief's draft payload, still waiting
    status, _h, body = env.post_json(
        "/inbox/cards/sample-brief/edit",
        {"draft": "Sample edit: show the attendees first"}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["draft"] == "Sample edit: show the attendees first"
    assert payload["status"] == "waiting"

    # snooze +1h hides the feature request; the auto-return brings it back
    status, _h, body = env.post_json(
        "/inbox/cards/sample-feature-request/snooze", {"choice": "1h"}, auth)
    assert status == 200
    assert json.loads(body)["snoozedUntil"] == env.clock() + 3600
    count = json.loads(env.request("GET", "/widgets/inbox", auth)[2])
    assert count["waiting"] == 2  # brief + consent
    env.clock.advance(2 * 3600)
    count = json.loads(env.request("GET", "/widgets/inbox", auth)[2])
    assert count["waiting"] == 3  # returned, never silently

    # the tomorrow flavor pins the next morning
    status, _h, body = env.post_json(
        "/inbox/cards/sample-feature-request/snooze", {"choice": "tomorrow"}, auth)
    assert status == 200
    expected = datetime(2026, 11, 12, 8, 0, 0).astimezone().timestamp()
    assert json.loads(body)["snoozedUntil"] == expected

    # more-info attaches the instruction and ends the snooze early
    status, _h, body = env.post_json(
        "/inbox/cards/sample-feature-request/more-info",
        {"instruction": "say which wizard session it came from"}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["meta"]["instruction"] == "say which wizard session it came from"
    assert payload["snoozedUntil"] is None

    # dismiss, then restore the dismissed card
    assert env.post_json("/inbox/cards/sample-brief/dismiss", {}, auth)[0] == 200
    status, _h, body = env.post_json("/inbox/dismissed/sample-brief/restore", {}, auth)
    assert status == 200
    assert json.loads(body)["status"] == "waiting"

    # accepting the update-consent records the (plugin, scope) allow
    consent = env.server.inbox.get("sample-update-consent")
    plugin_id = consent.meta["pluginId"]
    scope = consent.meta["scope"]
    assert env.server.consents.allowed(plugin_id, scope) is False
    status, _h, _b = env.post_json(
        "/inbox/cards/sample-update-consent/accept", {"forPlugin": True}, auth)
    assert status == 200
    assert env.server.consents.allowed(plugin_id, scope) is True

    # every action audited, with the sample card as its target
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    actions = {e["action"] for e in entries}
    for action in ("inbox.approved", "inbox.edited", "inbox.snoozed",
                   "inbox.pending", "inbox.more-info", "inbox.denied",
                   "inbox.restored"):
        assert action in actions
    targets = {e["target"] for e in entries}
    assert {"sample-update", "sample-brief", "sample-feature-request"} <= targets

    # and the activity page shows the words
    page = env.request("GET", "/activity", auth)[2].decode("utf-8")
    for word in ("approved", "edited", "snoozed", "pending", "more-info",
                 "denied", "restored"):
        assert word in page


# -- the store's demo support ------------------------------------------------

def test_the_store_lists_every_card_and_deletes_outright():
    clock = FakeClock(MORNING)
    store = _store(clock)
    keep = store.add("suggestion", "origin", "keep")
    gone = store.add("suggestion", "origin", "gone")
    store.accept(gone.id)  # an accepted card is invisible to the status lists
    assert [c.id for c in store.all_cards()] == [keep.id, gone.id]
    store.delete(gone.id)
    assert [c.id for c in store.all_cards()] == [keep.id]
    with pytest.raises(UnknownCard):
        store.delete(gone.id)


def test_seed_and_clear_on_a_raw_store_and_folder(tmp_path):
    clock = FakeClock(MORNING)
    store = _store(clock)
    user = store.add("suggestion", "origin", "user card")
    seeded = demo_data.seed(store, tmp_path)
    assert seeded["cards"] == len(SAMPLE_CARD_IDS)
    assert [c for c in store.all_cards() if demo_data.is_sample_card(c)]
    cleared = demo_data.clear(store, tmp_path)
    assert cleared["cards"] == len(SAMPLE_CARD_IDS)
    assert [c.id for c in store.all_cards()] == [user.id]
    assert not (tmp_path / "sample").exists()


def test_seed_without_an_inbox_still_writes_the_files(tmp_path):
    seeded = demo_data.seed(None, tmp_path)
    assert seeded["cards"] == 0
    assert (tmp_path / "sample" / "sample-sales.xlsx").exists()


def test_the_demo_and_restore_actions_are_in_the_audit_vocabulary():
    actions = {action for action, _kind, _statement in audit_store.VOCABULARY}
    for action in ("demo.seeded", "demo.cleared", "inbox.restored"):
        assert action in actions


def test_sample_mail_dates_fall_inside_the_digest_window(env, auth):
    """The sample mail is dated relative to seeding time (#68 fix): the
    digest counts the last 24 hours of headers, so fixtures pinned to
    authored dates would bind zeros forever and the demo card would
    look broken while behaving honestly. Parse the real Date headers
    and require every one to sit inside the window."""
    from datetime import timedelta
    from email.utils import parsedate_to_datetime

    _toggle(env, auth)
    mails = sorted((env.data_dir / "sample" / "sample-mail").glob("*.eml"))
    assert len(mails) >= 3
    # The same clock the seed stamped the fixtures against: the inbox
    # store's (frozen in this harness, the wall clock in production).
    now = datetime.fromtimestamp(env.server.inbox.now_ts()).astimezone()
    for path in mails:
        date_line = next(
            line for line in path.read_text("utf-8").splitlines()
            if line.startswith("Date: ")
        )
        stamped = parsedate_to_datetime(date_line.removeprefix("Date: "))
        age = now - stamped
        assert timedelta(0) <= age <= timedelta(hours=24), (
            f"{path.name} is dated {age} old; outside the 24-hour window"
        )


def test_the_dashboard_payload_says_when_sample_data_is_on(env, auth):
    def sample_flag():
        status, _headers, body = env.request("GET", "/api/dashboard", auth)
        assert status == 200
        return json.loads(body)["sample"]

    assert sample_flag() is False
    _toggle(env, auth)
    assert sample_flag() is True
