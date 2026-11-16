"""Memory store tests: CRUD in SQLite and persistence across a reopen.

The teammate's store keeps facts in a process list and loses everything
on restart; the whole point of this store is that a close and reopen
keeps every fact. The persistence test uses a real temp-file database,
closed properly, the way the app runs it.
"""

import contextlib
import sqlite3
import sys
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
    edited = store.edit(fact.id, "revenue is 480")
    assert edited.text == "revenue is 480"
    assert edited.source == "page"
    assert edited.created_ts == fact.created_ts
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
    # contribution (keyword rank 0 here: 1/61), not the overlap
    # fraction the old service.rank returned.
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


def _seed_entity(conn, name, aliases="[]"):
    cursor = conn.execute(
        "INSERT INTO entities (canonical_name, aliases_json, type, created_ts)"
        " VALUES (?, ?, 'org', 100.0)",
        (name, aliases),
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
        again = reopened.add("revenue is 220", source="page")  # no write-time dedupe yet
        assert again.id not in {1, 3, 4, 5}
    with contextlib.closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        final = MemoryStore(conn, FakeClock())
        # the re-added duplicate survives the reopen: no second migration
        assert {f.id for f in final.all()} == {1, 3, 4, 5, again.id}


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
