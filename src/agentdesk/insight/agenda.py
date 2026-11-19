"""What the next meeting needs from this person, and why.

Pure helpers shared by the calendar and digest families. Nothing here
touches the server, the clock or the memory store: a reading is a function
of the agenda, the facts that were recalled for a subject, and the
preferences the user typed in Settings.

The three readings a caller can build from this module are the prep
checklist (sized by prepMinutes, never longer than three lines), the memory
links for a subject (at most two, each with its source), and the focus
topics a line of text touches.
"""

from __future__ import annotations

import re

from agentdesk.insight.preferences import PREP_MINUTES
from agentdesk.insight.types import InsightContext

DEFAULT_MINUTES = 15
MAX_ITEMS = 3
MAX_TOPICS = 3

# Words too common to tell one meeting from another. A subject word in this
# set must not make a remembered fact look like it is about this meeting.
_COMMON = frozenset({
    "about", "after", "again", "against", "also", "before", "been", "being",
    "call", "catch", "check", "daily", "does", "down", "each", "even",
    "every", "from", "have", "here", "into", "just", "like", "make", "many",
    "meeting", "more", "most", "much", "must", "next", "notes", "only",
    "over", "prep", "review", "same", "some", "standup", "status", "still",
    "such", "sync", "take", "team", "than", "that", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "under", "until",
    "update", "very", "weekly", "well", "were", "what", "when", "where",
    "which", "while", "will", "with", "would", "your",
})


def normalise(text: object) -> str:
    """The comparison form of a line: lowercase, single-spaced, trimmed."""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def truncate(text: object, limit: int) -> str:
    """At most `limit` characters, marked when something was cut."""
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3].rstrip() + "..."


def _words(text: str) -> list[str]:
    """The words of a subject that can carry meaning, longest first kept
    in reading order."""
    return [
        word
        for word in re.findall(r"[a-z0-9']+", normalise(text))
        if len(word) >= 4 and word not in _COMMON
    ]


def mentions(fact: str, subject: str) -> bool:
    """Whether a remembered fact is about this subject at all.

    A subject with no distinctive word (a "Weekly sync") cannot filter
    anything, so whatever recall returned for it stands."""
    words = _words(subject)
    if not words:
        return True
    haystack = normalise(fact)
    return any(word in haystack for word in words)


def focus_matches(text: str, preferences: dict) -> list[str]:
    """The user's focus topics this line of text touches, in their order."""
    haystack = normalise(text)
    topics = (preferences or {}).get("focusTopics")
    if not haystack or not isinstance(topics, list):
        return []
    matched: list[str] = []
    for topic in topics:
        line = str(topic or "").strip()
        # A one-character topic would match every card; it is not a topic.
        if len(line) < 2 or line.lower() in {seen.lower() for seen in matched}:
            continue
        if line.lower() in haystack:
            matched.append(line)
        if len(matched) >= MAX_TOPICS:
            break
    return matched


def focus_overlap(agenda_row: dict, preferences: dict) -> list[str]:
    """The focus topics the next meeting's title or meta touches."""
    if not isinstance(agenda_row, dict):
        return []
    text = f"{agenda_row.get('title') or ''} {agenda_row.get('meta') or ''}"
    return focus_matches(text, preferences)


def _minutes(preferences: dict) -> int:
    """The prep window in minutes, or the default when nothing usable is
    stored.

    A hand-edited file can hold any value, so a window outside its range
    reads as the default rather than raising: the checklist is sized
    either way, and a reading never fails over a preference.
    """
    low, high = PREP_MINUTES
    value = (preferences or {}).get("prepMinutes")
    if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
        return value
    return DEFAULT_MINUTES


def _sizing_line(minutes: int, topics: list[str]) -> str:
    """The checklist's first line: how long to set aside, and for what.

    A window of zero says no prep time is set, which is a choice the user
    made and not an omission to hide. The focus topics ride the same line
    so a quiet card can drop the checklist and still carry both facts.
    """
    if minutes <= 0:
        line = "No prep window is set."
    else:
        line = f"Set aside {minutes} minutes before this."
    if topics:
        line += " Focus: " + ", ".join(topics) + "."
    return line


def prep_items(
    agenda_row: dict, preferences: dict, *, skip=(), limit: int = MAX_ITEMS
) -> list[dict]:
    """The checklist a meeting earns: one sizing line, then its own prep.

    `skip` is the text the card already shows, so a reading never repeats
    the card it sits under. Nothing here knows whether a prep item was
    ticked, so the items are offered undone rather than guessed at."""
    row = agenda_row if isinstance(agenda_row, dict) else {}
    items = [
        {
            "text": _sizing_line(_minutes(preferences), focus_overlap(row, preferences)),
            "done": False,
            "due": "",
        }
    ]
    seen = {normalise(text) for text in skip}
    prep = row.get("prep")
    for text in prep if isinstance(prep, list) else []:
        line = str(text or "").strip()
        key = normalise(line)
        if not line or key in seen:
            continue
        seen.add(key)
        items.append({"text": line, "done": False, "due": ""})
        if len(items) >= limit:
            break
    return items[:limit]


def prep_checklist(
    agenda_row: dict, preferences: dict, *, skip=(), limit: int = MAX_ITEMS
) -> dict:
    """The checklist as a renderable element."""
    return {
        "kind": "checklist",
        "title": "Before the meeting",
        "items": prep_items(agenda_row, preferences, skip=skip, limit=limit),
    }


def recalled(context: InsightContext, subject: str, *, limit: int = 2) -> list[dict]:
    """The recalled facts that mention this subject, as {"text", "source"}.

    A missing, sealed or failing memory reads as no facts at all: the
    context already explains itself in `memory_note`, and a reading must
    not invent one."""
    recall = getattr(context, "recall", None)
    line = str(subject or "").strip()
    if recall is None or not line:
        return []
    try:
        found = list(recall(line, limit + 2) or [])
    except Exception:  # noqa: BLE001 - a reading never takes a card down
        return []
    rows: list[dict] = []
    for fact in found:
        if not isinstance(fact, dict):
            continue
        text = str(fact.get("text") or "").strip()
        if not text or not mentions(text, line):
            continue
        rows.append(
            {
                "text": text,
                "source": str(fact.get("source") or "").strip() or "memory",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def memory_lines(
    context: InsightContext,
    subject: str,
    *,
    prefix: str = "Last time",
    limit: int = 2,
) -> list[dict]:
    """The memory links as list rows: the fact, and where it came from."""
    return [
        {
            "primary": f"{prefix}: {row['text']}",
            "secondary": "",
            "meta": row["source"],
        }
        for row in recalled(context, subject, limit=limit)
    ]
