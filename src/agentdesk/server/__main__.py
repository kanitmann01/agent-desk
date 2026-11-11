"""Module entry point so `python -m agentdesk.server` works (used by tools/agent-desk.cmd)."""

import sys

from agentdesk.server.cli import main

if __name__ == "__main__":
    sys.exit(main())
