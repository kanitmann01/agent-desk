"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, agent/curator.py and agent/curator_backup.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The curator (spec 016 sections 5.5 and 6.6): the weekly pass that moves
unused, unpinned, desk-made skills between active, stale and archived.

The transitions are Hermes apply_automatic_transitions with its defaults:
the anchor is last_used_ts, or created_ts when the skill has never run;
never-used skills younger than the stale window are left alone; a stale
skill whose anchor has moved inside the window is reactivated. The
snapshot discipline is Hermes curator_backup: snapshot FIRST, keep the
newest two, abort the whole run when the snapshot cannot be written, and
never delete a skills or skill_versions row.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from agentdesk.agentloop import schedule
from agentdesk.repetition.skills import (
    STATE_ACTIVE,
    STATE_ARCHIVED,
    STATE_STALE,
    SkillStore,
)

LOG = logging.getLogger(__name__)

DEFAULT_INTERVAL_HOURS = 24 * 7
STALE_AFTER_DAYS = 14
ARCHIVE_AFTER_DAYS = 30
KEEP_SNAPSHOTS = 2

# The interval clock's key in the skills database's curator_state table.
LAST_RUN_KEY = "last_run_at"

RecordFn = Callable[[dict, dict], str]


def due(skills: SkillStore, now: datetime) -> bool:
    """Whether the curator's interval has elapsed, seeding on first sight.

    The first sighting stores now and defers one full interval (Hermes
    should_run_now), so a fresh desk never mutates its skills on the
    first pass. The stored time lives in the curator_state table.
    """
    stored = skills.curator_state_value(LAST_RUN_KEY)
    ok, seed = schedule.interval_due(stored, DEFAULT_INTERVAL_HOURS, now)
    if seed is not None:
        skills.set_curator_state(LAST_RUN_KEY, seed)
    return ok


def run_curator(skills: SkillStore, snapshots_dir: Path,
                record: RecordFn, now: float) -> dict:
    """One curation pass over the desk-made, unpinned skills.

    Snapshots the agent skill rows and their versions to
    <snapshots_dir>/<utc-iso>.json FIRST, pruning to the newest
    KEEP_SNAPSHOTS; a snapshot that cannot be written raises before any
    skill is touched. Each transition is one record(before, detail) call
    (the caller's ledger entry, undo_kind skill-state). Returns Hermes'
    counts dict plus the snapshot's name. Never deletes a skills or
    skill_versions row, and resets the interval clock so a failed or
    empty run defers a full interval rather than retrying hourly.
    """
    skills.set_curator_state(
        LAST_RUN_KEY, datetime.fromtimestamp(now, timezone.utc).isoformat())
    snapshot_name = _snapshot(skills, snapshots_dir, now)
    counts = {"checked": 0, "markedStale": 0, "archived": 0,
              "reactivated": 0, "snapshot": snapshot_name}
    now_dt = datetime.fromtimestamp(now, timezone.utc)
    stale_cutoff = now_dt - timedelta(days=STALE_AFTER_DAYS)
    archive_cutoff = now_dt - timedelta(days=ARCHIVE_AFTER_DAYS)
    for row in skills.agent_skills():
        counts["checked"] += 1
        if row["pinned"]:
            continue
        # The anchor is last_used_ts, or created_ts for a never-run skill.
        anchor_ts = row["last_used_ts"] if row["last_used_ts"] is not None else row["created_ts"]
        anchor = datetime.fromtimestamp(anchor_ts, timezone.utc)
        current = row["state"]
        # use_count 0 is absence of evidence, not staleness: a never-used
        # skill younger than the stale window is untouched (Hermes' grace),
        # though one already stale comes back to active.
        if row["use_count"] == 0 and anchor > stale_cutoff:
            if current == STATE_STALE:
                _transition(skills, record, row, STATE_ACTIVE, "reactivated", counts)
            continue
        if anchor <= archive_cutoff and current != STATE_ARCHIVED:
            _transition(skills, record, row, STATE_ARCHIVED, "archived", counts)
        elif anchor <= stale_cutoff and current == STATE_ACTIVE:
            _transition(skills, record, row, STATE_STALE, "markedStale", counts)
        elif anchor > stale_cutoff and current == STATE_STALE:
            _transition(skills, record, row, STATE_ACTIVE, "reactivated", counts)
    return counts


def _transition(skills: SkillStore, record: RecordFn, row: dict,
                to_state: str, key: str, counts: dict) -> None:
    """Apply one state change and record it as the caller's undoable entry."""
    before = {"id": row["id"], "state": row["state"], "active": row["active"]}
    skills.set_state(row["id"], to_state)
    record(before, {"skill": row["name"], "to": to_state})
    counts[key] += 1


def _snapshot(skills: SkillStore, snapshots_dir: Path, now: float) -> str:
    """Write the pre-run snapshot and prune to the newest KEEP_SNAPSHOTS.

    The name is a UTC ISO stamp with filesystem-safe separators and
    microsecond precision, so names sort chronologically and two runs in
    the same second cannot clobber each other. Raises OSError when the
    snapshot cannot be written, before the caller changes anything.
    """
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime(
        "%Y-%m-%dT%H-%M-%S.%f") + "Z"
    name = f"{stamp}.json"
    payload = {"ts": now, **skills.snapshot_rows()}
    (snapshots_dir / name).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    keep = sorted(
        (p for p in snapshots_dir.glob("*.json") if p.name != name),
        key=lambda p: p.name, reverse=True,
    )[:max(0, KEEP_SNAPSHOTS - 1)]
    for old in snapshots_dir.glob("*.json"):
        if old.name != name and old not in keep:
            try:
                old.unlink()
            except OSError:
                LOG.warning("could not prune old skill snapshot %s", old)
    return name
