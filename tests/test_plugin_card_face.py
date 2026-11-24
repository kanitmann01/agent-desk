"""The face a workbook tile draws, once the manager has chosen one.

Before spec 024 every confirmed workbook instance drew the classic tracker
face: value, change, workbook, trend. A tile built by describing it may ask
for a big number, a table, a bar or a trend instead, and the card the runtime
serves has to draw what was asked. A tile with no chosen face, and every
plugin built before the question existed, keeps the classic one.
"""

import json
from pathlib import Path

import pytest

NOW = "2026-11-11T16:00:00"


def _workbook_zip(tmp_path: Path, elements: list) -> Path:
    """A config-backed workbook plugin whose ui-schema asks for these elements."""
    from .plugins_fixtures import build_zip, VALID_PLUGIN_DIR

    schema = json.dumps({"type": "card", "title": "Workbook face",
                         "elements": elements}, indent=2)
    return build_zip(VALID_PLUGIN_DIR, tmp_path / "wb.zip",
                     manifest_overrides={
                         "id": "wb-face",
                         "name": "Workbook face",
                         "permissions": {
                             "filesystem": {"read": [], "write": ["${pluginData}"]},
                             "network": {"allow": []},
                             "llm": {"allow": False},
                             "shell": "none",
                         },
                         "config": {"kinds": ["workbook"]},
                         "activationEvents": ["onWidget:wb"],
                         "contributes": {"widgets": [{
                             "id": "wb",
                             "size": "2x1",
                             "dataSource": {"type": "excel-watch"},
                             "render": {"type": "ui-schema",
                                        "file": "widget.ui.json"},
                         }]},
                     },
                     extra_file=("widget.ui.json", schema))


@pytest.fixture()
def boot(tmp_path):
    import server_harness
    from agentdesk.plugins.runtime import PluginRuntime

    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now=NOW,
    )
    booted = server_harness.Booted(plugins=runtime)
    try:
        booted.auth = booted.exchange()
        yield booted
    finally:
        booted.close()


def _cards(boot) -> list:
    status, _headers, body = boot.request("GET", "/api/dashboard", headers=boot.auth)
    assert status == 200
    return json.loads(body)["plugins"]["cards"]


def test_a_chosen_face_is_served_instead_of_the_classic_tracker(boot, tmp_path):
    plugin = boot.server.plugins.install(
        str(_workbook_zip(tmp_path, [{"type": "metric", "binding": "value",
                                      "label": "Deals"}])), source="zip")
    card = next(c for c in _cards(boot) if c["id"] == plugin["id"])

    # Before an instance is confirmed there is a setup card, not a face.
    assert card["freshness"] == "setup"
    assert card["payload"]["setup"]["pluginId"] == plugin["id"]


def test_the_runtime_reads_the_chosen_face_from_the_manifest(tmp_path):
    """The manifest the runtime hands a card carries the parsed elements, which
    is how the card learns what was asked for without a second file read."""
    from agentdesk.plugins.runtime import PluginRuntime

    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now=NOW,
    )
    plugin = runtime.install(str(_workbook_zip(
        tmp_path, [{"type": "metric", "binding": "value", "label": "Deals"}])),
        source="zip")
    entry = runtime.record(plugin["id"])
    manifest = runtime._active_manifest(entry)

    assert manifest["_ui_elements"] == [
        {"type": "metric", "binding": "value", "label": "Deals"}]


def test_a_classic_face_keeps_the_tracker_card(tmp_path):
    """An element list that is the classic value/change/workbook face renders
    the classic card, so a tile built before the question is unchanged."""
    from agentdesk.plugins.cards import _rendered_face

    classic = [
        {"type": "metric", "binding": "value"},
        {"type": "delta", "binding": "delta"},
        {"type": "text", "binding": "file"},
    ]
    reading = {"value": 10, "delta": "+2", "direction": "up", "points": [],
               "file": "sales.xlsx", "table": {"rows": []}}

    assert _rendered_face({"_ui_elements": classic}, reading) is None


def test_a_chosen_face_renders_its_element_from_the_reading(tmp_path):
    from agentdesk.plugins.cards import _rendered_face

    reading = {"value": 10, "delta": "+2", "direction": "up",
               "points": [1, 2, 3], "file": "sales.xlsx",
               "table": {"rows": [{"primary": "North", "secondary": "10",
                                   "meta": ""}]}}

    face = _rendered_face({"_ui_elements": [
        {"type": "table", "columns": ["Item", "Value", "Note"],
         "rowsBinding": "rows"}]}, reading)

    assert face[0]["kind"] == "table"
    assert face[0]["rows"][0][0] == "North"


def test_a_progress_face_uses_the_reading_s_target(tmp_path):
    from agentdesk.plugins.cards import _rendered_face

    reading = {"value": 10, "delta": "+2", "direction": "up", "points": [],
               "file": "sales.xlsx", "table": {"rows": []},
               "goal": {"value": 20}}

    face = _rendered_face({"_ui_elements": [
        {"type": "progress", "binding": "value", "targetBinding": "target"}]},
        reading)

    assert face[0]["kind"] == "progress"
    assert face[0]["value"] == 10
    assert face[0]["target"] == 20
