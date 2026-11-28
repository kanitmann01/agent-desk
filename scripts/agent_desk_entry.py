#!/usr/bin/env python3
"""Nuitka entry point for the Nexuus Bot bundle.

Nuitka is pointed at a script rather than at src/nexuusbot/server/ so the
compiled program keeps the real package name (nexuusbot) instead of
re-rooting nexuusbot.server as top-level "server". scripts/build_bundle.py
sets PYTHONPATH=src for the build and carries the canonical package plus
the compatibility alias package.
"""

from __future__ import annotations

import sys

from nexuusbot.server.cli import main

if __name__ == "__main__":
    sys.exit(main())
