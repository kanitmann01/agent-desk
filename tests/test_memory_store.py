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
