"""Reopening a dismissed card for Undo (ticket #191).

The user's own restore keeps the 30-day recovery window; a dismissal the
desk made by itself must stay undoable however long it sat, so
InboxStore.reopen skips that window. The clock is frozen and moved by hand.
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.inbox.core import RECOVERY_DAYS, STATUS_WAITING, UnknownCard
from agentdesk.inbox.store import InboxStore

MORNING = datetime(2026, 11, 11, 9, 0, 0).astimezone()


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(clock) -> InboxStore:
    return InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)


def test_reopen_skips_the_30_day_recovery_window() -> None:
    clock = FakeClock(MORNING)
    inbox = _store(clock)

    # The user's own restore still refuses after 30 days, and prunes the row.
    user_card = inbox.add("suggestion", "excel", "Old card")
    inbox.dismiss(user_card.id)
    clock.advance(86400 * (RECOVERY_DAYS + 1))
    with pytest.raises(UnknownCard):
        inbox.restore(user_card.id)
    with pytest.raises(UnknownCard):
        inbox.get(user_card.id)

    # An agent dismissal stays undoable however long it sat: reopen ignores
    # the window and brings the card back as waiting, with no dismissal stamp.
    agent_card = inbox.add("suggestion", "excel", "Agent card")
    inbox.dismiss(agent_card.id)
    clock.advance(86400 * (RECOVERY_DAYS + 1))
    reopened = inbox.reopen(agent_card.id)
    assert reopened.status == STATUS_WAITING
    assert reopened.dismissed_ts is None


def test_the_dismissed_shelf_purges_past_the_retention_window() -> None:
    # The shelf lists what dismissed() returns, so a card past its 30 days
    # is pruned at that read instead of sitting there with a restore button
    # that answers gone.
    clock = FakeClock(MORNING)
    inbox = _store(clock)
    card = inbox.add("suggestion", "excel", "Old card")
    inbox.dismiss(card.id)
    clock.advance(86400 * RECOVERY_DAYS)
    # Exactly 30 days is still inside the window, the same side restore uses.
    assert [c.id for c in inbox.dismissed()] == [card.id]
    clock.advance(86400)
    assert inbox.dismissed() == []
    with pytest.raises(UnknownCard):
        inbox.get(card.id)  # pruned, not merely hidden
