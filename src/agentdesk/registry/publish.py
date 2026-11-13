"""Publishing a local release into the registry (ticket #63).

The create-to-publish loop: an installed plugin (wizard-made or
otherwise) becomes a registry release without leaving the machine. The
shared validator runs first, the tree lands in ``plugins/<id>/`` with
the same layout the PR-published plugins carry, and the index gains a
release pinned by the same tree digest install verifies. The release is
``source: "local"``: no git tag exists for it, so installs resolve it
straight from the plugins directory. Every refusal carries a named
code, validator style.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from .index import (
    PluginEntry,
    Release,
    RegistryIndex,
    RegistryIndexError,
    load_index,
)
from .install import RegistryError, tree_digest

# A local release is a Class D declarative plugin the app itself built
# or installed; the risk line the index carries for those is low, and
# nothing that would warrant more can pass the validator anyway.
LOCAL_RISK = "low"


def _require_safe_name(value: str, what: str) -> None:
    """Defense in depth, publish's own vocabulary: ids and versions
    become directory names inside the registry checkout."""
    if (not value or "/" in value or "\\" in value or value.startswith("-")
            or ".." in value):
        raise RegistryError("publish:unsafe-name",
                            f"{what} is not a safe name: {value[:40]!r}")


def resolve_publish_root(settings_store=None, environ=None) -> Path:
    """The registry root publish writes into, or a named refusal.

    The resolution order is the sacred one (settings ``registry_path``,
    then ``AGENTDESK_REGISTRY``, then this app's own checkout); when
    nothing resolves, publish refuses honestly, naming all three.
    """
    from . import source as registry_source

    root, _origin = registry_source.resolve_registry_root(
        settings_store, environ)
    if root is None:
        raise RegistryError(
            "publish:no-registry",
            "No plugin registry is configured, so there is nowhere to "
            "publish to. The registry resolves in this order: the "
            "registry_path saved in Settings, the AGENTDESK_REGISTRY "
            "environment variable, then this app's own checkout. Set one "
            "in Settings.")
    return root


def publish_to_registry(registry_root: Path | str, plugin_id: str, *,
                        version: str, source_dir: Path | str) -> dict:
    """Publish one validated plugin tree as a local release.

    The source is the installed version directory the plugin runtime
    owns. Nothing lands before the shared validator passes and the
    manifest agrees with the id and version asked for; the tree digest
    is computed by the same function install verifies with; the index
    append keeps releases append-only (a duplicate id+version is a
    named refusal, not an overwrite).
    """
    _require_safe_name(plugin_id, "plugin id")
    _require_safe_name(version, "version")
    registry_root = Path(registry_root)
    source_dir = Path(source_dir)

    from agentdesk.validator.core import validate_plugin
    try:
        verdict = validate_plugin(source_dir)
    except Exception as exc:  # unreadable source: a bad request
        raise RegistryError("publish:unreadable", str(exc)) from exc
    if not verdict.ok:
        first = verdict.failures[0]
        raise RegistryError("publish:validator-failed",
                            f"{first.code}: {first.message}")
    try:
        manifest = json.loads((source_dir / "manifest.json").read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError("publish:unreadable",
                            f"the manifest cannot be read: {exc}") from exc
    if (str(manifest.get("id", "")) != plugin_id
            or str(manifest.get("version", "")) != version):
        raise RegistryError(
            "publish:manifest-mismatch",
            f"the source is {manifest.get('id', '?')} "
            f"{manifest.get('version', '?')}, not {plugin_id} {version}")

    try:
        raw = (registry_root / "index.json").read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError("publish:index-unreadable", str(exc)) from exc
    index = load_index(raw)  # RegistryIndexError: the index is already bad

    entry = index.plugin(plugin_id)
    if entry is not None and entry.release_for(version) is not None:
        raise RegistryError(
            "publish:already-exists",
            f"{plugin_id} {version} is already published; publish a new "
            "version instead")

    plugin_dir = registry_root / "plugins" / plugin_id
    plugin_dir.parent.mkdir(parents=True, exist_ok=True)
    # Stage outside the registry, then swap in: a half-copied tree never
    # sits where installs would read it.
    with tempfile.TemporaryDirectory(prefix="agentdesk-publish-") as tmp:
        staged = Path(tmp) / "plugin"
        shutil.copytree(source_dir, staged)
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)
        shutil.copytree(staged, plugin_dir)
    digest = tree_digest(plugin_dir)

    release = Release(version=version, sha256=digest, tag="", source="local")
    index = _append_release(index, plugin_id, version, release, manifest)
    (registry_root / "index.json").write_text(index.to_json() + "\n",
                                              encoding="utf-8")
    return {
        "ok": True,
        "plugin": plugin_id,
        "version": version,
        "sha256": digest,
        "source": "local",
        "path": str(plugin_dir),
    }


def _append_release(index: RegistryIndex, plugin_id: str, version: str,
                    release: Release, manifest: dict) -> RegistryIndex:
    """The index with the release appended, as a new document.

    Append-only by construction: existing entries and releases are
    never rewritten, only extended; ``latest`` moves forward to the
    newly published version. The document is rebuilt through the model
    so what lands on disk always reloads through the total loader.
    """
    entry = index.plugin(plugin_id)
    if entry is None:
        entry = PluginEntry(
            id=plugin_id,
            publisher=str(manifest.get("publisher", "")) or "local",
            latest=version,
            risk=LOCAL_RISK,
            class_=str(manifest.get("class", "")) or "declarative",
            releases=(release,),
        )
        return replace(index, plugins=index.plugins + (entry,))
    return replace(
        index,
        plugins=tuple(
            replace(existing, releases=existing.releases + (release,),
                    latest=version)
            if existing.id == plugin_id else existing
            for existing in index.plugins
        ),
    )
