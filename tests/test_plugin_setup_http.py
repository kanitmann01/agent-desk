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
