"""The side-car smoke: one real turn against the local mock (spec 023).

The opt-in evidence that the contained engine turn works end to end:
boot the desk's mock endpoint in-process, run one real turn through the
engine boundary against the installed side-car venv, print the event
kinds the stream carried and the actions the boundary parsed, then boot
a throwaway desk and execute the parsed add_card through its own tools
route, printing the ledger entry it records. A PASS requires a result
event, at least one known action, no refusal, and an undoable
recommend.added entry with the card-added undo kind. It is evidence,
not a gate: the suite never runs it (the side-car itself is never
started by a test), and a machine without the side-car gets the named
refusal and the installer's command instead of a failure to guess at.

    python tools/engine_sidecar_check.py

Stdlib only, loopback only: the mock binds 127.0.0.1, the turn runs one
process under the side-car home folder, and the execution desk writes
only inside a throwaway temp folder with an in-memory keychain.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from layout_audit import _inert_gate_runners

MOCK_KEY = "sk-sidecar-check"
MOCK_MODEL = "mock-chat"


def _load_mock():
    """The mock endpoint module, by path (tools is not a package)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "agentdesk_mock_endpoint", ROOT / "tools" / "mock_endpoint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(clone: Path, *args: str) -> str:
    """One git answer inside a checkout, or '' when git cannot answer."""
    proc = subprocess.run(["git", "-C", str(clone), *args],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _checkout(home: Path, tag: str) -> tuple[Path, str, str] | None:
    """The pinned clone under this home, its HEAD and the tag's commit.

    The installer clones into `src`; a spike or a hand-built home may
    keep its checkout as `hermes-src`. A home with neither has no
    checkout to verify, which the marker (when present) still covers.
    """
    for name in ("src", "hermes-src"):
        clone = home / name
        if (clone / ".git").exists():
            return (clone,
                    _git(clone, "rev-parse", "HEAD"),
                    _git(clone, "rev-parse", f"{tag}^{{commit}}"))
    return None


def _pin_env(folder: Path) -> dict[str, str | None]:
    """Point the desk's data and template folders at this smoke's temp folder."""
    saved = {name: os.environ.get(name)
             for name in ("AGENTDESK_DATA", "AGENTDESK_TEMPLATES")}
    for name, child in (("AGENTDESK_DATA", "data"),
                        ("AGENTDESK_TEMPLATES", "templates")):
        path = folder / child
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    return saved


def _restore_env(saved: dict[str, str | None]) -> None:
    """Put every pinned variable back exactly as it was."""
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _boot_temp_desk(folder: Path):
    """Boot the real desk over a throwaway folder with a stand-in keychain.

    The data and template folders are this boot's own, and the keychain
    is the in-memory stand-in, so no real user store is read or written.
    """
    from nexuusbot.keys.secrets import KeychainSecrets, MemoryKeychain
    from nexuusbot.server import app as server_app

    saved = _pin_env(folder)
    try:
        server = server_app.create_server(
            port=0, keychain=KeychainSecrets(backend=MemoryKeychain()),
            gate_runners=_inert_gate_runners())
    except Exception:
        _restore_env(saved)
        raise
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, saved


def _close_stores(server) -> None:
    """Close every SQLite connection the throwaway desk holds.

    Windows will not delete the temporary folder while a connection is
    open, and some stores keep their connection on the store object.
    """
    for value in list(vars(server).values()):
        for holder in (value, getattr(value, "conn", None)):
            if isinstance(holder, sqlite3.Connection):
                try:
                    holder.close()
                except sqlite3.Error:
                    pass


def _stop_temp_desk(server, thread, saved: dict[str, str | None]) -> None:
    """Stop the throwaway desk and restore the environment it pinned."""
    try:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _close_stores(server)
    finally:
        _restore_env(saved)


def _post_action(server, action) -> tuple[int, dict]:
    """POST one parsed action to the desk's own tools route with its token."""
    data = json.dumps({"tool": action.tool, "args": dict(action.args),
                       "why": action.why}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/api/engine/tools", data=data,
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {server.engine_token}",
                 "Host": f"127.0.0.1:{server.port}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = {}
    return status, body if isinstance(body, dict) else {}


def main() -> int:
    """Run one real side-car turn against the mock and print what it saw."""
    parser = argparse.ArgumentParser(
        description="One real engine turn against the local mock endpoint")
    parser.add_argument("--home", default="",
                        help="the side-car home folder (default: the desk data folder's)")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="the turn's ceiling in seconds")
    args = parser.parse_args()

    from nexuusbot.engine import (
        ConnectionSpec,
        actions_from_events,
        available,
        cli_path,
        home_for,
        pinned_tag,
        read_marker,
        run_turn,
    )

    home = Path(args.home) if args.home else None
    if home is None:
        from nexuusbot.server.app import default_data_dir

        home = home_for(default_data_dir())
    if not available(home):
        cli = cli_path(home)
        print(f"FAIL no side-car is installed at the pinned tag (looked for {cli}).",
              flush=True)
        print("Install it once with:", flush=True)
        print("  python tools/install_engine_sidecar.py", flush=True)
        return 1
    marker = read_marker(home)
    if marker is None:
        print("install marker: none (a hand-built or pre-marker venv; the CLI "
              "file is the only check)", flush=True)
    else:
        tag = str(marker.get("tag") or "")
        commit = str(marker.get("commit") or "")
        if tag != pinned_tag() or len(commit) < 8:
            print(f"FAIL the install marker at {home} names tag {tag!r} commit "
                  f"{commit!r}, not {pinned_tag()}", flush=True)
            return 1
        print(f"install marker: {tag} {commit[:12]}", flush=True)
    checkout = _checkout(home, pinned_tag())
    if checkout is not None:
        clone, head, tagged = checkout
        if not head or not tagged or head != tagged:
            print(f"FAIL the checkout at {clone} is at {head[:12] or 'unreadable'}, "
                  f"not {pinned_tag()} ({tagged[:12] or 'unreadable'})", flush=True)
            return 1
        print(f"checkout: {clone.name} at {pinned_tag()} ({head[:12]})", flush=True)

    mock = _load_mock()
    mock_server = ThreadingHTTPServer(("127.0.0.1", 0), mock.MockEndpointHandler)
    mock_port = mock_server.server_address[1]
    thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    thread.start()
    context = json.dumps({
        "desk": "the smoke's throwaway desk",
        "names": {"memory": [], "agenda": None, "workbook": None},
    })
    connection = ConnectionSpec(
        base_url=f"http://127.0.0.1:{mock_port}/v1",
        api_key=MOCK_KEY, model=MOCK_MODEL)
    print(f"side-car home: {home}", flush=True)
    print(f"mock endpoint: {connection.base_url}", flush=True)
    try:
        result = run_turn(context, connection=connection, home=home,
                          timeout_s=args.timeout)
    finally:
        mock_server.shutdown()
        mock_server.server_close()
        thread.join(timeout=5)
    print(f"backend: {result.backend}", flush=True)
    kinds = [str(event.get("type") or "") for event in result.events]
    print(f"event kinds: {kinds}", flush=True)
    if result.note:
        print(f"note: {result.note}", flush=True)
    actions, refused = actions_from_events(result.events)
    for action in actions:
        print(f"action: {action.tool} args={action.args} "
              f"undo_kinds={action.undo_kinds}", flush=True)
    for sentence in refused:
        print(f"refused: {sentence}", flush=True)
    saw_result = any(kind == "result" for kind in kinds)
    problems: list[str] = []
    if not saw_result:
        problems.append("the turn never carried a result event.")
    if not actions:
        problems.append("the turn drew no tool actions.")
    if refused:
        problems.append("the boundary refused a call: " + " ".join(refused))
    if problems:
        print("FAIL " + " ".join(problems), flush=True)
        return 1
    card_action = next(
        (action for action in actions if action.tool == "add_card"), None)
    if card_action is None:
        print("FAIL the turn drew no add_card action to execute.", flush=True)
        return 1
    with tempfile.TemporaryDirectory(prefix="agentdesk-engine-smoke-") as folder:
        server, desk_thread, saved = _boot_temp_desk(Path(folder))
        try:
            status, body = _post_action(server, card_action)
            ledger = getattr(server, "ledger", None)
            entry_id = str(body.get("entryId") or "")
            entry = (ledger.get(entry_id)
                     if ledger is not None and entry_id else None)
        finally:
            _stop_temp_desk(server, desk_thread, saved)
    if status != 201 or entry is None:
        print(f"FAIL the tools route answered {status}: "
              f"{body.get('error') or body!r}", flush=True)
        return 1
    print(f"ledger: {entry.id} {entry.action} undo_kind={entry.undo_kind} "
          f"undoable={entry.undoable}", flush=True)
    if entry.action != "recommend.added" or entry.undo_kind != "card-added" \
            or not entry.undoable:
        print("FAIL the add_card entry is not an undoable recommend.added "
              "with card-added.", flush=True)
        return 1
    print(f"PASS the turn carried a result event, {len(actions)} action(s), "
          "and the tools route recorded the card with card-added undo.",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
