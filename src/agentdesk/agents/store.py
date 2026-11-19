"""The agent runs store: what each run was asked and what it produced.

Runs are rows, not files: the brief, the status and its cause, the
model's reply, the parsed artifact, and the receipt (the recalled facts
the run actually used). A degraded run is kept with its cause, because
the store holds what happened, never what would have been nice. The
feedback columns exist for the run page's later "how did it land?"
form; a fresh run carries none.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable

# The history the page renders: newest first, capped, so the surface
# stays readable without a pager.
RECENT_LIMIT = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  brief TEXT NOT NULL,
  status TEXT NOT NULL,
  cause TEXT NOT NULL DEFAULT '',
  reply TEXT NOT NULL DEFAULT '',
  artifact TEXT NOT NULL DEFAULT '',
  facts TEXT NOT NULL DEFAULT '[]',
  feedback TEXT NOT NULL DEFAULT '',
  feedback_ts REAL,
  created_ts REAL NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the runs table.

    Idempotent: the schema uses IF NOT EXISTS, so this runs on every open.
    """
    conn.executescript(SCHEMA)
    conn.commit()


class AgentRunStore:
    """Agent runs in, the same rows out, newest first."""

    def __init__(self, conn: sqlite3.Connection,
                 clock: Callable[[], float] = time.time) -> None:
        """Open the store on an existing connection and prepare its schema.

        The connection is shared by request threads, so every read and write
        is serialized through the lock; it is re-entrant because a holder
        may call another method that takes it again.
        """
        self.conn = conn
        self.clock = clock
        self._lock = threading.RLock()
        ensure_schema(conn)

    def record(self, agent_id: str, brief: str, status: str, cause: str = "",
               reply: str = "", artifact: dict | None = None,
               facts: list | None = None) -> int:
        """Insert one run and return its id.

        `artifact` and `facts` are stored as JSON; a degraded run passes
        no artifact, and the row keeps exactly that (never a fabricated
        one).
        """
        with self._lock, self.conn:
            cursor = self.conn.execute(
                "INSERT INTO agent_runs (agent_id, brief, status, cause, reply,"
                " artifact, facts, created_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(agent_id),
                    str(brief),
                    str(status),
                    str(cause),
                    str(reply),
                    json.dumps(artifact) if artifact is not None else "",
                    json.dumps(facts or []),
                    self.clock(),
                ),
            )
            return int(cursor.lastrowid)

    def recent(self, limit: int = RECENT_LIMIT) -> list[dict]:
        """The newest runs first, at most `limit` of them."""
        return self._rows(
            "SELECT id, agent_id, brief, status, cause, reply, artifact, facts,"
            " feedback, feedback_ts, created_ts FROM agent_runs"
            " ORDER BY created_ts DESC, id DESC LIMIT ?",
            (limit,),
        )

    def get(self, run_id: int) -> dict | None:
        """One run by id, or None when no row carries it."""
        rows = self._rows(
            "SELECT id, agent_id, brief, status, cause, reply, artifact, facts,"
            " feedback, feedback_ts, created_ts FROM agent_runs WHERE id = ?",
            (run_id,),
        )
        return rows[0] if rows else None

    def _rows(self, sql: str, params: tuple) -> list[dict]:
        """Run a select and shape every row the way the page reads it.

        The JSON columns come back parsed (artifact as a dict or None,
        facts as a list), so no caller re-parses stored JSON.
        """
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        shaped = []
        for row in rows:
            artifact = json.loads(row[6]) if row[6] else None
            shaped.append(
                {
                    "id": row[0],
                    "agentId": row[1],
                    "brief": row[2],
                    "status": row[3],
                    "cause": row[4],
                    "reply": row[5],
                    "artifact": artifact,
                    "facts": json.loads(row[7]),
                    "feedback": row[8],
                    "feedbackTs": row[9],
                    "createdTs": row[10],
                }
            )
        return shaped
