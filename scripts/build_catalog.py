#!/usr/bin/env python3
"""Generate the bundled catalog from the shipped registry.

The catalog is a build artifact: every plugin under registry/plugins is
listed with the digest of its tree, so the dashboard can show what is
installed without trusting the workspace. Trust data under
registry/trust/releases is optional; when present its detached release
signature is carried through unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from nexuusbot.registry.index import load_index  # noqa: E402
from nexuusbot.registry.install import tree_digest  # noqa: E402


def _manifest(plugin_dir: Path) -> dict:
    """Read one plugin folder's manifest as a dict.

    A missing or unparseable manifest reads as an empty mapping, so the
    folder still gets a catalog entry (named after the directory, with empty
    placeholders) instead of dropping out of the catalog without a trace.
    """
    try:
        return json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _release_statement(trust_dir: Path, plugin_id: str, version: str) -> dict:
    """Read the detached release statement for one plugin version, or {}.

    Trust data is optional. When it is absent the catalog entry carries an
    empty signature, and changelog and minHost fall back to the index release
    when the index has one and to the payload's own fields otherwise.
    """
    path = trust_dir / "releases" / plugin_id / f"{version}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def build_catalog(registry_root: Path | str) -> dict:
    """Return the catalog document for registry_root."""
    root = Path(registry_root)
    plugins_dir = root / "plugins"
    index = None
    index_path = root / "index.json"
    if index_path.is_file():
        index = load_index(index_path.read_text(encoding="utf-8"))
    indexed = {plugin.id: plugin for plugin in index.plugins} if index else {}
    trust_dir = root / "trust"

    entries = []
    for plugin_dir in sorted(plugins_dir.iterdir(), key=lambda path: path.name):
        if not plugin_dir.is_dir():
            continue
        manifest = _manifest(plugin_dir)
        plugin_id = manifest.get("id") or plugin_dir.name
        indexed_plugin = indexed.get(plugin_id)
        releases = {}
        if indexed_plugin is not None:
            releases = {release.version: release for release in indexed_plugin.releases}
        latest = indexed_plugin.latest if indexed_plugin else str(
            manifest.get("version", ""))
        release = releases.get(latest)
        statement = _release_statement(trust_dir, plugin_id, latest)
        statement_payload = statement.get("payload") or {}
        statement_signature = (statement.get("signature") or {}).get("signature", "")
        entries.append({
            "id": plugin_id,
            "name": manifest.get("name", plugin_id),
            "publisher": (indexed_plugin.publisher if indexed_plugin
                          else manifest.get("publisher", "")),
            "category": (indexed_plugin.category if indexed_plugin
                         else manifest.get("category", "")),
            "tags": list(indexed_plugin.tags) if indexed_plugin
                    else list(manifest.get("tags") or []),
            "latest": latest,
            "digest": tree_digest(plugin_dir),
            "signature": statement_signature,
            "changelog": (release.changelog if release is not None
                          else statement_payload.get("changelog", "")),
            "risk": (indexed_plugin.risk if indexed_plugin is not None
                     else str(manifest.get("risk", ""))),
            "minHost": (release.min_host if release is not None
                        else statement_payload.get("minHost", "")),
            "yanked": bool(release.yanked) if release is not None else False,
        })
    return {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "plugins": entries,
    }


def main(argv: list[str] | None = None) -> int:
    """Write the bundled catalog for one registry root and report it.

    Reads --registry (default registry/) and overwrites --out (default
    build/catalog.json), creating the parent directory; the file is written
    with sorted keys and a trailing newline so reruns diff cleanly. Exits 0
    after printing the plugin count. A registry with no plugins/ directory
    raises before --out is touched, and argparse exits 2 on bad usage.
    """
    parser = argparse.ArgumentParser(description="Build the bundled plugin catalog")
    parser.add_argument("--registry", default=str(REPO_ROOT / "registry"))
    parser.add_argument("--out", default=str(REPO_ROOT / "build" / "catalog.json"))
    args = parser.parse_args(argv)
    catalog = build_catalog(args.registry)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {len(catalog['plugins'])} plugins to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
