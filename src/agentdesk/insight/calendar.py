"""The calendar family: what the next meeting needs from this person.

The card already shows the next event, its time and its own prep list, so
this reading never repeats any of that. It adds what only preferences and
memory can: a prep checklist sized to the user's prep window and aimed at
their focus topics, the facts memory holds about this meeting, and one
honest line when memory could not be consulted.
"""

from __future__ import annotations

from agentdesk.insight.agenda import DEFAULT_MINUTES, normalise, prep_items, recalled
from agentdesk.insight.preferences import PREP_MINUTES
from agentdesk.insight.types import InsightContext, InsightReading

CHECKLIST_TITLE = "Before the meeting"
MEMORY_TITLE = "From memory"


def derive(card: dict, payload: dict, context: InsightContext) -> InsightReading:
    """The calendar family's reading: prep sized to the user, memory added.

    No next meeting is an empty reading carrying the context's own reason,
    never an invented one. Quiet density folds the checklist into its
    sizing line and drops the memory list, because quiet keeps one
    element, and the reason memory stayed quiet then rides the note
    instead of a status line that would be dropped. The card's own prep
    text is skipped, so the reading adds to the card rather than repeats
    it."""
    row = context.agenda if isinstance(context.agenda, dict) else None
    title = str((row or {}).get("title") or "").strip()
    if not row or not title:
        # No meeting to prepare for: the context's own reason is the
        # reading, and nothing is invented to fill the card.
        return InsightReading(status="empty", note=context.agenda_note or "")

    quiet = context.density == "quiet"
    items = prep_items(row, context.preferences, skip=_shown_text(payload), limit=3)
    if quiet:
        # Quiet keeps one line, so the checklist folds into the sizing line
        # rather than arriving as a list of one.
        elements = [{"kind": "text", "label": "Prep", "text": items[0]["text"]}]
    else:
        elements = [{"kind": "checklist", "title": CHECKLIST_TITLE, "items": items}]
    note = ""
    memory_notes = 0
    rows: list[dict] = []
    if context.recall is None:
        # Quiet keeps one element, so the reason rides the note instead of
        # a status line that would be dropped.
        if quiet:
            note = context.memory_note
        elif context.memory_note:
            elements.append(
                {"kind": "status", "text": context.memory_note, "tone": "attention"}
            )
    elif not quiet:
        # The rows are read once here: the list element and the why citations
        # both come from them, so a second recall call is never needed.
        rows = recalled(context, title, limit=2)
        if rows:
            elements.append(
                {
                    "kind": "list",
                    "title": MEMORY_TITLE,
                    "rows": [
                        {
                            "primary": f"Last time: {row['text']}",
                            "secondary": "",
                            "meta": row["source"],
                        }
                        for row in rows
                    ],
                }
            )
        memory_notes = len(rows)
    return InsightReading(
        elements=elements[: context.max_elements],
        status="ok",
        note=note,
        used=_sized_by_preference(context),
        inputs=_inputs(context, quiet=quiet),
        memory_notes=memory_notes,
        why=_why(title, items[0]["text"], rows),
    )


def _why(title: str, sizing_line: str, rows: list[dict]) -> tuple[dict, ...]:
    """The reading's provenance: the meeting it prepared for, the rule and
    threshold that sized the checklist (the prep window and focus topics),
    and the cited fact ids and sources.

    A fact is cited by id and source only, so the drilldown can travel
    without carrying a fact's text; a row without an integer id cannot be
    cited at all."""
    cited = [
        {"id": row["id"], "source": row["source"]}
        for row in rows
        if isinstance(row.get("id"), int) and not isinstance(row.get("id"), bool)
    ]
    entry: dict = {
        "claim": f"Next meeting this reading prepared for: {title}",
        "rule": sizing_line,
    }
    if cited:
        entry["facts"] = cited
    return (entry,)


def _sized_by_preference(context: InsightContext) -> tuple[str, ...]:
    """The prep window the user set, when it is not the default one.

    The checklist is sized from this value, so a stored window other than the
    15-minute default - including zero, which is what removes the window - is
    a preference that changed the reading and belongs on the receipt.
    """
    value = context.preferences.get("prepMinutes")
    low, high = PREP_MINUTES
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        return ()
    return ("prepMinutes",) if value != DEFAULT_MINUTES else ()


def _inputs(context: InsightContext, *, quiet: bool) -> tuple[str, ...]:
    """The calendar, and memory when this reading was allowed to read it.

    A sealed or missing bank leaves `recall` None, and quiet keeps one element
    so it never asks memory at all: neither case may claim a consultation
    that did not happen.
    """
    names = ["calendar"]
    if context.recall is not None and not quiet:
        names.append("memory")
    return tuple(names)


def _shown_text(payload: dict) -> set[str]:
    """The text this card already shows, so the reading never repeats it."""
    shown: set[str] = set()
    elements = payload.get("elements") if isinstance(payload, dict) else None
    for element in elements or []:
        if not isinstance(element, dict):
            continue
        if element.get("kind") == "text":
            shown.add(normalise(element.get("text")))
        elif element.get("kind") == "checklist":
            for item in element.get("items") or []:
                if isinstance(item, dict):
                    shown.add(normalise(item.get("text")))
    shown.discard("")
    return shown
