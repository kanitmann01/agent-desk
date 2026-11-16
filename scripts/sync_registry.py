#!/usr/bin/env python3
"""Keep registry/index.json in step with the plugin folders.

Every directory under registry/plugins is a shipped, bundled release. The
catalog and the install path both resolve through the index, so a plugin
that exists only as a folder is invisible; a plugin listed with a stale
digest fails the catalog consistency check.

This script is idempotent: it preserves existing releases (clients pin
them), appends a new local release when a manifest version or tree digest
changes, and prunes entries whose folder is gone. It never tags a release;
shipped plugins are digest-pinned to the plugins directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from agentdesk.registry.install import tree_digest  # noqa: E402


def _manifest(plugin_dir: Path) -> dict:
    try:
        return json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _risk(manifest: dict) -> str:
    permissions = manifest.get("permissions", {})
    network = permissions.get("network", {}).get("allow", []) if isinstance(permissions, dict) else []
    if network:
        return "medium"
    return "low"


def sync(registry_root: Path | str) -> dict:
    root = Path(registry_root)
    plugins_dir = root / "plugins"
    index_path = root / "index.json"
    document = json.loads(index_path.read_text(encoding="utf-8"))
    existing = {entry["id"]: entry for entry in document.get("plugins", [])}

    entries = []
    for plugin_dir in sorted(plugins_dir.iterdir(), key=lambda p: p.name):
        if not plugin_dir.is_dir():
            continue
        manifest = _manifest(plugin_dir)
        plugin_id = str(manifest.get("id") or plugin_dir.name)
        version = str(manifest.get("version") or "0.1.0")
        digest = tree_digest(plugin_dir)
        entry = existing.pop(plugin_id, None)
        if entry is None:
            entry = {
                "id": plugin_id,
                "publisher": str(manifest.get("publisher") or "agent-desk"),
                "latest": version,
                "risk": _risk(manifest),
                "class": str(manifest.get("class") or "declarative"),
                "releases": [],
            }
        # Display metadata belongs to the manifest, not to the index, so a
        # renamed or recategorised plugin updates on the next sync.
        entry["name"] = str(manifest.get("name") or plugin_id)
        entry["category"] = str(manifest.get("category") or "")
        entry["tags"] = [str(tag) for tag in (manifest.get("tags") or [])]
        entry["dependencies"] = manifest.get("requires") or {}
        releases = list(entry.get("releases", []))
        if not any(release.get("version") == version for release in releases):
            releases.append({"version": version, "sha256": digest,
                             "source": "local", "yanked": False})
        else:
            for release in releases:
                if release.get("version") == version and release.get("source", "tag") == "local":
                    release["sha256"] = digest
        entry["releases"] = releases
        entry["latest"] = version
        entry["risk"] = _risk(manifest)
        entries.append(entry)

    if existing:
        # Folders that disappeared are deliberately dropped from the index;
        # a release that is no longer shipped cannot be installed.
        pass
    document["plugins"] = entries
    document.setdefault("schemaVersion", 1)
    index_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(REPO_ROOT / "registry"))
    args = parser.parse_args(argv)
    document = sync(args.registry)
    print(f"synced {len(document['plugins'])} plugins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
