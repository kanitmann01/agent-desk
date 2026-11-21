"""Calendar bridge tests: parsing, key-event picking, and the poll
state machine on fakes, a frozen clock, and an in-memory store.
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
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


# The day view (#64): today's facts for plugin cards, without any model
# call. The commitments card asks the bridge for a breakdown (cache
# first, model second); a plugin binding must never spend that call, so
# the day view is the same read minus the breakdown half.

def test_day_view_reads_today_without_any_model_call(tmp_path):
    calls: list[str] = []

    def llm(prompt):
        calls.append(prompt)
        return '{"subtasks": ["Prep"], "followups": []}'

    events = sample_events(TODAY) + [
        {
            "id": "evt-2",
            "subject": "Later sync",
            "start": TODAY.replace(hour=16).isoformat(),
            "end": TODAY.replace(hour=17).isoformat(),
        },
        {
            "id": "evt-3",
            "subject": "Tomorrow's thing",
            "start": (TODAY + timedelta(days=1)).replace(hour=10).isoformat(),
            "end": (TODAY + timedelta(days=1)).replace(hour=11).isoformat(),
        },
    ]
    bridge, _clock = make_bridge(tmp_path, event_doc(TODAY, events), TODAY, llm=llm)
    bridge.poll()
    assert len(calls) == 1  # the poll's own breakdown, nothing else

    view = bridge.day_view()

    assert len(calls) == 1  # the day view added no model call
    assert view["state"] == "healthy"
    assert view["cause"] == ""
    assert view["keyEvent"]["subject"] == "Q4 pipeline review"
    assert view["keyEvent"]["start"] == TODAY.replace(hour=14).isoformat()
    assert view["eventsToday"] == 2  # today's two; tomorrow is not today
    assert view["generatedAt"] == TODAY.isoformat()
    assert "breakdown" not in view  # not asked for, not paid for


def test_day_view_before_any_poll_is_the_empty_state(tmp_path):
    bridge, _clock = make_bridge(tmp_path, event_doc(TODAY, sample_events(TODAY)), TODAY)
    view = bridge.day_view()
    assert view["state"] == "empty"
    assert view["keyEvent"] is None
    assert view["eventsToday"] == 0
    assert view.get("generatedAt") is None


def test_day_view_on_a_clear_day_counts_nothing_ahead(tmp_path):
    over = [
        {
            "id": "evt-done",
            "subject": "Morning standup",
            "start": TODAY.replace(hour=7).isoformat(),
            "end": TODAY.replace(hour=8).isoformat(),
        }
    ]
    bridge, _clock = make_bridge(tmp_path, event_doc(TODAY, over), TODAY)
    assert bridge.poll()["state"] == "clear"
    view = bridge.day_view()
    assert view["state"] == "clear"
    assert view["keyEvent"] is None
    assert view["eventsToday"] == 1  # it happened today; that is still true


def test_poll_can_skip_the_breakdown_entirely(tmp_path):
    """The breakdown-free poll (#75 review): reads the file, refreshes
    the state, returns the status without ever touching the model, so a
    plugin card's re-test cannot spend an endpoint request. The built-in
    card's retest() keeps its breakdown: cache first, model second."""
    calls: list[str] = []

    def llm(prompt):
        calls.append(prompt)
        return '{"subtasks": ["Prep"], "followups": []}'

    bridge, _clock = make_bridge(tmp_path, event_doc(TODAY, sample_events(TODAY)),
                                 TODAY, llm=llm)
    status = bridge.poll(breakdown=False)
    assert calls == []  # no model call anywhere in the poll
    assert status["state"] == "healthy"
    assert status["keyEvent"]["subject"] == "Q4 pipeline review"
    assert status["breakdown"] is None  # not asked for, not paid for

    # The built-in re-test keeps its behaviour: breakdown attached, one
    # call spent (then cached).
    retested = bridge.retest()
    assert len(calls) == 1
    assert retested["breakdown"]["subtasks"] == ["Prep"]


def test_parse_breakdown_tolerates_fences_and_garbage():
    good = parse_breakdown('```json\n{"subtasks": ["a"], "followups": []}\n```')
    assert good["subtasks"] == ["a"]
    fallback = parse_breakdown("the model rambled in prose")
    assert fallback["subtasks"]  # generic, never empty


def _z(local_dt: datetime) -> str:
    """The UTC shape the sync flow writes: an instant, trailing Z."""
    return local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_z_timestamps_normalize_to_local_at_the_parse_boundary():
    doc = parse_calendar_document({
        "generatedAt": "2026-11-20T23:30:00Z",
        "events": [{
            "id": "early", "subject": "Early sync",
            "start": "2026-11-20T23:30:00Z", "end": "2026-11-21T00:30:00Z",
        }],
    })
    start = doc.events[0].start
    expected = datetime.fromisoformat("2026-11-20T23:30:00+00:00").astimezone()
    assert start == expected
    # Local, not whatever zone the file carried.
    assert start.utcoffset() == datetime.now().astimezone().utcoffset()


def test_early_and_late_utc_meetings_count_today_and_show_local_clock(tmp_path):
    """The audit's repro, machine-independent: the fixture's meaning is
    pinned in local clock times (00:30 and 23:30 today) while the file
    carries the UTC Z shape the sync flow actually writes."""
    import json as json_mod

    from agentdesk.server.commitments import render_commitments_widget

    now = datetime(2026, 11, 11, 1, 0, 0).astimezone()
    early = now.replace(hour=0, minute=30, second=0, microsecond=0)
    late = now.replace(hour=23, minute=30, second=0, microsecond=0)
    doc = json_mod.dumps({
        "generatedAt": _z(now),
        "events": [
            {"id": "early", "subject": "Early sync",
             "start": _z(early), "end": _z(early + timedelta(hours=1))},
            {"id": "late", "subject": "Late review",
             "start": _z(late), "end": _z(late + timedelta(minutes=30))},
        ],
    }).encode("utf-8")
    bridge, clock = make_bridge(tmp_path, doc, now)
    status = bridge.poll()
    assert status["state"] == "healthy"
    assert status["keyEvent"]["id"] == "early"
    shown = datetime.fromisoformat(status["keyEvent"]["start"]).strftime("%H:%M")
    assert shown == "00:30"  # the local clock time, not the file's UTC hour
    view = bridge.day_view()
    assert view["eventsToday"] == 2
    assert view["todayRows"][0]["secondary"] == "00:30"
    widget = render_commitments_widget(status, now)
    assert "00:30" in widget.body_html

    clock[0] = now.replace(hour=22, minute=0).timestamp()
    later = bridge.status()
    assert later["keyEvent"]["id"] == "late"
    assert datetime.fromisoformat(later["keyEvent"]["start"]).strftime("%H:%M") == "23:30"


def test_non_dict_events_are_unreadable_not_a_crash(tmp_path):
    """A torn flow write can put a non-dict entry in events; that is the
    unreadable amber state with a cause, never a 500 page."""
    import json as json_mod

    broken = json_mod.dumps({"generatedAt": _z(TODAY), "events": ["x"]}).encode("utf-8")
    with pytest.raises(CalendarUnreadable):
        parse_calendar_document(json_mod.loads(broken))
    bridge, _clock = make_bridge(tmp_path, broken, TODAY)
    status = bridge.poll()
    assert status["state"] == "unreadable"
    assert "calendar file" in status["cause"]


def test_a_fallback_breakdown_is_retried_on_the_next_poll(tmp_path):
    """One endpoint outage must not freeze the generic answer forever:
    the degraded breakdown is not cached, so the next poll or retest
    asks again and recovers when the endpoint returns."""
    answers = [RuntimeError("endpoint down"), '{"subtasks": ["Recovered"], "followups": []}']

    def llm(_prompt):
        outcome = answers.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    bridge, _clock = make_bridge(tmp_path, event_doc(TODAY, sample_events(TODAY)),
                                 TODAY, llm=llm)
    degraded = bridge.poll()
    assert degraded["breakdown"]["fallback"] is True
    recovered = bridge.retest()
    assert recovered["breakdown"]["subtasks"] == ["Recovered"]
    assert recovered["breakdown"]["fallback"] is False
    # And the real answer stays cached from here on.
    again = bridge.retest()
    assert again["breakdown"]["subtasks"] == ["Recovered"]


def test_a_renamed_meeting_gets_a_fresh_breakdown(tmp_path):
    """The cache key carries the subject, so a meeting renamed in the
    same slot is prepared for what it became, not what it was."""
    import json as json_mod

    def llm(prompt):
        if "Vendor negotiation" in prompt:
            return '{"subtasks": ["Prep the term sheet"], "followups": []}'
        return '{"subtasks": ["Prep the budget deck"], "followups": []}'

    slot = TODAY.replace(hour=14, minute=0, second=0, microsecond=0)

    def doc(subject: str) -> bytes:
        return json_mod.dumps({
            "generatedAt": TODAY.isoformat(),
            "events": [{
                "id": "evt-1", "subject": subject,
                "start": slot.isoformat(), "end": (slot + timedelta(hours=1)).isoformat(),
            }],
        }).encode("utf-8")

    data = {"bytes": doc("Budget review")}
    adapters = Adapters(
        read_calendar=lambda: ("calendar_sync.json", data["bytes"]),
        clock=lambda: TODAY.timestamp(),
    )
    bridge = CalendarBridge(
        sqlite3.connect(":memory:", check_same_thread=False), adapters, llm=llm)
    first = bridge.poll()
    assert first["breakdown"]["subtasks"] == ["Prep the budget deck"]
    data["bytes"] = doc("Vendor negotiation")
    renamed = bridge.retest()
    assert renamed["breakdown"]["subtasks"] == ["Prep the term sheet"]
