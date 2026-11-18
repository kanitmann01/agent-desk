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
    return InsightContext(
        preferences=dict(preferences),
        now=time.time() if now is None else now,
        recall=recall,
        memory_note=note,
    )


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
