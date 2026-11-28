"""Staging an update: snapshots, zip-slip refusals, digests and restore.

Nothing executes and no pointer moves until every file matches the manifest.
A corrupted database is the only thing a rollback replaces; a healthy one is
left exactly as the new version wrote it.
"""

import json
import sqlite3
import zipfile

import pytest

from nexuusbot.update import stage


def _sqlite(path, value):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()


def _integrity(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def _bundle(root, version="0.2.0", files=None):
    """A version folder with a zip and the same manifest beside it."""
    folder = root / version
    folder.mkdir(parents=True)
    items = dict(files or {"AgentDesk.exe": b"stub exe", "README.txt": b"hello"})
    entries = [
        {"path": name, "size": len(data),
         "sha256": __import__("hashlib").sha256(data).hexdigest()}
        for name, data in sorted(items.items())
    ]
    manifest = {
        "schema_version": 1,
        "product": "Nexuus Bot",
        "version": version,
        "files": entries,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    with zipfile.ZipFile(folder / "agent-desk.zip", "w") as archive:
        for name, data in items.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", manifest_bytes)
    (folder / "manifest.json").write_bytes(manifest_bytes)
    return folder


def test_zip_slip_refused(tmp_path):
    """An archive member that would land outside the staging folder is refused."""
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", b"no")
    with pytest.raises(ValueError):
        stage.extract(archive, tmp_path / "staged")
    assert not (tmp_path / "escape.txt").exists()

    absolute = tmp_path / "absolute.zip"
    with zipfile.ZipFile(absolute, "w") as zf:
        zf.writestr("C:/Windows/escape.txt", b"no")
    with pytest.raises(ValueError):
        stage.extract(absolute, tmp_path / "staged-two")


def test_digest_mismatch_not_staged(tmp_path):
    """One changed byte is a list of problems, not a staged version."""
    folder = _bundle(tmp_path / "share")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    staged = tmp_path / "staged"
    stage.extract(folder / "agent-desk.zip", staged)
    (staged / "README.txt").write_bytes(b"tampered")
    problems = stage.verify(staged, manifest)
    assert "README.txt" in " ".join(problems)


def test_missing_and_extra_files_are_reported(tmp_path):
    """The manifest is the whole truth about the folder."""
    folder = _bundle(tmp_path / "share")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    staged = tmp_path / "staged"
    stage.extract(folder / "agent-desk.zip", staged)
    (staged / "README.txt").unlink()
    (staged / "sneaked.txt").write_text("extra", encoding="utf-8")
    problems = " ".join(stage.verify(staged, manifest))
    assert "README.txt" in problems
    assert "sneaked.txt" in problems


def test_snapshot_and_integrity_restore(tmp_path):
    """A corrupt sqlite file is restored; a healthy one is left alone."""
    data = tmp_path / "data"
    data.mkdir()
    _sqlite(data / "settings.sqlite3", "keep")
    _sqlite(data / "inbox.sqlite3", "restore")
    snap = stage.snapshot(data, __import__("datetime").datetime(2026, 11, 22, 9, 0, 0))
    assert (snap / "settings.sqlite3").exists()
    assert (snap / "inbox.sqlite3").exists()

    healthy_bytes = (data / "settings.sqlite3").read_bytes()
    (data / "inbox.sqlite3").write_bytes(b"not a database at all")
    restored = stage.restore_corrupt(data, snap)
    assert restored == ["inbox.sqlite3"]
    assert _integrity(data / "inbox.sqlite3") == "ok"
    assert (data / "settings.sqlite3").read_bytes() == healthy_bytes


def test_snapshot_keeps_only_the_newest(tmp_path):
    """One snapshot is enough to roll back the update in front of us."""
    data = tmp_path / "data"
    data.mkdir()
    _sqlite(data / "settings.sqlite3", "one")
    first = stage.snapshot(data, __import__("datetime").datetime(2026, 11, 22, 9, 0, 0))
    second = stage.snapshot(data, __import__("datetime").datetime(2026, 11, 22, 10, 0, 0))
    assert first != second
    assert not first.exists()
    assert second.exists()


def test_update_state_shape_and_pointer(tmp_path):
    """The state starts from the shipped defaults and the pointer is atomic json."""
    state = stage.UpdateState(tmp_path)
    document = state.read()
    assert document["pending"] is None
    assert document["lastResult"] == "none"
    assert document["current"]
    state.set(pending="0.2.0", lastResult="staged")
    assert stage.UpdateState(tmp_path).read()["pending"] == "0.2.0"

    target = tmp_path / "versions" / "0.2.0" / "AgentDesk.exe"
    stage.write_pointer(tmp_path, "0.2.0", target)
    pointer = json.loads((tmp_path / "update" / "current.json").read_text(encoding="utf-8"))
    assert pointer == {"version": "0.2.0", "path": str(target)}
