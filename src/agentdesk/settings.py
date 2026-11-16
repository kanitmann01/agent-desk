"""Settings: toggles and the typed endpoint, with defaults that need no
documentation.

The controls are booleans or small choices; the endpoint rows (base URL,
API key, model) are free text the user types once in the app, so research
works without touching environment variables. The inbox reads its
quiet-hours and budget values from here, so what this page shows is what
the app enforces. The key row is a secret: callers render its masked
state, never the value.
"""

import sqlite3
import threading
import time
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# The whole surface. Read-only indicators are not settings and live
# elsewhere; anything here is either a bool, a small ordered choice, or
# one of the typed endpoint strings.
TOGGLES = {
    "excel_enabled": True,
    "calendar_enabled": True,
    "endpoint_enabled": True,
    "quiet_hours": True,
    "mail_enabled": False,  # mail digest: off until the user turns it on
    "sample_data": False,  # demo seed (#68): off until the user asks for it
    # Semantic recall (ticket #95): embeddings stay inactive until the
    # embeddings probe passes on the capabilities page, so this default
    # on changes nothing until the endpoint answers the probe.
    "semantic_memory": True,
}
CHOICES = {
    "daily_cap": [3, 1, 0],  # notifications per day; 0 means inbox only
}
# The embeddings model default below is the spec's Further Notes
# default (decision: text-embedding-3-small); agentdesk.memory.embed
# holds the same constant, and a test pins the two together.
EMBEDDINGS_MODEL_DEFAULT = "text-embedding-3-small"
TEXT_KEYS = {
    "llm_base": "",  # OpenAI-compatible base URL
    "llm_key": "",   # API key; secret, rendered only in masked form
    "llm_model": "",  # empty means the adapter's default model
    "embeddings_model": EMBEDDINGS_MODEL_DEFAULT,  # the semantic recall model (#95)
    "mail_folder": "",  # the .eml folder the mail watcher polls when enabled
    "registry_path": "",  # the local registry checkout the plugins page browses; empty means auto
    "extra_allowed_hosts": "",  # host[:port] entries the guard admits beyond loopback (#61); comma or space separated
}
DEFAULTS = {**TOGGLES, "daily_cap": 3, **TEXT_KEYS}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class SettingsStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self.conn = conn
        self.clock = clock
        # One lock around every statement: the connection is shared
        # across request threads (check_same_thread=False), the guard
        # reads it on EVERY request, and without this the interleaved
        # cursor use raises InterfaceError on the hot path (the same
        # shared-connection class the calendar bridge fixed with a
        # lock; see the research store for the third instance).
        self._lock = threading.RLock()
        ensure_schema(conn)

    def get(self, key: str):
        """The stored value, or the default. Unknown keys are not settings."""
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        with self._lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return DEFAULTS[key]
        default = DEFAULTS[key]
        if isinstance(default, bool):
            return row[0] == "1"
        if key in TEXT_KEYS:
            return row[0]
        return int(row[0])

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        if isinstance(DEFAULTS[key], bool):
            stored = "1" if value else "0"
        elif key in TEXT_KEYS:
            stored = str(value)
        else:
            if value not in CHOICES[key]:
                raise ValueError(f"{key} must be one of {CHOICES[key]}")
            stored = str(value)
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, stored),
            )

    def toggle(self, key: str):
        """Flip a boolean; cycle a choice. Returns the new value."""
        current = self.get(key)
        if key in TOGGLES:
            new = not current
        else:
            options = CHOICES[key]
            new = options[(options.index(current) + 1) % len(options)]
        self.set(key, new)
        return new

    def all(self) -> dict:
        return {key: self.get(key) for key in DEFAULTS}
