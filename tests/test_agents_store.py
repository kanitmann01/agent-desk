"""The agent runs store in isolation: the record, the newest-first
history, the single-row read, and the JSON columns' roundtrip."""

import sys
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.agents.store import AgentRunStore


class FakeClock:
    """One movable now, so the newest-first order is asserted, not hoped."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store() -> tuple[AgentRunStore, FakeClock]:
    clock = FakeClock()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    return AgentRunStore(conn, clock), clock


def test_record_and_recent_roundtrip_every_column():
    store, clock = _store()
    artifact = {"kind": "slides", "title": "Q3", "slides": [{"title": "Revenue", "bullets": ["220"]}]}
    facts = [{"id": 3, "text": "revenue is 220"}]
    run_id = store.record(
        "worksheet-brief", "the Q3 review", "ok",
        reply='{"title": "Q3"}', artifact=artifact, facts=facts,
    )
    clock.advance(5)
    store.record("worksheet-brief", "a second brief", "degraded", cause="no corporate endpoint configured")
    rows = store.recent()
    assert [row["id"] for row in rows] == [run_id + 1, run_id]
    first = rows[1]
    assert first["agentId"] == "worksheet-brief"
    assert first["brief"] == "the Q3 review"
    assert first["status"] == "ok"
    assert first["cause"] == ""
    assert first["reply"] == '{"title": "Q3"}'
    assert first["artifact"] == artifact
    assert first["facts"] == facts
    assert first["createdTs"] == 100.0
    # The feedback columns exist for the run page's later form; a fresh
    # run carries none.
    assert first["feedback"] == ""
    assert first["feedbackTs"] is None
    second = rows[0]
    assert second["status"] == "degraded"
    assert second["cause"] == "no corporate endpoint configured"
    assert second["artifact"] is None
    assert second["facts"] == []
    assert second["createdTs"] == 105.0


def test_recent_keeps_the_newest_first_under_its_cap():
    store, clock = _store()
    for index in range(25):
        store.record("worksheet-brief", f"brief {index}", "degraded", cause="off")
        clock.advance(1)
    rows = store.recent()
    assert len(rows) == 20
    assert rows[0]["brief"] == "brief 24"
    assert rows[-1]["brief"] == "brief 5"


def test_get_returns_the_one_row_or_none():
    store, _clock = _store()
    run_id = store.record("worksheet-brief", "brief", "ok")
    assert store.get(run_id)["brief"] == "brief"
    assert store.get(run_id + 100) is None


def test_set_feedback_records_the_text_with_its_own_timestamp():
    store, clock = _store()
    run_id = store.record("worksheet-brief", "brief", "ok")
    assert store.set_feedback(run_id, "my manager liked it") is True
    clock.advance(10)
    row = store.get(run_id)
    assert row["feedback"] == "my manager liked it"
    assert row["feedbackTs"] == 100.0  # the moment it landed, not the run's
    # A repost overwrites: the run carries one feedback record, the latest.
    assert store.set_feedback(run_id, "second thoughts") is True
    assert store.get(run_id)["feedback"] == "second thoughts"
    assert store.get(run_id)["feedbackTs"] == 110.0


def test_set_feedback_on_an_unknown_run_writes_nothing():
    store, _clock = _store()
    assert store.set_feedback(4, "nothing") is False
    assert store.recent() == []


def test_the_store_needs_no_default_clock_argument():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AgentRunStore(conn)
    assert store.clock is time.time
