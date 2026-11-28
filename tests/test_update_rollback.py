"""Self-update at the HTTP seam: off by default, staged only on a pass,
first-start rollback, and Undo on the pointer.

The update share is a local folder in these tests; nothing here reaches a
network. Auth links and model keys never appear in this file.
"""

import hashlib
import json
import sqlite3
import zipfile

import server_harness
from agentdesk import update
from agentdesk.update import stage

EXE = "AgentDesk.exe"


def _integrity(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def _sqlite(path, value):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()


def _publish(root, version="0.1.1"):
    """One fake bundle: the exe is a stub, which run_staged is patched over."""
    folder = root / version
    folder.mkdir(parents=True)
    files = {
        EXE: b"stub exe",
        "README.txt": b"a build",
        "sbom.cdx.json": b"{}",
    }
    entries = [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())
    ]
    manifest = {
        "schema_version": 1,
        "product": "Nexuus Bot",
        "version": version,
        "files": entries,
    }
    payload = json.dumps(manifest, sort_keys=True).encode("utf-8")
    with zipfile.ZipFile(folder / "agent-desk.zip", "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", payload)
    (folder / "manifest.json").write_bytes(payload)
    return folder


def _boot(tmp_path, monkeypatch, channel=None, auto=False):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "desk-data"))
    booted = server_harness.Booted()
    booted.server.settings.set("auto_update", bool(auto))
    if channel is not None:
        booted.server.settings.set("update_channel", str(channel))
    return booted


def test_off_by_default_stages_nothing(tmp_path, monkeypatch):
    """The shipped default reads the share and never copies or executes."""
    channel = tmp_path / "share"
    _publish(channel)
    booted = _boot(tmp_path, monkeypatch, channel=channel)
    try:
        auth = booted.exchange()
        status, _headers, body = booted.request("GET", "/api/update", auth)
        assert status == 200
        payload = json.loads(body)
        assert payload["autoUpdate"] is False
        assert payload["channelSet"] is True

        status, _headers, body = booted.post_json("/api/update/check", {}, auth)
        assert status == 200
        payload = json.loads(body)
        # A newer version on the share is reported in available. Nothing was
        # staged, so the last result stays the shipped none.
        assert payload["lastResult"] == "none"
        assert payload["available"] == "0.1.1"
        assert not (tmp_path / "desk-data" / "update" / "versions").exists()

        status, _headers, body = booted.request("GET", "/settings", auth)
        page = body.decode("utf-8")
        assert "Version 0.1.1 is on the share. Install updates is off." in page
        assert "Install updates" in page
    finally:
        booted.close()


def test_apply_writes_pointer_only_on_pass(tmp_path, monkeypatch):
    """A verified bundle writes state, pointer and one undoable ledger row."""
    channel = tmp_path / "share"
    _publish(channel)
    booted = _boot(tmp_path, monkeypatch, channel=channel, auto=True)
    try:
        result = update.run_update(
            booted.server, health_runner=lambda exe, data: (True, "")
        )
        assert result["result"] == "staged"
        data_dir = tmp_path / "desk-data"
        state = stage.UpdateState(data_dir).read()
        assert state["pending"] == "0.1.1"
        assert state["lastResult"] == "staged"
        pointer = json.loads(
            (data_dir / "update" / "current.json").read_text(encoding="utf-8")
        )
        assert pointer["version"] == "0.1.1"
        assert pointer["path"].endswith(EXE)

        entries = booted.server.ledger.entries(limit=10)
        applied = [row for row in entries if row.action == "update.applied"]
        assert len(applied) == 1
        assert applied[0].undo_kind == "version-pointer"
        assert update.summary(data_dir)["banner"] == (
            "Version 0.1.1 is ready. Restart Nexuus Bot from its shortcut to switch."
        )
    finally:
        booted.close()


def test_checking_again_after_staging_does_not_restage(tmp_path, monkeypatch):
    """A staged version waits for the restart; the next pass repeats nothing."""
    channel = tmp_path / "share"
    _publish(channel)
    booted = _boot(tmp_path, monkeypatch, channel=channel, auto=True)
    try:
        calls = []
        runner = lambda exe, data: (calls.append(1) or True, "")
        first = update.run_update(booted.server, health_runner=runner)
        second = update.run_update(booted.server, health_runner=runner)
        assert first["result"] == "staged"
        assert second["result"] == "staged"
        assert len(calls) == 1
        entries = [row for row in booted.server.ledger.entries(limit=20)
                   if row.action == "update.applied"]
        assert len(entries) == 1
    finally:
        booted.close()


def test_older_staged_versions_are_pruned(tmp_path, monkeypatch):
    """After a stage only the new version and the one it replaced remain."""
    channel = tmp_path / "share"
    _publish(channel)
    booted = _boot(tmp_path, monkeypatch, channel=channel, auto=True)
    try:
        data_dir = tmp_path / "desk-data"
        older = data_dir / "update" / "versions" / "0.0.9"
        older.mkdir(parents=True)
        result = update.run_update(
            booted.server, health_runner=lambda exe, data: (True, "")
        )
        assert result["result"] == "staged"
        assert not older.exists()
        assert (data_dir / "update" / "versions" / "0.1.1").is_dir()
    finally:
        booted.close()


def test_digest_mismatch_not_staged(tmp_path, monkeypatch):
    """A tampered archive never reaches the pointer or the health runner."""
    channel = tmp_path / "share"
    folder = _publish(channel)
    # Replace the outside manifest after the zip was made: the two copies
    # are no longer byte-identical, and the digest check must refuse it.
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    booted = _boot(tmp_path, monkeypatch, channel=channel, auto=True)
    try:
        called = []
        result = update.run_update(
            booted.server,
            health_runner=lambda exe, data: called.append(data) or (True, ""),
        )
        assert result["result"] == "health-failed"
        assert called == []
        data_dir = tmp_path / "desk-data"
        state = stage.UpdateState(data_dir).read()
        assert state["lastResult"] == "health-failed"
        assert state["pending"] is None
        assert not (data_dir / "update" / "current.json").exists()

        auth = booted.exchange()
        status, _headers, body = booted.request("GET", "/api/desk-check", auth)
        assert status == 200
        ids = [row["id"] for row in json.loads(body)["findings"]]
        assert "update-failed" in ids
        page = booted.request("GET", "/settings", auth)[2].decode("utf-8")
        assert "The manifest in the bundle does not match the share." in page
    finally:
        booted.close()


def test_first_start_failure_rolls_back_and_restores_corrupt_db(tmp_path, monkeypatch):
    """A pending version that fails its own check goes back; the DB is restored."""
    data_dir = tmp_path / "desk-data"
    data_dir.mkdir()
    _sqlite(data_dir / "settings.sqlite3", "healthy")
    _sqlite(data_dir / "inbox.sqlite3", "snapshot")
    healthy = (data_dir / "settings.sqlite3").read_bytes()
    snap = stage.snapshot(data_dir, __import__("datetime").datetime(2026, 11, 22, 9))
    (data_dir / "inbox.sqlite3").write_bytes(b"broken")
    previous = data_dir / "update" / "versions" / "0.1.0" / EXE
    previous.parent.mkdir(parents=True)
    previous.write_text("old", encoding="utf-8")
    stage.write_pointer(data_dir, "0.1.0", previous)
    state = stage.UpdateState(data_dir)
    state.set(
        current="0.1.0",
        previous="0.1.0",
        pending="0.1.1",
        snapshot=snap.name,
        lastResult="staged",
    )
    # The staged pointer the launcher would have moved to on restart.
    stage.write_pointer(data_dir, "0.1.1", data_dir / "update" / "versions" / "0.1.1" / EXE)

    result = update.first_start(
        data_dir, checker=lambda: {"version": "0.1.1", "ok": False, "findings": []}
    )
    assert result["lastResult"] == "rolled-back"
    pointer = json.loads(
        (data_dir / "update" / "current.json").read_text(encoding="utf-8")
    )
    assert pointer["version"] == "0.1.0"
    assert _integrity(data_dir / "inbox.sqlite3") == "ok"
    assert (data_dir / "settings.sqlite3").read_bytes() == healthy
    assert update.summary(data_dir)["banner"] == (
        "This version failed its check. The desk went back to 0.1.0. "
        "Restart from the shortcut to finish."
    )


def test_undo_applied_rolls_back(tmp_path, monkeypatch):
    """Undo on update.applied puts the previous pointer back."""
    channel = tmp_path / "share"
    _publish(channel)
    booted = _boot(tmp_path, monkeypatch, channel=channel, auto=True)
    try:
        earlier = tmp_path / "desk-data" / "update" / "versions" / "0.1.0" / EXE
        earlier.parent.mkdir(parents=True)
        earlier.write_text("old", encoding="utf-8")
        stage.write_pointer(tmp_path / "desk-data", "0.1.0", earlier)
        update.run_update(booted.server, health_runner=lambda exe, data: (True, ""))
        entry = [
            row for row in booted.server.ledger.entries(limit=10)
            if row.action == "update.applied"
        ][0]
        auth = booted.exchange()
        status, _headers, body = booted.post_json(
            "/api/ledger/undo", {"id": entry.id}, auth
        )
        assert status == 200, body
        pointer = json.loads(
            (tmp_path / "desk-data" / "update" / "current.json").read_text(encoding="utf-8")
        )
        assert pointer["version"] == "0.1.0"
        assert stage.UpdateState(tmp_path / "desk-data").read()["lastResult"] == "rolled-back"
    finally:
        booted.close()


def test_no_network_in_update_package():
    """The update package is file-share code; it has no network client."""
    import agentdesk.update as package

    root = package.__path__[0]
    forbidden = ("urllib", "http.client", "socket", "requests", "httpx")
    for path in __import__("pathlib").Path(root).glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden), path.name

def test_settings_page_lists_the_update_controls(tmp_path, monkeypatch):
    """The Updates section explains the share and every control it offers."""
    channel = tmp_path / "share"
    _publish(channel)
    booted = _boot(tmp_path, monkeypatch, channel=channel)
    try:
        auth = booted.exchange()
        status, _headers, body = booted.request("GET", "/settings", auth)
        assert status == 200
        page = body.decode("utf-8")
        for sentence in (
            "id='updates'",
            "Update share",
            "Install updates",
            "Update plugins too",
            "Check now",
            "Current version",
        ):
            assert sentence in page
    finally:
        booted.close()


def test_update_step_stages_and_the_dashboard_says_restart(tmp_path, monkeypatch):
    """A pass checks the share, stages a good bundle and shows the banner."""
    channel = tmp_path / "share"
    _publish(channel)
    booted = _boot(tmp_path, monkeypatch, channel=channel, auto=True)
    monkeypatch.setattr(update, "_default_health", lambda exe, data: (True, ""))
    try:
        results = booted.server.agent_loop.run_pass(only={"update"})
        assert results[0]["name"] == "update"
        assert results[0]["ok"] is True
        data_dir = tmp_path / "desk-data"
        state = stage.UpdateState(data_dir).read()
        assert state["pending"] == "0.1.1"
        assert state["lastResult"] == "staged"

        auth = booted.exchange()
        status, _headers, body = booted.request("GET", "/api/dashboard", auth)
        assert status == 200
        payload = json.loads(body)
        assert payload["update"]["banner"] == (
            "Version 0.1.1 is ready. Restart Nexuus Bot from its shortcut to switch."
        )
        page = booted.request("GET", "/", auth)[2].decode("utf-8")
        assert "Version 0.1.1 is ready. Restart Nexuus Bot from its shortcut to switch." in page
        assert "class='alert'" in page
    finally:
        booted.close()


def test_update_check_failure_is_audited_and_named(tmp_path, monkeypatch):
    """An unreadable share is one audit row and the plain cause on Settings."""
    booted = _boot(tmp_path, monkeypatch, channel=tmp_path / "missing", auto=True)
    try:
        booted.server.agent_loop.run_pass(only={"update"})
        auth = booted.exchange()
        status, _headers, body = booted.request("GET", "/settings/activity", auth)
        assert status == 200
        page = body.decode("utf-8")
        assert "update.check-failed" in page
        assert "Update" in page
    finally:
        booted.close()
