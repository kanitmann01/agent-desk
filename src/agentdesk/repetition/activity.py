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
    conn.executescript(SCHEMA)
    conn.commit()


class ActivityLog:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    def record(self, kind: str, text: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO activity (ts, kind, text) VALUES (?, ?, ?)",
                (self.clock(), kind, text),
            )

    def entries(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ts, kind, text FROM (SELECT * FROM activity ORDER BY id DESC LIMIT ?)"
            " ORDER BY id ASC",
            (limit,),
        ).fetchall()
        return [{"ts": r[0], "kind": r[1], "text": r[2]} for r in rows]
