"""Pinned install through the public API (ticket #10).

Installing verifies the release hash and refuses on mismatch. Lockfile
pins keep resolving when the index moves: releases are append-only
history, and a yanked release resolves only for a client that pins its
exact digest.
"""
import json

import pytest

from .registry_fixtures import make_registry, tree_digest


def digest_of(repo):
    from nexuusbot.registry.index import load_index
    index = load_index((repo / "index.json").read_text(encoding="utf-8"))
    return index.plugins[0].releases[0].sha256


def test_install_pinned_by_recorded_hash(tmp_path):
    repo = make_registry(tmp_path)
    sha = digest_of(repo)
    from nexuusbot.registry.install import install_from_registry
    out = install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                                sha256=sha, destination=tmp_path / "plugins")
    assert out["ok"] is True
    installed = tmp_path / "plugins" / "sales-delta-widget-1.2.0"
    assert (installed / "manifest.json").is_file()
    assert (installed / "widget.ui.json").is_file()


def test_install_refuses_on_hash_mismatch(tmp_path):
    repo = make_registry(tmp_path)
    from nexuusbot.registry.install import RegistryError, install_from_registry
    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                              sha256="0" * 64, destination=tmp_path / "plugins")
    assert excinfo.value.code == "install:hash-mismatch"


def test_install_refuses_tampered_index(tmp_path):
    """The pin in the index does not match the tagged content: refuse."""
    repo = make_registry(tmp_path)
    index_path = repo / "index.json"
    document = json.loads(index_path.read_text(encoding="utf-8"))
    document["plugins"][0]["releases"][0]["sha256"] = "1" * 64
    index_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    from nexuusbot.registry.install import RegistryError, install_from_registry
    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                              destination=tmp_path / "plugins")
    assert excinfo.value.code == "install:hash-mismatch"


def test_install_refuses_unknown_plugin_and_version(tmp_path):
    repo = make_registry(tmp_path)
    from nexuusbot.registry.install import RegistryError, install_from_registry
    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(repo, "ghost-plugin", version="1.0.0",
                              destination=tmp_path / "plugins")
    assert excinfo.value.code == "install:unknown-plugin"
    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(repo, "sales-delta-widget", version="9.9.9",
                              destination=tmp_path / "plugins")
    assert excinfo.value.code == "install:unknown-version"


def _add_release(repo, new_version, new_tag, yanked=False):
    """Move the index: append a release (and optionally yank an old one)."""
    index_path = repo / "index.json"
    document = json.loads(index_path.read_text(encoding="utf-8"))
    plugin = document["plugins"][0]
    digest = plugin["releases"][0]["sha256"]
    plugin["releases"].append(
        {"version": new_version, "sha256": digest, "tag": new_tag,
         "yanked": yanked})
    plugin["latest"] = new_version
    index_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def test_old_lockfile_pin_resolves_after_index_moves(tmp_path):
    from nexuusbot.registry.install import install_from_registry
    repo = make_registry(tmp_path)
    old_sha = digest_of(repo)
    _add_release(repo, "1.3.0", "sales-delta-widget-1.3.0")
    out = install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                                sha256=old_sha, destination=tmp_path / "plugins")
    assert out["version"] == "1.2.0"


def test_yanked_release_resolves_only_with_exact_pin(tmp_path):
    from nexuusbot.registry.install import RegistryError, install_from_registry
    repo = make_registry(tmp_path)
    old_sha = digest_of(repo)
    _add_release(repo, "1.3.0", "sales-delta-widget-1.3.0")
    index_path = repo / "index.json"
    document = json.loads(index_path.read_text(encoding="utf-8"))
    document["plugins"][0]["releases"][0]["yanked"] = True
    index_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                              destination=tmp_path / "a")
    assert excinfo.value.code == "install:yanked"

    out = install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                                sha256=old_sha, destination=tmp_path / "b")
    assert out["version"] == "1.2.0"


def test_local_release_resolves_versioned_then_flat_tree(tmp_path):
    """A checkout with one local release can install it from plugins/<id>."""
    from nexuusbot.registry.install import local_release_source

    flat = tmp_path / "plugins" / "local-only"
    flat.mkdir(parents=True)
    (flat / "manifest.json").write_text(
        json.dumps({"version": "1.0.0"}), encoding="utf-8")
    assert local_release_source(tmp_path, "local-only", "1.0.0") == flat
    assert local_release_source(tmp_path, "local-only", "0.9.0") is None

    versioned = tmp_path / "plugins" / "local-only" / "1.0.0"
    versioned.mkdir()
    (versioned / "manifest.json").write_text(
        json.dumps({"version": "1.0.0"}), encoding="utf-8")
    assert local_release_source(tmp_path, "local-only", "1.0.0") == versioned


def test_cli_install_happy_and_refusal(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    repo = make_registry(tmp_path)
    sha = digest_of(repo)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src") \
        + os.pathsep + env.get("PYTHONPATH", "")

    r = subprocess.run(
        [sys.executable, "-m", "nexuusbot.registry", "install",
         "--registry", str(repo), "--plugin", "sales-delta-widget",
         "--version", "1.2.0", "--sha256", sha,
         "--dest", str(tmp_path / "plugins")],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("OK sales-delta-widget@1.2.0")

    r = subprocess.run(
        [sys.executable, "-m", "nexuusbot.registry", "install",
         "--registry", str(repo), "--plugin", "sales-delta-widget",
         "--version", "1.2.0", "--sha256", "0" * 64,
         "--dest", str(tmp_path / "plugins2")],
        capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "FAIL install:hash-mismatch" in r.stdout
