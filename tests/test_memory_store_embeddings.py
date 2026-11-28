"""The store's semantic half (ticket #95): write-time vectors, the
recall vector leg, and the backfill action.

The donor contracts pinned here: an embedding failure at write stores
the fact WITHOUT a vector and recall keeps working through the
deterministic legs (vectorFor); the vector leg compares only
same-model same-dimension rows and joins the fusion at unit weight
(vectorScores); backfill walks the NULL rows oldest-first and commits
one UPDATE per row, so a mid-run failure leaves the prior rows
embedded and the action can retry (backfillEmbeddings). With
embeddings inactive, recall is byte-identical to the deterministic
hybrid, scores included. Sealed banks carry the same behavior through
the byte envelopes (ticket #94's box extended with seal_bytes).
"""

import sqlite3
import threading
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.memory.crypto import CryptoBox  # noqa: F401 - the byte envelope seam
from nexuusbot.memory.embed import (
    EmbedderUnavailable,
    decode_embedding,
    encode_embedding,
)
from nexuusbot.memory.hybrid import rank_hybrid
from nexuusbot.memory.store import MemoryStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeEmbedder:
    """The scripted embedder: a text-to-vector map, a failure set, and
    a call log the order tests read."""

    def __init__(self, vectors=None, fail_for=(), model="fake-embed") -> None:
        self.vectors = dict(vectors or {})
        self.fail_for = set(fail_for)
        self.model = model
        self.calls: list[str] = []

    def embed(self, text: str):
        self.calls.append(text)
        if text in self.fail_for:
            raise EmbedderUnavailable("the scripted endpoint refused")
        return self.vectors[text]


def _store(clock=None, embedder=None, active=False, key=None) -> MemoryStore:
    kwargs = {}
    if key is not None:
        kwargs["key"] = key
    return MemoryStore(
        sqlite3.connect(":memory:", check_same_thread=False),
        clock or FakeClock(),
        embedder=embedder,
        embeddings_active=active,
        **kwargs,
    )


def _embedding_row(store: MemoryStore, fact_id: int):
    row = store.conn.execute(
        "SELECT embedding, embedding_model, embedding_dim"
        " FROM facts WHERE id = ?",
        (fact_id,),
    ).fetchone()
    return row


def _fact_vector(store: MemoryStore, fact_id: int):
    """The stored vector as floats (the sealed bank decrypts first),
    or None when the row carries no vector."""
    row = _embedding_row(store, fact_id)
    if row is None or row[0] is None:
        return None
    blob = row[0]
    if store.is_sealed:
        blob = store._box.open_bytes(blob, "facts", "embedding", fact_id)
    return decode_embedding(blob, row[2])


# -- the columns ------------------------------------------------------------


def test_fresh_and_upgraded_facts_tables_carry_the_embedding_columns():
    store = _store()
    columns = {row[1] for row in store.conn.execute("PRAGMA table_info(facts)")}
    assert {"embedding", "embedding_model", "embedding_dim"} <= columns


def test_an_old_v2_file_gains_the_columns_on_open(tmp_path):
    path = Path(tmp_path) / "old.sqlite3"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE facts (
          id INTEGER PRIMARY KEY,
          text TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT '',
          created_ts REAL NOT NULL
        );
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES ('version', '2');
        INSERT INTO facts (text, source, created_ts) VALUES ('old fact', 'page', 1.0);
        """
    )
    conn.commit()
    conn.close()
    store = MemoryStore(sqlite3.connect(str(path), check_same_thread=False), FakeClock())
    try:
        columns = {row[1] for row in store.conn.execute("PRAGMA table_info(facts)")}
        assert {"embedding", "embedding_model", "embedding_dim"} <= columns
        assert [f.text for f in store.all()] == ["old fact"]
        assert store.embedding_counts() == {"embedded": 0, "remaining": 1}
    finally:
        store.conn.close()


# -- write-time embedding ---------------------------------------------------


def test_active_add_embeds_the_fact_and_records_model_and_dim():
    embedder = FakeEmbedder(vectors={"the revenue is 220": [1.0, 0.0, 0.5]})
    store = _store(embedder=embedder, active=True)
    fact = store.add("the revenue is 220", source="page")
    stored = _fact_vector(store, fact.id)
    assert stored == [1.0, 0.0, 0.5]
    row = _embedding_row(store, fact.id)
    assert row[1] == "fake-embed"
    assert row[2] == 3


def test_inactive_add_stores_no_vector_even_with_an_embedder():
    embedder = FakeEmbedder(vectors={"the revenue is 220": [1.0, 0.0]})
    store = _store(embedder=embedder, active=False)
    fact = store.add("the revenue is 220", source="page")
    assert _embedding_row(store, fact.id) == (None, None, None)
    assert embedder.calls == []


def test_an_embed_failure_at_write_stores_the_fact_without_a_vector():
    embedder = FakeEmbedder(fail_for={"the revenue is 220"})
    store = _store(embedder=embedder, active=True)
    fact = store.add("the revenue is 220", source="page")
    assert _embedding_row(store, fact.id) == (None, None, None)
    # Recall still works through the deterministic legs.
    ranked = store.recall("revenue")
    assert [f.id for _score, f in ranked] == [fact.id]


def test_a_duplicate_write_backfills_the_vector_only_into_a_null():
    embedder = FakeEmbedder(
        vectors={"the revenue is 220": [1.0, 0.0], "The Revenue  is 220": [0.0, 1.0]}
    )
    store = _store(embedder=embedder, active=True)
    first = store.add("the revenue is 220", source="page")
    assert _fact_vector(store, first.id) == [1.0, 0.0]
    # The same normalized text embeds to a different vector this time;
    # the stored one must not be overwritten.
    again = store.add("The Revenue  is 220 ", source="page")  # strips to the embedder key
    assert again.id == first.id
    assert _fact_vector(store, again.id) == [1.0, 0.0]


def test_a_duplicate_write_backfills_a_null_vector():
    embedder = FakeEmbedder(fail_for={"the revenue is 220"})
    store = _store(embedder=embedder, active=True)
    first = store.add("the revenue is 220", source="page")
    assert _embedding_row(store, first.id) == (None, None, None)
    embedder.fail_for.clear()
    embedder.vectors["The Revenue  is 220"] = [0.0, 1.0]
    again = store.add("The Revenue  is 220 ", source="page")  # strips to the embedder key
    assert again.id == first.id
    assert _fact_vector(store, again.id) == [0.0, 1.0]


def test_an_active_edit_refreshes_the_vector_with_the_new_text():
    embedder = FakeEmbedder(
        vectors={"old text": [1.0, 0.0], "new text": [0.0, 1.0]}
    )
    store = _store(embedder=embedder, active=True)
    fact = store.add("old text", source="page")
    store.edit(fact.id, "new text")
    assert _fact_vector(store, fact.id) == [0.0, 1.0]


# -- the recall vector leg --------------------------------------------------


def test_inactive_recall_is_byte_identical_to_the_deterministic_hybrid():
    embedder = FakeEmbedder()
    store = _store(embedder=embedder, active=False)
    clock = store.clock
    for text in ("revenue is 220", "standup moved to nine", "alice runs the graph team"):
        store.add(text, source="page")
    deterministic = rank_hybrid(
        "revenue total", store.all(), store._entity_links(), now=clock()
    )
    ranked = store.recall("revenue total")
    assert ranked == deterministic
    # Byte-identical means the scores too, not just the order.
    assert [score for score, _f in ranked] == [score for score, _f in deterministic]
    assert embedder.calls == []


def test_the_vector_leg_changes_a_zero_keyword_overlap_recall_only_when_active():
    # The paraphrase shares no meaningful token with the fact.
    fact_text = "the quarterly revenue total is 220 thousand"
    paraphrase = "how much money did we make"
    vectors = {
        fact_text: [1.0, 0.0],
        paraphrase: [0.95, 0.05],
        "unrelated note about printers": [0.0, 1.0],
    }
    embedder = FakeEmbedder(vectors=vectors)
    active_store = _store(embedder=embedder, active=True)
    fact = active_store.add(fact_text, source="page")
    active_store.add("unrelated note about printers", source="page")
    ranked = active_store.recall(paraphrase)
    assert ranked, "the vector leg alone should surface the fact"
    assert ranked[0][1].id == fact.id
    assert [f.id for _s, f in ranked] == [fact.id, active_store.all()[1].id]

    inert_store = _store(embedder=FakeEmbedder(vectors=vectors), active=False)
    inert_store.add(fact_text, source="page")
    inert_store.add("unrelated note about printers", source="page")
    assert inert_store.recall(paraphrase) == []


def test_a_query_embed_failure_degrades_to_the_deterministic_legs():
    embedder = FakeEmbedder(vectors={"revenue is 220": [1.0, 0.0]}, fail_for={"revenue"})
    store = _store(embedder=embedder, active=True)
    fact = store.add("revenue is 220", source="page")
    ranked = store.recall("revenue")
    assert [f.id for _s, f in ranked] == [fact.id]


def test_rows_with_a_different_model_or_dim_never_compare():
    embedder = FakeEmbedder(vectors={"target fact": [1.0, 0.0, 0.0]})
    store = _store(embedder=embedder, active=True)
    target = store.add("target fact", source="page")

    # A same-shape vector recorded under another model name.
    store.conn.execute(
        "UPDATE facts SET embedding = ?, embedding_model = ?, embedding_dim = ?"
        " WHERE id = ?",
        (encode_embedding([1.0, 0.0, 0.0]), "other-model", 3, target.id),
    )
    ranked = store.recall("target fact")
    # The keyword leg still recalls it; the vector leg is silent, so the
    # fused score equals the deterministic fusion's.
    deterministic = rank_hybrid(
        "target fact", store.all(), store._entity_links(), now=store.clock()
    )
    assert [score for score, _f in ranked] == [score for score, _f in deterministic]

    # Back to the matching model, wrong dim: still no vector leg.
    store.conn.execute(
        "UPDATE facts SET embedding = ?, embedding_model = ?, embedding_dim = ?"
        " WHERE id = ?",
        (encode_embedding([1.0, 0.0]), "fake-embed", 2, target.id),
    )
    ranked = store.recall("target fact")
    assert [score for score, _f in ranked] == [score for score, _f in deterministic]

    # Matching model and dim: the vector leg joins (the query embeds to
    # the same direction, so the fused score rises above the
    # deterministic fusion's).
    store.conn.execute(
        "UPDATE facts SET embedding = ?, embedding_model = ?, embedding_dim = ?"
        " WHERE id = ?",
        (encode_embedding([1.0, 0.0, 0.0]), "fake-embed", 3, target.id),
    )
    ranked = store.recall("target fact")
    assert ranked[0][0] > deterministic[0][0]


def test_a_undecodable_vector_row_never_breaks_recall():
    embedder = FakeEmbedder(vectors={"target fact": [1.0, 0.0]})
    store = _store(embedder=embedder, active=True)
    store.add("target fact", source="page")
    store.conn.execute(
        "UPDATE facts SET embedding = ? WHERE id = 1",
        (b"\x00\x01\x02",),  # not a valid 2-float blob
    )
    ranked = store.recall("target fact")
    assert [f.text for _s, f in ranked] == ["target fact"]


# -- the backfill action -----------------------------------------------------


def test_backfill_embeds_null_rows_oldest_first_and_reports_counts():
    embedder = FakeEmbedder(
        vectors={
            "first fact": [1.0, 0.0],
            "second fact": [0.0, 1.0],
            "third fact": [1.0, 1.0],
        }
    )
    # The facts predate the probe: written inert, backfilled active,
    # exactly the flow the memory page's backfill button serves.
    store = _store(embedder=embedder, active=False)
    store.add("first fact", source="page")
    store.add("second fact", source="page")
    store.add("third fact", source="page")
    store.embeddings_active = True
    # Push the second row older than the first: the order is
    # created_ts ASC, id ASC, not insertion order.
    store.conn.execute("UPDATE facts SET created_ts = 5.0 WHERE id = 2")
    store.conn.commit()

    result = store.backfill_embeddings()

    assert result["embedded"] == 3
    assert result["remaining"] == 0
    assert result["cause"] is None
    assert embedder.calls == ["second fact", "first fact", "third fact"]
    assert store.embedding_counts() == {"embedded": 3, "remaining": 0}


def test_a_mid_run_failure_leaves_prior_rows_committed_and_reports_the_cause():
    embedder = FakeEmbedder(
        vectors={"first fact": [1.0, 0.0], "second fact": [0.0, 1.0]},
        fail_for={"third fact"},
    )
    store = _store(embedder=embedder, active=False)
    store.add("first fact", source="page")
    store.add("second fact", source="page")
    store.add("third fact", source="page")
    store.embeddings_active = True

    result = store.backfill_embeddings()

    assert result["embedded"] == 2
    assert result["remaining"] == 1
    assert result["cause"]
    assert _fact_vector(store, 1) == [1.0, 0.0]
    assert _fact_vector(store, 2) == [0.0, 1.0]
    assert _embedding_row(store, 3) == (None, None, None)

    # Retryable: the embedder heals, the same action finishes the job.
    embedder.fail_for.clear()
    embedder.vectors["third fact"] = [1.0, 1.0]
    retried = store.backfill_embeddings()
    assert retried == {"embedded": 1, "remaining": 0, "cause": None}
    assert store.embedding_counts() == {"embedded": 3, "remaining": 0}


def test_backfill_without_an_active_client_is_refused():
    inert = _store()
    with pytest.raises(ValueError):
        inert.backfill_embeddings()
    dormant = _store(embedder=FakeEmbedder(), active=False)
    with pytest.raises(ValueError):
        dormant.backfill_embeddings()


# -- sealed parity ------------------------------------------------------------


def _sealed_store(embedder=None, active=False) -> MemoryStore:
    key = bytes(range(32))
    return _store(embedder=embedder, active=active, key=key)


def test_sealed_write_stores_the_vector_as_ciphertext():
    embedder = FakeEmbedder(vectors={"the revenue is 220": [1.0, 0.0, 2.0]})
    store = _sealed_store(embedder=embedder, active=True)
    fact = store.add("the revenue is 220", source="page")
    raw = _embedding_row(store, fact.id)[0]
    assert raw != encode_embedding([1.0, 0.0, 2.0])
    assert raw[0] == 1, "the byte envelope's version byte"
    assert _fact_vector(store, fact.id) == [1.0, 0.0, 2.0]


def test_sealed_recall_rides_the_vector_leg_and_decrypts_in_memory():
    vectors = {
        "the quarterly revenue total is 220 thousand": [1.0, 0.0],
        "how much money did we make": [0.95, 0.05],
    }
    embedder = FakeEmbedder(vectors=vectors)
    store = _sealed_store(embedder=embedder, active=True)
    fact = store.add("the quarterly revenue total is 220 thousand", source="page")
    ranked = store.recall("how much money did we make")
    assert [f.id for _s, f in ranked] == [fact.id]


def test_sealed_backfill_and_reopen_recall(tmp_path):
    key = bytes(range(32))
    path = Path(tmp_path) / "sealed.sqlite3"
    embedder = FakeEmbedder(vectors={"seed fact": [1.0, 0.0], "later fact": [0.0, 1.0]})
    store = MemoryStore(
        sqlite3.connect(str(path), check_same_thread=False),
        FakeClock(),
        key=key,
        embedder=embedder,
        embeddings_active=False,
    )
    fact = store.add("seed fact", source="page")
    store.add("later fact", source="page")
    store.embeddings_active = True
    result = store.backfill_embeddings()
    assert result["embedded"] == 2 and result["remaining"] == 0
    expected = store.recall("seed fact")
    store.conn.close()

    reopened = MemoryStore(
        sqlite3.connect(str(path), check_same_thread=False),
        FakeClock(),
        key=key,
        embedder=embedder,
        embeddings_active=True,
    )
    try:
        assert reopened.embedding_counts() == {"embedded": 2, "remaining": 0}
        assert reopened.recall("seed fact") == expected
        assert reopened.get(fact.id).text == "seed fact"
    finally:
        reopened.conn.close()


def test_the_encryption_conversion_seals_existing_vectors_and_counts_them(tmp_path):
    embedder = FakeEmbedder(vectors={"plain fact": [1.0, 0.0, 3.0]})
    plain = _store(embedder=embedder, active=True)
    fact = plain.add("plain fact", source="page")
    counts = plain.plain_field_counts()
    assert counts["facts"] == 2, "the fact text and its embedding vector"

    plain.key_path = Path(tmp_path) / "memory.key"
    plain.encrypt_all()
    raw = _embedding_row(plain, fact.id)[0]
    assert raw[0] == 1, "the sealed vector rides the byte envelope"
    assert _fact_vector(plain, fact.id) == [1.0, 0.0, 3.0]


def test_backfill_spends_its_embed_time_outside_the_write_lock():
    # The review's finding 2: a slow backfill (network waits inside
    # embed) must not block other writers, so the lock is held per row,
    # never across the run. The two vector-less rows are seeded by SQL
    # (a live add would embed at write time), and only the backfill's
    # FIRST embed parks; while it parks, another thread's add() has to
    # complete.
    arrived = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    class ParkingEmbedder:
        model = "test-model"

        def embed(self, text):
            calls.append(text)
            if len(calls) == 1:
                arrived.set()
                release.wait(timeout=10)
            return [1.0, 0.0]

    store = _store(embedder=ParkingEmbedder(), active=True)
    store.conn.executemany(
        "INSERT INTO facts (text, source, created_ts)"
        " VALUES (?, 'page', ?)",
        [("fact 0 awaits its vector", 100.0),
         ("fact 1 awaits its vector", 101.0)],
    )
    store.conn.commit()
    result: dict = {}

    def run_backfill():
        result.update(store.backfill_embeddings())

    thread = threading.Thread(target=run_backfill)
    thread.start()
    assert arrived.wait(timeout=5), "the backfill never reached its embed"
    # The first embed is parked: with the lock held across the run this
    # add would block on the store lock until the park timed out.
    store.add("written while the backfill waits", source="page")
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result["embedded"] == 2
    assert result["remaining"] == 0
    # The concurrent add embedded too (its embed call returned at once).
    assert store.embedding_counts()["embedded"] == 3
