"""The desk check's automatic fixes, and the latch that stops a broken one.

Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, hermes_cli/cli_auto_maintenance.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

A fix runs only when its check is confident and the caller asked for fixing;
every fix records its change in the action ledger with the before state, so
Activity can undo it. A fix that fails is tried again only while the finding
still says the same thing: after three failures with the same detail the desk
stops calling it, until the detail changes and the count resets.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from agentdesk.deskcheck.core import (
    FIX_NONE,
    SEVERITY_ATTENTION,
    DeskContext,
    Finding,
)
from agentdesk.ledger.store import LedgerError

# Three failures in a row is the point where the desk stops retrying. Hermes
# used the same latched one-time repair idea for its automatic maintenance;
# here the latch is per finding and carries the finding's detail fingerprint.
MAX_FAILURES = 3

SET_ASIDE_DIR = "set-aside"

FixFn = Callable[[DeskContext, Finding], "str | None"]

FIXES: dict[str, FixFn] = {}


@dataclass(frozen=True)
class FixOutcome:
    """What one attempt at an automatic fix achieved."""

    fixed: bool
    entry: str | None = None
    cause: str | None = None


def fix(finding_id: str):
    """Register the automatic fix for one finding id."""

    def decorator(fn: FixFn) -> FixFn:
        """Remember fn as the fix for finding_id."""
        FIXES[finding_id] = fn
        return fn

    return decorator


def failure_latch_key(finding_id: str) -> str:
    """The ledger latch key holding one finding's consecutive failure state."""
    return f"fixfail:{finding_id}"


def detail_fingerprint(detail: dict) -> str:
    """A short stable hash of a finding's detail: what the fix was looking at.

    A changed detail means the problem changed, so the failure count for the
    old problem must not apply to it.
    """
    encoded = json.dumps(detail, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _read_state(ledger, key: str) -> dict | None:
    """The stored failure state for one fix, or None when there is none."""
    raw = ledger.latch_value(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _gave_up(count: int, cause: str) -> str:
    """The sentence shown once a fix has failed the allowed number of times."""
    return f"The desk tried to fix this {count} times; last cause: {cause}"


def apply_fix(ctx: DeskContext, finding: Finding) -> FixOutcome:
    """Run one finding's automatic fix, or explain why it did not run.

    Fails closed: without a ledger there is nothing to record before the
    change, so nothing runs. Three failures with the same detail stop the
    fourth call; a changed detail fingerprint starts the count over.
    """
    ledger = ctx.ledger
    if ledger is None:
        return FixOutcome(
            False, None,
            "The desk has no action ledger, so it cannot fix anything by itself.",
        )
    run = FIXES.get(finding.id)
    if run is None:
        return FixOutcome(False, None, "That finding has no automatic fix.")
    key = failure_latch_key(finding.id)
    state = _read_state(ledger, key)
    fingerprint = detail_fingerprint(finding.detail)
    same = state is not None and state.get("detail") == fingerprint
    count = int(state.get("count", 0)) if same else 0
    if same and count >= MAX_FAILURES:
        return FixOutcome(False, None, _gave_up(count, str(state.get("cause") or "")))
    try:
        entry = run(ctx, finding)
    except Exception as exc:  # noqa: BLE001 - the cause is shown to the user
        cause = f"{type(exc).__name__}: {exc}"
        ledger.latch(key, json.dumps({
            "count": count + 1,
            "detail": fingerprint,
            "cause": cause,
        }))
        return FixOutcome(False, None, cause)
    ledger.unlatch(key)
    return FixOutcome(True, entry, None)


def fix_failing_findings(ctx: DeskContext) -> list[Finding]:
    """One finding for every fix that has failed the allowed number of times."""
    if ctx.ledger is None:
        return []
    findings = []
    for finding_id in FIXES:
        state = _read_state(ctx.ledger, failure_latch_key(finding_id))
        if not state:
            continue
        count = int(state.get("count", 0))
        if count < MAX_FAILURES:
            continue
        cause = _gave_up(count, str(state.get("cause") or ""))
        findings.append(Finding(
            id=f"fix-failing:{finding_id}",
            title="A fix keeps failing",
            cause=cause,
            severity=SEVERITY_ATTENTION,
            confident=False,
            fix=FIX_NONE,
            fix_label="",
            detail={"finding": finding_id, "count": count},
        ))
    return findings


def _fsync_dir(folder: Path) -> None:
    """Flush the folder entry too, so a new file's name survives a crash."""
    try:
        descriptor = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@fix("inbox-unreadable-rows")
def _fix_inbox_rows(ctx: DeskContext, finding: Finding) -> str | None:
    """Set unreadable inbox rows aside in a file, then remove them.

    The order is the promise: the file is written and fsynced, then the
    ledger entry captures the raw rows (which is what Undo re-inserts), and
    only then do the rows leave the database. A capture that fails leaves the
    rows in place, so a fix that cannot be undone never happens.
    """
    rows = ctx.inbox.unreadable() if ctx.inbox is not None else []
    if not rows:
        return None
    if ctx.data_dir is None:
        raise RuntimeError("no data folder to write the set-aside file into")
    folder = Path(ctx.data_dir) / SET_ASIDE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = int((ctx.clock or time.time)())
    path = folder / f"inbox-{stamp}.json"
    payload = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    with open(path, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_dir(folder)
    row_ids = [row["id"] for row in rows]
    try:
        entry = ctx.ledger.record(
            actor="desk",
            action="deskcheck.fixed",
            subject="inbox-unreadable-rows",
            why=(f"Set aside {len(rows)} inbox row(s) this version cannot read; "
                 "the file is in the set-aside folder."),
            undo_kind="inbox-rows",
            before=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
            detail={"finding": finding.id, "count": len(rows),
                    "ids": row_ids, "file": str(path)},
        )
    except LedgerError:
        raise
    ctx.inbox.delete_rows(row_ids)
    return entry.id


@fix("sample-not-wired")
def _fix_sample_wiring(ctx: DeskContext, finding: Finding) -> str | None:
    """Point the workbook and calendar at the sample files, undoably."""
    from agentdesk.server import demo_data

    if ctx.settings is None:
        raise RuntimeError("settings are not available")
    server = SimpleNamespace(settings=ctx.settings, excel=ctx.excel,
                             calendar=ctx.calendar)
    before = demo_data.wire_sample_sources(server, data_dir=ctx.data_dir)
    if before is None:
        return None
    try:
        entry = ctx.ledger.record(
            actor="desk",
            action="deskcheck.fixed",
            subject="sample-not-wired",
            why=("Sample data was on but the sample files were not attached, "
                 "so the desk attached them."),
            undo_kind="wiring",
            before=json.dumps(before, sort_keys=True).encode("utf-8"),
            detail={"finding": finding.id},
        )
    except Exception:
        demo_data.unwire_sample_sources(server, data_dir=ctx.data_dir)
        raise
    return entry.id
