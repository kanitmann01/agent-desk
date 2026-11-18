"""Studio's personal install path: create, validate, install, usable."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from server_harness import Booted


def _payload(plugin_id="studio-demo", version="0.1.0"):
    manifest = {
        "schemaVersion": 2,
        "id": plugin_id,
        "name": "Studio demo",
        "version": version,
        "publisher": "local",
        "class": "declarative",
        "engines": {"dashboardHost": ">=0.1.0"},
        "license": "MIT",
        "category": "reference",
        "tags": ["demo"],
        "icon": "plugin",
        "summary": "A plugin created in the Studio.",
        "description": "A plugin created in the Studio.",
        "highlights": ["Local", "Declarative", "Read only"],
        "permissions": {
            "filesystem": {"read": [], "write": []},
            "network": {"allow": []},
            "llm": {"allow": False},
            "shell": "none",
        },
        "activationEvents": [f"onWidget:{plugin_id}"],
        "contributes": {"widgets": [{
            "id": plugin_id,
            "size": "2x1",
            "dataSource": {"type": "manual-metric"},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
        "sample": "sample.json",
        "minHost": ">=0.1.0",
    }
    widget = {
        "type": "card",
        "title": "Studio demo",
        "elements": [
            {"type": "metric", "label": "Value", "binding": "value"},
            {"type": "text", "label": "Last updated", "binding": "lastUpdated"},
        ],
    }
    sample = {"bindings": {"value": 0, "lastUpdated": "Never"},
              "state": "ok", "checkedAt": "2026-11-18T09:00:00Z"}
    return {"manifest": manifest, "widgetUi": widget, "sample": sample}


@pytest.fixture()
def booted():
    boot = Booted()
    boot.auth = boot.exchange()
    try:
        yield boot
    finally:
        boot.close()


def test_a_studio_plugin_installs_on_this_desk(booted):
    status, _h, body = booted.post_json(
        "/api/marketplace/studio/install", _payload(), booted.auth)
    assert status == 200, body
    result = json.loads(body)
    assert result["status"] == "installed"
    assert result["id"] == "studio-demo"
    assert result["version"] == "0.1.0"
    record = booted.server.plugins.record("studio-demo")
    assert record is not None
    assert record["state"] != "uninstalled"
    active = Path(record["versions"][-1]["dir"])
    assert active.is_dir()
    assert (active / "widget.ui.json").is_file()
    manual = Path(record["data_dir"]) / "manual.json"
    assert manual.is_file()
    assert record["data_source"]["status"] == "fresh", record["data_source"]
    seeded = json.loads(manual.read_text(encoding="utf-8"))
    assert seeded["value"] == 0
    assert seeded["updatedAt"]


def test_an_invalid_studio_plugin_is_refused(booted):
    payload = _payload("broken-plugin")
    payload["manifest"]["license"] = ""
    status, _h, body = booted.post_json(
        "/api/marketplace/studio/install", payload, booted.auth)
    assert status == 400, body
    error = json.loads(body)
    assert error["error"] == "studio:validation-failed"
    from agentdesk.plugins.runtime import PluginError
    with pytest.raises(PluginError):
        booted.server.plugins.record("broken-plugin")
