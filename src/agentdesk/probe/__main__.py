"""Module entry point so `python -m agentdesk.probe` works (used by tools/probe.cmd)."""

import sys

from agentdesk.probe.cli import main

if __name__ == "__main__":
    sys.exit(main())
