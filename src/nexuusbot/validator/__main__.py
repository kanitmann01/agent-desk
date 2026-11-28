"""Allow ``python -m nexuusbot.validator``; the CLI lives in ``cli.py``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
