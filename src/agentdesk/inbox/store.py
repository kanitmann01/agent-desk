"""The inbox store: cards and the notification ledger, in SQLite.

Cards are never deleted while they mean anything: dismissed cards stay
for thirty days, expired cards stay visible as expired. The notification
ledger is the budget's memory: how many were spent today.
"""

import functools
import json
import logging
import sqlite3
import threading
from collections.abc import Callable

from agentdesk.inbox.budget import DAILY_CAP, decide_budget, new_card_id
from agentdesk.inbox.core import (
    CARD_KINDS,
    RECOVERY_DAYS,
    STATUS_ACCEPTED,
    STATUS_DISMISSED,
    STATUS_WAITING,
    Card,
    UnknownCard,
)

LOG = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  origin TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  action_label TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  created_ts REAL NOT NULL,
  window_hours REAL,
  notified_ts REAL,
  dismissed_ts REAL,
  accepted_ts REAL,
  draft TEXT NOT NULL DEFAULT '',
  snoozed_until REAL,
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  kind TEXT NOT NULL
);
"""

_COLUMNS = (
    "id, kind, origin, title, body, action_label, status, created_ts,"
    " window_hours, notified_ts, dismissed_ts, accepted_ts, draft,"
    " snoozed_until, meta"
)
_COLUMN_NAMES = tuple(part.strip() for part in _COLUMNS.split(","))

# Row ids already reported as unreadable, so one unknown kind is one warning
# per process rather than one per inbox read.
_LOGGED_UNREADABLE: set[str] = set()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the tables and add the columns later builds introduced.

    The migrations are append-only: existing rows keep their values and a
    column that is already there is left alone, so a current store comes out
    unchanged. Commits.
    """
    conn.executescript(SCHEMA)
    # Append-only migration for stores created by earlier builds: new
    # columns are added, never rewritten (the audit store's precedent).
    for ddl in (
        "ALTER TABLE cards ADD COLUMN draft TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE cards ADD COLUMN snoozed_until REAL",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # column already there
    conn.commit()


def _serialized(method):
    """Every read and write holds the store's one lock. The connection is
    shared (check_same_thread=False) by the server's request threads and
    the background memory-capture thread; Python's sqlite3 connection
    keeps one implicit transaction, so two threads interleaving on it
    can commit each other's half-done writes or read a row mid-write.
    An RLock, because some methods call others (dismiss reads the card
    back through get)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        """Run one store method with the store's re-entrant lock held."""
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class InboxStore:
    """Cards in, decisions out; the budget reads the ledger. Thread-safe:
    every method serializes on one lock (see _serialized)."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float]) -> None:
        """Adopt the connection as the store's only one, and migrate it.

        The lock belongs to this instance; the clock supplies every timestamp the
        store writes and compares against.
        """
        self.conn = conn
        self.clock = clock
        self._lock = threading.RLock()
        with self._lock:
            ensure_schema(conn)

    def now_ts(self) -> float:
        """The store's own clock: every payload is judged by it, so cards
        never age by two different clocks."""
        return self.clock()

    # -- writes -----------------------------------------------------------

    @_serialized
    def add(
        self,
        kind: str,
        origin: str,
        title: str,
        body: str = "",
        action_label: str = "",
        window_hours: float | None = None,
        meta: dict | None = None,
        card_id: str | None = None,
        draft: str = "",
    ) -> Card:
        """Insert a waiting card and return it as the store now holds it.

        The id is generated unless one is handed in, and created_ts comes from the
        store clock. Nothing is deduplicated here: an identical waiting card is
        inserted too, so suppressing repeats stays the callers' concern.
        """
        card = Card(
            id=card_id or new_card_id(),
            kind=kind,
            origin=origin,
            title=title,
            body=body,
            action_label=action_label,
            status=STATUS_WAITING,
            created_ts=self.clock(),
            window_hours=window_hours,
            meta=meta or {},
            draft=draft,
        )
        with self.conn:
            self.conn.execute(
                "INSERT INTO cards (id, kind, origin, title, body, action_label, status,"
                " created_ts, window_hours, draft, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (card.id, card.kind, card.origin, card.title, card.body,
                 card.action_label, card.status, card.created_ts,
                 card.window_hours, card.draft,
                 json.dumps(card.meta, ensure_ascii=False)),
            )
        return card

    @_serialized
    def dismiss(self, card_id: str) -> Card:
        """Mark a card dismissed and stamp the start of its recovery window.

        The status write is unconditional, so an accepted card becomes dismissed and
        keeps its acceptance stamp. An unknown id raises UnknownCard before anything
        is written.
        """
        card = self.get(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET status = ?, dismissed_ts = ? WHERE id = ?",
                (STATUS_DISMISSED, self.clock(), card_id),
            )
        return self.get(card_id)

    @_serialized
    def accept(self, card_id: str) -> Card:
        """Mark a card accepted and stamp when it was accepted.

        The status write is unconditional, so a dismissed card becomes accepted and
        keeps its dismissal stamp. An unknown id raises UnknownCard before anything
        is written.
        """
        card = self.get(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET status = ?, accepted_ts = ? WHERE id = ?",
                (STATUS_ACCEPTED, self.clock(), card_id),
            )
        return self.get(card_id)

    @_serialized
    def edit_draft(self, card_id: str, draft: str) -> Card:
        """Update the card's editable draft. The card keeps waiting; only
        what accepting would apply has changed."""
        self.get(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET draft = ? WHERE id = ?", (draft, card_id)
            )
        return self.get(card_id)

    @_serialized
    def snooze(self, card_id: str, until_ts: float) -> Card:
        """Hide a waiting card until `until_ts` passes. Not a status: the
        card stays waiting, merely out of sight; evaluation returns it
        when due (the donor's tick)."""
        self.get(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET snoozed_until = ? WHERE id = ?",
                (until_ts, card_id),
            )
        return self.get(card_id)

    @_serialized
    def more_info(self, card_id: str, instruction: str) -> Card:
        """Attach the user's instruction and bring the card back to the
        visible waiting set (a running snooze ends early)."""
        card = self.get(card_id)
        meta = dict(card.meta)
        meta["instruction"] = instruction
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET snoozed_until = NULL, meta = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), card_id),
            )
        return self.get(card_id)

    @_serialized
    def return_due_snoozes(self) -> list[Card]:
        """The donor's tick(): every waiting card whose snooze time has
        passed returns to the visible waiting set. Returns the returned
        cards so the caller can log the return. The clear is conditional
        (only a still-snoozed row counts), so concurrent evaluations
        (/inbox and /widgets/inbox) cannot double-report, and so
        double-log, one return."""
        now = self.clock()
        due = [
            card for card in self._by_status(STATUS_WAITING)
            if card.snoozed_until is not None and card.snoozed_until <= now
        ]
        returned = []
        for card in due:
            with self.conn:
                cleared = self.conn.execute(
                    "UPDATE cards SET snoozed_until = NULL"
                    " WHERE id = ? AND snoozed_until IS NOT NULL",
                    (card.id,),
                )
            if cleared.rowcount:
                returned.append(card)
        return returned

    @_serialized
    def restore(self, card_id: str) -> Card:
        """Bring a dismissed card back. After 30 days it is gone: the row
        is pruned and the error says so, because nothing expires silently,
        including recoverability itself."""
        card = self.get(card_id)
        if card.status != STATUS_DISMISSED:
            raise UnknownCard(f"{card_id} is not dismissed")
        if card.dismissed_for_days(self.clock()) > RECOVERY_DAYS:
            with self.conn:
                self.conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
            raise UnknownCard(f"{card_id}'s 30-day recovery window has passed")
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET status = ?, dismissed_ts = NULL WHERE id = ?",
                (STATUS_WAITING, card_id),
            )
        return self.get(card_id)

    @_serialized
    def reopen(self, card_id: str) -> Card:
        """Bring a dismissed card back for an Undo, with no recovery limit.

        The user's own restore keeps the 30-day window; a change the desk
        made by itself must stay undoable however long it sat, so this
        reopens unconditionally. An unknown id raises UnknownCard before
        anything is written.
        """
        self.get(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET status = ?, dismissed_ts = NULL WHERE id = ?",
                (STATUS_WAITING, card_id),
            )
        return self.get(card_id)

    @_serialized
    def mark_notified(self, card_id: str) -> None:
        """Stamp the card as notified without touching its status.

        Only the API payload reads this stamp; the daily budget counts the
        notification rows instead.
        """
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET notified_ts = ? WHERE id = ?", (self.clock(), card_id)
            )

    @_serialized
    def delete(self, card_id: str) -> None:
        """Remove a card outright, whatever its status.

        Only the demo clear path may call this: a decision keeps its row
        for the 30-day recovery window, but a seeded sample card is
        scaffolding, not a decision, and the switch going off removes it
        honestly rather than shelving it.
        """
        self.get(card_id)  # a missing id is an error, never a silent no-op
        with self.conn:
            self.conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))

    @_serialized
    def record_notification(self, kind: str) -> None:
        """Append one notification to the ledger the daily budget counts."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO notifications (ts, kind) VALUES (?, ?)",
                (self.clock(), kind),
            )

    @_serialized
    def spend_notification(
        self, card_ids: list[str], now, quiet_hours: bool = True, cap: int = DAILY_CAP
    ) -> bool:
        """Decide and spend in one lock: judge quiet hours and the cap at
        the same instant the ledger row is written.

        Reading the ledger and spending in separate lock-scoped calls let
        two concurrent evaluations both pass the cap check; here the
        decision cannot observe anything but a committed spend. Returns
        whether the spend happened; the cards are left unnotified when it
        did not (they keep waiting, visibly).
        """
        if decide_budget(now, self.notified_today(now), quiet_hours, cap) != "notify":
            return False
        for card_id in card_ids:
            self.mark_notified(card_id)
        kind = "digest" if len(card_ids) > 1 else "card"
        self.record_notification(kind)
        return True

    # -- reads ------------------------------------------------------------

    @_serialized
    def get(self, card_id: str) -> Card:
        """Read one card by id, with its meta decoded from the stored JSON.

        Raises UnknownCard when no row carries the id, and when the row's
        kind belongs to a build this one does not know: an unknown card is
        not found here, never a crash.
        """
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM cards WHERE id = ?",
            (card_id,),
        ).fetchone()
        if row is None:
            raise UnknownCard(f"no card {card_id}")
        card = self._readable(row)
        if card is None:
            raise UnknownCard(f"card {card_id} is not readable in this version")
        return card

    def _readable(self, row: tuple) -> Card | None:
        """One row as a card, or None when its kind is unknown.

        A row written by another build is data, not an error: it is skipped
        by every list read and reported once per id per process, so the rest
        of the inbox (and every page under it) stays readable.
        """
        card_id = row[0]
        try:
            return Card(
                id=card_id, kind=row[1], origin=row[2], title=row[3], body=row[4],
                action_label=row[5], status=row[6], created_ts=row[7],
                window_hours=row[8], notified_ts=row[9], dismissed_ts=row[10],
                accepted_ts=row[11], draft=row[12], snoozed_until=row[13],
                meta=json.loads(row[14]),
            )
        except ValueError as exc:
            if card_id not in _LOGGED_UNREADABLE:
                _LOGGED_UNREADABLE.add(card_id)
                LOG.warning("skipping unreadable inbox row %s: %s", card_id, exc)
            return None

    @_serialized
    def unreadable(self) -> list[dict]:
        """Every raw row whose kind this build does not know, oldest first.

        The rows come back exactly as stored, one dict per column, so a
        later build (or the user's own look) can still see what is there
        without this one having to understand it.
        """
        placeholders = ", ".join("?" for _ in CARD_KINDS)
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM cards WHERE kind NOT IN ({placeholders})"
            " ORDER BY created_ts ASC",
            CARD_KINDS,
        ).fetchall()
        return [dict(zip(_COLUMN_NAMES, row)) for row in rows]

    @_serialized
    def waiting(self, include_snoozed: bool = False) -> list[Card]:
        """The visible waiting set: a card snoozed into the future is
        still waiting, but it is not shown until its snooze passes.
        Dedupe callers (briefs, the consolidator) pass include_snoozed so
        a snoozed card still suppresses its own duplicates."""
        if include_snoozed:
            return self._by_status(STATUS_WAITING)
        now = self.clock()
        return [
            card for card in self._by_status(STATUS_WAITING)
            if not card.is_snoozed(now)
        ]

    @_serialized
    def dismissed(self) -> list[Card]:
        """Return every dismissed card still inside its recovery window,
        oldest created first.

        A card past the 30 days is pruned here rather than listed with a
        restore button that would answer gone: the shelf shows only what
        can actually come back.
        """
        now = self.clock()
        cards = self._by_status(STATUS_DISMISSED)
        expired_ids = {
            card.id for card in cards
            if card.dismissed_for_days(now) > RECOVERY_DAYS
        }
        if expired_ids:
            with self.conn:
                self.conn.executemany(
                    "DELETE FROM cards WHERE id = ?", ((i,) for i in expired_ids)
                )
        return [card for card in cards if card.id not in expired_ids]

    @_serialized
    def all_cards(self) -> list[Card]:
        """Every card regardless of status, oldest first: the demo clear
        path walks this to find exactly what it seeded."""
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM cards ORDER BY created_ts ASC"
        ).fetchall()
        return [card for card in (self._readable(row) for row in rows) if card]

    @_serialized
    def _by_status(self, status: str) -> list[Card]:
        """Return every card in one status, ordered by creation time, oldest first."""
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM cards WHERE status = ? ORDER BY created_ts ASC",
            (status,),
        ).fetchall()
        return [card for card in (self._readable(row) for row in rows) if card]

    @_serialized
    def notified_today(self, now) -> int:
        """Notifications spent on today's local calendar day."""
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        row = self.conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE ts >= ?",
            (day_start.timestamp(),),
        ).fetchone()
        return int(row[0]) if row else 0
