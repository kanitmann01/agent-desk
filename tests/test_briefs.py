"""Pre-meeting briefs: only when actionable, budget-respecting, and
traceable to app data. Frozen clock throughout.
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
from nexuusbot.calendar.store import save_breakdown
from nexuusbot.inbox.store import InboxStore

NOW = datetime(2026, 11, 11, 9, 0, 0).astimezone()
MEETING = NOW + timedelta(hours=1)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance_to(self, when: datetime) -> None:
        self.now = when.timestamp()


def calendar_doc() -> dict:
    return {
        "generatedAt": NOW.isoformat(),
        "events": [
            {
                "id": "evt-review",
                "subject": "Q4 pipeline review",
                "start": MEETING.isoformat(),
                "end": (MEETING + timedelta(hours=1)).isoformat(),
                "location": "Room Beaufort",
                "attendees": ["Meridian", "Marco"],
            }
        ],
    }


def make_env(meeting_doc: dict | None = calendar_doc()):
    clock = FakeClock(NOW)
    cal_conn = sqlite3.connect(":memory:", check_same_thread=False)

    def read_calendar():
        if meeting_doc is None:
            return None
        return "onedrive/calendar_sync.json", json.dumps(meeting_doc).encode("utf-8")

    from nexuusbot.calendar.watcher import Adapters, CalendarBridge

    bridge = CalendarBridge(
        cal_conn,
        Adapters(read_calendar=read_calendar, clock=clock),
        llm=lambda prompt: '{"subtasks": [], "followups": []}',
    )
    bridge.poll()
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    from nexuusbot.repetition.activity import ActivityLog

    activity = ActivityLog(sqlite3.connect(":memory:", check_same_thread=False), clock)
    return clock, bridge, inbox, activity


def test_brief_appears_for_a_meeting_with_related_open_work():
    clock, bridge, inbox, activity = make_env()
    # Marco owes numbers (follow-up chip) and an open commitment exists.
    save_breakdown(bridge.conn, "evt-review:2026", {
        "subtasks": ["Pull the regional numbers Marco asked for"],
        "followups": [{"text": "Send the updated deck to Marco", "deadline": "13:00"}],
    })
    from nexuusbot.briefs import generate_briefs

    created = generate_briefs(bridge, inbox, activity, clock)
    assert created == 1
    cards = [c for c in inbox.waiting() if c.kind == "brief"]
    assert len(cards) == 1
    brief = cards[0].to_json(clock())
    assert "Marco" in brief["body"]
    assert "Pull the regional numbers" in brief["body"]
    assert brief["meta"]["sources"] == ["calendar", "commitments", "research_history"]
    assert brief["windowHours"] is not None  # time-bound: nothing expires silently
    # One brief per meeting, ever.
    assert generate_briefs(bridge, inbox, activity, clock) == 0


def test_brief_cites_research_history_about_the_attendees():
    clock, bridge, inbox, activity = make_env()
    activity.record("research", "What is Meridian's pricing position?")
    from nexuusbot.briefs import generate_briefs

    generate_briefs(bridge, inbox, activity, clock)
    cards = [c for c in inbox.waiting() if c.kind == "brief"]
    assert cards and "Meridian's pricing" in cards[0].body


def test_meeting_with_nothing_to_say_produces_no_card():
    clock, bridge, inbox, activity = make_env()  # no breakdowns, no research
    from nexuusbot.briefs import generate_briefs

    assert generate_briefs(bridge, inbox, activity, clock) == 0
    assert [c for c in inbox.waiting() if c.kind == "brief"] == []


def test_brief_respects_the_interruption_budget():
    clock, bridge, inbox, activity = make_env()
    save_breakdown(bridge.conn, "evt-review:2026", {
        "subtasks": ["Pull the regional numbers Marco asked for"],
        "followups": [],
    })
    from nexuusbot.briefs import generate_briefs
    from nexuusbot.inbox.service import evaluate

    generate_briefs(bridge, inbox, activity, clock)
    evening = NOW.replace(hour=20)
    clock.advance_to(evening)
    tally = evaluate(inbox, evening)
    assert tally["notified"] == 0  # quiet hours: the brief waits like any card
    assert len(inbox.waiting()) == 1  # and is not lost


def test_accepting_a_brief_prevents_the_twin():
    # One brief per meeting, ever: an accepted card still counts, or every
    # "Got it" would mint a twin of the brief it answered and spend another
    # notification on it.
    clock, bridge, inbox, activity = make_env()
    save_breakdown(bridge.conn, "evt-review:2026", {
        "subtasks": ["Pull the regional numbers Marco asked for"],
        "followups": [],
    })
    from nexuusbot.briefs import generate_briefs

    assert generate_briefs(bridge, inbox, activity, clock) == 1
    card = next(c for c in inbox.waiting() if c.kind == "brief")
    inbox.accept(card.id)
    assert generate_briefs(bridge, inbox, activity, clock) == 0
    assert [c for c in inbox.waiting() if c.kind == "brief"] == []


def test_no_code_path_reads_mail():
    # The brief module's only inputs are the bridge, the inbox, the
    # activity log and a clock: there is no mail-shaped parameter to abuse.
    import inspect

    from nexuusbot import briefs

    params = inspect.signature(briefs.generate_briefs).parameters
    assert set(params) == {"bridge", "inbox", "activity", "clock", "lead_hours"}


def test_briefs_flow_through_the_running_server(tmp_path):
    clock = FakeClock(NOW)
    calendar_file = tmp_path / "calendar_sync.json"
    calendar_file.write_text(json.dumps(calendar_doc()), encoding="utf-8")

    from nexuusbot.calendar.watcher import Adapters, CalendarBridge
    from nexuusbot.repetition.activity import ActivityLog

    def read_calendar():
        return str(calendar_file), calendar_file.read_bytes()

    bridge = CalendarBridge(
        sqlite3.connect(":memory:", check_same_thread=False),
        Adapters(read_calendar=read_calendar, clock=clock),
        llm=lambda prompt: '{"subtasks": ["Confirm the spend figure with Finance"], "followups": []}',
    )
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    activity = ActivityLog(sqlite3.connect(":memory:", check_same_thread=False), clock)
    booted = server_harness.Booted(calendar=bridge, inbox_store=inbox, activity_log=activity)
    try:
        auth = booted.exchange()
        booted.post_json("/sources/calendar-bridge/retest", {}, auth)
        # The retest generates the brief (the breakdown exists from the poll).
        payload = json.loads(booted.request("GET", "/widgets/inbox", auth)[2])
        assert payload["waiting"] >= 1
        page = booted.request("GET", "/inbox", auth)[2].decode("utf-8")
        assert "Q4 pipeline review" in page
        assert "Before your 10:00" in page
    finally:
        bridge.stop_polling()
        booted.close()
