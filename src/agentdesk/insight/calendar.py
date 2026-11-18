"""The calendar family: what the next meeting needs from this person.

The card already shows the next event, its time and its own prep list, so
this reading never repeats any of that. It adds what only preferences and
memory can: a prep checklist sized to the user's prep window and aimed at
their focus topics, the facts memory holds about this meeting, and one
honest line when memory could not be consulted.
"""

from __future__ import annotations

from agentdesk.insight.agenda import memory_lines, normalise, prep_items
from agentdesk.insight.types import InsightContext, InsightReading

CHECKLIST_TITLE = "Before the meeting"
MEMORY_TITLE = "From memory"


def derive(card: dict, payload: dict, context: InsightContext) -> InsightReading:
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
        rows = memory_lines(context, title, limit=2)
        if rows:
            elements.append({"kind": "list", "title": MEMORY_TITLE, "rows": rows})
    return InsightReading(
        elements=elements[: context.max_elements], status="ok", note=note
    )


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
