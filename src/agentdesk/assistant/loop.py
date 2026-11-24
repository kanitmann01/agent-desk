"""The thin agent loop behind research and the assistant.

One shape for both surfaces: context from the widgets, the user's ask,
one call to the corporate endpoint, a tolerant parse of the reply. The
loop never raises at the surface: unreachable endpoints and malformed
replies come back as a degraded status with a plain-language cause, and
every attempt is recorded in the audit store.
"""

import json
import logging
import time as _time
from dataclasses import dataclass

from agentdesk.assistant import audit
from agentdesk.llm import LlmUnavailable

LOG = logging.getLogger("agentdesk.assistant")

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"

DEGRADED_CAUSE = (
    "Your AI is not answering right now, so this is running "
    "at reduced capacity. Everything else on the dashboard keeps working."
)


@dataclass(frozen=True)
class Answer:
    """What a research or assistant turn returns to the surface."""

    status: str
    summary: str = ""
    sources: list = None  # type: ignore[assignment]
    reply: str = ""
    cause: str = ""

    def __post_init__(self) -> None:
        """Give the frozen dataclass a real list when sources was omitted.

        The None default exists only because a mutable default would be shared
        between instances; this replaces it per instance.
        """
        if self.sources is None:
            object.__setattr__(self, "sources", [])

    def to_json(self) -> dict:
        """Return the wire shape the research and assistant views render.

        The key set is the contract those views read; sources is always a list
        by the time this runs.
        """
        return {
            "status": self.status,
            "summary": self.summary,
            "sources": self.sources,
            "reply": self.reply,
            "cause": self.cause,
        }


def research(
    question: str,
    context: str,
    llm,
    audit_conn=None,
    endpoint: str = "",
    model: str = "",
    clock=None,
) -> Answer:
    """A sourced summary for a pasted question or context."""
    prompt = (
        f"{context}\n\n"
        "Research request (the user pasted it; search only what the company "
        "endpoint sanctions):\n"
        f"{question}\n\n"
        'Reply with JSON only: {"summary": "a short sourced summary", '
        '"sources": ["file or origin names that back it"]}'
    )
    return _ask(prompt, kind="research", llm=llm, audit_conn=audit_conn,
                endpoint=endpoint, model=model, clock=clock,
                summary_mode=True)


def assistant_reply(
    question: str,
    context: str,
    llm,
    audit_conn=None,
    endpoint: str = "",
    model: str = "",
    clock=None,
) -> Answer:
    """One assistant turn: an answer that may lean on widget context."""
    prompt = (
        f"{context}\n\n"
        "The user asks (they will not restate their context; use it):\n"
        f"{question}\n\n"
        "Answer in two short parts at most. Be concrete; if the context "
        "does not cover it, say so plainly."
    )
    return _ask(prompt, kind="assistant", llm=llm, audit_conn=audit_conn,
                endpoint=endpoint, model=model, clock=clock,
                summary_mode=False)


def _ask(prompt: str, *, kind: str, llm, audit_conn, endpoint: str, model: str, clock, summary_mode: bool) -> Answer:
    """Run one model call for a surface, degrading instead of raising.

    A failed call returns a degraded Answer whose cause is the endpoint's own
    message for LlmUnavailable and DEGRADED_CAUSE for anything unexpected.
    Every attempt is audited under llm.<kind> with the prompt's size in UTF-8
    bytes, never its text. In summary mode the reply is parsed into summary
    and sources; otherwise it is stripped and returned as reply.
    """
    now = clock if clock is not None else _time.time
    request_bytes = len(prompt.encode("utf-8"))
    try:
        text = llm(prompt)
    except Exception as exc:  # noqa: BLE001 - degrade at the surface
        if audit_conn is not None:
            audit.record(audit_conn, f"llm.{kind}", target=endpoint, status="error",
                         model=model, request_bytes=request_bytes,
                         detail=str(exc)[:200], clock=now)
        LOG.debug("%s degraded: %s", kind, exc)
        # A named endpoint cause is the vocabulary the adapter pinned;
        # anything unexpected keeps the standing degraded line.
        cause = str(exc) if isinstance(exc, LlmUnavailable) else DEGRADED_CAUSE
        return Answer(status=STATUS_DEGRADED, cause=cause)
    if audit_conn is not None:
        audit.record(audit_conn, f"llm.{kind}", target=endpoint, status="ok",
                     model=model, request_bytes=request_bytes, clock=now)
    if summary_mode:
        parsed = _parse_summary(text)
        return Answer(status=STATUS_OK, summary=parsed["summary"], sources=parsed["sources"])
    return Answer(status=STATUS_OK, reply=text.strip())


def _parse_summary(text: str) -> dict:
    """Tolerant parse of the research reply; prose becomes the summary."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    try:
        parsed = json.loads(stripped)
        summary = str(parsed.get("summary", "")).strip()
        sources = [str(s) for s in parsed.get("sources", []) if str(s).strip()][:6]
    except ValueError:
        summary, sources = stripped, []
    if not summary:
        summary = stripped or "The endpoint returned an empty answer."
    if not sources:
        sources = ["your AI"]
    return {"summary": summary, "sources": sources}
