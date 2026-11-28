"""The hand-kept number: the tile's save form route and the card that shows it.

A tile watching a number the manager keeps is useless without a way to set
it, so the marketplace route writes the object the reader already reads, and
the card carries the form that reaches that route. These tests cover both
halves through their public entry points.
"""

import json
from pathlib import Path

import pytest

from .plugins_fixtures import valid_zip

NOW = "2026-11-11T16:00:00"


@pytest.fixture()
def boot(tmp_path):
    """A booted server with a plugin runtime and a session, like the API suite's."""
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


def _post(booted, path: str, payload: dict) -> tuple[int, dict]:
    status, _headers, body = booted.post_json(path, payload, booted.auth)
    return status, json.loads(body)


def _write_manual_plugin(tmp_path: Path, root: Path) -> Path:
    """A zip whose one widget watches a hand-kept number."""
    return valid_zip(tmp_path / "manual.zip", overrides={
        "id": "kept-number",
        "name": "Kept number",
        "permissions": {
            "filesystem": {"read": [], "write": ["${pluginData}"]},
            "network": {"allow": []},
            "llm": {"allow": False},
            "shell": "none",
        },
        "activationEvents": ["onWidget:kept", "onHook:manual"],
        "contributes": {"widgets": [{
            "id": "kept",
            "size": "2x1",
            "dataSource": {"type": "manual-metric"},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    })


def test_saving_a_value_writes_the_file_the_reader_reads(boot, tmp_path):
    plugin = boot.server.plugins.install(str(_write_manual_plugin(tmp_path, tmp_path)),
                                         source="zip")
    data_dir = Path(boot.server.plugins.record(plugin["id"])["data_dir"])

    status, body = _post(boot, "/api/marketplace/manual-value",
                         {"id": plugin["id"], "value": 42, "unit": "deals",
                          "target": 50})

    assert status == 200, body
    written = json.loads((data_dir / "manual.json").read_text(encoding="utf-8"))
    assert written["value"] == 42
    assert written["unit"] == "deals"
    assert written["target"] == 50
    assert written["updatedAt"]
    # The series the tile's trend reads starts with this value.
    assert written["history"][-1]["value"] == 42


def test_a_second_save_extends_the_history(boot, tmp_path):
    plugin = boot.server.plugins.install(str(_write_manual_plugin(tmp_path, tmp_path)),
                                         source="zip")
    data_dir = Path(boot.server.plugins.record(plugin["id"])["data_dir"])
    _post(boot, "/api/marketplace/manual-value", {"id": plugin["id"], "value": 10})
    _post(boot, "/api/marketplace/manual-value", {"id": plugin["id"], "value": 20})

    written = json.loads((data_dir / "manual.json").read_text(encoding="utf-8"))
    assert [entry["value"] for entry in written["history"]] == [10, 20]


def test_a_value_that_is_not_a_number_is_refused(boot, tmp_path):
    plugin = boot.server.plugins.install(str(_write_manual_plugin(tmp_path, tmp_path)),
                                         source="zip")
    data_dir = Path(boot.server.plugins.record(plugin["id"])["data_dir"])

    status, body = _post(boot, "/api/marketplace/manual-value",
                         {"id": plugin["id"], "value": "lots"})

    assert status == 400
    assert body["error"] == "manual-value:bad"
    assert not (data_dir / "manual.json").exists()


def test_an_unknown_plugin_is_a_named_404(boot):
    status, body = _post(boot, "/api/marketplace/manual-value",
                         {"id": "not-installed", "value": 1})

    assert status == 404
    assert body["error"] == "plugin:unknown"


def test_the_tile_carries_the_form_that_reaches_that_route(boot, tmp_path):
    """The card names the plugin a hand-kept number belongs to, which is what
    the SPA's form posts back; a number nobody can set is a broken tile."""
    plugin = boot.server.plugins.install(str(_write_manual_plugin(tmp_path, tmp_path)),
                                         source="zip")
    status, _headers, body = boot.request("GET", "/api/dashboard", headers=boot.auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == plugin["id"])

    assert card["manualMetric"] == plugin["id"]
