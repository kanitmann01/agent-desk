"""Unit tests for the pure parts of tools/layout_audit.py.

Playwright is not needed and never imported here. The browser probe and the
selftest are exercised by `python tools/layout_audit.py --selftest`; these
tests cover the matrix, coverage accounting, fixture loading and pending
verdict rules that can be checked without a browser.
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

import layout_audit as audit  # noqa: E402


def _args(**overrides):
    """A CLI namespace with the defaults the pure functions expect."""
    values = {
        "conditions": "fresh",
        "widths": "1024,1280,800,1920",
        "themes": "unkey,coforge,momentuum",
        "routes": "",
        "no_stress": False,
        "only_condition": "",
        "fail_on": "none",
        "allow_partial": False,
        "record_api": "",
        "api_fixture": "",
        "mock_delay_ms": 0,
        "slow_ms": 0,
        "pending_audit": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _matrix_for(planned):
    """One measured matrix row per planned combination."""
    rows = []
    for combo in planned:
        view = combo["view"]
        rows.append({
            "condition": combo["condition"], "width": combo["width"],
            "theme": combo["theme"], "route": view["path"],
            "state": view.get("state", ""), "stress": combo["stress"],
            "status": "measured", "note": "", "http": 200,
            "final_url": "", "ms": 1,
        })
    return rows


def test_build_combos_rejects_unsupported_width():
    """A width outside the four supported viewports is a hard error."""
    with pytest.raises(audit.AuditError, match="unsupported width"):
        audit.build_combos(_args(widths="1500"))


def test_build_combos_rejects_unknown_theme():
    """A theme outside the three shipped themes is a hard error."""
    with pytest.raises(audit.AuditError, match="unsupported theme"):
        audit.build_combos(_args(themes="bogus"))


def test_build_combos_rejects_unknown_condition():
    """A condition outside the fixed list is a hard error."""
    with pytest.raises(audit.AuditError, match="unsupported condition"):
        audit.build_combos(_args(conditions="bogus"))


def test_build_combos_rejects_route_that_matches_nothing():
    """A route filter that matches no view or overlay is a hard error."""
    with pytest.raises(audit.AuditError, match="no route or overlay"):
        audit.build_combos(_args(routes="nomatch-anywhere"))


def test_build_combos_rejects_empty_band():
    """A valid filter combination that yields no rows is a hard error."""
    with pytest.raises(audit.AuditError, match="no combinations"):
        audit.build_combos(_args(conditions="data", widths="800", themes="unkey"))


def test_build_combos_contains_the_three_bands_for_fresh():
    """fresh has base, theme and extreme rows; long-values has only base."""
    fresh = audit.build_combos(_args(conditions="fresh"))
    widths = {(combo["width"], combo["theme"]) for combo in fresh}
    assert (1024, "unkey") in widths
    assert (1280, "coforge") in widths
    assert (800, "unkey") in widths
    long_values = audit.build_combos(_args(conditions="long-values"))
    assert long_values
    assert {combo["width"] for combo in long_values} == {1024, 1280}
    assert {combo["theme"] for combo in long_values} == {"unkey"}


def test_planned_combos_match_each_condition_child():
    """The parent's plan is the union of the children's own plans."""
    args = _args(conditions="fresh,data")
    planned = audit._planned_combos(args, ["fresh", "data"])
    expected = []
    for condition in ("fresh", "data"):
        child = argparse.Namespace(**vars(args))
        child.only_condition = condition
        child.conditions = condition
        expected.extend(audit._combo_key(combo)
                        for combo in audit.build_combos(child))
    assert [audit._combo_key(combo) for combo in planned] == expected


def _seed_run_folder(tmp_path, planned, findings=None):
    """Write the child JSON files a merge reads."""
    (tmp_path / "findings.fresh.json").write_text(
        json.dumps(findings or []), encoding="utf-8")
    (tmp_path / "matrix.fresh.json").write_text(
        json.dumps(planned), encoding="utf-8")


def _finding():
    """One high finding for the fail-on tests."""
    return {
        "kind": "content-spill", "severity": "high", "stress": False,
        "route": "/", "state": "legacy-dashboard", "condition": "fresh",
        "width": 800, "theme": "unkey", "selector": "div.x",
        "container": "div.x", "classes": "x", "text": "x",
        "metrics": {"over": 5}, "rect": {},
    }


def test_merge_outputs_exits_zero_when_every_row_is_measured(tmp_path):
    """A complete matrix and no findings is a clean exit."""
    args = _args(conditions="fresh", widths="800")
    planned = audit._planned_combos(args, ["fresh"])
    _seed_run_folder(tmp_path, _matrix_for(planned))
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, []) == 0


def test_merge_outputs_marks_a_missing_row_as_incomplete(tmp_path):
    """A planned row with no matrix row exits 3 even with --fail-on none."""
    args = _args(conditions="fresh", widths="800")
    planned = audit._planned_combos(args, ["fresh"])
    rows = _matrix_for(planned)
    _seed_run_folder(tmp_path, rows[:-1])
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, []) == 3


def test_allow_partial_keeps_a_missing_row_from_failing(tmp_path):
    """--allow-partial suppresses the coverage exit code."""
    args = _args(conditions="fresh", widths="800", allow_partial=True)
    planned = audit._planned_combos(args, ["fresh"])
    rows = _matrix_for(planned)
    _seed_run_folder(tmp_path, rows[:-1])
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, []) == 0


def test_nonzero_child_exit_is_incomplete_even_with_a_full_matrix(tmp_path):
    """A child failure is coverage evidence even when its matrix is full."""
    args = _args(conditions="fresh", widths="800")
    planned = audit._planned_combos(args, ["fresh"])
    _seed_run_folder(tmp_path, _matrix_for(planned))
    results = [{"condition": "fresh", "exit": 9}]
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, results) == 3


def test_fail_on_high_fails_for_a_high_finding(tmp_path):
    """--fail-on high exits 1 when a high finding is present."""
    args = _args(conditions="fresh", widths="800", fail_on="high")
    planned = audit._planned_combos(args, ["fresh"])
    _seed_run_folder(tmp_path, _matrix_for(planned), [_finding()])
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, []) == 1


def test_load_api_fixture_reads_a_path_map(tmp_path):
    """The fixture loader returns the path-to-body map, null included."""
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({"/api/dashboard": {"a": 1},
                                "/api/skip": None}), encoding="utf-8")
    loaded = audit._load_api_fixture(path)
    assert loaded["/api/dashboard"] == {"a": 1}
    assert loaded["/api/skip"] is None


def test_load_api_fixture_rejects_a_non_object(tmp_path):
    """A fixture whose top level is a list is a named error."""
    path = tmp_path / "fixture.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(audit.AuditError, match="must be a JSON object"):
        audit._load_api_fixture(path)


def test_pending_verdicts():
    """Every pending verdict is reached by its own evidence shape."""
    control = {"text": "Save", "tag": "button"}
    state = {"control": {"disabled": False}, "indicators": [],
             "labelChanged": False, "ariaBusy": False}
    verdict, _ = audit._pending_verdict(
        control, state, [], [], False, True, ["structure-or-text"])
    assert verdict == "instant"

    verdict, evidence = audit._pending_verdict(
        control, state, [], [], False, False, [])
    assert verdict == "dead"
    assert evidence["signatureChanged"] is False

    busy = dict(state, ariaBusy=True)
    verdict, _ = audit._pending_verdict(control, busy, [{"method": "POST"}], [], False)
    assert verdict == "meets"

    disabled = {"control": {"disabled": True}, "indicators": [],
                "labelChanged": False, "ariaBusy": False}
    verdict, _ = audit._pending_verdict(
        control, disabled, [{"method": "POST"}], [], False)
    assert verdict == "disabled-only"

    verdict, _ = audit._pending_verdict(
        control, state, [{"method": "POST"}], [], False)
    assert verdict == "silent"

    indicator = dict(state, indicators=[{"path": "div.skel", "text": ""}])
    verdict, _ = audit._pending_verdict(
        control, indicator, [{"method": "POST"}], [], False)
    assert verdict == "meets"

    verdict, _ = audit._pending_verdict(control, state, [], [], True)
    assert verdict == "native-dialog"

    wait = dict(state, waitVisible=True)
    verdict, _ = audit._pending_verdict(
        control, wait, [{"method": "POST"}], [], False)
    assert verdict == "meets"

    aria_disabled = {"control": {"disabled": False, "ariaDisabled": "true"},
                     "indicators": [], "labelChanged": False, "ariaBusy": False}
    verdict, _ = audit._pending_verdict(
        control, aria_disabled, [{"method": "POST"}], [], False)
    assert verdict == "disabled-only"


def _signature(**overrides):
    """A complete page signature with one field at a time changed."""
    value = {
        "html": "<body><p>Before</p><button>Act</button></body>",
        "htmlAttrs": [["data-theme", "unkey"]],
        "scroll": [0, 0],
        "location": "/inbox",
        "title": "Inbox, Agent Desk",
    }
    value.update(overrides)
    return value


def test_signature_sees_each_part_of_the_page():
    """Structure, document attributes, scroll, path and hash all count."""
    before = _signature()
    assert audit._signature_changed(before, before) is False
    assert audit._signature_changed(
        before, _signature(html="<body><p>After</p></body>")) is True
    assert audit._signature_changed(
        before, _signature(htmlAttrs=[["data-theme", "coforge"]])) is True
    assert audit._signature_changed(
        before, _signature(scroll=[0, 240])) is True
    assert audit._signature_changed(
        before, _signature(location="/inbox#card-1")) is True
    assert audit._signature_changed(
        before, _signature(title="Card, Agent Desk")) is True


def test_signature_reasons_name_every_change():
    """The reasons list is the readable evidence beside a changed signature."""
    reasons = audit._signature_reasons(_signature(), _signature(
        html="<body>changed</body>", htmlAttrs=[["data-theme", "coforge"]],
        scroll=[0, 10], location="/inbox#card-1", title="Card"))
    assert reasons == ["structure-or-text", "document-attributes", "scroll",
                       "location", "title"]
    assert audit._signature_reasons(_signature(), {"unavailable": "gone"}) == [
        "navigation-or-unavailable"]


def test_already_selected_control_is_skipped():
    """A radio, tab or current control is skipped before any click."""
    selected = {"text": "Unkey", "alreadySelected": True,
                "selectedAttr": "aria-checked"}
    assert audit._pending_skip(selected) == "already selected"
    verdict, evidence = audit._pending_verdict(
        selected, {}, [], [], False, False, [], True)
    assert verdict == "skipped"
    assert evidence == {"reason": "already selected", "alreadySelected": True}
    assert audit._pending_skip({"disabled": True}) == "already disabled"
    assert audit._pending_skip({}) == ""


def test_signature_includes_the_query_string():
    """The query string is part of the location a signature compares."""
    assert "location.search" in audit.PENDING_SIGNATURE_JS
    before = _signature(location="/marketplace/search?q=watch")
    after = _signature(location="/marketplace/search?q=forecast")
    assert audit._signature_reasons(before, after) == ["location"]


def test_late_signature_reason_names_the_millisecond():
    """A change first seen after the early window names when it landed."""
    before = _signature()
    after = _signature(html="<body><p>Late</p></body>")
    reasons = audit._late_signature_reasons(before, after, 812)
    assert reasons[0] == "changed late at 812 ms"
    assert "structure-or-text" in reasons
    assert audit._late_signature_reasons(before, before, 900) == []
    assert audit.SIGNATURE_LATE_MS == 1500


def test_drag_handles_are_recognized_by_name_or_role_description():
    """A drag grip is skipped before its click can be mistaken for a no-op."""
    assert audit._pending_drag_handle(
        {"text": "Drag to reorder Sales"}) is True
    assert audit._pending_drag_handle(
        {"text": "Handle", "roleDescription": "drag handle"}) is True
    assert audit._pending_drag_handle({"text": "Move up"}) is False


def test_covered_control_uses_element_from_point():
    """The cover check asks the point at the visible box centre."""
    assert "elementFromPoint" in audit.PENDING_COVER_JS
    assert "hit.contains(el)" in audit.PENDING_COVER_JS


def test_native_validation_names_the_field_and_never_checks_it():
    """An invalid event with no request is the browser's own refusal."""
    control = {"text": "Save", "tag": "button"}
    invalid = {"tag": "input", "id": "title", "name": "title",
               "label": "Planted required field"}
    verdict, evidence = audit._pending_verdict(
        control, {}, [], [], False, False, [], False, invalid)
    assert verdict == "native-validation"
    assert evidence["reason"] == (
        "the browser's own message on Planted required field")
    assert evidence["invalidControl"] == invalid
    assert "addEventListener('invalid'" in audit.PENDING_INVALID_JS
    verdict, _ = audit._pending_verdict(
        control, {}, [{"method": "POST"}], [], False, False, [], False, invalid)
    assert verdict != "native-validation"


def test_fieldset_disabled_controls_read_as_disabled():
    """The listing uses the browser's own disabled match."""
    assert "el.matches(':disabled')" in audit.PENDING_ENUM_JS


def test_pending_fresh_pages_repin_the_requested_theme():
    """Every fresh page sets the requested theme before its scripts run."""
    script = audit._theme_init_script("momentuum")
    assert "agentdesk.theme" in script
    assert '"momentuum"' in script or "'momentuum'" in script
    assert script.rstrip().endswith("})();")
    source = inspect.getsource(audit._run_pending_audit)
    assert "add_init_script(script=_theme_init_script(combo[\"theme\"]))" in source


def test_box_changed_compares_width_and_height_with_one_pixel_noise():
    """A busy box is flagged only when width or height moves by more than 1px."""
    before = {"width": 100.0, "height": 24.0}
    assert audit._box_changed(before, {"width": 102.0, "height": 24.0}) is True
    assert audit._box_changed(before, {"width": 101.0, "height": 24.0}) is False
    assert audit._box_changed(before, {"width": 100.0, "height": 26.0}) is True
    assert audit._box_changed(before, {"width": 100.5, "height": 24.5}) is False
    assert audit._box_changed(None, before) is False
    assert audit._box_changed(before, {"width": 120.0, "height": 24.0}, True) is False
    assert audit._box_changed(before, {"width": 120.0, "height": 30.0}, True) is True
    assert audit._box_delta(before, {"width": 116.0, "height": 24.0}) == (16.0, 0.0)


def test_pending_fail_thresholds():
    """Silent and dead are high, disabled-only is medium, the rest never fail."""
    silent = [{"verdict": "silent"}]
    dead = [{"verdict": "dead"}]
    disabled = [{"verdict": "disabled-only"}]
    meets = [{"verdict": "meets"}]
    assert audit._pending_fail(silent, "high") is True
    assert audit._pending_fail(dead, "high") is True
    assert audit._pending_fail(disabled, "high") is False
    assert audit._pending_fail(disabled, "medium") is True
    assert audit._pending_fail(meets, "any") is False
    assert audit._pending_fail(silent, "none") is False
    assert audit._pending_fail(dead, "none") is False


def test_overflow_fixture_is_a_local_widget_with_the_planned_overlays():
    """The overflow fixture is a local manual metric and keeps four rows."""
    manifest = json.loads((audit.OVERFLOW_FIXTURE / "manifest.json").read_text(
        encoding="utf-8"))
    widget = manifest["contributes"]["widgets"][0]
    assert widget["dataSource"]["type"] == "manual-metric"
    assert len(manifest["name"]) > 60
    assert (audit.OVERFLOW_FIXTURE / manifest["sample"]).is_file()
    assert audit.OVERFLOW_CONDITIONS == ("plugins", "full")
    args = _args(conditions="plugins,full", widths="1024,1280", themes="unkey")
    combos = audit.build_combos(args)
    overlays = [combo for combo in combos
                if combo["view"].get("state") == "overlay-widget-menu"]
    assert len(overlays) == 4
    assert {combo["condition"] for combo in overlays} == {"plugins", "full"}


def test_relative_records_drop_the_run_folder_prefix(tmp_path):
    """Evidence paths in findings.json are relative to the run folder."""
    path = tmp_path / "crops" / "a.png"
    records = audit._relative_records([{"crop": str(path)}], tmp_path)
    assert records[0]["crop"] == "crops/a.png"


class _GateResult:
    """The small immutable result shape the instrument's fixtures need."""

    def __init__(self, key, number, title, status, evidence=(), note=""):
        self.key = key
        self.number = number
        self.title = title
        self.status = status
        self.evidence = tuple(evidence)
        self.note = note


class _WalkRecorder:
    """A stand-in for the server factory and every request a walk makes."""

    def __init__(self):
        self.create_calls = []
        self.requests = []
        self.cached = []
        self.guard_events = []
        self.base = "http://127.0.0.1:43123"

    def create_server(self, **kwargs):
        """Record the factory call and return a server that cannot listen."""
        self.create_calls.append(kwargs)
        recorder = self

        class Server:
            port = 43123
            settings = None
            sessions = SimpleNamespace(bootstrap_token=lambda: "test-token")
            excel = calendar = mail = plugins = None
            gate_runners = kwargs.get("gate_runners")
            capabilities_cache = SimpleNamespace(
                save_result=lambda result: recorder.cached.append(result) or result)

            def serve_forever(self):
                return None

            def shutdown(self):
                return None

            def server_close(self):
                return None

        return Server()

    def request(self):
        """The context request client, recording but never sending."""
        recorder = self

        class Request:
            def post(self, url, **_kwargs):
                recorder.requests.append(("POST", url))
                return SimpleNamespace(status=200, text=lambda: "")

        return Request()


def _install_fake_desk(monkeypatch, recorder):
    """Replace every agentdesk import used by a boot with in-memory stand-ins."""
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

    def pin(data_dir, _condition, _mock_port):
        monkeypatch.setenv("AGENTDESK_DATA", str(data_dir))

    monkeypatch.setattr(audit, "_pin_environment", pin)
    monkeypatch.setattr(audit, "_start_mock", lambda _delay=0: (
        SimpleNamespace(shutdown=lambda: None, server_close=lambda: None), 4321))
    return Path(recorder.base)


def _worker_args(condition, run_dir, pending=False):
    """The complete child namespace without a browser or a real desk."""
    values = vars(_args(
        conditions=condition, widths="1024", themes="unkey", no_stress=True,
        pending_audit=pending))
    values.update(jobs=1, out=str(run_dir), child=True, only_condition=condition)
    return argparse.Namespace(**values)


def _drive_layout_worker(monkeypatch, tmp_path, recorder, pending=False):
    """Drive the real condition worker against a recorded, inert server."""
    import feedback_walkthrough as walk

    tmp_path.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    desk_root = tmp_path / "desk"
    desk_root.mkdir()
    monkeypatch.setattr(audit.tempfile, "mkdtemp", lambda **_kwargs: str(desk_root))
    monkeypatch.setattr(audit, "_seed", lambda *_args: [])

    class Page:
        url = recorder.base + "/"

        def __init__(self):
            self.clock = SimpleNamespace(install=lambda **_kwargs: None,
                                         set_fixed_time=lambda *_args: None)

        def on(self, *_args):
            return None

        def goto(self, url, **_kwargs):
            self.url = recorder.base + "/"
            return SimpleNamespace(status=200)

        def evaluate(self, *_args, **_kwargs):
            return None

        def wait_for_timeout(self, *_args):
            return None

        def close(self):
            return None

    class Context:
        def __init__(self):
            self.request = recorder.request()

        def new_page(self):
            return Page()

        def add_init_script(self, *_args, **_kwargs):
            recorder.guard_events.append("init-script")
            return None

        def route(self, _pattern, _handler):
            recorder.guard_events.append("route")
            return None

        def close(self):
            return None

    class Browser:
        def new_context(self, **_kwargs):
            return Context()

        def close(self):
            return None

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **_kwargs: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(audit, "sync_playwright", Playwright)

    def measure(_page, combo, _runtime, _run_dir, _calendar, _crops, _base,
                _record_dir=None):
        return {"entry": {
            "condition": combo["condition"], "width": combo["width"],
            "theme": combo["theme"], "route": combo["view"]["path"],
            "state": combo["view"].get("state", ""), "stress": combo["stress"],
            "status": "measured", "note": "", "http": 200,
            "final_url": recorder.base + "/", "ms": 1,
        }, "findings": []}

    monkeypatch.setattr(audit, "_measure_combo", measure)
    monkeypatch.setattr(audit, "_run_pending_audit", lambda *_args: [{
        "verdict": "meets", "page_index": 1, "page_total": 1,
    }])
    args = _worker_args("busy", run_dir, pending)
    assert audit._condition_worker(args, "busy", run_dir) == 0
    assert walk.audit is audit


def _drive_feedback_worker(monkeypatch, tmp_path, recorder):
    """Drive the feedback boot and seed with no action and no real browser."""
    import feedback_walkthrough as walk

    tmp_path.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "feedback"
    run_dir.mkdir()
    desk_root = tmp_path / "feedback-desk"
    desk_root.mkdir()
    monkeypatch.setattr(walk.tempfile, "mkdtemp", lambda **_kwargs: str(desk_root))
    monkeypatch.setattr(audit, "_seed", lambda *_args: [])

    class Page:
        url = recorder.base + "/"
        clock = SimpleNamespace(install=lambda **_kwargs: None,
                                set_fixed_time=lambda *_args: None)

        def goto(self, _url, **_kwargs):
            return None

    class Context:
        def __init__(self):
            self.request = recorder.request()

        def new_page(self):
            return Page()

        def route(self, _pattern, _handler):
            recorder.guard_events.append("route")
            return None

        def close(self):
            return None

    class Browser:
        def new_context(self, **_kwargs):
            return Context()

        def close(self):
            return None

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **_kwargs: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    playwright_package = types.ModuleType("playwright")
    playwright_package.__path__ = []
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = Playwright
    monkeypatch.setitem(sys.modules, "playwright", playwright_package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(walk, "ACTIONS", ())
    args = SimpleNamespace(mock_delay_ms=0, only="")
    walk._walk(args, run_dir)


def test_every_walk_entry_point_injects_inert_gate_runners(monkeypatch, tmp_path):
    """Matrix, pending and feedback boots all replace production gate runners."""
    for entry in ("matrix", "pending", "feedback"):
        recorder = _WalkRecorder()
        _install_fake_desk(monkeypatch, recorder)
        if entry == "feedback":
            _drive_feedback_worker(monkeypatch, tmp_path / entry, recorder)
        else:
            _drive_layout_worker(monkeypatch, tmp_path / entry, recorder,
                                 pending=entry == "pending")
        assert len(recorder.create_calls) == 1
        runners = recorder.create_calls[0].get("gate_runners")
        assert runners is not None, f"{entry} boot omitted gate_runners"
        assert set(runners) == {key for key, _number, _title in
                                sys.modules["agentdesk.capabilities"].GATES}
        assert {runner().status for runner in runners.values()} == {"UNKNOWN"}


def test_busy_seeding_never_sends_a_capability_request(monkeypatch, tmp_path):
    """Busy pages come from cache fixtures, never real capability retests."""
    recorder = _WalkRecorder()
    _install_fake_desk(monkeypatch, recorder)
    server = recorder.create_server()
    context = SimpleNamespace(request=recorder.request())
    notes = []
    audit._seed_busy(context, recorder.base, tmp_path, server, 4321, notes)
    capability_requests = [url for method, url in recorder.requests
                           if method != "GET" and "/capabilities/" in url]
    assert capability_requests == []
    assert {result.key for result in recorder.cached} == {
        key for key, _number, _title in sys.modules["agentdesk.capabilities"].GATES}
