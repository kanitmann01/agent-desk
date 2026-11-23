"""The memory loop: capture, store, process and remove, end to end.

Before this module a fact arrived only when the user typed it on the
Memory page or chose "Save to memory" on a conversation. The loop makes
memory follow what the user actually does:

1. Capture. Whatever flows through the server on a channel the user left
   on (an Assistant question and its answer, a Research question and its
   sourced summary) is offered to the extractor. The configured company
   endpoint extracts first (memory/extract's EndpointExtractor, the same
   prompt the manual save uses); when no endpoint answers, the
   deterministic rules below take the user's own words instead, so
   capture still works offline. Candidates already stored or already
   waiting are skipped.
2. Approval. In review mode (the default) each candidate becomes the
   same memory_draft inbox card the manual save makes, and nothing is
   written until the user approves it. In automatic mode the candidate
   is stored at once, through the same write as an approval.
3. Storing. One write path for every fact (store_fact): the store's
   normalized dedupe, the excerpt the fact came from, entity resolution.
4. Processing. After every write: a newer fact that states a different
   value for the same thing replaces the older one (the older one stays
   visible and can be kept, recall skips it), and each entity mentioned
   by two or more standing facts gets one consolidated observation that
   cites them, rewritten whenever its facts change.
5. Removal. A fact, an excerpt with every fact taken from it, an entity
   with every fact that mentions it, or an observation. The plan names
   everything else that changes before anything is written; the removal
   is one transaction that dumps what it touched, so it can be undone
   for a short window.

The settings live in the ordinary settings store (memory_capture,
memory_auto_approve and one switch per channel), so nothing here is
hard-coded to a user.
"""

from __future__ import annotations

import re
import secrets
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from agentdesk.memory.core import Fact, UnknownEntity, UnknownFact, normalize_fact_text
from agentdesk.memory.extract import (
    CandidateFact,
    facts_to_retain,
    model_json_object,
)

# -- capture settings -------------------------------------------------------

# Channel id, the label the page shows, and the settings switch for it.
CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("assistant", "Assistant", "memory_capture_assistant"),
    ("research", "Research", "memory_capture_research"),
    # Rows that change in the watched sales workbook (the excel watch's
    # poll delta): structured, so the facts are written from the cells
    # directly, no extraction call.
    ("workbook", "Workbook tracker", "memory_capture_workbook"),
    # Run feedback (the agents page's "how did it land?" form): the run's
    # transcript is offered with the user's feedback as their own words,
    # so what one run learned the next one recalls.
    ("agents", "Agents", "memory_capture_agents"),
)
CHANNEL_LABELS = {channel: label for channel, label, _key in CHANNELS}
METHOD_MODEL = "model"
METHOD_RULES = "rules"
AUTO_SOURCE_PREFIX = "auto: "
ENTITY_SCOPE_PREFIX = "entity:"
UNDO_WINDOW_S = 30.0
MAX_CONSOLIDATED_FACTS = 6


@dataclass(frozen=True)
class CaptureSettings:
    enabled: bool = True
    auto_approve: bool = False
    channels: frozenset[str] = frozenset(channel for channel, _l, _k in CHANNELS)

    def captures(self, channel: str) -> bool:
        """Whether capture runs on this channel: the master switch and the
        channel's own switch both on.

        An id outside CHANNELS is off, because only those ids can ever be in
        the set.
        """
        return self.enabled and channel in self.channels

    def to_json(self) -> dict:
        """The Memory page's shape: the two switches and one row per channel.

        Every channel in CHANNELS is listed even when the master switch is off,
        so the page can draw the per-channel switches without knowing the
        roster; the keys are the camelCase ones the client reads.
        """
        return {
            "enabled": self.enabled,
            "autoApprove": self.auto_approve,
            "channels": [
                {"id": channel, "label": label, "setting": key,
                 "on": channel in self.channels}
                for channel, label, key in CHANNELS
            ],
        }


def capture_settings(settings) -> CaptureSettings:
    """Read the loop's switches from the settings store (None: defaults)."""
    if settings is None:
        return CaptureSettings()
    return CaptureSettings(
        enabled=bool(settings.get("memory_capture")),
        auto_approve=bool(settings.get("memory_auto_approve")),
        channels=frozenset(
            channel for channel, _label, key in CHANNELS if bool(settings.get(key))
        ),
    )


# -- the deterministic extractor (the fallback when no endpoint answers) ----

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_LEAD_INS = re.compile(
    r"^(?:please\s+)?(?:remember|note|fyi|for the record|keep in mind|just so you know)"
    r"(?:\s+that)?[:,]?\s+",
    re.I,
)
_QUESTION_START = re.compile(
    r"^(?:what|how|why|when|where|who|whom|which|can|could|would|should|do|does|did"
    r"|is|are|was|were|will|shall|may|might|have|has)\b",
    re.I,
)
_REQUEST_START = re.compile(
    r"^(?:please|show|tell|give|list|find|summari[sz]e|help|explain|draft|write"
    r"|create|make|open|compare|check|look|search|send|book|remind|let'?s|can you"
    r"|could you|thanks|thank you|hi|hello|hey|ok|okay|sure)\b",
    re.I,
)
_STATEMENT_VERB = re.compile(
    r"\b(?:is|are|was|were|has|have|had|owns?|leads?|manages?|runs?|prefers?|likes?"
    r"|uses?|works?|lives?|due|will|moved|joined|left|signed|agreed|decided"
    r"|scheduled|needs?|wants?|reports?|closed|renewed|starts?|ends?|costs?"
    r"|totals?|grew|fell|rose|ships?|belongs?|met|said|plans?|expects?|stays?"
    r"|goes|went|became|becomes|holds?|keeps?|takes?|took|meets?|[a-z]{3,}ed)\b",
    re.I,
)
_HAS_DIGIT = re.compile(r"\d")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&'.-]*")
_ORG_SUFFIX = re.compile(r"\b(?:inc|corp|corporation|ltd|llc|plc|gmbh|co|group|bank|labs?)\.?$", re.I)
_NOT_NAMES = {
    "i", "we", "you", "they", "he", "she", "it", "our", "my", "the", "a", "an",
    "this", "that", "these", "those", "their", "his", "her", "its", "and", "but",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "q1", "q2", "q3", "q4",
    "today", "tomorrow", "yesterday", "also", "then", "so", "if", "in", "on", "at",
    "for", "to", "of", "by", "with", "from", "remember", "note",
}
MAX_RULE_SENTENCE_CHARS = 400
MIN_RULE_SENTENCE_CHARS = 12


def _names_in(sentence: str) -> tuple[tuple[str, str], ...]:
    """Capitalized runs read as named things. Sentence-initial words count
    only when they are not common lead words; months, weekdays and
    pronouns never name anything."""
    words = _WORD.findall(sentence)
    names: list[tuple[str, str]] = []
    run: list[str] = []

    def flush() -> None:
        """Close the current capitalized run as one name, if it is one.

        The run is trimmed of trailing periods, refused when it is a common
        word (pronoun, month, weekday, filler), typed "org" when it ends like a
        company name, and skipped when that name is already in the list.
        """
        if run:
            name = " ".join(run).strip(".")
            if name and name.lower() not in _NOT_NAMES:
                kind = "org" if _ORG_SUFFIX.search(name) else "other"
                if all(n.lower() != name.lower() for n, _t in names):
                    names.append((name, kind))
            run.clear()

    for word in words:
        bare = word.strip(".'")
        if bare[:1].isupper() and bare.lower() not in _NOT_NAMES and len(bare) > 1:
            run.append(bare)
        else:
            flush()
    flush()
    return tuple(names[:6])


def names_in(text: str) -> tuple[tuple[str, str], ...]:
    """The named things a typed fact mentions, for entity linking."""
    return _names_in(" ".join((text or "").split()))


def rule_candidates(text: str) -> list[CandidateFact]:
    """Statements worth remembering in the user's own words: declarative
    sentences that name something (a capitalized name or a number) and
    say something about it. Questions, requests and small talk are
    dropped; "remember that ..." lead-ins are trimmed. World facts only:
    the user's own life is world knowledge, not the agent's experience."""
    candidates: list[CandidateFact] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(text or ""):
        sentence = " ".join(raw.split()).strip(" -*\u2022")
        sentence = _LEAD_INS.sub("", sentence)
        if not (MIN_RULE_SENTENCE_CHARS <= len(sentence) <= MAX_RULE_SENTENCE_CHARS):
            continue
        if sentence.endswith("?") or _QUESTION_START.match(sentence):
            continue
        if _REQUEST_START.match(sentence):
            continue
        if not _STATEMENT_VERB.search(sentence):
            continue
        names = _names_in(sentence)
        if not names and not _HAS_DIGIT.search(sentence):
            continue
        sentence = sentence.rstrip(";")
        if sentence[-1] not in ".!":
            sentence += "."
        sentence = sentence[0].upper() + sentence[1:]
        key = normalize_fact_text(sentence)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(CandidateFact(text=sentence, kind="world", entities=names))
    return facts_to_retain(candidates)


# -- processing: replacement and consolidation -------------------------------

_VALUE = re.compile(
    r"^(?:\$?\d[\d,.]*(?:k|m|bn|%|st|nd|rd|th)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?"
    r"|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?"
    r"|nov(?:ember)?|dec(?:ember)?|monday|tuesday|wednesday|thursday|friday"
    r"|saturday|sunday|today|tomorrow|yesterday|q[1-4])$",
    re.I,
)
_TOKEN = re.compile(r"\$?[a-z0-9][a-z0-9,.%$]*", re.I)
_FILLER = {"the", "a", "an", "of", "to", "and", "is", "are", "was", "were", "on",
           "in", "at", "for", "by", "now", "be", "it", "its", "this", "that"}
REPLACE_FRAME_SIMILARITY = 0.6


def _split_tokens(text: str) -> tuple[set[str], set[str]]:
    """(frame words, value words) of a fact: values are numbers, amounts,
    dates and days; the frame is what the sentence is about."""
    frame: set[str] = set()
    values: set[str] = set()
    for token in _TOKEN.findall(text.lower()):
        token = token.strip(".,")
        if not token:
            continue
        if _VALUE.match(token):
            values.add(token)
        elif token not in _FILLER:
            frame.add(token)
    return frame, values


def replaces(newer: str, older: str) -> bool:
    """True when the newer fact restates the older one with a different
    value: the same frame (Jaccard at least 0.6 over the non-value words)
    and both carry values that differ. "The Acme renewal is due December
    1" is replaced by "The Acme renewal is due December 15"."""
    new_frame, new_values = _split_tokens(newer)
    old_frame, old_values = _split_tokens(older)
    if not new_values or not old_values or new_values == old_values:
        return False
    union = new_frame | old_frame
    if not union:
        return False
    return len(new_frame & old_frame) / len(union) >= REPLACE_FRAME_SIMILARITY


def counted(n: int, noun: str, plural: str | None = None) -> str:
    """"1 fact", "2 facts": the audit rows read as plain English."""
    return f"{n} {noun if n == 1 else (plural or noun + 's')}"


# -- processing: one observation per entity ---------------------------------

MAX_SUMMARY_CHARS = 300
MAX_SUMMARY_INPUT_FACTS = 12
# How many entities one model pass rewrites; the rest wait for the next.
MAX_MODEL_SUMMARIES_PER_PASS = 8


@dataclass(frozen=True)
class Summary:
    """One entity's observation: the text, the facts it cites, who wrote
    it (METHOD_MODEL or METHOD_RULES) and the standing facts it was built
    from (the basis a rebuild compares against)."""
    text: str
    fact_ids: tuple[int, ...]
    method: str
    basis: frozenset[int] = frozenset()


class SummaryFailed(Exception):
    """The endpoint gave no usable observation; the rules write it."""


def _when(fact: Fact) -> float:
    """The instant a fact is ordered by: its occurrence, else its creation.

    A dated fact sorts by when the thing happened and an undated one by when it
    was recorded, so "we met Tuesday" does not outrank a fact written just now
    simply because it was extracted later.
    """
    return fact.occurrence_ts if fact.occurrence_ts is not None else fact.created_ts


def newest_first(facts: Iterable[Fact]) -> list[Fact]:
    """The facts newest first by occurrence-or-creation, then creation, then id.

    The id tiebreak makes the order total, so two facts sharing an instant
    always sort alike and an observation's text does not depend on the order the
    rows happened to arrive in.
    """
    return sorted(facts, key=lambda fact: (_when(fact), fact.created_ts, fact.id), reverse=True)


def _day(fact: Fact) -> str:
    """The fact's date as "Nov 18", in the process's local time zone.

    Local rather than UTC because this is display text for the reader, and it is
    never compared or stored.
    """
    moment = datetime.fromtimestamp(_when(fact))
    return f"{moment:%b} {moment.day}"


def _sentence(text: str) -> str:
    """The text as one line that ends in sentence punctuation.

    Whitespace is collapsed, trailing separators dropped, and a period appended
    when the text ended in none, so a fact pasted into a summary never runs into
    the next sentence.
    """
    text = " ".join(text.split()).rstrip(";,: ")
    return text if text.endswith((".", "!", "?")) else text + "."


def rule_summary(name: str, facts: list[Fact]) -> Summary:
    """The deterministic observation: how much is known, then the newest
    state and the one before it. Never a list of every fact."""
    ordered = newest_first(facts)
    basis = ordered[:MAX_CONSOLIDATED_FACTS]
    text = f"{counted(len(ordered), 'fact')} about {name}. Latest, {_day(ordered[0])}: {_sentence(ordered[0].text)}"
    if len(ordered) > 1:
        same_day = _day(ordered[1]) == _day(ordered[0])
        when = "Before that" if same_day else f"Before that, {_day(ordered[1])}"
        before = f" {when}: {_sentence(ordered[1].text)}"
        if len(text) + len(before) <= MAX_SUMMARY_CHARS:
            text += before
    return Summary(
        text=text[:MAX_SUMMARY_CHARS],
        fact_ids=tuple(fact.id for fact in basis),
        method=METHOD_RULES,
        basis=frozenset(fact.id for fact in basis),
    )


SUMMARY_PROMPT = """You keep one short observation about {name} in a work assistant's memory.
Read the facts below, newest first, and say what they add up to right now.
Rules:
- One or two plain sentences, at most 240 characters in total.
- Where facts disagree, the newest one wins: state the current position, not the history.
- Do not list the facts back. No hedging, no preamble, no quotation marks.
Reply with JSON only: {{"text":"...","sourceFactIds":[the ids you relied on]}}

Facts (id | date | text):
{lines}"""


class EndpointSummarizer:
    """The model-written observation, through the app's llm callable (the
    reflector's sibling). One call per entity; any failure raises
    SummaryFailed and the rules write the observation instead.
    `last_request_bytes` and `calls` feed the audit row."""

    def __init__(self, llm) -> None:
        """Bind the prompt-to-text callable; no call is made here.

        Both counters start at zero and accumulate for the life of the object:
        calls counts requests, last_request_bytes the prompt bytes sent in
        total, which is what the audit row reports as the cost of a pass.
        """
        self._llm = llm
        self.last_request_bytes = 0
        self.calls = 0

    def prompt(self, name: str, facts: list[Fact]) -> str:
        """The summary prompt for one entity, one "id | date | text" line per fact.

        The facts are rendered in the order given: no ordering happens here, so
        the caller is responsible for the newest-first list the instructions
        assume.
        """
        lines = "\n".join(
            f"{fact.id} | {_day(fact)} | {' '.join(fact.text.split())}"
            for fact in facts
        )
        return SUMMARY_PROMPT.format(name=name, lines=lines)

    def __call__(self, name: str, facts: list[Fact]) -> Summary:
        """One summarizer call: a Summary, or SummaryFailed and nothing written.

        The prompt shows at most MAX_SUMMARY_INPUT_FACTS facts while the basis
        records the newer MAX_CONSOLIDATED_FACTS, so a cited id must be one of
        the shown facts; ids outside that set are dropped, and a reply citing
        none falls back to the whole basis. Any endpoint exception, empty text or
        text over MAX_SUMMARY_CHARS raises, and the caller writes the rules'
        observation instead.
        """
        ordered = newest_first(facts)
        basis = ordered[:MAX_CONSOLIDATED_FACTS]
        shown = ordered[:MAX_SUMMARY_INPUT_FACTS]
        prompt = self.prompt(name, shown)
        self.last_request_bytes += len(prompt.encode("utf-8"))
        self.calls += 1
        try:
            reply = self._llm(prompt)
        except Exception as exc:  # noqa: BLE001 - any endpoint failure falls back to the rules
            raise SummaryFailed(str(exc)[:200] or "The endpoint did not answer.") from exc
        parsed = model_json_object(reply, SummaryFailed, "Summarizer")
        text = " ".join(str(parsed.get("text") or "").split()).strip('"')
        if not normalize_fact_text(text):
            raise SummaryFailed("The endpoint returned no observation text.")
        if len(text) > MAX_SUMMARY_CHARS:
            raise SummaryFailed("The endpoint's observation was longer than the limit.")
        allowed = {fact.id for fact in shown}
        cited: list[int] = []
        for value in parsed.get("sourceFactIds") or []:
            try:
                fact_id = int(str(value).strip())
            except ValueError:
                continue
            if fact_id in allowed and fact_id not in cited:
                cited.append(fact_id)
        return Summary(
            text=text,
            fact_ids=tuple(cited) if cited else tuple(fact.id for fact in basis),
            method=METHOD_MODEL,
            basis=frozenset(fact.id for fact in basis),
        )


Summarize = Callable[[str, list[Fact]], Summary]


def entity_scope(entity_id: int) -> str:
    """The observation scope string for an entity: "entity:<id>".

    Observations are looked up by scope, so this prefix is the namespace that
    keeps an entity-derived observation apart from every other scope a write
    might use.
    """
    return f"{ENTITY_SCOPE_PREFIX}{int(entity_id)}"


@dataclass(frozen=True)
class EntityBasis:
    entity_id: int
    name: str
    facts: tuple[Fact, ...]  # standing facts, newest first, at most MAX_CONSOLIDATED_FACTS

    @property
    def scope(self) -> str:
        """The observation scope this entity's observation is stored under.

        In phase 4 the scope is the observation's identity: an entity keeps at
        most one observation, and this string is how a later run finds it again.
        """
        return entity_scope(self.entity_id)

    @property
    def basis(self) -> frozenset[int]:
        """The standing fact ids the observation is built from.

        A frozenset rather than a list because freshness compares it by value:
        the same facts in another order are the same basis, so a reordering does
        not rewrite the observation.
        """
        return frozenset(fact.id for fact in self.facts)


def entity_bases(memory, without: Iterable[int] = ()) -> tuple[list[EntityBasis], list[int]]:
    """(the entities that earn an observation, every entity id). An entity
    earns one when two or more standing (not replaced) facts mention it.
    Two entities whose standing facts are the same set share one
    observation: the entity with more facts (then the lower id) keeps it,
    so the graph never shows the same observation twice. `without`
    simulates a removal: those facts are gone, and the facts they
    replaced stand again."""
    gone = {int(f) for f in without}
    names = {entity.id: entity.canonical_name for entity in memory.entities()}
    replaced = {
        old: new for old, new in memory.superseded_map().items()
        if new not in gone
    }
    facts = {fact.id: fact for fact in memory.all() if fact.id not in gone}
    by_entity: dict[int, list[Fact]] = {}
    for fact_id, entity_ids in memory.fact_entity_ids().items():
        if fact_id not in facts or fact_id in replaced:
            continue
        for entity_id in entity_ids:
            by_entity.setdefault(entity_id, []).append(facts[fact_id])
    candidates = sorted(
        (
            (entity_id, standing) for entity_id, standing in by_entity.items()
            if entity_id in names and len(standing) >= 2
        ),
        key=lambda item: (-len(item[1]), item[0]),
    )
    kept: list[EntityBasis] = []
    claimed: set[frozenset[int]] = set()
    for entity_id, standing in candidates:
        ordered = tuple(newest_first(standing)[:MAX_CONSOLIDATED_FACTS])
        key = frozenset(fact.id for fact in standing)
        if key in claimed:
            continue
        claimed.add(key)
        kept.append(EntityBasis(entity_id=entity_id, name=names[entity_id], facts=ordered))
    return kept, sorted(names)


@dataclass(frozen=True)
class ProcessOutcome:
    replaced: tuple[int, ...] = ()
    observations_saved: tuple[int, ...] = ()
    observations_removed: tuple[int, ...] = ()
    # Old ids a rewrite replaced (the new id is in observations_saved):
    # the same observation to the user, not a removal.
    observations_rewritten: tuple[int, ...] = ()
    model_written: int = 0
    model_failure: str = ""


def _observation_state(memory, kept: list[EntityBasis], all_ids: list[int]):
    """(scope -> observation ids, marks, stale ids) for the entity scopes."""
    scope_of = memory.scope_of_observations(entity_scope(eid) for eid in all_ids)
    by_scope: dict[str, list[int]] = {}
    for observation_id, scope in sorted(scope_of.items()):
        by_scope.setdefault(scope, []).append(observation_id)
    return by_scope, memory.observation_marks(), set(memory.stale_observations())


def _is_fresh(entry: EntityBasis, by_scope, marks, stale) -> tuple[bool, str | None]:
    """(fresh, method) for one entity in phase 4: whether its observation stands.

    Fresh requires exactly one observation at the entity's scope, that
    observation not flagged stale, and the basis recorded for it equal to
    entry.basis. The second element is the method that observation was written
    with, None when there is no observation to read one from.
    """
    existing = by_scope.get(entry.scope, [])
    if len(existing) != 1 or existing[0] in stale:
        return False, None
    method, basis = marks.get(existing[0], (None, frozenset()))
    return basis == entry.basis, method


def model_summaries(memory, summarize: Summarize,
                    limit: int = MAX_MODEL_SUMMARIES_PER_PASS) -> tuple[dict[str, Summary], int, str]:
    """Ask the endpoint for the observations that need it: built from
    changed facts, or written by the rules. Nothing is written here, so
    the store is never locked across a model call. Returns (scope ->
    summary, how many were asked, the first failure); asking stops at the
    first failure or after `limit`."""
    kept, all_ids = entity_bases(memory)
    by_scope, marks, stale = _observation_state(memory, kept, all_ids)
    out: dict[str, Summary] = {}
    asked = 0
    for entry in kept:
        fresh, method = _is_fresh(entry, by_scope, marks, stale)
        if fresh and method == METHOD_MODEL:
            continue
        if asked >= limit:
            break
        asked += 1
        try:
            out[entry.scope] = summarize(entry.name, list(entry.facts))
        except SummaryFailed as exc:
            return out, asked, str(exc) or "The endpoint did not answer."
    return out, asked, ""


def reconcile_observations(
    memory,
    summarize: Summarize | None = None,
    planned: dict[str, Summary] | None = None,
) -> ProcessOutcome:
    """Bring every entity's observation in line with its standing facts.

    With `summarize` (the endpoint), the observations that need it are
    written by the model first (model_summaries, outside any lock). The
    write itself holds the store's lock end to end, so two passes never
    interleave: an observation whose basis is unchanged stays (unless a
    model summary for that same basis is offered and the rules wrote
    it); a changed one is written from the offered summary when it was
    built from the same facts (`planned`: the removal preview's text, or
    the model's), else by the rules. Entities that no longer earn one
    lose theirs. Idempotent."""
    offered = dict(planned or {})
    model_written, failure = 0, ""
    if summarize is not None:
        asked, _count, failure = model_summaries(memory, summarize)
        model_written = len(asked)
        offered = {**asked, **offered}
    saved: list[int] = []
    removed: list[int] = []
    rewritten: list[int] = []
    with memory.exclusive():
        kept, all_ids = entity_bases(memory)
        by_scope, marks, stale = _observation_state(memory, kept, all_ids)
        wanted = {entry.scope for entry in kept}
        for scope, observation_ids in by_scope.items():
            if scope not in wanted:
                removed.extend(memory.delete_observations(observation_ids))
        for entry in kept:
            existing = by_scope.get(entry.scope, [])
            fresh, method = _is_fresh(entry, by_scope, marks, stale)
            summary = offered.get(entry.scope)
            if summary is not None and summary.basis != entry.basis:
                summary = None  # written from facts that have changed since
            if fresh and (summary is None or method == METHOD_MODEL or summary.method != METHOD_MODEL):
                continue
            if summary is None:
                summary = rule_summary(entry.name, list(entry.facts))
            now = memory.clock()
            confidence = min(0.95, 0.5 + 0.1 * len(entry.facts))
            result = memory.save_observation(
                entry.scope, summary.text, confidence, summary.fact_ids, now=now, run_ts=now,
            )
            memory.mark_observation(result.observation.id, summary.method, entry.basis)
            saved.append(result.observation.id)
            removed.extend(i for i in result.removed_ids if i not in existing)
            rewritten.extend(i for i in existing if i != result.observation.id)
    return ProcessOutcome(
        observations_saved=tuple(saved),
        observations_removed=tuple(removed),
        observations_rewritten=tuple(rewritten),
        model_written=model_written,
        model_failure=failure,
    )


def process_fact(memory, fact_id: int) -> ProcessOutcome:
    """After a write: replace older facts the new one contradicts, then
    bring the observations in line (the rules write; the server's model
    pass rewrites them afterwards when an endpoint is configured)."""
    fact = memory.get(fact_id)
    links = memory.fact_entity_ids()
    mine = set(links.get(fact.id, []))
    already = memory.superseded_map()
    replaced: list[int] = []
    if fact.id not in already:
        for other in memory.all():
            if other.id == fact.id or other.id in already:
                continue
            theirs = set(links.get(other.id, []))
            related = bool(mine & theirs) if (mine or theirs) else True
            if not related or other.created_ts > fact.created_ts:
                continue
            if replaces(fact.text, other.text):
                memory.mark_superseded(other.id, fact.id)
                replaced.append(other.id)
    consolidated = reconcile_observations(memory)
    return ProcessOutcome(
        replaced=tuple(replaced),
        observations_saved=consolidated.observations_saved,
        observations_removed=consolidated.observations_removed,
    )


@dataclass(frozen=True)
class StoreOutcome:
    fact: Fact
    merged: bool
    process: ProcessOutcome


def store_fact(
    memory,
    text: str,
    *,
    source: str,
    kind: str = "world",
    occurrence_ts: float | None = None,
    source_id: int | None = None,
    entities: Iterable[tuple[str, str]] = (),
) -> StoreOutcome:
    """The one write every fact takes (typed, approved or automatic):
    dedupe through the store, link the excerpt and the entities, then
    process. An excerpt that no longer exists is dropped rather than
    failing the write."""
    if source_id is not None and not memory.source_exists(source_id):
        source_id = None
    before = {fact.id for fact in memory.all()}
    fact = memory.add(text, source=source, kind=kind, occurrence_ts=occurrence_ts,
                      source_id=source_id)
    mentions = [(name, kind_) for name, kind_ in entities]
    if mentions:
        memory.resolve_and_link(fact.id, mentions)
    return StoreOutcome(fact=fact, merged=fact.id in before,
                        process=process_fact(memory, fact.id))


# -- capture ----------------------------------------------------------------


@dataclass(frozen=True)
class CaptureOutcome:
    channel: str
    method: str
    cause: str = ""
    found: int = 0
    skipped: int = 0
    card_ids: tuple[str, ...] = ()
    fact_ids: tuple[int, ...] = ()
    source_id: int | None = None


def _known_texts(memory, inbox, draft_kind: str) -> set[str]:
    """Texts capture must not propose again: stored facts, candidates
    waiting for review, and candidates the user rejected (the inbox keeps
    dismissed cards for thirty days), so a channel that repeats itself,
    like the workbook's rolling 24-hour delta, never re-asks."""
    known = {normalize_fact_text(fact.text) for fact in memory.all()}
    if inbox is not None:
        for card in [*inbox.waiting(include_snoozed=True), *inbox.dismissed()]:
            if card.kind == draft_kind:
                known.add(normalize_fact_text(card.draft))
    return known


def capture(
    memory,
    inbox,
    *,
    channel: str,
    excerpt: str,
    own_words: str,
    settings: CaptureSettings,
    extract: Callable[[str], list[CandidateFact]] | None,
    stage_card: Callable[[CandidateFact, int, str, str], object],
    speaker: str = "You",
    draft_kind: str = "memory_draft",
    candidates: list[CandidateFact] | None = None,
) -> CaptureOutcome | None:
    """Run one capture. `extract` is the endpoint extractor's call (None
    when endpoint calls are off); when it is missing or raises, the
    rules read `own_words` (the user's text only, never a model reply).
    Returns None when the channel is off. `stage_card(candidate,
    source_id, channel, method)` makes the review card."""
    if not settings.captures(channel) or not (excerpt or "").strip():
        return None
    method, cause = METHOD_RULES, ""
    if candidates is not None:
        # The channel wrote its own candidates (the workbook's cells).
        candidates = facts_to_retain(list(candidates))
        extract = None
    else:
        candidates = []
    if extract is not None:
        try:
            candidates = facts_to_retain(list(extract(excerpt)))
            method = METHOD_MODEL
        except Exception as exc:  # noqa: BLE001 - the classified extractor errors and anything else fall back
            cause = str(exc)[:200] or "The endpoint did not answer."
            candidates = []
    if method == METHOD_RULES and not candidates:
        candidates = rule_candidates(own_words)
    known = _known_texts(memory, inbox, draft_kind)
    fresh: list[CandidateFact] = []
    for candidate in candidates:
        key = normalize_fact_text(candidate.text)
        if not key or key in known:
            continue
        known.add(key)
        fresh.append(candidate)
    skipped = len(candidates) - len(fresh)
    if not fresh:
        return CaptureOutcome(channel=channel, method=method, cause=cause,
                              found=len(candidates), skipped=skipped)
    source_id = memory.add_source(excerpt, speaker=speaker, context=channel)
    card_ids: list[str] = []
    fact_ids: list[int] = []
    for candidate in fresh:
        if settings.auto_approve:
            outcome = store_fact(
                memory, candidate.text,
                source=f"{AUTO_SOURCE_PREFIX}{channel}",
                kind=candidate.kind,
                occurrence_ts=candidate.occurrence_ts,
                source_id=source_id,
                entities=candidate.entities,
            )
            fact_ids.append(outcome.fact.id)
        else:
            card = stage_card(candidate, source_id, channel, method)
            card_ids.append(getattr(card, "id", str(card)))
    return CaptureOutcome(
        channel=channel, method=method, cause=cause, found=len(candidates),
        skipped=skipped, card_ids=tuple(card_ids), fact_ids=tuple(fact_ids),
        source_id=source_id,
    )


# -- the workbook channel ---------------------------------------------------

MAX_WORKBOOK_FACTS = 10
MAX_WORKBOOK_COLUMNS = 3


def _cell(value) -> str:
    """One workbook cell as display text: blank for None, an integral float
    without its trailing ".0", and runs of whitespace collapsed.

    The text is quoted into a fact verbatim, so a cell that reads "3" and not
    "3.0" is the difference between a sentence and a number dump.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())


def workbook_candidates(header: list, added: list, removed: list) -> list[CandidateFact]:
    """Facts from one workbook poll delta, written from the cells: the
    first column names the row (a deal, an account), the header names the
    columns. An edited row (same name in removed and added) gives one fact
    per changed column; a new row, what it was added with; a row that
    went, that it left the tracker. The row's name is the entity."""
    columns = [_cell(cell) for cell in (header or [])]
    head_key = [cell.lower() for cell in columns]

    def is_header(row) -> bool:
        """True when the row's cells equal the header's, case-insensitively.

        A delta list can repeat the header row; read as data it would become a
        row named after the first column title.
        """
        return [_cell(cell).lower() for cell in row] == head_key

    def name_of(row) -> str:
        """The row's name: its first cell, blank for an empty row.

        The name is the fact's subject and the entity it is filed under, so a
        row without one is skipped instead of becoming a fact about nothing.
        """
        return _cell(row[0]) if row else ""

    def column(index: int) -> str:
        """The header label for a column, or "Column N" when the header is
        shorter than the row or that cell is blank.
        """
        return columns[index] if index < len(columns) and columns[index] else f"Column {index + 1}"

    old_rows = {name_of(row): row for row in removed if row and not is_header(row) and name_of(row)}
    out: list[CandidateFact] = []
    seen_names: set[str] = set()
    for row in added:
        if not row or is_header(row):
            continue
        name = name_of(row)
        if not name:
            continue
        seen_names.add(name)
        entities = names_in(name) or ((name, "other"),)
        entities = ((name, entities[0][1]),)
        old = old_rows.get(name)
        if old is not None:
            changes = 0
            for index in range(1, max(len(row), len(old))):
                before = _cell(old[index]) if index < len(old) else ""
                after = _cell(row[index]) if index < len(row) else ""
                if before == after or changes >= MAX_WORKBOOK_COLUMNS:
                    continue
                changes += 1
                if before and after:
                    text = f"{name}: {column(index)} changed from {before} to {after}."
                elif after:
                    text = f"{name}: {column(index)} is now {after}."
                else:
                    text = f"{name}: {column(index)} was cleared (it was {before})."
                out.append(CandidateFact(text=text, kind="world", entities=entities))
        else:
            details = [
                f"{column(index)} {_cell(row[index])}"
                for index in range(1, len(row)) if _cell(row[index])
            ][:MAX_WORKBOOK_COLUMNS]
            text = f"{name} was added to the tracker" + (f" with {', '.join(details)}." if details else ".")
            out.append(CandidateFact(text=text, kind="world", entities=entities))
    for name, _row in old_rows.items():
        if name not in seen_names:
            out.append(CandidateFact(
                text=f"{name} was removed from the tracker.", kind="world",
                entities=((name, "other"),),
            ))
    return out[:MAX_WORKBOOK_FACTS]


def workbook_excerpt(workbook: str, candidates: list[CandidateFact]) -> str:
    """The provenance excerpt stored with workbook facts."""
    lines = "\n".join(candidate.text for candidate in candidates)
    return f"Changes in {workbook or 'the watched workbook'}:\n{lines}"


# -- removal ----------------------------------------------------------------

TARGET_TYPES = ("fact", "source", "entity", "observation")

# The one removal target no route names: the whole bank. "Forget
# everything" plans through plan_removal with it (ticket #283), so the
# action deletes by the same statements as every other removal.
TARGET_EVERYTHING = "everything"


class UnknownTarget(Exception):
    """Nothing to remove at that address."""


@dataclass(frozen=True)
class RemovalPlan:
    target_type: str
    target_id: int
    label: str
    fact_ids: tuple[int, ...]
    observation_ids: tuple[int, ...] = ()
    source_ids: tuple[int, ...] = ()
    # What else changes, named before anything is written.
    observations_updated: tuple[int, ...] = ()
    observations_removed: tuple[int, ...] = ()
    observations_flagged: tuple[int, ...] = ()
    entities_removed: tuple[int, ...] = ()
    entities_updated: tuple[int, ...] = ()
    released_fact_ids: tuple[int, ...] = ()
    sources_removed: tuple[int, ...] = ()
    # The text each updated observation will read after the removal,
    # keyed by observation id, with the scope it is saved under.
    after: dict = field(default_factory=dict, compare=False)

    def planned(self) -> dict[str, Summary]:
        """Scope to the previewed text, for reconcile_observations."""
        return {scope: summary for scope, summary in self.after.values()}

    def to_json(self, memory) -> dict:
        """The removal dialog's preview payload, in the keys the client reads.

        Rows are looked up in memory at call time, so an id that has since gone
        is silently omitted instead of breaking the preview. This is display
        data only: what executes is the plan itself, not this dict.
        """
        facts = {fact.id: fact for fact in memory.all()}
        observations = {obs.id: obs for obs in memory.observations()}
        entities = {entity.id: entity for entity in memory.entities()}

        def fact_rows(ids):
            """id-and-text rows for the facts that still exist."""
            return [{"id": i, "text": facts[i].text} for i in ids if i in facts]

        def obs_rows(ids):
            """id-and-text rows for the observations that still exist."""
            return [{"id": i, "text": observations[i].text} for i in ids if i in observations]

        def updated_rows(ids):
            """Rows for observations that change, with the previewed text.

            "after" and "afterMethod" come from the plan's own preview and stay
            None when it holds no rewritten text for that id, which is how the
            dialog separates "will be rewritten when it is removed" from "the
            new wording is known".
            """
            rows = []
            for i in ids:
                if i not in observations:
                    continue
                row = {"id": i, "text": observations[i].text, "after": None, "afterMethod": None}
                if i in self.after:
                    summary = self.after[i][1]
                    row["after"] = summary.text
                    row["afterMethod"] = summary.method
                rows.append(row)
            return rows

        def entity_rows(ids):
            """id-and-name rows for the entities that still exist."""
            return [{"id": i, "name": entities[i].canonical_name} for i in ids if i in entities]

        return {
            "target": {"type": self.target_type, "id": self.target_id, "label": self.label},
            "facts": fact_rows(self.fact_ids),
            "observationsRemoved": obs_rows(self.observations_removed),
            "observationsUpdated": updated_rows(self.observations_updated),
            "observationsFlagged": obs_rows(self.observations_flagged),
            "entitiesRemoved": entity_rows(self.entities_removed),
            "entitiesUpdated": entity_rows(self.entities_updated),
            "factsRestored": fact_rows(self.released_fact_ids),
            "sourcesRemoved": list(self.sources_removed),
        }


def _target_facts(memory, target_type: str, target_id: int) -> tuple[list[int], str, list[int], list[int]]:
    """(fact ids, label, named observation ids, named source ids)."""
    if target_type == TARGET_EVERYTHING:
        return ([fact.id for fact in memory.all()], "everything",
                [obs.id for obs in memory.observations()],
                [excerpt.id for excerpt in memory.sources()])
    if target_type == "fact":
        try:
            fact = memory.get(target_id)
        except UnknownFact as exc:
            raise UnknownTarget(str(exc)) from exc
        return [fact.id], fact.text, [], []
    if target_type == "entity":
        names = {entity.id: entity.canonical_name for entity in memory.entities()}
        if target_id not in names:
            raise UnknownTarget(f"no entity {target_id}")
        return memory.fact_ids_for_entity(target_id), names[target_id], [], []
    if target_type == "source":
        excerpts = {excerpt.id: excerpt for excerpt in memory.sources()}
        if target_id not in excerpts:
            raise UnknownTarget(f"no excerpt {target_id}")
        label = " ".join(excerpts[target_id].text.split())[:120]
        return memory.fact_ids_for_sources([target_id]), label, [], [target_id]
    if target_type == "observation":
        observations = {obs.id: obs for obs in memory.observations()}
        if target_id not in observations:
            raise UnknownTarget(f"no observation {target_id}")
        return [], observations[target_id].text, [target_id], []
    raise UnknownTarget(f"cannot remove a {target_type!r}")


def plan_forget_all(memory) -> RemovalPlan:
    """The plan for forgetting the whole bank (ticket #283): every fact,
    named outright together with every summary and every excerpt, so
    plan_removal derives the rest (the names the facts were filed under)
    as it does for any removal. Nothing is written here; the plan goes
    through apply_removal like any other, with no excerpt kept back."""
    return plan_removal(memory, TARGET_EVERYTHING, 0, keep_source_ids=())


def plan_removal(memory, target_type: str, target_id: int,
                 keep_source_ids: Iterable[int] = (),
                 summarize: Summarize | None = None) -> RemovalPlan:
    """Everything a removal would change, computed from the rows, with
    nothing written: including the text each rewritten observation will
    read afterwards (by `summarize`, the endpoint, when given; the rules
    otherwise or when it fails)."""
    fact_ids, label, named_obs, named_sources = _target_facts(memory, target_type, int(target_id))
    doomed = set(fact_ids)
    links = memory.fact_entity_ids()
    replaced = memory.superseded_map()
    touched_entities = sorted({eid for fid in doomed for eid in links.get(fid, [])})
    entities_removed = [
        eid for eid in touched_entities
        if all(fid in doomed for fid, eids in links.items() if eid in eids)
        # The entity being removed is the subject, not a knock-on effect.
        and not (target_type == "entity" and eid == int(target_id))
    ]
    entities_updated = [
        eid for eid in touched_entities
        if eid not in entities_removed and not (target_type == "entity" and eid == int(target_id))
    ]
    _now, all_entities = entity_bases(memory)
    scope_of = memory.scope_of_observations(entity_scope(eid) for eid in all_entities)
    after_bases = {entry.scope: entry for entry in entity_bases(memory, without=doomed)[0]}
    marks = memory.observation_marks()
    observations_removed: list[int] = list(named_obs)
    observations_updated: list[int] = []
    observations_flagged: list[int] = []
    after: dict[int, tuple[str, Summary]] = {}
    failed = False
    for obs in memory.observations():
        if obs.id in named_obs:
            continue
        if obs.id in scope_of:
            scope = scope_of[obs.id]
            basis = marks.get(obs.id, (None, frozenset()))[1] or frozenset(obs.fact_ids)
            if not (basis | set(obs.fact_ids)) & doomed:
                continue
            entry = after_bases.get(scope)
            if entry is None:
                observations_removed.append(obs.id)
                continue
            observations_updated.append(obs.id)
            summary = None
            if summarize is not None and not failed:
                try:
                    summary = summarize(entry.name, list(entry.facts))
                except SummaryFailed:
                    failed = True
            if summary is None:
                summary = rule_summary(entry.name, list(entry.facts))
            after[obs.id] = (scope, summary)
            continue
        cited = set(obs.fact_ids)
        if not cited & doomed:
            continue
        if not cited - doomed:
            observations_removed.append(obs.id)
        else:
            observations_flagged.append(obs.id)
    released = sorted(old for old, new in replaced.items() if new in doomed and old not in doomed)
    keep = {int(s) for s in keep_source_ids}
    fact_rows = {fact.id: fact for fact in memory.all()}
    sources_removed: set[int] = set(named_sources)
    for fid in doomed:
        sid = fact_rows[fid].source_id if fid in fact_rows else None
        if sid is None or sid in keep:
            continue
        others = [f for f in fact_rows.values() if f.source_id == sid and f.id not in doomed]
        if not others:
            sources_removed.add(sid)
    return RemovalPlan(
        target_type=target_type,
        target_id=int(target_id),
        label=label,
        fact_ids=tuple(sorted(doomed)),
        observation_ids=tuple(named_obs),
        source_ids=tuple(named_sources),
        observations_updated=tuple(observations_updated),
        observations_removed=tuple(observations_removed),
        observations_flagged=tuple(observations_flagged),
        entities_removed=tuple(entities_removed),
        entities_updated=tuple(entities_updated),
        released_fact_ids=tuple(released),
        sources_removed=tuple(sorted(sources_removed - keep if target_type != "source" else sources_removed)),
        after=after,
    )


@dataclass(frozen=True)
class RemovalResult:
    fact_ids: tuple[int, ...]
    observations_removed: tuple[int, ...]
    observations_flagged: tuple[int, ...]
    observations_updated: tuple[int, ...]
    entities_removed: tuple[int, ...]
    sources_removed: tuple[int, ...]
    released_fact_ids: tuple[int, ...]
    dump: dict = field(repr=False, default_factory=dict)
    created_observation_ids: tuple[int, ...] = ()

    def to_json(self) -> dict:
        """The removal's effect as the route reports it: ids only, per category.

        No text and no dump: the snapshot that makes undo possible stays on the
        object and is never serialized to the client.
        """
        return {
            "facts": list(self.fact_ids),
            "observationsRemoved": list(self.observations_removed),
            "observationsFlagged": list(self.observations_flagged),
            "observationsUpdated": list(self.observations_updated),
            "entitiesRemoved": list(self.entities_removed),
            "sourcesRemoved": list(self.sources_removed),
            "factsRestored": list(self.released_fact_ids),
        }


def apply_removal(memory, plan: RemovalPlan, keep_source_ids: Iterable[int] = (),
                  planned: dict[str, Summary] | None = None) -> RemovalResult:
    """Write the plan in one transaction, then bring the observations in
    line: with the previewed text where the facts are still the ones it
    was written from (`planned`, else the plan's own), the rules
    otherwise. The dump rides the result for undo."""
    before_obs = {obs.id for obs in memory.observations()}
    raw = memory.remove_with_effects(
        plan.fact_ids,
        observation_ids=plan.observation_ids,
        source_ids=plan.source_ids,
        keep_source_ids=keep_source_ids,
    )
    consolidated = reconcile_observations(
        memory, planned=planned if planned is not None else plan.planned(),
    )
    after_obs = {obs.id for obs in memory.observations()}
    created = tuple(sorted(after_obs - before_obs))
    gone = set(raw["observation_ids"]) | set(consolidated.observations_removed)
    rewritten = set(consolidated.observations_rewritten) | set(consolidated.observations_saved)
    return RemovalResult(
        fact_ids=tuple(raw["fact_ids"]),
        observations_removed=tuple(sorted(gone - rewritten)),
        # Flagged means it still stands and lost a cited fact; one the
        # rewrite replaced or that went away is not left to look at.
        observations_flagged=tuple(
            sorted(set(raw["flagged_observation_ids"]) - gone - rewritten)
        ),
        observations_updated=tuple(consolidated.observations_saved),
        entities_removed=tuple(raw["entity_ids"]),
        sources_removed=tuple(raw["source_ids"]),
        released_fact_ids=tuple(raw["released_fact_ids"]),
        dump=raw["dump"],
        created_observation_ids=created,
    )


@dataclass
class _Held:
    result: RemovalResult
    label: str
    expires_ts: float


class UndoBuffer:
    """Removals held in process memory for a short window. Nothing is
    written to disk: once the window passes (or the server restarts)
    the removed text is gone for good."""

    def __init__(self, clock: Callable[[], float], window_s: float = UNDO_WINDOW_S) -> None:
        """Take the clock that ages entries and the undo window, in seconds.

        The clock is injected so a test can expire an entry without sleeping.
        Held removals live in this process only, so a restart loses every undo.
        """
        self.clock = clock
        self.window_s = window_s
        self._held: dict[str, _Held] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        """Drop every entry whose window has closed. The caller holds the lock."""
        now = self.clock()
        for token in [t for t, held in self._held.items() if held.expires_ts <= now]:
            del self._held[token]

    def hold(self, result: RemovalResult, label: str) -> tuple[str, float]:
        """Keep one removal for undo; returns (token, expiry in epoch seconds).

        Expired entries are swept first, so the buffer holds no more than the
        removals made inside one window. The token is random and is the only
        handle to the dump: it cannot be reconstructed from the removal.
        """
        with self._lock:
            self._expire()
            token = secrets.token_urlsafe(12)
            expires = self.clock() + self.window_s
            self._held[token] = _Held(result=result, label=label, expires_ts=expires)
            return token, expires

    def take(self, token: str) -> _Held | None:
        """Remove and return the held removal, or None when unknown or expired.

        Popping makes an undo single-use: taking the same token twice cannot
        restore the same rows again.
        """
        with self._lock:
            self._expire()
            return self._held.pop(token, None)


def undo_removal(memory, held: _Held) -> None:
    """Put a held removal back; the observations it rewrote come back as
    they were (the dump), and anything else is brought in line."""
    memory.restore_dump(held.result.dump, drop_observation_ids=held.result.created_observation_ids)
    reconcile_observations(memory)


class PreviewCache:
    """The removal previews shown in the last few minutes, by target, so
    the removal writes the observation text the user just read (the
    endpoint is not asked twice for the same facts). Process memory only."""

    def __init__(self, clock: Callable[[], float], ttl_s: float = 300.0) -> None:
        """Take the clock that ages entries and how long a preview stays usable.

        One entry per (target type, target id), in process memory only: a restart
        means the next removal simply writes the rules' text.
        """
        self.clock = clock
        self.ttl_s = ttl_s
        self._plans: dict[tuple[str, int], tuple[float, dict[str, Summary]]] = {}
        self._lock = threading.Lock()

    def put(self, plan: RemovalPlan) -> None:
        """Record this plan's previewed texts under its target.

        A later plan for the same target replaces the earlier one, so the removal
        always writes the text the user read last.
        """
        with self._lock:
            self._plans[(plan.target_type, plan.target_id)] = (self.clock(), plan.planned())

    def take(self, target_type: str, target_id: int) -> dict[str, Summary] | None:
        """Consume the preview for this target, or None when there is none.

        Single-use: the entry is popped, and one older than ttl_s counts as
        absent. Expired entries are swept on the way out.
        """
        with self._lock:
            entry = self._plans.pop((target_type, int(target_id)), None)
            now = self.clock()
            for key in [k for k, (ts, _p) in self._plans.items() if now - ts > self.ttl_s]:
                del self._plans[key]
        if entry is None or self.clock() - entry[0] > self.ttl_s:
            return None
        return entry[1]
