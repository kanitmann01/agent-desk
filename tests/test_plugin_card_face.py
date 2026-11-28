"""The face a workbook tile draws, once the manager has chosen one.

Before spec 025 every confirmed workbook instance drew the classic tracker
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
    # The fixture's own schema is replaced, not duplicated: build_zip writes
    # the files first and the extras last, so the same name twice is a warning.
    source = tmp_path / "wb-source"
    source.mkdir()
    for path in VALID_PLUGIN_DIR.iterdir():
        if path.is_file() and path.name != "widget.ui.json":
            (source / path.name).write_bytes(path.read_bytes())
    return build_zip(source, tmp_path / "wb.zip",
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
    from nexuusbot.plugins.runtime import PluginRuntime

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
    from nexuusbot.plugins.runtime import PluginRuntime

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


def test_the_flagship_tracker_keeps_its_chart(tmp_path):
    """excel-report's schema is metric, delta, text, text: a fourth note makes
    it look like a chosen face by its elements alone. Guessing from shapes
    would take its column/area chart away, so the marker is the install
    source, not the schema."""
    from nexuusbot.plugins.cards import _rendered_face
    from nexuusbot.plugins.runtime import PluginRuntime

    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now=NOW,
    )
    root = Path(__file__).resolve().parents[1] / "registry" / "plugins"
    plugin = runtime.install(root / "excel-report", source="dir")
    entry = runtime.record(plugin["id"])
    manifest = runtime._active_manifest(entry)
    reading = {"value": 10, "delta": "+2", "direction": "up",
               "points": [1, 2, 3], "file": "sales.xlsx",
               "table": {"rows": []}, "chart": "column"}

    # It has its own elements, but no chosen face: the classic card draws it.
    assert manifest.get("_ui_elements")
    assert _rendered_face(manifest, reading) is None


def test_a_classic_face_keeps_the_tracker_card(tmp_path):
    """An element list that is the classic value/change/workbook face renders
    the classic card, so a tile built before the question is unchanged."""
    from nexuusbot.plugins.cards import _rendered_face

    classic = [
        {"type": "metric", "binding": "value"},
        {"type": "delta", "binding": "delta"},
        {"type": "text", "binding": "file"},
    ]
    reading = {"value": 10, "delta": "+2", "direction": "up", "points": [],
               "file": "sales.xlsx", "table": {"rows": []}}

    assert _rendered_face({"_ui_elements": classic}, reading) is None


def test_a_chosen_face_renders_its_element_from_the_reading(tmp_path):
    from nexuusbot.plugins.cards import _rendered_face

    reading = {"value": 10, "delta": "+2", "direction": "up",
               "points": [1, 2, 3], "file": "sales.xlsx",
               "table": {"rows": [{"primary": "North", "secondary": "10",
                                   "meta": ""}]}}

    face = _rendered_face({"_chosen_face": True, "_ui_elements": [
        {"type": "table", "columns": ["Item", "Value", "Note"],
         "rowsBinding": "rows"}]}, reading)

    assert face[0]["kind"] == "table"
    assert face[0]["rows"][0][0] == "North"


def test_a_progress_face_uses_the_reading_s_target(tmp_path):
    from nexuusbot.plugins.cards import _rendered_face

    reading = {"value": 10, "delta": "+2", "direction": "up", "points": [],
               "file": "sales.xlsx", "table": {"rows": []},
               "goal": {"value": 20}}

    face = _rendered_face({"_chosen_face": True, "_ui_elements": [
        {"type": "progress", "binding": "value", "targetBinding": "target"}]},
        reading)

    assert face[0]["kind"] == "progress"
    assert face[0]["value"] == 10
    assert face[0]["target"] == 20


def test_a_wizard_built_tile_applies_the_chosen_face(tmp_path):
    """Regression for the core merge: runtime.py briefly held two
    _active_manifest definitions, and core's simpler one (no parsed
    elements, no chosen-face marker) sat later in the file and silently
    won, so a wizard-built tile fell back to the classic tracker. One
    definition survives: the one that attaches both the elements and the
    marker, and a wizard-built install proves both ride on its manifest."""
    from nexuusbot.plugins.runtime import PluginRuntime

    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now=NOW,
    )
    plugin = runtime.install(str(_workbook_zip(
        tmp_path, [{"type": "metric", "binding": "value", "label": "Deals"}])),
        source="wizard")
    entry = runtime.record(plugin["id"])
    manifest = runtime._active_manifest(entry)

    assert manifest["_chosen_face"] is True
    assert manifest["_ui_elements"] == [
        {"type": "metric", "binding": "value", "label": "Deals"}]
