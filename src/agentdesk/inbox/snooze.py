"""Snooze arithmetic: one hour, or the next local morning.

"Tomorrow" is pinned to 08:00 local, the moment quiet hours end, and it
means the next calendar day (before dawn, tomorrow is still tomorrow).
The morning is computed on the local wall clock and resolved as a naive
timestamp, so the wall hour stays 08:00 across DST transitions: an aware
datetime carries one fixed offset, and adding a day to it can land an
hour off after the clocks change.
"""

from datetime import datetime, timedelta

SNOOZE_1H = "1h"
SNOOZE_TOMORROW = "tomorrow"
SNOOZE_CHOICES = (SNOOZE_1H, SNOOZE_TOMORROW)

# The local hour a "tomorrow" snooze resolves to: the end of quiet hours
# (18:00-08:00 in budget.py), so nothing returns while you sleep.
TOMORROW_HOUR = 8


def snooze_until(now: datetime, choice: str) -> float:
    """The timestamp a snooze choice hides a card until.

    Raises ValueError for any choice the inbox page does not offer: a
    snooze is one hour or the next morning, never a free-form date.
    """
    if choice == SNOOZE_1H:
        return (now + timedelta(hours=1)).timestamp()
    if choice == SNOOZE_TOMORROW:
        # Through a timestamp and back: naive local wall fields, whatever
        # fixed offset the caller's tzinfo carries. Add the day first,
        # then pin the hour, so 08:00 stays 08:00 after spring-forward.
        local = datetime.fromtimestamp(now.timestamp())
        morning = (local + timedelta(days=1)).replace(
            hour=TOMORROW_HOUR, minute=0, second=0, microsecond=0
        )
        return morning.timestamp()
    raise ValueError(f"unknown snooze choice: {choice!r}")
