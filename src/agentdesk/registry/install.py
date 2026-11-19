"""Pinned installation from the registry.

The client resolves its lockfile pin against the index, fetches the
pinned content (``git archive`` at the tag for a tag-pinned release,
the registry's own plugins directory for a digest-pinned local
release), verifies the tree digest against the pin, runs the shared
validator, and only then installs into a versioned directory. Any
refusal carries a named code, validator style.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .index import PluginEntry, Release, RegistryIndex, RegistryIndexError, load_index


class RegistryError(Exception):
    """A named install refusal: ``code`` is the stable vocabulary."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the stable code beside the message."""
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Pin:
    version: str
    sha256: str | None = None


def tree_digest(plugin_dir: Path) -> str:
    """sha256 over sorted relpaths and file bytes: the release pin.

    The sort key is the posix relpath string, not the Path object:
    pathlib compares case-insensitively on Windows, so a Path sort walks
    a mixed-case tree (README.md after manifest.json) in a different
    order there, and the same tree hashes differently across machines.
    A pin that only verifies on the machine that made it is not a pin.
    """
    digest = hashlib.sha256()
    files = [path for path in Path(plugin_dir).rglob("*") if path.is_file()]
    files.sort(key=lambda path: path.relative_to(plugin_dir).as_posix())
    for path in files:
        rel = path.relative_to(plugin_dir).as_posix()
        digest.update(rel.encode("utf-8") + b"\n")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def resolve(index: RegistryIndex, plugin_id: str,
            version: str, sha256: str | None = None) -> tuple[PluginEntry, Release]:
    """Resolve a client pin against the index. Old pins keep resolving:
    releases are append-only history, and a pinned sha256 resolves even
    when the release is yanked, because the client already has it."""
    _require_safe_name(plugin_id, "plugin id")
    _require_safe_name(version, "version")
    entry = index.plugin(plugin_id)
    if entry is None:
        raise RegistryError("install:unknown-plugin", f"no plugin {plugin_id}")
    release = entry.release_for(version)
    if release is None:
        raise RegistryError("install:unknown-version",
                            f"{plugin_id} has no release {version}")
    if sha256 is not None and release.sha256 != sha256:
        raise RegistryError("install:hash-mismatch",
                            f"pin {sha256[:12]} does not match release "
                            f"{release.sha256[:12]}")
    if release.yanked and release.sha256 != sha256:
        raise RegistryError("install:yanked",
                            f"{plugin_id} {version} is yanked")
    return entry, release


def _require_safe_name(value: str, what: str) -> None:
    """Defense in depth: the index validates names too, but nothing that
    becomes a filesystem path may rely on the caller having validated it."""
    if (not value or "/" in value or "\\" in value or value.startswith("-")
            or ".." in value):
        raise RegistryError("install:unsafe-name",
                            f"{what} is not a safe name: {value[:40]!r}")


def _archive_plugin(registry_root: Path, tag: str, plugin_prefix: str,
                    destination: Path) -> None:
    """Extract plugins/<id> at ``tag`` via git archive into destination."""
    result = subprocess.run(
        ["git", "-C", str(registry_root), "archive", tag, "--", plugin_prefix],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RegistryError("install:tag-missing",
                            f"tag {tag} is not readable in the registry")
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "archive.tar"
        tar_path.write_bytes(result.stdout)
        with tarfile.open(tar_path) as archive:
            _safe_extractall(archive, tmp)
        source = Path(tmp) / plugin_prefix
        if not source.is_dir():
            raise RegistryError("install:tag-missing",
                                f"tag {tag} has no {plugin_prefix}")
        shutil.copytree(source, destination)


def local_release_source(registry_root: Path, plugin_id: str,
                         version: str) -> Path | None:
    """The working-tree directory that holds one local release.

    Published releases live in plugins/<id>/<version>. A registry built
    from a single checkout keeps its newest local release flat at
    plugins/<id>; that tree is accepted only when its manifest names the
    same version, so an older pin can never silently resolve to a newer
    tree (the digest check would reject it anyway).
    """
    versioned = registry_root / "plugins" / plugin_id / version
    if versioned.is_dir():
        return versioned
    flat = registry_root / "plugins" / plugin_id
    manifest = flat / "manifest.json"
    if manifest.is_file():
        try:
            declared = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            return None
        if declared == version:
            return flat
    return None


def _stage_local_plugin(registry_root: Path, plugin_id: str, version: str,
                        destination: Path) -> None:
    """Copy a local release out of the registry's working tree.

    A local release is pinned by digest to its own directory; there is no
    tag to extract, so git is never invoked. The digest check right after
    this copy is the whole verification story.
    """
    source = local_release_source(registry_root, plugin_id, version)
    if source is None:
        raise RegistryError(
            "install:local-plugin-missing",
            f"{plugin_id} {version} is not present in the registry "
            "plugins folder")
    shutil.copytree(source, destination)


def _verify_against_trust(index: RegistryIndex, entry: PluginEntry,
                           release: Release, trust, now) -> None:
    """Fail closed when a trust store is supplied.

    v2 index entries carry the publisher key id and a detached release
    signature over {pluginId, version, digest}; v1 entries carry neither,
    so with a trust store the signed release statement is still required
    and its digest must equal the published sha256. TrustError is
    intentionally not wrapped in RegistryError: the trust vocabulary is
    the contract callers switch on.
    """
    from agentdesk.trust import TrustError

    publisher = entry.publisher
    publisher_info = index.publishers.get(publisher)
    if not index.legacy and publisher_info is None:
        raise TrustError(
            "trust:unknown-publisher",
            f"index has no publisher key for {publisher}",
        )
    key_id = publisher_info.key_id if publisher_info is not None else None
    cert = trust.cert_for(publisher, key_id, now=now)

    if not index.legacy:
        if not release.signature:
            raise TrustError(
                "trust:unsigned",
                f"release {entry.id}@{release.version} has no signature",
            )
        if not release.digest:
            raise TrustError(
                "trust:bad-signature",
                f"release {entry.id}@{release.version} has no digest",
            )
        if release.digest != release.sha256:
            raise TrustError(
                "trust:bad-signature",
                f"release digest {release.digest[:12]} does not match "
                f"sha256 {release.sha256[:12]}",
            )
        trust.verify_pin(entry.id, release.version, release.digest,
                         release.signature, cert, now=now)

    statement = trust.verify_release(entry.id, release.version, cert, now=now)
    if statement.digest != release.sha256:
        raise TrustError(
            "trust:bad-signature",
            f"release statement digest {statement.digest[:12]} does not "
            f"match the published sha256 {release.sha256[:12]}",
        )


def install_from_registry(registry_root: Path | str, plugin_id: str, *,
                          version: str, sha256: str | None = None,
                          destination: Path | str, trust=None,
                          now=None) -> dict:
    """Install one pinned release. Returns the install record."""
    _require_safe_name(plugin_id, "plugin id")
    _require_safe_name(version, "version")
    registry_root = Path(registry_root)
    destination = Path(destination)
    try:
        index = load_index((registry_root / "index.json").read_text(encoding="utf-8"))
    except OSError as exc:
        raise RegistryError("install:index-unreadable", str(exc)) from exc
    entry, release = resolve(index, plugin_id, version, sha256)

    plugin_prefix = f"plugins/{plugin_id}"
    installed = destination / f"{plugin_id}-{version}"
    installed.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "plugin"
        if release.source == "local":
            _stage_local_plugin(registry_root, plugin_id, release.version,
                                staged)
        else:
            _archive_plugin(registry_root, release.tag, plugin_prefix, staged)
        actual = tree_digest(staged)
        if actual != release.sha256:
            raise RegistryError(
                "install:hash-mismatch",
                f"content sha256 {actual[:12]} does not match the pinned "
                f"{release.sha256[:12]}")
        if trust is not None:
            _verify_against_trust(index, entry, release, trust, now)
        from agentdesk.validator.core import validate_plugin
        verdict = validate_plugin(staged)
        if not verdict.ok:
            first = verdict.failures[0]
            raise RegistryError("install:validator-failed",
                                f"{first.code}: {first.message}")
        if installed.exists():
            shutil.rmtree(installed)
        shutil.copytree(staged, installed)
    _write_lock(destination, plugin_id, version, release.sha256,
                publisher=entry.publisher, category=entry.category)
    return {
        "ok": True,
        "plugin": plugin_id,
        "version": version,
        "sha256": release.sha256,
        "path": str(installed),
    }


# -- the client lockfile: the pointer that rollback repoints -------------

LOCK_NAME = "lock.json"


def _write_lock(destination: Path, plugin_id: str, version: str, sha256: str,
                *, publisher: str | None = None,
                category: str | None = None) -> dict:
    """Record the installed release in the client's lockfile.

    The lock is the pointer: ``version`` is what the client uses, and the
    ``history`` map is what rollback repoints to. Imports stay local so
    the module loads without touching the filesystem at import time.
    """
    import json

    lock_path = destination / LOCK_NAME
    lock: dict = {}
    if lock_path.is_file():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            lock = {}
    entry = lock.setdefault("plugins", {}).setdefault(plugin_id, {"history": {}})
    entry["version"] = version
    entry["sha256"] = sha256
    if publisher is not None:
        entry["publisher"] = publisher
    if category is not None:
        entry["category"] = category
    entry["history"][version] = sha256
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    return entry


def read_lock(destination: Path | str, plugin_id: str) -> dict | None:
    """The lock entry for one plugin, or None when it is not installed."""
    import json

    lock_path = Path(destination) / LOCK_NAME
    if not lock_path.is_file():
        return None
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    return lock.get("plugins", {}).get(plugin_id)


def rollback(destination: Path | str, plugin_id: str, *, to_version: str) -> dict:
    """Repoint the lock at an already-installed older version.

    Rollback is metadata: the versioned directory is already on disk, so
    going back is one lock write, not a re-download.
    """
    _require_safe_name(plugin_id, "plugin id")
    _require_safe_name(to_version, "version")
    destination = Path(destination)
    prior_dir = destination / f"{plugin_id}-{to_version}"
    if not prior_dir.is_dir():
        raise RegistryError("rollback:version-not-installed",
                            f"{plugin_id} {to_version} is not installed here")
    import json

    lock_path = destination / LOCK_NAME
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {}
    entry = lock.get("plugins", {}).get(plugin_id)
    if entry is None or to_version not in entry.get("history", {}):
        raise RegistryError("rollback:unknown-pin",
                            f"no lockfile pin for {plugin_id} {to_version}")
    entry["version"] = to_version
    entry["sha256"] = entry["history"][to_version]
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    return {"ok": True, "plugin": plugin_id, "version": to_version,
            "sha256": entry["sha256"]}


def _safe_extractall(archive: tarfile.TarFile, destination: str) -> None:
    """Extract with the data filter where the runtime has one, and with an
    explicit member check where it does not (older 3.10/3.11 patches)."""
    if hasattr(tarfile, "data_filter"):
        archive.extractall(destination, filter="data")
        return
    dest = Path(destination).resolve()
    for member in archive.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest)) or member.name.startswith("/") or ".." in member.name.split("/"):
            raise RegistryError("install:unsafe-archive-member", member.name)
    archive.extractall(destination)
