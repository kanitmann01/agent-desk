#!/bin/sh
# Nexuus Bot: double-click me from Finder. The dashboard opens in your browser.
# No elevation, ever: nothing here asks for a password.
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/../src:$PYTHONPATH"

# The server detaches into the background with its output in the log, so this
# Terminal window can close: the browser is the surface, not the console.
LOG="$HOME/.agent-desk/agent-desk.log"

if command -v python3 >/dev/null 2>&1; then
  if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
    mkdir -p "$HOME/.agent-desk"
    nohup python3 -m nexuusbot.server >>"$LOG" 2>&1 &
    echo "Nexuus Bot is starting. Your browser opens when the server is up."
    echo "Log: $LOG"
    exit 0
  fi
fi

# Last rung: uv bootstraps its own Python. Native TLS reads the macOS system
# keychain; the Windows-only certs spelling does nothing on a Mac, so only
# UV_NATIVE_TLS is set here.
if command -v uv >/dev/null 2>&1; then
  mkdir -p "$HOME/.agent-desk"
  UV_NATIVE_TLS=1 nohup uv run --no-project python -m nexuusbot.server >>"$LOG" 2>&1 &
  echo "Nexuus Bot is starting via uv. Your browser opens when the server is up."
  echo "Log: $LOG"
  exit 0
fi

echo "python3 not found on PATH (macOS has no bare python) or older than 3.10, and no uv. Install Python 3.10+ for your user, or install uv."
exit 1
