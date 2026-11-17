"""The memory graph payload the Memory page's island draws.

`GET /api/memory/graph` answers with real store rows only: the writer
of each fact (page, sample seed, an accepted inbox card, a plugin), the
retained excerpt it was extracted from, its entities and the
observations that cite it, plus a per-fact provenance trail and the
whole bank's pipeline counts. Authenticated like every route; a locked
bank answers 423 and reads nothing.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.inbox.core import KIND_MEMORY_DRAFT
from agentdesk.memory.crypto import load_key
from agentdesk.memory.store import MemoryStore
from agentdesk.server import demo_data
from agentdesk.server.memory_graph_api import build_memory_graph


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


def _graph(booted, auth, query: str = "") -> dict:
    status, _h, body = booted.request("GET", "/api/memory/graph" + query, auth)
    assert status == 200, body
    return json.loads(body)


def _node(payload: dict, node_id: str) -> dict:
    return next(n for n in payload["nodes"] if n["id"] == node_id)


def _edges(payload: dict, kind: str) -> set[tuple[str, str]]:
    return {(e["source"], e["target"]) for e in payload["edges"] if e["type"] == kind}


def _retained_fact(memory, inbox):
    """The real retain path: an excerpt, a draft card the user accepts,
    and the fact the accept writes with its entity mentions."""
    excerpt = memory.add_source("Dana said Halvorsen wants to renew by Dec 15.",
                                speaker="You", context="assistant")
    card = inbox.add(KIND_MEMORY_DRAFT, "memory", "Halvorsen renews by Dec 15",
                     meta={"memoryFact": {"entities": [["Halvorsen", "org"]]}})
    inbox.accept(card.id)
    fact = memory.add("Halvorsen renews by Dec 15", source=f"inbox card {card.id}",
                      source_id=excerpt)
    memory.resolve_and_link(fact.id, [("Halvorsen", "org")])
    return excerpt, card, fact


def test_the_graph_api_requires_a_session(booted):
    status, _h, _b = booted.request("GET", "/api/memory/graph", booted.host_header())
    assert status == 401


def test_an_empty_bank_answers_no_nodes_and_zero_counts(booted, auth):
    payload = _graph(booted, auth)
    assert payload["status"] == "ok"
    assert payload["nodes"] == [] and payload["edges"] == []
    assert [s["step"] for s in payload["pipeline"]] == [
        "retain", "extract", "approve", "store", "link", "reflect"]
    assert all(s["count"] == 0 for s in payload["pipeline"])


def test_a_typed_fact_hangs_off_the_memory_page_and_says_it_has_no_entities(booted, auth):
    fact = booted.server.memory.add("the office closes at six", source="page")
    payload = _graph(booted, auth)
    node = _node(payload, f"fact:{fact.id}")
    assert node["kind"] == "fact" and node["origin"] == "origin:page"
    assert ("origin:page", f"fact:{fact.id}") in _edges(payload, "wrote")
    steps = [s["step"] for s in node["steps"]]
    assert steps == ["store", "link"]
    assert "No entities linked" in node["steps"][-1]["text"]


def test_a_retained_fact_carries_its_whole_trail(booted, auth):
    memory, inbox = booted.server.memory, booted.server.inbox
    excerpt, card, fact = _retained_fact(memory, inbox)
    payload = _graph(booted, auth)
    node = _node(payload, f"fact:{fact.id}")
    assert node["origin"] == "origin:retain"
    assert [s["step"] for s in node["steps"]] == [
        "retain", "extract", "approve", "store", "link"]
    assert "Halvorsen" in node["steps"][1]["text"]
    assert ("origin:retain", f"fact:{fact.id}") in _edges(payload, "wrote")
    assert (f"source:{excerpt}", f"fact:{fact.id}") in _edges(payload, "extracted")
    entity = next(n for n in payload["nodes"] if n["kind"] == "entity")
    assert entity["label"] == "Halvorsen" and entity["factCount"] == 1
    assert (f"fact:{fact.id}", entity["id"]) in _edges(payload, "mentions")
    counts = {s["step"]: s["count"] for s in payload["pipeline"]}
    assert counts == {"retain": 1, "extract": 1, "approve": 1,
                      "store": 1, "link": 1, "reflect": 0}


def test_a_plugin_card_names_the_plugin_as_the_writer(booted, auth):
    memory, inbox = booted.server.memory, booted.server.inbox
    card = inbox.add("suggestion", "plugin", "AR is overdue", meta={"pluginId": "ar-aging"})
    inbox.accept(card.id)
    fact = memory.add("AR is overdue", source=f"inbox card {card.id}")
    payload = _graph(booted, auth)
    assert _node(payload, f"fact:{fact.id}")["origin"] == "origin:plugin:ar-aging"
    assert _node(payload, "origin:plugin:ar-aging")["label"] == "Plugin ar-aging"


def test_observations_cite_their_facts_and_time_orders_the_facts(booted, auth):
    memory = booted.server.memory
    first = memory.add("alpha shipped", source="page", occurrence_ts=1_700_000_000)
    second = memory.add("beta shipped", source="page", occurrence_ts=1_700_086_400)
    obs = memory.save_observation("scope", "both shipped", 0.9,
                                  [first.id, second.id], time.time()).observation.id
    payload = _graph(booted, auth)
    cites = _edges(payload, "cites")
    assert {(f"observation:{obs}", f"fact:{first.id}"),
            (f"observation:{obs}", f"fact:{second.id}")} <= cites
    assert _edges(payload, "temporal")
    node = _node(payload, f"observation:{obs}")
    assert node["confidence"] == pytest.approx(0.9) and node["sample"] is False
    assert [s["step"] for s in node["steps"]] == ["reflect", "approve"]


def test_the_sample_seed_is_labelled_and_clears_cleanly(booted, auth):
    memory = booted.server.memory
    mine = memory.add("my own note", source="page")
    written = demo_data.seed_memory(memory)
    assert written > 0
    payload = _graph(booted, auth)
    samples = [n for n in payload["nodes"] if n["kind"] == "fact" and n.get("sample")]
    assert len(samples) == written
    assert all(n["origin"] == "origin:sample" for n in samples)
    assert any(n["kind"] == "source" for n in payload["nodes"])
    observation = next(n for n in payload["nodes"] if n["kind"] == "observation")
    assert observation["sample"] is True
    assert [s["step"] for s in observation["steps"]] == ["reflect"]
    demo_data.clear_memory(memory)
    payload = _graph(booted, auth)
    assert [n["id"] for n in payload["nodes"] if n["kind"] == "fact"] == [f"fact:{mine.id}"]
    assert not [n for n in payload["nodes"] if n["kind"] == "source"]


def test_the_limit_query_bounds_the_window(booted, auth):
    memory = booted.server.memory
    for i in range(5):
        memory.add(f"note {i}", source="page")
    payload = _graph(booted, auth, "?limit=2")
    assert payload["window"]["limit"] == 2
    assert len([n for n in payload["nodes"] if n["kind"] == "fact"]) <= 2
    assert payload["truncated"] is True


def test_a_locked_bank_answers_423_with_its_cause(tmp_path):
    db = tmp_path / "memory.sqlite3"
    first = sqlite3.connect(str(db), check_same_thread=False)
    MemoryStore(first, time.time, key=load_key(bytes(range(32)))).add("sealed", source="page")
    first.close()
    conn = sqlite3.connect(str(db), check_same_thread=False)
    store = MemoryStore(conn, time.time, key_path=tmp_path / "memory.key")
    booted = server_harness.Booted(memory_store=store)
    try:
        status, _h, body = booted.request("GET", "/api/memory/graph", booted.exchange())
        assert status == 423
        assert json.loads(body)["status"] == "locked"
    finally:
        booted.close()
        conn.close()


def test_the_builder_reads_without_an_inbox(tmp_path):
    memory = MemoryStore(sqlite3.connect(":memory:"), time.time)
    fact = memory.add("orphaned approval", source="inbox card gone")
    payload = build_memory_graph(memory, None)
    node = _node(payload, f"fact:{fact.id}")
    assert node["origin"] == "origin:inbox"
    assert node["steps"][0]["step"] == "approve"


def test_the_memory_page_mounts_the_island_when_it_is_built(booted, auth, monkeypatch):
    from agentdesk.server import app as app_module
    monkeypatch.setattr(app_module, "memory_graph_island_built", lambda: True)
    monkeypatch.setattr(app_module, "memory_loop_island_built", lambda: False)
    status, _h, body = booted.request("GET", "/memory", auth)
    page = body.decode()
    assert status == 200
    assert 'id="memory-graph-root"' in page
    assert 'data-endpoint="/api/memory/graph"' in page
    assert "/static/spa/assets/memory-graph.js" in page
    assert 'href="/memory/graph"' in page  # the no-script way in
