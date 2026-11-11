"""Registry CI review: the shared validator, dependencies, hashes, history.

Every concern in one pass over the changed plugin directories and the
index:

- Validator: the same ``validate_plugin`` entry point the client runs,
  so registry CI and the app can never disagree (spec: byte-identical).
- Dependency scan: every dependency an index entry declares must exist
  in the index.
- Hash consistency: the index pin must equal the recomputed tree digest
  of the plugin directory.
- Append-only history: releases may be appended or yanked, never
  dropped, because clients pinned to older versions must keep
  resolving.
"""
from __future__ import annotations

import json
from pathlib import Path

from .index import load_index
from .install import tree_digest


def _dependency_reasons(index, plugin_dir: Path, plugin_id: str) -> list[str]:
    entry = index.plugin(plugin_id)
    if entry is None:
        return [f"registry-ci:unindexed-plugin:{plugin_id}"]
    return [f"registry-ci:unknown-dependency:{dep}"
            for dep in entry.dependencies if index.plugin(dep) is None]


def _hash_reasons(index, plugin_dir: Path, plugin_id: str) -> list[str]:
    try:
        manifest = json.loads((plugin_dir / "manifest.json").read_text(
            encoding="utf-8"))
        version = str(manifest.get("version", ""))
    except (OSError, json.JSONDecodeError):
        return ["registry-ci:manifest-unreadable"]
    entry = index.plugin(plugin_id)
    if entry is None:
        return []
    release = entry.release_for(version)
    if release is None:
        return [f"registry-ci:unindexed-release:{version}"]
    if release.sha256 != tree_digest(plugin_dir):
        return [f"registry-ci:hash-mismatch:{plugin_id}@{version}"]
    return []


def _history_reasons(new_index, base_index_text: str | None) -> list[str]:
    if base_index_text is None:
        return []
    stripped = (base_index_text or "").strip()
    if stripped in ("", "{}"):  # nothing published on the base yet
        return []
    try:
        base = load_index(stripped)
    except Exception as exc:  # a malformed base still gets a named reason
        return [f"registry-ci:base-index-unreadable:{exc}"]
    reasons = []
    for old_plugin in base.plugins:
        new_plugin = new_index.plugin(old_plugin.id)
        if new_plugin is None:
            reasons.append(f"registry-ci:history-truncated:{old_plugin.id}")
            continue
        old_versions = {r.version for r in old_plugin.releases}
        new_versions = {r.version for r in new_plugin.releases}
        if not old_versions <= new_versions:
            dropped = sorted(old_versions - new_versions)
            reasons.append(
                f"registry-ci:history-truncated:{old_plugin.id}:{','.join(dropped)}")
    return reasons


def review_registry_changes(registry_root: Path, plugin_dirs: list[Path],
                            base_index_text: str | None = None) -> dict:
    """Review one registry PR. Returns ok plus named reasons for every block."""
    from agentdesk.validator.core import validate_plugin

    registry_root = Path(registry_root)
    reasons: list[str] = []
    try:
        index = load_index((registry_root / "index.json").read_text(
            encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reasons": [f"registry-ci:index-unreadable:{exc}"]}

    reasons += _history_reasons(index, base_index_text)

    for plugin_dir in plugin_dirs:
        plugin_dir = Path(plugin_dir)
        try:
            manifest = json.loads((plugin_dir / "manifest.json").read_text(
                encoding="utf-8"))
            plugin_id = str(manifest.get("id", ""))
        except (OSError, json.JSONDecodeError):
            plugin_id = ""

        verdict = validate_plugin(plugin_dir)
        for failure in verdict.failures:
            reasons.append(f"validator:{failure.code}:{failure.message}")

        if not plugin_id:
            reasons.append("registry-ci:manifest-unreadable")
            continue
        reasons += _dependency_reasons(index, plugin_dir, plugin_id)
        reasons += _hash_reasons(index, plugin_dir, plugin_id)

    return {"ok": not reasons, "reasons": reasons}
