#!/usr/bin/env python3
"""Nuitka entry point for the Nexuus Bot bundle.

Nuitka is pointed at a script rather than at src/agentdesk/server/ so the
compiled program keeps the real package name (agentdesk) instead of
re-rooting agentdesk.server as top-level "server". scripts/build_bundle.py
sets PYTHONPATH=src for the build.
"""

from __future__ import annotations

import sys

from agentdesk.server.cli import main

if __name__ == "__main__":
    sys.exit(main())
