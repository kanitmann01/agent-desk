"""One feeder pass: pick a collector, write its headers, record the truth.

The runner is the only place a pass happens. Every side effect is
injected (collectors, folder provider, clock, status path), so a test
never touches a real index. The cross-process claim from
agentdesk.agentloop.schedule holds the run slot, so two desks on one
data folder cannot collect and write at the same time. No module here
imports a platform, a subprocess, an HTTP client or the model client:
the platform branch is agentdesk.feeder.platform, and the collectors
that use it arrive in later tickets.
"""

import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from agentdesk.agentloop.schedule import claim_run, release_run
from agentdesk.feeder.contract import MANUAL_CAUSE, MANUAL_COLLECTOR_NAME, MailCollector
from agentdesk.feeder.writer import write_mail, write_status

LOG = logging.getLogger("agentdesk.feeder")

DEFAULT_WINDOW_DAYS = 14  # the settings choice's default, mail_feeder_days
DEFAULT_LIMIT = 100       # the export helper's cap, enough for one window

# The lastResult vocabulary the Settings card renders. "busy" means
# another pass holds the run lock, so nothing new ran and nothing changed.
RESULT_OK = "ok"
RESULT_ERROR = "error"
RESULT_UNAVAILABLE = "unavailable"
RESULT_BUSY = "busy"

DAY_S = 24 * 60 * 60

CLAIM_BUSY = "A feeder run is already in progress."
NO_FOLDER = (
    "No mail folder is configured, so the feeder has nowhere to write."
    " Choose the mail folder in Settings."
)


class OutlookFeeder:
    """One host-side feeder over a folder of exported mail headers."""

    def __init__(
        self,
        collectors: Sequence[MailCollector],
        folder_provider: Callable[[], str],
        status_path,
        clock: Callable[[], float] = time.time,
        *,
        platform: str = "",
        window_days: int = DEFAULT_WINDOW_DAYS,
        limit: int = DEFAULT_LIMIT,
        lock_path=None,
    ) -> None:
        """Wire the collectors and the paths for one feeder.

        collectors arrive in trust order. folder_provider is asked on
        every pass, so a folder chosen in Settings applies without a
        restart. platform is injected as a label for the status, which
        keeps the platform decision in agentdesk.feeder.platform. The
        lock lives beside the status file unless lock_path names it.
        """
        self.collectors = list(collectors)
        self.folder_provider = folder_provider
        self.status_path = Path(status_path)
        self.clock = clock
        self.platform = platform
        self.window_days = window_days
        self.limit = limit
        self.lock_path = (
            Path(lock_path) if lock_path is not None
            else self.status_path.with_suffix(".lock")
        )

    def run_once(self) -> dict:
        """Run one pass and return the status dict, never raising.

        The claim is taken before any collection, so an overlapping call
        returns "busy" without touching the folder or the status file.
        Every other outcome is persisted atomically and returned: "ok"
        with the written count and the coverage window, "unavailable"
        with the manual Save as sentence, or "error" with a plain cause.
        """
        now = self.clock()
        try:
            claimed = claim_run(self.lock_path, now=now)
        except OSError as exc:
            return self._record(
                RESULT_ERROR, "", None, 0,
                f"The feeder could not claim its run lock: {exc}.",
            )
        if not claimed:
            return self._status(RESULT_BUSY, "", None, 0, CLAIM_BUSY)
        try:
            return self._run_claimed(now)
        except Exception:  # noqa: BLE001 - a feeder pass must never reach the caller
            LOG.exception("feeder pass failed unexpectedly")
            return self._record(
                RESULT_ERROR, "", now, 0, "The feeder pass failed unexpectedly.",
            )
        finally:
            release_run(self.lock_path, start_ts=now)

    def _run_claimed(self, now: float) -> dict:
        """The pass itself; the caller already holds the run claim."""
        folder_text = str(self.folder_provider() or "").strip()
        if not folder_text:
            return self._record(RESULT_ERROR, "", now, 0, NO_FOLDER)
        collector = self._first_available()
        if collector is None:
            return self._record(
                RESULT_UNAVAILABLE, MANUAL_COLLECTOR_NAME, now, 0, MANUAL_CAUSE,
            )
        since = datetime.fromtimestamp(now - self.window_days * DAY_S, tz=timezone.utc)
        try:
            messages = collector.collect(since, self.limit)
            written = write_mail(
                messages, Path(folder_text), now=now, window_days=self.window_days,
            )
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            detail = str(exc).strip() or exc.__class__.__name__
            LOG.warning("feeder collector %s failed", collector.name, exc_info=True)
            return self._record(
                RESULT_ERROR, collector.name, now, 0,
                f"The {collector.name} collector could not finish: {detail}.",
            )
        return self._record(RESULT_OK, collector.name, now, written, "", messages)

    def _first_available(self) -> MailCollector | None:
        """The first collector that says it can run, or None.

        A collector whose availability check itself raises is treated as
        unavailable: the next one is asked, so one broken probe cannot
        stop the whole feeder.
        """
        for collector in self.collectors:
            try:
                available, _cause = collector.available()
            except Exception:  # noqa: BLE001 - one broken probe, not a failed pass
                LOG.warning(
                    "feeder collector %s could not report availability",
                    getattr(collector, "name", "?"), exc_info=True,
                )
                continue
            if available:
                return collector
        return None

    def _record(self, result: str, collector: str, last_run_ts: float | None,
                written: int, error: str, messages=()) -> dict:
        """Build the status, persist it atomically, and return it.

        A status write that fails is logged, not raised: the pass's own
        outcome is still the honest answer for this call.
        """
        status = self._status(result, collector, last_run_ts, written, error, messages)
        try:
            write_status(status, self.status_path)
        except OSError as exc:
            LOG.warning("feeder status could not be written: %s", exc)
        return status

    def _status(self, result: str, collector: str, last_run_ts: float | None,
                written: int, error: str, messages=()) -> dict:
        """The one status shape: what ran, when, how it ended, how much landed.

        The coverage window is the dated first and last record the pass
        collected. A record with no readable date does not widen it, and
        an empty pass leaves both ends None rather than claiming a window
        it never saw.
        """
        dated = [m.date_ts for m in messages if m.date_ts > 0]
        return {
            "collector": collector,
            "platform": self.platform,
            "lastRunTs": last_run_ts,
            "lastResult": result,
            "lastError": error,
            "written": written,
            "coverageFromTs": min(dated) if dated else None,
            "coverageToTs": max(dated) if dated else None,
        }
