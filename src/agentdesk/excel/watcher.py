"""The excel-watch poll loop: register once, delta forever after.

Adapters carry every side effect (shadow copy, parse, clock) so the poll
logic, state transitions and stale marking run in tests against fakes and
a frozen clock, exactly like the probe's gates. Polling is a daemon timer
loop; tests drive poll() directly and never sleep.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agentdesk.excel import shadow as shadow_mod
from agentdesk.excel import store, xlsx
from agentdesk.excel.core import (
    STATE_FIRST_SNAPSHOT,
    STATE_HEALTHY,
    STATE_LOCKED,
    STATE_UNREADABLE,
    PollResult,
    WorkbookLocked,
    WorkbookUnreadable,
    compute_delta,
    row_hash,
)

LOG = logging.getLogger("agentdesk.excel")

DEFAULT_INTERVAL_S = 3600.0  # hourly, matching the widget's own footnote

# The status payload carries a bounded preview of the sheet so cards can
# map columns by header name without shipping the whole workbook to the
# browser. 50 rows x 12 columns is enough for a header row plus a month of
# rows, and small enough to cross a status endpoint on every view.
GRID_MAX_ROWS = 50
GRID_MAX_COLUMNS = 12


def _grid_cell(value):
    """One grid cell: a plain string or number, never a Python object."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    return str(value).strip()


@dataclass
class Adapters:
    """The side effects a poll needs; swap for fakes in tests."""

    copy_shadow: Callable[[str], Path]
    parse_workbook: Callable[[Path], list]
    clock: Callable[[], float]


def default_adapters() -> Adapters:
    return Adapters(
        copy_shadow=lambda path: shadow_mod.copy_to_shadow(path),
        parse_workbook=xlsx.parse_workbook_file,
        clock=time.time,
    )


class ExcelWatch:
    """One watched workbook: register, poll, retest, report status."""

    def __init__(
        self,
        conn,
        adapters: Adapters | None = None,
        interval_s: float = DEFAULT_INTERVAL_S,
        source: str = "excel-watch",
        audit_hook: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.conn = conn
        self.adapters = adapters if adapters is not None else default_adapters()
        self.interval_s = interval_s
        self.stale_after_s = max(2.0 * interval_s, 2.5 * 60.0 * 60.0)
        self._source = source
        self._path: str | None = None
        self._last_result: PollResult | None = None
        self._last_ok_ts: float | None = None
        self._last_rows: list = []
        self.audit_hook = audit_hook
        # Called with (workbook file name, header row, delta) after a poll
        # that found changed rows, outside the lock (the memory loop's
        # workbook channel). A failing hook never breaks the watch.
        self.change_hook: Callable[[str, list, object], None] | None = None
        self._stop = threading.Event()
        self._timer: threading.Timer | None = None
        # One sqlite connection shared by the poll thread and the request
        # threads: every use is serialized. An RLock because register,
        # retest and resume end up inside poll while holding it.
        self._lock = threading.RLock()
        store.ensure_schema(conn)

    @property
    def registered_path(self) -> str | None:
        return self._path

    def register(self, path: str) -> PollResult:
        """Point the watch at a workbook (the file picker's outcome)."""
        with self._lock:
            return self._register_locked(path)

    def _register_locked(self, path: str) -> PollResult:
        self._path = path
        # Persisted before the poll so a restart resumes this workbook
        # even when the first poll finds the file locked or unreadable.
        store.set_meta(self.conn, store.WORKBOOK_PATH_KEY, path)
        self._audit("excel.register", "ok")
        return self.poll()

    def poll(self) -> PollResult:
        """One poll: shadow copy, parse, diff against T-24h, snapshot."""
        with self._lock:
            result = self._poll_locked()
            header = list(self._last_rows[0]) if self._last_rows else []
            path = self._path
        self._notify_change(result, header, path)
        return result

    def _notify_change(self, result: PollResult, header: list, path: str | None) -> None:
        if self.change_hook is None or result.delta is None or result.delta.is_empty:
            return
        name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
        try:
            self.change_hook(name, header, result.delta)
        except Exception:  # noqa: BLE001 - the hook must never break the watch
            LOG.exception("change hook failed")

    def _poll_locked(self) -> PollResult:
        if self._path is None:
            raise RuntimeError("no workbook registered")
        ts = self.adapters.clock()
        try:
            shadow_path = self.adapters.copy_shadow(self._path)
            rows = self.adapters.parse_workbook(shadow_path)
        except WorkbookLocked:
            result = PollResult(
                STATE_LOCKED,
                cause=(
                    "Can't refresh: the workbook is open in Excel right now. "
                    "Changes will appear once the file is free."
                ),
            )
            self._audit("excel.poll", "blocked")
        except WorkbookUnreadable as exc:
            result = PollResult(
                STATE_UNREADABLE,
                cause=f"Can't read the workbook: {exc}. Check it is a valid .xlsx.",
            )
            self._audit("excel.poll", "error")
        else:
            reference = store.load_reference(self.conn, self._source, ts)
            if reference is None:
                result = PollResult(STATE_FIRST_SNAPSHOT, rows_seen=len(rows))
            else:
                result = PollResult(
                    STATE_HEALTHY,
                    delta=compute_delta(reference, rows),
                    rows_seen=len(rows),
                )
            store.save_snapshot(self.conn, self._source, ts, rows, row_hash)
            self._last_ok_ts = ts
            self._last_rows = rows
            self._audit("excel.poll", "ok")
        self._last_result = result
        return result

    def _audit(self, action: str, status: str) -> None:
        """Record a brokered touch when the audit hook is wired."""
        if self.audit_hook is None or self._path is None:
            return
        name = str(self._path).replace("\\", "/").rsplit("/", 1)[-1]
        try:
            self.audit_hook(action, name, status)
        except Exception:  # noqa: BLE001 - auditing must never break the watch
            LOG.exception("audit hook failed")

    def retest(self) -> PollResult:
        """The amber widget's button: one poll, right now."""
        return self.poll()

    def status(self) -> dict:
        """The widget payload: state, cause, delta, and the poll clock.

        Freshness presentation (status dot, stamp text) is the server's
        job; this reports the raw state and when the last good poll ran.
        """
        with self._lock:
            return self._status_locked()

    def _grid_locked(self) -> dict:
        """A bounded header + rows preview, columns mapped by name later."""
        if not self._last_rows:
            return {"columns": [], "rows": []}
        columns = [_grid_cell(cell) for cell in self._last_rows[0][:GRID_MAX_COLUMNS]]
        rows = [
            [_grid_cell(cell) for cell in row[:GRID_MAX_COLUMNS]]
            for row in self._last_rows[1:GRID_MAX_ROWS + 1]
        ]
        return {"columns": columns, "rows": rows}

    def _status_locked(self) -> dict:
        now = self.adapters.clock()
        result = self._last_result
        if result is None:
            return {
                "configured": False,
                "state": "not_configured",
                "cause": "",
                "delta": None,
                "rowsSeen": 0,
                "last_ok_ts": None,
            }
        state = result.state
        if state in (STATE_HEALTHY, STATE_FIRST_SNAPSHOT) and self._last_ok_ts is not None:
            if now - self._last_ok_ts > self.stale_after_s:
                state = "stale"
        return {
            "configured": True,
            "path": self._path,
            "state": state,
            "cause": result.cause,
            "delta": result.delta.to_json() if result.delta is not None else None,
            "rowsSeen": result.rows_seen,
            "examples": [list(r[:4]) for r in self._last_rows[:3]],
            "grid": self._grid_locked(),
            "last_ok_ts": self._last_ok_ts,
        }

    def resume(self) -> bool:
        """Watch the registered workbook again after a process restart.

        The path comes back from the store, one poll runs on a daemon
        thread so the first dashboard load shows the real state (startup
        itself never blocks on the read), and the interval loop continues
        as after a normal registration. False when nothing is registered.
        """
        with self._lock:
            if self._path is None:
                self._path = store.get_meta(self.conn, store.WORKBOOK_PATH_KEY)
            if self._path is None:
                return False
        # The threads start outside the lock: a poll must never wait for
        # it indirectly while the resumer still holds it.
        self.start_polling()
        threading.Thread(target=self._poll_quietly, daemon=True).start()
        return True

    def start_polling(self) -> None:
        """Poll every interval on a daemon timer until stop_polling()."""
        self.stop_polling()
        self._stop.clear()
        self._timer = threading.Timer(self.interval_s, self._poll_loop)
        self._timer.daemon = True
        self._timer.start()

    def _poll_quietly(self) -> None:
        """One poll that swallows failures: background threads must not crash."""
        try:
            self.poll()
        except Exception:  # noqa: BLE001 - the loop must survive any poll
            LOG.exception("excel poll failed")

    def _poll_loop(self) -> None:
        if self._stop.is_set():
            return
        self._poll_quietly()
        if not self._stop.is_set():
            self._timer = threading.Timer(self.interval_s, self._poll_loop)
            self._timer.daemon = True
            self._timer.start()

    def stop_polling(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
