"""The mail store: handled threads in SQLite, persistent across restarts.

The donor keeps mail state in one table keyed by thread name; the same
shape lives here, under the repo's store idioms (ensure_schema, an
injectable clock, `with conn` writes). Only the handled markers are
persisted: messages themselves are re-read from the folder on every
poll, because the folder is the source of truth and a copy would only
grow stale and misleading.
"""

import sqlite3
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS handled_threads (
  thread TEXT PRIMARY KEY,
  handled_ts REAL NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class MailStore:
    """Handled-thread markers in, the handled set out."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float]) -> None:
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    def mark_handled(self, thread: str) -> None:
        """One thread, marked handled. Marking twice keeps the first
        timestamp: when it was decided is history, not state to churn."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO handled_threads (thread, handled_ts) VALUES (?, ?)"
                " ON CONFLICT(thread) DO NOTHING",
                (thread, self.clock()),
            )

    def handled(self) -> set[str]:
        rows = self.conn.execute("SELECT thread FROM handled_threads").fetchall()
        return {row[0] for row in rows}

    def is_handled(self, thread: str) -> bool:
        return self.handled_ts(thread) is not None

    def handled_ts(self, thread: str) -> float | None:
        """When the thread was marked handled, or None."""
        row = self.conn.execute(
            "SELECT handled_ts FROM handled_threads WHERE thread = ?", (thread,)
        ).fetchone()
        return row[0] if row else None
