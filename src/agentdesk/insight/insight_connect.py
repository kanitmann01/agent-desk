"""The connect step (spec 023, ticket 023-1): what a card shows, read
against what the desk already holds.

Plugins bring rows; this module says which of the names in a row the
desk already knows, and what it holds about them, so a card can carry
one honest line: "Also in your desk: Harborlight Freight, 3 things you
told the desk, renewal call today at 14:38." The match is deterministic
and model-free, so it works with no key and cannot invent a
relationship: a name is either here or it is not.

Nothing user-facing names the mechanism. The index is built once per
dashboard read (`insight/context.py`), a sealed or missing memory
contributes no names, and a family that finds no match says nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

# The entity types a line may name: concepts are excluded, the same
# standing rule the meeting rule keeps.
NAME_TYPES = ("org", "person")
# A name whose longest word is under this many letters draws nothing:
# short names match too much, and a card must never claim a link the
# desk cannot defend.
MIN_LONGEST_WORD = 6
# At most three names on one card, in the order the rows name them.
MAX_PER_CARD = 3


@dataclass(frozen=True)
class DeskName:
    """One thing the desk holds: the entity's id, every name it answers
    to, and how many facts stand behind it."""

    entity_id: int
    names: tuple[str, ...]
    fact_count: int
    # The next event's clause ("renewal call today at 14:38") when the
    # agenda names this entity, else "".
    event_clause: str = ""


@dataclass(frozen=True)
class _Span:
    """One whole-word match of a held name in a block of text."""

    start: int
    end: int
    order: int
    entry: DeskName


def _matching_spans(text: str, index: tuple[DeskName, ...], *,
                    limit: int | None = None) -> list[_Span]:
    """The desk names one block of text carries, as spans in text order.

    Every held name is searched as a whole word, case-insensitively.
    Candidates are taken longest first (then earliest, then index order),
    and one overlapping an already taken span is skipped, so where two
    held names share letters the longer name owns that span and a shorter
    name inside it is not also a match. One span per entity survives (its
    earliest taken occurrence), and the result is ordered by where each
    span starts: the order the text names them. `limit` caps the result;
    the agenda's own pass asks for every match."""
    lowered = (text or "").lower()
    if not lowered.strip() or not index:
        return []
    candidates: list[_Span] = []
    for order, entry in enumerate(index):
        for name in entry.names:
            if _longest_word(name) < MIN_LONGEST_WORD:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(name.lower())}(?!\w)")
            for hit in pattern.finditer(lowered):
                candidates.append(_Span(hit.start(), hit.end(), order, entry))
    candidates.sort(key=lambda span: (span.start - span.end, span.start, span.order))
    taken: list[_Span] = []
    for candidate in candidates:
        if any(candidate.start < span.end and candidate.end > span.start
               for span in taken):
            continue
        taken.append(candidate)
    earliest: dict[int, _Span] = {}
    for span in taken:
        current = earliest.get(span.entry.entity_id)
        if current is None or span.start < current.start:
            earliest[span.entry.entity_id] = span
    ordered = sorted(earliest.values(), key=lambda span: (span.start, span.order))
    return ordered[:limit] if limit is not None else ordered


def build_index(entities, agenda: dict | None, now: float) -> tuple[DeskName, ...]:
    """The desk's nameable things, from the memory store's entity list.

    `entities` is whatever `memory.entities()` returned (already [] for a
    missing store). Only org and person entities enter, a single-word
    alias is refused, and every one of them the agenda's title names
    carries its event clause. `now` dates the clause; a time it cannot
    read leaves the clause at the bare title, never at nothing."""
    names: list[DeskName] = []
    for entity in entities or ():
        kind = str(getattr(entity, "type", "") or "")
        if kind not in NAME_TYPES:
            continue
        canonical = str(getattr(entity, "canonical_name", "") or "").strip()
        if not canonical:
            continue
        aliases = tuple(
            str(alias).strip() for alias in (getattr(entity, "aliases", ()) or ())
            if str(alias).strip() and len(str(alias).split()) > 1
        )
        names.append(DeskName(
            entity_id=int(getattr(entity, "id", 0)),
            names=(canonical, *aliases),
            fact_count=int(getattr(entity, "fact_count", 0) or 0),
        ))
    if agenda and str(agenda.get("title") or "").strip():
        named = _matching_spans(str(agenda.get("title")), tuple(names))
        if named:
            clause = _event_clause(agenda, now)
            named_ids = {span.entry.entity_id for span in named}
            names = [DeskName(n.entity_id, n.names, n.fact_count, clause)
                     if n.entity_id in named_ids else n for n in names]
    return tuple(names)


def match_names(text: str, index: tuple[DeskName, ...]) -> list[DeskName]:
    """The desk names one block of text carries, in the order it names them.

    A held name matches only as a whole word, case-insensitively. Where
    two names overlap, the longest span wins and a shorter name inside it
    is not also a match; one entry per entity id (a name and its alias
    count once); the refusals are the spec's. Returns at most
    MAX_PER_CARD, in first-named order."""
    return [span.entry for span in
            _matching_spans(text, index, limit=MAX_PER_CARD)]


def connect_line(rows: list[str], index: tuple[DeskName, ...]) -> tuple[str, int]:
    """The card's line, and how many remembered notes it drew on.

    Rows are the card's label texts, in the order the card shows them.
    No match draws no line (""), so a card with nothing to say stays
    quiet; a match names each entity once, in the order the rows name
    them (a row's own matches in the order they appear in the text),
    with its fact count and its event clause when there is one. The
    longest name present wins each span, so a shorter held name inside a
    longer one is never counted as a second connection."""
    picked: dict[int, tuple[int, DeskName]] = {}
    for position, row in enumerate(rows or ()):
        for span in _matching_spans(str(row), index):
            picked.setdefault(span.entry.entity_id, (position, span.entry))
    if not picked:
        return "", 0
    ordered = [entry for _position, entry in
               sorted(picked.values(), key=lambda pair: pair[0])[:MAX_PER_CARD]]
    clauses = []
    total = 0
    for entry in ordered:
        total += entry.fact_count
        noun = "thing" if entry.fact_count == 1 else "things"
        clause = f"{entry.names[0]}, {entry.fact_count} {noun} you told the desk"
        if entry.event_clause:
            clause += f", {entry.event_clause}"
        clauses.append(clause)
    return "Also in your desk: " + "; ".join(clauses) + ".", total


def _event_clause(agenda: dict, now: float) -> str:
    """The agenda's next meeting as one clause: title, day, clock time.

    The title keeps the casing it was stored with; matching lowercased it
    only to find which entities the agenda names."""
    title = str(agenda.get("title") or "").strip()
    when = str(agenda.get("time") or "").strip()
    day = ""
    clock = ""
    if when:
        try:
            start = datetime.fromisoformat(when)
        except ValueError:
            start = None
        if start is not None:
            clock = start.strftime("%H:%M")
            today = datetime.fromtimestamp(now, tz=timezone.utc).astimezone().date()
            delta = (start.date() - today).days
            day = {0: "today", 1: "tomorrow"}.get(delta, start.strftime("%b %d"))
    return " ".join(part for part in (title, day, f"at {clock}" if clock else "") if part)


def _longest_word(name: str) -> int:
    """The longest word a name holds, in characters."""
    words = [word for word in re.split(r"\W+", name) if word]
    return max((len(word) for word in words), default=0)
