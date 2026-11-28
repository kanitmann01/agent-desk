"""The three update modes through the runner, which is what serves a card.

These tests drive a real runner over a real file, and pin the one rule that
keeps the modes apart: a scheduled or change-driven tile is answered from its
stored reading, so opening the desk never re-reads it. Re-testing still does.

The source is a JSON file rather than a workbook on purpose: a workbook's
numbers move when its own watch polls, which would hide the difference the
modes make. A file read is a file read.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.plugins.execute import PluginWidgetRunner  # noqa: E402
from nexuusbot.plugins.refresh import ReadingStore  # noqa: E402


def _manifest(events: list) -> dict:
    return {
        "id": "sales",
        "activationEvents": events,
        "contributes": {"widgets": [{
            "id": "sales",
            "dataSource": {"type": "json-watch",
                           "file": "${workspace}/data/sales.json",
                           "selector": "$.value"},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }


def _write_ui(version_dir: Path) -> None:
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (version_dir / "widget.ui.json").write_text(
        json.dumps({"type": "card", "elements": [
            {"type": "metric", "binding": "value", "label": "Value"}]}),
        encoding="utf-8")


def _value(card: dict) -> str:
    """The number the tile shows, which is what a manager would notice."""
    return str(card["payload"]["elements"][0]["value"])


@pytest.fixture
def workspace(tmp_path):
    data = tmp_path / "workspace" / "data"
    data.mkdir(parents=True)
    (data / "sales.json").write_text(json.dumps({"value": 10}), encoding="utf-8")
    return tmp_path / "workspace"


def _write_value(workspace: Path, value: int) -> None:
    """Write the watched file one clock tick after any earlier write.

    Windows stamps a write with the system clock's tick, about one
    millisecond, so two writes inside one tick share a modification time
    and the tile rightly reads that as no change. A real save never lands
    that close to the one before it, so the helper steps the time forward.
    """
    path = workspace / "data" / "sales.json"
    path.write_text(json.dumps({"value": value}), encoding="utf-8")
    written = path.stat()
    os.utime(path, ns=(written.st_atime_ns, written.st_mtime_ns + 1_000_000))


def _attached(workspace: Path, tmp_path: Path, events: list,
              reading_time: datetime | None = None) -> PluginWidgetRunner:
    runner = PluginWidgetRunner(workspace)
    if reading_time is not None:
        runner.readings = ReadingStore(lambda: reading_time)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir)
    runner.attach("sales", _manifest(events), version_dir, tmp_path / "data")
    return runner


def test_a_view_tile_reads_live_on_every_open(workspace, tmp_path):
    runner = _attached(workspace, tmp_path, ["onWidget:sales"])

    first = runner.card("sales")
    _write_value(workspace, 99)
    second = runner.card("sales")

    # No cache flag, and the second open sees the new file.
    assert "cached" not in second
    assert first["status"]["status"] == "fresh"
    assert _value(first) == "10"
    assert _value(second) == "99"


def test_a_scheduled_tile_serves_its_stored_reading_between_ticks(workspace, tmp_path):
    runner = _attached(workspace, tmp_path,
                       ["onWidget:sales", "onSchedule:0 8 * * *"])

    stored = runner.card("sales")  # the first read, taken for the tile
    _write_value(workspace, 50)
    opened = runner.card("sales")

    assert stored.get("cached") is not True  # the first read is live
    assert opened.get("cached") is True
    assert _value(opened) == _value(stored) == "10"


@pytest.mark.parametrize(("stored", "not_due", "expected_due"), [
    (datetime(2026, 11, 25, 0, 0),
     (datetime(2026, 11, 25, 7, 59),),
     datetime(2026, 11, 25, 8, 0)),
    (datetime(2026, 11, 25, 7, 59),
     (),
     datetime(2026, 11, 25, 8, 0)),
    (datetime(2026, 11, 25, 8, 0),
     (datetime(2026, 11, 25, 8, 0), datetime(2026, 11, 25, 23, 59)),
     datetime(2026, 11, 26, 8, 0)),
])
def test_a_scheduled_tile_refreshes_when_its_clock_comes_due(
        workspace, tmp_path, stored, not_due, expected_due):
    runner = _attached(workspace, tmp_path,
                       ["onWidget:sales", "onSchedule:0 8 * * *"], stored)
    before = runner.card("sales")
    _write_value(workspace, 50)
    assert before["asOf"] == stored.isoformat(timespec="seconds")

    # The first 08:00 strictly after the stored reading is the due time.
    due = stored.replace(hour=8, minute=0, second=0, microsecond=0)
    if due <= stored:
        due += timedelta(days=1)
    assert due == expected_due

    # Before the due minute, including the rest of a reading's own 08:00 day.
    for now in not_due:
        assert runner.refresh_due(now) == []
        assert _value(runner.card("sales")) == _value(before)

    # The scheduled minute: the tile re-reads, and the open now shows it.
    assert runner.refresh_due(due) == ["sales"]
    assert _value(runner.card("sales")) == "50"


def test_a_change_tile_refreshes_only_after_its_own_event(workspace, tmp_path):
    runner = _attached(workspace, tmp_path, ["onWidget:sales", "onHook:file"])
    before = runner.card("sales")
    _write_value(workspace, 50)

    # Opening the desk is not a change, and another topic's event is not this
    # plugin's: neither re-reads it.
    assert _value(runner.card("sales")) == _value(before)
    assert runner.refresh_on_event("mail") == []
    assert _value(runner.card("sales")) == _value(before)

    # Its own event does.
    assert runner.refresh_on_event("file") == ["sales"]
    assert _value(runner.card("sales")) == "50"


def test_an_event_with_an_unchanged_reading_leaves_the_tile_alone(workspace, tmp_path):
    runner = _attached(workspace, tmp_path, ["onWidget:sales", "onHook:file"])
    first = runner.card("sales")

    # The file is rewritten with the same value: an event fires, the reading
    # does not change, so the tile and its as-of time stay as they were.
    _write_value(workspace, 10)
    assert runner.refresh_on_event("file") == []
    after = runner.card("sales")
    assert after["asOf"] == first["asOf"]


def test_a_file_change_tile_refreshes_only_when_the_file_moved(workspace, tmp_path):
    """The minute tick's file path: a stat that shows no change costs no read,
    and a save is picked up on the next tick."""
    runner = _attached(workspace, tmp_path, ["onWidget:sales", "onHook:file"])
    runner.card("sales")  # first read, and the stamp it records

    # Nothing written: the tick does nothing at all.
    assert runner.refresh_files_and_pipelines() == []
    _write_value(workspace, 77)
    assert set(runner.refresh_files_and_pipelines()) == {"sales"}
    assert _value(runner.card("sales")) == "77"


def test_retesting_still_reads_once_on_demand(workspace, tmp_path):
    """Re-test is the manager asking for a fresh read, which every mode
    allows; it must keep working for a scheduled tile."""
    runner = _attached(workspace, tmp_path,
                       ["onWidget:sales", "onSchedule:0 8 * * *"])
    before = runner.card("sales")
    _write_value(workspace, 50)

    status = runner.retest("sales")

    assert status["status"] == "fresh"
    assert _value(runner.card("sales")) == "50"
    assert _value(runner.card("sales")) != _value(before)
