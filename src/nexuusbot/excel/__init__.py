"""Excel watch: what changed in the workbook over the last 24 hours.

Binding decisions baked in here (research A9.2 rule 3): the .xlsx carries
no cell timestamps, so the snapshot store is the clock: every poll
shadow-copies the file, parses the copy, hashes each row, and stores the
snapshot in SQLite; the delta is the row-hash diff against the T-24h
snapshot. The workbook is never parsed in place, never written.
"""

from nexuusbot.excel.core import (
    STATE_FIRST_SNAPSHOT,
    STATE_HEALTHY,
    STATE_LOCKED,
    STATE_STALE,
    STATE_UNREADABLE,
    Delta,
    PollResult,
    WorkbookLocked,
    WorkbookUnreadable,
    compute_delta,
    row_hash,
)
from nexuusbot.excel.watcher import Adapters, ExcelWatch, default_adapters

__all__ = [
    "STATE_FIRST_SNAPSHOT",
    "STATE_HEALTHY",
    "STATE_LOCKED",
    "STATE_STALE",
    "STATE_UNREADABLE",
    "Adapters",
    "Delta",
    "ExcelWatch",
    "PollResult",
    "WorkbookLocked",
    "WorkbookUnreadable",
    "compute_delta",
    "default_adapters",
    "row_hash",
]
