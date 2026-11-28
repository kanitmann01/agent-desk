"""Recommendations on the two dashboard surfaces and their inbox cards
(spec 016 §7, §9.1, §9.2, §13).

The whole stack runs on one frozen clock: the settings, inbox and memory
stores and the ledger all read it, so "December 15" is a fixed number of
days out and the assertions do not drift with the wall clock.
"""

import datetime
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from nexuusbot.assistant import audit as audit_store
from nexuusbot.inbox.store import InboxStore
from nexuusbot.ledger.store import Ledger
from nexuusbot.memory.store import MemoryStore
from nexuusbot.settings import SettingsStore
from nexuusbot.server import demo_data

MORNING = datetime.datetime(2026, 11, 20, 9, 0, 0)


class FakeClock:
    """A clock the whole desk shares, frozen one November morning."""

    def __init__(self, start: datetime.datetime) -> None:
        """Hold one timestamp and hand it back on every call."""
        self.now = start.astimezone().timestamp()

    def __call__(self) -> float:
        """Return the frozen timestamp."""
        return self.now


def _stores():
    """Build the desk stores this test needs, all on one frozen clock."""
    clock = FakeClock(MORNING)
    settings = SettingsStore(
        sqlite3.connect(":memory:", check_same_thread=False), clock
    )
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    memory = MemoryStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    ledger = Ledger(":memory:", clock=clock)
    return settings, inbox, memory, ledger


def _boot(stores, data_dir):
    """Boot a desk on the given stores, with sample files under the test's dir."""
    settings, inbox, memory, ledger = stores
    return server_harness.Booted(
        settings_store=settings,
        inbox_store=inbox,
        memory_store=memory,
        ledger=ledger,
    )


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    """A booted desk over a throwaway data folder, and its stores."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "desk-data"))
    stores = _stores()
    booted = _boot(stores, tmp_path)
    booted.stores = stores
    booted.data_dir = tmp_path / "desk-data"
    try:
        yield booted
    finally:
        booted.close()


def _auth(desk):
    return desk.exchange()


def _toggle(desk, auth, key):
    """Flip one settings toggle through the JSON route."""
    status, _headers, body = desk.post_json("/settings/toggle", {"key": key}, auth)
    assert status == 200, body
    return json.loads(body)["value"]


def _recommendations(desk, auth):
    """Read the recommendations[] of the dashboard payload."""
    status, _headers, body = desk.request("GET", "/api/dashboard", auth)
    assert status == 200
    return json.loads(body)["recommendations"]


def _harborlight(desk, auth):
    """The Harborlight Freight recommendation, or a failure naming what was served."""
    recs = _recommendations(desk, auth)
    return next(r for r in recs if r["title"].startswith("Harborlight Freight")), recs


def _dismiss(desk, auth, card_id):
    """Post the no-JS Not now form the rendered dashboard shows."""
    body = urlencode({"card": card_id}).encode()
    headers = dict(auth)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    headers["Content-Length"] = str(len(body))
    return desk.request("POST", f"/inbox/cards/{card_id}/dismiss", headers, body)


def test_dashboard_api_serves_the_sample_recommendation(desk):
    auth = _auth(desk)
    assert _toggle(desk, auth, "sample_data") is True
    rec, recs = _harborlight(desk, auth)
    assert rec["sample"] is True
    assert rec["title"] == "Harborlight Freight: December 15 (in 25 days)"
    assert "Harold" not in json.dumps(rec)
    assert "wants the renewal signed" not in json.dumps(recs)
    assert rec["why"] == "You told the desk this deadline; it is 25 days away."
    assert rec["whySource"] == "rule"
    assert rec["score"] is None
    assert rec["due"] == "2026-12-15"
    assert rec["href"] == "/agents"
    assert rec["actionLabel"] == "Open Agents"
    assert isinstance(rec["cites"], list) and all(isinstance(i, int) for i in rec["cites"])
    assert len(recs) <= 5
    assert rec["cardId"]


def test_server_rendered_dashboard_shows_the_decisions_widget(desk):
    auth = _auth(desk)
    _toggle(desk, auth, "sample_data")
    rec, _recs = _harborlight(desk, auth)
    page = desk.request("GET", "/", auth)[2].decode("utf-8")
    assert ">Decisions</h2>" in page
    assert "Harborlight Freight: December 15 (in 25 days)" in page
    assert "Not now" in page
    assert f'action="/inbox/cards/{rec["cardId"]}/dismiss"' in page
    assert ">Open Agents</a>" in page
    assert "sample-tag" in page or "SAMPLE" in page


def test_server_rendered_dashboard_shows_setup_decisions_when_nothing_is_saved(desk):
    auth = _auth(desk)
    page = desk.request("GET", "/", auth)[2].decode("utf-8")
    assert ">Decisions</h2>" in page
    assert "Nothing needs a decision." not in page
    assert "Connect a workbook" in page
    assert "The pipeline figure and the moves come from it." in page
    assert "Connect your calendar" in page
    assert "The digest reads today" in page
    assert "meetings from it." in page
    assert "Ask your first question" in page
    assert "Answers come from your AI and are logged." in page
    assert page.count('class="decision-title"') == 3


class _LiveCalendar:
    """A calendar bridge whose status is a connected, non-empty source."""

    def status(self):
        """Report one connected calendar with a key event."""
        return {"state": "clear", "configured": True}


class _LiveWorkbook:
    """A workbook watch whose status is a configured source."""

    registered_path = "sample-sales.xlsx"

    def status(self):
        """Report the first snapshot of a connected workbook."""
        return {
            "state": "first",
            "configured": True,
            "path": "sample-sales.xlsx",
            "last_ok_ts": MORNING.astimezone().timestamp(),
        }


def test_server_rendered_dashboard_says_nothing_needs_a_decision_once_set_up(desk):
    auth = _auth(desk)
    _toggle(desk, auth, "sample_data")
    _harborlight(desk, auth)
    desk.server.calendar = _LiveCalendar()
    desk.server.excel = _LiveWorkbook()
    audit_store.record(desk.server.audit_conn, "llm.research", status="ok")
    for rec in _recommendations(desk, auth):
        status, _headers, _body = _dismiss(desk, auth, rec["cardId"])
        assert status == 303
    page = desk.request("GET", "/", auth)[2].decode("utf-8")
    assert ">Decisions</h2>" in page
    assert "Nothing needs a decision." in page
    assert "Connect a workbook" not in page
    assert "Connect your calendar" not in page
    assert "Ask your first question" not in page
    assert "/inbox/cards/" not in page


def test_not_now_removes_the_card_and_it_stays_gone_across_a_restart(desk, tmp_path):
    auth = _auth(desk)
    _toggle(desk, auth, "sample_data")
    rec, _recs = _harborlight(desk, auth)
    status, headers, _body = _dismiss(desk, auth, rec["cardId"])
    assert status == 303
    assert headers.get("Location").split("?", 1)[0] == "/inbox"
    assert all(r["cardId"] != rec["cardId"] for r in _recommendations(desk, auth))
    card = desk.server.inbox.get(rec["cardId"])
    assert card.status == "dismissed"
    booted = _boot(desk.stores, tmp_path)
    try:
        again = booted.exchange()
        recs = _recommendations(booted, again)
        assert all(r["cardId"] != rec["cardId"] for r in recs)
        assert any(r["title"].startswith("Prep for ") for r in recs)
    finally:
        booted.close()


def test_memory_add_builds_a_recommendation_from_the_saved_fact(desk):
    auth = _auth(desk)
    status, _headers, _body = desk.post_json(
        "/memory/add", {"text": "Quarterly pricing review due December 1."}, auth
    )
    assert status == 201
    recs = _recommendations(desk, auth)
    assert [r["title"] for r in recs] == [
        "Quarterly: December 1 (in 11 days)"
    ]
    assert recs[0]["sample"] is False


def test_deleting_the_fact_withdraws_its_recommendation(desk):
    auth = _auth(desk)
    _toggle(desk, auth, "sample_data")
    rec, _recs = _harborlight(desk, auth)
    fact_id = rec["cites"][0]
    status, _headers, _body = desk.post_json(f"/memory/{fact_id}/delete", {}, auth)
    assert status == 200
    assert all(r["cardId"] != rec["cardId"] for r in _recommendations(desk, auth))
    card = desk.server.inbox.get(rec["cardId"])
    assert card.status == "dismissed"
    assert card.origin.startswith("Withdrawn:")
    actions = [entry.action for entry in desk.server.ledger.entries(limit=50)]
    assert "recommend.withdrawn" in actions


def test_recommendations_off_creates_no_new_cards_but_keeps_the_waiting_one(desk):
    auth = _auth(desk)
    _toggle(desk, auth, "sample_data")
    rec, _recs = _harborlight(desk, auth)
    assert _toggle(desk, auth, "recommendations") is False
    status, _headers, _body = desk.post_json(
        "/memory/add", {"text": "Quarterly pricing review due December 1."}, auth
    )
    assert status == 201
    recs = _recommendations(desk, auth)
    assert all(not r["title"].startswith("Quarterly") for r in recs)
    recommendation_cards = [
        card for card in desk.server.inbox.waiting()
        if (card.meta or {}).get("recommendation")
    ]
    assert len(recommendation_cards) == 2


def test_ledger_recommend_rows_hold_fact_ids_only(desk):
    auth = _auth(desk)
    _toggle(desk, auth, "sample_data")
    _harborlight(desk, auth)
    added = [
        entry for entry in desk.server.ledger.entries(limit=50)
        if entry.action == "recommend.added"
    ]
    assert {entry.detail["rule"] for entry in added} == {"deadline", "meeting-prep"}
    for entry in added:
        detail = entry.detail
        assert set(detail) == {"rule", "cites"}
        assert all(isinstance(i, int) for i in detail["cites"])
        assert "Harborlight" not in json.dumps(detail)
        assert "December 15" not in json.dumps(detail)