"""Agent breakdowns for the key commitment, over the corporate endpoint.

The widget's breakdown comes from the OpenAI-compatible endpoint the
company already provides, through the shared LLM adapter. Every failure
mode (no endpoint configured, network error, malformed reply) degrades
to a generic breakdown, because a widget that helps less is better than
a widget that breaks. Breakdowns are cached per event so a poll never
re-asks the model for a meeting it already prepared.
"""

import json
import logging

from agentdesk.llm import LlmUnavailable, env_config, chat

LOG = logging.getLogger("agentdesk.calendar")

FALLBACK_SUBTASKS = [
    "Review the agenda so you walk in knowing the point",
    "Note the one decision you need from this meeting",
    "Decide what you will offer to own afterwards",
]
FALLBACK_FOLLOWUPS: list[dict] = []


def env_llm_adapter(
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
):
    """A prompt-to-text adapter from the environment (or the given
    config), raising LlmUnavailable when nothing is configured. Tests
    inject their own callable instead."""
    cfg_base, cfg_key, cfg_model = env_config()
    base_url = base_url or cfg_base
    api_key = api_key or cfg_key
    model = model or cfg_model

    def complete(prompt: str) -> str:
        """Send one prompt to the endpoint this adapter was built with.

        The configuration is resolved once by env_llm_adapter, so the closure
        keeps calling the same endpoint even if the environment changes later.
        """
        return chat(base_url, api_key, model, prompt)

    return complete


def breakdown_prompt(event) -> str:
    """The one prompt the bridge asks; kept small and structured."""
    when = event.start.strftime("%H:%M") + "-" + event.end.strftime("%H:%M")
    return (
        f"Meeting: {event.subject}, today {when}"
        + (f", {event.attendees} attendees" if event.attendees else "")
        + ". I need to prepare. Reply with JSON only: "
        '{"subtasks": ["three short preparation steps"], '
        '"followups": [{"text": "a follow-up I owe", "deadline": "when it is due"}]} '
        "At most 3 subtasks and 2 followups."
    )


def parse_breakdown(text: str) -> dict:
    """Parse the model's JSON reply, tolerating code fences. Any surprise
    becomes the fallback rather than an error, and the fallback is marked
    so nothing downstream mistakes advice for tracked commitments."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return {"subtasks": list(FALLBACK_SUBTASKS), "followups": [], "fallback": True}
    subtasks = [str(s) for s in parsed.get("subtasks", []) if str(s).strip()][:3]
    followups = [
        {"text": str(f.get("text", "")), "deadline": str(f.get("deadline", ""))}
        for f in parsed.get("followups", [])
        if isinstance(f, dict) and str(f.get("text", "")).strip()
    ][:2]
    if not subtasks:
        subtasks = list(FALLBACK_SUBTASKS)
        return {"subtasks": subtasks, "followups": followups, "fallback": True}
    return {"subtasks": subtasks, "followups": followups, "fallback": False}


def generic_breakdown() -> dict:
    """The no-model breakdown: still useful, never broken."""
    return {"subtasks": list(FALLBACK_SUBTASKS), "followups": [dict(f) for f in FALLBACK_FOLLOWUPS], "fallback": True}
