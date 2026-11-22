"""Self-checks that answer before the desk serves, and for a staged copy.

The staged build has to prove it can read the same data folder before the
launcher points at it. run() builds the read-only stores without binding a
server, runs the desk checks, and reports one JSON document; run_staged()
runs the same command in a child process against a copy of the data.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agentdesk import __version__
from agentdesk.deskcheck import DeskContext, Finding, SEVERITY_FATAL, finding_to_api, run_checks

FINDING_ID = "selfcheck-crashed"


def _closers(stores: list) -> None:
    """Close whatever a partially built check context managed to open."""
    for store in stores:
        if store is None:
            continue
        close = getattr(store, "close", None)
        if callable(close):
            try:
                close()
                continue
            except Exception:
                pass
        conn = getattr(store, "conn", None)
        close = getattr(conn, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _build_context(data_dir: Path):
    """Build the read-only stores the checks need, never a bound server."""
    from agentdesk.server import app as server_app

    settings = server_app._default_settings_store()
    inbox = server_app._default_inbox_store()
    excel = server_app._default_excel_watch()
    calendar = server_app._default_calendar_bridge(settings)
    ledger = server_app._default_ledger()
    ctx = DeskContext(
        settings=settings,
        inbox=inbox,
        excel=excel,
        calendar=calendar,
        plugins=None,
        catalog_ids=frozenset(),
        data_dir=data_dir,
        ledger=ledger,
    )
    return ctx, [settings, inbox, excel, calendar, ledger]


def run(data_dir: Path) -> dict:
    """Run the desk checks against one data folder and return the JSON shape.

    The caller is the staged build's --self-check, before any launcher points
    at it. A fatal finding means the copy is not fit to serve; a normal
    attention finding is the desk's own business, not a failed check.
    """
    data_dir = Path(data_dir)
    previous = os.environ.get("AGENTDESK_DATA")
    os.environ["AGENTDESK_DATA"] = str(data_dir)
    stores = []
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        ctx, stores = _build_context(data_dir)
        result = run_checks(ctx, should_fix=False)
        findings = [finding_to_api(finding) for finding in result.findings]
        ok = not any(finding.severity == SEVERITY_FATAL for finding in result.findings)
        return {"version": __version__, "ok": ok, "findings": findings}
    except Exception as exc:  # a broken build must answer, not traceback
        finding = Finding(
            id=FINDING_ID,
            title="The desk could not check this data folder",
            cause=f"The check raised {type(exc).__name__}, so its answer is missing.",
            severity=SEVERITY_FATAL,
            confident=False,
            fix="none",
            fix_label="",
        )
        return {"version": __version__, "ok": False, "findings": [finding_to_api(finding)]}
    finally:
        _closers(stores)
        if previous is None:
            os.environ.pop("AGENTDESK_DATA", None)
        else:
            os.environ["AGENTDESK_DATA"] = previous


def run_staged(command, data_copy: Path, timeout: float = 60) -> tuple[bool, str]:
    """Run a staged copy's --self-check and require exit 0 with JSON ok true."""
    if isinstance(command, (str, Path)):
        argv = [str(command), "--self-check", str(data_copy)]
    else:
        argv = [str(part) for part in command]
    env = os.environ.copy()
    env["AGENTDESK_DATA"] = str(data_copy)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"The staged copy did not answer its check: {exc}"
    if proc.returncode != 0:
        note = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return False, f"The staged copy failed its check: {note}"[:300]
    try:
        document = json.loads(proc.stdout or "")
    except (TypeError, ValueError):
        return False, "The staged copy did not answer its check with JSON."
    if not isinstance(document, dict) or not document.get("ok"):
        return False, "The staged copy reported a failed check."
    return True, ""


def command_for(executable: Path, data_copy: Path) -> list[str]:
    """The self-check command for a staged build.

    A frozen AgentDesk.exe takes the flag itself; a source checkout runs the
    module through the same interpreter, with PYTHONPATH pointing at it.
    """
    executable = Path(executable)
    if executable.suffix.lower() == ".exe" or executable.is_file():
        return [str(executable), "--self-check", str(data_copy)]
    return [sys.executable, "-m", "agentdesk.server", "--self-check", str(data_copy)]
