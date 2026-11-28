"""The store's graph snapshot read (ticket #96): one method over the
real database that feeds the pure builder everything it needs.

The seeded bank exercises all four edge types at once: two facts share
an entity (entity edge), sit a day apart (temporal edge), carry
same-model same-dimension vectors with a high cosine (semantic edge),
and an observation cites them both (derived edges). Sealed parity pins
the encryption seam: the same seeding over an encrypted bank decrypts
through the existing helpers and produces a byte-equal snapshot, since
every number in it comes from the same stored bytes.
"""

import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.memory.crypto import MemoryEncryptedError, make_marker
from nexuusbot.memory.embed import EmbedderUnavailable, cosine
from nexuusbot.memory.store import MemoryStore, ensure_schema


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeEmbedder:
    """The scripted embedder: a text-to-vector map, a failure set."""

    def __init__(self, vectors=None, model="fake-embed") -> None:
        self.vectors = dict(vectors or {})
        self.model = model

    def embed(self, text: str):
        if text not in self.vectors:
            raise EmbedderUnavailable("the scripted endpoint refused")
        return self.vectors[text]


VECTOR_A = [1.0, 0.0]
VECTOR_B = [0.98, 0.19899748742132497]  # cosine with VECTOR_A is about 0.98
VECTOR_C = [-1.0, 0.0]

TEXT_A = "alice runs the platform team"
TEXT_B = "the platform team shipped the release"
TEXT_C = "an unrelated note about printers"

NOW = 2_000_000.0
KEY = bytes(range(32))


def _store(key=None) -> MemoryStore:
    embedder = FakeEmbedder(
        vectors={TEXT_A: VECTOR_A, TEXT_B: VECTOR_B, TEXT_C: VECTOR_C}
    )
    kwargs = {"key": key} if key is not None else {}
    return MemoryStore(
        sqlite3.connect(":memory:", check_same_thread=False),
        FakeClock(),
        embedder=embedder,
        embeddings_active=True,
        **kwargs,
    )


def _seed(store: MemoryStore) -> int:
    """The shared seeding: two platform-team facts one day apart, one
    unrelated fact, an entity joining the pair, and an observation
    citing the pair. Returns the observation id."""
    store.clock.advance(0.0)
    first = store.add(TEXT_A, source="page")
    store.clock.advance(1 * 86_400.0)
    second = store.add(TEXT_B, source="page")
    store.clock.advance(30 * 86_400.0)
    store.add(TEXT_C, source="page")
    store.resolve_and_link(first.id, [("Platform Team", "org")])
    store.resolve_and_link(second.id, [("Platform Team", "org")])
    saved = store.save_observation(
        "scope", "the platform team is shipping steadily", 0.9,
        [first.id, second.id], store.clock(),
    )
    return saved.observation.id


def _types(snapshot) -> set:
    return {edge.type for edge in snapshot.edges}


def test_a_snapshot_over_a_seeded_bank_has_every_edge_type():
    store = _store()
    observation_id = _seed(store)
    snapshot = store.graph_snapshot(now=NOW)
    node_ids = {node.id for node in snapshot.nodes}
    assert f"observation:{observation_id}" in node_ids
    assert len(node_ids) == 4  # three facts, one observation
    assert "fact:1" in node_ids and "fact:3" in node_ids
    assert _types(snapshot) == {"semantic", "temporal", "entity", "derived"}

    by_type: dict[str, set] = {}
    for edge in snapshot.edges:
        by_type.setdefault(edge.type, set()).add(
            (edge.source, edge.target)
        )
    semantic = by_type["semantic"]
    assert semantic == {("fact:1", "fact:2")}, (
        f"only the close vectors pair: {semantic}"
    )
    entity = by_type["entity"]
    assert ("fact:1", "fact:2") in entity
    derived = by_type["derived"]
    assert (f"observation:{observation_id}", "fact:1") in derived
    assert (f"observation:{observation_id}", "fact:2") in derived


def test_the_semantic_edge_weight_is_the_cosine_of_the_stored_vectors():
    store = _store()
    _seed(store)
    snapshot = store.graph_snapshot(now=NOW)
    semantic = [edge for edge in snapshot.edges if edge.type == "semantic"]
    assert len(semantic) == 1
    assert semantic[0].weight == pytest.approx(cosine(VECTOR_A, VECTOR_B))


def test_the_printer_note_never_joins_the_semantic_pair():
    store = _store()
    _seed(store)
    snapshot = store.graph_snapshot(now=NOW)
    for edge in snapshot.edges:
        if edge.type != "semantic":
            continue
        assert 3 not in (edge.source, edge.target)


def test_the_window_and_limit_apply_to_the_stored_bank():
    store = _store()
    _seed(store)
    day = 86_400.0
    first_created = 1_000_000.0
    # The window keeps only the first fact (the second's created time
    # sits exactly on the exclusive until bound); the limit then keeps
    # a single node and no edge can form.
    narrow = store.graph_snapshot(
        now=NOW, since=first_created, until=first_created + day, limit=1
    )
    assert len(narrow.nodes) == 1
    assert narrow.nodes[0].id == "fact:1"
    assert narrow.edges == ()


def test_a_snapshot_over_a_sealed_bank_is_identical_to_the_plaintext_one():
    plain = _store()
    sealed = _store(key=KEY)
    assert sealed.is_sealed
    row = sealed.conn.execute("SELECT text FROM facts").fetchone()
    assert row is None or row[0] == "", "no fact has been written yet"
    _seed(plain)
    _seed(sealed)
    first_text = sealed.conn.execute(
        "SELECT text FROM facts WHERE id = 1"
    ).fetchone()[0]
    assert first_text == "", "sealed rows blank the plaintext column"

    plain_snapshot = plain.graph_snapshot(now=NOW)
    sealed_snapshot = sealed.graph_snapshot(now=NOW)
    assert sealed_snapshot == plain_snapshot
    labels = {node.label for node in sealed_snapshot.nodes}
    assert TEXT_A in labels, "the sealed bank decrypted its labels for the view"


def test_a_locked_store_refuses_the_snapshot_read():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('encryption', ?)",
        (make_marker(KEY),),
    )
    conn.commit()
    locked = MemoryStore(conn, time.time)
    assert locked.locked_cause is not None
    with pytest.raises(MemoryEncryptedError):
        locked.graph_snapshot(now=NOW)


def test_a_bank_without_embeddings_still_renders_the_other_edges():
    embedder = FakeEmbedder(vectors={})
    store = MemoryStore(
        sqlite3.connect(":memory:", check_same_thread=False),
        FakeClock(),
        embedder=embedder,
        embeddings_active=True,
    )
    observation_id = _seed(store)
    snapshot = store.graph_snapshot(now=NOW)
    assert "semantic" not in _types(snapshot)
    assert _types(snapshot) == {"temporal", "entity", "derived"}
    assert any(
        edge.type == "derived" and edge.source == f"observation:{observation_id}"
        for edge in snapshot.edges
    )
