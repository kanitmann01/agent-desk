"""The deadline rule: a date saved in a fact becomes a recommendation.

A rule is a pure function: facts in, candidate rows out. The date grammar is
the same one recall parses with, imported from memory/hybrid.py rather than
copied, so a date the desk can recall is a date it can recommend from.
Resolution is forward: a bare month and day means the next occurrence on or
after today, because a recommendation is about what is still ahead.
"""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from datetime import timedelta

from agentdesk.memory import hybrid
from agentdesk.server.demo_data import SAMPLE_MEMORY_SOURCE


@dataclass(frozen=True)
class Candidate:
    """One recommendation the rules propose, before the builder stores it.

    cites holds fact ids only; the body carries the quoted fact for the card
    the builder will make, and never leaves the store via the API.
    """

    rule: str
    key: str
    title: str
    why: str
    body: str
    cites: tuple[int, ...]
    href: str
    action_label: str
    due_ts: float | None
    sample: bool


def deadline_candidates(
    facts: list,
    superseded: set[int],
    entity_names: dict[int, str],
    now: datetime,
    horizon_days: int,
) -> list[Candidate]:
    """One candidate per saved fact and resolved day inside the horizon.

    Superseded facts are skipped, entity_names picks the subject when a fact
    is linked to one, and the horizon counts calendar days from now, both
    ends inclusive, so a date saved for today is a candidate.
    """
    today = now.date()
    candidates: list[Candidate] = []
    for fact in facts:
        if fact.id in superseded:
            continue
        subject = _subject(fact, entity_names)
        found: set[date] = set()
        for day in _described_days(fact.text, today):
            days = (day - today).days
            if days < 0 or days > horizon_days or day in found:
                continue
            found.add(day)
            when = _when_phrase(days)
            candidates.append(
                Candidate(
                    rule="deadline",
                    key=f"deadline:{fact.id}:{day.isoformat()}",
                    title=f"{subject}: {calendar.month_name[day.month]} {day.day} {when}",
                    why=_why(days),
                    body=f'"{fact.text}"\nSaved {_saved_on(fact.created_ts)}',
                    cites=(fact.id,),
                    href="/agents",
                    action_label="Open Agents",
                    due_ts=datetime.combine(day, dt_time.min).timestamp(),
                    sample=fact.source == SAMPLE_MEMORY_SOURCE,
                )
            )
    candidates.sort(key=lambda candidate: (candidate.due_ts or 0.0, candidate.key))
    return candidates


def _subject(fact, entity_names: dict[int, str]) -> str:
    """The first linked entity's name, else the fact text cut at 48 characters."""
    name = entity_names.get(fact.id)
    if name:
        return name
    return fact.text.strip()[:48].strip()


def _described_days(text: str, today: date):
    """Every real day the fact's text names, resolved forward from today.

    An explicit year is used as written; a bare month and day rolls to the
    next occurrence on or after today, skipping years where the date does not
    exist (February 29). Patterns fold case the way recall does."""
    text = text.lower()
    for match in hybrid._ISO_DAY.finditer(text):
        yield from _explicit_day(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    for match in hybrid._MONTH_DAY.finditer(text):
        month = hybrid._month_index(match.group(1))
        if month is not None:
            yield from _resolved_day(month + 1, int(match.group(2)), match.group(3), today)
    for match in hybrid._DAY_MONTH.finditer(text):
        month = hybrid._month_index(match.group(2))
        if month is not None:
            yield from _resolved_day(month + 1, int(match.group(1)), match.group(3), today)


def _explicit_day(year: int, month: int, day: int):
    """The written calendar day when it is real, else nothing."""
    try:
        yield date(year, month, day)
    except ValueError:
        return


def _resolved_day(month: int, day: int, explicit_year: str | None, today: date):
    """The written year's day, or the next real occurrence from today on."""
    if explicit_year is not None:
        yield from _explicit_day(int(explicit_year), month, day)
        return
    for offset in range(9):
        try:
            candidate = date(today.year + offset, month, day)
        except ValueError:
            continue
        if candidate >= today:
            yield candidate
            return


def _when_phrase(days: int) -> str:
    """The title's day phrase: today, tomorrow, or the days still ahead."""
    if days == 0:
        return "(today)"
    if days == 1:
        return "(tomorrow)"
    return f"(in {days} days)"


def _why(days: int) -> str:
    """The card's why line, in the desk's voice."""
    if days == 0:
        return "You told the desk this deadline; it is today."
    if days == 1:
        return "You told the desk this deadline; it is tomorrow."
    return f"You told the desk this deadline; it is {days} days away."


def _saved_on(created_ts: float) -> str:
    """The fact's created day as 'Nov 3', which the card body cites."""
    created = datetime.fromtimestamp(created_ts)
    return f"{created.strftime('%b')} {created.day}"
