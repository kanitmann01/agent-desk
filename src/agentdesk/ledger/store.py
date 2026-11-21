"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, tools/skill_ledger.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The action ledger: every change the desk makes by itself, undoably.

Hermes kept a JSONL ledger plus a blob folder; this keeps the same ideas
(content-addressed captures, capture-before, bounded size, blob GC and
fail-closed rollback) over the SQLite tables the spec fixes. Recording is
cheap and never blocks the action, with one exception: a change that
promises Undo also promises the before state is on disk, so when that
capture cannot be written the action does not run.
"""

import functools
import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger("agentdesk.ledger")


class LedgerError(Exception):
    """The ledger refused an operation and nothing changed.

    Raised when a capture cannot be stored, when a capture cannot be read
    back, and when an Undo cannot be made fail-safe. Callers treat it as a
    409 with the message as the plain sentence shown to the user.
    """

# The subjects whose captures carry private text (memory facts, the learned
# profile, inbox bodies). When the memory database is sealed, these are the
# captures stored as CryptoBox envelopes (spec §10).
SEALED_PREFIXES = ("memory", "learned", "inbox")

# The cap's low-water mark: trimming brings the ledger down to 80% of the
# cap, so a burst of records does not trim on every single write.
TRIM_LOW_WATER = 0.8

# How long an unreferenced capture is kept before it is collected. A capture
# written moments before a crash may not have its entry row yet; the grace
# keeps it from being swept mid-write.
BLOB_GC_GRACE_SECS = 60 * 60

# The approximate bytes one entry row costs on disk. The exact page size is
# an implementation detail; counting a flat allowance keeps size maintenance
# independent of SQLite's internals, which is what the cap promises.
ENTRY_ROW_BYTES = 256

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id TEXT PRIMARY KEY,
  ts REAL NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  subject TEXT NOT NULL,
  why TEXT NOT NULL,
  undo_kind TEXT NOT NULL,
  before_sha TEXT,
  after_sha TEXT,
  detail TEXT NOT NULL DEFAULT '{}',
  undoes TEXT,
  undone_by TEXT
);
CREATE INDEX IF NOT EXISTS entries_subject ON entries(subject);
CREATE TABLE IF NOT EXISTS blobs (
  sha TEXT PRIMARY KEY,
  ts REAL NOT NULL,
  data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS latches (
  key TEXT PRIMARY KEY,
  ts REAL NOT NULL,
  value TEXT NOT NULL DEFAULT ''
);
"""

_COLUMNS = (
    "id, ts, actor, action, subject, why, undo_kind, before_sha, after_sha,"
    " detail, undoes, undone_by"
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the ledger's tables and index; commits. Additive only, so an
    existing data folder keeps every row it already has."""
    conn.executescript(SCHEMA)
    conn.commit()


def _serialized(method):
    """Every read and write holds the ledger's one lock. The connection is
    shared by the server's request threads (check_same_thread=False) and
    Python's sqlite3 connection keeps one implicit transaction, so two
    threads interleaving could commit each other's half-done writes. An
    RLock, because record() calls the blob and maintenance helpers."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        """Run one ledger method with the ledger's re-entrant lock held."""
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass(frozen=True)
class Entry:
    """One recorded change, exactly as a reader needs it: who, what, why,
    where the before and after captures are, and whether Undo can still
    put the before state back."""

    id: str
    ts: float
    actor: str
    action: str
    subject: str
    why: str
    undo_kind: str
    before_sha: str | None = None
    after_sha: str | None = None
    detail: dict = field(default_factory=dict)
    undoes: str | None = None
    undone_by: str | None = None

    @property
    def undoable(self) -> bool:
        """Whether Undo may act on this entry: a known reverse, and no later
        entry has undone it already (one undo per entry; redo by undoing
        the undo)."""
        return self.undo_kind != "none" and self.undone_by is None


def _entry_from_row(row: sqlite3.Row) -> Entry:
    """One row back into the dataclass; the stored detail is JSON."""
    try:
        detail = json.loads(row["detail"] or "{}")
    except ValueError:
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    return Entry(
        id=row["id"],
        ts=float(row["ts"]),
        actor=row["actor"],
        action=row["action"],
        subject=row["subject"],
        why=row["why"],
        undo_kind=row["undo_kind"],
        before_sha=row["before_sha"],
        after_sha=row["after_sha"],
        detail=detail,
        undoes=row["undoes"],
        undone_by=row["undone_by"],
    )


class Ledger:
    """The append-only change log with its captures. Thread-safe: every
    method serializes on one lock (see _serialized)."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
        seal: Callable[[bytes], bytes] | None = None,
        unseal: Callable[[bytes], bytes] | None = None,
        cap_bytes: int = 20 * 2**20,
        blob_cap: int = 2 * 2**20,
    ) -> None:
        """Open (or create) the database at path and adopt the injected
        clock and crypto pair.

        The seal function turns private captures into envelopes at write
        time; the unseal function turns them back. Both are optional: when
        memory is not sealed the ledger stores plaintext, and a ledger
        opened without a key still reads everything that was never sealed.
        """
        self.path = path
        self.cap_bytes = cap_bytes
        self.blob_cap = blob_cap
        self.clock = clock
        self._seal = seal
        self._unseal = unseal
        self._lock = threading.RLock()
        target = ":memory:" if str(path) == ":memory:" else str(path)
        self.conn = sqlite3.connect(target, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            ensure_schema(self.conn)

    # -- blobs ------------------------------------------------------------

    def _store_blob(self, data: bytes, *, sealed: bool) -> str:
        """Store one capture under its plaintext sha and return the sha.

        The sha is over the plaintext, so identical states share one row and
        a reader can ask for the state it knows. The stored bytes are the
        envelope for a private subject when a seal function was given.
        """
        payload = bytes(data)
        if len(payload) > self.blob_cap:
            raise LedgerError(
                f"That change is larger than {self.blob_cap} bytes, so it cannot be recorded."
            )
        sha = hashlib.sha256(payload).hexdigest()
        stored = self._seal(payload) if sealed and self._seal is not None else payload
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs (sha, ts, data) VALUES (?, ?, ?)",
                (sha, self.clock(), sqlite3.Binary(stored)),
            )
        return sha

    @_serialized
    def put_blob(self, data: bytes) -> str:
        """Store one capture and return its sha; over the blob cap raises
        LedgerError before anything is written."""
        return self._store_blob(data, sealed=False)

    @_serialized
    def get_blob(self, sha: str) -> bytes:
        """Read a capture back, opening the envelope when it has one.

        A capture is stored plaintext unless its subject was private and the
        ledger had a seal function; such an envelope needs the matching
        unseal function, and without one it cannot be opened (it is never
        silently returned as ciphertext under a plaintext promise).
        """
        row = self.conn.execute("SELECT data FROM blobs WHERE sha = ?", (sha,)).fetchone()
        if row is None:
            raise LedgerError("That capture is not in the ledger.")
        data = bytes(row["data"])
        if self._unseal is None:
            return data
        try:
            return bytes(self._unseal(data))
        except Exception:
            # Written before the memory database was sealed, so there is no
            # envelope to open: the stored bytes are the state itself.
            # An envelope that will not open is a failure, not plaintext.
            if data[:1] == b"\x01":
                raise LedgerError("That capture could not be opened.") from None
            return data

    # -- entries ----------------------------------------------------------

    @_serialized
    def record(
        self,
        *,
        actor: str,
        action: str,
        subject: str,
        why: str,
        undo_kind: str = "none",
        before: bytes | None = None,
        after: bytes | None = None,
        detail: dict | None = None,
        undoes: str | None = None,
    ) -> Entry:
        """Append one entry and its captures, and return it as stored.

        Recording never blocks the action it describes: a capture that cannot
        be written is dropped and the entry is still appended. The exception
        is a change that promises Undo (undo_kind is not "none"): without the
        before capture the promise is empty, so the failure is raised and the
        caller does not run the action.
        """
        undoable_change = undo_kind != "none"
        sealed = subject.startswith(SEALED_PREFIXES)
        # Only the before state can block: it is the promise Undo makes.
        # A lost after capture costs the redo trail, not the action.
        before_sha = self._capture(before, sealed=sealed, required=undoable_change)
        after_sha = self._capture(after, sealed=sealed, required=False)
        entry = Entry(
            id=uuid.uuid4().hex[:16],
            ts=float(self.clock()),
            actor=actor,
            action=action,
            subject=subject,
            why=why,
            undo_kind=undo_kind,
            before_sha=before_sha,
            after_sha=after_sha,
            detail=dict(detail or {}),
            undoes=undoes,
            undone_by=None,
        )
        with self.conn:
            self.conn.execute(
                f"INSERT INTO entries ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.ts,
                    entry.actor,
                    entry.action,
                    entry.subject,
                    entry.why,
                    entry.undo_kind,
                    entry.before_sha,
                    entry.after_sha,
                    json.dumps(entry.detail, ensure_ascii=False),
                    entry.undoes,
                    entry.undone_by,
                ),
            )
            if entry.undoes is not None:
                # An entry that undoes another is that undo: stamping the
                # original in the same transaction makes "one undo per
                # entry" true even across a crash.
                updated = self.conn.execute(
                    "UPDATE entries SET undone_by = ? WHERE id = ? AND undone_by IS NULL",
                    (entry.id, entry.undoes),
                )
                if updated.rowcount == 0:
                    raise LedgerError("That change was already undone.")
        self._maintain_size()
        return entry

    def _capture(self, data: bytes | None, *, sealed: bool, required: bool) -> str | None:
        """Store one side of a change; a dropped capture is a logged miss,
        unless the entry cannot keep its Undo promise without it."""
        if data is None:
            return None
        try:
            return self._store_blob(data, sealed=sealed)
        except LedgerError:
            if required:
                raise
            LOG.warning("ledger capture dropped: %s bytes no longer fit", len(data))
            return None

    @_serialized
    def entries(self, limit: int = 50) -> list[Entry]:
        """The most recent entries, newest first."""
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM entries ORDER BY rowid DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [_entry_from_row(row) for row in rows]

    @_serialized
    def get(self, entry_id: str) -> Entry | None:
        """One entry by id, or None when the ledger never held it."""
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return _entry_from_row(row) if row is not None else None

    @_serialized
    def mark_undone(self, entry_id: str, by: str) -> None:
        """Stamp the id of the entry that undid this one. One undo per
        entry, so the first stamp is the one that counts."""
        with self.conn:
            self.conn.execute(
                "UPDATE entries SET undone_by = ? WHERE id = ? AND undone_by IS NULL",
                (by, entry_id),
            )

    # -- latches ----------------------------------------------------------

    @_serialized
    def latch(self, key: str, value: str = "") -> None:
        """Remember that a one-time action has happened, so it never repeats.
        Re-latching the same key updates the value and the timestamp."""
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO latches (key, ts, value) VALUES (?, ?, ?)",
                (key, self.clock(), value),
            )

    @_serialized
    def latched(self, key: str) -> bool:
        """Whether the key was ever latched."""
        return self.latch_value(key) is not None

    @_serialized
    def latch_value(self, key: str) -> str | None:
        """The value stored with the latch, or None when it was never set."""
        row = self.conn.execute("SELECT value FROM latches WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

    @_serialized
    def unlatch(self, key: str) -> None:
        """Forget a latch, e.g. when the condition it marked clears."""
        with self.conn:
            self.conn.execute("DELETE FROM latches WHERE key = ?", (key,))

    # -- size maintenance -------------------------------------------------

    def _size(self) -> int:
        """Blob bytes plus a flat per-entry allowance."""
        blob_bytes = self.conn.execute(
            "SELECT COALESCE(SUM(LENGTH(data)), 0) FROM blobs"
        ).fetchone()[0]
        count = self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        return int(blob_bytes) + int(count) * ENTRY_ROW_BYTES

    def _maintain_size(self) -> None:
        """Keep the ledger bounded: over the cap, drop the oldest entries
        down to the low-water mark; then collect captures nothing refers
        to any more, once they are older than the grace window.

        The newest entry always survives, even alone over the cap: it is
        the change the reader is about to be shown.
        """
        if self._size() > self.cap_bytes:
            low_water = int(self.cap_bytes * TRIM_LOW_WATER)
            while self._size() > low_water:
                count = self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                if count <= 1:
                    break
                with self.conn:
                    row = self.conn.execute(
                        "SELECT id, before_sha, after_sha FROM entries"
                        " ORDER BY rowid ASC LIMIT 1"
                    ).fetchone()
                    self.conn.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
                    for sha in (row["before_sha"], row["after_sha"]):
                        if not sha:
                            continue
                        still = self.conn.execute(
                            "SELECT 1 FROM entries WHERE before_sha = ? OR after_sha = ?",
                            (sha, sha),
                        ).fetchone()
                        if still is None:
                            self.conn.execute("DELETE FROM blobs WHERE sha = ?", (sha,))
        self._gc_blobs()

    def _gc_blobs(self) -> None:
        """Delete unreferenced captures older than the grace window; a
        capture a record is mid-way through writing is never collected."""
        cutoff = self.clock() - BLOB_GC_GRACE_SECS
        with self.conn:
            self.conn.execute(
                "DELETE FROM blobs WHERE ts < ? AND NOT EXISTS ("
                " SELECT 1 FROM entries WHERE entries.before_sha = blobs.sha"
                " OR entries.after_sha = blobs.sha)",
                (cutoff,),
            )

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        """Close the database. Safe to call twice (server shutdown and a
        test fixture both do)."""
        with self._lock:
            if self.conn is None:
                return
            self.conn.close()
            self.conn = None
