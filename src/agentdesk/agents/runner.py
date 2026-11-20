"""The agent runner: recall, one prompt, one call, an honest outcome.

Mirrors the assistant loop's posture for every agent kind: build the
prompt (live context lines, the bounded facts block, the kind's
instructions, the user's brief), call the injected llm callable once,
catch the pinned endpoint causes into a degraded outcome, and parse the
reply tolerantly. The runner never raises at the handler and never
fabricates an artifact; the bounds come from the one module that owns
them (memory/service), never a copy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agentdesk.agents.registry import CONTEXT_WORKBOOK, AgentKind
from agentdesk.assistant.context import build_context
from agentdesk.llm import LlmUnavailable
from agentdesk.memory.service import MAX_FACTS, build_facts_block

LOG = logging.getLogger("agentdesk.agents")

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"

# The pinned prose causes, the assistant's own words, so a paused or
# failing endpoint reads the same on every surface.
ENDPOINT_OFF_CAUSE = (
    "Company endpoint calls are turned off in settings, so this "
    "surface is paused. Everything else keeps working."
)
DEGRADED_CAUSE = (
    "The company endpoint is not answering right now, so this is running "
    "at reduced capacity. Everything else on the dashboard keeps working."
)

# The brief bound, the retain excerpt's spirit: a few hundred characters,
# blank refused by the route, so one prompt stays one screen of intent.
BRIEF_MAX_CHARS = 400

# The feedback bound rides the retain excerpt's own ceiling, so a run's
# "how did it land?" can never out-grow the excerpt it is offered as.
FEEDBACK_MAX_CHARS = 4000

@dataclass(frozen=True)
class AgentRun:
    """What one agent run returns to the handler.

    `facts` is the receipt: the ranked facts the bounded block actually
    carried, as {id, text} rows. `artifact` is the parsed outcome, or
    None on a degraded run (never a fabricated one).
    """

    status: str
    cause: str = ""
    reply: str = ""
    artifact: dict | None = None
    facts: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Give the frozen dataclass a real list when facts was omitted.

        The None default exists only because a mutable default would be
        shared between instances; this replaces it per instance.
        """
        if self.facts is None:
            object.__setattr__(self, "facts", [])


def recall_block(ranked: list) -> tuple[str, list]:
    """The bounded facts block for one run, and the receipt it earns.

    The block is memory/service's own (at most five facts, five hundred
    characters, whole facts only); the receipt is derived from the
    finished block, so the two can never disagree about what the run
    used. Matching is on whitespace-collapsed text, because a fact whose
    text spans lines renders as several block lines and must still earn
    its receipt. No recall, no block, empty receipt: silence is the
    designed empty, not a hidden failure.
    """
    block = build_facts_block(ranked)
    if not block:
        return "", []
    # An entry starts at a "- " line and owns every continuation line
    # after it (a fact whose text spans lines renders that way), so the
    # block's own format says where each carried fact ends.
    entries: list[str] = []
    for line in block.splitlines()[1:]:
        if line.startswith("- "):
            entries.append(line[2:])
        elif line.strip() and entries:
            entries[-1] += "\n" + line
    carried: dict[str, int] = {}
    for entry in entries:
        key = " ".join(entry.split())
        carried[key] = carried.get(key, 0) + 1
    receipt = []
    for _score, fact in ranked[:MAX_FACTS]:
        key = " ".join(fact.text.split())
        if carried.get(key, 0) > 0:
            carried[key] -= 1
            receipt.append({"id": fact.id, "text": fact.text})
    return block, receipt


def workbook_context(agent: AgentKind, excel_status: dict | None) -> str:
    """The live context lines a workbook kind runs with, "" otherwise.

    The same derivation the assistant's context performs on the excel
    status, so a workbook agent's briefing is grounded in exactly what
    the assistant would see, and an unconfigured watch says so honestly.
    """
    if agent.context != CONTEXT_WORKBOOK:
        return ""
    return build_context(excel_status, None)


def build_agent_prompt(agent: AgentKind, brief: str, context_block: str = "",
                       facts_block: str = "") -> str:
    """Assemble one agent prompt: context lines, then the bounded facts
    block, then the kind's instructions, then the user's brief.

    The facts ride before the instructions so the model reads them as
    ground truth, not as suggestions; everything the model may know
    about the user arrives in that one bounded block.
    """
    parts = []
    if context_block:
        parts.append(context_block)
    if facts_block:
        parts.append(facts_block)
    parts.append(f"{agent.name} agent instructions:\n{agent.instructions}")
    parts.append(
        "The user's brief (they will not restate their context; use it):\n"
        f"{brief}"
    )
    return "\n\n".join(parts)


def parse_artifact(reply: str, agent: AgentKind) -> dict:
    """Tolerant parse of one reply into its artifact.

    The reply is kept as {"kind": "outline", "text"}. A fenced block is
    unwrapped so the model's words, not the fence, are what the page
    prints. An empty reply is named, never dropped.
    """
    stripped = (reply or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    return {
        "kind": "outline",
        "text": stripped or "The endpoint returned an empty answer.",
    }


def endpoint_off_run() -> AgentRun:
    """The degraded outcome of a run never made.

    The endpoint switch turned off means no prompt is built and no
    recall happens, so the receipt stays empty by design; the cause is
    the pinned sentence every surface shows for the switch.
    """
    return AgentRun(status=STATUS_DEGRADED, cause=ENDPOINT_OFF_CAUSE)


# The artifact summary's own bound: one line naming what the run made,
# because the transcript is provenance, not a second copy of the reply.
ARTIFACT_SUMMARY_CHARS = 120


def slides_text(artifact: dict) -> str:
    """An old slides artifact as plain lines.

    Title, then each slide title and its bullets. The page and the
    feedback summary both use this, so a stored deck is never a blank line.
    """
    lines = []
    title = str(artifact.get("title") or "").strip()
    if title:
        lines.append(title)
    for slide in artifact.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        slide_title = str(slide.get("title") or "").strip()
        if slide_title:
            lines.append(slide_title)
        for bullet in slide.get("bullets") or []:
            text = str(bullet).strip()
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines)


def artifact_summary(run: dict) -> str:
    """One line naming what a run produced, for the feedback transcript.

    A degraded run says so in so many words. An old slides row is named
    from its title and bullets. Anything else keeps the first line of
    its text.
    """
    artifact = run.get("artifact") if run else None
    if not artifact:
        return "no artifact (the run did not complete)"
    if artifact.get("kind") == "slides":
        raw = slides_text(artifact)
    else:
        raw = str(artifact.get("text", ""))
    text = " ".join(raw.split())
    return f"an outline: {text[:ARTIFACT_SUMMARY_CHARS]}"


def feedback_transcript(agent_name: str, run: dict, feedback: str) -> str:
    """The excerpt feedback offers the memory loop: the whole run as one
    transcript, agent and brief and artifact and the user's words, so a
    fact accepted from it carries provenance that reads like the run.
    """
    return "\n".join(
        [
            f"{agent_name} agent, one run.",
            f"The brief: {run.get('brief', '')}",
            f"What it produced: {artifact_summary(run)}",
            f"How it landed (the user's own words): {feedback}",
        ]
    )


def run_agent(agent: AgentKind, brief: str, llm,
              ranked_facts: list | None = None,
              excel_status: dict | None = None) -> AgentRun:
    """Run one agent task end to end, degrading instead of raising.

    The recall is already ranked by the caller (the store is a server
    concern); the runner builds the block and the receipt, attaches the
    kind's live context, calls the llm once, and parses the reply. A
    failed call keeps the receipt (the prompt was built and sent with
    those facts) and returns the endpoint's own pinned cause for
    LlmUnavailable, the standing degraded line for anything else.
    """
    facts_block, receipt = recall_block(ranked_facts or [])
    prompt = build_agent_prompt(
        agent, brief,
        context_block=workbook_context(agent, excel_status),
        facts_block=facts_block,
    )
    try:
        reply = llm(prompt)
    except Exception as exc:  # noqa: BLE001 - degrade at the surface
        LOG.debug("agent %s degraded: %s", agent.id, exc)
        cause = str(exc) if isinstance(exc, LlmUnavailable) else DEGRADED_CAUSE
        return AgentRun(status=STATUS_DEGRADED, cause=cause, facts=receipt)
    text = reply.strip()
    return AgentRun(
        status=STATUS_OK,
        reply=text,
        artifact=parse_artifact(text, agent),
        facts=receipt,
    )
