"""The pure graph snapshot builder (ticket #96, the donor's src/graph.ts).

Donor contracts pinned here: node selection keeps facts and observations
whose instant (occurrence-else-created, the observation's updated time)
is non-null and inside the window, ordered instant descending then id
ascending, sliced to the limit (default two hundred, cap one thousand);
labels trim, collapse whitespace and truncate at eighty characters with
one trailing ellipsis; recency is the thirty-day half-life clamped to
the unit interval; edges cap at four thousand overall with semantic
(cosine at least the minimum, top three per origin, deduped undirected),
temporal (consecutive time-ordered nodes within seven days, weight
decaying with the gap), entity (each fact pairs the next three members
in time order, weight accumulating per shared entity) and derived
(directional observation to cited fact, only when the fact is present)
edges in that order. No I/O anywhere: every row arrives as data.
"""

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.memory.embed import cosine
from agentdesk.memory.graph import (
    DEFAULT_GRAPH_LIMIT,
    DEFAULT_MIN_SIMILARITY,
    LABEL_LENGTH,
    MAX_EDGES,
    MAX_GRAPH_LIMIT,
    GraphEdge,
    GraphFact,
    build_graph,
    truncate_label,
)
from agentdesk.memory.core import Observation
from agentdesk.memory.hybrid import EntityLink, DAY_SECONDS

DAY = DAY_SECONDS
NOW = 1_800_000_000.0
MODEL = "fake-embed"


def _fact(
    fact_id,
    text="a fact",
    created=NOW,
    occurrence=None,
    embedding=None,
    model=MODEL,
    dim=None,
):
    if dim is None and embedding is not None:
        dim = len(embedding)
    return GraphFact(
        id=fact_id,
        text=text,
        kind="world",
        created_ts=created,
        occurrence_ts=occurrence,
        embedding=embedding,
        embedding_model=model,
        embedding_dim=dim,
    )


def _obs(obs_id, fact_ids=(), updated=NOW, text="an observation"):
    return Observation(
        id=obs_id,
        text=text,
        confidence=0.9,
        fact_ids=tuple(fact_ids),
        created_ts=updated,
        updated_ts=updated,
    )


def _dir_vector(cosine_value, dim=5, axis=1):
    """One vector whose cosine with e1 is exactly the given value: the
    value rides the first axis and the remainder sits on the axis the
    caller picks, so two of these with different axes share only the
    e1 component (their mutual cosine is the product of the values)."""
    rest = math.sqrt(max(0.0, 1.0 - cosine_value * cosine_value))
    vector = [0.0] * dim
    vector[0] = cosine_value
    vector[axis] = rest
    return vector


# -- node selection -----------------------------------------------------------


def test_occurrence_else_created_instant():
    snapshot = build_graph([_fact(1, occurrence=NOW - 5 * DAY, created=NOW)], [], {}, NOW)
    assert snapshot.nodes[0].instant == NOW - 5 * DAY


def test_a_fact_without_an_instant_is_dropped():
    undated = SimpleNamespace(
        id=9,
        text="no dates at all",
        kind="world",
        created_ts=None,
        occurrence_ts=None,
        embedding=None,
        embedding_model=None,
        embedding_dim=None,
    )
    snapshot = build_graph([_fact(1), undated], [], {}, NOW)
    assert [node.id for node in snapshot.nodes] == [1]


def test_an_observation_without_an_updated_instant_is_dropped():
    undated = SimpleNamespace(
        id=9,
        text="no update time",
        confidence=0.5,
        fact_ids=(1,),
        created_ts=None,
        updated_ts=None,
    )
    snapshot = build_graph([_fact(1)], [undated], {}, NOW)
    assert [node.id for node in snapshot.nodes] == [1]


def test_observation_instant_is_the_updated_time():
    snapshot = build_graph(
        [_fact(1)], [_obs(7, fact_ids=(1,), updated=NOW - 9 * DAY)], {}, NOW
    )
    nodes = {node.id: node for node in snapshot.nodes}
    observation = nodes[7]
    assert observation.instant == NOW - 9 * DAY
    assert observation.kind == "observation"
    assert observation.derived is True


def test_window_filters_inclusive_since_exclusive_until():
    facts = [
        _fact(1, occurrence=NOW - 1 * DAY),  # before since
        _fact(2, occurrence=NOW),  # exactly since
        _fact(3, occurrence=NOW + 2 * DAY),  # inside
        _fact(4, occurrence=NOW + 3 * DAY),  # exactly until
        _fact(5, occurrence=NOW + 5 * DAY),  # after until
    ]
    snapshot = build_graph(facts, [], {}, NOW, since=NOW, until=NOW + 3 * DAY)
    # Newest first: id 3 (NOW + 2 days) precedes id 2 (exactly since).
    assert [node.id for node in snapshot.nodes] == [3, 2]


def test_window_applies_to_observations_too():
    inside = _obs(11, fact_ids=(1,), updated=NOW + 1 * DAY)
    outside = _obs(12, fact_ids=(1,), updated=NOW + 3 * DAY)
    snapshot = build_graph([_fact(1)], [inside, outside], {}, NOW, until=NOW + 3 * DAY)
    assert [node.id for node in snapshot.nodes] == [11, 1]


def test_ordering_is_instant_descending_then_id_ascending():
    facts = [
        _fact(1, occurrence=NOW),
        _fact(2, occurrence=NOW + 5 * DAY),
        _fact(3, occurrence=NOW + 2 * DAY),
        _fact(7, occurrence=NOW),  # ties with id 1 on the instant
    ]
    snapshot = build_graph(facts, [], {}, NOW)
    assert [node.id for node in snapshot.nodes] == [2, 3, 1, 7]


def test_observations_and_facts_share_one_order():
    fact = _fact(1, occurrence=NOW)
    newer_observation = _obs(5, fact_ids=(1,), updated=NOW + 1 * DAY)
    snapshot = build_graph([fact], [newer_observation], {}, NOW)
    assert [node.id for node in snapshot.nodes] == [5, 1]


def test_limit_slices_the_sorted_nodes():
    facts = [
        _fact(1, occurrence=NOW),
        _fact(2, occurrence=NOW + 4 * DAY),
        _fact(3, occurrence=NOW + 2 * DAY),
        _fact(4, occurrence=NOW + 6 * DAY),
        _fact(5, occurrence=NOW + 8 * DAY),
    ]
    snapshot = build_graph(facts, [], {}, NOW, limit=3)
    assert [node.id for node in snapshot.nodes] == [5, 4, 2]


def test_limit_counts_facts_and_observations_together():
    snapshot = build_graph(
        [_fact(1), _fact(2)], [_obs(3, fact_ids=(1,)), _obs(4, fact_ids=(2,))],
        {}, NOW, limit=3,
    )
    assert len(snapshot.nodes) == 3


def test_the_default_limit_is_two_hundred():
    assert DEFAULT_GRAPH_LIMIT == 200
    facts = [_fact(i, occurrence=NOW + i * DAY) for i in range(1, 205)]
    snapshot = build_graph(facts, [], {}, NOW)
    assert len(snapshot.nodes) == 200


def test_out_of_range_limits_clamp_into_one_to_one_thousand():
    assert MAX_GRAPH_LIMIT == 1000
    facts = [_fact(i, occurrence=NOW + i * DAY) for i in range(1, 1003)]
    assert len(build_graph(facts, [], {}, NOW, limit=10**6).nodes) == 1000
    assert len(build_graph(facts, [], {}, NOW, limit=0).nodes) == 1
    assert len(build_graph(facts, [], {}, NOW, limit=-5).nodes) == 1


def test_a_limit_past_the_node_count_keeps_every_node():
    snapshot = build_graph([_fact(1), _fact(2)], [], {}, NOW, limit=50)
    assert len(snapshot.nodes) == 2


# -- labels -------------------------------------------------------------------


def test_label_truncation_at_the_boundary():
    assert LABEL_LENGTH == 80
    exact = "x" * 80
    assert truncate_label(exact) == exact
    assert "…" not in truncate_label(exact)
    long = "y" * 81
    truncated = truncate_label(long)
    assert truncated == "y" * 79 + "…"
    assert len(truncated) == 80


def test_label_trims_and_collapses_whitespace():
    assert truncate_label("  spaced\n\t out   text  ") == "spaced out text"


def test_node_labels_are_truncated_in_the_snapshot():
    snapshot = build_graph([_fact(1, text="z" * 200)], [], {}, NOW)
    assert snapshot.nodes[0].label == "z" * 79 + "…"


# -- recency and source counts ------------------------------------------------


def test_recency_follows_the_thirty_day_half_life():
    snapshot = build_graph(
        [
            _fact(1, occurrence=NOW),
            _fact(2, occurrence=NOW - 30 * DAY),
            _fact(3, occurrence=NOW - 60 * DAY),
        ],
        [],
        {},
        NOW,
    )
    recency = {node.id: node.recency for node in snapshot.nodes}
    assert recency[1] == 1.0
    assert recency[2] == pytest.approx(0.5)
    assert recency[3] == pytest.approx(0.25)


def test_recency_of_a_future_instant_is_one():
    snapshot = build_graph([_fact(1, occurrence=NOW + 10 * DAY)], [], {}, NOW)
    assert snapshot.nodes[0].recency == 1.0


def test_recency_stays_inside_the_unit_interval():
    snapshot = build_graph([_fact(1, occurrence=NOW - 3650 * DAY)], [], {}, NOW)
    assert 0.0 <= snapshot.nodes[0].recency <= 1.0
    assert snapshot.nodes[0].recency == pytest.approx(0.0, abs=1e-9)


def test_source_fact_count_is_one_for_facts_and_citations_for_observations():
    snapshot = build_graph(
        [_fact(1), _fact(2)], [_obs(9, fact_ids=(1, 2), updated=NOW)], {}, NOW
    )
    counts = {node.id: node.source_fact_count for node in snapshot.nodes}
    assert counts[1] == 1
    assert counts[2] == 1
    assert counts[9] == 2


def test_an_observation_without_citations_counts_zero():
    snapshot = build_graph([_fact(1)], [_obs(9)], {}, NOW)
    observation = next(node for node in snapshot.nodes if node.id == 9)
    assert observation.source_fact_count == 0
    assert observation.derived is True


# -- semantic edges -----------------------------------------------------------


def test_a_strong_pair_makes_one_undirected_semantic_edge():
    left = _fact(1, embedding=_dir_vector(1.0))
    right = _fact(2, embedding=_dir_vector(0.98), occurrence=NOW + DAY)
    snapshot = build_graph([left, right], [], {}, NOW)
    semantic = [edge for edge in snapshot.edges if edge.type == "semantic"]
    assert len(semantic) == 1
    edge = semantic[0]
    assert (edge.source, edge.target) == (1, 2)
    assert edge.weight == pytest.approx(cosine(left.embedding, right.embedding))


def test_the_similarity_threshold_is_inclusive():
    left = _fact(1, embedding=[1.0, 0.0])
    right = _fact(2, embedding=[0.72, math.sqrt(1 - 0.72**2)])
    weight = cosine(left.embedding, right.embedding)
    kept = build_graph([left, right], [], {}, NOW, min_similarity=weight)
    assert any(edge.type == "semantic" for edge in kept.edges)
    refused = build_graph(
        [left, right], [], {}, NOW, min_similarity=math.nextafter(weight, math.inf)
    )
    assert not any(edge.type == "semantic" for edge in refused.edges)


def test_the_default_minimum_similarity_is_zero_point_seven_two():
    assert DEFAULT_MIN_SIMILARITY == 0.72
    left = _fact(1, embedding=_dir_vector(0.71, axis=1))
    right = _fact(2, embedding=_dir_vector(0.72, axis=2))
    snapshot = build_graph([left, right], [], {}, NOW)
    # The pair's mutual cosine is 0.71*0.72 (the remainders are
    # orthogonal), below the default cutoff, so nothing links them.
    assert not any(edge.type == "semantic" for edge in snapshot.edges)


def test_semantic_keeps_the_top_three_per_origin():
    # Fact 1 sees five candidates at the same 0.9 cosine (tied, so the
    # id-ascending tie-break applies); its own top three are ids 2, 3
    # and 4. Candidates 5 and 6 stay above the cutoff yet never link to
    # fact 1: their own origin slots rank the identical siblings above
    # it, and fact 1 already spent its three picks. The 3-per-origin
    # cap is what keeps the pair count at three, not six.
    facts = [_fact(1, embedding=[1.0, 0.0, 0.0, 0.0, 0.0])]
    facts += [
        _fact(i, embedding=_dir_vector(0.9, axis=1), occurrence=NOW + i * DAY)
        for i in range(2, 7)
    ]
    snapshot = build_graph(facts, [], {}, NOW, min_similarity=0.85)
    semantic = [edge for edge in snapshot.edges if edge.type == "semantic"]
    touching_one = {(edge.source, edge.target): edge.weight
                    for edge in semantic if 1 in (edge.source, edge.target)}
    assert set(touching_one) == {(1, 2), (1, 3), (1, 4)}
    assert touching_one[(1, 2)] == pytest.approx(0.9)
    assert touching_one[(1, 3)] == pytest.approx(0.9)
    assert touching_one[(1, 4)] == pytest.approx(0.9)


def test_mutual_hits_dedupe_to_one_edge():
    left = _fact(1, embedding=_dir_vector(0.99))
    right = _fact(2, embedding=_dir_vector(0.98))
    snapshot = build_graph([left, right], [], {}, NOW)
    semantic = [edge for edge in snapshot.edges if edge.type == "semantic"]
    assert len(semantic) == 1


def test_semantic_compares_same_model_same_dim_only():
    vector = _dir_vector(0.99)
    same_vector = list(vector)
    mixed_model = build_graph(
        [_fact(1, embedding=vector, model=MODEL),
         _fact(2, embedding=same_vector, model="other-embed")],
        [], {}, NOW,
    )
    assert not any(edge.type == "semantic" for edge in mixed_model.edges)
    mismatched = build_graph(
        [_fact(1, embedding=vector),
         _fact(2, embedding=[0.9, 0.43589, 0.0, 0.0, 0.0, 0.0])],
        [], {}, NOW,
    )
    assert not any(edge.type == "semantic" for edge in mismatched.edges)


def test_zero_vectors_never_make_semantic_edges():
    left = _fact(1, embedding=[0.0, 0.0], dim=2)
    right = _fact(2, embedding=[1.0, 0.0], dim=2)
    snapshot = build_graph([left, right], [], {}, NOW)
    assert not any(edge.type == "semantic" for edge in snapshot.edges)


def test_facts_without_vectors_still_join_the_other_edge_types():
    facts = [
        _fact(1, occurrence=NOW),
        _fact(2, occurrence=NOW + DAY),
    ]
    links = {1: [EntityLink(id=3, name="Hub")], 2: [EntityLink(id=3, name="Hub")]}
    snapshot = build_graph(facts, [], links, NOW)
    assert not any(edge.type == "semantic" for edge in snapshot.edges)
    assert {edge.type for edge in snapshot.edges} == {"entity", "temporal"}


def test_out_of_range_similarity_clamps_into_the_unit_interval():
    twin = _fact(1, embedding=[1.0, 0.0, 0.0, 0.0, 0.0])
    near = _fact(2, embedding=_dir_vector(0.9, axis=1))
    same = _fact(3, embedding=[1.0, 0.0, 0.0, 0.0, 0.0], occurrence=NOW + DAY)
    # Clamped to 1.0: only the identical direction survives.
    strict = build_graph([twin, near, same], [], {}, NOW, min_similarity=1.5)
    semantic = [(edge.source, edge.target)
                for edge in strict.edges if edge.type == "semantic"]
    assert semantic == [(1, 3)]
    # Clamped to 0.0: the 0.9 pair joins the identical one.
    loosest = build_graph([twin, near, same], [], {}, NOW, min_similarity=-0.5)
    pairs = {(edge.source, edge.target)
             for edge in loosest.edges if edge.type == "semantic"}
    assert pairs == {(1, 2), (1, 3), (2, 3)}


# -- temporal edges -----------------------------------------------------------


def test_temporal_edges_join_consecutive_nodes_within_seven_days():
    facts = [
        _fact(1, occurrence=NOW),
        _fact(2, occurrence=NOW + 1 * DAY),
        _fact(3, occurrence=NOW + 5 * DAY),
    ]
    snapshot = build_graph(facts, [], {}, NOW)
    temporal = [edge for edge in snapshot.edges if edge.type == "temporal"]
    assert len(temporal) == 2
    weights = {(edge.source, edge.target): edge.weight for edge in temporal}
    assert weights[(1, 2)] == pytest.approx(1 - 1 / 7)
    assert weights[(2, 3)] == pytest.approx(1 - 4 / 7)


def test_the_temporal_boundary_is_seven_days_exactly():
    edge_case = build_graph(
        [_fact(1, occurrence=NOW), _fact(2, occurrence=NOW + 7 * DAY)], [], {}, NOW
    )
    temporal = [edge for edge in edge_case.edges if edge.type == "temporal"]
    assert len(temporal) == 1
    assert temporal[0].weight == pytest.approx(0.0)
    past_it = build_graph(
        [_fact(1, occurrence=NOW), _fact(2, occurrence=NOW + 7 * DAY + 1)], [], {}, NOW
    )
    assert not any(edge.type == "temporal" for edge in past_it.edges)


def test_temporal_endpoints_normalize_undirected():
    # The earlier instant carries the larger id, so the edge normalizes
    # to the smaller id first.
    snapshot = build_graph(
        [_fact(2, occurrence=NOW), _fact(1, occurrence=NOW + 1 * DAY)], [], {}, NOW
    )
    temporal = [edge for edge in snapshot.edges if edge.type == "temporal"]
    assert [(edge.source, edge.target) for edge in temporal] == [(1, 2)]


def test_equal_instants_are_one_day_zero_gap_edges():
    snapshot = build_graph(
        [_fact(1, occurrence=NOW), _fact(2, occurrence=NOW)], [], {}, NOW
    )
    temporal = [edge for edge in snapshot.edges if edge.type == "temporal"]
    assert len(temporal) == 1
    assert temporal[0].weight == pytest.approx(1.0)


# -- entity edges -------------------------------------------------------------


def test_entity_edges_pair_each_fact_with_the_next_three_in_time():
    facts = [_fact(i, occurrence=NOW + i * DAY) for i in range(1, 6)]
    links = {i: [EntityLink(id=50, name="Hub")] for i in range(1, 6)}
    snapshot = build_graph(facts, [], links, NOW)
    entity = [edge for edge in snapshot.edges if edge.type == "entity"]
    pairs = {(edge.source, edge.target): edge.weight for edge in entity}
    expected = {
        (1, 2), (1, 3), (1, 4),
        (2, 3), (2, 4), (2, 5),
        (3, 4), (3, 5),
        (4, 5),
    }
    assert set(pairs) == expected
    assert all(weight == 1 for weight in pairs.values())


def test_entity_members_order_by_instant_then_id_not_link_order():
    # Link rows arrive in an arbitrary order; the pairing follows time.
    facts = [
        _fact(3, occurrence=NOW + 2 * DAY),
        _fact(1, occurrence=NOW),
        _fact(2, occurrence=NOW + 1 * DAY),
    ]
    links = {
        3: [EntityLink(id=50, name="Hub")],
        1: [EntityLink(id=50, name="Hub")],
        2: [EntityLink(id=50, name="Hub")],
    }
    snapshot = build_graph(facts, [], links, NOW)
    entity = [edge for edge in snapshot.edges if edge.type == "entity"]
    assert {(edge.source, edge.target) for edge in entity} == {(1, 2), (1, 3), (2, 3)}


def test_entity_weights_accumulate_per_shared_entity():
    facts = [_fact(1), _fact(2)]
    links = {
        1: [EntityLink(id=50, name="Alpha"), EntityLink(id=51, name="Beta")],
        2: [EntityLink(id=50, name="Alpha"), EntityLink(id=51, name="Beta")],
    }
    snapshot = build_graph(facts, [], links, NOW)
    entity = [edge for edge in snapshot.edges if edge.type == "entity"]
    assert len(entity) == 1
    assert (entity[0].source, entity[0].target) == (1, 2)
    assert entity[0].weight == 2


def test_entity_edges_ignore_observations_and_absent_facts():
    facts = [_fact(1)]
    links = {
        # An observation id and a fact outside the snapshot ride the
        # same entity; neither may contribute an edge.
        9: [EntityLink(id=50, name="Hub")],
        99: [EntityLink(id=50, name="Hub")],
        1: [EntityLink(id=50, name="Hub")],
    }
    snapshot = build_graph(facts, [_obs(9, fact_ids=(1,))], links, NOW)
    entity = [edge for edge in snapshot.edges if edge.type == "entity"]
    assert entity == []


def test_bare_entity_ids_in_the_links_map_are_accepted():
    facts = [_fact(1), _fact(2)]
    snapshot = build_graph(facts, [], {1: [50], 2: [50]}, NOW)
    entity = [edge for edge in snapshot.edges if edge.type == "entity"]
    assert len(entity) == 1


# -- derived edges ------------------------------------------------------------


def test_derived_edges_point_from_the_observation_to_the_cited_fact():
    facts = [_fact(1), _fact(2)]
    snapshot = build_graph(facts, [_obs(9, fact_ids=(1, 2), updated=NOW)], {}, NOW)
    derived = [edge for edge in snapshot.edges if edge.type == "derived"]
    assert {(edge.source, edge.target) for edge in derived} == {(9, 1), (9, 2)}
    assert all(edge.weight == 1 for edge in derived)
    for edge in derived:
        assert isinstance(edge, GraphEdge)


def test_citations_to_absent_facts_make_no_derived_edge():
    # Fact 5 exists but sits outside the window; the citation drops.
    snapshot = build_graph(
        [_fact(1), _fact(5, occurrence=NOW - 30 * DAY)],
        [_obs(9, fact_ids=(1, 5), updated=NOW)],
        {},
        NOW,
        since=NOW - DAY,
    )
    derived = [edge for edge in snapshot.edges if edge.type == "derived"]
    assert [(edge.source, edge.target) for edge in derived] == [(9, 1)]


# -- the overall edge cap -----------------------------------------------------


def test_edges_cap_at_four_thousand_with_earlier_types_first():
    # Six hundred facts, identical instants, one entity and identical
    # directions: semantic (3n-6), temporal (n-1) and entity (3n-6)
    # candidates together overrun the cap, so the truncation keeps
    # semantic first, then temporal, then as much entity as fits.
    assert MAX_EDGES == 4000
    count = 600
    vector = [1.0, 0.0]
    facts = [
        _fact(i, occurrence=NOW, embedding=list(vector), dim=2)
        for i in range(1, count + 1)
    ]
    links = {i: [EntityLink(id=1, name="Hub")] for i in range(1, count + 1)}
    snapshot = build_graph(facts, [], links, NOW, limit=count)
    assert len(snapshot.edges) == MAX_EDGES
    by_type: dict[str, int] = {}
    for edge in snapshot.edges:
        by_type[edge.type] = by_type.get(edge.type, 0) + 1
    semantic_expected = 3 * count - 6
    temporal_expected = count - 1
    assert by_type["semantic"] == semantic_expected
    assert by_type["temporal"] == temporal_expected
    assert by_type["entity"] == MAX_EDGES - semantic_expected - temporal_expected
    # The types appear in donor order along the edge list.
    types_in_order = []
    for edge in snapshot.edges:
        if not types_in_order or types_in_order[-1] != edge.type:
            types_in_order.append(edge.type)
    assert types_in_order == ["semantic", "temporal", "entity"]


# -- empties ------------------------------------------------------------------


def test_empty_inputs_make_an_empty_snapshot():
    snapshot = build_graph([], [], {}, NOW)
    assert snapshot.nodes == ()
    assert snapshot.edges == ()


def test_a_single_fact_renders_alone_without_edges():
    snapshot = build_graph([_fact(1)], [], {}, NOW)
    assert len(snapshot.nodes) == 1
    assert snapshot.edges == ()
    node = snapshot.nodes[0]
    assert node.label == "a fact"
    assert node.kind == "world"
    assert node.derived is False
    assert node.instant == NOW
