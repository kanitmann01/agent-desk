"""The agent registry: the task kinds the desk can run.

A kind is data, not code: the runner reads the fields and a new kind
joins by adding one entry here, with no change to the runner, the store
or the page. The `context` field says what live state the runner must
supply per run: "none" (nothing beyond memory) or "workbook" (the
watched workbook's status lines, the same derivation the assistant's
context uses).
"""

from __future__ import annotations

from dataclasses import dataclass

CONTEXT_NONE = "none"
CONTEXT_WORKBOOK = "workbook"


@dataclass(frozen=True)
class AgentKind:
    """One task the desk can run.

    `instructions` is the whole model-facing contract for the kind,
    including the reply shape it asks for; `artifact_kind` names what
    the tolerant parse aims for ("slides" for the slide outline).
    `context` picks the live status lines the runner attaches
    (CONTEXT_NONE or CONTEXT_WORKBOOK).
    """

    id: str
    name: str
    blurb: str
    artifact_kind: str
    instructions: str
    context: str = CONTEXT_NONE


PRESENTATION = AgentKind(
    id="presentation",
    name="Presentation",
    blurb=(
        "A slide outline from a short brief, grounded in what the desk "
        "already remembers about the topic."
    ),
    artifact_kind="slides",
    instructions=(
        "You turn a short brief into a slide outline. Reply with JSON "
        'only: {"title": "the deck title", "slides": [{"title": "one '
        'slide", "bullets": ["a short point", "a short point"]}]}. Keep '
        "it to three to six slides of two to four bullets each. Use the "
        "known facts and context when they are given; never invent "
        "numbers."
    ),
    context=CONTEXT_NONE,
)

WORKSHEET_BRIEF = AgentKind(
    id="worksheet-brief",
    name="Worksheet brief",
    blurb=(
        "A short briefing about the watched workbook, grounded in its "
        "live status and what the desk already remembers about it."
    ),
    artifact_kind="outline",
    instructions=(
        "You write a short briefing about the watched sales workbook. "
        "Ground every line in the connected workbook context and the "
        "known facts; never invent rows, totals or file names. Reply "
        "with plain text only: one headline sentence, then three to six "
        "short bullet lines. When the context says no workbook is "
        "connected, say plainly that nothing is watched and there is "
        "nothing to brief on; a blank is never a zero."
    ),
    context=CONTEXT_WORKBOOK,
)

ROSTER = (PRESENTATION, WORKSHEET_BRIEF)


def find_agent(agent_id: str) -> AgentKind | None:
    """The roster entry with this id, or None for anything else.

    The one lookup every route and the runner share, so the roster can
    grow without a second place to keep the ids.
    """
    for agent in ROSTER:
        if agent.id == agent_id:
            return agent
    return None
