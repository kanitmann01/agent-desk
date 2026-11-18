"""The digest family: what the inbox is really asking of this person.

Filled by docs/tickets/2026-11-18-coupled-intelligence/04-agenda-and-digest.md;
until then a card of this family carries no reading and the seam records it
as empty rather than inventing one.
"""

from __future__ import annotations

from typing import Callable

from agentdesk.insight.types import InsightContext, InsightReading


def derive(card: dict, payload: dict, context: InsightContext) -> InsightReading:
    return InsightReading()


def compose(
    thread: dict,
    preferences: dict,
    *,
    complete: Callable[[dict, str], str] | None = None,
) -> str:
    """One reply draft from the thread's subject, sender and last line."""
    return ""
