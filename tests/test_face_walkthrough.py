"""Unit tests for tools/face_walkthrough.py.

Playwright is never imported and no desk is started here. The boot is driven
against a stand-in for the server factory that records every call, and the
routes, checks, counts and exit codes are exercised with fake pages.
"""

from __future__ import annotations

import argparse
import inspect
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import face_walkthrough as face  # noqa: E402
import layout_audit as audit  # noqa: E402


def _args(**overrides):
    """A CLI namespace with the face walk's defaults."""
    values = {
        "out": "unused",
        "routes": "",
        "themes": ",".join(face.THEMES),
        "widths": face.DEFAULT_WIDTHS,
        "mock_delay_ms": face.DEFAULT_MOCK_DELAY_MS,
        "record_api": "",
        "sheet_only": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class _FakeRoute:
    """A route stand-in that records how the instrument resolved it."""

    def __init__(self, method, url):
        self.request = SimpleNamespace(method=method, url=url)
        self.calls = []

    def fallback(self):
        self.calls.append("fallback")

    def continue_(self):
        self.calls.append("continue")

    def abort(self):
        self.calls.append("abort")

    def fulfill(self, **kwargs):
        self.calls.append(("fulfill", kwargs))


class _GateResult:
    """The small immutable result shape the inert runners return."""

    def __init__(self, key, number, title, status, evidence=(), note=""):
        self.key = key
        self.number = number
        self.title = title
        self.status = status
        self.evidence = tuple(evidence)
        self.note = note


class _BootRecorder:
    """A stand-in for the server factory that records every call."""

    def __init__(self):
        self.create_calls = []
        self.base = "http://127.0.0.1:43123"

    def create_server(self, **kwargs):
        """Record the factory call and return a server that cannot listen."""
        self.create_calls.append(kwargs)

        class Server:
            port = 43123
            settings = None
            sessions = SimpleNamespace(bootstrap_token=lambda: "test-token")
            excel = calendar = mail = plugins = None

            def serve_forever(self):
                return None

            def shutdown(self):
                return None

            def server_close(self):
                return None

        return Server()


def _install_fake_agentdesk(monkeypatch, recorder):
    """Replace every agentdesk import the audit's boot makes."""
    agentdesk = types.ModuleType("agentdesk")
    agentdesk.__path__ = []
    server_package = types.ModuleType("agentdesk.server")
    server_package.__path__ = []
    server_app = types.ModuleType("agentdesk.server.app")
    server_app.create_server = recorder.create_server
    server_package.app = server_app
    keys_package = types.ModuleType("agentdesk.keys")
    keys_package.__path__ = []
    secrets = types.ModuleType("agentdesk.keys.secrets")

    class KeychainSecrets:
        def __init__(self, backend):
            self.backend = backend

    secrets.KeychainSecrets = KeychainSecrets
    probe_package = types.ModuleType("agentdesk.probe")
    probe_package.__path__ = []
    core = types.ModuleType("agentdesk.probe.core")
    core.GateResult = _GateResult
    core.UNKNOWN = "UNKNOWN"
    core.PASS = "PASS"
    core.FAIL = "FAIL"
    capabilities = types.ModuleType("agentdesk.capabilities")
    capabilities.GATES = (
        ("exec-user-space", 1, "User-space execution"),
        ("uv-tls-bootstrap", 2, "uv bootstrap under corporate TLS"),
        ("power-automate-flows", 3, "Power Automate personal cloud flows"),
        ("onedrive-sync", 4, "OneDrive sync root"),
        ("edr-identity", 5, "EDR / AV identity"),
        ("embeddings", 6, "Endpoint embeddings"),
    )
    for module in (agentdesk, server_package, server_app, keys_package, secrets,
                   probe_package, core, capabilities):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def test_the_only_boot_path_is_the_layout_audits_boot_function():
    """The instrument never calls the server factory and has one boot call."""
    source = inspect.getsource(face)
    assert source.count("audit._boot_desk(") == 1
    assert "create_server(" not in source
    assert "agentdesk.server" not in source
    assert "/capabilities/" not in source


def test_boot_passes_the_inert_gate_runners(monkeypatch, tmp_path):
    """The instrument's boot goes through the audit and injects every runner."""
    recorder = _BootRecorder()
    _install_fake_agentdesk(monkeypatch, recorder)
    desk = face._boot_isolated_desk("full", tmp_path / "desk")
    assert desk["base"] == recorder.base
    assert len(recorder.create_calls) == 1
    runners = recorder.create_calls[0].get("gate_runners")
    assert runners is not None
    assert set(runners) == {key for key, _number, _title in
                            sys.modules["agentdesk.capabilities"].GATES}
    assert {runner().status for runner in runners.values()} == {"UNKNOWN"}


def test_the_real_phase_installs_the_guard_before_the_first_navigation(
        monkeypatch, tmp_path):
    """The guard route is registered before the auth navigation."""
    plan = face.build_plan(_args())
    run = face.RunState(plan, tmp_path / "run")
    run.run_dir.mkdir(parents=True)
    events = []
    routes = []

    class Page:
        url = "http://127.0.0.1:43123/"

        def __init__(self):
            self.clock = SimpleNamespace(install=lambda **_kwargs: None,
                                         set_fixed_time=lambda *_args: None)

        def goto(self, _url, **_kwargs):
            events.append("goto")

    class Context:
        def new_page(self):
            events.append("new_page")
            return Page()

        def route(self, pattern, handler):
            events.append("route")
            routes.append((pattern, handler))

        def close(self):
            return None

    class Browser:
        version = "159.0.8154.6"

        def new_context(self, **_kwargs):
            return Context()

        def close(self):
            return None

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **_kwargs: Browser())

    monkeypatch.setattr(face, "_boot_isolated_desk", lambda *_args: {
        "base": "http://127.0.0.1:43123", "token": "t",
        "server": SimpleNamespace(), "thread": SimpleNamespace()})
    monkeypatch.setattr(face.audit, "_start_mock", lambda _delay=0: (
        SimpleNamespace(shutdown=lambda: None, server_close=lambda: None), 4321))
    monkeypatch.setattr(face.audit, "_pin_environment", lambda *_args: None)
    monkeypatch.setattr(face.audit, "_stop_desk", lambda _desk: [])
    monkeypatch.setattr(face, "_save_mock_connection", lambda *_args: None)
    monkeypatch.setattr(face.tempfile, "mkdtemp",
                        lambda **_kwargs: str(tmp_path / "desk"))
    face._run_real_phase(_args(), run, plan, Playwright())
    assert events.index("route") < events.index("goto")
    assert [pattern for pattern, _handler in routes] == [
        "**/*", "**/research", "**/api/marketplace/retest"]


def test_both_walk_routes_answer_or_hold_their_request():
    """Research fails with a 500 or passes; the retest is held or passes."""
    class Target:
        def __init__(self):
            self.routes = []

        def route(self, pattern, handler):
            self.routes.append((pattern, handler))

    config = face.RouteConfig()
    held = []
    target = Target()
    face._install_real_routes(target, config, held)
    research = target.routes[0][1]
    retest = target.routes[1][1]

    config.research = "fail"
    refused = _FakeRoute("POST", "http://127.0.0.1:43123/research")
    research(refused)
    assert refused.calls[0][0] == "fulfill"
    assert refused.calls[0][1]["status"] == 500
    assert face.RESEARCH_REFUSAL in refused.calls[0][1]["body"]

    config.research = "pass"
    passed = _FakeRoute("POST", "http://127.0.0.1:43123/research")
    research(passed)
    assert passed.calls == ["fallback"]

    config.retest = "hold"
    hold = _FakeRoute("POST", "http://127.0.0.1:43123/api/marketplace/retest")
    retest(hold)
    assert hold.calls == []
    assert held == [hold]

    config.retest = "pass"
    released = _FakeRoute("POST", "http://127.0.0.1:43123/api/marketplace/retest")
    retest(released)
    assert released.calls == ["fallback"]

    other = _FakeRoute("POST", "http://127.0.0.1:43123/assistant/ask")
    research(other)
    retest(other)
    assert other.calls == ["fallback", "fallback"]


def test_a_failed_check_is_still_photographed_and_the_run_continues(tmp_path):
    """One failed check does not stop the captures after it."""
    shots = [
        face.Shot(id="a", surface="rail", kind="rail", theme="unkey",
                  mood="idle", motion="normal", condition="fresh", width=1280,
                  state="", variant="page", file="photos/a.png"),
        face.Shot(id="b", surface="rail", kind="rail", theme="unkey",
                  mood="listening", motion="normal", condition="fresh",
                  width=1280, state="", variant="page", file="photos/b.png"),
        face.Shot(id="c", surface="rail", kind="rail", theme="unkey",
                  mood="done", motion="normal", condition="full", width=1280,
                  state="", variant="page", file="photos/c.png"),
    ]
    run = face.RunState(shots, tmp_path)
    checks = []
    painted = []

    def check(shot):
        checks.append(shot.id)
        return {"kind": "mood", "passed": shot.id != "a", "detail": "fake"}

    def shoot(_page, shot, run_dir):
        painted.append(shot.id)
        path = run_dir / shot.file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        return str(path)

    face._capture_group(None, shots, check, run, shoot=shoot)
    assert checks == ["a", "b", "c"]
    assert painted == ["a", "b", "c"]
    assert run.records["a"]["verdict"] == "failed"
    assert run.records["a"]["missing"] is False
    assert run.records["b"]["verdict"] == "passed"
    assert run.records["c"]["verdict"] == "passed"
    assert len(list(tmp_path.rglob("*.png"))) == 3


def test_the_plan_holds_every_shot_the_full_run_must_take():
    """A default plan has the 48 sheet, 42 rail and 21 surface photographs."""
    plan = face.build_plan(_args())
    by_surface = {}
    for shot in plan:
        by_surface[shot.surface] = by_surface.get(shot.surface, 0) + 1
    assert by_surface == {
        "review-sheet": 48, "rail": 42, "rail-collapsed": 3,
        "phone-strip": 6, "dialog-describe": 3, "dialog-tracker": 3,
        "server-inbox": 6,
    }
    assert len(plan) == 111
    assert {shot.mood for shot in plan if shot.mood} == set(face.MOODS)
    assert {shot.theme for shot in plan} == set(face.THEMES)
    assert {shot.motion for shot in plan} == set(face.MOTIONS)
    assert len([shot for shot in plan if shot.motion == "reduce"]) == 24


def test_the_sheet_only_plan_holds_no_real_app_shot():
    """Sheet-only mode plans the review sheet and no desk surface."""
    plan = face.build_plan(_args(sheet_only=True))
    assert {shot.surface for shot in plan} == {"review-sheet"}
    assert len(plan) == 48


def test_plan_filters_and_rejects_unsupported_values():
    """Routes select, and an unsupported theme, width or route is a named error."""
    sheet = face.build_plan(_args(routes="sheet"))
    assert {shot.surface for shot in sheet} == {"review-sheet"}
    unkey = face.build_plan(_args(themes="unkey"))
    assert {shot.theme for shot in unkey} == {"unkey"}
    with pytest.raises(face.FaceWalkError, match="no supported theme"):
        face.build_plan(_args(themes="bogus"))
    with pytest.raises(face.FaceWalkError, match="unsupported width"):
        face.build_plan(_args(widths="1024"))
    with pytest.raises(face.FaceWalkError, match="matches no planned"):
        face.build_plan(_args(routes="nomatch-anywhere"))


def test_counts_measure_the_folder_and_the_records(tmp_path):
    """Every METRIC count equals what the run folder holds."""
    plan = face.build_plan(_args())
    run = face.RunState(plan, tmp_path)
    for shot in plan:
        path = tmp_path / shot.file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        record = run.records[shot.id]
        record.update({"file": shot.file, "verdict": "passed", "missing": False,
                       "check": {"passed": True}})
    surfaces = {
        "review-sheet": {"observed": True, "face": True},
        "rail": {"observed": True, "face": True},
        "rail-collapsed": {"observed": True, "face": True},
        "phone-strip": {"observed": True, "face": False},
        "dialog-describe": {"observed": True, "face": False},
        "dialog-tracker": {"observed": True, "face": False},
        "server-inbox": {"observed": True, "face": False},
    }
    counts = face._counts(list(run.records.values()), tmp_path, surfaces)
    assert counts == {
        "moods": 8, "themes": 3, "surfaces": 7, "photos": 111,
        "reduced_motion": 24, "missing": 0, "failed": 0,
        "surfaces_without_face": 4,
    }
    assert face._metric_line(counts) == (
        "METRIC moods=8 themes=3 surfaces=7 photos=111 "
        "reduced-motion=24 missing=0")
    assert face._verdict_line(counts) == (
        "FACE-WALK PASS WITH 4 SURFACES WITHOUT A FACE")
    assert face._exit_code(counts, False) == 0


def test_missing_and_failed_counts_are_measured_not_planned(tmp_path):
    """A removed file is missing; a failed check is failed; the lines name them."""
    plan = face.build_plan(_args(routes="sheet"))
    run = face.RunState(plan, tmp_path)
    for index, shot in enumerate(plan):
        record = run.records[shot.id]
        if index == 8:
            continue
        path = tmp_path / shot.file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        record.update({"file": shot.file, "verdict": "passed", "missing": False,
                       "check": {"passed": True}})
    counts = face._counts(list(run.records.values()), tmp_path, {})
    assert counts["photos"] == 47
    assert counts["missing"] == 1
    assert counts["failed"] == 1
    assert counts["reduced_motion"] == 23
    assert face._verdict_line(counts) == "FACE-WALK FAIL 1 failed"
    assert face._exit_code(counts, False) == 1
    clean = dict(counts, failed=0, missing=0)
    assert face._verdict_line(clean) == "FACE-WALK PASS"
    assert face._exit_code(clean, False) == 0
    assert face._exit_code(clean, True) == 2


class _SwitchPage:
    """A fake page that reports moods in order and records screenshots."""

    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.shots = []
        self.viewport_size = {"width": 1280, "height": 800}

    def evaluate(self, _script, *_args):
        return self.bodies.pop(0) if self.bodies else {}

    def screenshot(self, path=None, **_kwargs):
        self.shots.append(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"png")
