"""The keys store: named model connections in their own sqlite file.

A connection is the label a user types, its provider preset, a base URL
and a keychain reference; the secret itself never lands here, only the
masked hint (first three and last four characters, never the middle).
The inbox store's pattern throughout: the idempotent per-store schema
step, one re-entrant lock serializing every statement, an injectable
clock supplying every timestamp.
"""

import functools
import json
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL,
  base_url TEXT NOT NULL,
  keychain_ref TEXT NOT NULL DEFAULT '',
  masked_key TEXT NOT NULL DEFAULT '',
  headers TEXT NOT NULL DEFAULT '{}',
  is_default INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'unknown',
  last_checked_at REAL,
  last_error TEXT NOT NULL DEFAULT '',
  last_used_at REAL,
  models TEXT NOT NULL DEFAULT '[]',
  models_fetched_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS job_bindings (
  job_key TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL,
  model_id TEXT NOT NULL DEFAULT '',
  updated_at REAL NOT NULL,
  FOREIGN KEY (connection_id) REFERENCES connections (id) ON DELETE CASCADE
);
"""

_COLUMNS = (
    "id, label, provider, base_url, keychain_ref, masked_key, headers,"
    " is_default, enabled, status, last_checked_at, last_error,"
    " last_used_at, models, models_fetched_at, created_at, updated_at"
)


class UnknownConnection(Exception):
    """No connection carries the id (or it is not readable here)."""


@dataclass
class JobBinding:
    """One job's assignment: which connection serves it, with which model.

    The seven jobs (default, assistant, agents, presentations, memory,
    insights, research-web) are the keys this table can carry; the store
    keeps no registry of them, the routes and the resolver do.
    """

    job_key: str
    connection_id: str
    model_id: str = ""
    updated_at: float = 0.0


@dataclass
class Connection:
    """One saved connection, exactly the columns the store holds."""

    id: str
    label: str
    provider: str
    base_url: str
    keychain_ref: str = ""
    masked_key: str = ""
    headers: dict = field(default_factory=dict)
    is_default: bool = False
    enabled: bool = True
    status: str = "unknown"
    last_checked_at: float | None = None
    last_error: str = ""
    last_used_at: float | None = None
    models: list = field(default_factory=list)
    models_fetched_at: float | None = None
    created_at: float = 0.0
    updated_at: float = 0.0


def mask_key(secret: str) -> str:
    """The hint a saved key leaves everywhere except the keychain.

    First three and last four characters when the key is long enough to
    spare the middle; a plain "Set." when it is not, because a short key
    minus its middle is most of the key. Empty answers empty.
    """
    secret = (secret or "").strip()
    if not secret:
        return ""
    if len(secret) < 10:
        return "Set."
    return f"{secret[:3]}...{secret[-4:]}"


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the connections table and commit; safe on every open."""
    conn.executescript(SCHEMA)
    conn.commit()


def _serialized(method):
    """Every read and write holds the store's one lock (the inbox store's
    precedent: the connection is shared by the server's request threads)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        """Run one store method with the store's re-entrant lock held."""
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class KeysStore:
    """Connections in, references out; secrets live in the keychain.
    Thread-safe: every method serializes on one lock (see _serialized)."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float]) -> None:
        """Adopt the connection as the store's only one, and migrate it.

        The lock belongs to this instance; the clock supplies every timestamp the
        store writes.
        """
        self.conn = conn
        self.clock = clock
        self._lock = threading.RLock()
        with self._lock:
            ensure_schema(conn)

    @_serialized
    def add(
        self,
        label: str,
        provider: str,
        base_url: str,
        masked_key: str = "",
        headers: dict | None = None,
        is_default: bool = False,
        connection_id: str | None = None,
    ) -> Connection:
        """Insert one connection and return it as the store now holds it.

        The id is generated unless handed in, and the keychain reference is always
        key/<id>, so the keychain entry is derivable from the row alone. A label
        another connection already has is refused (ValueError): labels are how a
        user tells two keys for the same provider apart, so duplicates cannot
        silently merge.
        """
        connection_id = connection_id or uuid.uuid4().hex
        now = self.clock()
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO connections (id, label, provider, base_url,"
                    " keychain_ref, masked_key, headers, is_default,"
                    " created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (connection_id, label, provider, base_url,
                     f"key/{connection_id}", masked_key,
                     json.dumps(headers or {}, ensure_ascii=False),
                     1 if is_default else 0, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"the label {label!r} is already used by another"
                             " connection") from exc
        if is_default:
            self._clear_other_defaults(connection_id)
        return self.get(connection_id)

    @_serialized
    def get(self, connection_id: str) -> Connection:
        """Read one connection by id; UnknownConnection when there is none."""
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM connections WHERE id = ?",
            (connection_id,),
        ).fetchone()
        if row is None:
            raise UnknownConnection(f"no connection {connection_id}")
        return _as_connection(row)

    @_serialized
    def all(self) -> list[Connection]:
        """Every connection, oldest created first."""
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM connections ORDER BY created_at ASC, id ASC"
        ).fetchall()
        return [_as_connection(row) for row in rows]

    @_serialized
    def update(
        self,
        connection_id: str,
        label: str | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        masked_key: str | None = None,
        headers: dict | None = None,
    ) -> Connection:
        """Change only the named fields; everything else keeps its value.

        updated_at moves to the clock's now; created_at never does. An
        unknown id raises before anything is written, and a label another
        connection owns is refused like a duplicate insert.
        """
        self.get(connection_id)  # unknown ids raise before any write
        stored = {name: value for name, value in (
            ("label", label), ("provider", provider), ("base_url", base_url),
            ("masked_key", masked_key),
            ("headers", json.dumps(headers, ensure_ascii=False)
             if headers is not None else None),
        ) if value is not None}
        if not stored:
            return self.get(connection_id)
        assignments = ", ".join(f"{name} = ?" for name in stored)
        try:
            with self.conn:
                self.conn.execute(
                    f"UPDATE connections SET {assignments}, updated_at = ?"
                    " WHERE id = ?",
                    (*stored.values(), self.clock(), connection_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"the label {label!r} is already used by another"
                             " connection") from exc
        return self.get(connection_id)

    @_serialized
    def clear_key(self, connection_id: str) -> Connection:
        """Empty the masked hint; the keychain entry is the caller's to drop."""
        self.get(connection_id)
        with self.conn:
            self.conn.execute(
                "UPDATE connections SET masked_key = '', updated_at = ?"
                " WHERE id = ?",
                (self.clock(), connection_id),
            )
        return self.get(connection_id)

    @_serialized
    def set_default(self, connection_id: str) -> Connection:
        """Star one connection; any previous default loses the star."""
        self.get(connection_id)
        with self.conn:
            self.conn.execute("UPDATE connections SET is_default = 0")
            self.conn.execute(
                "UPDATE connections SET is_default = 1, updated_at = ?"
                " WHERE id = ?",
                (self.clock(), connection_id),
            )
        return self.get(connection_id)

    @_serialized
    def delete(self, connection_id: str) -> Connection:
        """Remove the row and return it, so the caller can drop its secret.

        The row's job bindings go in the same transaction: the schema's
        cascade, executed here rather than trusted to SQLite's optional
        per-connection foreign-keys pragma, so no binding can outlive its
        connection whatever opened the file.
        """
        connection = self.get(connection_id)
        with self.conn:
            self.conn.execute(
                "DELETE FROM job_bindings WHERE connection_id = ?", (connection_id,))
            self.conn.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        return connection

    # -- job bindings (spec 018 #233) -------------------------------------

    @_serialized
    def bind(self, job_key: str, connection_id: str,
             model_id: str = "") -> JobBinding:
        """Point one job at one connection (and a model), replacing any
        earlier binding the same job held.

        The write is an upsert on the job's primary key; an unknown
        connection raises before anything is written, so a binding can
        never name a row the store does not have.
        """
        self.get(connection_id)  # unknown ids raise before any write
        now = self.clock()
        with self.conn:
            self.conn.execute(
                "INSERT INTO job_bindings (job_key, connection_id, model_id,"
                " updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (job_key) DO UPDATE SET"
                " connection_id = excluded.connection_id,"
                " model_id = excluded.model_id,"
                " updated_at = excluded.updated_at",
                (job_key, connection_id, model_id, now),
            )
        return JobBinding(job_key, connection_id, model_id, now)

    @_serialized
    def bindings(self) -> list[JobBinding]:
        """Every binding, job_key order (the Settings page's job order)."""
        rows = self.conn.execute(
            "SELECT job_key, connection_id, model_id, updated_at"
            " FROM job_bindings ORDER BY job_key ASC"
        ).fetchall()
        return [JobBinding(*row) for row in rows]

    @_serialized
    def binding(self, job_key: str) -> JobBinding | None:
        """One job's binding, or None when the job is unbound."""
        row = self.conn.execute(
            "SELECT job_key, connection_id, model_id, updated_at"
            " FROM job_bindings WHERE job_key = ?",
            (job_key,),
        ).fetchone()
        return JobBinding(*row) if row is not None else None

    @_serialized
    def unbind(self, job_key: str) -> bool:
        """Remove one job's binding; False when there was none to remove."""
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM job_bindings WHERE job_key = ?", (job_key,))
        return cursor.rowcount > 0

    @_serialized
    def bound_jobs(self, connection_id: str) -> list[str]:
        """The job keys bound to one connection, job_key order; the delete
        warning's content, so nothing goes quiet without its jobs named."""
        rows = self.conn.execute(
            "SELECT job_key FROM job_bindings WHERE connection_id = ?"
            " ORDER BY job_key ASC",
            (connection_id,),
        ).fetchall()
        return [row[0] for row in rows]

    @_serialized
    def record_check(self, connection_id: str, status: str | None,
                     note: str = "") -> Connection:
        """Stamp one health check's outcome onto the row.

        last_checked_at and last_error always take the check's time and
        note (the note is the inline cause the badge shows, empty when
        all is clear). status is written only when it is not None: a
        transient failure or a missing listing keeps the last status, so
        one bad minute never flips a badge a real answer set.
        """
        self.get(connection_id)  # unknown ids raise before any write
        now = self.clock()
        if status is None:
            with self.conn:
                self.conn.execute(
                    "UPDATE connections SET last_checked_at = ?,"
                    " last_error = ?, updated_at = ? WHERE id = ?",
                    (now, note, now, connection_id),
                )
        else:
            with self.conn:
                self.conn.execute(
                    "UPDATE connections SET status = ?, last_checked_at = ?,"
                    " last_error = ?, updated_at = ? WHERE id = ?",
                    (status, now, note, now, connection_id),
                )
        return self.get(connection_id)

    @_serialized
    def record_use(self, connection_id: str) -> Connection:
        """Stamp last_used_at: live traffic served a call on this row.

        The one write the call path makes (spec 018's live-traffic leg);
        tests and the Test button never touch it.
        """
        self.get(connection_id)
        now = self.clock()
        with self.conn:
            self.conn.execute(
                "UPDATE connections SET last_used_at = ?, updated_at = ?"
                " WHERE id = ?",
                (now, now, connection_id),
            )
        return self.get(connection_id)

    @_serialized
    def set_models(self, connection_id: str, models: list) -> Connection:
        """Cache one discovered model list with its fetched-at time."""
        self.get(connection_id)
        now = self.clock()
        with self.conn:
            self.conn.execute(
                "UPDATE connections SET models = ?, models_fetched_at = ?,"
                " updated_at = ? WHERE id = ?",
                (json.dumps(list(models), ensure_ascii=False), now, now,
                 connection_id),
            )
        return self.get(connection_id)

    def _clear_other_defaults(self, connection_id: str) -> None:
        """The default star belongs to one connection at a time."""
        with self.conn:
            self.conn.execute(
                "UPDATE connections SET is_default = 0 WHERE id != ?",
                (connection_id,),
            )


def _as_connection(row: tuple) -> Connection:
    """One stored row as a Connection; positions are fixed by _COLUMNS."""
    return Connection(
        id=row[0], label=row[1], provider=row[2], base_url=row[3],
        keychain_ref=row[4], masked_key=row[5], headers=json.loads(row[6]),
        is_default=bool(row[7]), enabled=bool(row[8]), status=row[9],
        last_checked_at=row[10], last_error=row[11], last_used_at=row[12],
        models=json.loads(row[13]), models_fetched_at=row[14],
        created_at=row[15], updated_at=row[16],
    )
