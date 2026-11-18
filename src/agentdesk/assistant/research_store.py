"""The research answer store: the latest sourced summary, kept locally.

The research panel's answers live in the page until it closes, and the
audit row records only that a call happened (never text, by policy).
This store keeps the latest sourced answer itself, the summary and its
source names, so surfaces like a plugin's research card can show what
research last concluded without any new endpoint call. One row: a new
answer replaces the one before it, because the store is the latest
conclusion, not a history.
"""

import json
import sqlite3
import threading
import time
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_answer (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  ts REAL NOT NULL,
  summary TEXT NOT NULL,
  sources TEXT NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the research store's tables.

    Idempotent: the schema uses IF NOT EXISTS, so this runs on every open.
    """
    conn.executescript(SCHEMA)
    conn.commit()


class ResearchStore:
    """The latest research answer in, the same answer out."""

    def __init__(self, conn: sqlite3.Connection,
                 clock: Callable[[], float] = time.time) -> None:
        """Open the store on an existing connection and prepare its schema.

        The connection is shared by request threads, so every read and write is
        serialized through the lock; it is re-entrant because a holder may call
        another method that takes it again.
        """
        self.conn = conn
        self.clock = clock
        # One connection serves request threads (a POST /research save
        # while a dashboard render reads), so every use is serialized:
        # interleaved sqlite calls on one connection raise or tear. The
        # calendar bridge's pattern; an RLock because save and latest
        # may nest under a future holder.
        self._lock = threading.RLock()
        ensure_schema(conn)

    def save(self, summary: str, sources: list) -> None:
        """Record the newest answer; it replaces any earlier one."""
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO research_answer (id, ts, summary, sources)"
                " VALUES (1, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET ts = excluded.ts,"
                " summary = excluded.summary, sources = excluded.sources",
                (self.clock(), str(summary),
                 json.dumps([str(s) for s in sources])),
            )

    def latest(self) -> dict | None:
        """The latest answer as ``{summary, sources, answeredTs}``, or
        None when nothing was ever asked."""
        with self._lock:
            row = self.conn.execute(
                "SELECT ts, summary, sources FROM research_answer WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return {
            "summary": row[1],
            "sources": json.loads(row[2]),
            "answeredTs": row[0],
        }
