"""The one path that may spend a model call from a reading.

A reading is local and free; a draft is not. So the transport is separate:
it validates the request, states exactly what would be sent, and only then
delegates the composition. Nothing here writes memory, and the disclosure
it returns is the sentence the user sees before pressing.
"""

from __future__ import annotations

from typing import Any, Callable

from agentdesk.insight import digest
from agentdesk.insight.types import InsightError

KINDS = ("reply-draft",)

DISCLOSURE = (
    "Sends: the thread's subject, who it is from, and its last line.",
    "Does not send: the rest of the thread, the workbook, the calendar, or any memory.",
)


def draft_reply(
    server: Any,
    body: object,
    *,
    preferences: dict,
    complete: Callable[[dict, str], str] | None = None,
) -> dict:
    """Compose one reply draft for one thread, or say why not."""
    if not isinstance(body, dict):
        raise InsightError("insight:bad-request", "Expected a JSON object.")
    kind = body.get("kind")
    if kind not in KINDS:
        raise InsightError("insight:unknown-kind", f"{kind} is not something the desk drafts.")
    thread = body.get("thread")
    if not isinstance(thread, dict):
        raise InsightError("insight:bad-request", "A draft needs the thread it answers.")
    subject = str(thread.get("subject") or "").strip()
    if not subject:
        raise InsightError("insight:bad-request", "A draft needs the thread it answers.")
    if len(subject) > 200:
        raise InsightError("insight:bad-request", "That subject is too long to draft from.")
    text = digest.compose(thread, preferences, complete=complete)
    if not text.strip():
        return {
            "status": "empty",
            "text": "",
            "source": "none",
            "disclosure": list(DISCLOSURE),
            "note": "No draft yet.",
        }
    return {
        "status": "draft",
        "text": text,
        "source": "model" if complete is not None else "template",
        "disclosure": list(DISCLOSURE),
        "note": "",
    }
