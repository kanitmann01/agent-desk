"""Resolve the context a family reads, from what the dashboard already
loaded. Nothing here may raise: a missing or locked memory is a note on
the reading, never a broken dashboard.
"""

from __future__ import annotations

import time
from typing import Any

from agentdesk.insight.types import InsightContext
from agentdesk.memory.crypto import MemoryEncryptedError

RECALL_LIMIT = 3


def build_context(
    server: Any, preferences: dict, *, now: float | None = None
) -> InsightContext:
    recall, note = _memory(server)
    agenda, agenda_note = _agenda(server)
    return InsightContext(
        preferences=dict(preferences),
        now=time.time() if now is None else now,
        recall=recall,
        memory_note=note,
        agenda=agenda,
        agenda_note=agenda_note,
    )


def _agenda(server: Any) -> tuple[dict | None, str]:
    """The next meeting from the calendar bridge's day view, or the reason
    there is none. One read, shared by every family on the payload."""
    settings = getattr(server, "settings", None)
    try:
        if settings is not None and not settings.get("calendar_enabled"):
            return None, "Calendar reading is off in settings."
    except KeyError:
        pass
    calendar = getattr(server, "calendar", None)
    if calendar is None:
        return None, "The calendar bridge is not available."
    try:
        view = calendar.day_view()
    except Exception:  # noqa: BLE001 - a reading never takes a card down
        return None, "The calendar could not be read just now."
    upcoming = [row for row in (view.get("upcoming") or []) if isinstance(row, dict)]
    if not upcoming:
        return None, "Nothing left on the calendar."
    first = upcoming[0]
    return {
        "title": str(first.get("title") or "Busy"),
        "time": str(first.get("time") or ""),
        "meta": str(first.get("meta") or ""),
        "prep": [
            str(item.get("text"))
            for item in (view.get("items") or [])
            if isinstance(item, dict) and item.get("text")
        ],
    }, ""


def _memory(server: Any) -> tuple[Any, str]:
    """The recall adapter, and the reason it is missing when it is."""
    memory = getattr(server, "memory", None)
    if memory is None:
        return None, "Memory is not set up on this desk, so nothing was recalled."
    if bool(getattr(memory, "is_sealed", False)):
        return None, "Memory is locked, so nothing was recalled."

    def recall(subject: str, limit: int = RECALL_LIMIT) -> list[dict]:
        try:
            found = memory.recall(subject)
        except MemoryEncryptedError:
            return []
        except Exception:  # noqa: BLE001 - a reading never takes a card down
            return []
        rows = []
        for _score, fact in list(found)[:limit]:
            text = str(getattr(fact, "text", "") or "").strip()
            if text:
                rows.append({"text": text, "source": str(getattr(fact, "source", "") or "")})
        return rows

    return recall, ""
