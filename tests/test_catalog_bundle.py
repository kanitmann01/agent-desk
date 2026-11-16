"""The bundled catalog is generated from the shipped registry and verified."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from agentdesk.marketplace.catalog import (
    build_bundled_catalog,
    bundled_catalog_path,
)
from agentdesk.registry.index import load_index
from agentdesk.registry.install import tree_digest

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "registry"
SCRIPT = REPO / "scripts" / "build_catalog.py"


def load_catalog_module():
    spec = importlib.util.spec_from_file_location("build_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_every_shipped_plugin_is_in_the_catalog():
    module = load_catalog_module()
    catalog = module.build_catalog(REGISTRY)
    plugin_dirs = sorted(
        path.name for path in (REGISTRY / "plugins").iterdir() if path.is_dir()
    )
    assert [entry["id"] for entry in catalog["plugins"]] == plugin_dirs
    assert catalog["schemaVersion"] == 2
    assert catalog["generatedAt"]


def test_catalog_digests_match_the_plugin_trees():
    module = load_catalog_module()
    catalog = module.build_catalog(REGISTRY)
    for entry in catalog["plugins"]:
        assert entry["digest"] == tree_digest(REGISTRY / "plugins" / entry["id"])


def test_catalog_ids_match_the_index():
    module = load_catalog_module()
    catalog = module.build_catalog(REGISTRY)
    index = load_index((REGISTRY / "index.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in catalog["plugins"]] == [
        plugin.id for plugin in index.plugins
    ]
    by_id = {entry["id"]: entry for entry in catalog["plugins"]}
    for plugin in index.plugins:
        assert by_id[plugin.id]["latest"] == plugin.latest
        releases = {release.version: release for release in plugin.releases}
        latest = releases[plugin.latest]
        assert by_id[plugin.id]["digest"] == latest.sha256


def test_committed_bundle_pins_are_authoritative_over_a_drifted_checkout(tmp_path):
    """A mutated checkout tree must not silently rewrite the shipped digest."""
    committed = json.loads(bundled_catalog_path().read_text(encoding="utf-8"))
    plugin_id = committed["plugins"][0]["id"]
    pinned = {entry["id"]: entry for entry in committed["plugins"]}[plugin_id]

    registry = tmp_path / "registry"
    shutil.copytree(REGISTRY, registry)
    manifest = registry / "plugins" / plugin_id / "manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n",
                        encoding="utf-8")
    assert tree_digest(registry / "plugins" / plugin_id) != pinned["digest"]

    catalog = build_bundled_catalog(registry)
    entry = {item["id"]: item for item in catalog["plugins"]}[plugin_id]
    assert entry["digest"] == pinned["digest"]
    assert entry["digest"] != tree_digest(registry / "plugins" / plugin_id)


def test_catalog_cli_writes_the_bundle(tmp_path):
    out = tmp_path / "catalog.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--registry", str(REGISTRY), "--out", str(out)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["schemaVersion"] == 2
    assert len(document["plugins"]) >= 5
