"""Watcher tests: poll, delta, amber states, staleness, against fakes.

The watcher never touches a real file here: the copier and parser are
fakes, the clock is frozen and advanced by hand, and the snapshot store
is a real in-memory SQLite database, because the store is the delta clock
and faking it would fake the thing under test.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.excel import store
from agentdesk.excel.core import WorkbookLocked, WorkbookUnreadable
from agentdesk.excel.watcher import Adapters, ExcelWatch

BASE = [["Product", "Units"], ["Atlas", 41.0], ["Field", 12.0]]
CHANGED = [["Product", "Units"], ["Atlas", 44.0], ["Field", 12.0], ["Care", 7.0]]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_watch(tmp_path, rows_by_poll: list, clock: FakeClock | None = None) -> ExcelWatch:
    """A watch whose file content changes per poll (as edits would)."""
    clock = clock or FakeClock()
    polls = iter(rows_by_poll)

    def copy_shadow(path):
        return Path(path)

    def parse(path):
        rows = next(polls)
        if isinstance(rows, Exception):
            raise rows
        return rows

    adapters = Adapters(copy_shadow=copy_shadow, parse_workbook=parse, clock=clock)
    conn = sqlite3.connect(":memory:")
    return ExcelWatch(conn, adapters), clock


def test_register_takes_the_first_snapshot_without_inventing_a_delta(tmp_path):
    watch, _clock = make_watch(tmp_path, [BASE])
    result = watch.register("Q4-sales.xlsx")
    assert result.state == "first"
    assert result.delta is None
    assert store.snapshot_count(watch.conn, "excel-watch") == 1


def test_poll_after_24h_diffs_against_the_t24h_snapshot(tmp_path):
    watch, clock = make_watch(tmp_path, [BASE, CHANGED])
    watch.register("Q4-sales.xlsx")
    clock.advance(24 * 3600)
    result = watch.poll()
    assert result.state == "healthy"
    # The Atlas edit is one removed row plus one added row; Care is new.
    assert result.delta.added == [["Atlas", 44.0], ["Care", 7.0]]
    assert result.delta.removed == [["Atlas", 41.0]]
    assert result.delta.unchanged == 2


def test_poll_before_24h_still_reports_first_view(tmp_path):
    watch, clock = make_watch(tmp_path, [BASE, CHANGED])
    watch.register("Q4-sales.xlsx")
    clock.advance(3600)
    result = watch.poll()
    # No baseline at T-24h yet: the widget says so instead of inventing one.
    assert result.state == "first"
    assert store.snapshot_count(watch.conn, "excel-watch") == 2


def test_locked_workbook_enters_the_amber_state_with_a_cause(tmp_path):
    watch, _clock = make_watch(tmp_path, [BASE, WorkbookLocked("open in Excel")])
    watch.register("Q4-sales.xlsx")
    result = watch.poll()
    assert result.state == "locked"
    assert "open in Excel" in result.cause or "Excel" in result.cause
    status = watch.status()
    assert status["state"] == "locked"
    assert status["cause"]


def test_unlocked_file_recovers_on_retest(tmp_path):
    watch, _clock = make_watch(tmp_path, [BASE, WorkbookLocked("locked"), CHANGED])
    watch.register("Q4-sales.xlsx")
    assert watch.poll().state == "locked"
    recovered = watch.retest()
    assert recovered.state == "first"  # no 24h baseline in this scenario
    assert watch.status()["state"] == "first"


def test_unreadable_file_is_an_amber_cause_not_a_crash(tmp_path):
    watch, _clock = make_watch(tmp_path, [WorkbookUnreadable("not a workbook")])
    result = watch.register("broken.xlsx")
    assert result.state == "unreadable"
    assert "not a workbook" in result.cause


def test_stale_data_is_marked_stale_not_current(tmp_path):
    watch, clock = make_watch(tmp_path, [BASE])
    watch.register("Q4-sales.xlsx")
    assert watch.status()["state"] == "first"
    clock.advance(watch.stale_after_s + 1)
    assert watch.status()["state"] == "stale"


def test_poll_without_registration_is_a_programming_error(tmp_path):
    clock = FakeClock()
    watch = ExcelWatch(
        sqlite3.connect(":memory:"),
        Adapters(copy_shadow=lambda p: Path(p), parse_workbook=lambda p: [], clock=clock),
    )
    with pytest.raises(RuntimeError):
        watch.poll()


def test_polling_timer_can_start_and_stop(tmp_path):
    watch, _clock = make_watch(tmp_path, [])
    watch.start_polling()
    assert watch._timer is not None and watch._timer.is_alive()
    watch.stop_polling()
    watch.start_polling()  # restartable
    watch.stop_polling()
    assert watch._timer is None
