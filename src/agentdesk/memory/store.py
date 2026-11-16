"""The memory store: facts in SQLite, persistent across restarts.

The teammate's store keeps facts in a process list and loses everything
on restart; this one writes through to SQLite like every store in the
repo (ensure_schema, an injectable clock, `with conn` writes). Facts are
created only through add(): the memory page's form and the inbox's
accepted-card path are its only callers by policy, and nothing derives a
fact from conversation text.

Schema version 2 (ticket #89, the donor's migration): a schema_meta row
stamps the version, facts gain kind, occurrence_ts and source_id, and
the donor's sources, entities, edges and observations tables exist for
the later tickets that populate them (enforcing their constraints is
SQLite's job, not this module's). Opening a v1 database (no stamp)
upgrades it in place and runs the donor's startup dedupe exactly once;
a stamped database reopens untouched.
"""

import sqlite3
from collections.abc import Callable

from agentdesk.memory.core import Fact, UnknownFact
from agentdesk.memory.service import rank

SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  created_ts REAL NOT NULL,
  kind TEXT NOT NULL DEFAULT 'world' CHECK (kind IN ('world','experience')),
  occurrence_ts REAL,
  source_id INTEGER REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  speaker TEXT NOT NULL DEFAULT '',
  context TEXT NOT NULL DEFAULT '',
  created_ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  type TEXT NOT NULL CHECK (type IN ('person','org','place','product','concept','other')),
  created_ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY,
  fact_id INTEGER NOT NULL REFERENCES facts(id),
  entity_id INTEGER NOT NULL REFERENCES entities(id),
  UNIQUE (fact_id, entity_id)
);

CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY,
  scope_key TEXT NOT NULL,
  text TEXT NOT NULL,
  confidence REAL NOT NULL,
  created_ts REAL NOT NULL,
  updated_ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS observation_sources (
  observation_id INTEGER NOT NULL REFERENCES observations(id),
  fact_id INTEGER NOT NULL REFERENCES facts(id),
  PRIMARY KEY (observation_id, fact_id)
);
"""

_COLUMNS = "id, text, source, created_ts, kind, occurrence_ts, source_id"

_KINDS = ("world", "experience")

# What a v1 facts table lacks. The fresh-install DDL above already has
# all three; these ALTERs are for opening an old file. SQLite accepts a
# CHECK on an added column when the column has a DEFAULT (kind does), so
# the migrated table enforces the vocabulary exactly like a fresh one;
# source_id's default is NULL, which is what an added REFERENCES column
# requires while foreign keys are on.
_FACT_UPGRADE_COLUMNS = (
    (
        "kind",
        "ALTER TABLE facts ADD COLUMN kind TEXT NOT NULL DEFAULT 'world'"
        " CHECK (kind IN ('world','experience'))",
    ),
    ("occurrence_ts", "ALTER TABLE facts ADD COLUMN occurrence_ts REAL"),
    ("source_id", "ALTER TABLE facts ADD COLUMN source_id INTEGER REFERENCES sources(id)"),
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create or migrate the schema in place, safe on every open.

    `PRAGMA foreign_keys = ON` mirrors the donor's connection setup: a
    cheap per-connection switch, idempotent to repeat. The stamp decides
    the work: no `version` row means a v1 database (or a brand-new file,
    where the dedupe finds no rows to merge), and the stamp is written
    only after the upgrade, so every step below re-runs harmlessly if a
    crash lands between them.
    """
    conn.execute("PRAGMA foreign_keys = ON")
    version = _stored_version(conn)
    conn.executescript(SCHEMA)
    _add_missing_fact_columns(conn)
    if version != SCHEMA_VERSION:
        # The donor's startup dedupe, exactly once per upgrade. On a
        # stamped reopen it must not run again: a duplicate re-added
        # after migration is real data until write-time dedupe lands.
        _dedupe_identical_facts(conn)
        with conn:
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('version', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION,),
            )
    conn.commit()


def _stored_version(conn: sqlite3.Connection) -> str | None:
    """The stamped version, or None when nothing has stamped yet (a
    pre-#89 file has no schema_meta table at all)."""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else str(row[0])


def _add_missing_fact_columns(conn: sqlite3.Connection) -> None:
    """Add the v2 fact columns an upgraded table lacks; on a fresh or
    already-migrated database this is only a table_info scan."""
    present = {row[1] for row in conn.execute("PRAGMA table_info(facts)")}
    for name, ddl in _FACT_UPGRADE_COLUMNS:
        if name not in present:
            conn.execute(ddl)


def _normalize_fact_text(text: str) -> str:
    """The donor's normalizeFactText: trim, collapse internal whitespace
    runs to single spaces, lowercase. Punctuation stays, so this is an
    exact-text match, not a semantic comparison."""
    return " ".join(text.split()).lower()


def _dedupe_identical_facts(conn: sqlite3.Connection) -> None:
    """Merge pre-existing facts whose normalized texts are identical.

    The keeper is the oldest row (lowest created_ts, lowest id on a
    tie); the copies are deleted. A v1 database has no edges and no
    occurrence or embedding backfill to move onto the keeper (edges
    arrive with v2 and no v1 fact ever gained the rest), so a plain
    DELETE is the whole merge, unlike the donor's mention-moving dance.
    Groups whose normalized text is empty are skipped: blank rows are
    not duplicates of each other.
    """
    rows = conn.execute("SELECT id, text, created_ts FROM facts").fetchall()
    groups: dict[str, list[tuple[float, int]]] = {}
    for fact_id, text, created_ts in rows:
        key = _normalize_fact_text(text)
        if not key:
            continue
        groups.setdefault(key, []).append((created_ts, fact_id))
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort()
        for _created_ts, extra_id in members[1:]:
            conn.execute("DELETE FROM facts WHERE id = ?", (extra_id,))


class MemoryStore:
    """Facts in, recall out; the ranking lives in the pure service."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float]) -> None:
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    # -- writes -----------------------------------------------------------

    def add(
        self,
        text: str,
        source: str = "",
        kind: str = "world",
        occurrence_ts: float | None = None,
        source_id: int | None = None,
    ) -> Fact:
        """Insert one fact. The kind vocabulary and the numeric
        occurrence are checked here so the caller hears ValueError
        before the database would refuse the row."""
        if kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, not {kind!r}")
        if occurrence_ts is not None and not isinstance(occurrence_ts, (int, float)):
            raise ValueError("occurrence_ts must be a number or None")
        text = text.strip()
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO facts (text, source, created_ts, kind, occurrence_ts,"
                " source_id) VALUES (?, ?, ?, ?, ?, ?)",
                (text, source, self.clock(), kind, occurrence_ts, source_id),
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
        return Fact(
            id=row[0],
            text=row[1],
            source=row[2],
            created_ts=row[3],
            kind=row[4],
            occurrence_ts=row[5],
            source_id=row[6],
        )

    def all(self) -> list[Fact]:
        """Every fact in creation order (the recall tie-break order)."""
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM facts ORDER BY created_ts ASC, id ASC"
        ).fetchall()
        return [
            Fact(
                id=r[0],
                text=r[1],
                source=r[2],
                created_ts=r[3],
                kind=r[4],
                occurrence_ts=r[5],
                source_id=r[6],
            )
            for r in rows
        ]

    def recall(self, query: str) -> list[tuple[float, Fact]]:
        """The ranked recall: deterministic, best first (memory/service)."""
        return rank(query, self.all())
