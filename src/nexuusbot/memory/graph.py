"""The pure graph snapshot builder (ticket #96, the donor's src/graph.ts).

One bounded slice of the bank for the memory graph page: nodes are the
in-window facts and observations, edges the four relation types, all
computed with no I/O. Everything the builder needs arrives as data:
facts (with their stored vectors), observations (with their citation
lists) and the fact-to-entity link map the recall path already loads.
`now` is always passed in, so the same rows and the same clock produce
the same snapshot forever.

The donor contracts, ported exactly: a node's instant is the
occurrence-else-created time for facts and the updated time for
observations, and a node without a non-null instant inside the window
drops; the survivors order instant descending then id ascending and
slice to the limit (default two hundred, cap one thousand); labels
trim, collapse whitespace runs and truncate at eighty characters with
one trailing ellipsis; recency is the same thirty-day half-life the
recall uses, clamped to the unit interval with a future instant at one.
Edges cap at four thousand overall, built in the donor's order:
semantic (both nodes carry same-model same-dimension vectors, cosine at
least the minimum similarity, the top three per origin by cosine with
id ascending on a tie, deduped by the undirected min-max id key, weight
the cosine), temporal (consecutive nodes in time order within seven
days, weight one minus the gap over the window), entity (each
non-derived fact pairs the next three members of every shared entity in
time order, the weight accumulating once per shared entity, deduped by
the undirected key) and derived (directed observation to cited fact,
only when the fact node is in the snapshot, weight one).

Two recorded divergences, both making the static page safe: the donor
raises on an out-of-range limit or minimum similarity while this
builder clamps them into range (the HTTP route guards the query string
the same way, so the builder refusing would only duplicate the check a
page must never trip); and the entity groups iterate in entity-id
order where the donor iterates unspecified row order, so the edge list
is deterministic on both banks (the edge set is identical either way).

Reusable helpers are reused, never re-spelled: the instant and recency
arithmetic come from memory/hybrid; the unit-vector dot that scores
semantic pairs lives here (memory/embed's cosine is the same math with
both magnitudes folded back in).
"""

import math
from dataclasses import dataclass
from nexuusbot.memory.hybrid import (
    DAY_SECONDS,
    HALF_LIFE_DAYS,
    EntityLink,
    event_instant,
    recency_factor,
)

DEFAULT_GRAPH_LIMIT = 200
MAX_GRAPH_LIMIT = 1000
DEFAULT_MIN_SIMILARITY = 0.72
SEMANTIC_K = 3
ENTITY_DEGREE = 3
TEMPORAL_WINDOW_SECONDS = 7 * DAY_SECONDS
MAX_EDGES = 4000
LABEL_LENGTH = 80

SEMANTIC = "semantic"
TEMPORAL = "temporal"
ENTITY = "entity"
DERIVED = "derived"


@dataclass(frozen=True)
class GraphFact:
    """One fact row as the builder reads it: the Fact's identity and
    dates plus the stored vector triple (ticket #95). The store's read
    produces these; the decoded embedding is a list of floats or None
    when the row carries no usable vector. The id is whatever unique
    key the caller uses for nodes (the store qualifies its per-table
    integers as `fact:<id>`, mirroring the donor's globally unique
    ids, so a fact and an observation can never share one)."""

    id: int | str
    text: str
    created_ts: float
    kind: str = "world"
    occurrence_ts: float | None = None
    embedding: list[float] | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None


@dataclass(frozen=True)
class GraphObservation:
    """One observation row as the builder reads it (the Observation's
    shape with the node id the caller chose). Plain Observation rows
    are accepted just the same: the builder reads attributes."""

    id: int | str
    text: str
    updated_ts: float
    fact_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class GraphNode:
    """One rendered node: the bounded label, the kind, the instant the
    node was placed at, its recency shading and the citation count
    (one for a fact, the citation total for an observation). The id is
    the row's node id verbatim, so comparable values of one type (the
    donor compared strings; the store qualifies its integers)."""

    id: int | str
    label: str
    kind: str
    instant: float
    recency: float
    source_fact_count: int
    derived: bool


@dataclass(frozen=True)
class GraphEdge:
    """One rendered edge: the endpoint ids (undirected types normalized
    to the smaller id first, derived directed observation to fact), the
    type, and the weight the donor's arithmetic produced."""

    source: int | str
    target: int | str
    type: str
    weight: float


@dataclass(frozen=True)
class GraphSnapshot:
    """The page's whole input: the selected nodes (newest first) and
    the capped edges (semantic, temporal, entity, derived)."""

    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()


@dataclass
class _Raw:
    """The builder's internal node before the label and recency land."""

    id: int | str
    text: str
    kind: str
    instant: float
    source_fact_count: int
    derived: bool
    vector: list[float] | None = None
    model: str | None = None
    dim: int | None = None
    citations: tuple[int, ...] = ()


def truncate_label(text: str) -> str:
    """The donor's truncate: trim, collapse internal whitespace runs to
    single spaces, then cut at eighty characters with one trailing
    ellipsis, so the label is never longer than the bound."""
    trimmed = " ".join(text.split())
    if len(trimmed) <= LABEL_LENGTH:
        return trimmed
    return trimmed[: LABEL_LENGTH - 1] + "\u2026"


def _vector_of(row) -> list[float] | None:
    """The row's decoded vector, or None: absent whenever any part of
    the stored triple is missing (the donor's vectorOf), because a
    partial vector cannot honestly compare."""
    vector = getattr(row, "embedding", None)
    model = getattr(row, "embedding_model", None)
    dim = getattr(row, "embedding_dim", None)
    if not vector or model is None or dim is None:
        return None
    return list(vector)


def _in_range(when: float, since: float | None, until: float | None) -> bool:
    """The donor's inRange: the since bound inclusive, the until bound
    exclusive, both optional."""
    if since is not None and when < since:
        return False
    if until is not None and when >= until:
        return False
    return True


def build_graph(
    facts,
    observations,
    entity_links: dict[int, list[EntityLink]] | None,
    now: float,
    since: float | None = None,
    until: float | None = None,
    limit: int = DEFAULT_GRAPH_LIMIT,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> GraphSnapshot:
    """The bounded snapshot (the donor's buildGraphSnapshot): select,
    order and slice the nodes, then build the four edge types in the
    donor's order under the overall cap.

    `facts` are GraphFact rows (or anything with the same attributes),
    `observations` are memory/core Observation rows, `entity_links` the
    fact-id to linked-entities map the recall path loads (EntityLink
    rows, bare ids tolerated). The bounds are epoch seconds, the since
    bound inclusive and the until bound exclusive. Out-of-range limit
    and minimum similarity clamp into 1..1000 and 0..1 (the recorded
    divergence above), so the builder never raises on its numbers.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_GRAPH_LIMIT
    limit = min(max(limit, 1), MAX_GRAPH_LIMIT)
    if not isinstance(min_similarity, (int, float)) or isinstance(min_similarity, bool):
        min_similarity = DEFAULT_MIN_SIMILARITY
    min_similarity = min(max(float(min_similarity), 0.0), 1.0)
    links: dict = entity_links or {}

    raw: list[_Raw] = []
    for row in facts or ():
        when = event_instant(getattr(row, "occurrence_ts", None),
                             getattr(row, "created_ts", None))
        if when is None or not _in_range(when, since, until):
            continue
        raw.append(_Raw(
            id=row.id,
            text=getattr(row, "text", "") or "",
            kind=getattr(row, "kind", "world"),
            instant=when,
            source_fact_count=1,
            derived=False,
            vector=_vector_of(row),
            model=getattr(row, "embedding_model", None),
            dim=getattr(row, "embedding_dim", None),
        ))
    for row in observations or ():
        when = getattr(row, "updated_ts", None)
        if when is None or not _in_range(when, since, until):
            continue
        citations = tuple(getattr(row, "fact_ids", ()) or ())
        raw.append(_Raw(
            id=row.id,
            text=getattr(row, "text", "") or "",
            kind="observation",
            instant=when,
            source_fact_count=len(citations),
            derived=True,
            citations=citations,
        ))

    raw.sort(key=lambda node: (-node.instant, node.id))
    selected = raw[:limit]
    if not selected:
        return GraphSnapshot()

    edges: list[GraphEdge] = []
    _push_semantic(selected, min_similarity, edges)
    _push_temporal(selected, edges)
    _push_entity(selected, links, edges)
    _push_derived(selected, edges)

    nodes = tuple(
        GraphNode(
            id=node.id,
            label=truncate_label(node.text),
            kind=node.kind,
            instant=node.instant,
            recency=recency_factor(node.instant, now, HALF_LIFE_DAYS),
            source_fact_count=node.source_fact_count,
            derived=node.derived,
        )
        for node in selected
    )
    return GraphSnapshot(nodes=nodes, edges=tuple(edges[:MAX_EDGES]))


def _push_semantic(selected: list[_Raw], min_similarity: float,
                   edges: list[GraphEdge]) -> None:
    """The donor's pushSemantic: every vector-bearing origin keeps its
    top three same-model same-dimension neighbours above the cutoff,
    deduped by the undirected key so a mutual pair is one edge. Each
    vector normalizes exactly once and pairs score by the dot product
    of the unit vectors (the review's finding 1): pairwise cosine is
    the page's hot path once a real bank carries 1536-dimension
    vectors, and recomputing both magnitudes per pair made it
    quadratic in float work on top of quadratic in pairs."""
    units: dict[str, tuple[float, ...]] = {}
    for node in selected:
        vector = node.vector
        if not vector:
            continue
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            continue
        units[node.id] = tuple(value / norm for value in vector)
    indexed = [node for node in selected if node.id in units]
    seen: set[tuple[int, int]] = set()
    for origin in indexed:
        origin_unit = units[origin.id]
        scored: list[tuple[int, float]] = []
        for other in indexed:
            if other.id == origin.id:
                continue
            if other.model != origin.model or other.dim != origin.dim:
                continue
            if len(other.vector) != len(origin.vector):
                continue
            weight = sum(
                a * b for a, b in zip(origin_unit, units[other.id])
            )
            if weight >= min_similarity:
                scored.append((other.id, weight))
        scored.sort(key=lambda item: (-item[1], item[0]))
        for other_id, weight in scored[:SEMANTIC_K]:
            key = (min(origin.id, other_id), max(origin.id, other_id))
            if key in seen:
                continue
            seen.add(key)
            if len(edges) >= MAX_EDGES:
                return
            edges.append(GraphEdge(key[0], key[1], SEMANTIC, weight))


def _push_temporal(selected: list[_Raw], edges: list[GraphEdge]) -> None:
    """The donor's pushTemporal: consecutive nodes in time order join
    when their gap is within the seven-day window, the weight decaying
    linearly with the gap."""
    ordered = sorted(selected, key=lambda node: (node.instant, node.id))
    for index in range(len(ordered) - 1):
        left = ordered[index]
        right = ordered[index + 1]
        gap = right.instant - left.instant
        if gap < 0 or gap > TEMPORAL_WINDOW_SECONDS:
            continue
        if len(edges) >= MAX_EDGES:
            return
        weight = 1 - gap / TEMPORAL_WINDOW_SECONDS
        edges.append(GraphEdge(
            min(left.id, right.id), max(left.id, right.id), TEMPORAL, weight
        ))


def _push_entity(selected: list[_Raw], links: dict,
                 edges: list[GraphEdge]) -> None:
    """The donor's pushEntity: the snapshot's non-derived facts group by
    shared entity, each member pairing the next three in the member
    list's time order; a pair sharing several entities accumulates one
    weight per entity into a single edge. Groups iterate in entity-id
    order so the edge list is deterministic (the recorded divergence)."""
    members: dict[int, list[int]] = {}
    for node in selected:
        if node.derived:
            continue
        for link in links.get(node.id, ()) or ():
            entity_id = getattr(link, "id", link)
            members.setdefault(entity_id, []).append(node.id)
    when = {node.id: node.instant for node in selected}
    shared: dict[tuple[int, int], list] = {}
    for entity_id in sorted(members):
        unique = sorted(
            set(members[entity_id]),
            key=lambda fact_id: (when.get(fact_id, 0.0), fact_id),
        )
        for index in range(len(unique)):
            origin = unique[index]
            for step in range(1, ENTITY_DEGREE + 1):
                if index + step >= len(unique):
                    break
                other = unique[index + step]
                key = (min(origin, other), max(origin, other))
                entry = shared.get(key)
                if entry is not None:
                    entry[2] += 1
                else:
                    shared[key] = [key[0], key[1], 1]
    for source, target, weight in shared.values():
        if len(edges) >= MAX_EDGES:
            return
        edges.append(GraphEdge(source, target, ENTITY, weight))


def _push_derived(selected: list[_Raw], edges: list[GraphEdge]) -> None:
    """The donor's pushDerived: a directed edge from every snapshot
    observation to each of its cited facts that is itself in the
    snapshot, weight one."""
    present = {node.id for node in selected}
    for node in selected:
        if not node.derived:
            continue
        for fact_id in node.citations:
            if fact_id not in present:
                continue
            if len(edges) >= MAX_EDGES:
                return
            edges.append(GraphEdge(node.id, fact_id, DERIVED, 1))
