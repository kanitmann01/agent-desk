"""Calendar bridge tests: parsing, key-event picking, and the poll
state machine on fakes, a frozen clock, and an in-memory store.
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.calendar import store
from agentdesk.calendar.breakdown import parse_breakdown
from agentdesk.calendar.core import (
    CalendarUnreadable,
    parse_calendar_document,
    pick_key_event,
)
from agentdesk.calendar.watcher import Adapters, CalendarBridge

TODAY = datetime(2026, 11, 11, 9, 0, 0).astimezone()


def event_doc(now: datetime, events: list[dict]) -> bytes:
    import json

    return json.dumps({"generatedAt": now.isoformat(), "events": events}).encode("utf-8")


def make_bridge(tmp_path, file_bytes: bytes | None, now: datetime, llm=None):
    clock = [now.timestamp()]
    adapters = Adapters(
        read_calendar=lambda: ("onedrive/agent-desk/calendar_sync.json", file_bytes)
        if file_bytes is not None
        else None,
        clock=lambda: clock[0],
    )
    bridge = CalendarBridge(sqlite3.connect(":memory:", check_same_thread=False), adapters, llm=llm)
    bridge.clock = clock
    return bridge, clock


def sample_events(now: datetime) -> list[dict]:
    lunch = now.replace(hour=14, minute=0, second=0, microsecond=0)
    return [
        {
            "id": "evt-1",
            "subject": "Q4 pipeline review",
            "start": lunch.isoformat(),
            "end": (lunch + timedelta(hours=1)).isoformat(),
            "location": "Room Beaufort",
            "attendees": 6,
        }
    ]


def test_parse_calendar_document_reads_flow_output():
    doc = parse_calendar_document(
        {
            "generatedAt": TODAY.isoformat(),
            "events": [
                {
                    "id": "evt-1",
                    "subject": "Q4 pipeline review",
                    "start": TODAY.replace(hour=14).isoformat(),
                    "end": TODAY.replace(hour=15).isoformat(),
                    "attendees": 6,
                }
            ],
        }
    )
    assert doc.events[0].subject == "Q4 pipeline review"
    assert doc.events[0].attendees == 6


def test_parse_rejects_documents_without_events():
    with pytest.raises(CalendarUnreadable):
        parse_calendar_document({"nope": True})


def test_pick_key_event_takes_the_earliest_still_ahead():
    events = [
        {"id": "a", "subject": "Morning standup", "start": TODAY.replace(hour=8).isoformat(), "end": TODAY.replace(hour=8, minute=30).isoformat()},
        {"id": "b", "subject": "Q4 review", "start": TODAY.replace(hour=14).isoformat(), "end": TODAY.replace(hour=15).isoformat()},
    ]
    doc = parse_calendar_document({"generatedAt": TODAY.isoformat(), "events": events})
    key = pick_key_event(doc.events, TODAY)
    assert key is not None and key.id == "b"  # 08:00 is over by 09:00


def test_pick_key_event_with_nothing_left_returns_none():
    events = [
        {"id": "a", "subject": "Over", "start": TODAY.replace(hour=7).isoformat(), "end": TODAY.replace(hour=8).isoformat()}
    ]
    doc = parse_calendar_document({"generatedAt": TODAY.isoformat(), "events": events})
    assert pick_key_event(doc.events, TODAY) is None


def test_poll_without_a_file_is_the_walkthrough_state(tmp_path):
    bridge, _clock = make_bridge(tmp_path, None, TODAY)
    status = bridge.poll()
    assert status["state"] == "empty"
    assert status["configured"] is True


def test_poll_picks_the_key_event_and_asks_the_model_once(tmp_path):
    calls = []
    doc = event_doc(TODAY, sample_events(TODAY))

    def llm(prompt):
        calls.append(prompt)
        return '{"subtasks": ["Read the agenda", "Prep two questions", "Decide the ask"], "followups": [{"text": "Send notes", "deadline": "16:00"}]}'

    bridge, _clock = make_bridge(tmp_path, doc, TODAY, llm=llm)
    status = bridge.poll()
    assert status["state"] == "healthy"
    assert status["keyEvent"]["subject"] == "Q4 pipeline review"
    assert status["breakdown"]["subtasks"][0] == "Read the agenda"
    assert status["breakdown"]["followups"][0]["deadline"] == "16:00"
    assert len(calls) == 1
    # A second poll reuses the cache: the model is not asked again.
    bridge.poll()
    assert len(calls) == 1


def test_model_failure_degrades_to_the_generic_breakdown(tmp_path):
    def broken(_prompt):
        raise RuntimeError("endpoint down")

    bridge, _clock = make_bridge(tmp_path, event_doc(TODAY, sample_events(TODAY)), TODAY, llm=broken)
    status = bridge.poll()
    assert status["state"] == "healthy"
    assert status["breakdown"]["subtasks"]  # still useful, never broken


def test_stale_calendar_data_is_marked_stale(tmp_path):
    old = TODAY - timedelta(hours=12)
    bridge, clock = make_bridge(tmp_path, event_doc(old, sample_events(old)), TODAY)
    status = bridge.poll()
    assert status["state"] == "stale"
    assert "stale" in status["cause"]


def test_broken_calendar_file_is_unreadable_not_a_crash(tmp_path):
    bridge, _clock = make_bridge(tmp_path, b"{not json", TODAY)
    status = bridge.poll()
    assert status["state"] == "unreadable"
    assert "calendar file" in status["cause"]


def test_first_detection_is_recorded_once(tmp_path):
    bridge, _clock = make_bridge(tmp_path, event_doc(TODAY, sample_events(TODAY)), TODAY)
    bridge.poll()
    first = store.get_flag(bridge.conn, "calendar_first_detected")
    assert first is not None
    bridge.poll()
    assert store.get_flag(bridge.conn, "calendar_first_detected") == first


def test_checkbox_state_persists_in_the_store(tmp_path):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store.ensure_schema(conn)
    store.set_check(conn, "evt-1", 0, True)
    store.set_check(conn, "evt-1", 1, False)
    assert store.get_checks(conn, "evt-1") == {0: True, 1: False}
    store.set_check(conn, "evt-1", 0, False)  # untick works
    assert store.get_checks(conn, "evt-1") == {0: False, 1: False}


def test_toggle_check_api_writes_through(tmp_path):
    bridge, _clock = make_bridge(tmp_path, event_doc(TODAY, sample_events(TODAY)), TODAY)
    bridge.poll()
    bridge.toggle_check("evt-1", 2, True)
    assert bridge.status()["checks"] == {"2": True}


def test_parse_breakdown_tolerates_fences_and_garbage():
    good = parse_breakdown('```json\n{"subtasks": ["a"], "followups": []}\n```')
    assert good["subtasks"] == ["a"]
    fallback = parse_breakdown("the model rambled in prose")
    assert fallback["subtasks"]  # generic, never empty
