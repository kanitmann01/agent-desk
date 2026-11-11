"""The registry index: id, publisher, latest, risk, class, pinned releases.

The index is the registry's root document. Loading is total: any schema
problem raises RegistryIndexError with a named reason, never a stack
trace, because this file is what CI and every client consume.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


class RegistryIndexError(Exception):
    """A named reason the index cannot be trusted."""


@dataclass(frozen=True)
class Release:
    version: str
    sha256: str
    tag: str
    yanked: bool = False


@dataclass(frozen=True)
class PluginEntry:
    id: str
    publisher: str
    latest: str
    risk: str
    class_: str
    releases: tuple[Release, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)

    def release_for(self, version: str) -> Release | None:
        for release in self.releases:
            if release.version == version:
                return release
        return None


@dataclass(frozen=True)
class RegistryIndex:
    schema_version: int
    plugins: tuple[PluginEntry, ...]

    def plugin(self, plugin_id: str) -> PluginEntry | None:
        for entry in self.plugins:
            if entry.id == plugin_id:
                return entry
        return None

    def to_json(self) -> str:
        return json.dumps(_as_dict(self), indent=2, sort_keys=True)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise RegistryIndexError(reason)


def load_index(raw: str | bytes) -> RegistryIndex:
    """Parse and validate an index document. Total: named reasons only."""
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RegistryIndexError(f"index:invalid-json:{exc.msg}") from exc
    _require(isinstance(document, dict), "index:not-an-object")
    _require("schemaVersion" in document, "index:schemaVersion-missing")
    _require(document["schemaVersion"] == 1, "index:unsupported-schemaVersion")
    _require(isinstance(document.get("plugins"), list), "index:plugins-must-be-list")

    plugins = []
    for entry in document["plugins"]:
        _require(isinstance(entry, dict), "index:plugin-not-an-object")
        for key in ("id", "publisher", "latest", "risk", "class", "releases"):
            _require(key in entry, f"index:plugin-{key}-missing")
        releases = []
        for release in entry["releases"]:
            _require(isinstance(release, dict), "index:release-not-an-object")
            for key in ("version", "sha256", "tag"):
                _require(key in release, f"index:release-{key}-missing")
            releases.append(Release(
                version=str(release["version"]),
                sha256=str(release["sha256"]),
                tag=str(release["tag"]),
                yanked=bool(release.get("yanked", False)),
            ))
        plugins.append(PluginEntry(
            id=str(entry["id"]),
            publisher=str(entry["publisher"]),
            latest=str(entry["latest"]),
            risk=str(entry["risk"]),
            class_=str(entry["class"]),
            releases=tuple(releases),
            dependencies=tuple(str(d) for d in entry.get("dependencies", [])),
        ))
    return RegistryIndex(schema_version=1, plugins=tuple(plugins))


def _as_dict(index: RegistryIndex) -> dict:
    def plugin_dict(p: PluginEntry) -> dict:
        out = {
            "id": p.id,
            "publisher": p.publisher,
            "latest": p.latest,
            "risk": p.risk,
            "class": p.class_,
            "releases": [
                {"version": r.version, "sha256": r.sha256, "tag": r.tag,
                 "yanked": r.yanked}
                for r in p.releases
            ],
        }
        if p.dependencies:
            out["dependencies"] = list(p.dependencies)
        return out

    return {
        "schemaVersion": index.schema_version,
        "plugins": [plugin_dict(p) for p in index.plugins],
    }
