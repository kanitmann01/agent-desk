"""The inbox evaluation loop: decide, spend, batch, queue, return.

Called after a card is added and whenever the inbox is read. The rule
that satisfies both the cap and digest batching: one unnotified card
spends one notification; several unnotified cards together spend ONE
digest notification covering them all. What the budget will not spend
simply keeps waiting, visibly.

Snoozes return here too (the donor approvals module's tick): a waiting
card whose return time has passed comes back to the visible set on the
next evaluation, and `on_snooze_return` hears about it so the return is
logged, never silent.
"""

from collections.abc import Callable
from datetime import datetime

from agentdesk.inbox.budget import decide_budget
from agentdesk.inbox.core import Card
from agentdesk.inbox.store import InboxStore


def evaluate(
    store: InboxStore,
    now: datetime,
    quiet_hours: bool = True,
    cap: int = 3,
    on_snooze_return: Callable[[Card], None] | None = None,
) -> dict:
    """Return due snoozes, then spend the budget on waiting cards,
    digest-first. Returns the tally."""
    for card in store.return_due_snoozes():
        if on_snooze_return is not None:
            on_snooze_return(card)
    unnotified = [c for c in store.waiting() if c.notified_ts is None]
    if not unnotified:
        return {"notified": 0, "queued": 0, "digest": False}
    if decide_budget(now, store.notified_today(now), quiet_hours, cap) != "notify":
        return {"notified": 0, "queued": len(unnotified), "digest": False}
    if len(unnotified) == 1:
        store.mark_notified(unnotified[0].id)
        store.record_notification("card", 1)
        return {"notified": 1, "queued": 0, "digest": False}
    for card in unnotified:
        store.mark_notified(card.id)
    store.record_notification("digest", len(unnotified))
    return {"notified": len(unnotified), "queued": 0, "digest": True}
