"""GET /api/plugins/<id>/instances: the list the manage view renders.

Ticket T5 (specs/006): the marketplace manage surface needs a plugin's
instances over HTTP. The endpoint answers a config-backed plugin with its
instance documents, resolves an alias plugin to the one named instance
of its target, answers an empty list for a plain plugin, and refuses an
unknown plugin id with the standard not-found envelope.
"""

import json
from pathlib import Path

import pytest

from server_harness import Booted
from tests.plugin_fixtures import write_alias_plugin

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry" / "plugins"


@pytest.fixture
def booted(tmp_path):
    from nexuusbot.plugins.runtime import PluginRuntime

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=workspace,
    )
    runtime.install(REGISTRY / "excel-report", source="dir")
    server = Booted(plugins=runtime)
    try:
        yield server
    finally:
        server.close()


def get_listing(server, plugin_id):
    auth = server.exchange()
    status, _headers, body = server.request(
        "GET", f"/api/plugins/{plugin_id}/instances", auth)
    return status, json.loads(body)


def test_a_config_backed_plugin_lists_the_instances_it_was_given(booted):
    server = booted
    auth = server.exchange()
    for name in ("Pipeline", "Board pack"):
        status, _headers, body = server.post_json(
            "/api/plugins/excel-report/instances", {"name": name}, auth)
        assert status == 200, body

    status, listing = get_listing(server, "excel-report")
    assert status == 200, listing
    assert listing["pluginId"] == "excel-report"
    assert listing["configBacked"] is True
    assert listing["aliasOf"] is None
    assert listing["setupPluginId"] == "excel-report"
    assert listing["setupPluginName"] == "Workbook tracker"
    by_id = {item["instanceId"]: item for item in listing["instances"]}
    assert set(by_id) == {"pipeline", "board-pack"}
    assert by_id["pipeline"]["name"] == "Pipeline"
    assert by_id["board-pack"]["confirmedAt"] is None
    assert by_id["pipeline"]["source"] is None


def test_an_alias_lists_the_target_instance_it_resolves_to(booted, tmp_path):
    server = booted
    runtime = server.server.plugins
    runtime.install(write_alias_plugin(
        tmp_path, "sales-delta-widget", "Sales 24h Delta", "Sales",
        tags=("sales", "pipeline", "daily-delta"), widget_id="sales-delta"),
        source="dir")

    status, listing = get_listing(server, "sales-delta-widget")
    assert status == 200, listing
    assert listing["pluginId"] == "sales-delta-widget"
    assert listing["configBacked"] is True
    assert listing["aliasOf"] == "excel-report"
    assert listing["setupPluginId"] == "excel-report"
    assert listing["setupPluginName"] == "Workbook tracker"
    assert len(listing["instances"]) == 1
    resolved = listing["instances"][0]
    assert resolved["instanceId"] == "sales"
    assert resolved["name"] == "Sales"
    assert resolved["confirmedAt"] is None


def test_a_plain_plugin_answers_an_empty_list(booted, tmp_path):
    server = booted
    runtime = server.server.plugins
    runtime.install(REGISTRY / "competitor-watch", source="dir")

    status, listing = get_listing(server, "competitor-watch")
    assert status == 200, listing
    assert listing["pluginId"] == "competitor-watch"
    assert listing["configBacked"] is False
    assert listing["aliasOf"] is None
    assert listing["instances"] == []


def test_an_unknown_plugin_id_is_not_found(booted):
    server = booted
    status, listing = get_listing(server, "who-is-this")
    assert status == 404
    assert listing["error"] == "plugin:unknown"


def test_unknown_path_shapes_stay_not_found(booted):
    server = booted
    auth = server.exchange()
    for path in (
        "/api/plugins/excel-report/instances/main",
        "/api/plugins/excel-report/instances/main/nope",
    ):
        status, _headers, body = server.request("GET", path, auth)
        assert status == 404, path
        assert json.loads(body)["error"] == "not-found", path
