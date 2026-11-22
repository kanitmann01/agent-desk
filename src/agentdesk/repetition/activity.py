"""The activity log: what the manager asked, through the app only.

Entries come from app surfaces (research and assistant asks today); the
log never sees keystrokes or the screen. It is readable by the user on
the settings page, because a log kept about you belongs to you.
"""

import contextlib
import functools
import sqlite3
import threading
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


def _serialized(method):
    """Every read and write holds the store's one lock, the inbox store's
    pattern. The connection is shared (check_same_thread=False) by the
    server's request threads and the agent loop's skills step; Python's
    sqlite3 connection keeps one implicit transaction, so interleaved use
    can commit another thread's half-done write."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        """Run one store method with the store's re-entrant lock held."""
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class ActivityLog:
    """Asked-for text, thread-safe: every method serializes on one lock
    (see _serialized). Stores sharing a connection with the skills store
    (the default boot's repetition.sqlite3) share its lock too."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time,
                 lock: threading.RLock | None = None) -> None:
        """Bind the log to a connection and make sure its table exists.

        lock is injectable so stores sharing a connection can share its
        one lock.
        """
        self.conn = conn
        self.clock = clock
        self._lock = lock if lock is not None else threading.RLock()
        with self._lock:
            ensure_schema(conn)

    @contextlib.contextmanager
    def locked(self):
        """Hold the log's lock for compound statements a caller runs
        straight on the connection (the consolidator's cooldown table,
        which lives on this connection but not in this store)."""
        with self._lock:
            yield self.conn

    @_serialized
    def record(self, kind: str, text: str) -> None:
        """Append one entry stamped with the injected clock and commit it."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO activity (ts, kind, text) VALUES (?, ?, ?)",
                (self.clock(), kind, text),
            )

    @_serialized
    def entries(self, limit: int = 200) -> list[dict]:
        """The newest `limit` entries, oldest first."""
        rows = self.conn.execute(
            "SELECT ts, kind, text FROM (SELECT * FROM activity ORDER BY id DESC LIMIT ?)"
            " ORDER BY id ASC",
            (limit,),
        ).fetchall()
        return [{"ts": r[0], "kind": r[1], "text": r[2]} for r in rows]
