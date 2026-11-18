"""The calendar family: what the next meeting needs from this person.

Filled by docs/tickets/2026-11-18-coupled-intelligence/04-agenda-and-digest.md; until then a card of this family carries no reading
and the seam records it as empty rather than inventing one.
"""

from __future__ import annotations

from agentdesk.insight.types import InsightContext, InsightReading


def derive(card: dict, payload: dict, context: InsightContext) -> InsightReading:
    return InsightReading()
