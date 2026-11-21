"""The Memory page's loop data: GET /api/memory/loop.

One payload for the redesigned page: the capture settings and how
capture is extracting right now, the candidates waiting for review (the
memory inbox cards), the stored facts with their provenance, the
entities, the excerpts and the observations. Every row is read from the
memory store or the inbox; nothing is invented here. Texts are bounded
and React renders them as text.
"""

from __future__ import annotations

from agentdesk.inbox.core import KIND_MEMORY_DRAFT, KIND_MEMORY_REFLECTION
from agentdesk.memory.loop import (
    AUTO_SOURCE_PREFIX,
    CHANNEL_LABELS,
    ENTITY_SCOPE_PREFIX,
    entity_scope,
)
from agentdesk.server.core import bounded_text
from agentdesk.server.memory_graph_api import SAMPLE_SOURCE

EXCERPT_CHARS = 400
REVIEW_KINDS = (KIND_MEMORY_DRAFT, KIND_MEMORY_REFLECTION)


def origin_of(source: str, card, excerpt) -> dict:
    """Where a fact came from, in the page's words: the channel when the
    capture recorded one, else the writer named in the fact's source."""
    channel = ""
    if excerpt is not None and excerpt.context in CHANNEL_LABELS:
        channel = excerpt.context
    if source.startswith(AUTO_SOURCE_PREFIX):
        channel = source[len(AUTO_SOURCE_PREFIX):]
        return {"id": f"auto:{channel}", "label": CHANNEL_LABELS.get(channel, channel),
                "how": "Saved automatically"}
    if source == "page":
        return {"id": "page", "label": "Typed on this page", "how": ""}
    if source == SAMPLE_SOURCE:
        return {"id": "sample", "label": "Sample data", "how": ""}
    if source.startswith("inbox card "):
        meta = (card.meta.get("memoryFact") if card is not None else None) or {}
        channel = str(meta.get("channel") or channel)
        if channel in CHANNEL_LABELS:
            return {"id": f"review:{channel}", "label": CHANNEL_LABELS[channel],
                    "how": "You approved"}
        if card is not None and card.kind == KIND_MEMORY_DRAFT:
            return {"id": "retain", "label": "Save to memory", "how": "You approved"}
        return {"id": "inbox", "label": "Inbox card", "how": "You approved"}
    return {"id": "other", "label": bounded_text(source or "Unrecorded", 40), "how": "Saved"}


def _card_for(inbox, source: str):
    """The inbox card a fact's source names, or None.

    A source reads "inbox card <id>"; any other source, or a card that has since been
    deleted, yields None rather than an error.
    """
    if inbox is None or not source.startswith("inbox card "):
        return None
    try:
        return inbox.get(source[len("inbox card "):].strip())
    except Exception:  # noqa: BLE001 - a gone card is simply no card
        return None


def candidate_json(card, excerpts: dict, facts_by_id: dict) -> dict:
    """One waiting review card as the page shows it."""
    if card.kind == KIND_MEMORY_REFLECTION:
        meta = card.meta.get("memoryObservation") or {}
        cites = [
            {"id": fid, "text": bounded_text(facts_by_id[fid].text, 160)}
            for fid in meta.get("source_fact_ids") or []
            if isinstance(fid, int) and fid in facts_by_id
        ]
        return {
            "cardId": card.id, "type": "observation", "text": card.draft,
            "title": card.title, "createdTs": card.created_ts,
            "confidence": meta.get("confidence"), "cites": cites,
            "channel": "reflect", "channelLabel": "Reflect", "method": "model",
            "entities": [], "excerpt": None,
        }
    meta = card.meta.get("memoryFact") or {}
    source_id = meta.get("source_id")
    excerpt = excerpts.get(source_id) if isinstance(source_id, int) else None
    channel = str(meta.get("channel") or (excerpt.context if excerpt else "") or "retain")
    entities = [
        {"name": pair[0], "type": pair[1]}
        for pair in meta.get("entities") or []
        if isinstance(pair, (list, tuple)) and len(pair) == 2
    ]
    return {
        "cardId": card.id, "type": "fact", "text": card.draft, "title": card.title,
        "createdTs": card.created_ts, "kind": meta.get("kind", "world"),
        "channel": channel,
        "channelLabel": CHANNEL_LABELS.get(channel, "Save to memory"),
        "method": str(meta.get("method") or "model"),
        "entities": entities,
        "excerpt": (
            {"id": excerpt.id, "text": bounded_text(excerpt.text, EXCERPT_CHARS),
             "speaker": excerpt.speaker, "createdTs": excerpt.created_ts}
            if excerpt is not None else None
        ),
    }


def build_loop_state(memory, inbox, capture: dict, extractor: dict,
                     last_capture: dict | None, undo_window_s: float) -> dict:
    """The loop page's whole view model, assembled from the memory store and the inbox.

    Every list is newest first, ordered by timestamp and then id, and excerpt text is
    bounded at EXCERPT_CHARS. counts.standing excludes replaced facts, candidates are
    the waiting cards of a review kind, and an absent inbox yields no candidates at all.
    """
    facts = memory.all()
    facts_by_id = {fact.id: fact for fact in facts}
    excerpts = {excerpt.id: excerpt for excerpt in memory.sources()}
    entities = memory.entities()
    entity_names = {entity.id: entity.canonical_name for entity in entities}
    links = memory.fact_entity_ids()
    replaced = memory.superseded_map()
    replacing: dict[int, list[int]] = {}
    for old, new in replaced.items():
        replacing.setdefault(new, []).append(old)
    observations = memory.observations()
    stale = memory.stale_observations()
    scopes = memory.scope_of_observations(entity_scope(e.id) for e in entities)
    cited_by: dict[int, list[int]] = {}
    for obs in observations:
        for fid in obs.fact_ids:
            cited_by.setdefault(fid, []).append(obs.id)

    candidates = []
    if inbox is not None:
        waiting = [c for c in inbox.waiting(include_snoozed=True) if c.kind in REVIEW_KINDS]
        waiting.sort(key=lambda card: card.created_ts, reverse=True)
        candidates = [candidate_json(card, excerpts, facts_by_id) for card in waiting]

    fact_rows = []
    for fact in sorted(facts, key=lambda f: (f.created_ts, f.id), reverse=True):
        card = _card_for(inbox, fact.source)
        excerpt = excerpts.get(fact.source_id) if fact.source_id is not None else None
        fact_rows.append({
            "id": fact.id,
            "text": fact.text,
            "kind": fact.kind,
            "createdTs": fact.created_ts,
            "occurredTs": fact.occurrence_ts,
            "origin": origin_of(fact.source, card, excerpt),
            "sample": fact.source == SAMPLE_SOURCE,
            "sourceId": fact.source_id,
            "excerpt": (
                {"id": excerpt.id, "text": bounded_text(excerpt.text, EXCERPT_CHARS),
                 "speaker": excerpt.speaker, "createdTs": excerpt.created_ts}
                if excerpt is not None else None
            ),
            "entities": [
                {"id": eid, "name": entity_names[eid]}
                for eid in links.get(fact.id, []) if eid in entity_names
            ],
            "replacedBy": replaced.get(fact.id),
            "replaces": sorted(replacing.get(fact.id, [])),
            "observationIds": sorted(cited_by.get(fact.id, [])),
        })

    source_rows = []
    for excerpt in sorted(excerpts.values(), key=lambda e: (e.created_ts, e.id), reverse=True):
        fact_ids = [f.id for f in facts if f.source_id == excerpt.id]
        source_rows.append({
            "id": excerpt.id,
            "text": bounded_text(excerpt.text, EXCERPT_CHARS),
            "speaker": excerpt.speaker,
            "channel": excerpt.context,
            "channelLabel": CHANNEL_LABELS.get(
                excerpt.context,
                "Sample data" if excerpt.context == SAMPLE_SOURCE else "Save to memory",
            ),
            "createdTs": excerpt.created_ts,
            "factIds": fact_ids,
        })

    marks = memory.observation_marks()
    entity_names = {e.id: e.canonical_name for e in entities}
    observation_rows = []
    for obs in observations:
        scope = scopes.get(obs.id, "")
        entity_id = int(scope[len(ENTITY_SCOPE_PREFIX):]) if scope.startswith(ENTITY_SCOPE_PREFIX) else None
        observation_rows.append({
            "id": obs.id,
            "text": obs.text,
            "confidence": round(obs.confidence, 2),
            "factIds": list(obs.fact_ids),
            "createdTs": obs.created_ts,
            "updatedTs": obs.updated_ts,
            "staleTs": stale.get(obs.id),
            "entityId": entity_id,
            "entityName": entity_names.get(entity_id) if entity_id is not None else None,
            "derived": "consolidated" if entity_id is not None else "reflected",
            "method": (marks.get(obs.id) or (None, frozenset()))[0],
        })

    entity_rows = [
        {"id": e.id, "name": e.canonical_name, "type": e.type,
         "aliases": list(e.aliases), "factCount": e.fact_count}
        for e in sorted(entities, key=lambda e: (-e.fact_count, e.canonical_name.lower()))
    ]

    return {
        "status": "ok",
        "capture": capture,
        "extractor": extractor,
        "lastCapture": last_capture,
        "undoWindowS": undo_window_s,
        "counts": {
            "waiting": len(candidates),
            "facts": len(facts),
            "standing": len([f for f in facts if f.id not in replaced]),
            "replaced": len(replaced),
            "entities": len(entities),
            "observations": len(observations),
            "flagged": len(stale),
            "sources": len(excerpts),
        },
        "candidates": candidates,
        "facts": fact_rows,
        "entities": entity_rows,
        "sources": source_rows,
        "observations": observation_rows,
    }
