"""The curator (spec 016 ticket 10): transitions, snapshots, undo.

Ported from Hermes apply_automatic_transitions and curator_backup with an
injected clock: the anchor is last_used_ts else created_ts, never-used
skills younger than the stale window are untouched, snapshots land first
and keep two, a failed snapshot aborts with no changes, and no skills or
skill_versions row is ever deleted.
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.repetition import curator
from agentdesk.repetition.skills import SkillStore

NOW = datetime(2026, 11, 21, 9, 0, 0, tzinfo=timezone.utc)
NOW_TS = NOW.timestamp()
DAY = 24 * 3600.0


class SettableClock:
    def __init__(self, ts: float) -> None:
        self.ts = ts

    def __call__(self) -> float:
        return self.ts


def _store() -> tuple[SkillStore, SettableClock]:
    clock = SettableClock(NOW_TS)
    store = SkillStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    return store, clock


def _make_aged_skill(store: SkillStore, clock: SettableClock, *,
                     used_days_ago: float | None, created_days_ago: float,
                     created_by: str = "agent", pinned: bool = False,
                     state: str | None = None, name: str = "aged skill") -> int:
    """One skill created created_days_ago ago, optionally used used_days_ago ago."""
    clock.ts = NOW_TS - created_days_ago * DAY
    result = store.activate(name, "d", "p", created_by=created_by)
    skill_id = result["id"]
    clock.ts = NOW_TS
    if used_days_ago is not None:
        store.conn.execute(
            "UPDATE skills SET last_used_ts = ?, use_count = 1 WHERE id = ?",
            (NOW_TS - used_days_ago * DAY, skill_id),
        )
        store.conn.commit()
    if pinned:
        store.pin(skill_id, True)
    if state:
        store.set_state(skill_id, state)
    return skill_id


def _no_ledger(before: dict, detail: dict) -> str:
    """A record stub that never blocks: returns a fake entry id."""
    return "fake-entry"


def _counts(store: SkillStore) -> tuple[int, int]:
    skills = store.conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    versions = store.conn.execute("SELECT COUNT(*) FROM skill_versions").fetchone()[0]
    return skills, versions


@pytest.mark.parametrize(
    "used_days_ago,created_days_ago,before_state,expected_state,expected_active,expected_key",
    [
        # Unused for 15 days: active becomes stale, still running.
        (None, 15, "active", "stale", True, "markedStale"),
        # Unused for 31 days: archived and inactive.
        (None, 31, "active", "archived", False, "archived"),
        # A stale skill used 1 day ago is reactivated.
        (1.0, 40, "stale", "active", True, "reactivated"),
        # A stale skill whose last use is 20 days ago stays stale.
        (20.0, 40, "stale", "stale", True, None),
        # Never used, created 10 days ago: the grace leaves it alone.
        (None, 10, "active", "active", True, None),
        # Never used, created 10 days ago but already stale: back to active.
        (None, 10, "stale", "active", True, "reactivated"),
    ],
)
def test_curator_transitions(used_days_ago, created_days_ago, before_state,
                             expected_state, expected_active, expected_key, tmp_path):
    store, clock = _store()
    skill_id = _make_aged_skill(store, clock, used_days_ago=used_days_ago,
                                created_days_ago=created_days_ago,
                                state=None if before_state == "active" else before_state)
    seen: list[dict] = []

    def record(before: dict, detail: dict) -> str:
        seen.append({"before": dict(before), "detail": dict(detail)})
        return "entry-1"

    counts = curator.run_curator(store, tmp_path / "snaps", record, NOW_TS)
    skill = store.get(skill_id)
    assert skill["state"] == expected_state
    assert skill["active"] is expected_active
    assert counts["checked"] == 1
    if expected_key is None:
        assert seen == []
    else:
        assert len(seen) == 1
        assert seen[0]["before"]["state"] == before_state
        assert seen[0]["detail"]["to"] == expected_state
        assert counts[expected_key] == 1


def test_user_and_pinned_skills_are_untouched(tmp_path):
    store, clock = _store()
    user_id = _make_aged_skill(store, clock, used_days_ago=None,
                               created_days_ago=40, created_by="user",
                               name="a user skill")
    pinned_id = _make_aged_skill(store, clock, used_days_ago=None,
                                 created_days_ago=40, pinned=True,
                                 name="a pinned skill")
    counts = curator.run_curator(store, tmp_path / "snaps", _no_ledger, NOW_TS)
    # Only the agent-made rows are checked, the pinned one among them.
    assert counts["checked"] == 1
    assert counts["markedStale"] == 0
    assert counts["archived"] == 0
    assert counts["reactivated"] == 0
    for skill_id in (user_id, pinned_id):
        assert store.get(skill_id)["state"] == "active"
        assert store.get(skill_id)["active"] is True


def test_curator_snapshot_first_and_keep_two(tmp_path):
    store, clock = _store()
    _make_aged_skill(store, clock, used_days_ago=None, created_days_ago=1)
    snapshots = tmp_path / "snaps"
    for run in range(3):
        # Each run is a moment later so the snapshot ids differ.
        curator.run_curator(store, snapshots, _no_ledger, NOW_TS + run * 0.5)
        assert len(list(snapshots.glob("*.json"))) <= 2
    files = sorted(snapshots.glob("*.json"))
    assert len(files) == 2  # three runs, two kept
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["skills"] and payload["versions"]


def test_snapshot_written_before_any_change(tmp_path):
    store, clock = _store()
    skill_id = _make_aged_skill(store, clock, used_days_ago=None, created_days_ago=40)
    snapshots = tmp_path / "snaps"
    counts = curator.run_curator(store, snapshots, _no_ledger, NOW_TS)
    assert store.get(skill_id)["state"] == "archived"
    # The snapshot holds the pre-run state, proving it was written first.
    newest = sorted(snapshots.glob("*.json"))[-1]
    payload = json.loads(newest.read_text(encoding="utf-8"))
    row = next(r for r in payload["skills"] if r["id"] == skill_id)
    assert row["state"] == "active"
    assert counts["snapshot"] == newest.name


def test_a_failed_snapshot_aborts_with_no_changes(tmp_path):
    store, clock = _store()
    skill_id = _make_aged_skill(store, clock, used_days_ago=None, created_days_ago=40)
    before = _counts(store)
    # A file where the snapshots directory should be: mkdir fails.
    blocker = tmp_path / "snaps"
    blocker.write_text("not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        curator.run_curator(store, blocker, _no_ledger, NOW_TS)
    assert store.get(skill_id)["state"] == "active"
    assert _counts(store) == before


def test_curator_never_deletes(tmp_path):
    store, clock = _store()
    fresh = _make_aged_skill(store, clock, used_days_ago=None, created_days_ago=5,
                             name="fresh skill")
    _make_aged_skill(store, clock, used_days_ago=None, created_days_ago=20,
                     name="stale skill")
    _make_aged_skill(store, clock, used_days_ago=None, created_days_ago=40,
                     name="old skill")
    store.refine(fresh, "refined", "note")
    before = _counts(store)
    curator.run_curator(store, tmp_path / "snaps", _no_ledger, NOW_TS)
    # Rows are never deleted; a transition only adds its version row.
    assert _counts(store)[0] == before[0]
    assert _counts(store)[1] >= before[1]
    # Restoring a snapshot taken before the run also never deletes.
    snap = store.snapshot_rows()
    store.set_state(fresh, "archived")
    store.restore_rows(snap)
    assert _counts(store)[0] == before[0]
    assert _counts(store)[1] >= before[1]


def test_due_seeds_and_defers():
    store, _clock = _store()
    now = datetime(2026, 11, 21, 9, 0, 0, tzinfo=timezone.utc)
    # First sight: not due, and the seed is stored.
    assert curator.due(store, now) is False
    # A week less a day: still not due.
    assert curator.due(store, now + timedelta(days=6, hours=23)) is False
    # A week and a minute: due.
    assert curator.due(store, now + timedelta(days=7, minutes=1)) is True


def test_run_curator_updates_the_interval_state(tmp_path):
    store, _clock = _store()
    curator.run_curator(store, tmp_path / "snaps", _no_ledger, NOW_TS)
    stored = store.conn.execute(
        "SELECT v FROM curator_state WHERE k = 'last_run_at'").fetchone()
    assert stored is not None
    after = datetime.fromisoformat(stored[0])
    assert curator.due(store, after + timedelta(days=1)) is False
    assert curator.due(store, after + timedelta(days=7, minutes=1)) is True


def test_the_curator_step_records_ledger_entries_and_the_audit_row(tmp_path):
    """The loop step end to end: one undoable ledger entry per transition,
    one skill.curated audit row with the counts, and the switch off means
    no curator runs at all."""
    import server_harness
    from agentdesk.agentloop.loop import LoopContext
    from agentdesk.assistant import audit as audit_store
    from agentdesk.server.app import curator_step_run

    skills = SkillStore(sqlite3.connect(":memory:", check_same_thread=False),
                        lambda: NOW_TS)
    skills.activate("aged skill", "d", "p", created_by="agent")
    skills.conn.execute("UPDATE skills SET created_ts = ? WHERE id = 1",
                        (NOW_TS - 40 * DAY,))
    skills.conn.commit()
    booted = server_harness.Booted(
        skill_store=skills, skills_snapshots_dir=tmp_path / "snaps")
    try:
        server = booted.server
        # Seed the interval so the pass is due right now.
        server.skills.set_curator_state(
            "last_run_at",
            (NOW - timedelta(days=8)).isoformat())
        ctx = LoopContext(server=server, ledger=server.ledger,
                          settings=server.settings,
                          now=datetime.fromtimestamp(NOW_TS).astimezone())
        counts = curator_step_run(ctx)
        assert counts["archived"] == 1
        assert skills.get(1)["state"] == "archived"
        entry = next(e for e in server.ledger.entries(10)
                     if e.action == "skill.curated")
        assert entry.undo_kind == "skill-state"
        rows = [r for r in audit_store.entries(server.audit_conn, 10)
                if r["action"] == "skill.curated"]
        assert len(rows) == 1 and "archived" in rows[0]["detail"]

        # The undo restores the skill's earlier state.
        auth = booted.exchange()
        status, _h, _b = booted.post_json("/api/ledger/undo", {"id": entry.id}, auth)
        assert status == 200
        assert skills.get(1)["state"] == "active"
        assert skills.get(1)["active"] is True

        # The switch off means the step is not enabled at all, and the
        # interval the run reset means the next pass is a week away.
        from agentdesk.agentloop import loop as loop_module

        server.settings.set("skills_curator", False)
        curator_step = next(s for s in loop_module.STEPS if s.name == "curator")
        assert curator_step.enabled(server.settings) is False
        assert curator_step_run(ctx) == {}
        server.settings.set("skills_curator", True)
        assert curator_step.enabled(server.settings) is True
    finally:
        booted.close()
