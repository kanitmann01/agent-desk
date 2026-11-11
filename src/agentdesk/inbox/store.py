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
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  kind TEXT NOT NULL,
  card_count INTEGER NOT NULL DEFAULT 1
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
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
        )
        with self.conn:
            self.conn.execute(
                "INSERT INTO cards (id, kind, origin, title, body, action_label, status,"
                " created_ts, window_hours, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (card.id, card.kind, card.origin, card.title, card.body,
                 card.action_label, card.status, card.created_ts,
                 card.window_hours, json.dumps(card.meta, ensure_ascii=False)),
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

    def record_notification(self, kind: str, card_count: int = 1) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO notifications (ts, kind, card_count) VALUES (?, ?, ?)",
                (self.clock(), kind, card_count),
            )

    # -- reads ------------------------------------------------------------

    def get(self, card_id: str) -> Card:
        row = self.conn.execute(
            "SELECT id, kind, origin, title, body, action_label, status, created_ts,"
            " window_hours, notified_ts, dismissed_ts, accepted_ts, meta"
            " FROM cards WHERE id = ?",
            (card_id,),
        ).fetchone()
        if row is None:
            raise UnknownCard(f"no card {card_id}")
        return Card(
            id=row[0], kind=row[1], origin=row[2], title=row[3], body=row[4],
            action_label=row[5], status=row[6], created_ts=row[7],
            window_hours=row[8], notified_ts=row[9], dismissed_ts=row[10],
            accepted_ts=row[11], meta=json.loads(row[12]),
        )

    def waiting(self) -> list[Card]:
        return self._by_status(STATUS_WAITING)

    def dismissed(self) -> list[Card]:
        return self._by_status(STATUS_DISMISSED)

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
