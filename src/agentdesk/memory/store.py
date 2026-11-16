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
time dedupe is ticket #92's scope, left out of this one.
"""

import json
import os
import secrets
import sqlite3
from collections.abc import Callable
from pathlib import Path

from agentdesk.memory.core import Fact, UnknownFact
from agentdesk.memory.crypto import (
    KEY_FILE_NAME,
    CryptoBox,
    MemoryEncryptedError,
    check_marker,
    load_key,
    make_marker,
)
from agentdesk.memory.extract import ENTITY_TYPES
from agentdesk.memory.hybrid import EntityLink, normalize_name, rank_hybrid
from agentdesk.memory.resolve import (
    EntityRepo,
    EntityRef,
    Mention,
    StoredEntity,
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

CREATE TABLE IF NOT EXISTS entity_name_index (
  entity_id INTEGER NOT NULL REFERENCES entities(id),
  name_idx TEXT NOT NULL,
  UNIQUE (entity_id, name_idx)
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


def _normalize_fact_text(text: str) -> str:
    """The donor's normalizeFactText: trim, collapse internal whitespace
    runs to single spaces, lowercase. Punctuation stays, so this is an
    exact-text match, not a semantic comparison."""
    return " ".join(text.split()).lower()


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
    tie); the copies are deleted. A v1 database has no edges and no
    occurrence or embedding backfill to move onto the keeper (edges
    arrive with v2 and no v1 fact ever gained the rest), so a plain
    DELETE is the whole merge, unlike the donor's mention-moving dance.
    Groups whose normalized text is empty are skipped: blank rows are
    not duplicates of each other. Only ever runs on a plaintext bank:
    the migration and the conversion both happen before any sealing.
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


def _prune_orphan_observations(conn: sqlite3.Connection) -> None:
    """The donor's pruneOrphanObservations (single bank): delete the
    citations whose fact is gone, then the observations left with zero
    citations. Runs before the conversion so nothing sealed is orphaned
    by it afterwards."""
    with conn:
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


class MemoryStore:
    """Facts in, recall out; the ranking lives in the pure service.

    With `key` the store binds at open (see the module docstring): a
    sealed store encrypts every text-bearing write and refuses any read
    that lacks ciphertext; a locked store (a marker without a usable
    key, a wrong key, a key on a populated plaintext bank) keeps its
    plain-language cause in locked_cause and refuses every operation
    with that cause, surfacing it on the memory page instead of silently
    reading or writing plaintext.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], float],
        key: bytes | None = None,
        key_path=None,
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.key_path = Path(key_path) if key_path is not None else None
        self.locked_cause: str | None = None
        self._box: CryptoBox | None = None
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
        before the database would refuse the row. Sealed: the plaintext
        column is blanked and the ciphertext plus blind index land in
        the same transaction, bound to the row id the insert returns."""
        self._guard()
        if kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, not {kind!r}")
        if occurrence_ts is not None and not isinstance(occurrence_ts, (int, float)):
            raise ValueError("occurrence_ts must be a number or None")
        text = text.strip()
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO facts (text, source, created_ts, kind, occurrence_ts,"
                " source_id) VALUES (?, ?, ?, ?, ?, ?)",
                (self._plain(text), source, self.clock(), kind, occurrence_ts, source_id),
            )
            fact_id = int(cursor.lastrowid)
            self._seal_fact_text(fact_id, text)
        return self.get(fact_id)

    def edit(self, fact_id: int, text: str) -> Fact:
        """Replace the text; source and created_ts stay (provenance and
        the recall tie-break are not the editor's to change). Sealed:
        the same row id rebinds the new ciphertext."""
        self._guard()
        self.get(fact_id)
        text = text.strip()
        with self.conn:
            self.conn.execute(
                "UPDATE facts SET text = ? WHERE id = ?",
                (self._plain(text), fact_id),
            )
            self._seal_fact_text(fact_id, text)
        return self.get(fact_id)

    def delete(self, fact_id: int) -> None:
        self._guard()
        self.get(fact_id)
        with self.conn:
            self.conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))

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

    # -- encryption action (ticket #94) -----------------------------------

    def plain_field_counts(self) -> dict[str, int]:
        """The dry-run counts: values per table that the conversion
        would seal. A sealed or locked bank has no plain fields to
        count, so it refuses."""
        self._guard()
        if self._box is not None:
            raise MemoryEncryptedError("The memory database is already encrypted.")
        return _plain_field_counts(self.conn)

    def encrypt_all(self, key: bytes | None = None, dry_run: bool = False) -> dict:
        """The one-action conversion (the donor's encryptBank).

        Dedupes identical facts and prunes orphan citations and
        observations first, then seals sources, entities (rebuilding the
        name index), facts and observations and writes the marker in ONE
        transaction; the key file is ensured before that transaction so
        a crash never orphans an encrypted database without a key; the
        commit is followed by wal_checkpoint(TRUNCATE) and VACUUM. A
        dry run only counts. An already-sealed bank refuses (the page
        says so). Any failure inside the transaction rolls back to a
        valid plaintext bank.
        """
        self._guard()
        if self._box is not None:
            raise MemoryEncryptedError("The memory database is already encrypted.")
        if dry_run:
            fields = sum(_plain_field_counts(self.conn).values())
            return {"dry_run": True, "fields": fields}
        if key is None and self.key_path is None:
            raise ValueError(
                "memory encryption needs a key: key bytes or a key file path"
            )
        if key is None:
            # Created before the transaction (see ensure_key_file).
            key = ensure_key_file(self.key_path)
        else:
            key = load_key(key)
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
        rows = self.conn.execute("SELECT id, text FROM facts").fetchall()
        for row_id, text in rows:
            self.conn.execute(
                "UPDATE facts SET text = '', text_enc = ?, text_idx = ?"
                " WHERE id = ?",
                (
                    box.seal(text, "facts", "text", row_id),
                    box.blind(_normalize_fact_text(text)),
                    row_id,
                ),
            )

    def _encrypt_observations(self, box: CryptoBox) -> None:
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
                    box.blind(_normalize_fact_text(text)),
                    row_id,
                ),
            )

    def _write_marker(self, key: bytes) -> None:
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
        if self._box is None:
            return
        self.conn.execute(
            "UPDATE facts SET text_enc = ?, text_idx = ? WHERE id = ?",
            (
                self._box.seal(text, "facts", "text", fact_id),
                self._box.blind(_normalize_fact_text(text)),
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
        return _EntityRepo(self.conn, self.clock, self._box)

    # -- reads ------------------------------------------------------------

    def get(self, fact_id: int) -> Fact:
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

    def _fact_from_row(self, row) -> Fact:
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
        personal scale)."""
        self._guard()
        return rank_hybrid(query, self.all(), self._entity_links(), now=self.clock())

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


def _normalize_name(name: str) -> str:
    """The hybrid ranker's normalize_name, the one normalizer that
    serves recall and resolution alike."""
    return normalize_name(name)


class _EntityRepo(EntityRepo):
    """The resolution seam over the store's connection: entities load in
    id order (the donor's insertion order) and every write runs inside
    the transaction resolve_and_link opened, so a batch is all or
    nothing. Sealed: names load through decryption, writes blank the
    plaintext columns and maintain the entity_name_index blind rows."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float],
                 box: CryptoBox | None = None) -> None:
        self.conn = conn
        self.clock = clock
        self.box = box

    def load(self) -> list[StoredEntity]:
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
