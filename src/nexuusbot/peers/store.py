"""The peer store: identity, pairing codes, peers, shares, subscriptions.

Trust model, stated honestly. Pairing happens over plain HTTP on the
local network: anyone on the wire can read the pairing exchange, and the
short code that seeds the channel token is typed by a human, so the
channel token gates reads but is not a secret from the LAN. It is not
meant to be: a paired peer may read only the plugin manifests and
bundles this desk explicitly shares, every install still runs the same
shared validator the registry uses before anything executes, and no
peer path can mutate this desk. Verification compares only a hash of
the channel token; the token itself is also kept, so one code pairs
both directions and each desk can read the other's shares, exactly like
any API client credential. The server binds loopback only, so pairing
and sharing work between desks on one machine; a desk on the LAN can be
discovered and seen, but connections to it are refused until the bind
policy changes.

Pairing codes are throttled the simple way: each wrong code submitted
while a code is live burns one of that code's attempts, and the fifth
wrong attempt invalidates the live code outright (generate a fresh one
to try again).

Everything lives in one sqlite database with an injectable clock and
append-friendly rows (created/paired timestamps, upserts that replace
rather than rewrite history).
"""

import hashlib
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable

# The pairing code alphabet: no 0/O or 1/I, so a code read aloud or
# across a desk is never ambiguous. Eight characters of it.
# One pairing at a time is plenty; refusing a second live code keeps the
# page honest (the code shown is the only one that works).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_S = 10 * 60  # a code lives ten minutes, then it is dead
MAX_PAIRING_MISSES = 5  # wrong submissions that invalidate the live code
SCHEMA = """
CREATE TABLE IF NOT EXISTS desk (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  peer_id TEXT NOT NULL,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pairing_codes (
  code TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  used INTEGER NOT NULL DEFAULT 0,
  misses INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS peers (
  peer_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  token TEXT NOT NULL DEFAULT '',
  token_hash TEXT NOT NULL,
  paired_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
  plugin_id TEXT PRIMARY KEY,
  shared INTEGER NOT NULL DEFAULT 0,
  shared_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
  plugin_id TEXT NOT NULL,
  peer_id TEXT NOT NULL,
  seen_version TEXT NOT NULL DEFAULT '',
  seen_sha256 TEXT NOT NULL DEFAULT '',
  installed_version TEXT,
  updated_at REAL NOT NULL,
  PRIMARY KEY (plugin_id, peer_id)
);
CREATE TABLE IF NOT EXISTS peer_state (
  peer_id TEXT PRIMARY KEY,
  last_refresh REAL,
  ok INTEGER NOT NULL DEFAULT 0,
  cause TEXT NOT NULL DEFAULT ''
);
"""


class PeerError(Exception):
    """A named peer-flow refusal: ``code`` is the stable vocabulary."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the stable code beside the message."""
        super().__init__(message)
        self.code = code


def derive_token(code: str) -> str:
    """The channel token both desks derive from the pairing code.

    The code is typed by a human on the other desk, so both sides can
    derive the same token without anything crossing the wire beyond the
    code itself. Deterministic on purpose; secrecy comes from the code.
    """
    return hashlib.sha256(
        f"agentdesk-peer-channel:{code}".encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    """What verification compares against: a hash of the token. (The
    token itself is also kept in the peers row, so pairing works in
    both directions; this hash is the verifying side's copy.)"""
    return hashlib.sha256(
        f"agentdesk-peer-token:{token}".encode("utf-8")).hexdigest()


def _row(cursor: sqlite3.Cursor) -> dict | None:
    """Return the cursor's next row as a column-keyed dict, or None if empty."""
    row = cursor.fetchone()
    if row is None:
        return None
    return {d[0]: row[i] for i, d in enumerate(cursor.description)}


class PeerStore:
    """All peer state for one desk, behind a small locked surface."""

    def __init__(self, conn: sqlite3.Connection,
                 clock: Callable[[], float] = time.time) -> None:
        """Open the store on this connection and migrate it in place.

        The schema is created if absent and the misses column is added to stores
        from earlier builds; existing rows are never rewritten. The clock supplies
        every timestamp written.
        """
        self.conn = conn
        self.clock = clock
        self._lock = threading.Lock()
        with self._lock:
            self.conn.executescript(SCHEMA)
            # Light migration for stores created by earlier builds:
            # append-only means columns are added, never rewritten.
            try:
                self.conn.execute(
                    "ALTER TABLE pairing_codes ADD COLUMN misses"
                    " INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # column already there
            self.conn.commit()

    # -- this desk's identity ------------------------------------------

    def desk(self) -> dict:
        """This desk's stable identity, created once and kept."""
        with self._lock:
            row = _row(self.conn.execute(
                "SELECT peer_id, name FROM desk WHERE id = 1"))
            if row is not None:
                return row
            peer_id = f"desk-{uuid.uuid4().hex[:12]}"
            name = _default_desk_name()
            self.conn.execute(
                "INSERT INTO desk (id, peer_id, name) VALUES (1, ?, ?)",
                (peer_id, name))
            self.conn.commit()
            return {"peer_id": peer_id, "name": name}

    def set_name(self, name: str) -> None:
        """Rename this desk, creating its identity row first when it has none."""
        with self._lock:
            self.desk()
            self.conn.execute("UPDATE desk SET name = ? WHERE id = 1",
                              (name,))
            self.conn.commit()

    # -- pairing codes ---------------------------------------------------

    def create_pairing_code(self) -> dict:
        """A fresh single-use code, replacing any live one."""
        code = "".join(secrets.choice(CODE_ALPHABET)
                       for _ in range(CODE_LENGTH))
        now = self.clock()
        with self._lock:
            self.conn.execute("DELETE FROM pairing_codes")
            self.conn.execute(
                "INSERT INTO pairing_codes (code, created_at, expires_at)"
                " VALUES (?, ?, ?)", (code, now, now + CODE_TTL_S))
            self.conn.commit()
        return {"code": code, "expires_at": now + CODE_TTL_S}

    def active_pairing_code(self) -> dict | None:
        """The one live unused code, if any: what the peers page shows."""
        with self._lock:
            row = _row(self.conn.execute(
                "SELECT code, expires_at FROM pairing_codes WHERE used = 0"))
        if row is None:
            return None
        if self.clock() >= row["expires_at"]:
            return None
        return row

    def exchange_pairing_code(self, code: str, *, peer_id: str, name: str,
                              base_url: str) -> dict:
        """Redeem a code: persist the submitting peer, pin the token.

        Named refusals: unknown, expired, already used. The channel
        token is derived from the code, so the submitting desk (which
        typed the code) can compute it too; verification compares only
        its hash, and the token is kept so this desk can read that
        peer's shares in the other direction. A wrong code burns one of
        the live code's attempts; the fifth wrong code invalidates it.
        """
        if not peer_id or not name or not base_url:
            raise PeerError("pairing:bad-request",
                            "peer_id, name and base_url are all required")
        token = derive_token(code)
        with self._lock:
            row = _row(self.conn.execute(
                "SELECT expires_at, used FROM pairing_codes WHERE code = ?",
                (code,)))
            if row is None:
                self._burn_live_code()
                raise PeerError("pairing:unknown-code",
                                "That pairing code does not exist.")
            if self.clock() >= row["expires_at"]:
                raise PeerError("pairing:expired",
                                "That pairing code has expired. Generate a "
                                "fresh one.")
            if row["used"]:
                raise PeerError("pairing:used",
                                "That pairing code was already used. Each "
                                "code pairs one desk once.")
            self.conn.execute(
                "UPDATE pairing_codes SET used = 1 WHERE code = ?", (code,))
            self.conn.execute(
                "INSERT INTO peers (peer_id, name, base_url, token,"
                " token_hash, paired_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(peer_id) DO UPDATE SET name = excluded.name,"
                " base_url = excluded.base_url, token = excluded.token,"
                " token_hash = excluded.token_hash,"
                " paired_at = excluded.paired_at",
                (peer_id, name, base_url, token, hash_token(token),
                 self.clock()))
            self.conn.commit()
        return {"ok": True, "token": token}

    def _burn_live_code(self) -> None:
        """One wrong submission against the live code: count it, and
        invalidate the code outright once the attempts run out. Caller
        holds the lock; the transaction commits with the caller's raise
        path, so the burned attempt survives the refusal."""
        live = _row(self.conn.execute(
            "SELECT code FROM pairing_codes WHERE used = 0"))
        if live is None:
            return
        self.conn.execute(
            "UPDATE pairing_codes SET misses = misses + 1 WHERE code = ?",
            (live["code"],))
        counted = _row(self.conn.execute(
            "SELECT misses FROM pairing_codes WHERE code = ?",
            (live["code"],)))
        spent = counted is not None and counted["misses"] >= MAX_PAIRING_MISSES
        if spent:
            self.conn.execute("DELETE FROM pairing_codes WHERE code = ?",
                              (live["code"],))
        self.conn.commit()

    # -- paired peers ------------------------------------------------------

    def add_peer(self, *, peer_id: str, name: str, base_url: str,
                 token: str) -> dict:
        """Record the other side of a pairing (the desk that typed the
        code). The channel token is kept: this desk must present it to
        read the peer's shares, exactly like any API client credential.
        The verifier's comparison still uses only the hash."""
        with self._lock:
            self.conn.execute(
                "INSERT INTO peers (peer_id, name, base_url, token,"
                " token_hash, paired_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(peer_id) DO UPDATE SET name = excluded.name,"
                " base_url = excluded.base_url, token = excluded.token,"
                " token_hash = excluded.token_hash,"
                " paired_at = excluded.paired_at",
                (peer_id, name, base_url, token, hash_token(token),
                 self.clock()))
            self.conn.commit()
        return self.peer(peer_id)  # type: ignore[return-value]

    def peer(self, peer_id: str) -> dict | None:
        """Return one paired peer by id, or None. The channel token is not in it."""
        with self._lock:
            return _row(self.conn.execute(
                "SELECT peer_id, name, base_url, token_hash, paired_at"
                " FROM peers WHERE peer_id = ?", (peer_id,)))

    def peers(self) -> list[dict]:
        """Return every paired peer, oldest pairing first, without the token."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT peer_id, name, base_url, token_hash, paired_at"
                " FROM peers ORDER BY paired_at").fetchall()
        return [{"peer_id": r[0], "name": r[1], "base_url": r[2],
                 "token_hash": r[3], "paired_at": r[4]} for r in rows]

    def channel_token(self, peer_id: str) -> str | None:
        """The credential this desk presents to that peer, or None. Kept
        out of peer()/peers() rows on purpose: those feed pages."""
        with self._lock:
            row = self.conn.execute(
                "SELECT token FROM peers WHERE peer_id = ?",
                (peer_id,)).fetchone()
        return row[0] if row and row[0] else None

    def token_valid(self, token: str) -> bool:
        """True when the token names some paired peer. Constant-time
        compare against each stored hash, so timing says nothing."""
        if not token:
            return False
        candidate = hash_token(token)
        with self._lock:
            hashes = [row[0] for row in self.conn.execute(
                "SELECT token_hash FROM peers")]
        return any(secrets.compare_digest(candidate, stored)
                   for stored in hashes)

    # -- shares: what this desk publishes ---------------------------------

    def set_shared(self, plugin_id: str, shared: bool) -> None:
        """Record whether a plugin is shared with peers, replacing the last answer."""
        with self._lock:
            self.conn.execute(
                "INSERT INTO shares (plugin_id, shared, shared_at)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(plugin_id) DO UPDATE SET"
                " shared = excluded.shared, shared_at = excluded.shared_at",
                (plugin_id, 1 if shared else 0, self.clock()))
            self.conn.commit()

    def shared_ids(self) -> set[str]:
        """Return the ids of every plugin this desk currently shares."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT plugin_id FROM shares WHERE shared = 1").fetchall()
        return {row[0] for row in rows}

    # -- subscriptions: what this desk follows ----------------------------

    def record_seen(self, plugin_id: str, peer_id: str, version: str,
                    sha256: str) -> None:
        """The publisher's current version and digest, as last seen."""
        with self._lock:
            self.conn.execute(
                "INSERT INTO subscriptions (plugin_id, peer_id, seen_version,"
                " seen_sha256, installed_version, updated_at)"
                " VALUES (?, ?, ?, ?, NULL, ?)"
                " ON CONFLICT(plugin_id, peer_id) DO UPDATE SET"
                " seen_version = excluded.seen_version,"
                " seen_sha256 = excluded.seen_sha256,"
                " updated_at = excluded.updated_at",
                (plugin_id, peer_id, version, sha256, self.clock()))
            self.conn.commit()

    def set_installed(self, plugin_id: str, peer_id: str,
                      version: str) -> None:
        """The version this desk actually runs after an install/update."""
        with self._lock:
            self.conn.execute(
                "UPDATE subscriptions SET installed_version = ?,"
                " updated_at = ? WHERE plugin_id = ? AND peer_id = ?",
                (version, self.clock(), plugin_id, peer_id))
            self.conn.commit()

    def subscriptions(self) -> list[dict]:
        """Return every subscription, ordered by peer id and then plugin id."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT plugin_id, peer_id, seen_version, seen_sha256,"
                " installed_version, updated_at FROM subscriptions"
                " ORDER BY peer_id, plugin_id").fetchall()
        return [{"plugin_id": r[0], "peer_id": r[1], "seen_version": r[2],
                 "seen_sha256": r[3], "installed_version": r[4],
                 "updated_at": r[5]} for r in rows]

    def record_peer_refresh(self, peer_id: str, *, ok: bool,
                            cause: str) -> None:
        """The honest outcome of the last contact with this peer: ok, or
        the plain-language cause it was not (the page shows it, never a
        silent empty list)."""
        with self._lock:
            self.conn.execute(
                "INSERT INTO peer_state (peer_id, last_refresh, ok, cause)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(peer_id) DO UPDATE SET"
                " last_refresh = excluded.last_refresh, ok = excluded.ok,"
                " cause = excluded.cause",
                (peer_id, self.clock(), 1 if ok else 0, cause))
            self.conn.commit()

    def peer_state(self, peer_id: str) -> dict:
        """Return the last refresh outcome recorded for one peer.

        A peer that was never refreshed reports ok False, no timestamp and an empty
        cause, so a page can say so rather than show a blank.
        """
        with self._lock:
            row = _row(self.conn.execute(
                "SELECT peer_id, last_refresh, ok, cause FROM peer_state"
                " WHERE peer_id = ?", (peer_id,)))
        if row is None:
            return {"peer_id": peer_id, "last_refresh": None, "ok": False,
                    "cause": ""}
        return {"peer_id": row["peer_id"], "last_refresh": row["last_refresh"],
                "ok": bool(row["ok"]), "cause": row["cause"]}


def _default_desk_name() -> str:
    """The hostname, so a peer entry says which machine it came from."""
    import socket

    try:
        host = socket.gethostname()
    except OSError:
        host = "this machine"
    return host or "this machine"
