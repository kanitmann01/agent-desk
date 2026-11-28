"""Module entry point so `python -m nexuusbot.probe` works (used by tools/probe.cmd)."""

import sys

from nexuusbot.probe.cli import main

if __name__ == "__main__":
    sys.exit(main())
