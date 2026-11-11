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
    ) -> None:
        self.conn = conn
        self.adapters = adapters if adapters is not None else default_adapters()
        self.interval_s = interval_s
        self.stale_after_s = max(2.0 * interval_s, 2.5 * 60.0 * 60.0)
        self._source = source
        self._path: str | None = None
        self._last_result: PollResult | None = None
        self._last_ok_ts: float | None = None
        self._stop = threading.Event()
        self._timer: threading.Timer | None = None
        store.ensure_schema(conn)

    @property
    def registered_path(self) -> str | None:
        return self._path

    def register(self, path: str) -> PollResult:
        """Point the watch at a workbook (the file picker's outcome)."""
        self._path = path
        return self.poll()

    def poll(self) -> PollResult:
        """One poll: shadow copy, parse, diff against T-24h, snapshot."""
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
        except WorkbookUnreadable as exc:
            result = PollResult(
                STATE_UNREADABLE,
                cause=f"Can't read the workbook: {exc}. Check it is a valid .xlsx.",
            )
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
        self._last_result = result
        return result

    def retest(self) -> PollResult:
        """The amber widget's button: one poll, right now."""
        return self.poll()

    def status(self) -> dict:
        """The widget payload: state, cause, delta, and the poll clock.

        Freshness presentation (status dot, stamp text) is the server's
        job; this reports the raw state and when the last good poll ran.
        """
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
            "last_ok_ts": self._last_ok_ts,
        }

    def start_polling(self) -> None:
        """Poll every interval on a daemon timer until stop_polling()."""
        self.stop_polling()
        self._stop.clear()
        self._timer = threading.Timer(self.interval_s, self._poll_loop)
        self._timer.daemon = True
        self._timer.start()

    def _poll_loop(self) -> None:
        if self._stop.is_set():
            return
        try:
            self.poll()
        except Exception:  # noqa: BLE001 - the loop must survive any poll
            LOG.exception("excel poll failed")
        if not self._stop.is_set():
            self._timer = threading.Timer(self.interval_s, self._poll_loop)
            self._timer.daemon = True
            self._timer.start()

    def stop_polling(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
