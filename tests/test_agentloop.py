"""The agent loop's primitives and its supervision (spec 016, ticket 04).

interval_due seeds on first sight and defers one interval; the run claim is
exclusive between two loops on one data folder and takes over a dead or
stale holder; a pass isolates a failing step, writes its audit rows, heals
the inbox on the startup desk check, never runs at agent_loop_minutes 0,
restarts a dead thread and joins on stop. No test sleeps longer than 0.2 s.
"""

import json
import os
import socket
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from agentdesk.agentloop import schedule
from agentdesk.agentloop import loop as loop_module
from agentdesk.agentloop.loop import (
    AgentLoop,
    LoopContext,
    Step,
    STEPS,
)
from agentdesk.assistant import audit as audit_store
from agentdesk.inbox.store import InboxStore
from agentdesk.ledger.store import Ledger
from agentdesk.settings import SettingsStore

NOW = 1700000000.0


def _settings(**values):
    """A real settings store, defaulted like the app then overridden."""
    store = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False),
                          lambda: NOW)
    for key, value in values.items():
        store.set(key, value)
    return store


def _audit_conn():
    """An in-memory audit store the loop's rows land in."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    audit_store.ensure_schema(conn)
    return conn


def _inbox_with_raw_row(tmp_path: Path) -> InboxStore:
    """A real inbox store holding one row written by a build this one can't read."""
    store = InboxStore(sqlite3.connect(tmp_path / "inbox.sqlite3",
                                       check_same_thread=False), lambda: NOW)
    store.conn.execute(
        "INSERT INTO cards (id, kind, origin, title, body, action_label,"
        " status, created_ts, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("raw-commitment", "commitment", "Written by another build",
         "A card this build cannot read", "", "", "waiting", NOW, "{}"),
    )
    store.conn.commit()
    return store


class FakeServer:
    """The loop's view of a server: settings, ledger, audit and collaborators."""

    def __init__(self, settings=None, ledger=None, inbox=None, audit=None,
                 excel=None, calendar=None, plugins=None):
        self.settings = settings
        self.ledger = ledger
        self.inbox = inbox
        self.audit_conn = audit
        self.excel = excel
        self.calendar = calendar
        self.plugins = plugins


def _wait_until(predicate, timeout: float = 5.0, step: float = 0.02) -> bool:
    """Poll a predicate with short sleeps until it holds or the deadline passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


# ---- schedule.interval_due ----------------------------------------------


def test_interval_seeds_then_defers():
    now = datetime(2026, 11, 21, 9, 0, 0)
    # First sight is not due; the value to store seeds now, deferring one interval.
    assert schedule.interval_due(None, 1.0, now) == (False, now.isoformat())
    # A stored time this build cannot parse is treated as first sight.
    assert schedule.interval_due("not a date", 1.0, now) == (False, now.isoformat())
    # Before the interval there is nothing to store.
    assert schedule.interval_due(now.isoformat(), 1.0,
                                 now + timedelta(minutes=59)) == (False, None)
    # At the interval it is due, and the value to store is the new time.
    later = now + timedelta(minutes=60)
    assert schedule.interval_due(now.isoformat(), 1.0, later) == (True, later.isoformat())
    # Zero hours is never due, whatever the stored time says.
    assert schedule.interval_due(now.isoformat(), 0.0,
                                 now + timedelta(days=3)) == (False, None)


# ---- schedule.claim_run / release_run -----------------------------------


def test_claim_is_exclusive_and_stale_is_taken(tmp_path):
    lock = tmp_path / "agentloop.lock"
    # A fresh claim is ours and holds our pid.
    assert schedule.claim_run(lock, now=NOW) is True
    held = json.loads(lock.read_text(encoding="utf-8"))
    assert held["pid"] > 0 and held["host"]
    # While the holder is alive, a second claim is refused.
    assert schedule.claim_run(lock, now=NOW + 1) is False
    # Past the stale threshold the claim is taken over.
    assert schedule.claim_run(lock, now=NOW + 3601) is True
    schedule.release_run(lock)
    assert not lock.exists()
    # Releasing a lock that is not there is fine.
    schedule.release_run(lock)
    assert schedule.claim_run(lock, now=NOW) is True
    schedule.release_run(lock)

    # A holder on this machine whose pid is gone is taken over immediately.
    lock.write_text(json.dumps({"pid": 999999999, "startTs": NOW,
                                "host": socket.gethostname()}),
                    encoding="utf-8")
    assert schedule.claim_run(lock, now=NOW + 1) is True
    schedule.release_run(lock)
    # A lock file this build cannot read counts as dead.
    lock.write_text("not json", encoding="utf-8")
    assert schedule.claim_run(lock, now=NOW + 1) is True
    schedule.release_run(lock)


def test_a_foreign_machines_claim_is_refused_until_stale(tmp_path):
    lock = tmp_path / "agentloop.lock"
    lock.write_text(json.dumps({"pid": 999999999, "startTs": NOW,
                                "host": "another-desk"}),
                    encoding="utf-8")
    # This machine's pid probe says nothing about another machine's
    # process, so the claim is respected while it is fresh.
    assert schedule.claim_run(lock, now=NOW + 1) is False
    # Staleness is the one rule that may take a foreign claim over.
    assert schedule.claim_run(lock, now=NOW + 3601) is True
    schedule.release_run(lock)


def test_claim_takeover_removes_only_the_content_it_judged_dead(monkeypatch, tmp_path):
    lock = tmp_path / "agentloop.lock"
    dead = json.dumps({"pid": 999999999, "startTs": NOW,
                       "host": socket.gethostname()})
    lock.write_text(dead, encoding="utf-8")
    successor = json.dumps({"pid": os.getpid(), "startTs": NOW + 5,
                            "host": socket.gethostname()})
    reads = []

    def racing_read(path):
        """The takeover's first read sees the dead claim; by its confirming
        second read another desk has already replaced it with a live one."""
        reads.append(1)
        return dead if len(reads) == 1 else successor

    monkeypatch.setattr(schedule, "_read_claim", racing_read)
    assert schedule.claim_run(lock, now=NOW + 1) is False
    # The takeover refused rather than unlink: the claim on disk (in the
    # real race, the successor's) was left exactly as it was.
    assert lock.read_text(encoding="utf-8") == dead


def test_release_never_deletes_a_successors_claim(tmp_path):
    lock = tmp_path / "agentloop.lock"
    assert schedule.claim_run(lock, now=NOW) is True
    # The pass overruns the stale threshold; a successor takes the slot.
    assert schedule.claim_run(lock, now=NOW + 3601) is True
    # The overrun pass finishing now must leave the successor's claim be.
    schedule.release_run(lock, start_ts=NOW)
    assert json.loads(lock.read_text(encoding="utf-8"))["startTs"] == NOW + 3601
    # The successor's own release still removes the file.
    schedule.release_run(lock, start_ts=NOW + 3601)
    assert not lock.exists()


# ---- the step registry ---------------------------------------------------


def test_the_built_in_steps_are_registered():
    # Deskcheck is registered by the loop module; the app appends the
    # ticket steps in import order (08, 09, then rank and update).
    assert [step.name for step in STEPS] == [
        "deskcheck", "learn-topics", "profile-review", "rank", "update"]


# ---- run_pass: order, isolation, audit -----------------------------------


def test_failing_step_isolated(monkeypatch, tmp_path):
    ran = []

    def make(name, enabled=None, raises=False):
        def run(ctx):
            ran.append(name)
            if raises:
                raise RuntimeError(f"{name} broke")
            return {"note": f"{name} ran"}
        return Step(name=name, enabled=enabled or (lambda settings: True), run=run)

    steps = [
        make("first"),
        make("broken", raises=True),
        make("skipped", enabled=lambda settings: False),
        make("last"),
    ]
    monkeypatch.setattr(loop_module, "STEPS", steps)
    audit = _audit_conn()
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=audit)
    loop = AgentLoop(server, clock=lambda: NOW, data_dir=tmp_path)

    results = loop.run_pass()

    # Registration order, the failing step recorded, the disabled step skipped.
    assert [row["name"] for row in results] == ["first", "broken", "last"]
    assert [row["ok"] for row in results] == [True, False, True]
    assert ran == ["first", "broken", "last"]
    assert all(isinstance(row["ms"], int) for row in results)

    rows = audit_store.entries(audit)
    passes = [row for row in rows if row["action"] == "agentloop.pass"]
    assert len(passes) == 1
    assert "first ok" in passes[0]["detail"]
    assert "broken failed" in passes[0]["detail"]
    failures = [row for row in rows if row["action"] == "agentloop.step-failed"]
    assert [row["target"] for row in failures] == ["broken"]

    # A full pass remembers its time and restarts the interval from it.
    status = loop.status()
    assert status["lastRunTs"] == NOW
    assert status["running"] is False
    stored = server.ledger.latch_value("loop:last_run_at")
    assert stored is not None
    aware_now = datetime.fromtimestamp(NOW).astimezone()
    assert schedule.interval_due(stored, 1.0, aware_now) == (False, None)


def test_a_step_whose_gate_raises_writes_its_audit_row(monkeypatch, tmp_path):
    def broken_gate(settings):
        raise RuntimeError("the gate broke")

    def never_runs(ctx):
        raise AssertionError("the step must not run when its gate raises")

    monkeypatch.setattr(loop_module, "STEPS",
                        [Step("gated", broken_gate, never_runs)])
    audit = _audit_conn()
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=audit)
    loop = AgentLoop(server, clock=lambda: NOW, data_dir=tmp_path)

    results = loop.run_pass()

    assert [row["name"] for row in results] == ["gated"]
    assert results[0]["ok"] is False
    assert "RuntimeError" in results[0]["note"]
    failures = [row for row in audit_store.entries(audit)
                if row["action"] == "agentloop.step-failed"]
    assert [row["target"] for row in failures] == ["gated"]


def test_two_loops_on_one_data_folder_run_one_pass_at_a_time(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def slow(ctx):
        entered.set()
        release.wait(2)
        return {}

    monkeypatch.setattr(loop_module, "STEPS", [Step("slow", lambda settings: True, slow)])
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=_audit_conn())
    first = AgentLoop(server, clock=lambda: NOW, data_dir=tmp_path)
    second = AgentLoop(server, clock=lambda: NOW, data_dir=tmp_path)

    outcome = {}

    def run_first():
        outcome["steps"] = first.run_pass()

    thread = threading.Thread(target=run_first)
    thread.start()
    try:
        assert _wait_until(entered.is_set)
        # While the first pass holds the claim, the second records the refusal.
        assert second.run_pass() == [{
            "name": "claim", "ok": False, "ms": 0,
            "note": "Another pass holds the run claim.",
        }]
    finally:
        release.set()
        thread.join(timeout=2)
    assert [row["ok"] for row in outcome["steps"]] == [True]


def test_input_hash_latch_skips_unchanged_input(tmp_path):
    ledger = Ledger(":memory:")
    settings = _settings()
    ctx = LoopContext(server=FakeServer(settings=settings, ledger=ledger),
                      ledger=ledger, settings=settings,
                      now=datetime(2026, 11, 21, 9, 0, 0))
    assert ctx.input_unchanged("deskcheck", {"a": 1}) is False
    ctx.remember_input("deskcheck", {"a": 1})
    assert ctx.input_unchanged("deskcheck", {"a": 1}) is True
    assert ctx.input_unchanged("deskcheck", {"a": 2}) is False
    # Key order does not matter: the latch holds canonical JSON's hash.
    ctx.remember_input("deskcheck", {"a": 1, "b": [2]})
    assert ctx.input_unchanged("deskcheck", {"b": [2], "a": 1}) is True
    # Another step has its own latch.
    assert ctx.input_unchanged("other", {"a": 1}) is False


# ---- the thread, the supervisor, stop ------------------------------------


def test_startup_deskcheck_heals(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    inbox = _inbox_with_raw_row(tmp_path)
    server = FakeServer(settings=_settings(), ledger=Ledger(tmp_path / "ledger.sqlite3"),
                        inbox=inbox, audit=_audit_conn())
    loop = AgentLoop(server, clock=lambda: NOW, startup_delay=0.02,
                     wake_seconds=30, data_dir=tmp_path)
    loop.start()
    try:
        assert _wait_until(
            lambda: inbox.unreadable() == []
            and any(row["action"] == "agentloop.pass"
                    and "deskcheck ok" in row["detail"]
                    for row in audit_store.entries(server.audit_conn)))
        assert server.ledger.entries()[0].action == "deskcheck.fixed"
        # The startup check is not a full pass: no interval time was stored.
        assert server.ledger.latch_value("loop:last_run_at") is None
        assert [row["name"] for row in loop.status()["lastSteps"]] == ["deskcheck"]
    finally:
        loop.stop()


def test_zero_disables(tmp_path):
    audit = _audit_conn()
    server = FakeServer(settings=_settings(agent_loop_minutes=0),
                        ledger=Ledger(":memory:"), audit=audit)
    loop = AgentLoop(server, clock=lambda: NOW, startup_delay=0.02,
                     wake_seconds=0.02, data_dir=tmp_path)
    loop.start()
    time.sleep(0.15)
    loop.stop()
    status = loop.status()
    assert status == {
        "enabled": False, "intervalMinutes": 0, "lastRunTs": None,
        "nextRunTs": None, "running": False, "lastSteps": [],
    }
    assert audit_store.entries(audit) == []


def test_the_first_full_pass_waits_for_the_interval(tmp_path):
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=_audit_conn())
    loop = AgentLoop(server, clock=lambda: NOW, startup_delay=0.02,
                     wake_seconds=0.02, data_dir=tmp_path)
    loop.start()
    try:
        time.sleep(0.15)
        status = loop.status()
        assert status["enabled"] is True
        assert status["intervalMinutes"] == 60
        # Only the startup desk check ran; the first full pass is a full interval out.
        assert [row["name"] for row in status["lastSteps"]] == ["deskcheck"]
        assert status["nextRunTs"] == pytest.approx(NOW + 3600, abs=5)
    finally:
        loop.stop()


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_supervisor_restarts_dead_thread(tmp_path):
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=_audit_conn())
    loop = AgentLoop(server, clock=lambda: NOW, startup_delay=0.02,
                     wake_seconds=0.02, data_dir=tmp_path)
    armed = threading.Event()
    armed.set()
    real_run_pass = loop.run_pass

    def exploding_run_pass(only=None):
        """Explode once out of the target, then behave: the thread dies, the
        supervisor should respawn it, and the respawn must not die too."""
        if armed.is_set():
            armed.clear()
            raise RuntimeError("the target broke")
        return real_run_pass(only)

    loop.run_pass = exploding_run_pass
    loop.start()
    try:
        assert _wait_until(lambda: loop._thread is not None and not loop._thread.is_alive())
        assert loop.restart_if_dead() is True
        assert _wait_until(lambda: loop._thread is not None and loop._thread.is_alive())
        # One respawn, not a second thread beside the first.
        assert loop.restart_if_dead() is False
        alive = [t for t in threading.enumerate() if t.name == "agent-loop"]
        assert len(alive) == 1
    finally:
        loop.stop()
    # Once stopping was asked, the supervisor leaves the loop down.
    assert loop.restart_if_dead() is False


def test_close_joins(tmp_path):
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=_audit_conn())
    loop = AgentLoop(server, clock=lambda: NOW, startup_delay=30,
                     wake_seconds=30, data_dir=tmp_path)
    loop.start()
    thread = loop._thread
    assert thread is not None and thread.is_alive()
    started = time.monotonic()
    loop.stop(timeout=2)
    assert time.monotonic() - started < 2
    assert not thread.is_alive()


def test_run_now_409_when_busy(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def slow(ctx):
        entered.set()
        release.wait(2)
        return {}

    monkeypatch.setattr(loop_module, "STEPS", [Step("slow", lambda settings: True, slow)])
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=_audit_conn())
    loop = AgentLoop(server, clock=lambda: NOW, data_dir=tmp_path)
    assert loop.run_now() is True
    try:
        assert _wait_until(lambda: loop.status()["running"] is True)
        assert loop.run_now() is False
    finally:
        release.set()
    assert _wait_until(lambda: loop.status()["running"] is False)
    # Free again, a new manual pass may start.
    assert loop.run_now() is True
    assert _wait_until(lambda: loop.status()["running"] is False)


def test_scheduled_tick_cannot_stomp_a_manual_pass(monkeypatch, tmp_path):
    """The P1 regression: one owner for the running flag.

    A due scheduled run_pass arriving while a manual pass runs must skip
    outright: it must not clear the manual pass's flag (which would make
    status lie and turn the next 409 into a 200), and it must not burn a
    claim refusal against its own process.
    """
    entered = threading.Event()
    release = threading.Event()

    def slow(ctx):
        entered.set()
        release.wait(2)
        return {}

    monkeypatch.setattr(loop_module, "STEPS", [Step("slow", lambda settings: True, slow)])
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=_audit_conn())
    loop = AgentLoop(server, clock=lambda: NOW, data_dir=tmp_path)
    assert loop.run_now() is True
    try:
        assert _wait_until(lambda: loop.status()["running"] is True)
        skipped = loop.run_pass()
        assert skipped == [{"name": "pass", "ok": False, "ms": 0,
                            "note": "Another pass is already running in this process."}]
        assert loop.status()["running"] is True
        assert loop.run_now() is False
    finally:
        release.set()
    assert _wait_until(lambda: loop.status()["running"] is False)
    # The skipped tick never recorded a claim refusal against its own
    # process: the only lastSteps are the manual pass's own.
    assert [row["name"] for row in loop.status()["lastSteps"]] == ["slow"]
    assert [row["ok"] for row in loop.status()["lastSteps"]] == [True]


def test_stop_joins_the_manual_pass_thread(monkeypatch, tmp_path):
    """The manual pass thread is tracked and joined before the stores close."""
    entered = threading.Event()
    release = threading.Event()

    def slow(ctx):
        entered.set()
        release.wait(2)
        return {}

    monkeypatch.setattr(loop_module, "STEPS", [Step("slow", lambda settings: True, slow)])
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=_audit_conn())
    loop = AgentLoop(server, clock=lambda: NOW, data_dir=tmp_path)
    assert loop.run_now() is True
    assert _wait_until(entered.is_set)
    started = time.monotonic()
    # The pass cannot finish yet, so stop waits out its bounded join and
    # returns without hanging.
    loop.stop(timeout=2)
    assert time.monotonic() - started < 3
    release.set()
    assert _wait_until(lambda: (loop._run_thread is not None
                                 and not loop._run_thread.is_alive()))
    assert loop.status()["running"] is False


def test_a_manual_pass_never_starts_after_stop(monkeypatch, tmp_path):
    """A run_now that loses the race with shutdown reserves the slot but
    runs nothing: the job sees the stop request and returns."""
    ran = []

    def quick(ctx):
        ran.append(1)
        return {}

    monkeypatch.setattr(loop_module, "STEPS",
                        [Step("quick", lambda settings: True, quick)])
    server = FakeServer(settings=_settings(), ledger=Ledger(":memory:"), audit=_audit_conn())
    loop = AgentLoop(server, clock=lambda: NOW, data_dir=tmp_path)
    loop.stop()
    assert loop.run_now() is True
    assert _wait_until(lambda: loop.status()["running"] is False)
    assert ran == []
