"""Attach each card's reading, one family at a time.

The dashboard calls attach_cards once per payload. A family derives from
the card's own payload; a family that raises leaves the card untouched and
records why, because a reading is an addition to a card and never a reason
for one to fail.
"""

from __future__ import annotations

from typing import Callable

from agentdesk.insight import calendar, digest, research, workbook
from agentdesk.insight import reading as insight_reading
from agentdesk.insight.preferences import changed
from agentdesk.insight.snapshots import card_signature, perceptual_delta
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


def attach_cards(
    cards: list[dict],
    context: InsightContext,
    *,
    snapshots: dict | None = None,
) -> None:
    """Mutate the cards in place: extra elements, plus payload["insight"].

    `snapshots` is the watermark's card map from the snapshot store, or
    None. None leaves every card exactly as the reading left it; a map
    makes each tile open with its one-line delta when what it shows moved
    since the user last viewed the dashboard, even on a tile whose
    payload no family touches.
    """
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        family = FAMILIES.get(str(card.get("pluginId") or ""))
        if family is None:
            _delta(card, snapshots)
            continue
        payload = card.get("payload")
        if not isinstance(payload, dict):
            _delta(card, snapshots)
            continue
        _attach(card, family, payload, context)
        _delta(card, snapshots)


def _delta(card: dict, snapshots: dict | None) -> None:
    """Prepend one tile's perceptual delta block, when one is owed.

    The signature is read after the family ran, so a snapshot taken at
    view time and a signature taken at read time see the same card. A
    None snapshots map, a tile with no watermark, and an unchanged tile
    all leave the card exactly as it was.
    """
    if not snapshots:
        return
    entry = snapshots.get(str(card.get("id") or card.get("pluginId") or ""))
    previous = entry.get("signature") if isinstance(entry, dict) else None
    line = perceptual_delta(previous, card_signature(card))
    if not line:
        return
    payload = card.get("payload")
    if not isinstance(payload, dict):
        payload = {}
        card["payload"] = payload
    insight = payload.get("insight")
    if not isinstance(insight, dict):
        insight = {
            "status": "ok",
            "source": "local",
            "preferences": [],
            "note": "",
            "blocks": [],
            "press": None,
        }
        payload["insight"] = insight
    blocks = insight.get("blocks")
    insight["blocks"] = [{"kind": "delta", "text": line}] + (
        blocks if isinstance(blocks, list) else [])


def _attach(
    card: dict,
    family: Callable[[dict, dict, InsightContext], InsightReading],
    payload: dict,
    context: InsightContext,
) -> None:
    """Run one family over one card and write its reading into the payload.

    A family that refuses with InsightError or blows up becomes an
    \"unavailable\" note on the card, never a broken payload. Elements are
    kept only in the kinds the renderer knows and capped at the density's
    maximum; payload[\"insight\"] always lands, even with nothing to say,
    because the card's record of what was attempted belongs on it. The lines
    under the card and the press are resolved here, once, as blocks a surface
    prints verbatim: no surface keeps its own phrase table."""
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
        "blocks": insight_reading.blocks(reading),
        "press": insight_reading.press(reading.press),
    }
