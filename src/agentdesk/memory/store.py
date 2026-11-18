"""The memory store: facts in SQLite, persistent across restarts.

The teammate's store keeps facts in a process list and loses everything
on restart; this one writes through to SQLite like every store in the
repo (ensure_schema, an injectable clock, `with conn` writes). Facts are
created only through add(): the memory page's form and the inbox's
accepted-card path are its only callers by policy, and nothing derives a
fact from conversation text.

Schema version 2 (ticket #89, the donor's migration): a schema_meta row
stamps the version, facts gain kind, occurrence_ts and source_id, and
the donor's sources, entities, edges and observations tables exist.
Retain (ticket #91) populates sources, entities and edges: add_source()
records a retained excerpt, resolve_and_link() runs the donor's entity
resolution (memory/resolve.py) for one accepted fact and writes its
mention edges in one transaction (enforcing the tables' constraints is
SQLite's job, not this module's). Opening a v1 database (no stamp)
upgrades it in place and runs the donor's startup dedupe exactly once;
a stamped database reopens untouched. Recall ranks through the hybrid
ranker (memory/hybrid.py, ticket #90): facts, entities and edges load
here, the arithmetic stays in the pure module.

Encryption at rest (ticket #94, the donor's design on the cryptography
package): MemoryStore takes an optional 32-byte key and, with one, an
optional key_path (the memory.key file's location, needed by the
encryption action). Open-time binding replicates the donor's: a marker
row in schema_meta under the key "encryption" plus no key locks the
store with a plain-language cause; a wrong key locks with "Wrong
encryption key."; a key offered to a populated plaintext bank refuses;
a key on an empty fresh database initializes as sealed and writes the
marker immediately. Sealed writes blank the plaintext columns and store
ciphertext plus blind indexes (facts text, sources text/speaker/
context, entities canonical name and aliases, observations text and a
blinded scope key); sealed reads REQUIRE ciphertext, so a row without
one is a hard error (MemoryEncryptedError), never a silent plaintext
fallback. Plaintext columns of the graph itself (ids, kinds, edges,
timestamps, confidence, types) stay plaintext, like the donor.
encrypt_all() is the one-action conversion: dedupe and prune first,
then seal everything and write the marker in one transaction, with the
key file created before the transaction starts, then checkpoint and
vacuum. Duplicate detection on an encrypted bank compares the text_idx
blind index, never plaintext (the exact-name entity guard narrows
through entity_name_index the same way); the conversion's own dedupe
runs while the bank is still plaintext, like the donor's, and write-
time dedupe gates every write (ticket #92): add() reuses the row a
normalized duplicate matches, riding the text_idx blind index on a
sealed bank with a decrypt-verify second.
"""

import functools
import json
import math
import os
import secrets
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agentdesk.memory.core import (
    EditResult,
    EntitySummary,
    Fact,
    Observation,
    RemovedFacts,
    SavedObservation,
    SourceExcerpt,
    SweepCandidate,
    UnknownEntity,
    UnknownFact,
    normalize_fact_text,
)
from agentdesk.memory.crypto import (
    KEY_FILE_NAME,
    CryptoBox,
    MemoryEncryptedError,
    check_marker,
    load_key,
    make_marker,
)
from agentdesk.memory.embed import (
    EmbedderUnavailable,
    decode_embedding,
    encode_embedding,
    rank,
)
from agentdesk.memory.extract import ENTITY_TYPES
from agentdesk.memory.graph import (
    DEFAULT_GRAPH_LIMIT,
    DEFAULT_MIN_SIMILARITY,
    GraphFact,
    GraphObservation,
    build_graph,
)
from agentdesk.memory.hybrid import EntityLink, normalize_name, rank_hybrid
from agentdesk.memory.knowledge_gap import junk_reason
from agentdesk.memory.resolve import (
    EntityRepo,
    EntityRef,
    Mention,
    StoredEntity,
    dedupe_aliases,
    display_name,
    resolve_mentions,
)

SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  created_ts REAL NOT NULL,
  kind TEXT NOT NULL DEFAULT 'world' CHECK (kind IN ('world','experience')),
  occurrence_ts REAL,
  source_id INTEGER REFERENCES sources(id),
  embedding BLOB,
  embedding_model TEXT,
  embedding_dim INTEGER
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

CREATE TABLE IF NOT EXISTS entity_name_index (
  entity_id INTEGER NOT NULL REFERENCES entities(id),
  name_idx TEXT NOT NULL,
  UNIQUE (entity_id, name_idx)
);
"""

_COLUMNS = "id, text, source, created_ts, kind, occurrence_ts, source_id"

_KINDS = ("world", "experience")

# What a v1 facts table lacks. The fresh-install DDL above already has
# all of these; these ALTERs are for opening an old file. SQLite accepts
# a CHECK on an added column when the column has a DEFAULT (kind does),
# so the migrated table enforces the vocabulary exactly like a fresh
# one; source_id's default is NULL, which is what an added REFERENCES
# column requires while foreign keys are on. The embedding trio (ticket
# #95, the donor's migration) rides the same idempotent scan.
_FACT_UPGRADE_COLUMNS = (
    (
        "kind",
        "ALTER TABLE facts ADD COLUMN kind TEXT NOT NULL DEFAULT 'world'"
        " CHECK (kind IN ('world','experience'))",
    ),
    ("occurrence_ts", "ALTER TABLE facts ADD COLUMN occurrence_ts REAL"),
    ("source_id", "ALTER TABLE facts ADD COLUMN source_id INTEGER REFERENCES sources(id)"),
    ("embedding", "ALTER TABLE facts ADD COLUMN embedding BLOB"),
    ("embedding_model", "ALTER TABLE facts ADD COLUMN embedding_model TEXT"),
    ("embedding_dim", "ALTER TABLE facts ADD COLUMN embedding_dim INTEGER"),
)

# What encryption adds to each table (ticket #94): a ciphertext column
# and a blind index per sealed text, null until the conversion fills
# them. Added idempotently on every open, so both a pre-#94 and a fresh
# database carry them.
_ENCRYPTION_COLUMNS = {
    "facts": (
        ("text_enc", "ALTER TABLE facts ADD COLUMN text_enc BLOB"),
        ("text_idx", "ALTER TABLE facts ADD COLUMN text_idx TEXT"),
    ),
    "sources": (
        ("text_enc", "ALTER TABLE sources ADD COLUMN text_enc BLOB"),
        ("speaker_enc", "ALTER TABLE sources ADD COLUMN speaker_enc BLOB"),
        ("context_enc", "ALTER TABLE sources ADD COLUMN context_enc BLOB"),
    ),
    "entities": (
        ("canonical_name_enc", "ALTER TABLE entities ADD COLUMN canonical_name_enc BLOB"),
        ("aliases_enc", "ALTER TABLE entities ADD COLUMN aliases_enc BLOB"),
        ("name_idx", "ALTER TABLE entities ADD COLUMN name_idx TEXT"),
    ),
    "observations": (
        ("text_enc", "ALTER TABLE observations ADD COLUMN text_enc BLOB"),
        ("text_idx", "ALTER TABLE observations ADD COLUMN text_idx TEXT"),
    ),
}


# What the memory loop adds (auto-capture and removal): a fact a newer
# one replaced points at its replacement, and an observation that lost
# a cited fact carries the moment it went stale. Both null by default
# and added idempotently on every open, like the encryption columns.
_LOOP_COLUMNS = {
    "facts": (
        ("superseded_by", "ALTER TABLE facts ADD COLUMN superseded_by INTEGER"),
    ),
    "observations": (
        ("stale_ts", "ALTER TABLE observations ADD COLUMN stale_ts REAL"),
        # Who wrote a consolidated observation ("model" or "rules") and the
        # standing facts it was built from (comma-separated ids): the loop
        # rebuilds it only when that basis changes, or to let the model
        # rewrite what the rules wrote. Ids and a method name, never text.
        ("method", "ALTER TABLE observations ADD COLUMN method TEXT"),
        ("basis", "ALTER TABLE observations ADD COLUMN basis TEXT"),
    ),
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create or migrate the schema in place, safe on every open.

    `PRAGMA foreign_keys = ON` mirrors the donor's connection setup: a
    cheap per-connection switch, idempotent to repeat. The stamp decides
    the work: no `version` row means a v1 database (or a brand-new file,
    where the dedupe finds no rows to merge), and the stamp is written
    only after the upgrade, so every step below re-runs harmlessly if a
    crash lands between them. The encryption columns ride along on every
    open (null on an unconverted bank).
    """
    conn.execute("PRAGMA foreign_keys = ON")
    version = _stored_version(conn)
    conn.executescript(SCHEMA)
    _add_missing_fact_columns(conn)
    _add_missing_encryption_columns(conn)
    _add_missing_loop_columns(conn)
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


def _add_missing_encryption_columns(conn: sqlite3.Connection) -> None:
    """Add the encryption columns any table lacks (ticket #94); null on
    an unconverted bank."""
    for table, columns in _ENCRYPTION_COLUMNS.items():
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in present:
                conn.execute(ddl)


def _add_missing_loop_columns(conn: sqlite3.Connection) -> None:
    """Add the memory loop's columns (superseded_by, stale_ts) any table
    lacks; null on a bank written before the loop existed."""
    for table, columns in _LOOP_COLUMNS.items():
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in present:
                conn.execute(ddl)


def _parse_aliases(value: str) -> tuple[str, ...]:
    """The donor's parseAliases: a JSON array of strings, and anything
    else (corrupt, wrong shape, non-string entries) reads as none."""
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(alias for alias in parsed if isinstance(alias, str))


def _dedupe_identical_facts(conn: sqlite3.Connection) -> None:
    """Merge pre-existing facts whose normalized texts are identical.

    The keeper is the oldest row (lowest created_ts, lowest id on a
    tie); the copies are deleted. A v1 database has no edges or
    citations to move, but a v2 bank can still hold duplicates that
    predate ticket #92's write-time dedup (an older build or a foreign
    writer), so each copy's mention edges and observation citations
    move onto the keeper first (the donor's moveMentions, the same
    dance edit() merges with): the foreign keys would otherwise refuse
    the delete. Groups whose normalized text is empty are skipped:
    blank rows are not duplicates of each other. Only ever runs on a
    plaintext bank: the migration and the conversion both happen before
    any sealing.
    """
    rows = conn.execute("SELECT id, text, created_ts FROM facts").fetchall()
    groups: dict[str, list[tuple[float, int]]] = {}
    for fact_id, text, created_ts in rows:
        key = normalize_fact_text(text)
        if not key:
            continue
        groups.setdefault(key, []).append((created_ts, fact_id))
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort()
        keeper_id = members[0][1]
        for _created_ts, extra_id in members[1:]:
            conn.execute(
                "INSERT OR IGNORE INTO edges (fact_id, entity_id) "
                "SELECT ?, entity_id FROM edges WHERE fact_id = ?",
                (keeper_id, extra_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO observation_sources "
                "(observation_id, fact_id) "
                "SELECT observation_id, ? FROM observation_sources "
                "WHERE fact_id = ?",
                (keeper_id, extra_id),
            )
            conn.execute("DELETE FROM facts WHERE id = ?", (extra_id,))


def _prune_orphan_statements(conn: sqlite3.Connection) -> list[int]:
    """The donor's pruneOrphanObservations body: delete the citations
    whose fact is gone, then the observations left with zero citations,
    and return the removed observation ids. Runs no transaction of its
    own so the caller's write stays atomic (spec decision 24: orphan
    citations and uncited observations are pruned whenever facts are
    deleted)."""
    conn.execute(
        "DELETE FROM observation_sources WHERE fact_id NOT IN"
        " (SELECT id FROM facts)"
    )
    doomed = conn.execute(
        "SELECT id FROM observations WHERE id NOT IN"
        " (SELECT observation_id FROM observation_sources)"
    ).fetchall()
    for (observation_id,) in doomed:
        conn.execute("DELETE FROM observations WHERE id = ?", (observation_id,))
    return [int(row[0]) for row in doomed]


def _prune_orphan_observations(conn: sqlite3.Connection) -> None:
    """The standalone prune (the conversion's pre-step): the statements
    above in their own transaction. Runs before the conversion so
    nothing sealed is orphaned by it afterwards."""
    with conn:
        _prune_orphan_statements(conn)


def _read_marker(conn: sqlite3.Connection) -> str | None:
    """The encryption marker row, or None (an unconverted bank)."""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'encryption'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or row[0] is None:
        return None
    marker = str(row[0])
    return marker or None


def _database_has_rows(conn: sqlite3.Connection) -> bool:
    """The donor's databaseHasRows: any fact, entity, source or
    observation makes the bank populated."""
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM facts) + (SELECT COUNT(*) FROM entities)"
        " + (SELECT COUNT(*) FROM sources) + (SELECT COUNT(*) FROM observations)"
    ).fetchone()
    return bool(row and row[0])


def _plain_field_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """The donor's countPlainFields, per table: the values that would
    become ciphertext. A text counts when it holds a non-empty value;
    every row's primary text counts regardless."""
    counts = {"facts": 0, "sources": 0, "entities": 0, "observations": 0}
    counts["facts"] = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    # Ticket #95: a stored embedding vector is a field the conversion
    # seals too (the donor's countPlainFields counts it the same way).
    counts["facts"] += conn.execute(
        "SELECT COUNT(*) FROM facts WHERE embedding IS NOT NULL"
    ).fetchone()[0]
    for text, speaker, context in conn.execute(
        "SELECT text, speaker, context FROM sources"
    ):
        counts["sources"] += 1
        if speaker:
            counts["sources"] += 1
        if context:
            counts["sources"] += 1
    for canonical_name, aliases_json in conn.execute(
        "SELECT canonical_name, aliases_json FROM entities"
    ):
        counts["entities"] += 1
        if _parse_aliases(aliases_json):
            counts["entities"] += 1
    counts["observations"] = conn.execute(
        "SELECT COUNT(*) FROM observations"
    ).fetchone()[0]
    return counts


# -- the key file -------------------------------------------------------------


def key_file_path(data_dir) -> Path:
    """The key lives beside the other app data: data_dir / memory.key."""
    return Path(data_dir) / KEY_FILE_NAME


def write_key_file(path) -> bytes:
    """Create the key file with fresh random bytes, refusing to overwrite.

    os.open with mode 0o600: honored as user-only on POSIX; on Windows
    the C runtime maps only the write bit of the mode and the file
    inherits the profile's ACLs, which is the best the platform does
    without extra calls (recorded divergence, ticket #94).
    """
    key = secrets.token_bytes(32)
    # O_BINARY: on Windows a text-mode descriptor would translate any
    # 0x0A byte in the key to 0x0D 0x0A and corrupt it. O_NOINHERIT
    # keeps child processes from holding the descriptor.
    flags = (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    )
    fd = os.open(str(path), flags, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


def ensure_key_file(path) -> bytes:
    """The key file's bytes, creating it if it does not exist yet.

    The encryption action calls this before its transaction, so a crash
    mid-conversion can never leave an encrypted database without a key.
    """
    path = Path(path)
    if path.exists():
        return load_key(path.read_bytes())
    return write_key_file(path)


def read_key_file(path) -> bytes:
    """Read and validate the key file; ValueError when it is not 32 bytes."""
    return load_key(Path(path).read_bytes())


def _locked(method):
    """One lock around every write, the settings.py rule: the store's
    connection is shared across the server's request threads with
    check_same_thread=False, so mutating methods serialize on one RLock.
    Without it two threads can interleave commits on the connection's
    single transaction and half-apply each other's writes (a double-
    clicked Encrypt button is the worst case: both conversions would run
    over the same rows and the second blanking pass can seal an emptied
    plaintext over the only ciphertext). Reads stay unlocked: SQLite
    serializes them safely against one writer."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        """Run the method with the store's write lock held.

        An RLock because a locked method may call another one; reads skip it,
        since SQLite serializes them against a single writer.
        """
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class StoredVector:
    """One fact text's embedding, ready to store (the donor's
    StoredVector): the model that produced it, its dimension, and the
    little-endian float32 blob encode_embedding packed."""

    model: str
    dim: int
    bytes: bytes


class MemoryStore:
    """Facts in, recall out; the ranking lives in the pure service.

    With `key` the store binds at open (see the module docstring): a
    sealed store encrypts every text-bearing write and refuses any read
    that lacks ciphertext; a locked store (a marker without a usable
    key, a wrong key, a key on a populated plaintext bank) keeps its
    plain-language cause in locked_cause and refuses every operation
    with that cause, surfacing it on the memory page instead of silently
    reading or writing plaintext.

    With `embedder` and `embeddings_active` (ticket #95) the store's
    semantic half switches on: writes embed the fact text, recall adds
    the vector leg, and backfill embeds the rows that miss a vector.
    The flag is the gate (the server derives it from the semantic_memory
    toggle and the embeddings probe's cached result); both are plain
    attributes, so a caller can re-derive them per action. Every
    embedding failure degrades to the donor's vectorFor: the fact
    stores without a vector, recall keeps its deterministic legs.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], float],
        key: bytes | None = None,
        key_path=None,
        embedder=None,
        embeddings_active: bool = False,
    ) -> None:
        """Open the store: ensure the schema, then bind the key.

        With no marker and no key the bank stays plaintext. A marker plus a
        usable key seals it; a marker without a key, a key the marker rejects, or
        a key offered to a populated plaintext bank leaves the store locked with
        locked_cause set rather than raising here, and every later operation
        raises that cause through _guard. A key that is not 32 bytes raises
        ValueError before any binding happens.
        """
        self.conn = conn
        self.clock = clock
        # One lock around every write (see _locked): the connection is
        # shared across request threads.
        self._lock = threading.RLock()
        self.key_path = Path(key_path) if key_path is not None else None
        self.locked_cause: str | None = None
        self._box: CryptoBox | None = None
        # The semantic seam (ticket #95): an embedder object with a
        # `model` name and an `embed(text)` callable (memory/embed's
        # contract), plus the probe-and-toggle gate. None/inactive is
        # the deterministic-only store every earlier ticket shipped.
        self.embedder = embedder
        self.embeddings_active = bool(embeddings_active)
        ensure_schema(conn)
        if key is not None:
            key = load_key(key)
        marker = _read_marker(conn)
        if marker is not None:
            if key is None:
                where = (
                    f"the key file is missing: {self.key_path}"
                    if self.key_path is not None else "no key was provided"
                )
                self.locked_cause = (
                    f"The memory database is encrypted; {where}."
                )
                return
            try:
                check_marker(marker, key)
            except MemoryEncryptedError as exc:
                self.locked_cause = str(exc) or "Wrong encryption key."
                return
            self._box = CryptoBox(key)
            return
        if key is None:
            return
        if _database_has_rows(conn):
            self.locked_cause = (
                "The memory database is not encrypted. Run the encryption"
                " action first (the memory page) before opening it with a key."
            )
            return
        self._box = CryptoBox(key)
        self._write_marker(key)
        conn.commit()

    @property
    def is_sealed(self) -> bool:
        """True when the store encrypts writes and requires ciphertext
        on reads; False plaintext or locked."""
        return self._box is not None

    def _guard(self) -> None:
        """Every operation starts here: a locked store refuses with its
        cause, never silently reading or writing plaintext."""
        if self.locked_cause is not None:
            raise MemoryEncryptedError(self.locked_cause)

    # -- writes -----------------------------------------------------------

    @_locked
    def add(
        self,
        text: str,
        source: str = "",
        kind: str = "world",
        occurrence_ts: float | None = None,
        source_id: int | None = None,
    ) -> Fact:
        """Insert one fact, unless a normalized duplicate already exists
        (ticket #92, the donor's saveFact): then no row is inserted, the
        incoming occurrence backfills the survivor's only if that is
        null, and the surviving Fact is returned, so a caller that
        resolves mentions afterwards links them onto the existing row
        with INSERT OR IGNORE edges. The kind vocabulary and the numeric
        occurrence are checked here so the caller hears ValueError
        before the database would refuse the row. Sealed: the plaintext
        column is blanked and the ciphertext plus blind index land in
        the same transaction, bound to the row id the insert returns.
        Embeddings (ticket #95, the donor's saveFact vector): when the
        semantic half is active the text embeds before the write and the
        vector lands on the row it ends up on, backfilling the
        survivor's NULL only; ANY embed failure stores the fact without
        a vector (the donor's vectorFor) and recall keeps the
        deterministic legs."""
        self._guard()
        if kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, not {kind!r}")
        if occurrence_ts is not None and not isinstance(occurrence_ts, (int, float)):
            raise ValueError("occurrence_ts must be a number or None")
        text = text.strip()
        # The donor embeds before opening its write transaction.
        vector = self._vector_for(text)
        with self.conn:
            existing_id = self._find_identical_fact(text)
            if existing_id is not None:
                # Ticket #92, the donor's write-path reuse: the row is
                # reused and the new occurrence fills only a null; the
                # donor's saveFact likewise backfills its vector into a
                # NULL only, never overwriting a stored one.
                self._backfill_occurrence(existing_id, occurrence_ts)
                self._backfill_fact_vector(existing_id, vector)
                fact_id = existing_id
            else:
                cursor = self.conn.execute(
                    "INSERT INTO facts (text, source, created_ts, kind, occurrence_ts,"
                    " source_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (self._plain(text), source, self.clock(), kind, occurrence_ts, source_id),
                )
                fact_id = int(cursor.lastrowid)
                self._seal_fact_text(fact_id, text)
                self._store_fact_vector(fact_id, vector)
        return self.get(fact_id)

    def _find_identical_fact(
        self, text: str, exclude_id: int | None = None
    ) -> int | None:
        """The donor's findIdenticalFact: the oldest fact (created_ts,
        then id) whose normalized text equals this one, its id or None.
        An empty normalized text matches nothing, so blank rows are not
        duplicates of each other. Plaintext banks scan like the reads
        do; sealed banks take the text_idx blind lookup first and
        decrypt-verify each candidate's normalized text second (the
        seam ticket #94 maintains), so no plaintext is compared."""
        target = normalize_fact_text(text)
        if not target:
            return None
        if self._box is not None:
            rows = self.conn.execute(
                "SELECT id, text_enc FROM facts WHERE text_idx = ?"
                " ORDER BY created_ts ASC, id ASC",
                (self._box.blind(target),),
            ).fetchall()
            for fact_id, text_enc in rows:
                if exclude_id is not None and fact_id == exclude_id:
                    continue
                if text_enc is None:
                    raise MemoryEncryptedError("Missing ciphertext for facts.text.")
                stored = self._box.open(text_enc, "facts", "text", fact_id)
                if normalize_fact_text(stored) == target:
                    return int(fact_id)
            return None
        rows = self.conn.execute(
            "SELECT id, text FROM facts ORDER BY created_ts ASC, id ASC"
        ).fetchall()
        for fact_id, stored in rows:
            if exclude_id is not None and fact_id == exclude_id:
                continue
            if normalize_fact_text(stored) == target:
                return int(fact_id)
        return None

    def _backfill_occurrence(self, fact_id: int, occurrence_ts: float | None) -> None:
        """The donor's fillOccurrenceTime: an incoming occurrence fills
        a null and never overwrites a value already on the row."""
        if occurrence_ts is None:
            return
        self.conn.execute(
            "UPDATE facts SET occurrence_ts = ?"
            " WHERE id = ? AND occurrence_ts IS NULL",
            (occurrence_ts, fact_id),
        )

    # -- the semantic half (ticket #95) -----------------------------------

    def _embeddings_on(self) -> bool:
        """The semantic half's gate: an embedder injected and the
        caller's probe-and-toggle flag set."""
        return self.embeddings_active and self.embedder is not None

    def _prepare_vector(self, raw) -> StoredVector:
        """One embedder answer into a StoredVector (the donor's
        prepareText): an empty or unusable answer raises
        EmbedderUnavailable so the callers can degrade on one class."""
        try:
            blob = encode_embedding(raw)
        except ValueError as exc:
            raise EmbedderUnavailable(
                "the embedder returned an empty or unusable vector"
            ) from exc
        dim = len(raw)
        if decode_embedding(blob, dim) is None:
            raise EmbedderUnavailable(
                "the embedder returned an empty or unusable vector"
            )
        return StoredVector(model=self.embedder.model, dim=dim, bytes=blob)

    def _vector_for(self, text: str) -> StoredVector | None:
        """The donor's vectorFor: null when the semantic half is off or
        the embedder cannot answer, whatever the cause. The fact is
        still stored; recall keeps the deterministic legs."""
        if not self._embeddings_on():
            return None
        try:
            raw = self.embedder.embed(text)
            return self._prepare_vector(raw)
        except Exception:  # noqa: BLE001 - the donor catches everything here
            return None

    def _vector_blob(self, vector: StoredVector, fact_id: int) -> bytes:
        """The bytes to store: the raw blob on a plaintext bank, the
        byte envelope bound to facts|embedding|row id on a sealed one
        (the donor's sealBytes)."""
        if self._box is None:
            return vector.bytes
        return self._box.seal_bytes(vector.bytes, "facts", "embedding", fact_id)

    def _store_fact_vector(self, fact_id: int, vector: StoredVector | None) -> None:
        """Land a new row's vector (a fresh row has NULLs to fill)."""
        if vector is None:
            return
        self.conn.execute(
            "UPDATE facts SET embedding = ?, embedding_model = ?,"
            " embedding_dim = ? WHERE id = ?",
            (self._vector_blob(vector, fact_id), vector.model, vector.dim, fact_id),
        )

    def _backfill_fact_vector(self, fact_id: int, vector: StoredVector | None) -> int:
        """The donor's saveFact duplicate branch: fill a NULL only, never
        overwrite a stored vector. Returns how many rows changed."""
        if vector is None:
            return 0
        cursor = self.conn.execute(
            "UPDATE facts SET embedding = ?, embedding_model = ?,"
            " embedding_dim = ? WHERE id = ? AND embedding IS NULL",
            (self._vector_blob(vector, fact_id), vector.model, vector.dim, fact_id),
        )
        return int(cursor.rowcount or 0)

    def _refresh_fact_vector(self, fact_id: int, vector: StoredVector | None) -> None:
        """The donor's updateFact non-merge write: the new text's vector
        lands on the row, or the vector columns go NULL when the embed
        failed (a stale vector under changed text is worse than none).
        Only called while the semantic half is active."""
        blob = None
        model = None
        dim = None
        if vector is not None:
            blob = self._vector_blob(vector, fact_id)
            model = vector.model
            dim = vector.dim
        self.conn.execute(
            "UPDATE facts SET embedding = ?, embedding_model = ?,"
            " embedding_dim = ? WHERE id = ?",
            (blob, model, dim, fact_id),
        )

    def _open_fact_embedding(self, fact_id: int, blob):
        """The stored blob back as raw bytes: unchanged on a plaintext
        bank, opened from the byte envelope on a sealed one."""
        if self._box is None:
            return blob
        if blob is None:
            raise MemoryEncryptedError("Missing ciphertext for facts.embedding.")
        return self._box.open_bytes(blob, "facts", "embedding", fact_id)

    def _vector_scores(self, query: str) -> dict[int, float]:
        """The semantic leg's scores (the donor's vectorScores): the
        query embeds once, then every row whose model and dimension
        match the query's compares by cosine, positives kept. Any
        embedder failure means no leg, never an error; rows under
        another model or dimension never compare."""
        if not self._embeddings_on() or not query.strip():
            return {}
        try:
            raw = self.embedder.embed(query)
            query_vector = [float(value) for value in raw]
            model = self.embedder.model
        except Exception:  # noqa: BLE001 - no leg on any failure
            return {}
        if not query_vector or not model:
            return {}
        points: list[tuple[int, list[float]]] = []
        rows = self.conn.execute(
            "SELECT id, embedding, embedding_model, embedding_dim FROM facts"
            " WHERE embedding IS NOT NULL"
        ).fetchall()
        for fact_id, blob, stored_model, stored_dim in rows:
            if stored_model != model or stored_dim != len(query_vector):
                continue
            vector = decode_embedding(
                self._open_fact_embedding(int(fact_id), blob), stored_dim
            )
            if vector is None:
                continue
            points.append((int(fact_id), vector))
        return dict(rank(query_vector, points))

    def backfill_embeddings(self) -> dict:
        """The donor's backfillEmbeddings (ticket #95): every fact whose
        embedding is NULL embeds oldest-first (created_ts, then id), one
        committed UPDATE per row, so a mid-run failure leaves the prior
        rows embedded and a retry finishes the job. Returns the donor's
        result shape plus the cause that stopped the run: embedded
        count, remaining count, cause None on a clean pass. Refuses
        without an active embeddings client, like the donor refuses
        without an embedder. The write lock is held per row, never
        across the run (the review's finding 2): the embed call is
        network time spent outside the lock, so a long backfill never
        blocks other writers, and the embedding IS NULL predicate makes
        each row's UPDATE safe to interleave."""
        self._guard()
        if not self._embeddings_on():
            raise ValueError(
                "backfill needs an active embeddings client: pass the"
                " embeddings probe on the capabilities page and keep"
                " semantic memory on in settings"
            )
        rows = self.conn.execute(
            "SELECT id FROM facts WHERE embedding IS NULL"
            " ORDER BY created_ts ASC, id ASC"
        ).fetchall()
        embedded = 0
        cause: str | None = None
        for (row_id,) in rows:
            fact_id = int(row_id)
            try:
                text = self.get(fact_id).text
            except UnknownFact:
                continue  # the row vanished mid-run; nothing to embed
            try:
                raw = self.embedder.embed(text)
                vector = self._prepare_vector(raw)
            except Exception as exc:  # noqa: BLE001 - one attempt, then stop
                cause = str(exc) or "the embeddings endpoint did not answer"
                break
            with self._lock:
                with self.conn:  # one committed UPDATE per row (retryable)
                    embedded += self._backfill_fact_vector(fact_id, vector)
        remaining = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM facts WHERE embedding IS NULL"
            ).fetchone()[0]
        )
        return {"embedded": embedded, "remaining": remaining, "cause": cause}

    def embedding_counts(self) -> dict:
        """The memory page's live counts: how many facts carry a vector
        and how many still miss one."""
        self._guard()
        embedded = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM facts WHERE embedding IS NOT NULL"
            ).fetchone()[0]
        )
        remaining = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM facts WHERE embedding IS NULL"
            ).fetchone()[0]
        )
        return {"embedded": embedded, "remaining": remaining}

    @_locked
    def edit(self, fact_id: int, text: str) -> EditResult:
        """Replace the text, merging into an existing duplicate when the
        new normalized text matches another fact's (ticket #92, the
        donor's updateFact): the edited fact's entity mentions move onto
        the survivor (INSERT OR IGNORE, then the source edges go), the
        survivor's null occurrence is backfilled from the edited row,
        the edited row and its citations are deleted, and any
        observation left uncited is pruned with them. The survivor is
        the oldest other fact, like the donor's ordering. An edit to a
        unique text behaves exactly as before and reports no merge.
        Sealed: the same row id rebinds the new ciphertext on the
        non-merge path; the merge path only moves and deletes rows.
        Embeddings (ticket #95, the donor's updateFact): an active edit
        embeds the new text, refreshing the edited row's vector on the
        non-merge path and backfilling the survivor's NULL on the merge
        path; an embed failure there clears the vector, exactly the
        donor's vector-or-null write. An inactive edit leaves whatever
        vectors exist alone."""
        self._guard()
        self.get(fact_id)
        text = text.strip()
        vector = self._vector_for(text)
        survivor_id = fact_id
        merged = False
        with self.conn:
            duplicate_id = self._find_identical_fact(text, exclude_id=fact_id)
            if duplicate_id is not None:
                merged = True
                survivor_id = duplicate_id
                # Move the edited fact's mentions onto the survivor.
                self.conn.execute(
                    "INSERT OR IGNORE INTO edges (fact_id, entity_id)"
                    " SELECT ?, entity_id FROM edges WHERE fact_id = ?",
                    (duplicate_id, fact_id),
                )
                row = self.conn.execute(
                    "SELECT occurrence_ts FROM facts WHERE id = ?", (fact_id,)
                ).fetchone()
                if row is not None and row[0] is not None:
                    self._backfill_occurrence(duplicate_id, row[0])
                self._backfill_fact_vector(duplicate_id, vector)
                self.conn.execute("DELETE FROM edges WHERE fact_id = ?", (fact_id,))
                self.conn.execute(
                    "DELETE FROM observation_sources WHERE fact_id = ?", (fact_id,)
                )
                self.conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
                # Spec decision 24: pruning follows every fact deletion.
                _prune_orphan_statements(self.conn)
            else:
                self.conn.execute(
                    "UPDATE facts SET text = ? WHERE id = ?",
                    (self._plain(text), fact_id),
                )
                self._seal_fact_text(fact_id, text)
                if self._embeddings_on():
                    self._refresh_fact_vector(fact_id, vector)
        return EditResult(
            fact=self.get(survivor_id),
            merged_into=merged,
        )

    @_locked
    def delete(self, fact_id: int) -> None:
        """Delete one fact and its observation citations, in one transaction.

        The id must exist: a missing fact raises UnknownFact before anything is
        removed, so a mis-typed delete cannot pass silently. Orphaned statements
        are pruned in the same transaction; the observations and entities that
        mentioned the fact stay.
        """
        self._guard()
        self.get(fact_id)
        with self.conn:
            # Spec decision 24: pruning follows every fact deletion, the
            # page's single delete included (ticket #93).
            self.conn.execute(
                "DELETE FROM observation_sources WHERE fact_id = ?", (fact_id,)
            )
            self.conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            _prune_orphan_statements(self.conn)

    @_locked
    def add_source(self, text: str, speaker: str = "", context: str = "") -> int:
        """Record one retained excerpt and return its id: the provenance
        every candidate fact from that retain shares. Sealed: all three
        text columns blank to '' with ciphertext bound to the row id."""
        self._guard()
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO sources (text, speaker, context, created_ts)"
                " VALUES (?, ?, ?, ?)",
                (self._plain(text), self._plain(speaker), self._plain(context),
                 self.clock()),
            )
            row_id = int(cursor.lastrowid)
            if self._box is not None:
                for column, value in (
                    ("text", text), ("speaker", speaker), ("context", context)
                ):
                    self.conn.execute(
                        f"UPDATE sources SET {column}_enc = ? WHERE id = ?",
                        (self._box.seal(value, "sources", column, row_id), row_id),
                    )
        return row_id

    @_locked
    def resolve_and_link(self, fact_id: int, mentions) -> list[EntityRef]:
        """Resolve a fact's (name, type) mentions against the loaded
        entities and write the entities and mention edges in one
        transaction. Duplicate edges are tolerated (INSERT OR IGNORE);
        an unknown fact or an unknown entity type is a ValueError or
        UnknownFact before anything is written."""
        self._guard()
        self.get(fact_id)
        cleaned: list[Mention] = []
        for name, mention_type in mentions:
            if mention_type not in ENTITY_TYPES:
                raise ValueError(
                    f"entity type must be one of {ENTITY_TYPES}, not {mention_type!r}"
                )
            folded = display_name(name)
            if folded:
                cleaned.append(Mention(folded, mention_type))
        repo = self._entity_repo()
        with self.conn:
            resolved = resolve_mentions(repo, cleaned)
            for ref in resolved:
                self.conn.execute(
                    "INSERT OR IGNORE INTO edges (fact_id, entity_id) VALUES (?, ?)",
                    (fact_id, ref.id),
                )
        return resolved

    # -- observations (ticket #93) ------------------------------------------

    @_locked
    def save_observation(
        self,
        scope_key: str,
        text: str,
        confidence: float,
        fact_ids,
        now: float,
        run_ts: float | None = None,
    ) -> SavedObservation:
        """The donor's saveObservations, reduced to the one-observation
        shape the approval cards need: upsert by normalized text within
        the scope (the blind index carries the match over a sealed
        bank), reinsert the citations, then drop the scope rows this
        save no longer keeps and report their ids.

        The donor prunes the unkept rows inside its one reflect write;
        here the write rides the card's acceptance, so `run_ts` carries
        the reflecting run's moment (the accepted card's created_ts):
        scope rows last written before the run are the ones the run did
        not re-derive (the donor's unkept set), except the row this
        call upserts, which a text match keeps. Rows written after the
        run started are its already-accepted siblings and stand. A call
        without a run reference is a pure upsert that prunes nothing.
        Stale citations to facts that no longer exist are dropped, and
        a draft whose citations all vanished is refused: an observation
        always cites at least one standing fact. Sealed: the plaintext
        columns blank and the ciphertext plus blind indexes (text and
        scope) land in the same transaction, bound to the row id, like
        every other write."""
        self._guard()
        text = text.strip()
        if not normalize_fact_text(text):
            raise ValueError("an observation needs text")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or confidence < 0
            or confidence > 1
        ):
            raise ValueError("confidence must be a number from 0 to 1")
        wanted = list(dict.fromkeys(int(f) for f in fact_ids))
        stored_scope = (
            self._box.blind(scope_key) if self._box is not None else scope_key
        )
        normalized = normalize_fact_text(text)
        with self.conn:
            cited: list[int] = []
            if wanted:
                marks = ",".join("?" for _ in wanted)
                standing = {
                    int(row[0])
                    for row in self.conn.execute(
                        f"SELECT id FROM facts WHERE id IN ({marks})", wanted
                    ).fetchall()
                }
                cited = [fact_id for fact_id in wanted if fact_id in standing]
            if not cited:
                raise ValueError(
                    "an observation needs at least one cited fact that exists"
                )
            prior_id = self._find_same_observation(stored_scope, normalized)
            if prior_id is not None:
                row = self.conn.execute(
                    "SELECT created_ts FROM observations WHERE id = ?", (prior_id,)
                ).fetchone()
                self.conn.execute(
                    "UPDATE observations SET text = ?, confidence = ?,"
                    " updated_ts = ?, stale_ts = NULL WHERE id = ?",
                    (self._plain(text), float(confidence), now, prior_id),
                )
                self._seal_observation_text(prior_id, text, normalized)
                observation_id = prior_id
                created_ts = float(row[0])
            else:
                cursor = self.conn.execute(
                    "INSERT INTO observations (scope_key, text, confidence,"
                    " created_ts, updated_ts) VALUES (?, ?, ?, ?, ?)",
                    (stored_scope, self._plain(text), float(confidence), now, now),
                )
                observation_id = int(cursor.lastrowid)
                self._seal_observation_text(observation_id, text, normalized)
                created_ts = now
            self.conn.execute(
                "DELETE FROM observation_sources WHERE observation_id = ?",
                (observation_id,),
            )
            for fact_id in cited:
                self.conn.execute(
                    "INSERT INTO observation_sources (observation_id, fact_id)"
                    " VALUES (?, ?)",
                    (observation_id, fact_id),
                )
            removed: list[int] = []
            if run_ts is not None:
                rows = self.conn.execute(
                    "SELECT id, updated_ts FROM observations WHERE scope_key = ?",
                    (stored_scope,),
                ).fetchall()
                for row_id, updated_ts in rows:
                    row_id = int(row_id)
                    if row_id == observation_id or updated_ts >= run_ts:
                        continue
                    self.conn.execute(
                        "DELETE FROM observation_sources WHERE observation_id = ?",
                        (row_id,),
                    )
                    self.conn.execute(
                        "DELETE FROM observations WHERE id = ?", (row_id,)
                    )
                    removed.append(row_id)
        observation = Observation(
            id=observation_id,
            text=text,
            confidence=float(confidence),
            fact_ids=tuple(cited),
            created_ts=created_ts,
            updated_ts=now,
        )
        return SavedObservation(observation=observation, removed_ids=tuple(removed))

    def _find_same_observation(self, stored_scope: str, normalized: str) -> int | None:
        """The donor's observationKey match: the row in this scope whose
        normalized text equals this one. Sealed banks compare the
        text_idx blind index (the donor's exact seam); plaintext banks
        scan the scope's texts."""
        if self._box is not None:
            row = self.conn.execute(
                "SELECT id FROM observations WHERE scope_key = ? AND text_idx = ?"
                " ORDER BY id ASC LIMIT 1",
                (stored_scope, self._box.blind(normalized)),
            ).fetchone()
            return None if row is None else int(row[0])
        rows = self.conn.execute(
            "SELECT id, text FROM observations WHERE scope_key = ? ORDER BY id ASC",
            (stored_scope,),
        ).fetchall()
        for row_id, stored in rows:
            if normalize_fact_text(stored) == normalized:
                return int(row_id)
        return None

    def _seal_observation_text(self, observation_id: int, text: str,
                               normalized: str) -> None:
        """Write one observation's ciphertext and blind index in the caller's
        transaction.

        A no-op on a plaintext bank. The index is the normalized text, so the
        sealed duplicate lookup finds the same rows the plaintext scan would.
        """
        if self._box is None:
            return
        self.conn.execute(
            "UPDATE observations SET text_enc = ?, text_idx = ? WHERE id = ?",
            (
                self._box.seal(text, "observations", "text", observation_id),
                self._box.blind(normalized),
                observation_id,
            ),
        )

    def observations(self) -> list[Observation]:
        """Every stored observation, most recently updated first, each
        with its citations in fact-id order. Sealed banks decrypt,
        requiring ciphertext like every read."""
        self._guard()
        if self._box is not None:
            rows = self.conn.execute(
                "SELECT id, text_enc, confidence, created_ts, updated_ts"
                " FROM observations ORDER BY updated_ts DESC, id DESC"
            ).fetchall()
            observations = []
            for row_id, text_enc, confidence, created_ts, updated_ts in rows:
                if text_enc is None:
                    raise MemoryEncryptedError(
                        "Missing ciphertext for observations.text."
                    )
                observations.append(Observation(
                    id=int(row_id),
                    text=self._box.open(
                        text_enc, "observations", "text", int(row_id)
                    ),
                    confidence=float(confidence),
                    fact_ids=self._citation_ids(row_id),
                    created_ts=float(created_ts),
                    updated_ts=float(updated_ts),
                ))
            return observations
        rows = self.conn.execute(
            "SELECT id, text, confidence, created_ts, updated_ts"
            " FROM observations ORDER BY updated_ts DESC, id DESC"
        ).fetchall()
        return [
            Observation(
                id=int(row_id),
                text=text,
                confidence=float(confidence),
                fact_ids=self._citation_ids(row_id),
                created_ts=float(created_ts),
                updated_ts=float(updated_ts),
            )
            for row_id, text, confidence, created_ts, updated_ts in rows
        ]

    def sources(self) -> list[SourceExcerpt]:
        """Every retained excerpt (the retain write's provenance rows),
        oldest first. Sealed banks open the three text columns like
        every other read; a missing ciphertext refuses rather than
        showing a blank excerpt."""
        self._guard()
        if self._box is not None:
            rows = self.conn.execute(
                "SELECT id, text_enc, speaker_enc, context_enc, created_ts"
                " FROM sources ORDER BY created_ts ASC, id ASC"
            ).fetchall()
            excerpts = []
            for row_id, text_enc, speaker_enc, context_enc, created_ts in rows:
                opened = []
                for column, blob in (("text", text_enc), ("speaker", speaker_enc),
                                     ("context", context_enc)):
                    if blob is None:
                        raise MemoryEncryptedError(
                            f"Missing ciphertext for sources.{column}."
                        )
                    opened.append(self._box.open(blob, "sources", column, int(row_id)))
                excerpts.append(SourceExcerpt(
                    int(row_id), opened[0], opened[1], opened[2], float(created_ts)
                ))
            return excerpts
        rows = self.conn.execute(
            "SELECT id, text, speaker, context, created_ts FROM sources"
            " ORDER BY created_ts ASC, id ASC"
        ).fetchall()
        return [
            SourceExcerpt(int(row_id), text, speaker, context, float(created_ts))
            for row_id, text, speaker, context, created_ts in rows
        ]

    def fact_entity_ids(self) -> dict[int, list[int]]:
        """Which entities each fact mentions (the edges table), the
        memory graph's mention links: fact id to entity ids, in the
        order recall loads them."""
        self._guard()
        return {
            fact_id: [link.id for link in links]
            for fact_id, links in self._entity_links().items()
        }

    def fact_ids_with_vectors(self) -> set[int]:
        """The facts that carry a stored vector (the semantic half's
        rows), for the graph's provenance line."""
        self._guard()
        return {
            int(row[0]) for row in self.conn.execute(
                "SELECT id FROM facts WHERE embedding_model IS NOT NULL"
            ).fetchall()
        }

    @_locked
    def delete_sources(self, source_ids) -> int:
        """Remove retained excerpts by id, clearing the pointer on any
        fact that still names one (the fact itself stays). Used by the
        sample seed's clear, which removes exactly what it wrote."""
        self._guard()
        ids = [int(value) for value in source_ids]
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        with self.conn:
            self.conn.execute(
                f"UPDATE facts SET source_id = NULL WHERE source_id IN ({marks})", ids
            )
            cursor = self.conn.execute(f"DELETE FROM sources WHERE id IN ({marks})", ids)
        return int(cursor.rowcount or 0)

    def _citation_ids(self, observation_id) -> tuple[int, ...]:
        """The ids of the facts an observation cites, ascending by fact id.

        The order comes from the table, not from the order the citations were
        written, so a rebuilt Observation reads the same on every load.
        """
        rows = self.conn.execute(
            "SELECT fact_id FROM observation_sources WHERE observation_id = ?"
            " ORDER BY fact_id ASC",
            (observation_id,),
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    # -- hygiene actions (ticket #92) ---------------------------------------

    def entities(self) -> list[EntitySummary]:
        """Every entity with its names, type and fact count, canonical
        name then id order. Sealed banks load through decryption, so
        the ordering is applied over the decrypted names."""
        self._guard()
        counts = {
            int(row[0]): int(row[1])
            for row in self.conn.execute(
                "SELECT entity_id, COUNT(*) FROM edges GROUP BY entity_id"
            ).fetchall()
        }
        summaries = [
            EntitySummary(
                id=entity.id,
                canonical_name=entity.canonical_name,
                aliases=entity.aliases,
                type=entity.type,
                fact_count=counts.get(entity.id, 0),
            )
            for entity in self._entity_repo().load()
        ]
        summaries.sort(key=lambda summary: (summary.canonical_name, summary.id))
        return summaries

    @_locked
    def merge_entities(self, survivor_id: int, removed_id: int) -> StoredEntity:
        """The page's manual entity merge (ticket #92): the removed
        entity's aliases and canonical name union into the survivor's
        alias list (deduped by normalized form, the donor's
        dedupeAliases), every mention edge is relinked onto the survivor
        (INSERT OR IGNORE), the removed entity and its index rows go,
        and the survivor's type upgrades from "other" like the automatic
        resolution's do. Merging an entity with itself is refused; an
        unknown id is an UnknownEntity. One transaction; sealed banks
        re-seal the survivor's names and rebuild its entity_name_index
        rows through the same seam resolution writes."""
        self._guard()
        if survivor_id == removed_id:
            raise ValueError("an entity cannot be merged with itself")
        repo = self._entity_repo()
        loaded = {entity.id: entity for entity in repo.load()}
        survivor = loaded.get(survivor_id)
        removed = loaded.get(removed_id)
        if survivor is None:
            raise UnknownEntity(f"no entity {survivor_id}")
        if removed is None:
            raise UnknownEntity(f"no entity {removed_id}")
        merged_aliases = dedupe_aliases(
            [*survivor.aliases, *removed.aliases, removed.canonical_name],
            survivor.canonical_name,
        )
        merged_type = (
            removed.type if survivor.type == "other" and removed.type != "other"
            else survivor.type
        )
        with self.conn:
            # Relink: every mention edge keeps its fact and swaps the
            # removed entity for the survivor.
            self.conn.execute(
                "INSERT OR IGNORE INTO edges (fact_id, entity_id)"
                " SELECT fact_id, ? FROM edges WHERE entity_id = ?",
                (survivor_id, removed_id),
            )
            self.conn.execute("DELETE FROM edges WHERE entity_id = ?", (removed_id,))
            self.conn.execute(
                "DELETE FROM entity_name_index WHERE entity_id = ?", (removed_id,)
            )
            repo.save(survivor_id, survivor.canonical_name, merged_aliases, merged_type)
            self.conn.execute("DELETE FROM entities WHERE id = ?", (removed_id,))
        return StoredEntity(
            id=survivor_id,
            canonical_name=survivor.canonical_name,
            aliases=merged_aliases,
            type=merged_type,
        )

    def sweep_candidates(self) -> list[SweepCandidate]:
        """The junk sweep's dry run (ticket #92): every fact the ported
        junk_reason (memory/knowledge_gap) would drop, in creation
        order, each with its reason. Sealed banks read decrypted text
        like every other read; nothing is written here."""
        self._guard()
        candidates: list[SweepCandidate] = []
        for fact in self.all():
            reason = junk_reason(fact.text)
            if reason is not None:
                candidates.append(SweepCandidate(fact=fact, reason=reason))
        return candidates

    @_locked
    def remove_facts(self, fact_ids) -> RemovedFacts:
        """The donor's removeFacts (ticket #92): all-or-nothing by id
        (one missing id refuses the whole call before anything is
        written), then one transaction deletes the facts' edges and
        citations and the facts themselves, prunes the orphan
        observations, and deletes the entities that the removed facts
        mentioned and that are left with zero edges. Duplicate ids
        collapse; an empty list is a ValueError."""
        self._guard()
        unique = list(dict.fromkeys(int(fact_id) for fact_id in fact_ids))
        if not unique:
            raise ValueError("at least one fact id is required")
        with self.conn:
            return self._remove_fact_statements(unique)

    def _remove_fact_statements(self, unique: list[int]) -> RemovedFacts:
        """remove_facts' statements without a transaction of their own,
        so the memory loop's removal can run them inside its one write.
        A fact another one superseded points back at nothing afterwards:
        the pointer clears so the older fact rides recall again."""
        marks = ",".join("?" for _ in unique)
        present = {
            int(row[0])
            for row in self.conn.execute(
                f"SELECT id FROM facts WHERE id IN ({marks})", unique
            ).fetchall()
        }
        missing = [fact_id for fact_id in unique if fact_id not in present]
        if missing:
            raise UnknownFact(f"no fact {missing[0]}")
        entity_ids = [
            int(row[0])
            for row in self.conn.execute(
                f"SELECT DISTINCT entity_id FROM edges WHERE fact_id IN ({marks})",
                unique,
            ).fetchall()
        ]
        self.conn.execute(
            f"UPDATE facts SET superseded_by = NULL WHERE superseded_by IN ({marks})",
            unique,
        )
        self.conn.execute(f"DELETE FROM edges WHERE fact_id IN ({marks})", unique)
        self.conn.execute(
            f"DELETE FROM observation_sources WHERE fact_id IN ({marks})", unique
        )
        self.conn.execute(f"DELETE FROM facts WHERE id IN ({marks})", unique)
        observation_ids = _prune_orphan_statements(self.conn)
        entity_removed: list[int] = []
        for entity_id in entity_ids:
            still_used = self.conn.execute(
                "SELECT 1 FROM edges WHERE entity_id = ? LIMIT 1", (entity_id,)
            ).fetchone()
            if still_used is not None:
                continue
            # The donor deletes only edge-less entities; a sealed
            # bank trims the blind index rows with the row itself.
            self.conn.execute(
                "DELETE FROM entity_name_index WHERE entity_id = ?", (entity_id,)
            )
            self.conn.execute(
                "DELETE FROM entities WHERE id = ?", (entity_id,)
            )
            entity_removed.append(entity_id)
        return RemovedFacts(
            fact_ids=tuple(unique),
            observation_ids=tuple(observation_ids),
            entity_ids=tuple(entity_removed),
        )

    # -- encryption action (ticket #94) -----------------------------------

    def plain_field_counts(self) -> dict[str, int]:
        """The dry-run counts: values per table that the conversion
        would seal. A sealed or locked bank has no plain fields to
        count, so it refuses."""
        self._guard()
        if self._box is not None:
            raise MemoryEncryptedError("The memory database is already encrypted.")
        return _plain_field_counts(self.conn)

    @_locked
    def encrypt_all(self, dry_run: bool = False) -> dict:
        """The one-action conversion (the donor's encryptBank).

        Dedupes identical facts and prunes orphan citations and
        observations first, then seals sources, entities (rebuilding the
        name index), facts and observations and writes the marker in ONE
        transaction; the key file is ensured before that transaction so
        a crash never orphans an encrypted database without a key; the
        commit is followed by wal_checkpoint(TRUNCATE) and VACUUM. A
        dry run only counts. An already-sealed bank refuses (the page
        says so). Any failure inside the transaction rolls back to a
        valid plaintext bank. The key comes from the store's key_path
        only: a conversion whose key exists nowhere on disk would brick
        the bank on the next open, so raw key bytes are not accepted.
        """
        self._guard()
        if self._box is not None:
            raise MemoryEncryptedError("The memory database is already encrypted.")
        if dry_run:
            fields = sum(_plain_field_counts(self.conn).values())
            return {"dry_run": True, "fields": fields}
        if self.key_path is None:
            raise ValueError(
                "memory encryption needs the key file path (memory.key)"
            )
        # Created before the transaction (see ensure_key_file).
        key = ensure_key_file(self.key_path)
        _prune_orphan_observations(self.conn)
        _dedupe_identical_facts(self.conn)
        fields = sum(_plain_field_counts(self.conn).values())
        box = CryptoBox(key)
        with self.conn:
            self._encrypt_sources(box)
            self._encrypt_entities(box)
            self._encrypt_facts(box)
            self._encrypt_observations(box)
            self._write_marker(key)
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.execute("VACUUM")
        self.conn.commit()
        # The running store reads its own conversion from here on.
        self._box = box
        return {"fields": fields}

    def _encrypt_sources(self, box: CryptoBox) -> None:
        """Seal every source row: blank the three plaintext columns, store the
        ciphertext in the _enc ones.

        Runs inside encrypt_all's transaction and never commits, so a failure
        leaves the bank entirely plaintext.
        """
        rows = self.conn.execute(
            "SELECT id, text, speaker, context FROM sources"
        ).fetchall()
        for row_id, text, speaker, context in rows:
            self.conn.execute(
                "UPDATE sources SET text = '', text_enc = ?, speaker = '',"
                " speaker_enc = ?, context = '', context_enc = ? WHERE id = ?",
                (
                    box.seal(text, "sources", "text", row_id),
                    box.seal(speaker, "sources", "speaker", row_id),
                    box.seal(context, "sources", "context", row_id),
                    row_id,
                ),
            )

    def _encrypt_entities(self, box: CryptoBox) -> None:
        """Seal every entity's canonical name and aliases, and rebuild its index
        rows.

        aliases_json is blanked to "[]" and aliases_enc left NULL when the entity
        has no aliases, so an empty alias list is empty in both representations.
        Runs inside encrypt_all's transaction.
        """
        rows = self.conn.execute(
            "SELECT id, canonical_name, aliases_json FROM entities"
        ).fetchall()
        for row_id, canonical_name, aliases_json in rows:
            aliases = _parse_aliases(aliases_json)
            self.conn.execute(
                "UPDATE entities SET canonical_name = '', canonical_name_enc = ?,"
                " aliases_json = '[]', aliases_enc = ?, name_idx = ? WHERE id = ?",
                (
                    box.seal(canonical_name, "entities", "canonical_name", row_id),
                    (box.seal(json.dumps(aliases, ensure_ascii=False),
                              "entities", "aliases", row_id)
                     if aliases else None),
                    box.blind(_normalize_name(canonical_name)),
                    row_id,
                ),
            )
            self._sync_name_index(box, row_id, canonical_name, aliases)

    def _encrypt_facts(self, box: CryptoBox) -> None:
        """Seal every fact's text and, where one exists, its embedding blob.

        The blob is sealed under the facts/embedding destination bound to the row
        id, so a sealed bank's vectors are as unreadable as its text, and the
        text_idx blind keeps duplicate detection working. Runs inside
        encrypt_all's transaction.
        """
        # Ticket #95: an existing plain embedding blob re-seals under the
        # facts|embedding aad in the same conversion, like the donor's
        # encrypt-bank does.
        rows = self.conn.execute("SELECT id, text, embedding FROM facts").fetchall()
        for row_id, text, embedding in rows:
            self.conn.execute(
                "UPDATE facts SET text = '', text_enc = ?, text_idx = ?,"
                " embedding = ? WHERE id = ?",
                (
                    box.seal(text, "facts", "text", row_id),
                    box.blind(normalize_fact_text(text)),
                    (
                        box.seal_bytes(embedding, "facts", "embedding", row_id)
                        if embedding is not None
                        else None
                    ),
                    row_id,
                ),
            )

    def _encrypt_observations(self, box: CryptoBox) -> None:
        """Seal every observation's text and blinded scope key.

        The scope key is replaced by its blind rather than blanked, because the
        scope index is how a sealed bank finds an observation by scope; text_idx
        carries the normalized text for the duplicate lookup. Runs inside
        encrypt_all's transaction.
        """
        rows = self.conn.execute(
            "SELECT id, scope_key, text FROM observations"
        ).fetchall()
        for row_id, scope_key, text in rows:
            self.conn.execute(
                "UPDATE observations SET scope_key = ?, text = '', text_enc = ?,"
                " text_idx = ? WHERE id = ?",
                (
                    box.blind(scope_key),
                    box.seal(text, "observations", "text", row_id),
                    box.blind(normalize_fact_text(text)),
                    row_id,
                ),
            )

    def _write_marker(self, key: bytes) -> None:
        """Insert the schema_meta row that marks the bank sealed.

        No commit of its own: the marker belongs to the caller's transaction, so
        it lands together with the ciphertext it vouches for.
        """
        self.conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('encryption', ?)",
            (make_marker(key),),
        )

    # -- sealed-write helpers ----------------------------------------------

    def _plain(self, value: str) -> str:
        """The plaintext column value: unchanged until sealed, then ''
        (the donor's storedPlain for a NOT NULL column)."""
        return value if self._box is None else ""

    def _seal_fact_text(self, fact_id: int, text: str) -> None:
        """Write one fact's ciphertext and blind text index in the caller's
        transaction.

        A no-op on a plaintext bank. A sealed read requires text_enc, so a write
        that skipped this would leave a row nothing can read back.
        """
        if self._box is None:
            return
        self.conn.execute(
            "UPDATE facts SET text_enc = ?, text_idx = ? WHERE id = ?",
            (
                self._box.seal(text, "facts", "text", fact_id),
                self._box.blind(normalize_fact_text(text)),
                fact_id,
            ),
        )

    def _sync_name_index(self, box: CryptoBox, entity_id: int,
                         canonical: str, aliases) -> None:
        """Rebuild one entity's rows in entity_name_index: one blind per
        distinct normalized name (canonical first, then aliases)."""
        self.conn.execute(
            "DELETE FROM entity_name_index WHERE entity_id = ?", (entity_id,)
        )
        for name in [canonical, *aliases]:
            normalized = _normalize_name(name)
            if not normalized:
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_name_index (entity_id, name_idx)"
                " VALUES (?, ?)",
                (entity_id, box.blind(normalized)),
            )

    def _entity_repo(self) -> "_EntityRepo":
        """A resolution seam over this store's connection, clock and crypto box.

        A fresh repo per call: it carries no state of its own, and its writes
        join whatever transaction the caller has open.
        """
        return _EntityRepo(self.conn, self.clock, self._box)

    # -- reads ------------------------------------------------------------

    def get(self, fact_id: int) -> Fact:
        """One fact by id, decrypted through the store's own bindings.

        Raises UnknownFact for an id that is not stored, so "no such fact" stays
        distinct from "a fact whose text is empty".
        """
        self._guard()
        row = self.conn.execute(
            f"SELECT {_COLUMNS}, text_enc FROM facts WHERE id = ?", (fact_id,)
        ).fetchone()
        if row is None:
            raise UnknownFact(f"no fact {fact_id}")
        return self._fact_from_row(row)

    def all(self) -> list[Fact]:
        """Every fact in creation order (the recall tie-break order)."""
        self._guard()
        rows = self.conn.execute(
            f"SELECT {_COLUMNS}, text_enc FROM facts"
            " ORDER BY created_ts ASC, id ASC"
        ).fetchall()
        return [self._fact_from_row(row) for row in rows]

    def graph_snapshot(
        self,
        now: float | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = DEFAULT_GRAPH_LIMIT,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
    ):
        """The memory graph page's snapshot (ticket #96, the donor's
        buildGraphSnapshot with the I/O filled in): the facts load with
        their stored vectors, the observations with their citations and
        the entity links exactly as recall loads them, and the pure
        builder (memory/graph) does all the arithmetic. `now` defaults
        to the store's clock; the bounds are epoch seconds, the since
        bound inclusive and the until bound exclusive. Node ids are
        table-qualified (`fact:<id>`, `observation:<id>`) because the
        donor's per-row UUIDs were globally unique and these integer
        sequences are not; the graph's undirected keys then stay
        honest. Sealed banks decrypt through the same helpers every
        other read uses, so a sealed bank's snapshot equals the
        plaintext one's."""
        self._guard()
        if now is None:
            now = self.clock()
        facts = self._facts_with_embeddings()
        observations = [
            GraphObservation(
                id=f"observation:{row.id}",
                text=row.text,
                updated_ts=row.updated_ts,
                fact_ids=tuple(_qualified_fact_id(fid) for fid in row.fact_ids),
            )
            for row in self.observations()
        ]
        links = {
            _qualified_fact_id(fact_id): entity_links
            for fact_id, entity_links in self._entity_links().items()
        }
        return build_graph(
            facts,
            observations,
            links,
            now,
            since=since,
            until=until,
            limit=limit,
            min_similarity=min_similarity,
        )

    def _facts_with_embeddings(self) -> list[GraphFact]:
        """Every fact as the builder reads it: identity, dates and the
        decoded vector (None whenever the stored triple is incomplete,
        the donor's vectorOf). Sealed banks require and open the text
        and embedding ciphertext like every read; the embedding's blind
        envelope opens only when a blob is present, because a fact
        stored while the semantic half was off keeps a NULL vector."""
        facts: list[GraphFact] = []
        if self._box is not None:
            rows = self.conn.execute(
                "SELECT id, text_enc, kind, created_ts, occurrence_ts,"
                " embedding, embedding_model, embedding_dim FROM facts"
                " ORDER BY created_ts ASC, id ASC"
            ).fetchall()
            for row in rows:
                (row_id, text_enc, kind, created_ts, occurrence_ts,
                 blob, model, dim) = row
                if text_enc is None:
                    raise MemoryEncryptedError("Missing ciphertext for facts.text.")
                text = self._box.open(text_enc, "facts", "text", row_id)
                facts.append(GraphFact(
                    id=_qualified_fact_id(row_id),
                    text=text,
                    created_ts=float(created_ts),
                    kind=kind,
                    occurrence_ts=occurrence_ts,
                    embedding=self._stored_vector(int(row_id), blob, dim),
                    embedding_model=model,
                    embedding_dim=dim,
                ))
            return facts
        rows = self.conn.execute(
            "SELECT id, text, kind, created_ts, occurrence_ts,"
            " embedding, embedding_model, embedding_dim FROM facts"
            " ORDER BY created_ts ASC, id ASC"
        ).fetchall()
        for row_id, text, kind, created_ts, occurrence_ts, blob, model, dim in rows:
            facts.append(GraphFact(
                id=_qualified_fact_id(row_id),
                text=text,
                created_ts=float(created_ts),
                kind=kind,
                occurrence_ts=occurrence_ts,
                embedding=self._stored_vector(int(row_id), blob, dim),
                embedding_model=model,
                embedding_dim=dim,
            ))
        return facts

    def _stored_vector(self, fact_id: int, blob, dim):
        """The decoded vector behind one stored blob, or None: absent
        whenever the blob or the dimension is missing (the donor's
        vectorOf), decoded through the sealed envelope when the bank is
        sealed and through decode_embedding either way."""
        if blob is None or dim is None:
            return None
        raw = self._open_fact_embedding(fact_id, blob)
        return decode_embedding(raw, dim)

    def _fact_from_row(self, row) -> Fact:
        """Build a Fact from one _COLUMNS row followed by its text_enc.

        Index 7 is the ciphertext: a sealed bank reads the text from it and
        raises MemoryEncryptedError when it is missing, so a row without
        ciphertext is never served as its blank plaintext column.
        """
        text = row[1]
        if self._box is not None:
            if row[7] is None:
                raise MemoryEncryptedError("Missing ciphertext for facts.text.")
            text = self._box.open(row[7], "facts", "text", row[0])
        return Fact(
            id=row[0],
            text=text,
            source=row[2],
            created_ts=row[3],
            kind=row[4],
            occurrence_ts=row[5],
            source_id=row[6],
        )

    def recall(self, query: str) -> list[tuple[float, Fact]]:
        """The hybrid ranked recall (memory/hybrid): keyword, entity
        graph, recency and time windows fused deterministically, best
        first, the score the fused rank contribution. The old overlap
        rank stays in memory/service as the fallback scorer. Over a
        sealed bank the rows decrypt in memory (a known donor limit at
        personal scale). Ticket #95: when the semantic half is active,
        the query embeds once and the matching rows' cosine scores join
        the fusion as the vector leg at unit weight; any embed failure
        or a mismatched model or dimension simply leaves the leg out,
        so recall is never an error because of it."""
        self._guard()
        # A fact a newer one replaced (the memory loop's supersede step)
        # stays on the page for review but never rides recall.
        replaced = self.superseded_map()
        facts = [fact for fact in self.all() if fact.id not in replaced]
        links = self._entity_links()
        vector_scores = self._vector_scores(query)
        return rank_hybrid(
            query, facts, links, now=self.clock(), vector_scores=vector_scores
        )

    def _entity_links(self) -> dict[int, list[EntityLink]]:
        """The fact-to-entity graph the graph leg expands: one entry per
        linked fact, entities in canonical-name then id order."""
        if self._box is not None:
            rows = self.conn.execute(
                "SELECT g.fact_id, e.id, e.canonical_name_enc, e.aliases_enc"
                " FROM edges g JOIN entities e ON e.id = g.entity_id"
                " ORDER BY e.id"
            ).fetchall()
            links: dict[int, list[EntityLink]] = {}
            for fact_id, entity_id, name_enc, aliases_enc in rows:
                if name_enc is None:
                    raise MemoryEncryptedError(
                        "Missing ciphertext for entities.canonical_name."
                    )
                name = self._box.open(name_enc, "entities", "canonical_name", entity_id)
                aliases: tuple[str, ...] = ()
                if aliases_enc is not None:
                    decoded = self._box.open(
                        aliases_enc, "entities", "aliases", entity_id
                    )
                    aliases = _parse_aliases(decoded)
                links.setdefault(fact_id, []).append(
                    EntityLink(id=entity_id, name=name, aliases=aliases)
                )
            return links
        rows = self.conn.execute(
            "SELECT g.fact_id, e.id, e.canonical_name, e.aliases_json"
            " FROM edges g JOIN entities e ON e.id = g.entity_id"
            " ORDER BY e.canonical_name, e.id"
        ).fetchall()
        links = {}
        for fact_id, entity_id, name, aliases_json in rows:
            links.setdefault(fact_id, []).append(
                EntityLink(id=entity_id, name=name, aliases=_parse_aliases(aliases_json))
            )
        return links


    # -- the memory loop: supersede, stale flags, removal and undo ---------

    def superseded_map(self) -> dict[int, int]:
        """Replaced fact id to the newer fact id that replaced it."""
        self._guard()
        return {
            int(old): int(new)
            for old, new in self.conn.execute(
                "SELECT id, superseded_by FROM facts WHERE superseded_by IS NOT NULL"
            ).fetchall()
        }

    @_locked
    def mark_superseded(self, old_id: int, new_id: int) -> None:
        """Record that `new_id` replaces `old_id` (the loop's contradiction
        step). The older fact stays stored and visible; recall skips it."""
        self._guard()
        if int(old_id) == int(new_id):
            raise ValueError("a fact cannot replace itself")
        self.get(old_id)
        self.get(new_id)
        with self.conn:
            self.conn.execute(
                "UPDATE facts SET superseded_by = ? WHERE id = ?",
                (int(new_id), int(old_id)),
            )

    @_locked
    def clear_superseded(self, fact_id: int) -> None:
        """Keep both: the older fact rides recall again."""
        self._guard()
        self.get(fact_id)
        with self.conn:
            self.conn.execute(
                "UPDATE facts SET superseded_by = NULL WHERE id = ?", (int(fact_id),)
            )

    def stale_observations(self) -> dict[int, float]:
        """Observation id to the moment one of its cited facts was removed;
        only observations that still cite something stay to be flagged."""
        self._guard()
        return {
            int(row_id): float(stale)
            for row_id, stale in self.conn.execute(
                "SELECT id, stale_ts FROM observations WHERE stale_ts IS NOT NULL"
            ).fetchall()
        }

    def exclusive(self):
        """The store's write lock, for a caller that must read and write
        as one step (the memory loop's observation pass). Re-entrant, so
        the locked methods inside it still work."""
        return self._lock

    @_locked
    def mark_observation(self, observation_id: int, method: str, basis) -> None:
        """Record how a consolidated observation was written and from
        which standing facts (see _LOOP_COLUMNS)."""
        self._guard()
        ids = ",".join(str(int(value)) for value in sorted(set(basis)))
        with self.conn:
            self.conn.execute(
                "UPDATE observations SET method = ?, basis = ? WHERE id = ?",
                (str(method), ids, int(observation_id)),
            )

    def observation_marks(self) -> dict[int, tuple[str | None, frozenset[int]]]:
        """Observation id to (method, basis fact ids) for every row."""
        self._guard()
        marks: dict[int, tuple[str | None, frozenset[int]]] = {}
        for row_id, method, basis in self.conn.execute(
            "SELECT id, method, basis FROM observations"
        ).fetchall():
            ids = frozenset(int(part) for part in (basis or "").split(",") if part.strip())
            marks[int(row_id)] = (method, ids)
        return marks

    def observation_ids_in_scope(self, scope_key: str) -> list[int]:
        """The observation rows one scope holds (blinded on a sealed bank)."""
        self._guard()
        stored = self._box.blind(scope_key) if self._box is not None else scope_key
        return [
            int(row[0])
            for row in self.conn.execute(
                "SELECT id FROM observations WHERE scope_key = ? ORDER BY id", (stored,)
            ).fetchall()
        ]

    def scope_of_observations(self, scope_keys) -> dict[int, str]:
        """Observation id to the scope key it was saved under, for the
        scope keys asked about (a sealed bank stores only their blind
        form, so the caller names the keys it wants to recognize)."""
        self._guard()
        wanted = {
            (self._box.blind(key) if self._box is not None else key): key
            for key in scope_keys
        }
        if not wanted:
            return {}
        marks = ",".join("?" for _ in wanted)
        return {
            int(row_id): wanted[stored]
            for row_id, stored in self.conn.execute(
                f"SELECT id, scope_key FROM observations WHERE scope_key IN ({marks})",
                list(wanted),
            ).fetchall()
        }

    @_locked
    def delete_observations(self, observation_ids) -> list[int]:
        """Delete observations and their citations; the facts stay."""
        self._guard()
        ids = list(dict.fromkeys(int(value) for value in observation_ids))
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        with self.conn:
            present = [
                int(row[0]) for row in self.conn.execute(
                    f"SELECT id FROM observations WHERE id IN ({marks})", ids
                ).fetchall()
            ]
            self.conn.execute(
                f"DELETE FROM observation_sources WHERE observation_id IN ({marks})", ids
            )
            self.conn.execute(f"DELETE FROM observations WHERE id IN ({marks})", ids)
        return present

    def fact_ids_for_entity(self, entity_id: int) -> list[int]:
        """The ids of the facts linked to an entity, ascending.

        An unknown entity raises UnknownEntity instead of returning an empty
        list, so "no such entity" cannot be read as "an entity with no facts".
        """
        self._guard()
        if self.conn.execute(
            "SELECT 1 FROM entities WHERE id = ?", (int(entity_id),)
        ).fetchone() is None:
            raise UnknownEntity(f"no entity {entity_id}")
        return [
            int(row[0]) for row in self.conn.execute(
                "SELECT fact_id FROM edges WHERE entity_id = ? ORDER BY fact_id",
                (int(entity_id),),
            ).fetchall()
        ]

    def fact_ids_for_sources(self, source_ids) -> list[int]:
        """The ids of the facts naming one of these sources, ascending.

        A read: ids that match no fact are simply absent from the result, and an
        empty input answers [] without querying.
        """
        self._guard()
        ids = [int(value) for value in source_ids]
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        return [
            int(row[0]) for row in self.conn.execute(
                f"SELECT id FROM facts WHERE source_id IN ({marks}) ORDER BY id", ids
            ).fetchall()
        ]

    def source_exists(self, source_id: int) -> bool:
        """True when a source row with this id exists.

        A locked store raises rather than answering, like every other operation,
        so a caller cannot validate a pointer against a bank it may not read.
        """
        self._guard()
        return self.conn.execute(
            "SELECT 1 FROM sources WHERE id = ?", (int(source_id),)
        ).fetchone() is not None

    def _rows(self, table: str, column: str, ids) -> dict:
        """Raw rows (every column, ciphertext included) for an undo dump."""
        ids = list(dict.fromkeys(int(value) for value in ids))
        if not ids:
            return {"columns": [], "rows": []}
        marks = ",".join("?" for _ in ids)
        cursor = self.conn.execute(
            f"SELECT * FROM {table} WHERE {column} IN ({marks})", ids
        )
        columns = [item[0] for item in cursor.description]
        return {"columns": columns, "rows": [tuple(row) for row in cursor.fetchall()]}

    @_locked
    def remove_with_effects(
        self,
        fact_ids,
        observation_ids=(),
        source_ids=(),
        keep_source_ids=(),
    ) -> dict:
        """The memory loop's removal: one transaction that removes the
        facts (remove_facts' rules: citations, orphan observations and
        edge-less entities go with them), the observations named
        outright, the excerpts named outright and any excerpt the
        removal leaves without a fact (unless a waiting card still needs
        it, `keep_source_ids`), flags the surviving observations that
        lost a citation, and releases any fact a removed fact had
        replaced. Before writing it dumps every row it touches, so the
        caller can hold an undo; the answer carries the dump and what
        changed."""
        self._guard()
        facts = list(dict.fromkeys(int(value) for value in fact_ids))
        named_observations = list(dict.fromkeys(int(value) for value in observation_ids))
        named_sources = {int(value) for value in source_ids}
        keep = {int(value) for value in keep_source_ids}
        now = self.clock()
        with self.conn:
            fmarks = ",".join("?" for _ in facts) or "NULL"
            citing = [
                int(row[0]) for row in self.conn.execute(
                    f"SELECT DISTINCT observation_id FROM observation_sources"
                    f" WHERE fact_id IN ({fmarks})", facts
                ).fetchall()
            ] if facts else []
            entity_ids = [
                int(row[0]) for row in self.conn.execute(
                    f"SELECT DISTINCT entity_id FROM edges WHERE fact_id IN ({fmarks})",
                    facts,
                ).fetchall()
            ] if facts else []
            released_pairs = [
                (int(row[0]), int(row[1])) for row in self.conn.execute(
                    f"SELECT id, superseded_by FROM facts WHERE superseded_by IN ({fmarks})"
                    f" AND id NOT IN ({fmarks})", facts + facts
                ).fetchall()
            ] if facts else []
            released = [old for old, _new in released_pairs]
            fact_sources = {
                int(row[0]) for row in self.conn.execute(
                    f"SELECT DISTINCT source_id FROM facts WHERE id IN ({fmarks})"
                    " AND source_id IS NOT NULL", facts
                ).fetchall()
            } if facts else set()
            candidate_sources = sorted(named_sources | fact_sources)
            touched_observations = list(dict.fromkeys(citing + named_observations))
            dump = {
                "facts": self._rows("facts", "id", facts),
                "released_pairs": released_pairs,
                "edges": self._rows("edges", "fact_id", facts),
                "observations": self._rows("observations", "id", touched_observations),
                "observation_sources": self._rows(
                    "observation_sources", "observation_id", touched_observations
                ),
                "entities": self._rows("entities", "id", entity_ids),
                "entity_name_index": self._rows("entity_name_index", "entity_id", entity_ids),
                "sources": self._rows("sources", "id", candidate_sources),
            }
            if named_observations:
                omarks = ",".join("?" for _ in named_observations)
                self.conn.execute(
                    f"DELETE FROM observation_sources WHERE observation_id IN ({omarks})",
                    named_observations,
                )
                self.conn.execute(
                    f"DELETE FROM observations WHERE id IN ({omarks})", named_observations
                )
            removed = (
                self._remove_fact_statements(facts) if facts
                else RemovedFacts(fact_ids=())
            )
            removed_observations = list(dict.fromkeys(
                [oid for oid in named_observations] + list(removed.observation_ids)
            ))
            flagged = [
                oid for oid in citing
                if oid not in removed_observations
                and self.conn.execute(
                    "SELECT 1 FROM observations WHERE id = ?", (oid,)
                ).fetchone() is not None
            ]
            for oid in flagged:
                self.conn.execute(
                    "UPDATE observations SET stale_ts = ? WHERE id = ?", (now, oid)
                )
            removed_sources: list[int] = []
            for source_id in candidate_sources:
                if source_id in keep:
                    continue
                still_cited = self.conn.execute(
                    "SELECT 1 FROM facts WHERE source_id = ? LIMIT 1", (source_id,)
                ).fetchone()
                if still_cited is not None and source_id not in named_sources:
                    continue
                self.conn.execute(
                    "UPDATE facts SET source_id = NULL WHERE source_id = ?", (source_id,)
                )
                cursor = self.conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
                if cursor.rowcount:
                    removed_sources.append(source_id)
        return {
            "fact_ids": list(removed.fact_ids),
            "observation_ids": removed_observations,
            "flagged_observation_ids": flagged,
            "entity_ids": list(removed.entity_ids),
            "source_ids": removed_sources,
            "released_fact_ids": released,
            "dump": dump,
        }

    @_locked
    def restore_dump(self, dump: dict, drop_observation_ids=()) -> None:
        """Undo a remove_with_effects: put every dumped row back with its
        own id (ciphertext stays bound to it), drop the observations the
        removal's re-consolidation wrote, and point the released facts
        at their replacement again. Refused, with nothing written, when
        a removed fact's id has been taken since."""
        self._guard()
        fact_rows = dump["facts"]
        with self.conn:
            if fact_rows["rows"]:
                id_at = fact_rows["columns"].index("id")
                ids = [row[id_at] for row in fact_rows["rows"]]
                marks = ",".join("?" for _ in ids)
                taken = self.conn.execute(
                    f"SELECT id FROM facts WHERE id IN ({marks})", ids
                ).fetchone()
                if taken is not None:
                    raise ValueError(
                        "Memory changed since the removal, so it can no longer be undone."
                    )
            drop = list(dict.fromkeys(int(v) for v in drop_observation_ids))
            dumped_obs = dump["observations"]
            if dumped_obs["rows"]:
                at = dumped_obs["columns"].index("id")
                drop.extend(int(row[at]) for row in dumped_obs["rows"])
            if drop:
                marks = ",".join("?" for _ in drop)
                self.conn.execute(
                    f"DELETE FROM observation_sources WHERE observation_id IN ({marks})", drop
                )
                self.conn.execute(f"DELETE FROM observations WHERE id IN ({marks})", drop)
            for table in ("sources", "entities", "entity_name_index", "facts",
                          "edges", "observations", "observation_sources"):
                part = dump[table]
                if not part["rows"]:
                    continue
                columns = ", ".join(part["columns"])
                marks = ", ".join("?" for _ in part["columns"])
                self.conn.executemany(
                    f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({marks})",
                    part["rows"],
                )
            for old_id, new_id in dump.get("released_pairs", []):
                self.conn.execute(
                    "UPDATE facts SET superseded_by = ? WHERE id = ?", (new_id, old_id)
                )


def _normalize_name(name: str) -> str:
    """The hybrid ranker's normalize_name, the one normalizer that
    serves recall and resolution alike."""
    return normalize_name(name)


def _qualified_fact_id(row_id) -> str:
    """The graph node id for a fact row (ticket #96): the table-
    qualified string that keeps fact and observation nodes distinct,
    the donor's globally unique ids reduced to a rule."""
    return f"fact:{int(row_id)}"


class _EntityRepo(EntityRepo):
    """The resolution seam over the store's connection: entities load in
    id order (the donor's insertion order) and every write runs inside
    the transaction resolve_and_link opened, so a batch is all or
    nothing. Sealed: names load through decryption, writes blank the
    plaintext columns and maintain the entity_name_index blind rows."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float],
                 box: CryptoBox | None = None) -> None:
        """Bind the connection, clock and crypto box the repo reads and writes
        through.

        Nothing is loaded here, and no transaction is opened: the box decides
        whether the plaintext or the sealed column set is used, and the caller
        owns the transaction.
        """
        self.conn = conn
        self.clock = clock
        self.box = box

    def load(self) -> list[StoredEntity]:
        """Every entity in id order, decrypted on a sealed bank.

        Id order is the donor's insertion order, which keeps a resolution run
        deterministic when two entities answer a mention equally well. A sealed
        row missing canonical-name ciphertext raises MemoryEncryptedError; an
        entity with no aliases loads with ().
        """
        if self.box is None:
            rows = self.conn.execute(
                "SELECT id, canonical_name, aliases_json, type FROM entities"
                " ORDER BY id ASC"
            ).fetchall()
            return [
                StoredEntity(
                    id=row[0],
                    canonical_name=row[1],
                    aliases=_parse_aliases(row[2]),
                    type=row[3],
                )
                for row in rows
            ]
        stored: list[StoredEntity] = []
        for row in self.conn.execute(
            "SELECT id, canonical_name_enc, aliases_enc, type FROM entities"
            " ORDER BY id ASC"
        ).fetchall():
            entity_id, name_enc, aliases_enc, entity_type = row
            if name_enc is None:
                raise MemoryEncryptedError(
                    "Missing ciphertext for entities.canonical_name."
                )
            canonical = self.box.open(
                name_enc, "entities", "canonical_name", entity_id
            )
            aliases: tuple[str, ...] = ()
            if aliases_enc is not None:
                aliases = _parse_aliases(
                    self.box.open(aliases_enc, "entities", "aliases", entity_id)
                )
            stored.append(StoredEntity(
                id=entity_id, canonical_name=canonical, aliases=aliases,
                type=entity_type,
            ))
        return stored

    def save(self, entity_id: int, canonical: str, aliases, entity_type: str) -> None:
        """Replace one entity's names and type wholesale.

        aliases is the entity's complete alias set, not a delta, so an empty one
        clears them. Sealed: the plaintext columns blank, name_idx blinded, and
        the entity's index rows rebuilt. Joins the caller's transaction.
        """
        if self.box is None:
            self.conn.execute(
                "UPDATE entities SET canonical_name = ?, aliases_json = ?, type = ?"
                " WHERE id = ?",
                (canonical, json.dumps(list(aliases), ensure_ascii=False),
                 entity_type, entity_id),
            )
            return
        aliases = tuple(aliases)
        self.conn.execute(
            "UPDATE entities SET canonical_name = '', canonical_name_enc = ?,"
            " aliases_json = '[]', aliases_enc = ?, name_idx = ?, type = ?"
            " WHERE id = ?",
            (
                self.box.seal(canonical, "entities", "canonical_name", entity_id),
                (self.box.seal(json.dumps(list(aliases), ensure_ascii=False),
                              "entities", "aliases", entity_id)
                 if aliases else None),
                self.box.blind(_normalize_name(canonical)),
                entity_type,
                entity_id,
            ),
        )
        self._sync_name_index(entity_id, canonical, aliases)

    def create(self, name: str, entity_type: str) -> int:
        """Insert an entity and return the id the database assigned.

        That id is the handle later saves and edges use. Sealed: the row is
        inserted with NULL ciphertext and a second statement seals the name
        against the new id, since the ciphertext binds a row id the insert cannot
        know beforehand. Joins the caller's transaction.
        """
        if self.box is None:
            cursor = self.conn.execute(
                "INSERT INTO entities (canonical_name, aliases_json, type, created_ts)"
                " VALUES (?, '[]', ?, ?)",
                (name, entity_type, self.clock()),
            )
            return int(cursor.lastrowid)
        cursor = self.conn.execute(
            "INSERT INTO entities (canonical_name, aliases_json, aliases_enc,"
            " canonical_name_enc, name_idx, type, created_ts)"
            " VALUES ('', '[]', NULL, NULL, ?, ?, ?)",
            (self.box.blind(_normalize_name(name)), entity_type, self.clock()),
        )
        entity_id = int(cursor.lastrowid)
        # The ciphertext binds to the id the insert just assigned.
        self.conn.execute(
            "UPDATE entities SET canonical_name_enc = ? WHERE id = ?",
            (self.box.seal(name, "entities", "canonical_name", entity_id), entity_id),
        )
        self._sync_name_index(entity_id, name, ())
        return entity_id

    def linked_fact_ids(self, entity_ids) -> dict[int, set[int]]:
        """The fact adjacency the co-occurrence winner reads: one entry
        per asked id, empty sets included."""
        ids = list(set(entity_ids))
        linked: dict[int, set[int]] = {entity_id: set() for entity_id in ids}
        if not ids:
            return linked
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT entity_id, fact_id FROM edges WHERE entity_id IN ({marks})",
            ids,
        ).fetchall()
        for entity_id, fact_id in rows:
            linked[entity_id].add(int(fact_id))
        return linked

    def exact_ids(self, name: str) -> list[int] | None:
        """The exact index lookup (the donor's exactEntityIds): the
        entity ids whose indexed names equal this name. The index holds
        canonical names and aliases, so the caller still checks the
        canonical it cares about. Plaintext banks keep no index: None
        means every entity is a candidate."""
        if self.box is None:
            return None
        normalized = _normalize_name(name)
        if not normalized:
            return None
        rows = self.conn.execute(
            "SELECT entity_id FROM entity_name_index WHERE name_idx = ?",
            (self.box.blind(normalized),),
        ).fetchall()
        return [int(row[0]) for row in rows]

    def _sync_name_index(self, entity_id: int, canonical: str, aliases) -> None:
        """Rebuild this entity's rows in entity_name_index: one blind per
        distinct normalized name.

        A no-op on a plaintext bank, which keeps no index. The canonical name
        comes first, then the aliases; duplicates collapse because equal names
        blind to the same value. Joins the caller's transaction.
        """
        if self.box is None:
            return
        self.conn.execute(
            "DELETE FROM entity_name_index WHERE entity_id = ?", (entity_id,)
        )
        for name in [canonical, *aliases]:
            normalized = _normalize_name(name)
            if not normalized:
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_name_index (entity_id, name_idx)"
                " VALUES (?, ?)",
                (entity_id, self.box.blind(normalized)),
            )
