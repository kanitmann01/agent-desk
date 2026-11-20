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


def test_the_committed_bundle_is_fresh_against_the_registry():
    """The committed bundle's pins are the registry's current pins.

    The bundle is what a fresh desk installs from; a stale bundle would
    offer an old release while the registry review checks the new one.
    """
    committed = json.loads(bundled_catalog_path().read_text(encoding="utf-8"))
    index = load_index((REGISTRY / "index.json").read_text(encoding="utf-8"))
    assert {entry["id"] for entry in committed["plugins"]} == {
        plugin.id for plugin in index.plugins
    }
    for entry in committed["plugins"]:
        plugin = index.plugin(entry["id"])
        assert plugin is not None, entry["id"]
        assert entry["latest"] == plugin.latest
        release = plugin.release_for(plugin.latest)
        assert release is not None, entry["id"]
        assert entry["digest"] == release.sha256, entry["id"]


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
    manifest_summary = json.loads(manifest.read_text(encoding="utf-8"))["summary"]
    assert entry["summary"] == manifest_summary
    assert entry["summary"]


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
    assert len(document["plugins"]) == 2


def test_the_downloads_flag_lands_after_nuitka_not_between_m_and_nuitka():
    """The CI build passes --allow-downloads, so its flag position is CI load-bearing.

    python -m nuitka --assume-yes-for-downloads ... is the command; an insert
    at the wrong index turns it into "No module named
    --assume-yes-for-downloads" and fails every CI build.
    """
    from scripts.build_bundle import _build_command

    cmd = _build_command(Path("."), allow_downloads=True)
    assert cmd[1:4] == ["-m", "nuitka", "--assume-yes-for-downloads"], cmd[:5]
    without = _build_command(Path("."), allow_downloads=False)
    assert without[1:3] == ["-m", "nuitka"]
    assert "--assume-yes-for-downloads" not in without


ARCHIVE = REPO / "archive" / "plugins"
SHIPPED = {"competitor-watch", "excel-report"}


def test_the_archive_is_outside_every_shipped_surface():
    """Keep the retired trees where no shipped surface can pick them up.

    The archive holds the 23 retired trees, but this test deliberately does
    not read its contents: it proves the boundary instead. The archive sits
    outside the registry scan and outside the packaged source tree, and every
    shipped plugin list carries exactly the two surviving ids, so no archived
    tree can be published or installed.
    """
    assert ARCHIVE.is_dir()
    assert not ARCHIVE.is_relative_to(REGISTRY)
    assert not ARCHIVE.is_relative_to(REPO / "src")

    shipped_dirs = {path.name for path in (REGISTRY / "plugins").iterdir()
                    if path.is_dir()}
    assert shipped_dirs == SHIPPED

    catalog = load_catalog_module().build_catalog(REGISTRY)
    assert {entry["id"] for entry in catalog["plugins"]} == SHIPPED

    index = load_index((REGISTRY / "index.json").read_text(encoding="utf-8"))
    assert {plugin.id for plugin in index.plugins} == SHIPPED

    committed = json.loads(bundled_catalog_path().read_text(encoding="utf-8"))
    assert {entry["id"] for entry in committed["plugins"]} == SHIPPED


def test_the_packaged_build_never_reaches_the_archive():
    """The packaged inputs are the agentdesk package and its static assets.

    The build command names neither the archive folder nor anything under it;
    the only plugin list it can carry is the committed bundle, whose ids the
    test above pins to the two survivors. Engine-level render support for
    installed copies (card kinds, insight families) is not a shipped tree.
    """
    from scripts.build_bundle import _build_command

    command = _build_command(REPO, allow_downloads=False)
    assert not any("archive" in part for part in command), command
    assert not (REPO / "src" / "archive").exists()
