"""The research family: the question this desk has already half answered.

The research card prints its latest stored answer as rendered elements, so
the reading works from those elements (the answer is the text the reader
already sees, the time is what the card printed) rather than opening the
store for a second opinion. Everything added here comes from what the user
typed on Settings, from the meeting the calendar already resolved, and from
what memory remembers about the same subject. Nothing is written and no
model is called.
"""

from __future__ import annotations

import re
from datetime import datetime

from agentdesk.insight.types import InsightContext, InsightReading

MAX_SUGGESTIONS = 3
MAX_RECALL = 2
FACT_CHARS = 160
SUBJECT_CHARS = 400

# The labels the research widget's own schema sets on its rendered text
# elements: the only handle a family has on an answer it did not compute.
SUMMARY_LABEL = "latest answer"
ANSWERED_LABEL = "answered"
ANSWERED_FORMAT = "%Y-%m-%d %H:%M"

# Words that say nothing about a subject. Kept short on purpose: an overlap
# is evidence, and a word not on this list only ever adds one.
STOPWORDS = frozenset(
    """
    a about after again against all also an and any are as at be been before
    being between both but by can could did do does doing for from had has have
    having how if in into is it its just like more most much must no not now of
    off on once only or other our out over own same should since so some such
    than that the their them then there these they this those through to too
    under until up very was we were what when where which while who whom why
    will with within without would you your
    """.split()
)

_WORD = re.compile(r"[a-z0-9]+")


def derive(
    card: dict,  # noqa: ARG001 - the payload is this reading's input, not the card
    payload: dict,
    context: InsightContext,
) -> InsightReading:
    """What the stored answer leaves open, and what memory adds to it."""
    payload = payload if isinstance(payload, dict) else {}
    answer = _answer(payload)
    if not answer:
        return InsightReading(
            note="No research answer is stored yet, so there is nothing to continue from.",
            status="empty",
        )

    topics = _topics(context.preferences)
    meeting = _meeting(context)
    answered = _answered_at(payload)
    answer_words = _keywords(answer)
    closest = _closest(topics, answer_words)
    elements: list[dict] = []

    if meeting and _older_than(answered, meeting["start"]):
        name = meeting["title"] or meeting["meta"] or "the next meeting"
        clock = " at " + meeting["clock"] if meeting["clock"] else ""
        line = "The answer is older than " + name + clock + ": worth refreshing."
        if closest:
            line = line + " Closest focus topic: " + closest + "."
        elements.append({"kind": "status", "text": line, "tone": "attention"})
    elif closest:
        elements.append(
            {"kind": "text", "label": "Focus", "text": "Closest focus topic: " + closest + "."}
        )
    elif topics:
        elements.append(
            {
                "kind": "text",
                "label": "Focus",
                "text": "None of the focus topics are named in the stored answer.",
            }
        )

    suggestions = _suggestions(topics, answer_words, meeting)
    note = ""
    if suggestions:
        elements.append({"kind": "list", "title": "Worth researching", "rows": suggestions})
    elif not topics and not _meeting_rows(meeting, answer_words):
        # Nothing on either side: a meeting with no subject and no location
        # is no more to go on than an empty calendar.
        if meeting is None:
            note = (
                "The desk has nothing to base a suggestion on: no focus topics "
                "are set and the calendar has nothing upcoming."
            )
        else:
            note = (
                "The desk has nothing to base a suggestion on: no focus topics "
                "are set and the next meeting has no subject."
            )

    memory_notes = 0
    if context.recall is not None:
        rows = _recall_rows(context, answer)
        if rows:
            elements.append({"kind": "list", "title": "From memory", "rows": rows})
        memory_notes = len(rows)
    elif not elements and context.memory_note.strip():
        # With nothing else on the card, why memory stayed quiet is the whole
        # reading; with anything above it, the reason is only noise.
        elements.append(
            {"kind": "status", "text": context.memory_note.strip(), "tone": "attention"}
        )

    # The focus topics are visible in the sentences themselves, so this
    # reading names its sources and no preference key.
    inputs = ["rows"]
    if meeting is not None:
        inputs.append("calendar")
    if context.recall is not None:
        inputs.append("memory")
    return InsightReading(
        elements=elements,
        note=note,
        inputs=tuple(inputs),
        memory_notes=memory_notes,
    )


def _answer(payload: dict) -> str:
    """The stored answer: the card's own rendered text, never a new read."""
    for key in ("summary", "answer"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _line(value)
    elements = _elements(payload)
    labelled = _labelled(elements, SUMMARY_LABEL)
    if labelled:
        return labelled
    # A schema with no labels leaves one long text element standing where the
    # answer was; anything shorter is a note about it.
    longest = ""
    for element in elements:
        if element.get("kind") not in ("text", "status"):
            continue
        if str(element.get("state") or "") not in ("", "ok"):
            continue
        candidate = _line(str(element.get("text") or ""))
        if len(candidate) > len(longest):
            longest = candidate
    return longest if len(longest) >= 20 else ""


def _answered_at(payload: dict) -> datetime | None:
    """When the answer was written, as the card printed it, if it says."""
    raw = payload.get("answeredAt")
    if not isinstance(raw, str) or not raw.strip():
        raw = _labelled(_elements(payload), ANSWERED_LABEL)
    text = raw.strip() if isinstance(raw, str) else ""
    if not text:
        return None
    for parse in (_printed_time, datetime.fromisoformat):
        try:
            moment = parse(text)
        except ValueError:
            continue
        return moment.replace(tzinfo=None) if moment.tzinfo else moment
    return None


def _printed_time(text: str) -> datetime:
    """A time in the exact format the card printed it, raising ValueError
    when the text is not that format; _answered_at treats the raise as
    \"not said\" rather than an error."""
    return datetime.strptime(text, ANSWERED_FORMAT)


def _meeting(context: InsightContext) -> dict | None:
    """The next meeting as the calendar resolved it, or None."""
    agenda = context.agenda
    if not isinstance(agenda, dict):
        return None
    start = _iso(agenda.get("time"))
    title = str(agenda.get("title") or "").strip()
    if title.lower() == "busy":
        title = ""  # the calendar's own default for a slot with no subject
    return {
        "title": title,
        "meta": _line(str(agenda.get("meta") or "")),
        "start": start,
        "clock": start.strftime("%H:%M") if start else "",
    }


def _iso(value: object) -> datetime | None:
    """A value as a naive datetime, or None when it does not parse.

    A timezone is dropped rather than converted: the card printed local
    time and the meeting time is local too, so both sides of the
    comparison stay what the page showed."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return moment.replace(tzinfo=None) if moment.tzinfo else moment


def _older_than(answered: datetime | None, start: datetime | None) -> bool:
    """Whether the answer predates the meeting, unknown times aside.

    Either side missing reads as False: an unknown time is not evidence
    that the answer is stale."""
    if answered is None or start is None:
        return False
    return answered < start


def _suggestions(topics: list[str], answer_words: set[str], meeting: dict | None) -> list[dict]:
    """Questions the desk could research next, each naming where it came from."""
    rows = _topic_rows(topics, answer_words)
    rows.extend(_meeting_rows(meeting, answer_words))
    return rows[:MAX_SUGGESTIONS]


def _topic_rows(topics: list[str], answer_words: set[str]) -> list[dict]:
    """One question per focus topic the stored answer does not name."""
    rows: list[dict] = []
    for topic in topics:
        if _overlap(answer_words, _keywords(topic)):
            continue
        rows.append(
            {
                "primary": "What is the current picture on " + topic + "?",
                "secondary": "The focus list names " + topic + ", and the stored answer does not.",
                "meta": "Focus list",
            }
        )
    return rows


def _meeting_rows(meeting: dict | None, answer_words: set[str]) -> list[dict]:
    """One or two questions the next meeting makes worth researching."""
    if meeting is None:
        return []
    title, meta, clock = meeting["title"], meeting["meta"], meeting["clock"]
    at = " at " + clock if clock else ""
    rows: list[dict] = []
    if title and not _overlap(answer_words, _keywords(title)):
        rows.append(
            {
                "primary": "What should be known before " + title + at + "?",
                "secondary": (
                    "The calendar shows " + title + " next, and the stored "
                    "answer does not name it."
                ),
                "meta": "Calendar",
            }
        )
    if (
        meta
        and not _overlap(answer_words, _keywords(meta))
        and not _overlap(_keywords(meta), _keywords(title))
    ):
        subject = title or "the next meeting"
        rows.append(
            {
                "primary": "What should be known about " + meta + " before " + subject + "?",
                "secondary": (
                    "The calendar lists " + meta + " with " + subject + ", and "
                    "the stored answer does not name it."
                ),
                "meta": "Calendar",
            }
        )
    return rows


def _recall_rows(context: InsightContext, answer: str) -> list[dict]:
    """What memory remembers that bears on the answer, at most two lines."""
    try:
        found = context.recall(answer[:SUBJECT_CHARS], MAX_RECALL)
    except Exception:  # noqa: BLE001 - memory never sinks a card's reading
        return []
    if not isinstance(found, list):
        return []
    rows: list[dict] = []
    seen: set[str] = set()
    for item in found:
        if not isinstance(item, dict):
            continue
        text = _trim(_line(str(item.get("text") or "")))
        key = text.lower()
        if not text or key in seen or key in answer.lower():
            continue  # the card already says it, so the reading will not say it again
        seen.add(key)
        rows.append(
            {
                "primary": text,
                "secondary": "From memory",
                "meta": _trim(_line(str(item.get("source") or "")), 80) or "Memory",
            }
        )
        if len(rows) == MAX_RECALL:
            break
    return rows


def _closest(topics: list[str], answer_words: set[str]) -> str:
    """The focus topic the answer is nearest to; the earliest wins a tie."""
    best, score = "", 0
    for topic in topics:
        hits = _overlap(answer_words, _keywords(topic))
        if hits > score:
            best, score = topic, hits
    return best


def _topics(preferences: object) -> list[str]:
    """The focus topics exactly as the settings page typed them, blank
    lines dropped and nothing else inferred."""
    if not isinstance(preferences, dict):
        return []
    raw = preferences.get("focusTopics")
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _elements(payload: dict) -> list[dict]:
    """The payload's rendered elements, keeping only the dict-shaped ones."""
    raw = payload.get("elements")
    if not isinstance(raw, list):
        return []
    return [element for element in raw if isinstance(element, dict)]


def _labelled(elements: list[dict], label: str) -> str:
    """The text of the first element carrying this label, case aside, or
    \"\" when no element does."""
    for element in elements:
        if str(element.get("label") or "").strip().lower() != label:
            continue
        text = _line(str(element.get("text") or ""))
        if text:
            return text
    return ""


def _keywords(text: str) -> set[str]:
    """The lowercase words that can carry a subject: three characters or
    more, with the stopwords out."""
    return {
        word
        for word in _WORD.findall(text.lower())
        if len(word) >= 3 and word not in STOPWORDS
    }


def _overlap(one: set[str], other: set[str]) -> int:
    """How many words in "other" the text in "one" already names.

    Prefixes stand in for stemming: deployed/deployment and harness/harnesses
    are the same subject, and no model is consulted to notice."""
    hits = 0
    for word in other:
        for known in one:
            long_enough = len(word) >= 4 and len(known) >= 4
            if known == word or (
                long_enough and (known.startswith(word) or word.startswith(known))
            ):
                hits += 1
                break
    return hits


def _line(text: str) -> str:
    """The text with every run of whitespace collapsed to one space."""
    return " ".join(text.split())


def _trim(text: str, limit: int = FACT_CHARS) -> str:
    """The text cut to its limit on a word boundary and marked with ...,
    so a remembered fact never arrives half a word."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "..."
