"""Pure data model for the excel-watch: deltas, states, row hashing.

Nothing here touches files or the network, so the delta arithmetic and
state transitions are testable with plain lists and a frozen clock.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field

# Poll states, one plain-language story each in the UI.
STATE_HEALTHY = "healthy"            # fresh delta, nothing to recover
STATE_FIRST_SNAPSHOT = "first"       # baseline taken; deltas start next poll
STATE_STALE = "stale"                # data too old to show as current
STATE_LOCKED = "locked"              # workbook open in Excel: amber, re-test
STATE_UNREADABLE = "unreadable"      # not a workbook we can parse: amber

POLL_STATES = (
    STATE_HEALTHY,
    STATE_FIRST_SNAPSHOT,
    STATE_STALE,
    STATE_LOCKED,
    STATE_UNREADABLE,
)


class WorkbookLocked(Exception):
    """The workbook is exclusively open; the shadow copy could not be made."""


class WorkbookUnreadable(Exception):
    """The file exists but no table could be parsed out of it."""


def row_hash(row: list) -> str:
    """Stable hash of one row's values.

    Values are the parsed cell values (float for numbers, str for text).
    json.dumps gives a canonical serialization for both; sha256 keeps the
    hash stable across runs and machines.
    """
    canonical = json.dumps(row, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Delta:
    """The row-hash diff between two snapshots.

    A row edited in place shows up once in removed and once in added: the
    hash changed. added and removed carry the actual row values, oldest
    position first, so the UI can show examples without re-reading the file.
    """

    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    unchanged: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed

    def to_json(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "unchanged": self.unchanged,
        }


def compute_delta(old_rows: list, new_rows: list) -> Delta:
    """Multiset row-hash diff: order-preserving on both sides.

    Multiplicity matters: a row duplicated since the last snapshot is one
    added row, not zero.
    """
    old_counts = Counter(row_hash(r) for r in old_rows)
    new_counts = Counter(row_hash(r) for r in new_rows)
    common = old_counts & new_counts

    added: list = []
    pending = new_counts - common
    for row in new_rows:
        h = row_hash(row)
        if pending.get(h, 0) > 0:
            added.append(row)
            pending[h] -= 1

    removed: list = []
    pending = old_counts - common
    for row in old_rows:
        h = row_hash(row)
        if pending.get(h, 0) > 0:
            removed.append(row)
            pending[h] -= 1

    return Delta(added=added, removed=removed, unchanged=sum(common.values()))


@dataclass(frozen=True)
class PollResult:
    """The outcome of one poll: state, plain-language cause, and the delta."""

    state: str
    cause: str = ""
    delta: Delta | None = None
    rows_seen: int = 0

    def __post_init__(self) -> None:
        if self.state not in POLL_STATES:
            raise ValueError(f"unknown poll state: {self.state!r}")

    def to_json(self) -> dict:
        return {
            "state": self.state,
            "cause": self.cause,
            "delta": self.delta.to_json() if self.delta is not None else None,
            "rowsSeen": self.rows_seen,
        }
