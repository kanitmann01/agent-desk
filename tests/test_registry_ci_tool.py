"""The registry CI tool: exit-code contract and output style.

Runs straight from a checkout like CI does, with explicit plugin lists
and a base-index file, so no git plumbing is needed to test it.
"""
import subprocess
import sys
from pathlib import Path

from .registry_fixtures import PLUGIN_FIXTURE, make_registry, tree_digest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools" / "registry_ci.py"


def run_tool(*args: str) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(TOOLS), *args],
        capture_output=True, text=True, env=env,
    )


def write_registry(tmp_path: Path, digest: str) -> Path:
    registry_root = tmp_path / "registry"
    registry_root.mkdir(parents=True)
    document = {
        "schemaVersion": 1,
        "plugins": [{
            "id": "sales-delta-widget",
            "publisher": "acme-tools",
            "latest": "1.2.0",
            "risk": "low",
            "class": "declarative",
            "releases": [{"version": "1.2.0", "sha256": digest,
                          "tag": "sales-delta-widget-1.2.0", "yanked": False}],
        }],
    }
    (registry_root / "index.json").write_text(json.dumps(document, indent=2),
                                              encoding="utf-8")
    return registry_root


import json  # noqa: E402


def test_tool_passes_on_valid_plugin(tmp_path):
    registry_root = write_registry(tmp_path, tree_digest(PLUGIN_FIXTURE))
    r = run_tool("--registry", str(registry_root),
                 "--plugins", str(PLUGIN_FIXTURE))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REGISTRY-CI PASS" in r.stdout


def test_tool_blocks_on_invalid_plugin_with_named_reason(tmp_path):
    shell = tmp_path / "shell-plugin"
    shell.mkdir()
    validator_fixtures = PLUGIN_FIXTURE.parents[2] / "validator" / "shell-permission"
    for item in validator_fixtures.rglob("*"):
        if item.is_file():
            target = shell / item.relative_to(validator_fixtures)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())
    registry_root = write_registry(tmp_path, tree_digest(shell))
    r = run_tool("--registry", str(registry_root), "--plugins", str(shell))
    assert r.returncode == 1
    assert any(line.startswith("FAIL validator:") for line in r.stdout.splitlines())
    assert "REGISTRY-CI FAILED (1)" in r.stdout


def test_tool_blocks_on_hash_inconsistency(tmp_path):
    registry_root = write_registry(tmp_path, "0" * 64)
    r = run_tool("--registry", str(registry_root),
                 "--plugins", str(PLUGIN_FIXTURE))
    assert r.returncode == 1
    assert any(line.startswith("FAIL registry-ci:hash-mismatch")
               for line in r.stdout.splitlines())


def test_tool_blocks_on_truncated_history(tmp_path):
    registry_root = write_registry(tmp_path, tree_digest(PLUGIN_FIXTURE))
    old_index = tmp_path / "old-index.json"
    old_index.write_text((registry_root / "index.json").read_text(encoding="utf-8"),
                         encoding="utf-8")
    document = json.loads(old_index.read_text(encoding="utf-8"))
    document["plugins"][0]["releases"].append(
        {"version": "1.3.0", "sha256": "b" * 64,
         "tag": "sales-delta-widget-1.3.0", "yanked": False})
    document["plugins"][0]["latest"] = "1.3.0"
    new_index = tmp_path / "new-index.json"
    new_index.write_text(json.dumps(document, indent=2), encoding="utf-8")

    # Appending a release over the base is fine.
    (registry_root / "index.json").write_text(
        new_index.read_text(encoding="utf-8"), encoding="utf-8")
    r = run_tool("--registry", str(registry_root),
                 "--plugins", str(PLUGIN_FIXTURE),
                 "--base-index", str(old_index))
    assert r.returncode == 0, r.stdout

    # Dropping 1.3.0 from an index that had it breaks pins: refuse.
    (registry_root / "index.json").write_text(
        old_index.read_text(encoding="utf-8"), encoding="utf-8")
    r = run_tool("--registry", str(registry_root),
                 "--plugins", str(PLUGIN_FIXTURE),
                 "--base-index", str(new_index))
    assert r.returncode == 1
    assert any(line.startswith("FAIL registry-ci:history-truncated")
               for line in r.stdout.splitlines())


def test_tool_passes_with_no_changes(tmp_path):
    registry_root = write_registry(tmp_path, tree_digest(PLUGIN_FIXTURE))
    r = run_tool("--registry", str(registry_root))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REGISTRY-CI PASS" in r.stdout


def test_tool_allows_a_retirement_the_archive_accounts_for(tmp_path):
    """A removed id is a truncation until the archive folder holds its tree.

    The base carried two plugins; the reviewed index drops one. The removal
    passes only when --archive names a folder whose tree has that id.
    """
    registry_root = write_registry(tmp_path, tree_digest(PLUGIN_FIXTURE))
    base_index = tmp_path / "base-index.json"
    document = json.loads((registry_root / "index.json").read_text(encoding="utf-8"))
    document["plugins"].append({
        "id": "retired-plugin",
        "publisher": "acme-tools",
        "latest": "0.1.0",
        "risk": "low",
        "class": "declarative",
        "releases": [{"version": "0.1.0", "sha256": "a" * 64,
                      "tag": "retired-plugin-0.1.0", "yanked": False}],
    })
    base_index.write_text(json.dumps(document, indent=2), encoding="utf-8")

    # No archive stated: the drop reads as silent history truncation.
    r = run_tool("--registry", str(registry_root),
                 "--plugins", str(PLUGIN_FIXTURE),
                 "--base-index", str(base_index))
    assert r.returncode == 1
    assert "FAIL registry-ci:history-truncated:retired-plugin" in r.stdout

    # An archive folder that does not hold the retired id does not help.
    unrelated = tmp_path / "archive"
    (unrelated / "some-other-plugin").mkdir(parents=True)
    (unrelated / "some-other-plugin" / "manifest.json").write_text(
        json.dumps({"id": "some-other-plugin"}), encoding="utf-8")
    r = run_tool("--registry", str(registry_root),
                 "--plugins", str(PLUGIN_FIXTURE),
                 "--base-index", str(base_index),
                 "--archive", str(unrelated))
    assert r.returncode == 1
    assert "FAIL registry-ci:history-truncated:retired-plugin" in r.stdout

    # The archive holds the retired tree: the retirement is deliberate.
    (unrelated / "retired-plugin").mkdir()
    (unrelated / "retired-plugin" / "manifest.json").write_text(
        json.dumps({"id": "retired-plugin"}), encoding="utf-8")
    r = run_tool("--registry", str(registry_root),
                 "--plugins", str(PLUGIN_FIXTURE),
                 "--base-index", str(base_index),
                 "--archive", str(unrelated))
    assert r.returncode == 0, r.stdout
    assert "REGISTRY-CI PASS" in r.stdout
