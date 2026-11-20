"""Fixture builders shared by the plugin tests."""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry" / "plugins"


def write_alias_plugin(tmp_path, plugin_id, name, instance_name, tags=(),
                       widget_id=None):
    """Build a config-backed alias of the surviving workbook plugin.

    The retired sales-delta-widget and budget-burn were aliases like this:
    a manifest that points at excel-report and names one tracker instance.
    The helper keeps the alias contract testable without shipping the
    retired trees.
    """
    directory = Path(tmp_path) / plugin_id
    shutil.copytree(REGISTRY / "excel-report", directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest.update({
        "id": plugin_id,
        "name": name,
        "category": "finance",
        "config": {
            "kinds": ["workbook"],
            "aliasOf": "excel-report",
            "instanceName": instance_name,
            "good": "up",
        },
        "tags": list(tags),
        "icon": "chart",
    })
    widget = manifest["contributes"]["widgets"][0]
    widget["id"] = widget_id or plugin_id
    manifest["activationEvents"] = [f"onWidget:{widget['id']}"]
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return directory
