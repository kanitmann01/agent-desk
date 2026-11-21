"""The interruption budget: notifications are spent, never sprayed.

Three rules, from the spec: quiet hours 18:00-08:00 local (the manager is
not working), at most three proactive notifications per calendar day,
and digest batching when several queued cards become eligible together.
A card that may not notify simply waits in the inbox; nothing is lost.
"""

import secrets
from datetime import datetime

QUIET_START = 18  # 18:00 local
QUIET_END = 8     # 08:00 local
DAILY_CAP = 3


def decide_budget(now: datetime, notified_today: int, quiet_hours: bool = True, cap: int = DAILY_CAP) -> str:
    """'notify' or 'queue' for a card becoming eligible at `now`.

    Quiet hours and the cap come from settings, so what the page shows is
    what the inbox enforces; the defaults are the spec's defaults.
    """
    if quiet_hours and (QUIET_START <= now.hour or now.hour < QUIET_END):
        return "queue"
    if notified_today >= cap:
        return "queue"
    return "notify"


def new_card_id() -> str:
    """Fresh random card id; the `card-` prefix keeps it readable in logs and URLs."""
    return "card-" + secrets.token_urlsafe(9)

