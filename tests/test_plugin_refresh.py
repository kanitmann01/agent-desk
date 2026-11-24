"""The three update modes, tested through the seam that runs them.

A plugin's tile refreshes when the desk is opened, on a clock, or when what it
watches changes. These tests pin the reading store's change detection, the cron
reading the tick depends on, and the one rule that keeps the modes apart: a
scheduled or change-driven tile is answered from its stored reading, so opening
the desk never quietly re-reads it.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agentdesk.plugins.refresh import (
    MODE_CLOCK,
    MODE_HOOK,
    MODE_VIEW,
    ReadingStore,
    is_due,
    update_mode,
    was_due_since,
)

FIXED = datetime(2026, 11, 24, 8, 0, 0)


def store() -> ReadingStore:
    return ReadingStore(clock=lambda: FIXED)


# ---- which mode a manifest asks for ---------------------------------------


def test_no_schedule_or_hook_is_the_view_mode():
    assert update_mode({"activationEvents": ["onWidget:sales"]}) == (MODE_VIEW, "")


def test_a_schedule_event_is_the_clock_mode():
    assert update_mode({"activationEvents": [
        "onWidget:sales", "onSchedule:0 8 * * *"]}) == (MODE_CLOCK, "0 8 * * *")


def test_a_hook_event_is_the_change_mode():
    assert update_mode({"activationEvents": [
        "onWidget:mail", "onHook:mail"]}) == (MODE_HOOK, "mail")


def test_a_manifest_with_no_events_is_the_view_mode():
    assert update_mode({}) == (MODE_VIEW, "")


# ---- reading a cron -------------------------------------------------------


def test_a_morning_clock_is_due_only_in_that_minute():
    assert is_due("0 8 * * *", datetime(2026, 11, 24, 8, 0, 30))
    assert not is_due("0 8 * * *", datetime(2026, 11, 24, 8, 1, 0))
    assert not is_due("0 8 * * *", datetime(2026, 11, 24, 7, 59, 0))


def test_every_hour_is_due_on_the_hour():
    assert is_due("0 * * * *", datetime(2026, 11, 24, 14, 0, 0))
    assert not is_due("0 * * * *", datetime(2026, 11, 24, 14, 5, 0))


def test_monday_morning_is_due_on_monday_only():
    monday = datetime(2026, 11, 23, 8, 0, 0)  # a Monday
    assert monday.weekday() == 0
    assert is_due("0 8 * * 1", monday)
    assert not is_due("0 8 * * 1", monday + timedelta(days=1))


def test_friday_afternoon_is_due_on_friday_only():
    friday = datetime(2026, 11, 27, 16, 0, 0)
    assert friday.weekday() == 4
    assert is_due("0 16 * * 5", friday)
    assert not is_due("0 16 * * 5", friday - timedelta(days=1))


def test_an_unreadable_cron_never_comes_due_rather_than_firing_wrongly():
    assert not is_due("not a cron", FIXED)
    assert not is_due("0 8 * *", FIXED)


def test_a_machine_asleep_past_its_hour_catches_up_once():
    """Coming back after the scheduled minute has passed still refreshes:
    skipping the morning because the laptop was shut is not honest."""
    last = datetime(2026, 11, 24, 7, 0, 0)
    now = datetime(2026, 11, 24, 9, 30, 0)

    assert was_due_since("0 8 * * *", last, now)
    # And nothing is due again in a later window that has no scheduled minute.
    assert not was_due_since("0 8 * * *", now, now + timedelta(minutes=10))


# ---- the reading store ----------------------------------------------------


def test_a_stored_reading_keeps_its_status_payload_and_time():
    readings = store()
    readings.put("sales", {"status": "fresh"}, {"elements": []})

    reading = readings.get("sales")
    assert reading.status == {"status": "fresh"}
    assert reading.payload == {"elements": []}
    assert reading.as_of == FIXED.isoformat(timespec="seconds")
    assert readings.get("missing") is None


def test_an_unchanged_reread_is_not_a_change():
    readings = store()
    readings.put("mail", {"status": "fresh"}, {"elements": [{"kind": "list"}]})

    assert readings.replace_if_changed("mail", {"status": "fresh"},
                                       {"elements": [{"kind": "list"}]}) is False
    # The stored reading and its time survive: nothing changed.
    assert readings.get("mail").as_of == FIXED.isoformat(timespec="seconds")


def test_a_changed_reread_replaces_the_stored_reading():
    readings = store()
    readings.put("mail", {"status": "fresh"}, {"elements": [{"kind": "list"}]})

    assert readings.replace_if_changed("mail", {"status": "fresh"},
                                       {"elements": [{"kind": "metric"}]}) is True
    assert readings.get("mail").payload["elements"][0]["kind"] == "metric"


def test_a_hook_can_compare_two_readings_for_a_change():
    first = store().put("page", {"status": "fresh"}, {"elements": []})
    second = store().put("page", {"status": "fresh"}, {"elements": []})
    third = store().put("page", {"status": "fresh"}, {"elements": [{"kind": "text"}]})

    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint() != third.fingerprint()


def test_clearing_forgets_a_plugin_only():
    readings = store()
    readings.put("a", {"status": "fresh"}, None)
    readings.put("b", {"status": "fresh"}, None)

    readings.clear("a")

    assert readings.get("a") is None
    assert readings.get("b") is not None
