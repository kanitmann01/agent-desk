"""Memory store tests: CRUD in SQLite and persistence across a reopen.

The teammate's store keeps facts in a process list and loses everything
on restart; the whole point of this store is that a close and reopen
keeps every fact. The persistence test uses a real temp-file database,
closed properly, the way the app runs it.
"""

import contextlib
import json
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.memory.core import UnknownFact
from agentdesk.memory.hybrid import TIME_PRIOR
from agentdesk.memory.store import MemoryStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(clock=None) -> MemoryStore:
    return MemoryStore(
        sqlite3.connect(":memory:", check_same_thread=False),
        clock or FakeClock(),
    )


def _file_store(path: Path) -> MemoryStore:
    return MemoryStore(sqlite3.connect(str(path), check_same_thread=False), FakeClock())


def test_add_creates_a_fact_with_source_and_clock_timestamp():
    clock = FakeClock()
    clock.advance(42.5)
    store = _store(clock)
    fact = store.add("revenue is 220", source="page")
    assert fact.text == "revenue is 220"
    assert fact.source == "page"
    assert fact.created_ts == 142.5


def test_all_lists_facts_in_creation_order():
    store = _store()
    store.add("first fact", source="page")
    store.add("second fact", source="page")
    assert [f.id for f in store.all()] == [1, 2]
    assert [f.text for f in store.all()] == ["first fact", "second fact"]


def test_get_returns_one_fact_and_unknown_raises():
    store = _store()
    fact = store.add("revenue is 220", source="page")
    assert store.get(fact.id).text == "revenue is 220"
    with pytest.raises(UnknownFact):
        store.get(999)


def test_edit_replaces_the_text_and_keeps_the_rest():
    store = _store()
    fact = store.add("revenue is 220", source="page")
    # Ticket #92: edit answers an EditResult; a unique-text edit carries
    # the edited fact itself and merged_into False.
    result = store.edit(fact.id, "revenue is 480")
    assert result.merged_into is False
    assert result.fact.text == "revenue is 480"
    assert result.fact.source == "page"
    assert result.fact.created_ts == fact.created_ts
    with pytest.raises(UnknownFact):
        store.edit(999, "nothing")


def test_delete_removes_exactly_one_fact():
    store = _store()
    first = store.add("first fact", source="page")
    second = store.add("second fact", source="page")
    store.delete(first.id)
    assert [f.id for f in store.all()] == [second.id]
    with pytest.raises(UnknownFact):
        store.delete(999)


def test_recall_ranks_through_the_hybrid_ranker():
    # Ticket #90 deliberately changes the score's meaning: the store's
    # recall is the hybrid ranker, so the score is the fused RRF
    # contribution (keyword rank 0 here: 1/61), not an overlap fraction.
    store = _store()
    store.add("the meeting room is booked", source="page")
    store.add("revenue is 220", source="page")
    ranked = store.recall("revenue")
    assert [f.id for _s, f in ranked] == [2]
    assert ranked[0][0] == pytest.approx(1 / 61)


# -- hybrid recall through the store (ticket #90) --------------------------


def _ts(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


# A fixed now for window tests: Sunday 2026-11-15 at noon UTC, so
# "this week" is [Nov 9, Nov 16) with Monday starts.
NOW = _ts(2026, 11, 15, 12)


def _seed_entity(conn, name, aliases="[]", entity_type="org"):
    cursor = conn.execute(
        "INSERT INTO entities (canonical_name, aliases_json, type, created_ts)"
        " VALUES (?, ?, ?, 100.0)",
        (name, aliases, entity_type),
    )
    return int(cursor.lastrowid)


def _seed_edge(conn, fact_id, entity_id):
    conn.execute("INSERT INTO edges (fact_id, entity_id) VALUES (?, ?)", (fact_id, entity_id))


def test_recall_reaches_a_linked_fact_through_a_paraphrase():
    store = _store()
    fact = store.add("the board approved the budget", source="page")
    entity_id = _seed_entity(store.conn, "Acme")
    _seed_edge(store.conn, fact.id, entity_id)
    # The query shares no token with the fact text; the entity carries it.
    ranked = store.recall("acme")
    assert [f.id for _s, f in ranked] == [fact.id]
    assert ranked[0][0] == pytest.approx(1 / 61)


def test_recall_matches_an_entity_alias():
    store = _store()
    fact = store.add("quarterly review moved to tuesday", source="page")
    entity_id = _seed_entity(store.conn, "Acme", aliases='["Acme Industries"]')
    _seed_edge(store.conn, fact.id, entity_id)
    ranked = store.recall("acme industries")
    assert [f.id for _s, f in ranked] == [fact.id]


def test_recall_one_hop_seeds_the_neighbor_fact():
    store = _store()
    first = store.add("the board approved the budget", source="page")
    second = store.add("the offsite is planned", source="page")
    acme = _seed_entity(store.conn, "Acme")
    globex = _seed_entity(store.conn, "Globex")
    _seed_edge(store.conn, first.id, acme)
    _seed_edge(store.conn, first.id, globex)
    _seed_edge(store.conn, second.id, globex)
    ranked = store.recall("acme")
    # Globex was never named, but it links to the scored fact, so its
    # other fact seeds below the direct one.
    assert [f.id for _s, f in ranked] == [first.id, second.id]
    assert ranked[0][0] == pytest.approx(1 / 61)
    assert ranked[1][0] == pytest.approx(1 / 62)


def test_recall_is_deterministic_across_repeated_calls():
    store = _store()
    first = store.add("revenue lives in the sales workbook", source="page")
    second = store.add("revenue is checked every monday", source="page")
    entity_id = _seed_entity(store.conn, "Acme")
    store.clock.advance(10.0)  # the entity-linked fact is also the newest
    third = store.add("the offsite is planned", source="page")
    _seed_edge(store.conn, third.id, entity_id)
    first_ranked = store.recall("revenue acme")
    for _ in range(5):
        assert store.recall("revenue acme") == first_ranked
    assert [f.id for _s, f in first_ranked] == [third.id, first.id, second.id]


def test_recall_window_restricts_results_and_orders_newer_first():
    store = _store()
    clock = store.clock
    clock.now = _ts(2026, 11, 8)
    inside_older = store.add("sprint review happened", occurrence_ts=_ts(2026, 11, 10))
    clock.now = _ts(2026, 11, 14)
    inside_newer = store.add("standup notes written", occurrence_ts=_ts(2026, 11, 14))
    clock.now = _ts(2026, 11, 1)
    outside = store.add("revenue archive", occurrence_ts=_ts(2026, 11, 1))
    clock.now = NOW
    ranked = store.recall("this week revenue")
    # The window [Nov 9, Nov 16) drops the keyword-matching fact outside
    # it; the in-window facts recall on the prior alone and recency puts
    # the newer first.
    assert [f.id for _s, f in ranked] == [inside_newer.id, inside_older.id]
    assert ranked[0][0] == pytest.approx(TIME_PRIOR * 0.5 ** (1.5 / 30))
    assert ranked[1][0] == pytest.approx(TIME_PRIOR * 0.5 ** (5.5 / 30))


def test_facts_persist_across_a_close_and_reopen(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        store = MemoryStore(conn, FakeClock())
        kept = store.add("revenue is 220", source="page")
        store.edit(kept.id, "revenue is 480")
        store.add("meeting room is booked", source="inbox card 7")
        store.delete(store.add("soon deleted", source="page").id)
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        reopened = MemoryStore(conn, FakeClock())
        facts = reopened.all()
        assert [f.text for f in facts] == ["revenue is 480", "meeting room is booked"]
        assert facts[0].source == "page"
        assert reopened.recall("revenue")[0][1].id == facts[0].id


# -- schema v2 (ticket #89): migration, dedupe, constraints ---------------


def _schema_version(conn: sqlite3.Connection) -> str | None:
    """The stamped schema version, read the way the store reads it."""
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
    return None if row is None else str(row[0])


def _make_v1_database(path: Path, rows: list[tuple[int, str, str, float]]) -> None:
    """A hand-built v1 database: the old four-column facts schema and no
    schema_meta table, the shape every pre-#89 file has."""
    with contextlib.closing(sqlite3.connect(str(path))) as conn:
        conn.executescript(
            """
            CREATE TABLE facts (
              id INTEGER PRIMARY KEY,
              text TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT '',
              created_ts REAL NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO facts (id, text, source, created_ts) VALUES (?, ?, ?, ?)", rows
        )
        conn.commit()


def test_fresh_database_reports_version_2_and_reopens_idempotently(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        store = MemoryStore(conn, FakeClock())
        kept = store.add("revenue is 220", source="page")
        assert _schema_version(conn) == "2"
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        reopened = MemoryStore(conn, FakeClock())
        assert _schema_version(conn) == "2"
        facts = reopened.all()
        assert [f.id for f in facts] == [kept.id]
        assert facts[0].kind == "world"
        assert facts[0].occurrence_ts is None
        assert facts[0].source_id is None


def test_v1_database_upgrades_in_place_preserving_every_row(tmp_path):
    path = tmp_path / "memory.sqlite3"
    _make_v1_database(
        path,
        [
            (1, "revenue is 220", "page", 100.0),
            (2, "meeting room is booked", "inbox card 7", 150.0),
        ],
    )
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        store = MemoryStore(conn, FakeClock())
        assert _schema_version(conn) == "2"
        first, second = store.all()
        assert (first.id, first.text, first.source, first.created_ts) == (
            1,
            "revenue is 220",
            "page",
            100.0,
        )
        assert (second.id, second.text, second.source, second.created_ts) == (
            2,
            "meeting room is booked",
            "inbox card 7",
            150.0,
        )
        # Existing rows read as world knowledge that never happened at a
        # known time and never came from a retained excerpt.
        assert first.kind == "world"
        assert first.occurrence_ts is None
        assert first.source_id is None


def test_v1_duplicates_collapse_into_the_oldest_row_once(tmp_path):
    path = tmp_path / "memory.sqlite3"
    _make_v1_database(
        path,
        [
            (1, "Revenue is 220!", "page", 100.0),  # punctuation differs: never merges
            (2, "Revenue   is 220", "page", 150.0),  # same text as 3, younger
            (3, "  revenue\tis 220 ", "inbox card 7", 120.0),  # the keeper
            (4, "", "page", 90.0),  # empty normalized text merges nothing
            (5, "   ", "page", 95.0),  # ...not even another empty
        ],
    )
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        store = MemoryStore(conn, FakeClock())
        # 2 merged into the older 3; the near-miss and both blanks survive.
        assert [f.id for f in store.all()] == [4, 5, 1, 3]
        assert store.get(3).text == "  revenue\tis 220 "
        assert store.get(1).text == "Revenue is 220!"
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        reopened = MemoryStore(conn, FakeClock())
        assert [f.id for f in reopened.all()] == [4, 5, 1, 3]  # a reopen dedupes nothing
        # Ticket #92: write-time dedup gates every write now, so a
        # re-added normalized duplicate reuses the oldest matching row
        # instead of inserting a second one.
        again = reopened.add("revenue is 220", source="page")
        assert again.id == 3
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        final = MemoryStore(conn, FakeClock())
        # The re-added duplicate created no row (ticket #92), so the
        # reopen finds the same four facts: no second migration, and no
        # new duplicate for it to merge either.
        assert {f.id for f in final.all()} == {1, 3, 4, 5}
        assert [f.id for f in final.all()] == [4, 5, 1, 3]


def test_new_tables_enforce_their_constraints():
    store = _store()
    store.add("acme shipped the widget", source="page")  # fact id 1
    conn = store.conn
    conn.execute(
        "INSERT INTO entities (canonical_name, type, created_ts) VALUES ('Acme', 'org', 100.0)"
    )
    conn.execute("INSERT INTO edges (fact_id, entity_id) VALUES (1, 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO edges (fact_id, entity_id) VALUES (1, 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO entities (canonical_name, type, created_ts) VALUES ('Ghost', 'robot', 100.0)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO facts (text, source, created_ts, kind) VALUES ('x', '', 100.0, 'rumor')"
        )
    # foreign keys are on, so an edge to a missing fact is refused too
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO edges (fact_id, entity_id) VALUES (999, 1)")


def test_add_rejects_a_bad_kind_and_a_non_numeric_occurrence():
    store = _store()
    with pytest.raises(ValueError):
        store.add("revenue is 220", kind="rumor")
    with pytest.raises(ValueError):
        store.add("revenue is 220", occurrence_ts="friday")
    fact = store.add("launch was friday", kind="experience", occurrence_ts=1700000000.0)
    assert fact.kind == "experience"
    assert fact.occurrence_ts == 1700000000.0
    assert fact.source_id is None
    assert [f.text for f in store.all()] == ["launch was friday"]


# -- retain provenance and the entity graph (ticket #91) --------------------


def _entities(conn):
    rows = conn.execute(
        "SELECT id, canonical_name, aliases_json, type FROM entities ORDER BY id"
    ).fetchall()
    return [
        (r[0], r[1], json.loads(r[2]), r[3]) for r in rows
    ]


def _edges(conn):
    rows = conn.execute(
        "SELECT fact_id, entity_id FROM edges ORDER BY fact_id, entity_id"
    ).fetchall()
    return [tuple(r) for r in rows]


def test_add_source_records_the_excerpt_with_speaker_and_context():
    clock = FakeClock()
    clock.advance(7.0)
    store = _store(clock)
    source_id = store.add_source("we met Tuesday", speaker="Kanit", context="thread")
    row = store.conn.execute(
        "SELECT text, speaker, context, created_ts FROM sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    assert row[0] == "we met Tuesday"
    assert row[1] == "Kanit"
    assert row[2] == "thread"
    assert row[3] == 107.0


def test_add_source_defaults_speaker_and_context_to_empty():
    store = _store()
    source_id = store.add_source("hello")
    row = store.conn.execute(
        "SELECT speaker, context FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    assert row == ("", "")


def test_resolve_and_link_creates_entities_and_edges_for_a_new_fact():
    store = _store()
    fact = store.add("Maya joined Acme", source="page")
    refs = store.resolve_and_link(
        fact.id, [("Maya Rahman", "person"), ("Acme", "org")]
    )
    assert [(r.name, r.type) for r in refs] == [
        ("Maya Rahman", "person"),
        ("Acme", "org"),
    ]
    # Entities are created in mention order, ids ascending.
    assert _entities(store.conn) == [
        (1, "Maya Rahman", [], "person"),
        (2, "Acme", [], "org"),
    ]
    assert _edges(store.conn) == [(fact.id, 1), (fact.id, 2)]


def test_resolve_and_link_tolerates_a_duplicate_edge():
    store = _store()
    fact = store.add("Maya joined Acme", source="page")
    store.resolve_and_link(fact.id, [("Maya Rahman", "person")])
    store.resolve_and_link(fact.id, [("Maya Rahman", "person")])
    assert _edges(store.conn) == [(fact.id, 1)]
    assert len(_entities(store.conn)) == 1


def test_resolve_and_link_merges_a_typo_into_one_entity():
    store = _store()
    first = store.add("Obermeier Lin owns the ledger", source="page")
    second = store.add("Obermeir Lin owns the ledger", source="page")
    store.resolve_and_link(first.id, [("Obermeier Lin", "person")])
    refs = store.resolve_and_link(second.id, [("Obermeir Lin", "person")])
    assert [r.id for r in refs] == [1]
    entities = _entities(store.conn)
    assert entities == [(1, "Obermeier Lin", [], "person")]
    assert _edges(store.conn) == [(first.id, 1), (second.id, 1)]


def test_resolve_and_link_promotes_a_longer_weak_match_to_canonical():
    store = _store()
    first = store.add("Maya sent the note", source="page")
    second = store.add("Maya Rahman sent the note", source="page")
    store.resolve_and_link(first.id, [("Maya", "person")])
    refs = store.resolve_and_link(second.id, [("Maya Rahman", "person")])
    assert [(r.id, r.name) for r in refs] == [(1, "Maya Rahman")]
    assert _entities(store.conn) == [(1, "Maya Rahman", ["Maya"], "person")]


def test_resolve_and_link_shares_entities_across_facts_by_cooccurrence():
    store = _store()
    review = store.add("Priya Nair reviewed the budget with Maya Chen", source="page")
    lunch = store.add("Maya Chen lunched with Priya Nair on Tuesday", source="page")
    met = store.add("Priya Nair met Maya Rahman yesterday", source="page")
    brief = store.add("Priya met Maya today", source="page")
    store.resolve_and_link(review.id, [("Priya Nair", "person"), ("Maya Chen", "person")])
    store.resolve_and_link(lunch.id, [("Maya Chen", "person"), ("Priya Nair", "person")])
    store.resolve_and_link(met.id, [("Priya Nair", "person"), ("Maya Rahman", "person")])
    # "Maya" weak-matches both Mayas; the co-occurrence winner decides:
    # Maya Chen shares two distinct facts with the bound Priya Nair,
    # Maya Rahman only one.
    refs = store.resolve_and_link(brief.id, [("Priya Nair", "person"), ("Maya", "person")])
    assert sorted(r.id for r in refs) == [1, 2]
    assert _entities(store.conn) == [
        (1, "Priya Nair", [], "person"),
        (2, "Maya Chen", ["Maya"], "person"),
        (3, "Maya Rahman", [], "person"),
    ]
    assert (brief.id, 1) in _edges(store.conn)
    assert (brief.id, 2) in _edges(store.conn)
    assert (brief.id, 3) not in _edges(store.conn)


def test_resolve_and_link_rejects_an_unknown_fact_and_a_bad_type():
    store = _store()
    with pytest.raises(UnknownFact):
        store.resolve_and_link(999, [("Maya", "person")])
    fact = store.add("a fact", source="page")
    with pytest.raises(ValueError):
        store.resolve_and_link(fact.id, [("Maya", "robot")])
    assert _entities(store.conn) == []
    assert _edges(store.conn) == []


# -- hygiene (ticket #92): write-time dedup ----------------------------------


def test_add_reuses_the_existing_row_for_a_normalized_duplicate():
    store = _store()
    first = store.add("Revenue is 220", source="page")
    store.clock.advance(5.0)
    again = store.add("  revenue\tis 220 ", source="inbox card 3")
    assert again.id == first.id, "the duplicate reuses the row, it does not insert"
    facts = store.all()
    assert len(facts) == 1
    assert facts[0].text == "Revenue is 220", "the stored (oldest) text wins"
    assert facts[0].source == "page", "the existing provenance stays"
    assert facts[0].created_ts == 100.0, "the existing creation time stays"
    rows = store.conn.execute("SELECT COUNT(*) FROM facts").fetchone()
    assert rows[0] == 1


def test_add_of_a_distinct_text_still_creates_a_row():
    store = _store()
    store.add("revenue is 220", source="page")
    other = store.add("revenue is 220!", source="page")  # punctuation differs
    store.add("REVENU E IS 220", source="page")  # a token differs
    assert len(store.all()) == 3
    assert other.id == 2


def test_dedup_links_new_entity_mentions_onto_the_existing_row():
    store = _store()
    first = store.add("Maya joined Acme", source="page")
    store.resolve_and_link(first.id, [("Maya", "person")])
    again = store.add("maya joined ACME", source="page")
    assert again.id == first.id
    store.resolve_and_link(again.id, [("Acme", "org")])
    assert _entities(store.conn) == [(1, "Maya", [], "person"), (2, "Acme", [], "org")]
    assert _edges(store.conn) == [(first.id, 1), (first.id, 2)]


def test_dedup_backfills_occurrence_only_into_a_null():
    store = _store()
    first = store.add("launch happened", source="page")
    assert first.occurrence_ts is None
    again = store.add("  LAUNCH   happened ", occurrence_ts=1700000000.0)
    assert again.id == first.id
    assert store.get(first.id).occurrence_ts == 1700000000.0, "the null is filled"
    third = store.add("launch happened", occurrence_ts=1800000000.0)
    assert third.id == first.id
    assert store.get(first.id).occurrence_ts == 1700000000.0, "a filled value stays"
    # And an incoming None never blanks an existing occurrence.
    fourth = store.add("launch happened")
    assert fourth.id == first.id
    assert store.get(first.id).occurrence_ts == 1700000000.0


# -- hygiene (ticket #92): the edit merge -------------------------------------


def test_edit_onto_another_facts_text_merges_and_reports():
    store = _store()
    kept = store.add("revenue is 220", source="page")
    store.clock.advance(5.0)
    edited = store.add("meeting room booked", source="page", occurrence_ts=1700000000.0)
    store.resolve_and_link(edited.id, [("Acme", "org")])
    result = store.edit(edited.id, "  REVENUE   IS 220 ")
    assert result.merged_into is True
    assert result.fact.id == kept.id, "the oldest fact survives"
    assert result.fact.text == "revenue is 220"
    facts = store.all()
    assert [f.id for f in facts] == [kept.id], "the edited row is gone"
    # The edited fact's mentions moved onto the survivor.
    assert _edges(store.conn) == [(kept.id, 1)]
    # The survivor's null occurrence is backfilled from the merged row.
    assert facts[0].occurrence_ts == 1700000000.0
    with pytest.raises(UnknownFact):
        store.get(edited.id)


def test_edit_merge_backfills_nothing_when_both_sides_have_a_null_occurrence():
    store = _store()
    kept = store.add("revenue is 220", source="page")
    edited = store.add("meeting room booked", source="page")
    result = store.edit(edited.id, "revenue is 220")
    assert result.merged_into is True
    assert result.fact.occurrence_ts is None


def test_edit_to_a_unique_text_behaves_exactly_as_before():
    store = _store()
    fact = store.add("revenue is 220", source="page")
    result = store.edit(fact.id, "revenue is 480")
    assert result.merged_into is False
    assert result.fact.id == fact.id
    assert result.fact.text == "revenue is 480"
    assert result.fact.source == "page"
    assert result.fact.created_ts == fact.created_ts


def test_edit_to_the_facts_own_text_merges_nothing():
    store = _store()
    first = store.add("revenue is 220", source="page")
    second = store.add("meeting room booked", source="page")
    result = store.edit(first.id, "  REVENUE IS 220 ")
    assert result.merged_into is False, "the fact itself is excluded from the match"
    assert result.fact.id == first.id
    assert [f.id for f in store.all()] == [first.id, second.id]


def test_edit_merge_prunes_observations_cited_only_by_the_edited_fact():
    store = _store()
    kept = store.add("revenue is 220", source="page")
    edited = store.add("meeting room booked", source="page")
    other = store.add("the offsite is planned", source="page")
    store.conn.execute(
        "INSERT INTO observations (scope_key, text, confidence, created_ts, updated_ts)"
        " VALUES ('all', 'Doomed pattern.', 0.9, 100.0, 100.0)"
    )
    store.conn.execute(
        "INSERT INTO observation_sources (observation_id, fact_id) VALUES (1, ?)",
        (edited.id,),
    )
    store.conn.execute(
        "INSERT INTO observations (scope_key, text, confidence, created_ts, updated_ts)"
        " VALUES ('all', 'Surviving pattern.', 0.9, 100.0, 100.0)"
    )
    store.conn.execute(
        "INSERT INTO observation_sources (observation_id, fact_id) VALUES (2, ?)",
        (kept.id,),
    )
    store.conn.execute(
        "INSERT INTO observation_sources (observation_id, fact_id) VALUES (2, ?)",
        (other.id,),
    )
    store.conn.commit()
    store.edit(edited.id, "revenue is 220")
    rows = store.conn.execute(
        "SELECT id, text FROM observations ORDER BY id"
    ).fetchall()
    assert [r[0] for r in rows] == [2], "the citation-less observation is pruned"
    citations = store.conn.execute(
        "SELECT observation_id, fact_id FROM observation_sources"
    ).fetchall()
    assert citations == [(2, kept.id), (2, other.id)]


def test_editing_a_superseding_fact_onto_another_facts_text_releases_the_replaced_one():
    store = _store()
    old = store.add("The Acme renewal is due December 1.")
    new = store.add("The Acme renewal is due December 15.")
    other = store.add("The Zenith deal closed.")
    store.mark_superseded(old.id, new.id)
    result = store.edit(new.id, "The Zenith deal closed.")
    assert result.merged_into is True
    # The merge deleted the superseder, so the replaced fact's pointer is
    # released (not left dangling at a dead id): recall returns the older
    # true value instead of skipping it forever.
    assert store.superseded_map() == {}
    hits = [fact.id for _score, fact in store.recall("acme renewal due")]
    assert hits == [old.id]


def test_the_conversion_dedupe_repoints_superseded_facts_at_the_keeper(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with contextlib.closing(
        sqlite3.connect(str(path), check_same_thread=False)
    ) as conn:
        store = MemoryStore(conn, FakeClock(), key_path=tmp_path / "memory.key")
        old = store.add("The Acme renewal is due December 1.")
        keeper = store.add("The Acme renewal is due December 15.")
        # A foreign duplicate of the newer fact, younger than the keeper:
        # the shape a v2-era writer left behind, which the conversion's
        # dedupe collapses into the oldest row.
        store.conn.execute(
            "INSERT INTO facts (text, source, created_ts, kind) VALUES"
            " ('  the acme renewal is due december 15.  ', 'page', 200.0, 'world')"
        )
        store.conn.commit()
        duplicate = store.conn.execute(
            "SELECT id FROM facts ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        store.mark_superseded(old.id, duplicate)
        store.encrypt_all()
        # The copy is gone; the fact it replaced points at the keeper, the
        # row that now carries the replacing text, never at a dead id.
        assert store.superseded_map() == {old.id: keeper.id}
        hits = [fact.id for _score, fact in store.recall("acme renewal due")]
        assert hits == [keeper.id]


# -- hygiene (ticket #92): entity merge ---------------------------------------


def test_merge_entities_unions_aliases_and_relinks_edges():
    store = _store()
    first = store.add("the acme merger closed", source="page")
    second = store.add("the offsite is planned", source="page")
    third = store.add("the bonus pool grew", source="page")
    survivor = _seed_entity(store.conn, "Acme", aliases='["Acme Corp"]')
    removed = _seed_entity(store.conn, "ACME Industries", aliases='["Bee"]')
    _seed_edge(store.conn, first.id, survivor)
    _seed_edge(store.conn, second.id, survivor)
    _seed_edge(store.conn, second.id, removed)
    _seed_edge(store.conn, third.id, removed)
    merged = store.merge_entities(survivor, removed)
    assert merged.id == survivor
    assert merged.canonical_name == "Acme"
    # Union of both alias lists plus the removed canonical name, deduped
    # by normalized form, first-seen order kept.
    assert merged.aliases == ("Acme Corp", "Bee", "ACME Industries")
    entities = _entities(store.conn)
    assert len(entities) == 1
    assert entities[0] == (survivor, "Acme", ["Acme Corp", "Bee", "ACME Industries"], "org")
    assert _edges(store.conn) == [
        (first.id, survivor),
        (second.id, survivor),
        (third.id, survivor),
    ]


def test_merge_entities_upgrades_the_survivors_other_type():
    store = _store()
    survivor = _seed_entity(store.conn, "Acme", entity_type="other")
    removed = _seed_entity(store.conn, "Acme Industries", entity_type="org")
    merged = store.merge_entities(survivor, removed)
    assert merged.type == "org", "types upgrade from other, like resolution does"


def test_merge_entities_dedupes_an_alias_that_equals_the_survivors_canonical():
    store = _store()
    survivor = _seed_entity(store.conn, "Acme")
    removed = _seed_entity(store.conn, "ACME", aliases='["A K A"]')
    merged = store.merge_entities(survivor, removed)
    assert merged.aliases == ("A K A",), "ACME normalizes onto the canonical and drops"


def test_merge_entities_refuses_merging_an_entity_with_itself():
    store = _store()
    entity_id = _seed_entity(store.conn, "Acme")
    with pytest.raises(ValueError, match="itself"):
        store.merge_entities(entity_id, entity_id)
    assert len(_entities(store.conn)) == 1


def test_merge_entities_refuses_unknown_ids():
    store = _store()
    entity_id = _seed_entity(store.conn, "Acme")
    from agentdesk.memory.core import UnknownEntity

    with pytest.raises(UnknownEntity):
        store.merge_entities(entity_id, 999)
    with pytest.raises(UnknownEntity):
        store.merge_entities(999, entity_id)
    assert len(_entities(store.conn)) == 1
    assert _edges(store.conn) == []


def test_merge_entities_deletes_both_sides_observations():
    from agentdesk.memory.loop import entity_scope

    store = _store()
    acme_a = store.add("Acme signed the renewal.")
    acme_b = store.add("Acme hired Maya.")
    globex_a = store.add("Globex shipped the widget.")
    globex_b = store.add("Globex opened the office.")
    store.resolve_and_link(acme_a.id, [("Acme", "org")])
    store.resolve_and_link(acme_b.id, [("Acme", "org")])
    store.resolve_and_link(globex_a.id, [("Globex", "org")])
    store.resolve_and_link(globex_b.id, [("Globex", "org")])
    store.save_observation(
        entity_scope(1), "2 facts about Acme.", 0.7, (acme_a.id, acme_b.id), now=1.0
    )
    store.save_observation(
        entity_scope(2), "2 facts about Globex.", 0.7, (globex_a.id, globex_b.id),
        now=1.0,
    )
    store.merge_entities(1, 2)
    # The absorbed entity's scope is deleted in the same transaction (no
    # reconcile ever looks at a dead entity's scope again), and the
    # survivor's stale text goes with it, so the rebuild never has to
    # compete with a derived row the bank no longer supports.
    assert store.observation_ids_in_scope(entity_scope(2)) == []
    assert store.observation_ids_in_scope(entity_scope(1)) == []
    assert store.observations() == []


# -- hygiene (ticket #92): the entity list -------------------------------------


def test_entities_lists_canonical_names_aliases_types_and_fact_counts():
    store = _store()
    first = store.add("Maya joined Acme", source="page")
    second = store.add("Acme shipped the widget", source="page")
    third = store.add("the offsite is planned", source="page")
    store.resolve_and_link(first.id, [("Maya Rahman", "person"), ("Acme", "org")])
    store.resolve_and_link(second.id, [("Acme", "org")])
    store.resolve_and_link(third.id, [("Offsite Club", "other")])
    summaries = store.entities()
    assert [(s.canonical_name, s.aliases, s.type, s.fact_count) for s in summaries] == [
        ("Acme", (), "org", 2),
        ("Maya Rahman", (), "person", 1),
        ("Offsite Club", (), "other", 1),
    ]


def test_entities_on_an_empty_bank_is_empty():
    store = _store()
    assert store.entities() == []


# -- hygiene (ticket #92): the junk sweep --------------------------------------


def test_sweep_candidates_classify_with_the_donors_reasons():
    store = _store()
    gap = store.add("I do not have any information about that.", source="retain")
    unknown = store.add("unknown", source="page")
    empty = store.add("", source="page")
    inability = store.add(
        "Sorry, I could not find any details about it due to restrictions.",
        source="retain",
    )
    narration = store.add("I searched Wikipedia for the revenue report.", source="retain")
    priority = store.add(
        "Sorry, I could not find any details about it due to restrictions."
        " I do not have any information about that.",
        source="retain",
    )
    dated = store.add("I tried to open the page yesterday.", source="retain")
    mixed = store.add(
        "I do not have that information. Revenue is 220.", source="retain"
    )
    real = store.add("revenue is 220", source="page")
    candidates = {c.fact.id: c.reason for c in store.sweep_candidates()}
    assert candidates[gap.id] == "knowledge-gap"
    assert candidates[unknown.id] == "unknown"
    assert candidates[empty.id] == "empty"
    assert candidates[inability.id] == "inability"
    assert candidates[narration.id] == "session-narration"
    # Priority: inability over knowledge-gap over session-narration.
    assert candidates[priority.id] == "inability"
    # A dated event escapes the session-narration rule.
    assert dated.id not in candidates
    # A disclaimer mixed with a real sentence stays (sentence-level rule).
    assert mixed.id not in candidates
    assert real.id not in candidates


def test_sweep_candidates_come_in_creation_order():
    store = _store()
    first = store.add("unknown", source="page")
    store.clock.advance(5.0)
    second = store.add("tbd", source="page")
    candidates = [c.fact.id for c in store.sweep_candidates()]
    assert candidates == [first.id, second.id]
    assert [c.reason for c in store.sweep_candidates()] == ["unknown", "unknown"]


# -- hygiene (ticket #92): removeFacts semantics --------------------------------


def test_remove_facts_deletes_edges_and_citations_then_prunes_orphans():
    store = _store()
    doomed = store.add("meeting room booked", source="page")
    linked_elsewhere = store.add("the offsite is planned", source="page")
    store.resolve_and_link(doomed.id, [("Acme", "org"), ("Maya", "person")])
    store.resolve_and_link(linked_elsewhere.id, [("Acme", "org")])
    store.conn.execute(
        "INSERT INTO observations (scope_key, text, confidence, created_ts, updated_ts)"
        " VALUES ('all', 'Doomed pattern.', 0.9, 100.0, 100.0)"
    )
    store.conn.execute(
        "INSERT INTO observation_sources (observation_id, fact_id) VALUES (1, ?)",
        (doomed.id,),
    )
    store.conn.execute(
        "INSERT INTO observations (scope_key, text, confidence, created_ts, updated_ts)"
        " VALUES ('all', 'Surviving pattern.', 0.9, 100.0, 100.0)"
    )
    store.conn.execute(
        "INSERT INTO observation_sources (observation_id, fact_id) VALUES (2, ?)",
        (linked_elsewhere.id,),
    )
    store.conn.commit()
    removed = store.remove_facts([doomed.id])
    assert removed.fact_ids == (doomed.id,)
    assert removed.observation_ids == (1,), "the citation-less observation went too"
    assert sorted(removed.entity_ids) == [2], "Acme keeps an edge, Maya lost its last"
    assert [f.id for f in store.all()] == [linked_elsewhere.id]
    assert _edges(store.conn) == [(linked_elsewhere.id, 1)]
    assert _entities(store.conn) == [(1, "Acme", [], "org")]
    rows = store.conn.execute("SELECT id FROM observations").fetchall()
    assert [r[0] for r in rows] == [2]
    citations = store.conn.execute(
        "SELECT observation_id, fact_id FROM observation_sources"
    ).fetchall()
    assert citations == [(2, linked_elsewhere.id)]


def test_remove_facts_is_all_or_nothing_when_an_id_is_missing():
    store = _store()
    first = store.add("revenue is 220", source="page")
    second = store.add("meeting room booked", source="page")
    store.resolve_and_link(first.id, [("Acme", "org")])
    with pytest.raises(UnknownFact):
        store.remove_facts([first.id, 999])
    assert [f.id for f in store.all()] == [first.id, second.id]
    assert _edges(store.conn) == [(first.id, 1)], "nothing was deleted"


def test_remove_facts_collapses_duplicate_ids():
    store = _store()
    fact = store.add("revenue is 220", source="page")
    removed = store.remove_facts([fact.id, fact.id])
    assert removed.fact_ids == (fact.id,)
    assert store.all() == []


def test_remove_facts_refuses_an_empty_id_list():
    store = _store()
    with pytest.raises(ValueError):
        store.remove_facts([])


# -- removal undo: the restore refuses a reused id (spec 017, 4a) --------------


def test_restore_refuses_when_a_removed_entitys_id_was_reused():
    store = _store()
    keep = store.add("Acme signed the renewal.", source="page")
    gone = store.add("Beta review is due December 2.", source="page")
    later = store.add("Zenith closed the deal.", source="page")
    store.resolve_and_link(keep.id, [("Acme", "org")])
    store.resolve_and_link(gone.id, [("Beta Ltd", "org")])
    result = store.remove_with_effects([gone.id])
    assert result["entity_ids"], "Beta went edge-less and was deleted"
    # A new fact's entity takes the freed id (SQLite reuses the max rowid),
    # exactly the audit's repro: the new fact's own id does not collide.
    fresh = store.add("Delta signed the deal.", source="page")
    store.resolve_and_link(fresh.id, [("Delta Corp", "org")])
    assert fresh.id == later.id + 1
    entities = {entity.id for entity in store.entities()}
    assert result["entity_ids"][0] in entities, "the removed entity's id was taken"
    with pytest.raises(ValueError, match="no longer be undone"):
        store.restore_dump(result["dump"])


def test_restore_refuses_when_a_removed_sources_id_was_reused():
    store = _store()
    excerpt = store.add_source("You: The Berlin office has 40 people.")
    fact = store.add("The Berlin office has 40 people.", source="page",
                     source_id=excerpt)
    result = store.remove_with_effects([fact.id])
    assert result["source_ids"] == [excerpt], "the excerpt lost its last fact"
    assert store.add_source("You: A new conversation.") == excerpt
    with pytest.raises(ValueError, match="no longer be undone"):
        store.restore_dump(result["dump"])


def test_restore_refuses_when_a_removed_observations_id_was_reused():
    store = _store()
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    standing = store.add("The Berlin office has 40 people.")
    saved = store.save_observation(
        "scope-a", "Acme churns", 0.9, (left.id, right.id), now=100.0
    )
    result = store.remove_with_effects([left.id, right.id])
    assert result["observation_ids"] == [saved.observation.id]
    # The re-derived row takes the freed id; the undo must not delete it
    # to make room for the old one.
    fresh = store.save_observation(
        "scope-b", "Berlin keeps growing", 0.9, (standing.id,), now=200.0
    )
    assert fresh.observation.id == saved.observation.id
    with pytest.raises(ValueError, match="no longer be undone"):
        store.restore_dump(result["dump"])


# -- observations (ticket #93): the reflect write path ------------------------


def test_save_observation_inserts_with_its_citations():
    store = _store()
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    saved = store.save_observation(
        "scope-a", "Maya moved on from Acme", 0.9, (left.id, right.id), now=500.0
    )
    observation = saved.observation
    assert observation.id >= 1
    assert observation.text == "Maya moved on from Acme"
    assert observation.confidence == 0.9
    assert observation.fact_ids == (left.id, right.id)
    assert observation.created_ts == 500.0
    assert observation.updated_ts == 500.0
    assert saved.removed_ids == ()
    assert store.observations() == [observation]


def test_save_observation_upserts_by_normalized_text_within_the_scope():
    store = _store()
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    other = store.add("The office moved")
    first = store.save_observation(
        "scope-a", "Maya moved on from Acme", 0.9, (left.id, right.id), now=500.0
    )
    second = store.save_observation(
        "scope-a",
        "  maya   moved on from Acme ",
        0.95,
        (left.id, other.id),
        now=600.0,
    )
    assert second.observation.id == first.observation.id
    # The stored text is the trimmed original, never the normalized form.
    assert second.observation.text == "maya   moved on from Acme"
    assert second.observation.confidence == 0.95
    assert second.observation.created_ts == 500.0, "creation time stands"
    assert second.observation.updated_ts == 600.0
    assert second.observation.fact_ids == (left.id, other.id)
    assert second.removed_ids == ()
    rows = store.conn.execute(
        "SELECT fact_id FROM observation_sources WHERE observation_id = ?"
        " ORDER BY fact_id",
        (first.observation.id,),
    ).fetchall()
    assert [row[0] for row in rows] == sorted((left.id, other.id))


def test_the_same_text_in_another_scope_is_a_separate_observation():
    store = _store()
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    store.save_observation("scope-a", "Maya left", 0.9, (left.id,), now=500.0)
    store.save_observation("scope-b", "Maya left", 0.9, (right.id,), now=500.0)
    assert len(store.observations()) == 2


def test_scope_rows_written_before_the_run_go_when_not_kept():
    store = _store()
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    first = store.save_observation("scope", "First pattern", 0.8, (left.id,), now=100.0)
    second = store.save_observation(
        "scope", "Second pattern", 0.8, (right.id,), now=200.0
    )
    third = store.save_observation(
        "scope", "Third pattern", 0.9, (left.id, right.id), now=300.0, run_ts=250.0
    )
    assert third.removed_ids == (first.observation.id, second.observation.id)
    assert [observation.text for observation in store.observations()] == [
        "Third pattern"
    ]


def test_a_re_derived_row_updates_even_when_it_predates_the_run():
    store = _store()
    left = store.add("Maya left Acme")
    first = store.save_observation(
        "scope", "Maya moved on", 0.8, (left.id,), now=100.0
    )
    again = store.save_observation(
        "scope", "  maya moved on ", 0.95, (left.id,), now=300.0, run_ts=250.0
    )
    assert again.observation.id == first.observation.id
    assert again.removed_ids == ()
    assert [observation.text for observation in store.observations()] == [
        "maya moved on"
    ]


def test_rows_written_after_the_run_started_survive_a_sibling_acceptance():
    store = _store()
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    # The sibling was accepted after this run started (its updated_ts
    # is past run_ts), so a later card of the same run must not drop it.
    sibling = store.save_observation(
        "scope", "Sibling pattern", 0.8, (left.id,), now=300.0, run_ts=250.0
    )
    saved = store.save_observation(
        "scope", "This pattern", 0.9, (right.id,), now=400.0, run_ts=250.0
    )
    assert saved.removed_ids == ()
    assert sorted(o.text for o in store.observations()) == [
        "Sibling pattern",
        "This pattern",
    ]
    assert sibling.removed_ids == ()


def test_a_missing_run_reference_never_prunes():
    store = _store()
    left = store.add("Maya left Acme")
    store.save_observation("scope", "First pattern", 0.8, (left.id,), now=100.0)
    saved = store.save_observation(
        "scope", "Second pattern", 0.9, (left.id,), now=200.0
    )
    assert saved.removed_ids == ()
    assert len(store.observations()) == 2


def test_stale_citations_to_deleted_facts_are_dropped():
    store = _store()
    left = store.add("Maya left Acme")
    gone = store.add("Acme ships widgets")
    store.delete(gone.id)
    saved = store.save_observation(
        "scope", "Maya moved on", 0.9, (left.id, gone.id), now=500.0
    )
    assert saved.observation.fact_ids == (left.id,)


def test_an_observation_whose_citations_all_vanished_is_refused():
    store = _store()
    left = store.add("Maya left Acme")
    store.delete(left.id)
    with pytest.raises(ValueError):
        store.save_observation("scope", "Maya moved on", 0.9, (left.id,), now=500.0)
    assert store.observations() == []


def test_invalid_confidence_text_or_citations_are_value_errors():
    store = _store()
    left = store.add("Maya left Acme")
    for confidence in (float("nan"), -0.1, 1.1, True):
        with pytest.raises(ValueError):
            store.save_observation(
                "scope", "An observation", confidence, (left.id,), now=500.0
            )
    with pytest.raises(ValueError):
        store.save_observation("scope", "   ", 0.9, (left.id,), now=500.0)
    with pytest.raises(ValueError):
        store.save_observation("scope", "An observation", 0.9, (), now=500.0)
    assert store.observations() == []


def test_observations_list_newest_updated_first():
    store = _store()
    left = store.add("Maya left Acme")
    first = store.save_observation(
        "scope", "First pattern", 0.5, (left.id,), now=100.0
    )
    second = store.save_observation(
        "scope", "Second pattern", 0.6, (left.id,), now=200.0
    )
    third = store.save_observation(
        "scope", "Third pattern", 0.7, (left.id,), now=300.0
    )
    assert [o.id for o in store.observations()] == [
        third.observation.id, second.observation.id, first.observation.id,
    ]
    refreshed = store.save_observation(
        "scope", "Third pattern, restated", 0.8, (left.id,), now=400.0, run_ts=350.0
    )
    # A distinct normalized text is a new row; the run reference prunes
    # every scope row written before the run, since the run kept only
    # the one it re-derived.
    assert refreshed.observation.id != third.observation.id
    assert refreshed.removed_ids == (
        first.observation.id, second.observation.id, third.observation.id,
    )
    assert [o.id for o in store.observations()] == [refreshed.observation.id]


def test_deleting_a_cited_fact_prunes_the_citation_then_the_observation():
    store = _store()
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    store.save_observation(
        "scope", "Maya moved on from Acme", 0.9, (left.id, right.id), now=500.0
    )
    store.delete(left.id)
    assert [o.fact_ids for o in store.observations()] == [(right.id,)]
    store.delete(right.id)
    assert store.observations() == []


def test_remove_facts_reports_the_observations_it_pruned():
    store = _store()
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    other = store.add("The office moved")
    saved = store.save_observation(
        "scope", "Maya moved on from Acme", 0.9, (left.id, right.id), now=500.0
    )
    survivor = store.save_observation(
        "scope", "The office relocated", 0.8, (other.id,), now=500.0
    )
    removed = store.remove_facts([left.id])
    assert removed.observation_ids == ()
    assert sorted(o.fact_ids for o in store.observations()) == [
        (right.id,), survivor.observation.fact_ids,
    ]
    removed = store.remove_facts([right.id])
    assert removed.observation_ids == (saved.observation.id,)
    assert [o.id for o in store.observations()] == [survivor.observation.id]


def test_concurrent_adds_on_the_shared_connection_lose_nothing():
    # The connection is check_same_thread=False across request threads;
    # the store's write lock (the settings.py rule) serializes the
    # writes so four racing threads of adds all land (review finding 2).
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = MemoryStore(conn, FakeClock())
    errors: list = []

    def add_many(seed):
        try:
            for i in range(10):
                store.add(f"fact {seed}-{i} is recorded", source="threads")
        except Exception as exc:  # noqa: BLE001 - the barrier asserts emptiness
            errors.append(exc)

    threads = [threading.Thread(target=add_many, args=(seed,)) for seed in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(store.all()) == 40
    conn.close()
