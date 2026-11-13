"""The inbox store: cards and the notification ledger, in SQLite.

Cards are never deleted while they mean anything: dismissed cards stay
for thirty days, expired cards stay visible as expired. The notification
ledger is the budget's memory: how many were spent today.
"""

import json
import sqlite3
from collections.abc import Callable

from agentdesk.inbox.budget import new_card_id
from agentdesk.inbox.core import (
    RECOVERY_DAYS,
    STATUS_ACCEPTED,
    STATUS_DISMISSED,
    STATUS_WAITING,
    Card,
    UnknownCard,
)

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
  kind TEXT NOT NULL,
  card_count INTEGER NOT NULL DEFAULT 1
);
"""

_COLUMNS = (
    "id, kind, origin, title, body, action_label, status, created_ts,"
    " window_hours, notified_ts, dismissed_ts, accepted_ts, draft,"
    " snoozed_until, meta"
)


def ensure_schema(conn: sqlite3.Connection) -> None:
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


class InboxStore:
    """Cards in, decisions out; the budget reads the ledger."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float]) -> None:
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    def now_ts(self) -> float:
        """The store's own clock: every payload is judged by it, so cards
        never age by two different clocks."""
        return self.clock()

    # -- writes -----------------------------------------------------------

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

    def dismiss(self, card_id: str) -> Card:
        card = self.get(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET status = ?, dismissed_ts = ? WHERE id = ?",
                (STATUS_DISMISSED, self.clock(), card_id),
            )
        return self.get(card_id)

    def accept(self, card_id: str) -> Card:
        card = self.get(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET status = ?, accepted_ts = ? WHERE id = ?",
                (STATUS_ACCEPTED, self.clock(), card_id),
            )
        return self.get(card_id)

    def edit_draft(self, card_id: str, draft: str) -> Card:
        """Update the card's editable draft. The card keeps waiting; only
        what accepting would apply has changed."""
        self.get(card_id)
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET draft = ? WHERE id = ?", (draft, card_id)
            )
        return self.get(card_id)

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

    def mark_notified(self, card_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET notified_ts = ? WHERE id = ?", (self.clock(), card_id)
            )

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

    def record_notification(self, kind: str, card_count: int = 1) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO notifications (ts, kind, card_count) VALUES (?, ?, ?)",
                (self.clock(), kind, card_count),
            )

    # -- reads ------------------------------------------------------------

    def get(self, card_id: str) -> Card:
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM cards WHERE id = ?",
            (card_id,),
        ).fetchone()
        if row is None:
            raise UnknownCard(f"no card {card_id}")
        return Card(
            id=row[0], kind=row[1], origin=row[2], title=row[3], body=row[4],
            action_label=row[5], status=row[6], created_ts=row[7],
            window_hours=row[8], notified_ts=row[9], dismissed_ts=row[10],
            accepted_ts=row[11], draft=row[12], snoozed_until=row[13],
            meta=json.loads(row[14]),
        )

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

    def dismissed(self) -> list[Card]:
        return self._by_status(STATUS_DISMISSED)

    def all_cards(self) -> list[Card]:
        """Every card regardless of status, oldest first: the demo clear
        path walks this to find exactly what it seeded."""
        rows = self.conn.execute(
            "SELECT id FROM cards ORDER BY created_ts ASC"
        ).fetchall()
        return [self.get(r[0]) for r in rows]

    def _by_status(self, status: str) -> list[Card]:
        rows = self.conn.execute(
            "SELECT id FROM cards WHERE status = ? ORDER BY created_ts ASC",
            (status,),
        ).fetchall()
        return [self.get(r[0]) for r in rows]

    def notified_today(self, now) -> int:
        """Notifications spent on today's local calendar day."""
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        row = self.conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE ts >= ?",
            (day_start.timestamp(),),
        ).fetchone()
        return int(row[0]) if row else 0
