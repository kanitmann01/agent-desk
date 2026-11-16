"""The reflect port: gathered facts in, cited observation drafts out.

Ticket #93 ports the donor's observation pipeline in three layers, all
pure unless noted. Provenance: the gathering from src/bank.ts
gatherFacts (with a query, hybrid recall of at most forty facts keeping
those scoring at least half the best; without, the forty most recent;
optional since inclusive and until exclusive bounds on the
occurrence-else-creation time; zero gathered is an error before any
model call), the system prompt and user-message shape from
src/reflector.ts (verbatim), the tolerant reply parse from the same
file (the shared model_json_object seam with the extractor), and the
acceptance filters from src/reflect.ts (speculative-word and
meta-comment regexes verbatim, confidence zero to one, citations a
subset of the gathered facts numbering two, one only in a single-entity
scope, near-duplicates dropped keeping the higher confidence, five at
most). The scope key joins entity, topic, query, since and until,
trimmed and lowercased, exactly like the donor's scopeKey.

Two errors on the model side, both raised before anything is written:
ReflectorUnavailable when the endpoint could not be asked at all, and
ReflectFailed when it answered but nothing usable came back. An empty
gather raises ReflectEmpty (a ReflectFailed) before the reflector is
asked, also writing nothing.

Recorded divergences: the donor's Ollama reflector sends a system and a
user message; this chassis's llm seam is one prompt-to-text callable,
so the two ride as one prompt, system first (how the extractor, its
sibling port, composes its prompt). Fact ids are the chassis's integer
row ids, so the draft's sourceFactIds parse as integers, tolerant of
digit strings the way the donor was of strings. The donor's
near-duplicate cosine leg (embedding cosine at least 0.85) needs
vectors, which arrive with ticket #95: the threshold constant and the
hook where it joins are in place, the arithmetic is not. The donor's
fact rows carry an ISO mentionedAt; this chassis renders created_ts as
UTC ISO-8601 for the prompt, matching the port's UTC posture.
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
UTC = timezone.utc  # datetime.UTC needs 3.11; the declared floor is 3.10

from agentdesk.llm import LlmUnavailable
from agentdesk.memory.core import Fact, normalize_fact_text
from agentdesk.memory.extract import model_json_object
from agentdesk.memory.hybrid import meaningful_tokens
from agentdesk.memory.knowledge_gap import is_assistant_knowledge_gap

GATHER_LIMIT = 40


class ReflectFailed(Exception):
    """The reflector answered but nothing usable came back. Nothing was
    written."""


class ReflectEmpty(ReflectFailed):
    """Nothing gathered in the asked scope, refused before any model
    call. Nothing was written."""


class ReflectorUnavailable(Exception):
    """The endpoint could not be asked at all. Nothing was written."""


EMPTY_SCOPE_CAUSE = (
    "reflect found no facts in that scope. Nothing was written."
)
NOTHING_ACCEPTED_CAUSE = (
    "Reflector returned no observation that cites the gathered facts."
    " Nothing was written."
)


@dataclass(frozen=True)
class ObservationDraft:
    """One reflector proposal: what the inbox card would save, how
    confident the model claimed to be, and which gathered facts it
    cites. An unusable draft reads as empty text, a NaN confidence and
    no citations, which the acceptance filters then drop."""

    text: str
    confidence: float
    fact_ids: tuple[int, ...] = ()


# -- gathering (src/bank.ts gatherFacts) --------------------------------------


def gather_facts(
    query: str,
    recalled: list[tuple[float, Fact]] | None,
    facts: list[Fact] | None,
    since: float | None = None,
    until: float | None = None,
) -> list[Fact]:
    """The facts one reflect run sees: with a query the hybrid recall
    path, without it the recency path; empty in either is a
    ReflectEmpty raised before any model call."""
    if query.strip():
        rows = _gather_recalled(recalled or [], since, until)
    else:
        rows = _gather_recent(facts or [], since, until)
    if not rows:
        raise ReflectEmpty(EMPTY_SCOPE_CAUSE)
    return rows


def _gather_recalled(
    recalled: list[tuple[float, Fact]],
    since: float | None,
    until: float | None,
) -> list[Fact]:
    """The donor's query path: at most forty recalled facts (the recall
    arrives best first), the zero scores out, then everyone scoring at
    least half the best. The donor also drops derived facts here; in
    this chassis nothing derives facts, so every recalled row is a
    base fact already."""
    ranked = [(score, fact) for score, fact in recalled if score > 0]
    ranked = ranked[:GATHER_LIMIT]
    best = max((score for score, _fact in ranked), default=0.0)
    cutoff = best * 0.5
    return _filter_window(
        [fact for score, fact in ranked if score >= cutoff], since, until
    )


def _gather_recent(
    facts: list[Fact], since: float | None, until: float | None
) -> list[Fact]:
    """The donor's no-query path: the forty most recent facts by
    creation time, newest first (id descending on a tie, so a later row
    wins like the donor's insertion order would)."""
    rows = sorted(facts, key=lambda fact: (-fact.created_ts, -fact.id))
    return _filter_window(rows[:GATHER_LIMIT], since, until)


def _filter_window(
    rows: list[Fact], since: float | None, until: float | None
) -> list[Fact]:
    """The donor's window: since inclusive, until exclusive, judged on
    the occurrence time when the fact carries one and the creation time
    when it does not."""
    if since is None and until is None:
        return rows
    kept = []
    for fact in rows:
        when = (
            fact.occurrence_ts
            if fact.occurrence_ts is not None
            else fact.created_ts
        )
        if since is not None and when < since:
            continue
        if until is not None and when >= until:
            continue
        kept.append(fact)
    return kept


# -- the scope key (src/reflect.ts scopeKey) ----------------------------------


def scope_key(
    entity: str = "",
    topic: str = "",
    query: str = "",
    since: float | None = None,
    until: float | None = None,
) -> str:
    """The identity one re-reflect upserts against: the five scope
    parts, each trimmed and lowercased, joined with newlines in the
    donor's order (entity, topic, query, since, until)."""
    parts = (
        entity,
        topic,
        query,
        "" if since is None else str(float(since)),
        "" if until is None else str(float(until)),
    )
    return "\n".join(part.strip().lower() for part in parts)


# -- the acceptance filters (src/reflect.ts) ----------------------------------

# Both patterns are the donor's, verbatim.
_SPECULATIVE = re.compile(
    r"\b(?:suggest(?:s|ed|ing)?|indicat(?:e|es|ed|ing)|seem(?:s|ed|ing)?"
    r"|appear(?:s|ed|ing)?|might|may|possibly|probably|likely|perhaps|could)\b",
    re.IGNORECASE,
)
_META = re.compile(
    r"\b(?:separate from|separately from|mentioned in the context"
    r"|in the context of|unrelated to|distinct from|as opposed to"
    r"|not related to)\b",
    re.IGNORECASE,
)

MAX_OBSERVATIONS = 5

"""Token overlap above this is the same observation said twice."""
TEXT_SIMILARITY = 0.55

# The embedding cosine at or above which two drafts are the same
# observation. Unused until #95 ships the vectors; kept so the port's
# threshold reads in one place. (Ticket #95: the cosine leg joins in
# _same_observation, keyed by each draft's normalized text.)
VECTOR_SIMILARITY = 0.85


def is_low_value_observation(text: str) -> bool:
    """Meta comments and hedged guesses are not observations."""
    return bool(_SPECULATIVE.search(text) or _META.search(text))


def accept_observations(
    drafts: list[ObservationDraft],
    allowed_ids: set[int],
    max_observations: int = MAX_OBSERVATIONS,
    single_entity: bool = False,
) -> list[ObservationDraft]:
    """The donor's acceptObservations: drop drafts that cite nothing,
    cite a fact outside the gather, fail the junk or low-value filter,
    or have no text; collapse near-duplicates keeping the higher
    confidence; refuse when nothing survived so the caller writes
    nothing; cap the rest at max_observations, highest confidence
    first. Two citations are required except in a single-entity scope,
    and never demanded when only one fact was gathered."""
    require_two = not single_entity and len(allowed_ids) >= 2
    accepted: list[ObservationDraft] = []
    for draft in drafts:
        text = draft.text.strip()
        if not normalize_fact_text(text):
            continue
        if is_assistant_knowledge_gap(text) or is_low_value_observation(text):
            continue
        if not math.isfinite(draft.confidence) or not 0 <= draft.confidence <= 1:
            continue
        fact_ids = list(dict.fromkeys(draft.fact_ids))
        if not fact_ids:
            continue
        if any(fact_id not in allowed_ids for fact_id in fact_ids):
            continue
        if require_two and len(fact_ids) < 2:
            continue
        accepted.append(
            ObservationDraft(
                text=text, confidence=draft.confidence, fact_ids=tuple(fact_ids)
            )
        )
    unique = _drop_near_duplicates(accepted)
    if not unique:
        raise ReflectFailed(NOTHING_ACCEPTED_CAUSE)
    return unique[:max_observations]


def _drop_near_duplicates(
    drafts: list[ObservationDraft],
) -> list[ObservationDraft]:
    """Highest confidence first, then keep the first of every
    near-duplicate group (the donor's dropNearDuplicates order)."""
    ranked = sorted(drafts, key=lambda draft: -draft.confidence)
    kept: list[ObservationDraft] = []
    for draft in ranked:
        if not any(_same_observation(prior, draft) for prior in kept):
            kept.append(draft)
    return kept


def _same_observation(left: ObservationDraft, right: ObservationDraft) -> bool:
    """Two drafts are the same observation when their normalized texts
    are equal or their meaningful tokens overlap enough. (Ticket #95:
    the embedding cosine leg joins here, VECTOR_SIMILARITY over the
    drafts' vectors, once vectors exist.)"""
    if normalize_fact_text(left.text) == normalize_fact_text(right.text):
        return True
    return _token_similarity(left.text, right.text) >= TEXT_SIMILARITY


def _token_similarity(left: str, right: str) -> float:
    """Jaccard over the meaningful tokens (the donor's
    tokenSimilarity): shared tokens over the union."""
    a = set(meaningful_tokens(left))
    b = set(meaningful_tokens(right))
    if not a or not b:
        return 0.0
    shared = len(a & b)
    return shared / (len(a) + len(b) - shared)


# -- the donor prompt (src/reflector.ts, verbatim) ----------------------------

REFLECT_SYSTEM_PROMPT = """You write durable observations about the topic from the facts listed.
Reply with JSON only:
{"observations":[{"text":"...","confidence":0.0,"sourceFactIds":["..."]}]}
Quality:
- One observation per distinct pattern. Do not restate one pattern in different words.
- Cite at least two facts. A single fact is not an observation.
- State the pattern directly. No hedging and no words such as suggesting, indicating, seems, might, or possibly.
- Do not restate a single fact in new words.
- Do not write meta comments such as "X is separate from Y" or "mentioned in the context of".
- Use only facts about the topic. Ignore the rest.
- confidence is from 0 to 1. At most 5 observations.
- Do not say the assistant lacks knowledge or just did something in this chat."""


def _iso_created(created_ts: float) -> str:
    """A fact's creation time as the donor's message shows a
    mentionedAt: one UTC ISO-8601 string."""
    return datetime.fromtimestamp(created_ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def reflect_user_message(topic: str, facts: list[Fact]) -> str:
    """The donor's reflectUserMessage: the optional topic on its own
    line, then one pipe-separated line per gathered fact, id, kind,
    creation time and text."""
    topic_line = f"Topic: {topic.strip()}\n\n" if topic.strip() else ""
    lines = [
        f"{fact.id} | {fact.kind} | {_iso_created(fact.created_ts)} | {fact.text}"
        for fact in facts
    ]
    return f"{topic_line}Facts:\n" + "\n".join(lines)


# -- the tolerant reply parse (src/reflector.ts readObservations) -------------


def parse_reflection_payload(content) -> list[ObservationDraft]:
    """The observations array from one reflector reply, or
    ReflectFailed. The shared tolerant parse (extract's
    model_json_object), then a strict shape check: an object with an
    observations array."""
    parsed = model_json_object(content, ReflectFailed, "Reflector")
    drafts = parsed.get("observations")
    if not isinstance(drafts, list):
        raise ReflectFailed(
            "Reflector JSON must contain an observations array."
            " Nothing was written."
        )
    return [_read_draft(item) for item in drafts]


def _read_draft(value) -> ObservationDraft:
    """One draft entry, or the empty draft the filters drop. Fact ids
    read as integers, digit strings included; anything else in the
    list is ignored."""
    if not isinstance(value, dict):
        return ObservationDraft(text="", confidence=float("nan"), fact_ids=())
    text = value.get("text")
    text = text.strip() if isinstance(text, str) else ""
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = float("nan")
    raw_ids = value.get("sourceFactIds")
    fact_ids: list[int] = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                fact_ids.append(item)
            elif isinstance(item, str):
                try:
                    fact_ids.append(int(item.strip()))
                except ValueError:
                    continue
    return ObservationDraft(
        text=text, confidence=float(confidence), fact_ids=tuple(fact_ids)
    )


# -- the scope window's date parsing (the reflect form) -----------------------


def parse_scope_date(value) -> float | None:
    """One since/until form value as epoch seconds: an ISO-8601 date or
    timestamp, blank means unbounded, a timestamp without an offset
    reads as UTC (the chassis keeps UTC everywhere), anything else is a
    ValueError the route answers in plain language."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(
            "since and until must be ISO-8601 dates, like 2026-11-01."
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


# -- the endpoint-backed implementation (src/reflector.ts, adapted) -----------


class EndpointReflector:
    """The reflector port backed by the app's llm callable, the
    extractor port's sibling (ticket #91). One call, one prompt: the
    donor's system prompt verbatim, then the donor's user message over
    the gathered facts. Endpoint failures map to ReflectorUnavailable
    with the llm seam's pinned plain-language cause; a reply that
    cannot be parsed raises ReflectFailed. Both leave the bank
    untouched. `last_request_bytes` is the size of the prompt that
    actually went out, for the audit row."""

    def __init__(self, llm) -> None:
        self._llm = llm
        self.last_request_bytes = 0

    def reflect(self, topic: str, facts: list[Fact]) -> list[ObservationDraft]:
        prompt = REFLECT_SYSTEM_PROMPT + "\n\n" + reflect_user_message(topic, facts)
        self.last_request_bytes = len(prompt.encode("utf-8"))
        try:
            reply = self._llm(prompt)
        except LlmUnavailable as exc:
            raise ReflectorUnavailable(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - one attempt, classified failure
            raise ReflectorUnavailable(
                "The endpoint did not answer, so nothing was reflected"
                " and nothing was written."
            ) from exc
        return parse_reflection_payload(reply)
