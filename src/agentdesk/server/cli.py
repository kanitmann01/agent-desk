"""Command line interface for the dashboard server.

Usage (via tools/agent-desk.cmd or `python -m agentdesk.server`):

    python -m agentdesk.server [--port N] [--no-browser]
    python -m agentdesk.server --self-check DATA_DIR

The host flag does not exist on purpose: the app binds 127.0.0.1 and
cannot be talked out of it. Exit codes: 0 clean shutdown or a passing
self-check, 1 a failed self-check, 2 usage errors.
"""

import argparse
import json
from pathlib import Path

from agentdesk import PRODUCT_NAME
from agentdesk.config import load_env_file
from agentdesk.server import app, selfcheck


def build_parser() -> argparse.ArgumentParser:
    """The argparse definition for `python -m agentdesk.server`.

    --port defaults to None rather than PREFERRED_PORT so create_server can try the
    preferred port and fall back to a free one instead of failing.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agentdesk.server",
        description=f"Start the {PRODUCT_NAME} dashboard (127.0.0.1 only).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port to listen on (default {app.PREFERRED_PORT}, "
        "falls back to a free port when taken)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the default browser (used by tests and tools)",
    )
    parser.add_argument(
        "--self-check",
        metavar="DATA_DIR",
        default=None,
        help="check one data folder and print JSON without serving",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse argv, load the env file, then serve until the process stops.

    The env file is loaded before any bridge or endpoint is constructed so both read the
    same configuration; real environment variables still win. Returns 0 once the server
    stops.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    # Before anything builds the bridge or the endpoint adapter, so both
    # see the config file's values; real environment variables still win.
    load_env_file()
    if args.self_check is not None:
        document = selfcheck.run(Path(args.self_check))
        print(json.dumps(document, sort_keys=True))
        return 0 if document.get("ok") else 1
    server = app.create_server(port=args.port)
    app.serve(server, open_browser=not args.no_browser)
    return 0
