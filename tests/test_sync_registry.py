"""sync_registry risk tiering: optional permissions count (audit tooling F1).

The one network plugin in the registry declares its network access under
optionalPermissions, so a risk tier that reads only the required block
indexed a network plugin as "low" while its own README calls it the
network plugin. These tests pin the honest tier for both blocks.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO / "src"), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sync_registry  # noqa: E402  (scripts/ is not a package)


def _tier(tmp_path: Path, manifest: dict) -> str:
    root = tmp_path / "registry"
    plugin = root / "plugins" / manifest["id"]
    plugin.mkdir(parents=True)
    (plugin / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"schemaVersion": 1, "plugins": []}), encoding="utf-8")
    document = sync_registry.sync(root)
    return document["plugins"][0]["risk"]


def test_required_network_allowance_tiers_medium(tmp_path):
    assert _tier(tmp_path, {
        "id": "net-widget", "version": "0.1.0",
        "permissions": {"network": {"allow": ["example.com"]}},
    }) == "medium"


def test_optional_network_allowance_tiers_medium(tmp_path):
    # competitor-watch declares exactly this shape: no required network,
    # one optional host the user is prompted for. The tier must see it.
    assert _tier(tmp_path, {
        "id": "net-widget", "version": "0.1.0",
        "permissions": {"network": {"allow": []}},
        "optionalPermissions": {"network": {"allow": ["example.com"]}},
    }) == "medium"


def test_no_network_anywhere_tiers_low(tmp_path):
    assert _tier(tmp_path, {
        "id": "calm-widget", "version": "0.1.0",
        "permissions": {},
        "optionalPermissions": {"network": {"allow": []}},
    }) == "low"
