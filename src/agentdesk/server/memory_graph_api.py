"""The memory graph's data: GET /api/memory/graph.

The Memory page's graph shows how each knowledge point got into the
desk, so this payload carries the store's real rows and nothing
invented. It reuses the ticket #96 snapshot (memory/graph) to choose
the facts and observations in the window and to compute their time and
meaning links, then adds the provenance rows the snapshot leaves out:

- origin nodes: the action that wrote a fact (the Memory page form, an
  inbox approval, a plugin card, the sample seed), read from the
  fact's `source` column and, for inbox cards, from the card itself;
- source nodes: retained excerpts (the sources table) a retain
  extracted facts from, joined through `facts.source_id`;
- entity nodes: the resolved entities a fact mentions (the edges
  table);
- fact and observation nodes, with observation citations.

Each node carries its provenance as an ordered list of pipeline steps
(retain, extract, approve, store, link, reflect) with the moment each
happened when the store knows it. The pipeline counts at the top are
whole-bank totals from the same rows.

Labels are bounded here (the client never sees unbounded text) and
the payload is plain JSON: the client escapes nothing because React
renders text, never HTML.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentdesk.inbox.core import KIND_MEMORY_DRAFT, STATUS_WAITING, UnknownCard
from agentdesk.memory.graph import DEFAULT_GRAPH_LIMIT

SAMPLE_SOURCE = "sample seed"
LABEL_CHARS = 80
TEXT_CHARS = 600

STEP_RETAIN = "retain"
STEP_EXTRACT = "extract"
STEP_APPROVE = "approve"
STEP_STORE = "store"
STEP_LINK = "link"
STEP_REFLECT = "reflect"

_CARD_KIND_WORDS = {
    "suggestion": "a suggestion card",
    "skill_proposal": "a skill proposal",
    "update_consent": "an update consent card",
    "brief": "a meeting brief",
    "feature_request": "a feature request",
    "mail_digest": "a mail digest",
    "mail_follow_up": "a mail follow-up",
    KIND_MEMORY_DRAFT: "a memory draft",
    "memory_reflection": "a reflection card",
}


def _bounded(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


@dataclass(frozen=True)
class _Origin:
    id: str
    label: str
    detail: str
    sample: bool = False


def _card_for(inbox, source: str):
    """The inbox card a fact's `source` names ("inbox card <id>"), or
    None when the source is something else or the card is gone."""
    if inbox is None or not source.startswith("inbox card "):
        return None
    card_id = source[len("inbox card "):].strip()
    try:
        return inbox.get(card_id)
    except (UnknownCard, KeyError, ValueError):
        return None


def _origin_for(source: str, card) -> _Origin:
    """The writer of one fact, as a node shared by every fact the same
    action wrote."""
    if source == "page":
        return _Origin("origin:page", "Memory page",
                       "Facts typed into the Add a fact form and saved as written.")
    if source.startswith("auto: "):
        channel = source[len("auto: "):]
        label = channel.capitalize()
        return _Origin(f"origin:auto:{channel}", f"Captured from {label}",
                       f"Facts captured from your {label} activity and saved "
                       "automatically (review was off).")
    if source == SAMPLE_SOURCE:
        return _Origin("origin:sample", "Sample seed",
                       "Written when Sample data was turned on in Settings; "
                       "turning it off removes them.", sample=True)
    if source.startswith("inbox card "):
        if card is not None:
            plugin = str(card.meta.get("pluginId", "") or "")
            if plugin:
                return _Origin(f"origin:plugin:{plugin}", f"Plugin {plugin}",
                               f"Cards from the {plugin} plugin that you accepted.")
            channel = str((card.meta.get("memoryFact") or {}).get("channel") or "")
            if card.kind == KIND_MEMORY_DRAFT and channel:
                label = channel.capitalize()
                return _Origin(f"origin:capture:{channel}", f"Captured from {label}",
                               f"Facts captured from your {label} activity "
                               "that you approved.")
            if card.kind == KIND_MEMORY_DRAFT:
                return _Origin("origin:retain", "Save to memory",
                               "Conversations you saved from the Assistant, "
                               "extracted into draft facts you approved.")
            words = _CARD_KIND_WORDS.get(card.kind, "an inbox card")
            return _Origin(f"origin:card:{card.kind}", f"Inbox: {words[words.index(' ') + 1:]}",
                           f"Facts carried by {words} you accepted.")
        return _Origin("origin:inbox", "Inbox approvals",
                       "Accepted inbox cards that are no longer in the inbox.")
    if not source:
        return _Origin("origin:unknown", "Unrecorded",
                       "Facts saved before their writer was recorded.")
    return _Origin(f"origin:other:{source}", _bounded(source, 40),
                   f"Facts written by {source}.")


def _fact_steps(fact, card, excerpt, entity_names, has_vector, origin) -> list[dict]:
    """One fact's provenance, oldest step first, every line read from
    a stored row."""
    steps: list[dict] = []
    if excerpt is not None:
        who = f" ({excerpt.speaker})" if excerpt.speaker else ""
        lead = ("A sample excerpt" if origin.sample else "A conversation excerpt")
        steps.append({
            "step": STEP_RETAIN, "ts": excerpt.created_ts,
            "text": f"{lead}{who} was saved to memory: "
                    f"\u201c{_bounded(excerpt.text, 140)}\u201d",
        })
    if card is not None and card.kind == KIND_MEMORY_DRAFT:
        meta = card.meta.get("memoryFact") or {}
        mentioned = ", ".join(
            pair[0] for pair in meta.get("entities") or []
            if isinstance(pair, (list, tuple)) and pair
        )
        kind_word = "an experience" if fact.kind == "experience" else "a world fact"
        steps.append({
            "step": STEP_EXTRACT, "ts": card.created_ts,
            "text": f"The extractor proposed it as {kind_word}"
                    + (f", mentioning {mentioned}" if mentioned else "")
                    + ". Knowledge gaps were dropped and at most five "
                      "candidates were kept.",
        })
    elif excerpt is not None:
        steps.append({
            "step": STEP_EXTRACT, "ts": None,
            "text": "Extracted from the excerpt above.",
        })
    if card is not None:
        words = _CARD_KIND_WORDS.get(card.kind, "an inbox card")
        title = _bounded(card.title, 80)
        steps.append({
            "step": STEP_APPROVE, "ts": card.accepted_ts,
            "text": f"You accepted {words}, \u201c{title}\u201d.",
        })
    elif fact.source.startswith("inbox card "):
        steps.append({
            "step": STEP_APPROVE, "ts": None,
            "text": f"You accepted {fact.source}; the card is no longer in the inbox.",
        })
    how = {
        "origin:page": "Typed on the Memory page and stored as written.",
        "origin:sample": "Written by the sample seed, labelled sample.",
    }.get(origin.id, "Written to memory. A fact with the same words merges into the older copy.")
    steps.append({"step": STEP_STORE, "ts": fact.created_ts, "text": how})
    link_parts = []
    if entity_names:
        link_parts.append("Linked to " + ", ".join(entity_names) + ".")
    else:
        link_parts.append("No entities linked: only extracted facts carry entity mentions.")
    if has_vector:
        link_parts.append("Embedded, so it can join facts that mean the same.")
    steps.append({"step": STEP_LINK, "ts": None, "text": " ".join(link_parts)})
    return steps


def build_memory_graph(
    memory,
    inbox=None,
    since: float | None = None,
    until: float | None = None,
    limit: int = DEFAULT_GRAPH_LIMIT,
    now: float | None = None,
    semantic: bool = False,
) -> dict:
    """The whole payload for one window of the bank."""
    snapshot = memory.graph_snapshot(now=now, since=since, until=until, limit=limit)
    facts = {fact.id: fact for fact in memory.all()}
    observations = {obs.id: obs for obs in memory.observations()}
    entities = {entity.id: entity for entity in memory.entities()}
    excerpts = {excerpt.id: excerpt for excerpt in memory.sources()}
    mentions = memory.fact_entity_ids()
    vectors = memory.fact_ids_with_vectors()

    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()

    def push(node: dict) -> None:
        if node["id"] not in seen:
            seen.add(node["id"])
            nodes.append(node)

    origin_counts: dict[str, int] = {}
    origins: dict[str, _Origin] = {}
    fact_nodes: list[dict] = []
    for snap in snapshot.nodes:
        kind, _sep, raw = str(snap.id).partition(":")
        if kind == "fact":
            fact = facts.get(int(raw))
            if fact is None:
                continue
            card = _card_for(inbox, fact.source)
            origin = _origin_for(fact.source, card)
            origins[origin.id] = origin
            origin_counts[origin.id] = origin_counts.get(origin.id, 0) + 1
            excerpt = excerpts.get(fact.source_id) if fact.source_id is not None else None
            entity_ids = [eid for eid in mentions.get(fact.id, []) if eid in entities]
            names = [entities[eid].canonical_name for eid in entity_ids]
            node_id = f"fact:{fact.id}"
            fact_nodes.append({
                "id": node_id,
                "kind": "fact",
                "label": _bounded(fact.text, LABEL_CHARS),
                "text": _bounded(fact.text, TEXT_CHARS),
                "factKind": fact.kind,
                "createdTs": fact.created_ts,
                "occurredTs": fact.occurrence_ts,
                "recency": snap.recency,
                "sample": origin.sample,
                "origin": origin.id,
                "steps": _fact_steps(fact, card, excerpt, names, fact.id in vectors, origin),
            })
            edges.append({"source": origin.id, "target": node_id, "type": "wrote"})
            if excerpt is not None:
                source_id = f"source:{excerpt.id}"
                push({
                    "id": source_id,
                    "kind": "source",
                    "label": _bounded(excerpt.text, LABEL_CHARS),
                    "text": _bounded(excerpt.text, TEXT_CHARS),
                    "createdTs": excerpt.created_ts,
                    "sample": excerpt.context == SAMPLE_SOURCE,
                    "speaker": excerpt.speaker,
                    "steps": [{
                        "step": STEP_RETAIN, "ts": excerpt.created_ts,
                        "text": "Saved from the Assistant with Save to memory; "
                                "the extractor read it for candidate facts."
                                if excerpt.context != SAMPLE_SOURCE else
                                "A sample excerpt written by the sample seed.",
                    }],
                })
                edges.append({"source": source_id, "target": node_id, "type": "extracted"})
            for eid in entity_ids:
                entity = entities[eid]
                entity_node = f"entity:{eid}"
                push({
                    "id": entity_node,
                    "kind": "entity",
                    "label": _bounded(entity.canonical_name, 40),
                    "text": entity.canonical_name,
                    "entityType": entity.type,
                    "aliases": list(entity.aliases),
                    "factCount": entity.fact_count,
                    "steps": [{
                        "step": STEP_LINK, "ts": None,
                        "text": f"Resolved from the mentions in "
                                f"{_plural(entity.fact_count, 'fact')}; names that "
                                "match an existing entity or alias join it.",
                    }],
                })
                edges.append({"source": node_id, "target": entity_node, "type": "mentions"})
        elif kind == "observation":
            obs = observations.get(int(raw))
            if obs is None:
                continue
            cited = [fid for fid in obs.fact_ids if fid in facts]
            # Observations carry no writer of their own; one whose every
            # cited fact came from the sample seed was seeded alongside them.
            sample = bool(cited) and all(facts[fid].source == SAMPLE_SOURCE for fid in cited)
            reflect = (f"{_plural(len(cited), 'fact')}, confidence {obs.confidence:.2f}.")
            if sample:
                steps = [{"step": STEP_REFLECT, "ts": obs.created_ts,
                          "text": "Written by the sample seed as a reflect run would: "
                                  f"concluded from {reflect}"}]
            else:
                steps = [
                    {"step": STEP_REFLECT, "ts": obs.created_ts,
                     "text": f"A reflect run concluded this from {reflect}"},
                    {"step": STEP_APPROVE, "ts": obs.updated_ts,
                     "text": "You accepted the reflection card; a later run "
                             "with the same words updates it instead of adding one."},
                ]
            push({
                "id": f"observation:{obs.id}",
                "kind": "observation",
                "label": _bounded(obs.text, LABEL_CHARS),
                "text": _bounded(obs.text, TEXT_CHARS),
                "createdTs": obs.created_ts,
                "updatedTs": obs.updated_ts,
                "confidence": obs.confidence,
                "recency": snap.recency,
                "sample": sample,
                "steps": steps,
            })
    for origin_id, origin in origins.items():
        push({
            "id": origin_id,
            "kind": "origin",
            "label": origin.label,
            "text": origin.detail,
            "sample": origin.sample,
            "factCount": origin_counts.get(origin_id, 0),
            "steps": [],
        })
    for node in fact_nodes:
        push(node)

    present = seen
    for edge in snapshot.edges:
        source, target = str(edge.source), str(edge.target)
        if source not in present or target not in present:
            continue
        if edge.type == "derived":
            edges.append({"source": source, "target": target, "type": "cites"})
        elif edge.type in ("temporal", "semantic"):
            edges.append({"source": source, "target": target, "type": edge.type,
                          "weight": round(float(edge.weight), 3)})

    waiting_drafts = 0
    if inbox is not None:
        waiting_drafts = sum(
            1 for card in inbox.waiting(include_snoozed=True)
            if card.kind == KIND_MEMORY_DRAFT
        )
    all_facts = list(facts.values())
    pipeline = [
        {"step": STEP_RETAIN, "count": len(excerpts),
         "text": "Capture keeps the excerpt from the Assistant or Research, or a conversation you saved."},
        {"step": STEP_EXTRACT, "count": sum(1 for f in all_facts if f.source_id is not None),
         "waiting": waiting_drafts,
         "text": "The company endpoint, or the built-in rules when it does not answer, proposes up to five facts."},
        {"step": STEP_APPROVE, "count": sum(1 for f in all_facts if f.source.startswith("inbox card ")),
         "text": "Each candidate waits for review unless auto-approve is on."},
        {"step": STEP_STORE, "count": len(all_facts),
         "text": "Written once: the same words merge into the older fact."},
        {"step": STEP_LINK, "count": len(entities),
         "text": "Mentions resolve to entities; time and meaning link the facts."},
        {"step": STEP_REFLECT, "count": len(observations),
         "text": "Reflect proposes observations that cite the facts behind them."},
    ]
    return {
        "status": "ok",
        "semantic": bool(semantic),
        "window": {"since": since, "until": until, "limit": limit},
        "truncated": len(snapshot.nodes) >= limit,
        "pipeline": pipeline,
        "nodes": nodes,
        "edges": edges,
    }
