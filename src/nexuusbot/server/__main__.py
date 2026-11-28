"""Module entry point so `python -m nexuusbot.server` works (used by tools/agent-desk.cmd)."""

import sys

from nexuusbot.server.cli import main

if __name__ == "__main__":
    sys.exit(main())
