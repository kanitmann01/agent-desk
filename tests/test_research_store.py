"""The research answer store: the latest sourced summary, kept locally.

One row, replaced on every save: the store is what the research panel
last concluded, not a history (the audit log is the history, and it
never carries text). This is the data side of issue #64's research
binding; the runner tests in test_plugins_execute.py read through it.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.assistant.research_store import ResearchStore  # noqa: E402


def _store(clock=None):
    if clock is None:
        clock = lambda: 1_763_000_000.0  # noqa: E731
    return ResearchStore(sqlite3.connect(":memory:", check_same_thread=False),
                         clock)


def test_latest_is_none_until_an_answer_is_stored():
    assert _store().latest() is None


def test_save_then_latest_roundtrips_summary_and_sources():
    store = _store()
    store.save("Five of nine EU partners reflected the new prices.",
               ["eu-price-memo.pdf", "channel-weekly.xlsx, tab EU"])
    latest = store.latest()
    assert latest["summary"] == "Five of nine EU partners reflected the new prices."
    assert latest["sources"] == ["eu-price-memo.pdf", "channel-weekly.xlsx, tab EU"]
    assert latest["answeredTs"] == 1_763_000_000.0


def test_a_new_answer_replaces_the_previous_one():
    ticks = [1_763_000_000.0]
    store = _store(clock=lambda: ticks[0])
    store.save("First answer", ["a"])
    ticks[0] += 60
    store.save("Second answer", ["b", "c"])
    latest = store.latest()
    assert latest["summary"] == "Second answer"
    assert latest["sources"] == ["b", "c"]
    assert latest["answeredTs"] == 1_763_000_060.0
