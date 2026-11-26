"""Unit tests for tools/face_walkthrough.py.

Playwright is never imported and no desk is started here. The boot is driven
against a stand-in for the server factory that records every call, and the
routes, checks, counts and exit codes are exercised with fake pages.
"""

from __future__ import annotations

import argparse
import inspect
import json
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
    context_options = []
    emulate_options = []

    class Page:
        url = "http://127.0.0.1:43123/"

        def __init__(self):
            self.clock = SimpleNamespace(install=lambda **_kwargs: None,
                                         set_fixed_time=lambda *_args: None)

        def goto(self, _url, **_kwargs):
            events.append("goto")

        def emulate_media(self, **kwargs):
            events.append("emulate")
            emulate_options.append(kwargs)

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

        def new_context(self, **kwargs):
            context_options.append(kwargs)
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
    monkeypatch.setattr(face, "_photograph_real_app", lambda *_args: None)
    monkeypatch.setattr(face.tempfile, "mkdtemp",
                        lambda **_kwargs: str(tmp_path / "desk"))
    face._run_real_phase(_args(), run, plan, Playwright())
    assert events.index("route") < events.index("goto")
    assert [pattern for pattern, _handler in routes] == [
        "**/*", "**/research", "**/api/marketplace/retest"]
    assert "reduced_motion" not in context_options[0]
    assert emulate_options == [{"reduced_motion": "no-preference"}]


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


def test_the_collapsed_rail_is_planned_on_the_fresh_desk():
    """The collapsed rail is photographed before the full seed, where it is idle."""
    plan = face.build_plan(_args())
    collapsed = [shot for shot in plan if shot.kind == "rail-collapsed"]
    assert collapsed
    assert {shot.condition for shot in collapsed} == {"fresh"}
    assert {shot.mood for shot in collapsed} == {"idle"}


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


def test_the_proxied_paths_are_read_from_the_vite_config():
    """The deny rule tracks every backendPath the dev server proxies."""
    paths = face._proxied_paths()
    assert "/api" in paths
    assert "/auth" in paths
    assert "/widgets" in paths
    assert "/agents" in paths
    config = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    block = config.split("const backendPaths = [", 1)[1].split("];", 1)[0]
    for path in paths:
        assert f"'{path}'" in block


def test_the_sheet_deny_rule_aborts_every_proxied_and_foreign_request():
    """Only the sheet's own assets fall through; every proxied path aborts."""
    class Target:
        def __init__(self):
            self.handler = None

        def route(self, _pattern, handler):
            self.handler = handler

    target = Target()
    proxied = face._install_sheet_deny(target)

    def resolve(method, url):
        route = _FakeRoute(method, url)
        target.handler(route)
        return route.calls

    origin = f"http://{face.SHEET_HOST}:{face.SHEET_PORT}"
    for path in proxied:
        assert resolve("GET", origin + path) == ["abort"], path
        assert resolve("GET", origin + "/static/spa" + path) == ["abort"], path
    assert resolve("GET", origin + "/api/marketplace/retest") == ["abort"]
    assert resolve("POST", origin + "/face-sheet.html") == ["abort"]
    assert resolve("GET", origin + "/marketplace") == ["abort"]
    assert resolve("GET", origin + "/") == ["abort"]
    assert resolve("GET", "https://example.com/src/evil.js") == ["abort"]
    for path in ("/face-sheet.html", "/src/face/sheet.tsx",
                 "/node_modules/.vite/deps/react.js?v=1", "/@vite/client",
                 "/static/spa/@vite/client", "/@react-refresh",
                 "/src/index.css", "/static/spa/fonts/inter.woff2",
                 "/static/spa/favicon.svg", "/favicon.ico"):
        assert resolve("GET", origin + path) == ["fallback"], path


def _sheet_state(mood, theme, media=False, signature=None):
    """One SHEET_STATE_JS answer with a stable signature by default."""
    sig = signature or {
        "box": {"transform": "", "borderRadius": "", "shape": ""},
        "left": {"transform": "translate(0px, 0px)", "borderRadius": "3px",
                 "shape": "capsule"},
        "right": {"transform": "translate(0px, 0px)", "borderRadius": "3px",
                  "shape": "capsule"},
    }
    return {"present": True, "mood": mood, "size": "md", "theme": theme,
            "title": "Nexuus Bot", "media": media, "signature": sig}


class _SheetCheckPage:
    """A fake page that replays sheet states and records the 500 ms wait."""

    def __init__(self, states):
        self.states = list(states)
        self.waits = []
        self.arguments = []

    def evaluate(self, script, argument):
        assert script == face.SHEET_STATE_JS
        self.arguments.append(argument)
        return self.states.pop(0) if self.states else {}

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def test_the_sheet_check_passes_a_normal_and_a_still_reduced_face(tmp_path):
    """Normal motion checks mood and theme; reduced motion also checks stillness."""
    run = face.RunState([], tmp_path)
    normal_shot = face.Shot(
        id="n", surface="review-sheet", kind="sheet", theme="unkey",
        mood="thinking", motion="normal", condition="", width=1280,
        state="tile", variant="tile", file="photos/n.png")
    page = _SheetCheckPage([_sheet_state("thinking", "unkey")])
    result = face._check_sheet(page, normal_shot, run)
    assert result["passed"] is True
    assert page.waits == []
    assert run.surfaces["review-sheet"]["face"] is True

    reduced_shot = face.Shot(
        id="r", surface="review-sheet", kind="sheet", theme="coforge",
        mood="working", motion="reduce", condition="", width=1280,
        state="tile", variant="tile", file="photos/r.png")
    still = _sheet_state("working", "coforge", media=True)
    page = _SheetCheckPage([still, json.loads(json.dumps(still))])
    result = face._check_sheet(page, reduced_shot, run)
    assert result["passed"] is True
    assert page.waits == [500]
    assert page.arguments[0] == {"demo": True, "index": 4}


def test_the_sheet_check_fails_a_moved_reduced_face_and_a_wrong_mood(tmp_path):
    """A moving reduced pose and a wrong data-mood are failed checks."""
    run = face.RunState([], tmp_path)
    shot = face.Shot(
        id="r", surface="review-sheet", kind="sheet", theme="unkey",
        mood="thinking", motion="reduce", condition="", width=1280,
        state="tile", variant="tile", file="photos/r.png")
    first = _sheet_state("thinking", "unkey", media=True)
    moved = json.loads(json.dumps(first))
    moved["signature"]["left"]["transform"] = "translate(2px, 0px)"
    page = _SheetCheckPage([first, moved])
    result = face._check_sheet(page, shot, run)
    assert result["passed"] is False
    assert "moved" in result["detail"]

    page = _SheetCheckPage([_sheet_state("idle", "unkey")])
    result = face._check_sheet(page, shot, run)
    assert result["passed"] is False
    assert "data-mood" in result["detail"]

    page = _SheetCheckPage([_sheet_state("thinking", "momentuum")])
    result = face._check_sheet(page, shot, run)
    assert result["passed"] is False
    assert "data-theme" in result["detail"]


def test_the_sheet_page_installs_the_guard_and_deny_rule_before_navigation():
    """Both routes exist before the sheet page navigates, in both motions."""
    events = []
    options = []

    class Page:
        def emulate_media(self, **kwargs):
            events.append(("emulate", kwargs))

        def goto(self, _url, **_kwargs):
            events.append("goto")

        def wait_for_selector(self, *_args, **_kwargs):
            events.append("selector")

        def wait_for_timeout(self, _ms):
            return None

    class Context:
        def route(self, _pattern, _handler):
            events.append("route")

        def new_page(self):
            events.append("new_page")
            return Page()

    class Browser:
        def new_context(self, **kwargs):
            options.append(kwargs)
            return Context()

    run = face.RunState([], Path("unused"))
    face._open_sheet_page(Browser(), "reduce", ("/api",), run)
    assert events[:5] == ["route", "route", "new_page",
                          ("emulate", {"reduced_motion": "reduce"}), "goto"]
    assert options[0]["reduced_motion"] == "reduce"
    events.clear()
    options.clear()
    face._open_sheet_page(Browser(), "normal", ("/api",), run)
    assert options[0].get("reduced_motion") is None
    assert ("emulate", {"reduced_motion": "no-preference"}) in events


def test_the_sheet_tile_locator_uses_the_active_preset_grid():
    """A mood tile is the active preset's grid tile at the mood's index."""
    log = []

    class Locator:
        def nth(self, index):
            log.append(("nth", index))
            return self

        def locator(self, selector):
            log.append(("locator", selector))
            return self

        @property
        def first(self):
            log.append("first")
            return self

    class Page:
        def locator(self, selector):
            log.append(("locator", selector))
            return Locator()

    face._sheet_tile(Page(), "thinking")
    assert log == [("locator", ".face-sheet-grid"), ("nth", 0),
                   ("locator", ".face-sheet-tile"), ("nth", 2),
                   ("locator", ".face-box")]
    log.clear()
    face._sheet_tile(Page(), "working")
    assert log == [("locator",
                    '.face-sheet-demo [data-face-slot="rail"] .face-box'),
                   "first"]


def test_sheet_only_execution_never_boots_a_desk(monkeypatch, tmp_path):
    """The sheet-only mode starts the sheet phase and no desk boot."""
    plan = face.build_plan(_args(sheet_only=True))
    run = face.RunState(plan, tmp_path)
    calls = []

    class Playwright:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(face.audit, "sync_playwright", lambda: Playwright())
    monkeypatch.setattr(face, "_run_sheet_phase",
                        lambda *_args: calls.append("sheet"))
    monkeypatch.setattr(face, "_boot_isolated_desk",
                        lambda *_args: calls.append("boot"))
    assert face._execute(_args(sheet_only=True), run) is False
    assert calls == ["sheet"]


class _FakeLocator:
    """A locator stand-in that records the call the walk makes on it."""

    def __init__(self, page, selector, index=None, count=None):
        self.page = page
        self.selector = selector
        self.index = index
        self.count_override = count

    @property
    def first(self):
        return self

    def nth(self, index):
        self.page.events.append(("nth", self.selector, index))
        return _FakeLocator(self.page, self.selector, index)

    def count(self):
        if self.count_override is not None:
            return self.count_override
        return self.page.counts.get(self.selector, 1)

    def focus(self):
        self.page.events.append(("focus", self.selector))

    def fill(self, text):
        self.page.events.append(("fill", self.selector, text))

    def click(self):
        self.page.events.append(("click", self.selector, self.index))

    def get_attribute(self, name):
        return self.page.attributes.get((self.selector, self.index, name), "")

    def inner_text(self):
        return self.page.texts.get((self.selector, self.index), "")


class _StagePage:
    """A fake real-app page that records locators, waits and evaluations."""

    def __init__(self):
        self.events = []
        self.counts = {}
        self.attributes = {}
        self.texts = {}
        self.rail_states = []
        self.responses = {}
        self.keyboard = SimpleNamespace(press=self._press)

    def _press(self, key):
        self.events.append(("press", key))

    def goto(self, url, **_kwargs):
        self.events.append(("goto", url))

    def wait_for_load_state(self, *_args, **_kwargs):
        self.events.append(("load",))

    def wait_for_timeout(self, ms):
        self.events.append(("wait", ms))

    def wait_for_selector(self, selector, **_kwargs):
        self.events.append(("selector", selector))

    def set_viewport_size(self, size):
        self.events.append(("viewport", size["width"]))

    def evaluate(self, script, *args):
        self.events.append(("evaluate", script, args))
        if script == face.RAIL_STATE_JS and self.rail_states:
            return self.rail_states.pop(0)
        if script in self.responses:
            value = self.responses[script]
            return value.pop(0) if isinstance(value, list) else value
        if script == face.RAIL_STATE_JS:
            return {"present": True, "mood": "idle", "size": "md", "title": ""}
        return {}

    def locator(self, selector):
        self.events.append(("locator", selector))
        return _FakeLocator(self, selector)

    def get_by_role(self, role, name=None, exact=False):
        self.events.append(("role", role, str(name), exact))
        count = self.counts.get(("role", str(name)), 0)
        return _FakeLocator(self, f"role:{name}",
                            0 if count else None, count=count)

    def check_count(self, selector):
        self.counts[selector] = 0


def _stage_page():
    """A fake page whose research button and field each match once."""
    page = _StagePage()
    page.counts[face.RESEARCH_BUTTON] = 1
    page.counts[face.RESEARCH_FIELD] = 1
    return page


def test_idle_and_listening_use_the_dashboard_and_the_research_field():
    """Idle navigates to the dashboard; listening focuses the research field."""
    page = _stage_page()
    face._act_idle(page, "http://desk")
    assert ("goto", "http://desk/") in page.events
    assert ("selector", face.RESEARCH_BUTTON) in page.events
    page.events.clear()
    face._act_listening(page, "http://desk")
    assert ("focus", face.RESEARCH_FIELD) in page.events


def test_thinking_types_and_clicks_research():
    """Thinking fills the research field and clicks the research button."""
    page = _stage_page()
    face._act_thinking(page, "http://desk", "Which deals?")
    assert ("fill", face.RESEARCH_FIELD, "Which deals?") in page.events
    assert ("click", face.RESEARCH_BUTTON, None) in page.events


def test_blocked_sets_the_failure_route_before_asking():
    """Blocked selects the walk's 500 route, then asks the question."""
    page = _stage_page()
    config = face.RouteConfig()
    face._act_blocked(page, "http://desk", config, "Which deals?")
    assert config.research == "fail"
    assert ("fill", face.RESEARCH_FIELD, "Which deals?") in page.events
    assert ("click", face.RESEARCH_BUTTON, None) in page.events


def test_reading_sets_the_hold_route_and_opens_the_retest_menu():
    """Reading holds the retest and clicks Re-test now on a non-fresh card."""
    page = _stage_page()
    page.counts['button[aria-label^="Widget options"]'] = 2
    page.attributes[('button[aria-label^="Widget options"]', 0,
                     "aria-label")] = "Widget options, Fresh card"
    page.attributes[('button[aria-label^="Widget options"]', 1,
                     "aria-label")] = "Widget options, Stale card"
    config = face.RouteConfig()
    calls = {"index": 0}

    def role(role, name=None, exact=False):
        page.events.append(("role", role, str(name), exact))
        if name == "Re-test now":
            count = 1 if calls["index"] == 1 else 0
            calls["index"] += 1
            return _FakeLocator(page, f"role:{name}", 0 if count else None,
                                count=count)
        return _FakeLocator(page, f"role:{name}")

    page.get_by_role = role
    facts = face._act_reading(page, "http://desk", config)
    assert config.retest == "hold"
    assert facts["card"] == "Widget options, Stale card"
    assert ("role", "menuitem", "Re-test now", True) in page.events
    assert ("press", "Escape") in page.events


def test_waiting_and_done_add_no_new_action():
    """Waiting lands on the dashboard; done is the success already in flight."""
    page = _stage_page()
    face._act_waiting(page, "http://desk")
    assert ("goto", "http://desk/") in page.events
    page.events.clear()
    facts = face._act_done(page, "http://desk")
    assert facts["action"] == "done"
    assert page.events == []


def test_wait_mood_polls_until_the_expected_mood():
    """The wait returns the expected mood and keeps the last state on timeout."""
    page = _StagePage()
    page.rail_states = [
        {"present": True, "mood": "idle", "size": "md", "title": ""},
        {"present": True, "mood": "thinking", "size": "md", "title": ""},
    ]
    state = face._wait_mood(page, "thinking", 1000)
    assert state["mood"] == "thinking"
    assert any(event[0] == "wait" for event in page.events)
    page.rail_states = [{"present": True, "mood": "idle", "size": "md",
                         "title": ""}]
    state = face._wait_mood(page, "done", 10)
    assert state["mood"] == "idle"


def test_the_rail_check_names_the_waiting_count_and_the_blocked_failure(
        tmp_path, monkeypatch):
    """Waiting requires its tooltip count; blocked requires the kept failure."""
    monkeypatch.setattr(face, "RAIL_CHECK_TIMEOUT_MS", 5)
    run = face.RunState([], tmp_path)
    waiting = face.Shot(
        id="w", surface="rail", kind="rail", theme="unkey", mood="waiting",
        motion="normal", condition="full", width=1280, state="", variant="face",
        file="photos/w.png")
    page = _StagePage()
    page.rail_states = [{"present": True, "mood": "waiting", "size": "md",
                         "title": "Nexuus Bot: 3 waiting in Inbox"}]
    result = face._check_rail(page, waiting, run)
    assert result["passed"] is True
    assert result["extra"]["waiting_count"] == 3

    blocked = face.Shot(
        id="b", surface="rail", kind="rail", theme="unkey", mood="blocked",
        motion="normal", condition="full", width=1280, state="", variant="face",
        file="photos/b.png")
    page = _StagePage()
    page.rail_states = [{"present": True, "mood": "blocked", "size": "md",
                         "title": "Nexuus Bot: Needs attention"}]
    page.responses[face.BLOCKED_STATE_JS] = {
        "alert": "The face walk refused this request on purpose.", "question": "Q"}
    result = face._check_rail(page, blocked, run, "Q")
    assert result["passed"] is True
    page.responses[face.BLOCKED_STATE_JS] = {"alert": "", "question": "Q"}
    result = face._check_rail(page, blocked, run, "Q")
    assert result["passed"] is False
    assert "keeps no failure" in result["detail"]
    page.responses[face.BLOCKED_STATE_JS] = {"alert": "x", "question": "other"}
    result = face._check_rail(page, blocked, run, "Q")
    assert result["passed"] is False
    assert "not kept" in result["detail"]


def test_the_surface_checks_record_faces_without_failing_their_absence(tmp_path):
    """Collapsed rail needs its face; phone, dialogs and server record absence."""
    run = face.RunState([], tmp_path)
    collapsed = face.Shot(
        id="c", surface="rail-collapsed", kind="rail-collapsed", theme="unkey",
        mood="idle", motion="normal", condition="full", width=1280,
        state="collapsed", variant="page", file="photos/c.png")
    page = _StagePage()
    page.responses[face.COLLAPSED_STATE_JS] = {
        "collapsed": True,
        "face": {"present": True, "mood": "idle", "size": "md"},
    }
    result = face._check_collapsed(page, collapsed, run)
    assert result["passed"] is True

    phone = face.Shot(
        id="p", surface="phone-strip", kind="phone-strip", theme="unkey",
        mood="", motion="normal", condition="full", width=800,
        state="closed", variant="page", file="photos/p.png")
    page = _StagePage()
    page.responses[face.PHONE_STATE_JS] = {
        "bar": True, "visible": False, "slots": 0, "faces": 0}
    result = face._check_phone(page, phone, run)
    assert result["passed"] is True
    assert run.surfaces["phone-strip"]["face"] is False

    dialog = face.Shot(
        id="d", surface="dialog-tracker", kind="dialog", theme="unkey",
        mood="", motion="normal", condition="full", width=1280,
        state="open", variant="page", file="photos/d.png")
    page = _StagePage()
    page.responses[face.DIALOG_STATE_JS] = {
        "dialog": True, "dialogFaces": 0, "dialogSlots": 0,
        "railFaces": 1, "railStays": True}
    result = face._check_dialog(page, dialog, run)
    assert result["passed"] is True
    assert "rail face in page 1" in result["detail"]
    assert run.surfaces["dialog-tracker"]["face"] is False

    server = face.Shot(
        id="s", surface="server-inbox", kind="server", theme="unkey",
        mood="", motion="normal", condition="full", width=1280,
        state="collapsed", variant="page", file="photos/s.png")
    page = _StagePage()
    page.responses[face.SERVER_STATE_JS] = {
        "theme": "unkey", "faceSlots": 0, "faceBoxes": 0, "railSlots": 0,
        "collapsed": True}
    result = face._check_server(page, server, run)
    assert result["passed"] is True
    assert run.surfaces["server-inbox"]["face"] is False

    page.responses[face.PHONE_STATE_JS] = {
        "bar": True, "visible": True, "slots": 1, "faces": 1}
    result = face._check_phone(page, phone, run)
    assert result["passed"] is False
    page.responses[face.SERVER_STATE_JS] = {
        "theme": "coforge", "faceSlots": 0, "faceBoxes": 0, "railSlots": 0,
        "collapsed": False}
    result = face._check_server(page, server, run)
    assert result["passed"] is False


def test_the_dialog_openers_use_their_real_controls():
    """The describe and tracker dialogs open from the app's own controls."""
    page = _stage_page()
    page.counts[("role", "Describe a plugin in plain English")] = 1
    face._open_describe_dialog(page, "http://desk")
    assert ("goto", "http://desk/marketplace") in page.events
    assert ("role", "button", "Describe a plugin in plain English", True) in page.events
    assert ("selector", '.setup-sheet[role="dialog"]') in page.events

    page = _stage_page()
    page.counts[".tracker-card button"] = 2
    page.texts[(".tracker-card button", 0)] = "Open"
    page.texts[(".tracker-card button", 1)] = "Edit"
    face._open_tracker_dialog(page, "http://desk")
    assert ("goto", "http://desk/") in page.events
    assert ("click", ".tracker-card button", 1) in page.events
    assert ("selector", '.setup-sheet[role="dialog"]') in page.events


def test_a_failed_action_is_still_photographed(tmp_path):
    """A failed prep is a failed check for the group and the shots still happen."""
    shots = [
        face.Shot(id="a", surface="dialog-describe", kind="dialog",
                  theme="unkey", mood="", motion="normal", condition="full",
                  width=1280, state="open", variant="page",
                  file="photos/a.png"),
        face.Shot(id="b", surface="dialog-describe", kind="dialog",
                  theme="unkey", mood="", motion="normal", condition="full",
                  width=1280, state="open", variant="page",
                  file="photos/b.png"),
    ]
    run = face.RunState(shots, tmp_path)
    page = _StagePage()

    def prep():
        raise RuntimeError("the dialog did not open")

    def shoot(_page, shot, run_dir):
        path = run_dir / shot.file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        return str(path)

    face._capture_surface(page, shots, prep, lambda shot: {}, run, shoot=shoot)
    for shot in shots:
        record = run.records[shot.id]
        assert record["missing"] is False
        assert record["verdict"] == "failed"
        assert "did not open" in record["check"]["detail"]
    assert len(list(tmp_path.rglob("*.png"))) == 2
