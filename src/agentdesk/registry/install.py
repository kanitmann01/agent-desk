"""Pinned installation from the registry.

The client resolves its lockfile pin against the index, checks out the
pinned tag through ``git archive``, verifies the extracted tree digest
against the pin, runs the shared validator, and only then installs into
a versioned directory. Any refusal carries a named code, validator
style.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .index import PluginEntry, RegistryIndex, RegistryIndexError, load_index


class RegistryError(Exception):
    """A named install refusal: ``code`` is the stable vocabulary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Pin:
    version: str
    sha256: str | None = None


def tree_digest(plugin_dir: Path) -> str:
    """sha256 over sorted relpaths and file bytes: the release pin."""
    digest = hashlib.sha256()
    for path in sorted(Path(plugin_dir).rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(plugin_dir).as_posix()
        digest.update(rel.encode("utf-8") + b"\n")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def resolve(index: RegistryIndex, plugin_id: str,
            version: str, sha256: str | None = None) -> tuple[PluginEntry, object]:
    """Resolve a client pin against the index. Old pins keep resolving:
    releases are append-only history, and a pinned sha256 resolves even
    when the release is yanked, because the client already has it."""
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
            archive.extractall(tmp, filter="data")
        source = Path(tmp) / plugin_prefix
        if not source.is_dir():
            raise RegistryError("install:tag-missing",
                                f"tag {tag} has no {plugin_prefix}")
        shutil.copytree(source, destination)


def install_from_registry(registry_root: Path | str, plugin_id: str, *,
                          version: str, sha256: str | None = None,
                          destination: Path | str) -> dict:
    """Install one pinned release. Returns the install record."""
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
        _archive_plugin(registry_root, release.tag, plugin_prefix, staged)
        actual = tree_digest(staged)
        if actual != release.sha256:
            raise RegistryError(
                "install:hash-mismatch",
                f"content sha256 {actual[:12]} does not match the pinned "
                f"{release.sha256[:12]}")
        from agentdesk.validator.core import validate_plugin
        verdict = validate_plugin(staged)
        if not verdict.ok:
            first = verdict.failures[0]
            raise RegistryError("install:validator-failed",
                                f"{first.code}: {first.message}")
        if installed.exists():
            shutil.rmtree(installed)
        shutil.copytree(staged, installed)
    return {
        "ok": True,
        "plugin": plugin_id,
        "version": version,
        "sha256": release.sha256,
        "path": str(installed),
    }
