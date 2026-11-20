"""Registry CI review: the shared validator, dependencies, hashes, history.

Every concern in one pass over the changed plugin directories and the
index:

- Validator: the same ``validate_plugin`` entry point the client runs,
  so registry CI and the app can never disagree (spec: byte-identical).
- Dependency scan: every dependency an index entry declares must exist
  in the index.
- Hash consistency: the index pin must equal the recomputed tree digest
  of the plugin directory.
- Local releases: every ``source: "local"`` release of a reviewed
  plugin resolves from the registry's own working tree, so its
  versioned directory must exist and hash to its pin.
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
    """Return the reasons the reviewed plugin's dependencies do not resolve.

    The plugin has to be indexed itself before its dependencies can be looked
    up; every dependency missing from the index gets its own reason.
    """
    entry = index.plugin(plugin_id)
    if entry is None:
        return [f"registry-ci:unindexed-plugin:{plugin_id}"]
    return [f"registry-ci:unknown-dependency:{dep}"
            for dep in entry.dependencies if index.plugin(dep) is None]


def _hash_reasons(index, plugin_dir: Path, plugin_id: str) -> list[str]:
    """Return the reasons the index pin disagrees with the plugin directory.

    The version is read from the directory's own manifest, so an unreadable
    manifest or an unindexed release is reported before any digest is
    recomputed.
    """
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


def _local_release_reasons(index, registry_root: Path,
                           plugin_id: str) -> list[str]:
    """Every local release of a reviewed plugin must keep resolving.

    A local release installs straight from the registry's working tree
    (``plugins/<id>/<version>``, the directory publish wrote), so a
    missing or tampered tree is a broken pin even when only the newest
    version's directory changed in this review.
    """
    entry = index.plugin(plugin_id)
    if entry is None:
        return []
    from .install import local_release_source

    reasons = []
    for release in entry.releases:
        if release.source != "local":
            continue
        source = local_release_source(registry_root, plugin_id, release.version)
        if source is None:
            reasons.append(
                f"registry-ci:local-release-missing:{plugin_id}@{release.version}")
            continue
        if release.sha256 != tree_digest(source):
            reasons.append(
                f"registry-ci:hash-mismatch:{plugin_id}@{release.version}")
    return reasons


def _history_reasons(new_index, base_index_text: str | None,
                    archived_ids: frozenset[str] = frozenset()) -> list[str]:
    """Return the reasons the new index lost something the base index carried.

    No base (None, empty, or an empty object) has no history to lose. Only
    removals are reported: appending a release and yanking one are exactly what
    the append-only rule permits.

    Retiring a plugin removes it from the index on purpose, so a removal is
    allowed only when the caller also names it in `archived_ids`, the ids the
    archive folder actually holds. A plugin that simply disappeared from the
    index without a tree in the archive is still a truncation.
    """
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
            if old_plugin.id in archived_ids:
                continue
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
                            base_index_text: str | None = None,
                            archived_ids: frozenset[str] = frozenset()) -> dict:
    """Review one registry PR. Returns ok plus named reasons for every block.

    `archived_ids` are the retired plugin ids the archive folder holds; they
    may leave the index without failing the append-only history check. All
    other eligibility, hash, dependency and validator checks are unchanged.
    """
    from agentdesk.validator.core import validate_plugin

    registry_root = Path(registry_root)
    reasons: list[str] = []
    try:
        index = load_index((registry_root / "index.json").read_text(
            encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reasons": [f"registry-ci:index-unreadable:{exc}"]}

    reasons += _history_reasons(index, base_index_text, frozenset(archived_ids))

    reviewed_ids: set[str] = set()
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
        # Once per plugin, however many of its directories the review
        # was handed: every local release pin must resolve.
        if plugin_id not in reviewed_ids:
            reviewed_ids.add(plugin_id)
            reasons += _local_release_reasons(index, registry_root, plugin_id)

    return {"ok": not reasons, "reasons": reasons}
