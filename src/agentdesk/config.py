"""Optional configuration file support: ~/.agent-desk/config.env.

The app runs with zero configuration; this file exists so the corporate
endpoint and the calendar path can be set on a locked-down laptop where
editing OS environment variables is not an option. Format is plain
KEY=VALUE lines: # comments, blank lines ignored, optional surrounding
quotes stripped. Only AGENTDESK_-prefixed keys are honored, and a real
environment variable always wins over the file (setdefault semantics).
"""

import os
from pathlib import Path

PREFIX = "AGENTDESK_"
DEFAULT_PATH = Path(Path.home(), ".agent-desk", "config.env")


def parse_env_file(text: str) -> dict[str, str]:
    """Parse the file body into a dict of AGENTDESK_-prefixed keys only.

    Everything else (comments, blank lines, foreign keys, values with no
    content) is dropped, so a shared machine config cannot inject
    arbitrary environment variables into the app.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not key.startswith(PREFIX) or not value:
            continue
        values[key] = value
    return values


def load_env_file(path=None, environ=None) -> dict[str, str]:
    """Apply the config file to the environment; returns what was applied.

    Keys already present in the environment are left alone: an explicit
    OS-level setting outranks the file. A missing or unreadable file is
    not an error; the app simply runs unconfigured as always.
    """
    environ = os.environ if environ is None else environ
    path = DEFAULT_PATH if path is None else Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    applied: dict[str, str] = {}
    for key, value in parse_env_file(text).items():
        if key in environ:
            continue  # the real environment always wins
        environ[key] = value
        applied[key] = value
    return applied
