"""The registry index: id, publisher, latest, risk, class, pinned releases.

The index is the registry's root document. Loading is total: any schema
problem raises RegistryIndexError with a named reason, never a stack
trace, because this file is what CI and every client consume.

Schema v2 adds publisher keys, categories, tags and signed release
metadata. v1 documents keep loading through the same model (wrapped in
memory as v2 with no publisher keys), and every write emits v2.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class RegistryIndexError(Exception):
    """A named reason the index cannot be trusted."""

    def __init__(self, code: str):
        """Keep the named reason, which is also the exception's message."""
        super().__init__(code)
        self.code = code


# Ids, versions and tags become path fragments (install directories, git
# pathspecs), so they are names, not free text: no separators, no leading
# dashes, no dot-segments, ever.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_PROVENANCE_KINDS = {"dns", "github", "manual"}


def _safe_name(value: str, what: str) -> str:
    """Return the value when it is a safe path fragment, and raise otherwise.

    Ids, versions and tags become directories and git pathspecs, so a
    separator, a leading dash or any dot-segment is refused; the reason quotes
    at most 40 characters of the value.
    """
    if not _SAFE_NAME.match(value) or ".." in value:
        raise RegistryIndexError(f"index:unsafe-{what}:{value[:40]}")
    return value


@dataclass(frozen=True)
class PublisherInfo:
    key_id: str
    provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Release:
    version: str
    sha256: str
    tag: str = ""
    yanked: bool = False
    # Where the release content lives: "tag" (extracted from git at the
    # pinned tag, the PR-published shape) or "local" (the registry's own
    # plugins/<id>/<version> directory, digest-pinned; published from
    # inside the app with no git tag, so tag stays empty by construction).
    source: str = "tag"
    # Signed metadata: digest is the tree digest statement the publisher
    # signed; signature is the detached release pin over
    # {pluginId, version, digest}.
    digest: str = ""
    signature: str = ""
    changelog: str = ""
    min_host: str = ""


@dataclass(frozen=True)
class PluginEntry:
    id: str
    publisher: str
    latest: str
    risk: str
    class_: str
    releases: tuple[Release, ...] = field(default_factory=tuple)
    dependencies: object = field(default_factory=tuple)
    name: str = ""
    category: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def release_for(self, version: str) -> Release | None:
        """Return the release carrying that exact version string, or None."""
        for release in self.releases:
            if release.version == version:
                return release
        return None


@dataclass(frozen=True)
class RegistryIndex:
    schema_version: int
    plugins: tuple[PluginEntry, ...]
    version: int = 0
    generated_at: str = ""
    publishers: dict[str, PublisherInfo] = field(default_factory=dict)
    # True when the document on disk was schema v1 and is wrapped in memory;
    # serialization still emits v2, but trust semantics stay legacy-tolerant.
    legacy: bool = False

    def plugin(self, plugin_id: str) -> PluginEntry | None:
        """Return the entry for that plugin id, or None."""
        for entry in self.plugins:
            if entry.id == plugin_id:
                return entry
        return None

    def to_json(self) -> str:
        """Serialize the index as a schema v2 JSON document with sorted keys.

        An index wrapped from a v1 document is written out as v2.
        """
        return json.dumps(_as_dict(self), indent=2, sort_keys=True)


def _require(condition: bool, reason: str) -> None:
    """Raise RegistryIndexError(reason) unless the condition holds."""
    if not condition:
        raise RegistryIndexError(reason)


def _reject_unknown(value: dict, allowed: set[str]) -> None:
    """Refuse the first key outside the allowed set, naming it in the reason."""
    for key in sorted(set(value) - allowed):
        raise RegistryIndexError(f"index:unknown-key:{key}")


def _parse_release(release: dict, *, legacy: bool) -> Release:
    """Validate one release object into a Release, or raise a named reason.

    Version and sha256 are required, and the version must be a safe name. A
    local release carries no tag because its directory is the pin; every other
    release must carry one, since the tag is what the archive is read at. The
    remaining fields are optional and default to empty.
    """
    _require(isinstance(release, dict), "index:release-not-an-object")
    if not legacy:
        _reject_unknown(
            release,
            {
                "version",
                "sha256",
                "digest",
                "signature",
                "tag",
                "changelog",
                "minHost",
                "yanked",
                "source",
            },
        )
    for key in ("version", "sha256"):
        _require(key in release, f"index:release-{key}-missing")
    source = str(release.get("source", "tag"))
    _require(
        source in ("tag", "local"),
        "index:release-source-invalid",
    )
    if source == "local":
        # A local release is pinned to the registry's plugins directory by
        # digest; a tag on it would be a claim the release cannot keep.
        _require("tag" not in release, "index:release-local-tag-present")
        tag = ""
    else:
        _require("tag" in release, "index:release-tag-missing")
        tag = _safe_name(str(release["tag"]), "tag")
    return Release(
        version=_safe_name(str(release["version"]), "version"),
        sha256=str(release["sha256"]),
        tag=tag,
        yanked=bool(release.get("yanked", False)),
        source=source,
        digest=str(release.get("digest", "")),
        signature=str(release.get("signature", "")),
        changelog=str(release.get("changelog", "")),
        min_host=str(release.get("minHost", "")),
    )


def _parse_plugin(entry: dict, *, legacy: bool) -> PluginEntry:
    """Validate one plugin object into a PluginEntry, or raise a named reason.

    The required keys are checked before their values; tags must be a list, and
    dependencies stay a string map or become a tuple of strings.
    """
    _require(isinstance(entry, dict), "index:plugin-not-an-object")
    if not legacy:
        _reject_unknown(
            entry,
            {
                "id",
                "name",
                "publisher",
                "category",
                "tags",
                "latest",
                "risk",
                "class",
                "releases",
                "dependencies",
            },
        )
    for key in ("id", "publisher", "latest", "risk", "class", "releases"):
        _require(key in entry, f"index:plugin-{key}-missing")
    _require(isinstance(entry["releases"], list), "index:plugin-releases-must-be-list")
    releases = tuple(_parse_release(item, legacy=legacy) for item in entry["releases"])
    raw_tags = entry.get("tags", [])
    _require(isinstance(raw_tags, list), "index:plugin-tags-invalid")
    dependencies = entry.get("dependencies", ())
    if isinstance(dependencies, dict):
        dependencies = {str(k): str(v) for k, v in dependencies.items()}
    elif isinstance(dependencies, (list, tuple)):
        dependencies = tuple(str(d) for d in dependencies)
    else:
        raise RegistryIndexError("index:plugin-dependencies-invalid")
    return PluginEntry(
        id=_safe_name(str(entry["id"]), "id"),
        publisher=str(entry["publisher"]),
        latest=_safe_name(str(entry["latest"]), "version"),
        risk=str(entry["risk"]),
        class_=str(entry["class"]),
        releases=releases,
        dependencies=dependencies,
        name=str(entry.get("name", "")),
        category=str(entry.get("category", "")),
        tags=tuple(str(tag) for tag in raw_tags),
    )


def _parse_publishers(value) -> dict[str, PublisherInfo]:
    """Validate the publisher map into key ids and provenance.

    An absent map means no publishers. A present one must name a key id and a
    provenance of kind dns, github or manual, with a non-empty value.
    """
    if value is None:
        return {}
    _require(isinstance(value, dict), "index:publishers-must-be-object")
    publishers = {}
    for publisher_id, entry in value.items():
        _safe_name(str(publisher_id), "publisher")
        _require(isinstance(entry, dict), "index:publisher-not-an-object")
        _reject_unknown(entry, {"keyId", "provenance"})
        _require("keyId" in entry, "index:publisher-keyId-missing")
        provenance = entry.get("provenance", {})
        _require(isinstance(provenance, dict), "index:publisher-provenance-invalid")
        _reject_unknown(provenance, {"kind", "value"})
        kind = str(provenance.get("kind", ""))
        _require(kind in _PROVENANCE_KINDS, "index:publisher-provenance-kind")
        value_ = str(provenance.get("value", ""))
        _require(bool(value_), "index:publisher-provenance-value")
        publishers[str(publisher_id)] = PublisherInfo(
            key_id=str(entry["keyId"]),
            provenance={"kind": kind, "value": value_},
        )
    return publishers


def load_index(raw: str | bytes) -> RegistryIndex:
    """Parse and validate an index document. Total: named reasons only."""
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RegistryIndexError(f"index:invalid-json:{exc.msg}") from exc
    _require(isinstance(document, dict), "index:not-an-object")
    _require("schemaVersion" in document, "index:schemaVersion-missing")
    schema_version = document["schemaVersion"]
    _require(
        isinstance(schema_version, int)
        and not isinstance(schema_version, bool)
        and schema_version in (1, 2),
        "index:unsupported-schemaVersion",
    )
    _require(isinstance(document.get("plugins"), list), "index:plugins-must-be-list")

    if schema_version == 1:
        # v1 files keep the old validation rules exactly; unknown extension
        # keys stay tolerated because the shipped registry may carry them.
        plugins = tuple(_parse_plugin(entry, legacy=True) for entry in document["plugins"])
        return RegistryIndex(schema_version=2, plugins=plugins, legacy=True)

    _reject_unknown(
        document,
        {"schemaVersion", "version", "generatedAt", "publishers", "plugins"},
    )
    version = document.get("version", 0)
    _require(
        isinstance(version, int) and not isinstance(version, bool) and version >= 0,
        "index:version-invalid",
    )
    generated_at = document.get("generatedAt", "")
    _require(isinstance(generated_at, str), "index:generatedAt-invalid")
    publishers = _parse_publishers(document.get("publishers"))
    plugins = tuple(
        _parse_plugin(entry, legacy=False) for entry in document["plugins"]
    )
    return RegistryIndex(
        schema_version=2,
        plugins=plugins,
        version=version,
        generated_at=generated_at,
        publishers=publishers,
    )


def _as_dict(index: RegistryIndex) -> dict:
    """Build the schema v2 dictionary that to_json serializes.

    Empty optional fields are omitted instead of written blank, and publishers
    come out in sorted id order.
    """
    def release_dict(r: Release) -> dict:
        """One release in document form: a tag or the local marker, never both."""
        out = {"version": r.version, "sha256": r.sha256}
        if r.digest:
            out["digest"] = r.digest
        if r.signature:
            out["signature"] = r.signature
        if r.source == "local":
            out["source"] = "local"  # digest-pinned to the plugins dir, no tag
        else:
            out["tag"] = r.tag
        if r.changelog:
            out["changelog"] = r.changelog
        if r.min_host:
            out["minHost"] = r.min_host
        out["yanked"] = r.yanked
        return out

    def plugin_dict(p: PluginEntry) -> dict:
        """One plugin entry in document form, dependencies only when declared."""
        out = {
            "id": p.id,
            "name": p.name,
            "publisher": p.publisher,
            "category": p.category,
            "tags": list(p.tags),
            "latest": p.latest,
            "risk": p.risk,
            "class": p.class_,
            "releases": [release_dict(r) for r in p.releases],
        }
        if p.dependencies:
            out["dependencies"] = p.dependencies
        return out

    return {
        "schemaVersion": 2,
        "version": index.version,
        "generatedAt": index.generated_at,
        "publishers": {
            publisher_id: {
                "keyId": info.key_id,
                "provenance": dict(info.provenance),
            }
            for publisher_id, info in sorted(index.publishers.items())
        },
        "plugins": [plugin_dict(p) for p in index.plugins],
    }
