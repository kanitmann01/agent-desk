"""Settings: toggles only, with defaults that need no documentation.

Every control is a boolean or a small choice; there is no setting whose
default would do. The inbox reads its quiet-hours and budget values from
here, so what this page shows is what the app enforces.
"""

import sqlite3
import time
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# The whole surface. Read-only indicators are not settings and live
# elsewhere; anything here is either a bool or a small ordered choice.
TOGGLES = {
    "excel_enabled": True,
    "calendar_enabled": True,
    "endpoint_enabled": True,
    "quiet_hours": True,
}
CHOICES = {
    "daily_cap": [3, 1, 0],  # notifications per day; 0 means inbox only
}
DEFAULTS = {**TOGGLES, "daily_cap": 3}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class SettingsStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    def get(self, key: str):
        """The stored value, or the default. Unknown keys are not settings."""
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return DEFAULTS[key]
        default = DEFAULTS[key]
        if isinstance(default, bool):
            return row[0] == "1"
        return int(row[0])

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        if isinstance(DEFAULTS[key], bool):
            stored = "1" if value else "0"
        else:
            if value not in CHOICES[key]:
                raise ValueError(f"{key} must be one of {CHOICES[key]}")
            stored = str(value)
        with self.conn:
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
