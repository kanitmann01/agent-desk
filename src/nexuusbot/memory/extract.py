"""The extractor port: conversation text in, candidate facts out.

Ticket #91 ports the donor's extraction pipeline exactly. Provenance:
the system prompt and user-message shape from src/extract/prompt.ts
(verbatim), the tolerant reply parse from src/extract/parse.ts (think
blocks stripped, first brace to last brace, a facts array required),
the per-fact bounds from src/extract/validate.ts (non-empty text at
most 2000 characters, the world/experience kind vocabulary, a parseable
occurrence or none, typed entities), and the retain post-filters from
src/bank.ts (knowledge gaps dropped, five candidates at most, and the
occurrence gate: an extracted time survives only when the retained
source text itself names one). The gap detector itself is a separate
verbatim port in memory/knowledge_gap.py.

Two errors, both raised before anything is written anywhere:
ExtractorUnavailable when the endpoint could not be asked at all, and
ExtractionFailed when it answered but the payload is unusable. The bank
stays untouched; remember and recall keep working either way.

Recorded divergences: the donor's Ollama extractor sends a system and a
user message; this chassis's llm seam is one prompt-to-text callable,
so the two ride as one prompt, system first (how every chassis caller
composes its prompt). A timestamp without an offset reads as UTC,
matching the port's UTC posture everywhere. The post-filters are pure
functions here and the retain route applies them, so an injected
extractor is filtered identically to the endpoint-backed one (in the
donor the filters live inside the retain write).
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
UTC = timezone.utc  # datetime.UTC needs 3.11; the declared floor is 3.10

from nexuusbot.llm import LlmUnavailable
from nexuusbot.memory.knowledge_gap import is_assistant_knowledge_gap

MAX_FACT_CHARS = 2000
MAX_RETAINED_FACTS = 5
FACT_KINDS = ("world", "experience")
ENTITY_TYPES = ("person", "org", "place", "product", "concept", "other")


class ExtractorUnavailable(Exception):
    """The endpoint could not be asked at all. Nothing was written."""


class ExtractionFailed(Exception):
    """The endpoint answered but the payload is unusable. Nothing was
    written."""


@dataclass(frozen=True)
class CandidateFact:
    """One extracted candidate: what the inbox card would save.

    `occurrence_ts` is epoch seconds (the chassis stores epoch REAL
    timestamps, not the donor's ISO strings) and `entities` is a tuple
    of (name, type) pairs.
    """

    text: str
    kind: str = "world"
    occurrence_ts: float | None = None
    entities: tuple[tuple[str, str], ...] = ()


# -- the donor prompt (src/extract/prompt.ts, verbatim) ---------------------

EXTRACTION_SYSTEM_PROMPT = """You turn a conversation snippet into a few durable memory facts for a personal agent.

Reply with one JSON object and nothing else:
{
  "facts": [
    {
      "text": "narrative sentence",
      "kind": "world",
      "entities": [{ "name": "Full Name", "type": "person" }]
    }
  ]
}

How to write facts:
- Write 2 to 5 facts. Combine related details. Do not emit one fact per sentence when neighboring sentences belong together.
- Each fact is one or two plain sentences. Keep names, places, dates, and commitments. Drop small talk.
- kind "world" is about other people, organizations, places, products, or events.
- kind "experience" is only for something the agent itself did or decided. Write those in first person, starting with "I".
- The speaker line says who produced the snippet. That person's own life is "world" unless they are describing the agent's action.
- Only output occurrenceTime when the text names a specific past or scheduled occurrence, such as "we met Tuesday" or "the standup was on Nov 10 at 9am". Use an ISO-8601 timestamp for that occurrence.
- Omit occurrenceTime for preferences, standing facts, and undated statements. "9am works for me" is a preference, not an event time.
- Never use "now" or the current clock as occurrenceTime. Never copy mentioned_at into occurrenceTime.
- entities lists the people, organizations, places, products, and concepts named in that fact. type is one of: person, org, place, product, concept, other.
- Use the most specific name written in the snippet. Do not invent surnames. If two names in this snippet are the same person, use one spelling.
- Skip a fact that only reports your own lack of knowledge, or the assistant's or the model's. Do not emit "I don't know who Pepper is", "I do not have any information about that", or "I'm not sure who that is". Keep a real negative about someone else, such as "Maya does not have a preference for morning meetings".
- Do not add facts the snippet does not support.
- If nothing is worth keeping, return {"facts":[]}."""


def extraction_user_message(
    content: str,
    speaker: str = "",
    context: str = "",
    mentioned_at: str | None = None,
) -> str:
    """The donor's extractionUserMessage: the recording time, the
    speaker and the context on labeled lines, the content last."""
    return "\n".join(
        [
            "mentioned_at is when this text was recorded, not when an event "
            "happened. Do not copy it into occurrenceTime.",
            f"mentioned_at: {mentioned_at if mentioned_at else 'unknown'}",
            f"speaker: {speaker if speaker else 'unknown'}",
            f"context: {context if context else 'none'}",
            "content:",
            content,
        ]
    )


# -- the tolerant reply parse (src/extract/parse.ts) -------------------------


def strip_think_blocks(text: str) -> str:
    """Drop model reasoning blocks before JSON is parsed. A thinking
    field is never read."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


def model_json_object(content, error, subject: str) -> dict:
    """The parsed JSON object from one model reply, or `error` (the
    caller's failure class; `subject` names the caller in both
    messages). The shared tolerant parse behind the extractor and the
    reflector (tickets #91 and #93): think blocks strip first, then the
    slice from the first brace to the last brace is parsed, and a
    non-object payload refuses here."""
    if not isinstance(content, str):
        raise error(f"The {subject.lower()} reply was not text. Nothing was written.")
    stripped = strip_think_blocks(content)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end < start:
        raise error(
            f"{subject} did not return a JSON object. Nothing was written."
        )
    try:
        parsed = json.loads(stripped[start:end + 1])
    except ValueError:
        raise error(
            f"{subject} returned invalid JSON. Nothing was written."
        ) from None
    if not isinstance(parsed, dict):
        raise error(
            f"{subject} did not return a JSON object. Nothing was written."
        )
    return parsed


def parse_model_payload(content) -> list:
    """The facts array from one endpoint reply, or ExtractionFailed.

    The shared tolerant parse (model_json_object), then a strict shape
    check: an object with a facts array."""
    parsed = model_json_object(content, ExtractionFailed, "Extractor")
    if not isinstance(parsed.get("facts"), list):
        raise ExtractionFailed(
            "Extractor JSON must contain a facts array. Nothing was written."
        )
    return parsed["facts"]


# -- validation (src/extract/validate.ts) ------------------------------------


def normalize_extracted_facts(value) -> list[CandidateFact]:
    """Validates extractor output. The retain route decides which of
    these are kept."""
    if not isinstance(value, list):
        raise ExtractionFailed(
            "Extractor must return a list of facts. Nothing was written."
        )
    return [_normalize_fact(item) for item in value]


def _normalize_fact(item) -> CandidateFact:
    """One validated candidate: trimmed text, checked kind, parsed occurrence.

    Raises ExtractionFailed, and therefore writes nothing, for a non-object, a
    missing or blank text, a text over MAX_FACT_CHARS, a kind outside
    world/experience, a non-string occurrenceTime, or a bad entity list. An
    absent occurrenceTime stays None rather than defaulting to now.
    """
    if not isinstance(item, dict):
        raise ExtractionFailed("Each fact must be an object. Nothing was written.")
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ExtractionFailed("Each fact needs text. Nothing was written.")
    text = text.strip()
    if len(text) > MAX_FACT_CHARS:
        raise ExtractionFailed("A fact is too long to store. Nothing was written.")
    kind = item.get("kind")
    if kind not in FACT_KINDS:
        raise ExtractionFailed(
            'Fact kind must be "world" or "experience". Nothing was written.'
        )
    occurrence = item.get("occurrenceTime")
    occurrence_ts = None
    if occurrence is not None:
        if not isinstance(occurrence, str):
            raise ExtractionFailed(
                "occurrenceTime must be an ISO-8601 string or null."
                " Nothing was written."
            )
        occurrence_ts = _parse_occurrence(occurrence)
    return CandidateFact(
        text=text,
        kind=kind,
        occurrence_ts=occurrence_ts,
        entities=_normalize_entities(item.get("entities")),
    )


def _parse_occurrence(value: str) -> float:
    """One ISO-8601 string as epoch seconds. A timestamp without an
    offset reads as UTC (the chassis keeps UTC everywhere)."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise ExtractionFailed(
            "occurrenceTime must be an ISO-8601 string or null. Nothing was written."
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def _normalize_entities(value) -> tuple[tuple[str, str], ...]:
    """Validated (name, type) pairs, in the order the reply listed them.

    None means no entities and yields an empty tuple; any other non-list, or a
    list holding something without a non-blank name and a type from
    ENTITY_TYPES, raises ExtractionFailed before anything is written. Names are
    trimmed; duplicates are kept as given rather than folded.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ExtractionFailed("Fact entities must be a list. Nothing was written.")
    entities: list[tuple[str, str]] = []
    for entity in value:
        if not isinstance(entity, dict):
            raise ExtractionFailed(
                "Each entity needs a name and type. Nothing was written."
            )
        name = entity.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ExtractionFailed("Each entity needs a name. Nothing was written.")
        entity_type = entity.get("type")
        if entity_type not in ENTITY_TYPES:
            raise ExtractionFailed(
                f"Entity type must be one of: {', '.join(ENTITY_TYPES)}."
                " Nothing was written."
            )
        entities.append((name.strip(), entity_type))
    return tuple(entities)


# -- the retain post-filters (src/bank.ts) -----------------------------------


def facts_to_retain(candidates: list[CandidateFact]) -> list[CandidateFact]:
    """The donor's factsToRetain: assistant knowledge-gap texts dropped,
    at most five candidates kept."""
    kept = [c for c in candidates if not is_assistant_knowledge_gap(c.text)]
    return kept[:MAX_RETAINED_FACTS]


_WEEKDAY = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?"
    r"|dec(?:ember)?)"
)
_MONTH_THEN_DAY = re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b", re.I)
_DAY_THEN_MONTH = re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b", re.I)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?!\d)")
_NUMERIC_DATE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?(?!\d)|\b\d{1,2}-\d{1,2}-\d{4}\b")
_ORDINAL_DAY = re.compile(r"\b(?:on|the)\s+\d{1,2}(?:st|nd|rd|th)\b", re.I)
_RELATIVE_DAY = re.compile(
    r"\b(?:yesterday|today|tomorrow|tonight)\b|\bago\b|\b(?:this|last|next)\s+"
    r"(?:morning|afternoon|evening|night|week|month|year|monday|tuesday"
    r"|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)


def source_names_occurrence(text: str) -> bool:
    """True when the text names an occurrence in any of the donor's
    shapes: weekday, month-day, day-month, ISO date, numeric date,
    ordinal day, relative day."""
    return bool(
        _WEEKDAY.search(text)
        or _MONTH_THEN_DAY.search(text)
        or _DAY_THEN_MONTH.search(text)
        or _ISO_DATE.search(text)
        or _NUMERIC_DATE.search(text)
        or _ORDINAL_DAY.search(text)
        or _RELATIVE_DAY.search(text)
    )


def occurrence_from_source(content: str, extracted: float | None) -> float | None:
    """A clock time or a preference is not an occurrence. Missing stays
    None, never "now"."""
    if extracted is None:
        return None
    if not source_names_occurrence(content):
        return None
    return extracted


# -- the endpoint-backed implementation (src/extract/ollama.ts, adapted) -----


class EndpointExtractor:
    """The extractor port backed by the app's llm callable.

    One call, one prompt: the donor's system prompt verbatim, then the
    donor's user message. Endpoint failures map to ExtractorUnavailable
    with the llm seam's pinned plain-language cause; a reply that cannot
    be parsed or validated raises ExtractionFailed. Both leave the bank
    untouched. `last_request_bytes` is the size of the prompt that
    actually went out, for the audit row.
    """

    def __init__(self, llm) -> None:
        """Bind the prompt-to-text callable; nothing is called here.

        last_request_bytes starts at zero and only means anything once an
        extract call has set it.
        """
        self._llm = llm
        self.last_request_bytes = 0

    def extract(
        self,
        content: str,
        speaker: str = "",
        context: str = "",
        mentioned_at: str | None = None,
    ) -> list[CandidateFact]:
        """One extraction call: the system prompt, then the donor's user message.

        Returns candidates that still need the retain filters applied; this
        method writes nothing. Raises ExtractorUnavailable when the callable
        fails at all (LlmUnavailable keeps its pinned cause, any other exception
        becomes the generic one) and ExtractionFailed when the reply cannot be
        parsed or validated. last_request_bytes is set before the call, so a
        failed call still reports the prompt size it sent.
        """
        prompt = EXTRACTION_SYSTEM_PROMPT + "\n\n" + extraction_user_message(
            content, speaker=speaker, context=context, mentioned_at=mentioned_at
        )
        self.last_request_bytes = len(prompt.encode("utf-8"))
        try:
            reply = self._llm(prompt)
        except LlmUnavailable as exc:
            raise ExtractorUnavailable(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - one attempt, classified failure
            raise ExtractorUnavailable(
                "The endpoint did not answer, so nothing was extracted"
                " and nothing was written."
            ) from exc
        return normalize_extracted_facts(parse_model_payload(reply))
