"""Command line interface for the dashboard server.

Usage (via tools/agent-desk.cmd or `python -m agentdesk.server`):

    python -m agentdesk.server [--port N] [--no-browser]

The host flag does not exist on purpose: the app binds 127.0.0.1 and
cannot be talked out of it. Exit codes: 0 clean shutdown, 2 usage errors.
"""

import argparse

from agentdesk.config import load_env_file
from agentdesk.server import app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agentdesk.server",
        description="Start the Agent Desk dashboard (127.0.0.1 only).",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Before anything builds the bridge or the endpoint adapter, so both
    # see the config file's values; real environment variables still win.
    load_env_file()
    server = app.create_server(port=args.port)
    app.serve(server, open_browser=not args.no_browser)
    return 0
