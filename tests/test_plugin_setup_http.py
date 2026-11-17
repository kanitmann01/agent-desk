"""The tracker setup over the real HTTP server: open, suggest, confirm."""

import json
from pathlib import Path

import pytest

from server_harness import Booted
from tests import excel_fixtures


@pytest.fixture
def booted(tmp_path):
    from agentdesk.plugins.runtime import PluginRuntime

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=workspace,
    )
    runtime.install(Path(__file__).resolve().parents[1] / "registry" / "plugins" / "excel-report", source="dir")
    server = Booted(
        plugins=runtime,
        pick_workbook=lambda: str(book),
        llm=lambda _prompt: '{"labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum"}',
        llm_endpoint="http://llm.test/v1",
    )
    try:
        yield server, book
    finally:
        server.close()


def test_open_suggest_and_confirm_lands_on_the_tracker(booted):
    server, _book = booted
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/pick",
        {"name": "Workbook tracker"}, auth)
    assert status == 200, body
    opened = json.loads(body)
    assert opened["preview"]["headers"] == ["Region", "Booked"]

    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/suggest", {}, auth)
    assert status == 200, body
    suggested = json.loads(body)
    assert "up to 5 rows" in suggested["disclosure"]
    assert suggested["proposal"]["valueColumn"] == "Booked"
    assert "q4.xlsx" not in json.dumps(suggested)

    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/confirm",
        {"tracking": suggested["proposal"], "suggested": True}, auth)
    assert status == 200, body

    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["title"] == "Workbook tracker" or item["id"].startswith("excel-report"))
    assert card["freshness"] == "fresh"
    metrics = {element["label"]: element["value"] for element in card["payload"]["elements"] if element["kind"] == "metric"}
    assert metrics["Value"] == "15"


@pytest.fixture
def booted_pack(tmp_path):
    """The tracker desk with a second config-backed plugin that is not
    the historical tracker: the qbr-pack fixture under tests/fixtures."""
    from agentdesk.plugins.runtime import PluginRuntime

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    root = Path(__file__).resolve().parents[1]
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=workspace,
    )
    runtime.install(root / "registry" / "plugins" / "excel-report", source="dir")
    runtime.install(root / "tests" / "fixtures" / "plugins" / "qbr-pack", source="dir")
    server = Booted(
        plugins=runtime,
        pick_workbook=lambda: str(book),
        llm=lambda _prompt: '{"labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum"}',
        llm_endpoint="http://llm.test/v1",
    )
    try:
        yield server, book
    finally:
        server.close()


def test_a_config_backed_plugin_that_is_not_the_tracker_shows_its_setup_card(booted_pack):
    """The dashboard expands the fixture plugin into its own wireframe
    card with a Set up entry, exactly like the tracker's."""
    server, _book = booted_pack
    auth = server.exchange()
    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack")
    assert card["freshness"] == "setup"
    assert card["payload"]["setup"]["pluginId"] == "qbr-pack"
    assert card["payload"]["setup"]["step"] == "source"
    assert card["payload"]["elements"] == []


def test_the_whole_chain_serves_the_fixture_plugin_over_http(booted_pack):
    """Create, pick, stage, preview, confirm over real HTTP for a plugin
    that is not the tracker, then the dashboard reads exactly the
    confirmed file, and the seventh instance hits the cap."""
    server, _book = booted_pack
    auth = server.exchange()

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances", {"name": "Pipeline"}, auth)
    assert status == 200, body
    status, _headers, body = server.request(
        "GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "setup"
    assert card["payload"]["setup"]["step"] == "source"

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/pick",
        {"name": "Pipeline"}, auth)
    assert status == 200, body
    opened = json.loads(body)
    assert opened["preview"]["headers"] == ["Region", "Booked"]

    status, _headers, body = server.request(
        "GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["payload"]["setup"]["step"] == "columns"

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/confirm",
        {"tracking": {"labelColumn": "Region", "valueColumn": "Booked",
                      "aggregate": "sum"}}, auth)
    assert status == 200, body

    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "fresh"
    metrics = {element["label"]: element["value"]
               for element in card["payload"]["elements"]
               if element["kind"] == "metric"}
    assert metrics["Value"] == "15"

    for index in range(1, 6):
        status, _headers, _body = server.post_json(
            "/api/plugins/qbr-pack/instances", {"name": f"Extra {index}"}, auth)
        assert status == 200, _body
    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances", {"name": "One too many"}, auth)
    assert status == 400, body
    assert json.loads(body)["error"] == "config:cap"


def test_confirm_carries_the_selected_rows_and_the_card_reads_only_them(booted_pack):
    """T4: the confirm body's tracking.rows (ordered zero-based data rows)
    reach the stored config over the real endpoint, and the dashboard card
    then reads exactly the selected rows' values."""
    server, _book = booted_pack
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/pick", {"name": "Pipeline"}, auth)
    assert status == 200, body

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/confirm",
        {"tracking": {"labelColumn": "Region", "valueColumn": "Booked",
                      "aggregate": "sum", "rows": [0]}}, auth)
    assert status == 200, body
    saved = json.loads(body)
    assert saved["instance"]["tracking"]["rows"] == [0]

    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "fresh"
    metrics = {element["label"]: element["value"]
               for element in card["payload"]["elements"]
               if element["kind"] == "metric"}
    assert metrics["Value"] == "10"


def test_a_stale_row_selection_is_refused_over_http(booted_pack):
    """T4: rows past the staged file's data rows keep the existing
    stale-config refusal shape over HTTP: 400 with the mismatched-file
    code, and the instance stays unconfirmed."""
    server, _book = booted_pack
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/pick", {"name": "Pipeline"}, auth)
    assert status == 200, body

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/confirm",
        {"tracking": {"labelColumn": "Region", "valueColumn": "Booked",
                      "aggregate": "sum", "rows": [9]}}, auth)
    assert status == 400, body
    assert json.loads(body)["error"] == "config:not-granted"

    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "setup"
