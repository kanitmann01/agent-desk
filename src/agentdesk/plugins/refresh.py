"""When a plugin's tile refreshes, and how that choice is honoured.

A wizard-built plugin names its update mode in its activation events: no
schedule or hook means "when the desk is opened", ``onSchedule:<cron>`` means a
clock, and ``onHook:<topic>`` means when the watched thing changes. This module
is the only place that reading happens, so the three modes cannot drift apart
between the card, the tick and the event hooks.

The store keeps one reading per plugin. A scheduled or change-driven tile is
answered from that stored reading, so opening the home screen never quietly
turns into a live read; only opening a "when I open the desk" tile does.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Callable

MODE_VIEW = "view"
MODE_CLOCK = "clock"
MODE_HOOK = "hook"

# The one thing a stored reading is: what the source last said, and when.
_STORED_FIELDS = ("status", "payload")


def update_mode(manifest: dict) -> tuple[str, str]:
    """The plugin's update mode and its value: (mode, cron or hook topic).

    No schedule or hook event is the view mode, which is also what every
    plugin installed before the wizard asked the question does.
    """
    events = manifest.get("activationEvents")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, str) and event.startswith("onSchedule:"):
                return MODE_CLOCK, event.split(":", 1)[1]
            if isinstance(event, str) and event.startswith("onHook:"):
                return MODE_HOOK, event.split(":", 1)[1]
    return MODE_VIEW, ""


def _cron_fields(expression: str) -> tuple[str, str, str, str, str] | None:
    """The five fields of a standard cron expression, or None if unusable."""
    parts = expression.split()
    if len(parts) != 5:
        return None
    return tuple(parts)  # type: ignore[return-value]


def _field_matches(field_text: str, value: int, low: int, high: int) -> bool:
    """Whether one cron field matches a value, for the forms the wizard emits.

    Only the forms the wizard can write are read: ``*``, a plain number, and a
    step (``*/15``). A richer expression is not guessed at; an unreadable cron
    simply never comes due, which is honest rather than firing at a wrong time.
    """
    if field_text == "*":
        return True
    if field_text.startswith("*/"):
        try:
            step = int(field_text[2:])
        except ValueError:
            return False
        return step > 0 and (value - low) % step == 0
    try:
        return int(field_text) == value
    except ValueError:
        return False


def is_due(expression: str, now: datetime) -> bool:
    """Whether this cron's most recent minute is the one now is in.

    The tick runs every minute and asks this once, so a match means "this is
    the minute the schedule named". A five-field cron compares minute, hour,
    day of month, month and day of week; day-of-week accepts 0 or 7 for Sunday.
    """
    fields = _cron_fields(expression)
    if fields is None:
        return False
    minute, hour, day, month, weekday = fields
    if not _field_matches(minute, now.minute, 0, 59):
        return False
    if not _field_matches(hour, now.hour, 0, 23):
        return False
    if not _field_matches(month, now.month, 1, 12):
        return False
    if day != "*" and not _field_matches(day, now.day, 1, 31):
        return False
    if weekday == "*":
        return True
    # Python's Monday-is-0 becomes cron's Sunday-is-0.
    sunday_zero = (now.weekday() + 1) % 7
    return (_field_matches(weekday, sunday_zero, 0, 6)
            or (weekday == "7" and sunday_zero == 0))


def was_due_since(expression: str, since: datetime, now: datetime) -> bool:
    """Whether any minute in (since, now] matched the schedule.

    A machine asleep past its hour comes back and catches up once, instead of
    skipping the morning entirely, and without firing repeatedly for the
    minutes it missed.
    """
    cursor = since.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while cursor <= now:
        if is_due(expression, cursor):
            return True
        cursor += timedelta(minutes=1)
    return False


@dataclass
class Reading:
    """One stored read: the status half of a card and its payload."""

    status: dict = field(default_factory=dict)
    payload: dict | None = None
    as_of: str = ""

    def fingerprint(self) -> str:
        """A digest of the reading's content, for change detection.

        The timestamp is excluded on purpose: two reads of unchanged data must
        compare equal, or every poll would look like a change.
        """
        body = json.dumps({"status": self.status, "payload": self.payload},
                          sort_keys=True, default=str)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class ReadingStore:
    """The last reading per plugin, in memory, keyed by plugin id.

    Memory is the right scope: a reading describes a file or a mailbox at a
    moment, and a restart re-reads. Persisting it would let a card show a
    value older than the process that produced it.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        """Hold an optional clock so a test can place readings in time."""
        self._readings: dict[str, Reading] = {}
        self._lock = threading.Lock()
        self._clock = clock or datetime.now

    def get(self, plugin_id: str) -> Reading | None:
        """The stored reading for a plugin, or None when it has never read."""
        with self._lock:
            return self._readings.get(plugin_id)

    def put(self, plugin_id: str, status: dict, payload: dict | None) -> Reading:
        """Store a reading and return it."""
        reading = Reading(status=dict(status), payload=payload,
                          as_of=self._clock().isoformat(timespec="seconds"))
        with self._lock:
            self._readings[plugin_id] = reading
        return reading

    def clear(self, plugin_id: str) -> None:
        """Forget a plugin's reading, for a detach or an uninstall."""
        with self._lock:
            self._readings.pop(plugin_id, None)

    def replace_if_changed(self, plugin_id: str, status: dict,
                           payload: dict | None) -> bool:
        """Store a fresh reading only when it differs from the stored one.

        Returns whether it was stored, so a hook that read the source anyway
        can tell the card it has nothing new without writing.
        """
        candidate = Reading(status=dict(status), payload=payload)
        with self._lock:
            previous = self._readings.get(plugin_id)
            if previous is not None and previous.fingerprint() == candidate.fingerprint():
                return False
            self._readings[plugin_id] = Reading(
                status=candidate.status, payload=candidate.payload,
                as_of=self._clock().isoformat(timespec="seconds"))
            return True


def reading_to_api(reading: Reading | None) -> dict | None:
    """A stored reading's JSON shape, or None when there is none."""
    return asdict(reading) if reading is not None else None
