"""Memory store tests: CRUD in SQLite and persistence across a reopen.

The teammate's store keeps facts in a process list and loses everything
on restart; the whole point of this store is that a close and reopen
keeps every fact. The persistence test uses a real temp-file database,
closed properly, the way the app runs it.
"""

import contextlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.memory.core import UnknownFact
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


def test_recall_ranks_through_the_pure_service():
    store = _store()
    store.add("the meeting room is booked", source="page")
    store.add("revenue is 220", source="page")
    ranked = store.recall("revenue")
    assert [f.id for _s, f in ranked] == [2]
    assert ranked[0][0] == 1.0


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
