"""Staging an update from the share: snapshot, extract, verify, restore.

Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent,
commit f6c3eb1, hermes_cli/update_cmd.py and hermes_cli/update_cmd_maint.py),
Copyright (c) 2025 Nous Research, MIT License; see
licenses/third-party/hermes-agent-LICENSE.txt.

The order is the safety: a copy of the stores exists before anything is
extracted, every extracted file is checked against the manifest before any
staged program runs, and the pointer moves only after that program passes
its own health check. Nothing here opens a network connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from nexuusbot import __version__

CRITICAL = (
    "settings.sqlite3",
    "inbox.sqlite3",
    "memory.sqlite3",
    "ledger.sqlite3",
    "repetition.sqlite3",
    "preferences.json",
    "profile.learned.json",
    "memory.key",
)

UPDATE_DIR = Path("update")
STATE_NAME = "state.json"
SNAPSHOT_DIR = UPDATE_DIR / "snapshots"
VERSIONS_DIR = UPDATE_DIR / "versions"
POINTER_PATH = UPDATE_DIR / "current.json"

STATE_DEFAULTS = {
    "current": __version__,
    "previous": None,
    "pending": None,
    "lastCheckTs": 0,
    "lastResult": "none",
    "snapshot": None,
}


def _atomic_json(path: Path, document: dict) -> None:
    """Write JSON through a temp sibling and os.replace, never half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class UpdateState:
    """The small state document at <data>/update/state.json."""

    def __init__(self, data_dir: Path) -> None:
        """Bind the document to one data folder; nothing is read yet."""
        self.dir = Path(data_dir) / UPDATE_DIR
        self.path = self.dir / STATE_NAME

    def read(self) -> dict:
        """The stored document over defaults; a broken file reads as defaults."""
        document = dict(STATE_DEFAULTS)
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return document
        if isinstance(stored, dict):
            document.update(stored)
        return document

    def save(self, document: dict) -> dict:
        """Replace the whole document atomically and return what was written."""
        clean = dict(STATE_DEFAULTS)
        clean.update(document)
        _atomic_json(self.path, clean)
        return clean

    def set(self, **changes) -> dict:
        """Merge the named fields into the stored document atomically."""
        document = self.read()
        document.update(changes)
        return self.save(document)


def _sqlite_copy(source: Path, destination: Path) -> None:
    """Copy one live database with sqlite's own backup API."""
    origin = sqlite3.connect(source)
    try:
        target = sqlite3.connect(destination)
        try:
            origin.backup(target)
        finally:
            target.close()
    finally:
        origin.close()


def snapshot(data_dir: Path, now: datetime) -> Path:
    """Copy the critical stores under <data>/update/snapshots/<utc-stamp>/.

    One snapshot is kept; an update only ever needs the state in front of
    it. Databases use the backup API so a writer mid-transaction still
    yields a consistent copy.
    """
    root = Path(data_dir)
    folder = root / SNAPSHOT_DIR / now.strftime("%Y-%m-%dT%H-%M-%SZ")
    suffix = 2
    while folder.exists():
        folder = root / SNAPSHOT_DIR / f"{now.strftime('%Y-%m-%dT%H-%M-%SZ')}-{suffix}"
        suffix += 1
    folder.mkdir(parents=True)
    for name in CRITICAL:
        source = root / name
        if not source.is_file():
            continue
        if name.endswith(".sqlite3"):
            _sqlite_copy(source, folder / name)
        else:
            shutil.copy2(source, folder / name)
    for older in sorted((root / SNAPSHOT_DIR).iterdir())[:-1]:
        if older.is_dir() and older != folder:
            shutil.rmtree(older, ignore_errors=True)
    return folder


def _safe_member(name: str, destination: Path) -> Path:
    """The target for one archive member, or ValueError when it escapes."""
    normalized = name.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise ValueError("the update archive contains a path outside the bundle.")
    parts = PurePosixPath(normalized).parts
    if any(part in ("..", "") for part in parts):
        raise ValueError("the update archive contains a path outside the bundle.")
    target = (destination / normalized).resolve()
    if not target.is_relative_to(destination.resolve()):
        raise ValueError("the update archive contains a path outside the bundle.")
    return target


def extract(zip_path: Path, dest: Path) -> None:
    """Extract the bundle, refusing traversal, absolute paths and symlinks."""
    destination = Path(dest)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("the update archive contains a link.")
            target = _safe_member(info.filename, destination)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as handle:
                shutil.copyfileobj(source, handle)


def _sha256(path: Path) -> str:
    """The lower-case hex digest of one file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(folder: Path, manifest: dict) -> list[str]:
    """Every file the manifest names matches; nothing else is present.

    Returns plain sentences, empty when the folder is exactly the manifest.
    The manifest itself is allowed inside the bundle because the build
    writes it there; the updater separately requires the copy beside the
    zip to be byte-identical.
    """
    root = Path(folder)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return ["the manifest is not version 1."]
    files = manifest.get("files")
    if not isinstance(files, list):
        return ["the manifest lists no files."]
    problems: list[str] = []
    expected: set[str] = {"manifest.json"}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            problems.append("the manifest has a file without a path.")
            continue
        relative = entry["path"]
        if relative.startswith("/") or ".." in PurePosixPath(relative).parts:
            problems.append(f"{relative} is outside the bundle.")
            continue
        expected.add(relative)
        target = root / relative
        if not target.is_file():
            problems.append(f"{relative} is missing.")
            continue
        if entry.get("size") is not None and target.stat().st_size != entry.get("size"):
            problems.append(f"{relative} does not match the manifest.")
            continue
        if entry.get("sha256") != _sha256(target):
            problems.append(f"{relative} does not match the manifest.")
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if relative not in expected:
                problems.append(f"{relative} is not in the manifest.")
    return problems


def _integrity_ok(path: Path) -> bool:
    """True when sqlite reports this database as ok."""
    try:
        connection = sqlite3.connect(path)
        try:
            return connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return False


def restore_corrupt(data_dir: Path, snapshot_dir: Path | None) -> list[str]:
    """Restore only the sqlite files that fail integrity_check.

    A store the new version wrote correctly is left exactly as it is; a
    restore here is a repair, not a wholesale downgrade of the data.
    """
    if snapshot_dir is None:
        return []
    root = Path(data_dir)
    backup = Path(snapshot_dir)
    if not backup.is_dir():
        return []
    restored: list[str] = []
    for name in CRITICAL:
        if not name.endswith(".sqlite3"):
            continue
        source = backup / name
        live = root / name
        if not source.is_file() or not live.is_file():
            continue
        if _integrity_ok(live):
            continue
        for suffix in ("-wal", "-shm"):
            try:
                (root / (name + suffix)).unlink()
            except FileNotFoundError:
                pass
        shutil.copy2(source, live)
        restored.append(name)
    return restored


def write_pointer(data_dir: Path, version: str, target: Path) -> dict:
    """Write current.json: the version and the executable to launch."""
    document = {"version": version, "path": str(target)}
    _atomic_json(Path(data_dir) / POINTER_PATH, document)
    return document


def read_pointer(data_dir: Path) -> dict | None:
    """The current pointer, or None when no update ever wrote one."""
    try:
        document = json.loads((Path(data_dir) / POINTER_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None
