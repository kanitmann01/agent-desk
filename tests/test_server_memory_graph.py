"""The memory graph page over HTTP (ticket #96): the primary seam.

The page is server-rendered static SVG in the memory pages' style: the
route is authenticated like every route, an empty bank renders the
empty state, the counts header names the snapshot's facts, observations
and edges, the legend names the four edge types, and the since, until
and limit query parameters clamp and parse without ever failing the
render. The bank seeds through the real store the routes share.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

UTC = timezone.utc  # datetime.UTC needs 3.11; the declared floor is 3.10

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.memory.embed import encode_embedding


@pytest.fixture()
def booted():
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(booted):
    return booted.exchange()


def _ts(*parts) -> float:
    return datetime(*parts, tzinfo=UTC).timestamp()


def _seed(store) -> None:
    """The shared bank: two platform-team facts a day apart sharing an
    entity, close vectors on the pair (one semantic edge), and an
    observation citing them both."""
    day = 86_400.0
    first = store.add(
        "alice runs the platform team", source="page",
        occurrence_ts=_ts(2026, 1, 15),
    )
    second = store.add(
        "the platform team shipped the release", source="page",
        occurrence_ts=_ts(2026, 1, 16),
    )
    store.add("an unrelated note about printers", source="page",
              occurrence_ts=_ts(2026, 3, 1))
    store.resolve_and_link(first.id, [("Platform Team", "org")])
    store.resolve_and_link(second.id, [("Platform Team", "org")])
    store.save_observation(
        "scope", "the platform team is shipping steadily", 0.9,
        [first.id, second.id], time.time(),
    )
    for fact_id, vector in ((first.id, [1.0, 0.0]),
                            (second.id, [0.98, 0.19899748742132497])):
        store.conn.execute(
            "UPDATE facts SET embedding = ?, embedding_model = ?,"
            " embedding_dim = ? WHERE id = ?",
            (encode_embedding(vector), "fake-embed", len(vector), fact_id),
        )


def _nodes(page: str) -> int:
    return page.count('class="graph-node"')


# -- auth ---------------------------------------------------------------------


def test_the_graph_route_requires_a_session(booted):
    status, _h, _b = booted.request("GET", "/memory/graph", booted.host_header())
    assert status == 401


# -- the page's shapes --------------------------------------------------------


def test_an_empty_bank_renders_the_empty_state(booted, auth):
    status, _h, body = booted.request("GET", "/memory/graph", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert 'id="graph-empty"' in page
    assert 'id="memory-graph"' not in page
    assert "0 facts" in page
    assert "0 observations" in page
    assert "0 edges" in page


def test_the_seeded_page_renders_svg_with_every_edge_type_and_counts(booted, auth):
    _seed(booted.server.memory)
    expected = booted.server.memory.graph_snapshot(now=time.time())
    status, _h, body = booted.request("GET", "/memory/graph", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "<svg" in page and 'id="memory-graph"' in page
    assert _nodes(page) == len(expected.nodes)
    assert "graph-legend" in page
    for edge_type in ("entity", "temporal", "derived", "semantic"):
        assert f"edge-{edge_type}" in page, f"the {edge_type} edge class renders"
        assert f"graph-legend-{edge_type}" in page
    assert "3 facts" in page
    assert "1 observation" in page
    assert f"{len(expected.edges)} edges" in page
    # Older nodes shade down: the 2026-03-01 fact's circle carries the
    # lowest fill-opacity in the document.
    assert 'id="graph-node-fact-3"' in page


def test_every_node_and_edge_is_escaped(booted, auth):
    booted.server.memory.add(
        '<script>alert(1)</script> & "quotes"', source="page"
    )
    status, _h, body = booted.request("GET", "/memory/graph", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


# -- the query parameters -----------------------------------------------------


def test_the_window_accepts_since_and_until(booted, auth):
    _seed(booted.server.memory)
    status, _h, body = booted.request(
        "GET", "/memory/graph?since=2026-01-10&until=2026-01-20", auth
    )
    assert status == 200
    page = body.decode("utf-8")
    assert 'id="graph-window"' in page
    assert _nodes(page) == 2  # the January pair, not the March note


def test_an_unparsable_window_is_ignored_and_the_page_renders(booted, auth):
    _seed(booted.server.memory)
    status, _h, body = booted.request(
        "GET", "/memory/graph?since=not-a-date", auth
    )
    assert status == 200
    assert _nodes(body.decode("utf-8")) == 4


def test_the_limit_clamps_into_one_to_one_thousand(booted, auth):
    store = booted.server.memory
    for index in range(5):
        store.add(f"fact number {index}", source="page",
                  occurrence_ts=_ts(2026, 1, 10 + index))
    base = booted.request("GET", "/memory/graph", auth)
    assert base[0] == 200 and _nodes(base[2].decode("utf-8")) == 5

    status, _h, body = booted.request("GET", "/memory/graph?limit=2", auth)
    assert status == 200 and _nodes(body.decode("utf-8")) == 2

    status, _h, body = booted.request("GET", "/memory/graph?limit=0", auth)
    assert status == 200 and _nodes(body.decode("utf-8")) == 1

    status, _h, body = booted.request("GET", "/memory/graph?limit=99999", auth)
    assert status == 200 and _nodes(body.decode("utf-8")) == 5

    status, _h, body = booted.request("GET", "/memory/graph?limit=junk", auth)
    assert status == 200 and _nodes(body.decode("utf-8")) == 5


# -- the memory page's link ---------------------------------------------------


def test_the_memory_page_carries_the_graph_link(booted, auth):
    status, _h, body = booted.request("GET", "/memory", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert 'href="/memory/graph"' in page


# -- a locked store -----------------------------------------------------------


def test_a_locked_store_renders_the_memory_banner_instead(booted, auth):
    import sqlite3

    from agentdesk.memory.crypto import make_marker
    from agentdesk.memory.store import MemoryStore, ensure_schema

    key = bytes(range(32))
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('encryption', ?)",
        (make_marker(key),),
    )
    conn.commit()
    locked = MemoryStore(conn, time.time)
    assert locked.locked_cause is not None
    harness = server_harness.Booted(memory_store=locked)
    try:
        session = harness.exchange()
        status, _h, body = harness.request("GET", "/memory/graph", session)
        assert status == 200
        assert "Memory is locked." in body.decode("utf-8")
    finally:
        harness.close()
