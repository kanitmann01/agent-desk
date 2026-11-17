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

from agentdesk.memory.core import Fact, UnknownEntity, UnknownFact, normalize_fact_text
from agentdesk.memory.extract import (
    CandidateFact,
    facts_to_retain,
)

# -- capture settings -------------------------------------------------------

# Channel id, the label the page shows, and the settings switch for it.
CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("assistant", "Assistant", "memory_capture_assistant"),
    ("research", "Research", "memory_capture_research"),
)
CHANNEL_LABELS = {channel: label for channel, label, _key in CHANNELS}
METHOD_MODEL = "model"
METHOD_RULES = "rules"
AUTO_SOURCE_PREFIX = "auto: "
ENTITY_SCOPE_PREFIX = "entity:"
UNDO_WINDOW_S = 30.0
MAX_CONSOLIDATED_FACTS = 6
MAX_CONSOLIDATED_CHARS = 420


@dataclass(frozen=True)
class CaptureSettings:
    enabled: bool = True
    auto_approve: bool = False
    channels: frozenset[str] = frozenset(channel for channel, _l, _k in CHANNELS)

    def captures(self, channel: str) -> bool:
        return self.enabled and channel in self.channels

    def to_json(self) -> dict:
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


def consolidation_text(name: str, facts: list[Fact]) -> str:
    """One readable line per entity: its name, then what the standing
    facts say about it, newest first, bounded."""
    parts: list[str] = []
    used = len(name) + 2
    for fact in facts[:MAX_CONSOLIDATED_FACTS]:
        clause = fact.text.strip().rstrip(".")
        if used + len(clause) + 2 > MAX_CONSOLIDATED_CHARS and parts:
            break
        parts.append(clause)
        used += len(clause) + 2
    return f"{name}: " + "; ".join(parts) + "."


def entity_scope(entity_id: int) -> str:
    return f"{ENTITY_SCOPE_PREFIX}{int(entity_id)}"


@dataclass(frozen=True)
class ProcessOutcome:
    replaced: tuple[int, ...] = ()
    observations_saved: tuple[int, ...] = ()
    observations_removed: tuple[int, ...] = ()


def consolidate_entities(memory, entity_ids: Iterable[int]) -> ProcessOutcome:
    """Rewrite the consolidated observation of each entity: kept when two
    or more standing (not replaced) facts mention it, removed otherwise."""
    entity_ids = list(dict.fromkeys(int(e) for e in entity_ids))
    if not entity_ids:
        return ProcessOutcome()
    names = {entity.id: entity.canonical_name for entity in memory.entities()}
    replaced = memory.superseded_map()
    by_id = {fact.id: fact for fact in memory.all()}
    saved: list[int] = []
    removed: list[int] = []
    for entity_id in entity_ids:
        scope = entity_scope(entity_id)
        existing = memory.observation_ids_in_scope(scope)
        name = names.get(entity_id)
        standing: list[Fact] = []
        if name is not None:
            try:
                ids = memory.fact_ids_for_entity(entity_id)
            except UnknownEntity:
                ids = []
            standing = [by_id[i] for i in ids if i in by_id and i not in replaced]
        if name is None or len(standing) < 2:
            removed.extend(memory.delete_observations(existing))
            continue
        standing.sort(key=lambda fact: (fact.created_ts, fact.id), reverse=True)
        cited = standing[:MAX_CONSOLIDATED_FACTS]
        text = consolidation_text(name, cited)
        confidence = min(0.95, 0.5 + 0.1 * len(standing))
        now = memory.clock()
        result = memory.save_observation(
            scope, text, confidence, [fact.id for fact in cited], now=now, run_ts=now,
        )
        saved.append(result.observation.id)
        removed.extend(result.removed_ids)
    return ProcessOutcome(observations_saved=tuple(saved), observations_removed=tuple(removed))


def process_fact(memory, fact_id: int) -> ProcessOutcome:
    """After a write: replace older facts the new one contradicts, then
    re-consolidate every entity the new fact or a replaced one mentions."""
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
    touched = set(mine)
    for other_id in replaced:
        touched.update(links.get(other_id, []))
    consolidated = consolidate_entities(memory, sorted(touched))
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
    known = {normalize_fact_text(fact.text) for fact in memory.all()}
    if inbox is not None:
        for card in inbox.waiting(include_snoozed=True):
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
) -> CaptureOutcome | None:
    """Run one capture. `extract` is the endpoint extractor's call (None
    when endpoint calls are off); when it is missing or raises, the
    rules read `own_words` (the user's text only, never a model reply).
    Returns None when the channel is off. `stage_card(candidate,
    source_id, channel, method)` makes the review card."""
    if not settings.captures(channel) or not (excerpt or "").strip():
        return None
    method, cause = METHOD_RULES, ""
    candidates: list[CandidateFact] = []
    if extract is not None:
        try:
            candidates = facts_to_retain(list(extract(excerpt)))
            method = METHOD_MODEL
        except Exception as exc:  # noqa: BLE001 - the classified extractor errors and anything else fall back
            cause = str(exc)[:200] or "The endpoint did not answer."
            candidates = []
    if method == METHOD_RULES:
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


# -- removal ----------------------------------------------------------------

TARGET_TYPES = ("fact", "source", "entity", "observation")


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

    def to_json(self, memory) -> dict:
        facts = {fact.id: fact for fact in memory.all()}
        observations = {obs.id: obs for obs in memory.observations()}
        entities = {entity.id: entity for entity in memory.entities()}

        def fact_rows(ids):
            return [{"id": i, "text": facts[i].text} for i in ids if i in facts]

        def obs_rows(ids):
            return [{"id": i, "text": observations[i].text} for i in ids if i in observations]

        def entity_rows(ids):
            return [{"id": i, "name": entities[i].canonical_name} for i in ids if i in entities]

        return {
            "target": {"type": self.target_type, "id": self.target_id, "label": self.label},
            "facts": fact_rows(self.fact_ids),
            "observationsRemoved": obs_rows(self.observations_removed),
            "observationsUpdated": obs_rows(self.observations_updated),
            "observationsFlagged": obs_rows(self.observations_flagged),
            "entitiesRemoved": entity_rows(self.entities_removed),
            "entitiesUpdated": entity_rows(self.entities_updated),
            "factsRestored": fact_rows(self.released_fact_ids),
            "sourcesRemoved": list(self.sources_removed),
        }


def _target_facts(memory, target_type: str, target_id: int) -> tuple[list[int], str, list[int], list[int]]:
    """(fact ids, label, named observation ids, named source ids)."""
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


def plan_removal(memory, target_type: str, target_id: int,
                 keep_source_ids: Iterable[int] = ()) -> RemovalPlan:
    """Everything a removal would change, computed from the rows, with
    nothing written."""
    fact_ids, label, named_obs, named_sources = _target_facts(memory, target_type, int(target_id))
    doomed = set(fact_ids)
    links = memory.fact_entity_ids()
    replaced = memory.superseded_map()
    entity_count: dict[int, int] = {}
    for fid, eids in links.items():
        for eid in eids:
            entity_count[eid] = entity_count.get(eid, 0) + 1
    touched_entities = sorted({eid for fid in doomed for eid in links.get(fid, [])})
    entities_removed = [
        eid for eid in touched_entities
        if all(fid in doomed for fid, eids in links.items() if eid in eids)
    ]
    entities_updated = [eid for eid in touched_entities if eid not in entities_removed]
    entity_scopes = memory.scope_of_observations(
        entity_scope(eid) for eid in touched_entities
    )
    scope_entity = {oid: int(scope[len(ENTITY_SCOPE_PREFIX):]) for oid, scope in entity_scopes.items()}
    observations_removed: list[int] = list(named_obs)
    observations_updated: list[int] = []
    observations_flagged: list[int] = []
    for obs in memory.observations():
        if obs.id in named_obs:
            continue
        cited = set(obs.fact_ids)
        if not cited & doomed:
            continue
        left = cited - doomed
        if obs.id in scope_entity:
            eid = scope_entity[obs.id]
            standing = [
                fid for fid, eids in links.items()
                if eid in eids and fid not in doomed and fid not in replaced
            ]
            (observations_updated if len(standing) >= 2 else observations_removed).append(obs.id)
        elif not left:
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
        return {
            "facts": list(self.fact_ids),
            "observationsRemoved": list(self.observations_removed),
            "observationsFlagged": list(self.observations_flagged),
            "observationsUpdated": list(self.observations_updated),
            "entitiesRemoved": list(self.entities_removed),
            "sourcesRemoved": list(self.sources_removed),
            "factsRestored": list(self.released_fact_ids),
        }


def apply_removal(memory, plan: RemovalPlan, keep_source_ids: Iterable[int] = ()) -> RemovalResult:
    """Write the plan in one transaction, then re-consolidate the
    entities that keep facts. The dump rides the result for undo."""
    before_obs = {obs.id for obs in memory.observations()}
    raw = memory.remove_with_effects(
        plan.fact_ids,
        observation_ids=plan.observation_ids,
        source_ids=plan.source_ids,
        keep_source_ids=keep_source_ids,
    )
    touched = set(plan.entities_updated)
    for fid in raw["released_fact_ids"]:
        touched.update(memory.fact_entity_ids().get(fid, []))
    consolidated = consolidate_entities(memory, sorted(touched))
    after_obs = {obs.id for obs in memory.observations()}
    created = tuple(sorted(after_obs - before_obs))
    gone = set(raw["observation_ids"]) | set(consolidated.observations_removed)
    return RemovalResult(
        fact_ids=tuple(raw["fact_ids"]),
        observations_removed=tuple(sorted(gone - set(consolidated.observations_saved))),
        observations_flagged=tuple(raw["flagged_observation_ids"]),
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
        self.clock = clock
        self.window_s = window_s
        self._held: dict[str, _Held] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = self.clock()
        for token in [t for t, held in self._held.items() if held.expires_ts <= now]:
            del self._held[token]

    def hold(self, result: RemovalResult, label: str) -> tuple[str, float]:
        with self._lock:
            self._expire()
            token = secrets.token_urlsafe(12)
            expires = self.clock() + self.window_s
            self._held[token] = _Held(result=result, label=label, expires_ts=expires)
            return token, expires

    def take(self, token: str) -> _Held | None:
        with self._lock:
            self._expire()
            return self._held.pop(token, None)


def undo_removal(memory, held: _Held) -> None:
    """Put a held removal back and re-consolidate what it touched."""
    memory.restore_dump(held.result.dump, drop_observation_ids=held.result.created_observation_ids)
    links = memory.fact_entity_ids()
    touched = {eid for fid in held.result.fact_ids for eid in links.get(fid, [])}
    consolidate_entities(memory, sorted(touched))
