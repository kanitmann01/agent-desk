"""The memory store: facts in SQLite, persistent across restarts.

The teammate's store keeps facts in a process list and loses everything
on restart; this one writes through to SQLite like every store in the
repo (ensure_schema, an injectable clock, `with conn` writes). Facts are
created only through add(): the memory page's form and the inbox's
accepted-card path are its only callers by policy, and nothing derives a
fact from conversation text.
"""

import sqlite3
from collections.abc import Callable

from agentdesk.memory.core import Fact, UnknownFact
from agentdesk.memory.service import rank

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  created_ts REAL NOT NULL
);
"""

_COLUMNS = "id, text, source, created_ts"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class MemoryStore:
    """Facts in, recall out; the ranking lives in the pure service."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float]) -> None:
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    # -- writes -----------------------------------------------------------

    def add(self, text: str, source: str = "") -> Fact:
        text = text.strip()
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO facts (text, source, created_ts) VALUES (?, ?, ?)",
                (text, source, self.clock()),
            )
        return self.get(int(cursor.lastrowid))

    def edit(self, fact_id: int, text: str) -> Fact:
        """Replace the text; source and created_ts stay (provenance and
        the recall tie-break are not the editor's to change)."""
        self.get(fact_id)
        with self.conn:
            self.conn.execute(
                "UPDATE facts SET text = ? WHERE id = ?", (text.strip(), fact_id)
            )
        return self.get(fact_id)

    def delete(self, fact_id: int) -> None:
        self.get(fact_id)
        with self.conn:
            self.conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))

    # -- reads ------------------------------------------------------------

    def get(self, fact_id: int) -> Fact:
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM facts WHERE id = ?", (fact_id,)
        ).fetchone()
        if row is None:
            raise UnknownFact(f"no fact {fact_id}")
        return Fact(id=row[0], text=row[1], source=row[2], created_ts=row[3])

    def all(self) -> list[Fact]:
        """Every fact in creation order (the recall tie-break order)."""
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM facts ORDER BY created_ts ASC, id ASC"
        ).fetchall()
        return [Fact(id=r[0], text=r[1], source=r[2], created_ts=r[3]) for r in rows]

    def recall(self, query: str) -> list[tuple[float, Fact]]:
        """The ranked recall: deterministic, best first (memory/service)."""
        return rank(query, self.all())
