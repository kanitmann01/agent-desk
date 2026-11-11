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


@dataclass
class Adapters:
    """The side effects a poll needs; swap for fakes in tests."""

    read_calendar: Callable[[], "tuple[str, bytes] | None"]
    clock: Callable[[], float]


def default_read_calendar():
    """Read the synced calendar file from the OneDrive folder.

    Both the plain OneDrive folder and the 'OneDrive - Company' shape are
    tried; the flow writes to agent-desk/calendar_sync.json under whichever
    exists. AGENTDESK_CALENDAR_FILE overrides the whole path.
    """
    env_path = os.environ.get("AGENTDESK_CALENDAR_FILE")
    if env_path:
        candidates = [Path(env_path)]
    else:
        home = Path.home()
        candidates = [home / "OneDrive" / "agent-desk" / "calendar_sync.json"]
        candidates += sorted(home.glob("OneDrive*/agent-desk/calendar_sync.json"))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate), candidate.read_bytes()
        except OSError:  # mid-sync read: try the next candidate
            continue
    return None


def default_adapters() -> Adapters:
    return Adapters(read_calendar=default_read_calendar, clock=time.time)


def _now_from_clock(clock: Callable[[], float]) -> datetime:
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

    def poll(self) -> dict:
        """One poll: read, parse, pick, attach. Returns the status dict."""
        now_dt = _now_from_clock(self.adapters.clock)
        now = self.adapters.clock()
        found = None
        try:
            found = self.adapters.read_calendar()
        except OSError:
            found = None
        if found is None:
            self._state, self._cause = STATE_EMPTY, ""
            return self.status()
        path, data = found
        self._source_path = path
        self._last_read_ts = now
        try:
            document = parse_calendar_document(json.loads(data))
        except (CalendarUnreadable, ValueError) as exc:
            self._state = STATE_UNREADABLE
            self._cause = f"Can't read the calendar file: {exc}"
            self._audit("calendar.poll", "error")
            return self.status()
        self._document = document
        self._audit("calendar.ingest", "ok")
        if now - document.generated_at.timestamp() > self.stale_s:
            self._state = STATE_STALE
            self._cause = (
                "Calendar data is old, so it is shown as stale rather than "
                "current. Re-test after your flow has run, or walk through "
                "the setup again."
            )
            return self.status()
        if store.get_flag(self.conn, FIRST_DETECTED_FLAG) is None:
            store.set_flag(self.conn, FIRST_DETECTED_FLAG, now_dt.isoformat())
        key = pick_key_event(document.events, now_dt)
        if key is None:
            self._state, self._cause = STATE_CLEAR, ""
            return self.status()
        self._state, self._cause = STATE_HEALTHY, ""
        return self.status()

    def upcoming(self, now: datetime, within_hours: float = 1.0) -> list:
        """Events starting within the window, soonest first. None when no
        document has been read yet."""
        if self._document is None:
            return []
        horizon = now + timedelta(hours=within_hours)
        return sorted(
            (e for e in self._document.events if now <= e.start <= horizon),
            key=lambda e: e.start,
        )

    def status(self) -> dict:
        """The widget payload: state, key event, breakdown, freshness."""
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
        breakdown = self._breakdown_for(key)
        payload["breakdown"] = breakdown
        payload["checks"] = {str(k): v for k, v in store.get_checks(self.conn, key.id).items()}
        return payload

    def _breakdown_for(self, key) -> dict:
        cache_key = f"{key.id}:{key.start.isoformat()}"
        cached = store.cached_breakdown(self.conn, cache_key)
        if cached is not None:
            return cached
        try:
            breakdown = parse_breakdown(self.llm(breakdown_prompt(key)))
        except Exception:  # noqa: BLE001 - degrade, never break
            LOG.debug("breakdown fell back to generic", exc_info=True)
            breakdown = generic_breakdown()
        store.save_breakdown(self.conn, cache_key, breakdown)
        return breakdown

    def toggle_check(self, event_id: str, idx: int, checked: bool) -> None:
        """The checkbox API: persists across refreshes and restarts."""
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
        return self.poll()

    def start_polling(self, interval_s: float = 1800.0) -> None:
        """Poll on a daemon timer; the file syncs itself, this just keeps up."""
        self.stop_polling()
        self._stop = threading.Event()
        self._timer = threading.Timer(interval_s, self._loop, args=(interval_s,))
        self._timer.daemon = True
        self._timer.start()

    def _loop(self, interval_s: float) -> None:
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
        stop = getattr(self, "_stop", None)
        if stop is not None:
            stop.set()
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.cancel()
            self._timer = None
