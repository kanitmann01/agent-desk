"""The agent loop over HTTP: status, run now, the dashboard payload, the
settings section, and the supervisor that restarts a dead thread on a
dashboard view (spec 016, ticket 04).

Every test boots the real server with its data folder pointed at a
throwaway directory, so the run claim never touches the real one. Slow
passes block on events rather than sleeps, and nothing waits longer than
the request timeout.
"""

import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import server_harness
from agentdesk.agentloop.loop import AgentLoop, Step
from agentdesk.assistant import audit as audit_store
from agentdesk.server import app as server_app
from agentdesk.settings import SettingsStore


def _wait_until(predicate, timeout: float = 5.0, step: float = 0.02) -> bool:
    """Poll a predicate with short sleeps until it holds or the deadline passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def _settings_store(**values):
    """A real settings store over an in-memory database, then overrides."""
    store = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False),
                          time.time)
    for key, value in values.items():
        store.set(key, value)
    return store


def _get_json(env, auth, path):
    status, _headers, body = env.request("GET", path, auth)
    assert status == 200, body
    return json.loads(body)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture
def auth(env):
    return env.exchange()


def test_status_route_reports_the_loop_shape(env, auth):
    payload = _get_json(env, auth, "/api/agent-loop")
    assert payload["enabled"] is True
    assert payload["intervalMinutes"] == 60
    assert payload["running"] is False
    assert payload["lastSteps"] == []
    assert payload["lastRunTs"] is None
    assert payload["nextRunTs"] > time.time() + 3500


def test_run_now_starts_and_a_second_call_is_409(env, auth, tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def slow(ctx):
        entered.set()
        release.wait(5)
        return {}

    # The boot loop is not started, so it runs no pass of its own; the
    # loop under test runs the chosen slow step instead of the registry.
    env.server.agent_loop = AgentLoop(env.server, data_dir=tmp_path / "claim",
                                      steps=[Step("slow", 100,
                                                  lambda settings: True, slow)])
    status, _headers, body = env.post_json("/api/agent-loop/run", {}, auth)
    assert status == 200, body
    assert json.loads(body) == {"started": True}
    try:
        assert _wait_until(lambda: env.server.agent_loop.status()["running"] is True)
        status, _headers, body = env.post_json("/api/agent-loop/run", {}, auth)
        assert status == 409
        assert json.loads(body) == {"error": "A pass is already running."}
    finally:
        release.set()
    assert _wait_until(lambda: env.server.agent_loop.status()["running"] is False)


def test_a_scheduled_tick_cannot_stomp_a_running_manual_pass(env, auth, tmp_path):
    """The P1 regression over HTTP: one owner for the running flag.

    A due tick's run_pass arriving while a manual pass runs skips outright,
    so status().running keeps telling the truth and the next Run now still
    answers 409 instead of silently starting a second pass.
    """
    entered = threading.Event()
    release = threading.Event()

    def slow(ctx):
        entered.set()
        release.wait(5)
        return {}

    # The boot loop is not started, so it runs no pass of its own; the
    # loop under test runs the chosen slow step instead of the registry.
    env.server.agent_loop = AgentLoop(env.server, data_dir=tmp_path / "claim",
                                      steps=[Step("slow", 100,
                                                  lambda settings: True, slow)])
    status, _headers, body = env.post_json("/api/agent-loop/run", {}, auth)
    assert status == 200, body
    try:
        assert _wait_until(lambda: env.server.agent_loop.status()["running"] is True)
        skipped = env.server.agent_loop.run_pass()
        assert skipped == [{"name": "pass", "ok": False, "ms": 0,
                            "note": "Another pass is already running in this process."}]
        assert env.server.agent_loop.status()["running"] is True
        status, _headers, body = env.post_json("/api/agent-loop/run", {}, auth)
        assert status == 409
        assert json.loads(body) == {"error": "A pass is already running."}
    finally:
        release.set()
    assert _wait_until(lambda: env.server.agent_loop.status()["running"] is False)


def test_dashboard_payload_carries_the_agent_loop_summary(env, auth):
    payload = _get_json(env, auth, "/api/dashboard")
    assert set(payload["agentLoop"]) == {"lastRunTs", "nextRunTs", "enabled"}
    assert payload["agentLoop"]["enabled"] is True
    assert payload["agentLoop"]["lastRunTs"] is None


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_dashboard_view_restarts_a_dead_thread(env, auth, tmp_path):
    fast = AgentLoop(env.server, startup_delay=0.02, wake_seconds=0.02,
                     data_dir=tmp_path / "claim")
    env.server.agent_loop = fast
    armed = threading.Event()
    armed.set()
    real_run_pass = fast.run_pass

    def exploding_run_pass(only=None):
        """Explode once out of the target, then behave: one death, one respawn."""
        if armed.is_set():
            armed.clear()
            raise RuntimeError("the target broke")
        return real_run_pass(only)

    fast.run_pass = exploding_run_pass
    server_app.start_background_polls(env.server)
    assert _wait_until(lambda: fast._thread is not None and not fast._thread.is_alive())
    # A dashboard view is the supervisor's heartbeat: the thread comes back,
    # exactly one of it.
    _get_json(env, auth, "/api/dashboard")
    assert _wait_until(lambda: fast._thread is not None and fast._thread.is_alive())
    alive = [t for t in threading.enumerate() if t.name == "agent-loop"]
    assert len(alive) == 1
    fast.stop()


def test_server_close_stops_the_loop_within_two_seconds(env, tmp_path):
    slow = AgentLoop(env.server, startup_delay=30, wake_seconds=30,
                     data_dir=tmp_path / "claim")
    env.server.agent_loop = slow
    server_app.start_background_polls(env.server)
    assert slow._thread is not None and slow._thread.is_alive()
    env.server.shutdown()
    started = time.monotonic()
    env.server.server_close()
    assert time.monotonic() - started < 2
    assert slow._thread is not None and not slow._thread.is_alive()


def test_a_pass_is_audited_and_listed_on_the_trail(env, auth):
    status, _headers, body = env.post_json("/api/agent-loop/run", {}, auth)
    assert status == 200, body
    assert _wait_until(lambda: env.server.agent_loop.status()["running"] is False)
    rows = audit_store.entries(env.server.audit_conn)
    assert any(row["action"] == "agentloop.pass" and "deskcheck" in row["detail"]
               for row in rows)

    page = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "agentloop.pass" in page
    # The trail's Kind column uses the spec's one-word label for the family.
    assert "<td>Agent</td>" in page

    touches = env.request("GET", "/what-this-touches", auth)[2].decode("utf-8")
    assert "agentloop.pass" in touches
    assert "agentloop.step-failed" in touches
    assert "agentloop.lock" in touches


def test_settings_agent_section_shows_the_loop(env, auth):
    status, _headers, body = env.post_json("/api/agent-loop/run", {}, auth)
    assert status == 200, body
    assert _wait_until(lambda: env.server.agent_loop.status()["running"] is False)

    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "id='agent'" in page
    assert "Check every" in page
    assert "data-setting='agent_loop_minutes'" in page
    assert 'action="/api/agent-loop/run"' in page
    assert "Run now" in page
    assert "Last pass" in page
    # The step table lists the one registered step with its outcome.
    assert "deskcheck" in page
    assert "The agent hasn't run yet" not in page


def test_settings_agent_section_empty_state_is_verbatim(env, auth):
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert ("The agent hasn't run yet. It runs about an hour after the app "
            "opens, or now.") in page


def test_settings_says_automatic_checks_are_off_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    booted = server_harness.Booted(
        settings_store=_settings_store(agent_loop_minutes=0))
    try:
        auth = booted.exchange()
        page = booted.request("GET", "/settings", auth)[2].decode("utf-8")
        assert "Automatic checks are off." in page
        payload = _get_json(booted, auth, "/api/agent-loop")
        assert payload["enabled"] is False
        assert payload["intervalMinutes"] == 0
        assert payload["nextRunTs"] is None
    finally:
        booted.close()


def test_zero_minutes_means_no_startup_check_and_no_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    booted = server_harness.Booted(
        settings_store=_settings_store(agent_loop_minutes=0))
    try:
        fast = AgentLoop(booted.server, startup_delay=0.02, wake_seconds=0.02,
                         data_dir=tmp_path / "claim")
        booted.server.agent_loop = fast
        server_app.start_background_polls(booted.server)
        time.sleep(0.15)
        fast.stop()
        assert fast.status()["lastSteps"] == []
        assert audit_store.entries(booted.server.audit_conn) == []
    finally:
        booted.close()


def test_settings_toggle_cycles_the_interval(env, auth):
    expected = [30, 240, 0, 60]
    seen = []
    for _ in range(4):
        status, _headers, body = env.post_json("/settings/toggle",
                                               {"key": "agent_loop_minutes"}, auth)
        assert status == 200, body
        seen.append(json.loads(body)["value"])
    assert seen == expected
    payload = _get_json(env, auth, "/api/agent-loop")
    assert payload["intervalMinutes"] == 60
