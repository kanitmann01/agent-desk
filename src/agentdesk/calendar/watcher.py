"""The calendar bridge watcher: read the synced file, show today's plan.

Adapters carry the side effects (file read, clock, model call) so the
state machine runs in tests against fixtures and a frozen clock. One
poll cycle: read the folder, parse, pick the key event, attach the
breakdown (cache first, model second, generic fallback last).
"""

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from agentdesk.calendar import store
from agentdesk.calendar.breakdown import (
    breakdown_prompt,
    env_llm_adapter,
    generic_breakdown,
    parse_breakdown,
)
from agentdesk.calendar.core import (
    DEFAULT_STALE_S,
    CalendarUnreadable,
    parse_calendar_document,
    pick_key_event,
)

LOG = logging.getLogger("agentdesk.calendar")

# Bridge states, one plain-language story each.
STATE_HEALTHY = "healthy"      # key commitment + breakdown on the card
STATE_CLEAR = "clear"          # file is fresh, nothing left today
STATE_EMPTY = "empty"          # no calendar file yet: the walkthrough state
STATE_STALE = "stale"          # file too old: stale + refresh path
STATE_UNREADABLE = "unreadable"  # file exists but is broken

FIRST_DETECTED_FLAG = "calendar_first_detected"

# The day view is a render payload, so every list it carries is bounded:
# a card shows a day, a fortnight and a week of load, not the whole file.
MAX_TODAY_ROWS = 20
MAX_UPCOMING = 10
WEEK_DAYS = 14
WORK_WEEK_DAYS = 7
MAX_PREP_ITEMS = 6


def _event_title(event) -> str:
    """A real event with an empty subject is a busy slot."""
    return str(event.subject or "Busy")


def _event_meta(event) -> str:
    """Attendees when the file names a count, otherwise the location."""
    if event.attendees:
        plural = "s" if event.attendees != 1 else ""
        return f"{event.attendees} attendee{plural}"
    return str(event.location or "")


@dataclass
class Adapters:
    """The side effects a poll needs; swap for fakes in tests."""

    read_calendar: Callable[[], "tuple[str, bytes] | None"]
    clock: Callable[[], float]


def default_calendar_candidates() -> "list[Path]":
    """Every place the synced calendar file is looked for, in order.

    AGENTDESK_CALENDAR_FILE overrides the whole list. Otherwise the
    Windows shapes come first (the plain OneDrive folder, then any
    'OneDrive - Company' folder at the home root), then the macOS sync
    roots, which mount as ~/Library/CloudStorage/OneDrive-<tenant>; the
    glob means the exact tenant suffix never matters. The server's
    walkthrough hint reuses this list so what it shows is what it reads.
    """
    env_path = os.environ.get("AGENTDESK_CALENDAR_FILE")
    if env_path:
        return [Path(env_path)]
    home = Path.home()
    candidates = [home / "OneDrive" / "agent-desk" / "calendar_sync.json"]
    candidates += sorted(home.glob("OneDrive*/agent-desk/calendar_sync.json"))
    candidates += sorted(home.glob("Library/CloudStorage/OneDrive*/agent-desk/calendar_sync.json"))
    return candidates


def default_read_calendar():
    """Read the synced calendar file from the OneDrive folder.

    Tries every candidate from default_calendar_candidates in order and
    reads the first one that exists.
    """
    for candidate in default_calendar_candidates():
        try:
            if candidate.is_file():
                return str(candidate), candidate.read_bytes()
        except OSError:  # mid-sync read: try the next candidate
            continue
    return None


def read_explicit_calendar(path_text: str):
    """Read one named file, or None when it is absent or unreadable."""
    path = Path(path_text)
    try:
        if path.is_file():
            return str(path), path.read_bytes()
    except OSError:  # mid-sync read: treat as not found this poll
        return None
    return None


def default_adapters() -> Adapters:
    """Build the adapters used outside tests: the real calendar reader and the
    system clock.
    """
    return Adapters(read_calendar=default_read_calendar, clock=time.time)


def _now_from_clock(clock: Callable[[], float]) -> datetime:
    """Return the adapter clock's current time in the machine's local time zone."""
    return datetime.fromtimestamp(clock()).astimezone()


class CalendarBridge:
    """One watched calendar file; poll reads it, the widget shows today."""

    def __init__(
        self,
        conn,
        adapters: Adapters | None = None,
        llm: Callable[[str], str] | None = None,
        stale_s: float = DEFAULT_STALE_S,
        audit_hook: Callable[[str, str, str], None] | None = None,
    ) -> None:
        """Bind the bridge to a connection, its adapters and the LLM, and create the
        tables it needs.

        Whenever adapters or an LLM are omitted, the production ones are built: the
        SwiftBar folder reader, the system clock and the env-configured adapter. The
        lock is re-entrant on purpose, because poll, status and retest call each other
        while holding it.
        """
        self.conn = conn
        self.adapters = adapters if adapters is not None else default_adapters()
        self.llm = llm if llm is not None else env_llm_adapter()
        self.stale_s = stale_s
        self.audit_hook = audit_hook
        self._source_path: str | None = None
        self._last_read_ts: float | None = None
        self._state = STATE_EMPTY
        self._cause = ""
        self._document = None
        store.ensure_schema(conn)
        # One sqlite connection shared by the poll thread, the request
        # threads and the settings routes: every use is serialized. An
        # RLock because poll, status and retest call one another while
        # holding it.
        self._lock = threading.RLock()

    def poll(self, breakdown: bool = True) -> dict:
        """One poll: read, parse, pick, attach. Returns the status dict.

        ``breakdown=False`` skips the breakdown entirely, so the poll
        makes no model call and reads no cache: surfaces that must never
        spend an endpoint request (a plugin card's re-test) poll this
        way. The built-in card keeps the default, breakdown cache first,
        model second.
        """
        with self._lock:
            return self._poll_locked(breakdown=breakdown)

    def _poll_locked(self, breakdown: bool = True) -> dict:
        """Re-read the calendar file and return the status that re-reading produced.

        Every read ends in exactly one of the empty, unreadable, stale, clear or
        healthy states and returns the payload describing it, so a caller never sees a
        half-updated bridge. Callers must hold the lock. Reading on the first healthy
        poll records when that happened, and each outcome is audited.
        """
        now_dt = _now_from_clock(self.adapters.clock)
        now = self.adapters.clock()
        found = None
        try:
            found = self._read_calendar()
        except OSError:
            found = None
        if found is None:
            self._state, self._cause = STATE_EMPTY, ""
            return self._status_locked(breakdown=breakdown)
        path, data = found
        self._source_path = path
        self._last_read_ts = now
        try:
            document = parse_calendar_document(json.loads(data))
        except (CalendarUnreadable, ValueError) as exc:
            self._state = STATE_UNREADABLE
            self._cause = f"Can't read the calendar file: {exc}"
            self._audit("calendar.poll", "error")
            return self._status_locked(breakdown=breakdown)
        self._document = document
        self._audit("calendar.ingest", "ok")
        if now - document.generated_at.timestamp() > self.stale_s:
            self._state = STATE_STALE
            self._cause = (
                "Calendar data is old, so it is shown as stale rather than "
                "current. Re-test after your flow has run, or walk through "
                "the setup again."
            )
            return self._status_locked(breakdown=breakdown)
        if store.get_flag(self.conn, FIRST_DETECTED_FLAG) is None:
            store.set_flag(self.conn, FIRST_DETECTED_FLAG, now_dt.isoformat())
        key = pick_key_event(document.events, now_dt)
        if key is None:
            self._state, self._cause = STATE_CLEAR, ""
            return self._status_locked(breakdown=breakdown)
        self._state, self._cause = STATE_HEALTHY, ""
        return self._status_locked(breakdown=breakdown)

    def explicit_path(self) -> str | None:
        """The file the user chose in the app, when one is stored."""
        with self._lock:
            return store.get_calendar_path(self.conn)

    def set_explicit_path(self, path: str) -> None:
        """Persist the user's file choice under the bridge's own lock."""
        with self._lock:
            store.set_calendar_path(self.conn, path)

    def clear_explicit_path(self) -> None:
        """Forget the user's file choice under the bridge's own lock."""
        with self._lock:
            store.clear_calendar_path(self.conn)

    def _read_calendar(self):
        """The read the poll uses, in precedence order: the explicitly
        chosen file first (exclusive while set, like the env override),
        then the adapter's discovery (env override, then candidates)."""
        explicit = self.explicit_path()
        if explicit:
            found = read_explicit_calendar(explicit)
            if found is not None:
                return found
        return self.adapters.read_calendar()

    def upcoming(self, now: datetime, within_hours: float = 1.0) -> list:
        """Events starting within the window, soonest first. None when no
        document has been read yet."""
        with self._lock:
            return self._upcoming_locked(now, within_hours)

    def _upcoming_locked(self, now: datetime, within_hours: float = 1.0) -> list:
        """Return the events that start between now and within_hours from now, earliest
        first.
        """
        if self._document is None:
            return []
        horizon = now + timedelta(hours=within_hours)
        return sorted(
            (e for e in self._document.events if now <= e.start <= horizon),
            key=lambda e: e.start,
        )

    def status(self) -> dict:
        """The widget payload: state, key event, breakdown, freshness."""
        with self._lock:
            return self._status_locked()

    def _status_locked(self, breakdown: bool = True) -> dict:
        """Render the current state as the payload the settings screen reads.

        A bridge that is not healthy, or that has no document, answers with state,
        cause and path only; everything else stays absent rather than misleading. The
        breakdown and per-event checks are gathered only when asked for, because
        producing a breakdown can cost an LLM call.
        """
        now_dt = _now_from_clock(self.adapters.clock)
        payload = {
            "configured": True,
            "state": self._state,
            "cause": self._cause,
            "path": self._source_path,
            "keyEvent": None,
            "breakdown": None,
            "checks": {},
            "firstDetected": store.get_flag(self.conn, FIRST_DETECTED_FLAG),
        }
        if self._state not in (STATE_HEALTHY,) or self._document is None:
            return payload
        payload["generatedAt"] = self._document.generated_at.isoformat()
        key = pick_key_event(self._document.events, now_dt)
        if key is None:
            payload["state"] = STATE_CLEAR
            return payload
        payload["keyEvent"] = {
            "id": key.id,
            "subject": key.subject,
            "start": key.start.isoformat(),
            "end": key.end.isoformat(),
            "location": key.location,
            "attendees": key.attendees,
        }
        if breakdown:
            payload["breakdown"] = self._breakdown_for(key)
            payload["checks"] = {str(k): v for k, v in store.get_checks(self.conn, key.id).items()}
        return payload

    def day_view(self) -> dict:
        """Today's calendar facts for surfaces that must not spend a
        model call: the same read as status() (state, cause, the key
        event, the file's own generatedAt) minus the breakdown, plus the
        day's rows, the next fortnight, the week's load and a prep
        checklist for the next event. Plugin bindings read this, so no
        plugin card can ever trigger a breakdown request; the
        commitments card keeps status(), breakdown and checkboxes
        included."""
        with self._lock:
            now_dt = _now_from_clock(self.adapters.clock)
            view = self._status_locked(breakdown=False)
            for key in ("configured", "path", "firstDetected",
                        "breakdown", "checks"):
                view.pop(key, None)
            events = (list(self._document.events)
                      if self._document is not None else [])
            today = sorted((event for event in events
                            if event.start.date() == now_dt.date()),
                           key=lambda event: event.start)
            view["eventsToday"] = len(today)
            view["todayRows"] = [
                {
                    "primary": _event_title(event),
                    "secondary": event.start.strftime("%H:%M"),
                    "meta": str(event.location or ""),
                }
                for event in today[:MAX_TODAY_ROWS]
            ]
            horizon = now_dt + timedelta(days=WEEK_DAYS)
            upcoming = sorted(
                (event for event in events
                 if event.end >= now_dt and event.start < horizon),
                key=lambda event: event.start,
            )[:MAX_UPCOMING]
            view["upcoming"] = [
                {
                    "time": event.start.isoformat(),
                    "title": _event_title(event),
                    "meta": _event_meta(event),
                }
                for event in upcoming
            ]
            week_points = []
            for offset in range(WEEK_DAYS):
                day = (now_dt + timedelta(days=offset)).date()
                week_points.append(sum(
                    1 for event in events if event.start.date() == day))
            view["weekPoints"] = week_points
            week_end = (now_dt + timedelta(days=WORK_WEEK_DAYS)).date()
            seconds = 0.0
            for event in events:
                if now_dt.date() <= event.start.date() < week_end:
                    seconds += max(
                        (event.end - event.start).total_seconds(), 0.0)
            view["weekHours"] = round(seconds / 3600.0, 1)
            nxt = next((event for event in sorted(events,
                                                  key=lambda event: event.start)
                        if event.start >= now_dt), None)
            names = ([str(name) for name in nxt.attendee_names
                      if str(name).strip()] if nxt is not None else [])
            view["items"] = [
                {
                    "text": f"Confirm with {name}",
                    "done": False,
                    "due": nxt.start.isoformat(),
                }
                for name in names[:MAX_PREP_ITEMS]
            ]
            return view

    def _todays_locked(self, now_dt: datetime) -> list:
        """Today's events, soonest first; empty before the first poll."""
        if self._document is None:
            return []
        return sorted(
            (e for e in self._document.events if e.start.date() == now_dt.date()),
            key=lambda e: e.start,
        )

    def _breakdown_for(self, key) -> dict:
        """Return the breakdown for one key event, generating it the first time.

        The cache key carries the event's start time and subject, so moving or
        renaming an event produces a fresh breakdown instead of the old one. A
        failing or unparsable LLM answer degrades to the generic breakdown
        rather than raising; a degraded answer is marked and never cached, so
        the next poll or retest asks again instead of freezing the fallback.
        """
        cache_key = f"{key.id}:{key.start.isoformat()}:{key.subject}"
        cached = store.cached_breakdown(self.conn, cache_key)
        if cached is not None:
            return cached
        try:
            breakdown = parse_breakdown(self.llm(breakdown_prompt(key)))
        except Exception:  # noqa: BLE001 - degrade, never break
            LOG.debug("breakdown fell back to generic", exc_info=True)
            breakdown = generic_breakdown()
        if not breakdown.get("fallback"):
            store.save_breakdown(self.conn, cache_key, breakdown)
        return breakdown

    def toggle_check(self, event_id: str, idx: int, checked: bool) -> None:
        """The checkbox API: persists across refreshes and restarts."""
        with self._lock:
            store.set_check(self.conn, event_id, idx, checked)

    def _audit(self, action: str, status: str) -> None:
        """Record a brokered touch when the audit hook is wired."""
        if self.audit_hook is None or self._source_path is None:
            return
        name = str(self._source_path).replace("\\", "/").rsplit("/", 1)[-1]
        try:
            self.audit_hook(action, name, status)
        except Exception:  # noqa: BLE001 - auditing must never break the bridge
            LOG.exception("audit hook failed")

    def retest(self) -> dict:
        """Re-read the calendar on demand and return the resulting status."""
        return self.poll()

    def start_polling(self, interval_s: float = 1800.0) -> None:
        """Poll on a daemon timer; the file syncs itself, this just keeps up."""
        self.stop_polling()
        self._stop = threading.Event()
        self._timer = threading.Timer(interval_s, self._loop, args=(interval_s,))
        self._timer.daemon = True
        self._timer.start()

    def _loop(self, interval_s: float) -> None:
        """Poll once, then schedule the next poll on a timer unless polling was stopped.

        A poll that raises is logged and swallowed: the loop is what keeps the bridge
        fresh, so nothing it does may end it.
        """
        if self._stop.is_set():
            return
        try:
            self.poll()
        except Exception:  # noqa: BLE001 - the loop survives anything
            LOG.exception("calendar poll failed")
        if not self._stop.is_set():
            self._timer = threading.Timer(interval_s, self._loop, args=(interval_s,))
            self._timer.daemon = True
            self._timer.start()

    def stop_polling(self) -> None:
        """Stop the background loop and cancel the timer it was waiting on."""
        stop = getattr(self, "_stop", None)
        if stop is not None:
            stop.set()
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.cancel()
            self._timer = None
