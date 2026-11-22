"""The activity log: what the manager asked, through the app only.

Entries come from app surfaces (research and assistant asks today); the
log never sees keystrokes or the screen. It is readable by the user on
the settings page, because a log kept about you belongs to you.
"""

import sqlite3
import time
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the activity table if missing; commits, so it is safe to call again."""
    conn.executescript(SCHEMA)
    conn.commit()


class ActivityLog:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        """Bind the log to a connection and make sure its table exists."""
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    def record(self, kind: str, text: str) -> None:
        """Append one entry stamped with the injected clock and commit it."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO activity (ts, kind, text) VALUES (?, ?, ?)",
                (self.clock(), kind, text),
            )

    def entries(self, limit: int = 200) -> list[dict]:
        """The newest `limit` entries, oldest first, each with its row id
        (spec 016: the profile review and its latch count by id)."""
        rows = self.conn.execute(
            "SELECT id, ts, kind, text FROM (SELECT * FROM activity ORDER BY id DESC LIMIT ?)"
            " ORDER BY id ASC",
            (limit,),
        ).fetchall()
        return [{"id": r[0], "ts": r[1], "kind": r[2], "text": r[3]} for r in rows]
