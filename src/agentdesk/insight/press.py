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

# The desk will not hand back a skeleton dressed as a draft: when the model
# path is off the route refuses, and the refusal repeats what would have
# travelled so the promise and the refusal are the same sentence.
MODEL_OFF = (
    "Nothing was drafted: model calls are off on this desk, so there is no "
    "model to write with. Turn the model on in Settings, then ask again."
)

# The draft never quotes a body, because none was read. Saying so on the
# draft keeps the skeleton from being mistaken for a finished reply.
SKELETON_NOTE = (
    "A skeleton from the thread's subject and greeting; no message body was read."
)

DISCLOSURE = (
    "Sends: the thread's subject, who it is from, and its last line.",
    "Does not send: the rest of the thread, the workbook, the calendar, or any memory.",
)


def draft_reply(
    server: Any,  # noqa: ARG001 - kept for the caller's symmetry; unused by design
    body: object,
    *,
    preferences: dict,
    complete: Callable[[str], str] | None = None,
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
    if complete is None and digest.draftable(thread):
        raise InsightError(
            "insight:model-off", " ".join((MODEL_OFF,) + DISCLOSURE), 409
        )
    text, source = digest.compose_draft(thread, preferences, complete=complete)
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
        "source": source,
        "disclosure": list(DISCLOSURE),
        "note": SKELETON_NOTE if source == "template" else "",
    }
