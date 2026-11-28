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

from nexuusbot.assistant.research_store import ResearchStore  # noqa: E402


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


def test_concurrent_saves_and_reads_are_serialized(tmp_path):
    """One connection serves request threads: POST /research writes the
    latest answer while dashboard renders read it (#75 review). The
    store serializes both halves around the connection; without the
    lock, interleaved use of one sqlite connection raises
    InterfaceError or tears a read."""
    import threading

    store = ResearchStore(
        sqlite3.connect(tmp_path / "research.sqlite3", check_same_thread=False),
        clock=lambda: 1.0)
    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def writer(n: int) -> None:
        try:
            barrier.wait()
            for i in range(300):
                store.save(f"answer {n}-{i}", ["s"])
        except Exception as exc:  # noqa: BLE001 - the test collects them
            errors.append(exc)

    def reader() -> None:
        try:
            barrier.wait()
            for _ in range(300):
                latest = store.latest()
                if latest is not None and not isinstance(latest["summary"], str):
                    errors.append(ValueError("torn read"))
        except Exception as exc:  # noqa: BLE001 - the test collects them
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    threads += [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert store.latest()["summary"].startswith("answer ")
