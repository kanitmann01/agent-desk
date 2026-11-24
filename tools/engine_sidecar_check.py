"""The side-car smoke: one real turn against the local mock (spec 023).

The opt-in evidence that the contained engine turn works end to end:
boot the desk's mock endpoint in-process, run one real turn through the
engine boundary against the installed side-car venv, and print the
event kinds the stream carried and the actions the boundary parsed. A
PASS requires a result event, at least one known action and no refusal.
It is evidence, not a gate: the suite
never runs it (the side-car itself is never started by a test), and a
machine without the side-car gets the named refusal and the installer's
command instead of a failure to guess at.

    python tools/engine_sidecar_check.py

Stdlib only, loopback only: the mock binds 127.0.0.1, the turn runs one
process under the side-car home folder, and nothing outside that folder
is read or written.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

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


def main() -> int:
    """Run one real side-car turn against the mock and print what it saw."""
    parser = argparse.ArgumentParser(
        description="One real engine turn against the local mock endpoint")
    parser.add_argument("--home", default="",
                        help="the side-car home folder (default: the desk data folder's)")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="the turn's ceiling in seconds")
    args = parser.parse_args()

    from agentdesk.engine import (
        ConnectionSpec,
        actions_from_events,
        available,
        cli_path,
        home_for,
        run_turn,
    )

    home = Path(args.home) if args.home else None
    if home is None:
        from agentdesk.server.app import default_data_dir

        home = home_for(default_data_dir())
    if not available(home):
        cli = cli_path(home)
        print(f"FAIL no side-car is installed (looked for {cli}).", flush=True)
        print("Install it once with:", flush=True)
        print("  python tools/install_engine_sidecar.py", flush=True)
        return 1

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
    print(f"PASS the turn carried a result event and {len(actions)} "
          "action(s).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
