"""Attach each card's reading, one family at a time.

The dashboard calls attach_cards once per payload. A family derives from
the card's own payload; a family that raises leaves the card untouched and
records why, because a reading is an addition to a card and never a reason
for one to fail.
"""

from __future__ import annotations

from typing import Callable

from agentdesk.insight import calendar, digest, research, workbook
from agentdesk.insight.preferences import changed
from agentdesk.insight.types import InsightContext, InsightError, InsightReading
from agentdesk.plugins.render import ELEMENT_KINDS

FAMILIES: dict[str, Callable[[dict, dict, InsightContext], InsightReading]] = {
    "excel-report": workbook.derive,
    "calendar-today": calendar.derive,
    "meeting-prep": calendar.derive,
    "outlook-digest": digest.derive,
    "waiting-on-you": digest.derive,
    "research-brief": research.derive,
}


def attach_cards(cards: list[dict], context: InsightContext) -> None:
    """Mutate the cards in place: extra elements, plus payload["insight"]."""
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        family = FAMILIES.get(str(card.get("pluginId") or ""))
        if family is None:
            continue
        payload = card.get("payload")
        if not isinstance(payload, dict):
            continue
        _attach(card, family, payload, context)


def _attach(
    card: dict,
    family: Callable[[dict, dict, InsightContext], InsightReading],
    payload: dict,
    context: InsightContext,
) -> None:
    try:
        reading = family(card, payload, context)
    except InsightError as exc:
        reading = InsightReading(note=exc.message, status="unavailable")
    except Exception:  # noqa: BLE001 - a reading never takes a card down
        reading = InsightReading(
            note="This card's reading could not be worked out.",
            status="unavailable",
        )
    if not isinstance(reading, InsightReading):
        reading = InsightReading(status="unavailable", note="This card's reading was empty.")
    elements = [
        element
        for element in reading.elements
        if isinstance(element, dict) and element.get("kind") in ELEMENT_KINDS
    ][: context.max_elements]
    if elements:
        existing = payload.get("elements")
        if not isinstance(existing, list):
            existing = []
            payload["elements"] = existing
        existing.extend(elements)
    payload["insight"] = {
        "status": reading.status or ("ok" if elements or reading.note else "empty"),
        "source": "local",
        "preferences": changed(context.preferences),
        "note": reading.note,
        "press": reading.press,
        "suggested": [row for row in reading.suggested[:5] if isinstance(row, int)],
    }
