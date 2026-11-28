"""The --self-check path: build the stores, run the desk check, never bind.

The command is the same check the updater runs on a staged build. It prints
one JSON document on stdout and uses the exit code for the answer.
"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import server_harness
from nexuusbot import config
from nexuusbot.server import cli, selfcheck


def _no_personal_config(monkeypatch, tmp_path):
    """Keep the developer's config.env from leaking into later tests.

    The CLI loads the real config file before it dispatches; an absent
    path is the loader's no-op, so the self-check still runs its real
    wiring without writing the file's env values for the rest of pytest.
    """
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "no-config.env")


def test_selfcheck_cli_exit_codes(tmp_path, monkeypatch, capsys):
    """A healthy folder exits 0; a failed check exits 1 and still prints JSON."""
    _no_personal_config(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "desk-data"))
    # The self-check must build stores, not a server: binding a port here
    # would make a background update health check conflict with the app.
    monkeypatch.setattr(
        "nexuusbot.server.app.create_server",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("self-check bound a server")),
    )
    assert cli.main(["--self-check", str(tmp_path / "desk-data")]) == 0
    printed = json.loads(capsys.readouterr().out.strip())
    assert printed["ok"] is True
    assert printed["version"]

    monkeypatch.setattr(
        selfcheck, "run", lambda data_dir: {"version": "0.1.0", "ok": False, "findings": []}
    )
    assert cli.main(["--self-check", str(tmp_path / "desk-data")]) == 1


def test_selfcheck_run_reports_findings_without_a_server(tmp_path, monkeypatch):
    """run() returns the same findings shape /api/desk-check uses."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "desk-data"))
    document = selfcheck.run(tmp_path / "desk-data")
    assert set(document) == {"version", "ok", "findings"}
    assert document["ok"] is True
    assert isinstance(document["findings"], list)


def test_run_staged_reads_the_json_document(tmp_path, monkeypatch):
    """A staged build that exits non-zero is a failed health check."""
    exe = tmp_path / "AgentDesk"
    exe.write_text("", encoding="utf-8")

    class Proc:
        returncode = 0
        stdout = '{"version": "0.2.0", "ok": true, "findings": []}'
        stderr = ""

    monkeypatch.setattr(selfcheck.subprocess, "run", lambda *a, **k: Proc())
    ok, note = selfcheck.run_staged([sys.executable, "-c", "pass"], tmp_path, timeout=5)
    assert ok is True
    assert note == ""

    class Bad:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(selfcheck.subprocess, "run", lambda *a, **k: Bad())
    ok, note = selfcheck.run_staged([sys.executable, "-c", "pass"], tmp_path, timeout=5)
    assert ok is False
    assert "check" in note.lower()
