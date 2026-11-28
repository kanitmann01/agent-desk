#!/bin/sh
# Nexuus Bot P0 probe: double-click me from Finder. No elevation, ever.
DIR="$(cd "$(dirname "$0")" && pwd)"
# Finder starts .command files in the user home; the report lands in
# cwd/probe-run, so cd to the script dir like a double-clicked .cmd does.
cd "$DIR" || exit 1
export PYTHONPATH="$DIR/../src:$PYTHONPATH"

if command -v python3 >/dev/null 2>&1 && \
   python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
  python3 -m nexuusbot.probe "$@"
elif command -v uv >/dev/null 2>&1; then
  # Last rung: uv bootstraps its own Python. Native TLS reads the macOS system
  # keychain; the Windows-only certs spelling does nothing on a Mac, so only
  # UV_NATIVE_TLS is set here.
  UV_NATIVE_TLS=1 uv run --no-project python -m nexuusbot.probe "$@"
else
  echo "python3 not found on PATH (macOS has no bare python) or older than 3.10, and no uv. Install Python 3.10+ for your user, or install uv."
fi

# The report must stay readable: hold the window like the .cmd's pause does.
printf "Press Return to close this window..."
read -r _
