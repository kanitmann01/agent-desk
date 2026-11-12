"""Capabilities over HTTP: the cached page, and the one probing path.

The seam tests drive the real server. The safety property under test:
GET /capabilities renders the cache and never probes the environment
(probes belong to the explicit re-test POST, with the injected runner
set), and the endpoint and source cards read the live connection table,
so a down endpoint can never read green.
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.calendar import watcher as calendar_watcher
from agentdesk.calendar.watcher import Adapters as CalendarAdapters
from agentdesk.calendar.watcher import CalendarBridge
from agentdesk.capabilities import CapabilitiesCache, default_gate_runners
from agentdesk.excel import core as excel_core
from agentdesk.excel.watcher import Adapters as ExcelAdapters
from agentdesk.excel.watcher import ExcelWatch
from agentdesk.excel.xlsx import parse_workbook_bytes
from agentdesk.probe.core import FAIL, GATE_KEYS, PASS, UNKNOWN, GateResult
from agentdesk.server import capabilities_view
from agentdesk.server.core import (
    SRC_CALENDAR,
    SRC_EXCEL,
    SRC_RESEARCH,
    STATUS_CONNECTED,
    STATUS_NOT_CONNECTED,
    SourceStatus,
)
from excel_fixtures import base_workbook

NOW = datetime.now().astimezone()


class FakeClock:
    """The cache's clock under test control."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_result(
    key="exec-user-space",
    number=1,
    title="User-space execution",
    status=PASS,
    evidence=("command: hello",),
    note="",
) -> GateResult:
    return GateResult(
        key=key, number=number, title=title, status=status,
        evidence=tuple(evidence), note=note,
    )


class CountingRunners:
    """The five real gate runners wrapped in counters.

    This is the suite's proof that the page cannot probe: the runners
    really would touch the environment, and the test asserts the count
    stays at zero while the page renders.
    """

    def __init__(self, workdir: Path) -> None:
        self.calls = {key: 0 for key in GATE_KEYS}
        self._real = default_gate_runners(workdir)
        self.runners = {key: self._wrap(key, run) for key, run in self._real.items()}

    def _wrap(self, key, run):
        def call():
            self.calls[key] += 1
            return run()

        return call

    def total(self) -> int:
        return sum(self.calls.values())


class FakeGate:
    """One injected gate runner: canned result, counted calls."""

    def __init__(self, result: GateResult) -> None:
        self.result = result
        self.calls = 0

    def __call__(self) -> GateResult:
        self.calls += 1
        return self.result


def fake_runner_set(**overrides) -> dict:
    """All five keys present, every gate a counted fake."""
    results = {
        "exec-user-space": make_result(key="exec-user-space", number=1, status=UNKNOWN),
        "uv-tls-bootstrap": make_result(
            key="uv-tls-bootstrap", number=2, title="uv bootstrap", status=UNKNOWN
        ),
        "power-automate-flows": make_result(
            key="power-automate-flows", number=3, title="Power Automate", status=UNKNOWN
        ),
        "onedrive-sync": make_result(
            key="onedrive-sync", number=4, title="OneDrive", status=UNKNOWN
        ),
        "edr-identity": make_result(
            key="edr-identity", number=5, title="EDR", status=UNKNOWN
        ),
    }
    results.update(overrides)
    return {key: FakeGate(result) for key, result in results.items()}


# -- the gate and the page ----------------------------------------------------


@pytest.fixture()
def env():
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def test_capabilities_requires_a_session(env):
    status, _h, _b = env.request("GET", "/capabilities", env.host_header())
    assert status == 401
    status, _h, _b = env.post_json(
        "/capabilities/exec-user-space/retest", {}, env.host_header()
    )
    assert status == 401


def test_a_fresh_page_shows_never_tested_cards_and_a_retest_action(env, auth):
    status, _h, body = env.request("GET", "/capabilities", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "Capabilities" in page
    for key in GATE_KEYS:
        assert f'gate-{key}' in page
        assert f"/capabilities/{key}/retest" in page
    assert page.count("Not tested") == len(GATE_KEYS)


def test_get_never_probes_even_with_the_real_runners_wired(tmp_path):
    counting = CountingRunners(tmp_path / "probe-work")
    booted = server_harness.Booted(gate_runners=counting.runners)
    try:
        auth = booted.exchange()
        status, _h, _b = booted.request("GET", "/capabilities", auth)
        assert status == 200
        # The runners are the real adapters; the page rendered anyway.
        assert counting.total() == 0
    finally:
        booted.close()


def test_the_page_renders_a_cached_result_with_its_stamp(env, auth):
    env.server.capabilities_cache.save_result(
        make_result(status=PASS, evidence=("command: hello", "rc=0"), note="hello-world ran")
    )
    _status, _h, body = env.request("GET", "/capabilities", auth)
    page = body.decode("utf-8")
    assert "PASS" in page
    assert "hello-world ran" in page
    assert "command: hello" in page
    assert "Tested" in page
    assert "just now" in page


def test_an_old_pass_says_how_old_it_is():
    clock = FakeClock()
    booted = server_harness.Booted(
        capabilities_cache=CapabilitiesCache(
            sqlite3.connect(":memory:", check_same_thread=False), clock
        )
    )
    try:
        booted.server.capabilities_cache.save_result(make_result(status=PASS))
        clock.advance(2 * 60 * 60)
        auth = booted.exchange()
        _status, _h, body = booted.request("GET", "/capabilities", auth)
        page = body.decode("utf-8")
        assert "2 hours ago" in page
        # A stale pass never reads as current: no fresh stamp anywhere.
        assert "just now" not in page
    finally:
        booted.close()


def test_cached_card_output_is_escaped(env, auth):
    env.server.capabilities_cache.save_result(
        make_result(
            status=FAIL,
            evidence=("<script>alert(1)</script>",),
            note="<b>blocked</b> by policy",
        )
    )
    _status, _h, body = env.request("GET", "/capabilities", auth)
    page = body.decode("utf-8")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "&lt;b&gt;blocked&lt;/b&gt;" in page


def test_the_page_carries_no_model_listing(env, auth):
    # v1 divergence from the donor: the chat adapter is chat-only, and
    # their Ollama/model checks are not adopted.
    _status, _h, body = env.request("GET", "/capabilities", auth)
    page = body.decode("utf-8")
    assert "Ollama" not in page
    assert "model listing" in page


# -- the re-test path ---------------------------------------------------------


def test_retest_runs_exactly_one_gate_and_recaches():
    runners = fake_runner_set(
        **{
            "exec-user-space": make_result(
                key="exec-user-space", number=1, status=FAIL, note="blocked by policy"
            ),
        }
    )
    booted = server_harness.Booted(gate_runners=runners)
    try:
        booted.server.capabilities_cache.save_result(make_result(status=PASS))
        auth = booted.exchange()
        status, headers, _b = booted.request(
            "POST",
            "/capabilities/exec-user-space/retest",
            {"Content-Type": "application/x-www-form-urlencoded",
             "Content-Length": "0", **auth},
            b"",
        )
        assert status == 303
        assert headers["Location"] == "/capabilities"
        assert runners["exec-user-space"].calls == 1
        for key in GATE_KEYS:
            if key != "exec-user-space":
                assert runners[key].calls == 0
        stored = booted.server.capabilities_cache.cached("exec-user-space")
        assert stored.result.status == FAIL
        assert stored.result.note == "blocked by policy"
    finally:
        booted.close()


def test_retest_json_answers_the_cached_record():
    runners = fake_runner_set()
    booted = server_harness.Booted(gate_runners=runners)
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/capabilities/uv-tls-bootstrap/retest", {}, auth
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["key"] == "uv-tls-bootstrap"
        assert payload["result"]["status"] == UNKNOWN
        assert "updatedTs" in payload
        assert runners["uv-tls-bootstrap"].calls == 1
        stored = booted.server.capabilities_cache.cached("uv-tls-bootstrap")
        assert stored is not None and stored.updated_ts == payload["updatedTs"]
    finally:
        booted.close()


def test_retest_of_an_unknown_gate_is_a_404_and_runs_nothing():
    runners = fake_runner_set()
    booted = server_harness.Booted(gate_runners=runners)
    try:
        auth = booted.exchange()
        status, _h, _b = booted.post_json("/capabilities/not-a-gate/retest", {}, auth)
        assert status == 404
        assert all(gate.calls == 0 for gate in runners.values())
    finally:
        booted.close()


def test_a_retested_gate_updates_the_page_but_leaves_the_others():
    runners = fake_runner_set(
        **{
            "edr-identity": make_result(
                key="edr-identity", number=5, title="EDR / AV identity", status=PASS,
                note="CrowdStrike Falcon detected",
            ),
        }
    )
    booted = server_harness.Booted(gate_runners=runners)
    try:
        booted.server.capabilities_cache.save_result(
            make_result(key="onedrive-sync", number=4, title="OneDrive", status=PASS, note="old pass")
        )
        auth = booted.exchange()
        booted.post_json("/capabilities/edr-identity/retest", {}, auth)
        _status, _h, body = booted.request("GET", "/capabilities", auth)
        page = body.decode("utf-8")
        assert "CrowdStrike Falcon detected" in page
        assert "old pass" in page
    finally:
        booted.close()


# -- the endpoint card --------------------------------------------------------


def test_the_endpoint_card_is_not_green_when_nothing_is_configured(env, auth):
    _status, _h, body = env.request("GET", "/capabilities", auth)
    page = body.decode("utf-8")
    assert "Not connected." in page
    assert "No company endpoint configured." in page
    # Never a false green: the connected wording is absent entirely.
    assert "Company endpoint configured." not in page


def test_the_endpoint_card_names_the_error_state_of_a_failing_call(env, auth):
    booted = server_harness.Booted(llm_endpoint="http://127.0.0.1:9")
    try:
        authed = booted.exchange()
        audit_store.record(
            booted.server.audit_conn, "llm.research",
            target="http://127.0.0.1:9", status="error",
        )
        _status, _h, body = booted.request("GET", "/capabilities", authed)
        page = body.decode("utf-8")
        assert "Last call:" in page
        assert "error" in page
        assert "reduced capacity" in page
    finally:
        booted.close()


def test_a_configured_endpoint_reads_connected():
    booted = server_harness.Booted(llm_endpoint="http://127.0.0.1:9")
    try:
        auth = booted.exchange()
        _status, _h, body = booted.request("GET", "/capabilities", auth)
        page = body.decode("utf-8")
        assert "Connected." in page
        assert "Company endpoint configured." in page
    finally:
        booted.close()


# -- the source cards ---------------------------------------------------------


def test_the_source_cards_read_unconfigured_when_nothing_is_wired(env, auth):
    _status, _h, body = env.request("GET", "/capabilities", auth)
    page = body.decode("utf-8")
    assert "No workbook connected yet." in page
    assert "No calendar data yet." in page
    assert page.count("unconfigured") >= 2


def _watch_with_workbook(tmp_path) -> ExcelWatch:
    workbook = tmp_path / "Q4-sales.xlsx"
    workbook.write_bytes(base_workbook())
    watch = ExcelWatch(
        sqlite3.connect(":memory:", check_same_thread=False),
        ExcelAdapters(
            copy_shadow=lambda p: Path(p),
            parse_workbook=lambda p: parse_workbook_bytes(Path(p).read_bytes()),
            clock=lambda: NOW.timestamp(),
        ),
    )
    watch.register(str(workbook))
    return watch


def _bridge_with_calendar(tmp_path, payload: bytes) -> CalendarBridge:
    calendar_file = tmp_path / "calendar_sync.json"
    calendar_file.write_bytes(payload)
    bridge = CalendarBridge(
        sqlite3.connect(":memory:", check_same_thread=False),
        CalendarAdapters(
            read_calendar=lambda: (str(calendar_file), calendar_file.read_bytes()),
            clock=lambda: NOW.timestamp(),
        ),
        llm=lambda prompt: '{"subtasks": [], "followups": []}',
    )
    bridge.poll()
    return bridge


def test_the_source_cards_read_watching_when_the_bridges_read(tmp_path):
    booted = server_harness.Booted(
        excel=_watch_with_workbook(tmp_path),
        calendar=_bridge_with_calendar(
            tmp_path,
            json.dumps({"generatedAt": NOW.isoformat(), "events": []}).encode("utf-8"),
        ),
    )
    try:
        auth = booted.exchange()
        _status, _h, body = booted.request("GET", "/capabilities", auth)
        page = body.decode("utf-8")
        assert "Watches Q4-sales.xlsx." in page
        assert "watching" in page
        assert page.count("unconfigured") == 0
    finally:
        booted.close()


def test_an_unreadable_calendar_names_the_error_state(tmp_path):
    booted = server_harness.Booted(
        calendar=_bridge_with_calendar(tmp_path, b"definitely not calendar json"),
    )
    try:
        auth = booted.exchange()
        _status, _h, body = booted.request("GET", "/capabilities", auth)
        page = body.decode("utf-8")
        assert "error" in page
    finally:
        booted.close()


def test_watch_words_are_built_from_the_constants_the_watches_export():
    # Not re-spelled literals: the watches' first-snapshot state is "first",
    # and a hand-copied tuple already drifted once. The tuples must be the
    # exported constants, so a watch renaming a state breaks this test.
    assert capabilities_view._EXCEL_WATCHING == (
        excel_core.STATE_HEALTHY, excel_core.STATE_FIRST_SNAPSHOT,
    )
    assert capabilities_view._EXCEL_ERROR == (
        excel_core.STATE_LOCKED, excel_core.STATE_UNREADABLE, excel_core.STATE_STALE,
    )
    assert capabilities_view._CALENDAR_WATCHING == (
        calendar_watcher.STATE_HEALTHY, calendar_watcher.STATE_CLEAR,
    )
    assert capabilities_view._CALENDAR_ERROR == (
        calendar_watcher.STATE_STALE, calendar_watcher.STATE_UNREADABLE,
    )


def test_the_first_snapshot_state_renders_watching():
    sources = [
        SourceStatus(SRC_EXCEL, STATUS_CONNECTED, "Watches Q4-sales.xlsx."),
        SourceStatus(SRC_CALENDAR, STATUS_NOT_CONNECTED, "No calendar data yet."),
        SourceStatus(SRC_RESEARCH, STATUS_NOT_CONNECTED, "No company endpoint configured."),
    ]
    page = capabilities_view.render_capabilities_page(
        {}, sources, {"state": excel_core.STATE_FIRST_SNAPSHOT, "cause": ""},
        None, {"configured": False, "last": "never"}, "0.1.0", now_ts=1_000.0,
    )
    assert "watching" in page
    assert "Watches Q4-sales.xlsx." in page
    assert page.count("unconfigured") == 1


# -- the settings rail, the harness, and the IT surface -----------------------


def test_settings_rails_the_capabilities_page(env, auth):
    _status, _h, body = env.request("GET", "/settings", auth)
    page = body.decode("utf-8")
    assert 'href="/capabilities"' in page


def test_a_fresh_boot_cache_has_no_gate_results(env):
    for key in GATE_KEYS:
        assert env.server.capabilities_cache.cached(key) is None


def test_the_probe_cli_still_stands_untouched():
    # The CLI stays the IT surface; this page never replaces or edits it.
    from agentdesk.probe import cli

    assert callable(cli.main)
    assert callable(cli.run_all_gates)
