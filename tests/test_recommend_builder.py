"""The recommendation builder: candidates become waiting inbox cards.

The builder is the only part that touches the inbox and the ledger, so these
tests cover the promises around it: refresh is idempotent, the waiting cap
keeps the soonest deadlines, Not now is permanent even after the card row is
gone, and a deleted or superseded fact withdraws its card.
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agentdesk.inbox.core import STATUS_DISMISSED
from agentdesk.inbox.service import evaluate
from agentdesk.inbox.store import InboxStore
from agentdesk.ledger.store import Ledger
from agentdesk.ledger.undo import undo
from agentdesk.memory.store import MemoryStore
from agentdesk.recommend.builder import MAX_PENDING, WITHDRAWN_ORIGIN, RecommendationBuilder
from agentdesk.server import demo_data
from agentdesk.settings import SettingsStore

NOV_20 = datetime(2026, 11, 20, 9, 0)


class Clock:
    """A settable clock, so one test can cross quiet hours."""

    def __init__(self, moment: datetime) -> None:
        self.ts = moment.timestamp()

    def __call__(self) -> float:
        return self.ts


class Desk:
    """The builder with the four stores it reads, on one in-memory database."""

    def __init__(self, moment: datetime = NOV_20, settings: dict | None = None) -> None:
        self.clock = Clock(moment)
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.memory = MemoryStore(conn, self.clock)
        self.inbox = InboxStore(conn, self.clock)
        self.settings = SettingsStore(conn, self.clock)
        for key, value in (settings or {}).items():
            self.settings.set(key, value)
        self.ledger = Ledger(":memory:", clock=self.clock)
        self.builder = RecommendationBuilder(
            inbox=self.inbox,
            memory=self.memory,
            calendar=None,
            settings=self.settings,
            ledger=self.ledger,
            clock=self.clock,
        )


def _recommendations(cards) -> list[dict]:
    """The recommendation metadata of each card, in card order."""
    return [card.meta["recommendation"] for card in cards]


def test_refresh_idempotent():
    desk = Desk()
    fact = desk.memory.add("Sign the Halvorsen renewal before December 15.", source="page")

    assert desk.builder.refresh() == {"added": 1, "withdrawn": 0}
    assert desk.builder.refresh() == {"added": 0, "withdrawn": 0}

    cards = desk.builder.waiting()
    assert len(cards) == 1
    assert "December 15" in cards[0].title
    assert cards[0].kind == "suggestion"
    assert _recommendations(cards)[0]["cites"] == [fact.id]
    added = [entry for entry in desk.ledger.entries(limit=20) if entry.action == "recommend.added"]
    assert len(added) == 1


def test_cap_five_soonest_first():
    desk = Desk()
    for day in range(1, 8):
        desk.memory.add(f"Renewal number {day} is due December {day}.")

    assert desk.builder.refresh() == {"added": MAX_PENDING, "withdrawn": 0}
    cards = desk.builder.waiting()
    assert len(cards) == MAX_PENDING
    dues = [rec["dueTs"] for rec in _recommendations(cards)]
    assert dues == sorted(dues)
    assert [card.title.split(": ", 1)[1] for card in cards] == [
        f"December {day} (in {day + 10} days)" for day in range(1, 6)
    ]


def test_not_now_is_permanent_even_if_row_deleted():
    desk = Desk()
    desk.memory.add("Sign the renewal before December 15.")
    desk.builder.refresh()
    card = desk.builder.waiting()[0]

    desk.inbox.dismiss(card.id)
    assert desk.builder.refresh() == {"added": 0, "withdrawn": 0}
    assert desk.builder.waiting() == []

    # The demo clear can remove the row outright; the latch still holds.
    desk.inbox.delete(card.id)
    assert desk.builder.refresh() == {"added": 0, "withdrawn": 0}
    assert desk.builder.waiting() == []


def test_withdraw_on_delete_and_supersede():
    desk = Desk()
    deleted = desk.memory.add("Renewal one is due December 1.")
    superseded = desk.memory.add("Renewal two is due December 2.")
    assert desk.builder.refresh() == {"added": 2, "withdrawn": 0}
    by_cite = {
        rec["cites"][0]: card for card, rec in zip(desk.builder.waiting(), _recommendations(desk.builder.waiting()))
    }

    desk.memory.remove_facts([deleted.id])
    assert desk.builder.refresh() == {"added": 0, "withdrawn": 1}
    gone = desk.inbox.get(by_cite[deleted.id].id)
    assert gone.status == STATUS_DISMISSED
    assert gone.origin == WITHDRAWN_ORIGIN
    assert len(desk.builder.waiting()) == 1

    replacement = desk.memory.add("The second renewal moved.")
    desk.memory.mark_superseded(superseded.id, replacement.id)
    assert desk.builder.refresh() == {"added": 0, "withdrawn": 1}
    assert desk.builder.waiting() == []
    withdrawn = [
        entry for entry in desk.ledger.entries(limit=20) if entry.action == "recommend.withdrawn"
    ]
    assert len(withdrawn) == 2
    assert withdrawn[0].undo_kind == "none"


def test_budget_applied():
    desk = Desk(moment=datetime(2026, 11, 20, 22, 0))
    desk.memory.add("Sign the renewal before December 15.")
    desk.builder.refresh()

    tally = evaluate(desk.inbox, datetime(2026, 11, 20, 22, 0), quiet_hours=True, cap=3)
    assert tally["queued"] == 1
    assert desk.inbox.waiting()[0].notified_ts is None

    desk.clock.ts = datetime(2026, 11, 21, 9, 0).timestamp()
    tally = evaluate(desk.inbox, datetime(2026, 11, 21, 9, 0), quiet_hours=True, cap=3)
    assert tally["notified"] == 1
    assert desk.inbox.waiting()[0].notified_ts is not None


def test_sample_flag():
    desk = Desk()
    demo_data.seed_memory(desk.memory)
    desk.memory.add("A page fact due on December 20.", source="page")
    desk.builder.refresh()

    by_title = {card.title: rec for card, rec in zip(
        desk.builder.waiting(), _recommendations(desk.builder.waiting())
    )}
    halvorsen = next(
        (rec for title, rec in by_title.items() if "December 15" in title), None,
    )
    assert halvorsen is not None and halvorsen["sample"] is True
    page = next(rec for title, rec in by_title.items() if "A page fact" in title)
    assert page["sample"] is False


def test_settings_off_stops_creating_but_keeps_cards():
    desk = Desk()
    desk.memory.add("Sign the renewal before December 15.")

    desk.settings.set("recommendations", False)
    assert desk.builder.refresh() == {"added": 0, "withdrawn": 0}
    assert desk.builder.waiting() == []

    desk.settings.set("recommendations", True)
    desk.settings.set("recommend_deadlines", False)
    assert desk.builder.refresh() == {"added": 0, "withdrawn": 0}

    desk.settings.set("recommend_deadlines", True)
    assert desk.builder.refresh()["added"] == 1
    desk.settings.set("recommendations", False)
    assert desk.builder.refresh() == {"added": 0, "withdrawn": 0}
    assert len(desk.builder.waiting()) == 1


def test_ledger_detail_holds_fact_ids_only_and_undo_dismisses():
    desk = Desk()
    fact = desk.memory.add("Sign the Halvorsen renewal before December 15.")
    desk.builder.refresh()

    entry = next(entry for entry in desk.ledger.entries(limit=20) if entry.action == "recommend.added")
    assert entry.actor == "agent"
    assert entry.detail == {"rule": "deadline", "cites": [fact.id]}
    assert entry.undo_kind == "card-added"
    assert entry.undoable
    assert "Halvorsen" not in json.dumps(entry.detail)
    assert "Halvorsen" not in entry.subject and "Halvorsen" not in entry.why

    card = desk.builder.waiting()[0]
    server = SimpleNamespace(inbox=desk.inbox, ledger=desk.ledger)
    undo(server, desk.ledger, entry.id)
    assert desk.inbox.get(card.id).status == STATUS_DISMISSED
