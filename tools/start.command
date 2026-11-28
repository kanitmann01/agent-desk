#!/bin/sh
# Nexuus Bot: start everything.
# Double-click me for the dashboard (same as agent-desk.command).
# From a terminal, "./start.command dev" runs the development stack:
# the Python API in the background with a pid file, and the
# live-reloading UI dev server in the foreground (Ctrl+C stops the UI).
# No elevation, ever: nothing here asks for a password.
DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$1" = "dev" ]; then
  export PYTHONPATH="$DIR/../src:$PYTHONPATH"
  if ! command -v npm >/dev/null 2>&1; then
    echo "node/npm not found. The committed UI bundle is served by the API anyway:"
    echo "double-click agent-desk.command instead."
    exit 1
  fi
  if [ ! -f "$DIR/../frontend/package.json" ]; then
    echo "frontend/ was not found, so there is no dev server to start."
    echo "double-click agent-desk.command instead."
    exit 1
  fi
  LOG="$HOME/.agent-desk/agent-desk-dev.log"
  PID="$HOME/.agent-desk/agent-desk-dev.pid"
  mkdir -p "$HOME/.agent-desk"
  PY=""
  if command -v python3 >/dev/null 2>&1 && \
     python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
    PY=python3
  elif command -v uv >/dev/null 2>&1; then
    PY="uv run --no-project python"
  else
    echo "python3 not found (macOS has no bare python) or older than 3.10, and no uv."
    echo "Install Python 3.10+ for your user, or install uv."
    exit 1
  fi
  # API in the background: its one-time start link lands in the dev log.
  $PY -m nexuusbot.server --port 8765 --no-browser >>"$LOG" 2>&1 &
  echo $! > "$PID"
  echo "API running on port 8765. Log: $LOG"
  echo "Stop it later with: kill \$(cat $PID)"
  # UI dev server in the foreground: Ctrl+C returns here.
  echo "Open the UI at http://localhost:5199/static/spa/"
  echo "If it says a session is required: open the start link above with"
  echo "127.0.0.1:8765 replaced by localhost:5199."
  echo "Starting the UI dev server..."
  npm --prefix "$DIR/../frontend" run dev
  kill "$(cat "$PID")" 2>/dev/null
  rm -f "$PID"
  exit 0
fi

exec "$DIR/agent-desk.command"
