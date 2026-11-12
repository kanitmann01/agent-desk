"""The plugin widget runner: excel-watch execution and ui-schema binding.

Adapters are fakes throughout (the shadow copy is the identity, the
parser returns a mutable list, the clock is a number the test moves),
so these tests cover the runner's own behavior: probe-shaped status,
honest amber states, and the binding of real poll results into the
ui-schema render model. The excel arithmetic itself is covered by the
excel suite; here it only has to arrive.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.excel.core import WorkbookLocked  # noqa: E402
from agentdesk.excel.watcher import Adapters  # noqa: E402
from agentdesk.plugins.execute import PluginWidgetRunner  # noqa: E402
from agentdesk.plugins.runtime import PluginRuntime  # noqa: E402
from plugins_fixtures import valid_zip  # noqa: E402

DAY = 24 * 60 * 60.0


class FakeWorkbook:
    """A parseable workbook the test mutates between polls."""

    def __init__(self, rows):
        self.rows = rows
        self.locked = False

    def parse(self, _path):
        if self.locked:
            raise WorkbookLocked()
        return self.rows


def _runner(workspace: Path, workbook: FakeWorkbook, clock: list[float]):
    adapters = Adapters(copy_shadow=lambda path: Path(path),
                        parse_workbook=workbook.parse,
                        clock=lambda: clock[0])
    return PluginWidgetRunner(workspace, adapters=adapters)


def _manifest(tmp_path: Path, *, source_type="excel-watch",
              file_glob="${workspace}/reports/*.xlsx", elements=None) -> dict:
    return {
        "id": "sales-delta-widget",
        "contributes": {"widgets": [{
            "id": "sales-delta",
            "dataSource": {"type": source_type, "file": file_glob,
                           "deltaWindow": "24h"},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }


@pytest.fixture
def workspace(tmp_path):
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    (reports / "sales.xlsx").write_bytes(b"xlsx")
    return tmp_path / "workspace"


def _write_ui(version_dir: Path, elements: list) -> None:
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (version_dir / "widget.ui.json").write_text(
        json.dumps({"type": "card", "elements": elements}), encoding="utf-8")


def test_first_poll_is_fresh_with_baseline_note(workspace, tmp_path):
    workbook = FakeWorkbook([["Region", "Sales"], ["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "delta24h", "label": "Changed rows"},
    ])
    status = runner.attach("p1", _manifest(tmp_path), version_dir,
                           tmp_path / "data")
    assert status["status"] == "fresh"
    payload = runner.payload("p1")
    assert payload is not None
    assert payload["status"] == "fresh"
    assert payload["elements"] == [
        {"kind": "metric", "label": "Changed rows",
         "value": "First snapshot taken; changes show on the next refresh."},
    ]


def test_delta_binds_after_the_window(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "delta24h"},
        {"type": "metric", "binding": "addedCount", "label": "New"},
        {"type": "metric", "binding": "removedCount", "label": "Removed"},
        {"type": "text", "binding": "windowNote"},
    ])
    runner.attach("p1", _manifest(tmp_path), version_dir, tmp_path / "data")
    workbook.rows = [["North", 10], ["South", 20]]
    clock[0] += DAY + 60
    status = runner.retest("p1")
    assert status["status"] == "fresh"
    payload = runner.payload("p1")
    metrics = [e["value"] for e in payload["elements"] if e["kind"] == "metric"]
    assert metrics[0] == "1 new rows."
    assert metrics[1] == "1"
    assert metrics[2] == "0"
    notes = [e["text"] for e in payload["elements"] if e["kind"] == "text"]
    assert notes == ["Compared with the snapshot from about 24 hours ago."]


def test_locked_workbook_is_amber_with_cause(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "metric", "binding": "delta24h"}])
    runner.attach("p1", _manifest(tmp_path), version_dir, tmp_path / "data")
    workbook.locked = True
    clock[0] += DAY + 60
    status = runner.retest("p1")
    assert status["status"] == "attention"
    assert "open in Excel" in status["cause"]
    # The card renders amber; the payload still binds nothing false.
    payload = runner.payload("p1")
    assert payload["status"] == "attention"


def test_unexecutable_type_keeps_probe_parity(workspace, tmp_path):
    workbook = FakeWorkbook([["x"]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    status = runner.attach("p1", _manifest(tmp_path, source_type="json-watch"),
                           tmp_path / "plugin", tmp_path / "data")
    assert status == {"status": "fresh", "cause": "",
                      "checked_at": status["checked_at"],
                      "file": "sales.xlsx"}
    assert not runner.attached("p1")
    assert runner.payload("p1") is None


def test_no_matching_file_is_attention(workspace, tmp_path):
    workbook = FakeWorkbook([["x"]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    status = runner.attach("p1", _manifest(
        tmp_path, file_glob="${workspace}/reports/*.missing"),
        tmp_path / "plugin", tmp_path / "data")
    assert status["status"] == "attention"
    assert "no file matches" in status["cause"]


def test_unknown_bindings_and_kinds_are_dropped(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "inventedNumber"},
        {"type": "metric", "binding": "rowsSeen", "label": "Rows"},
        {"type": "chart", "binding": "delta24h"},
        {"type": "text", "text": "Static note"},
    ])
    runner.attach("p1", _manifest(tmp_path), version_dir, tmp_path / "data")
    payload = runner.payload("p1")
    assert payload["elements"] == [
        {"kind": "metric", "label": "Rows", "value": "1"},
        {"kind": "text", "text": "Static note"},
    ]


def test_runtime_installs_executes_and_retests_the_widget(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    zip_path = valid_zip(tmp_path / "sales.zip")
    result = runtime.install(zip_path)
    assert result["ok"] is True
    record = runtime.record("sales-delta-widget")
    assert record["data_source"]["status"] == "fresh"

    cards = runtime.widget_cards()
    assert len(cards) == 1
    payload = cards[0]["payload"]
    assert payload is not None
    metrics = [e["value"] for e in payload["elements"] if e["kind"] == "metric"]
    assert metrics == ["First snapshot taken; changes show on the next refresh."]

    workbook.rows = [["North", 10], ["South", 20], ["East", 5], ["West", 1]]
    clock[0] += DAY + 60
    runtime.retest("sales-delta-widget")
    cards = runtime.widget_cards()
    metrics = [e["value"] for e in cards[0]["payload"]["elements"]
               if e["kind"] == "metric"]
    assert metrics[0] == "3 new rows."


def test_disable_detaches_and_enable_reattaches(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    runtime.install(valid_zip(tmp_path / "sales.zip"))
    assert runner.attached("sales-delta-widget")

    runtime.disable("sales-delta-widget")
    assert not runner.attached("sales-delta-widget")
    assert runtime.widget_cards() == []

    runtime.enable("sales-delta-widget")
    assert runner.attached("sales-delta-widget")
    cards = runtime.widget_cards()
    assert cards and cards[0]["freshness"] == "fresh"


def test_uninstall_detaches_but_keeps_data(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    runtime.install(valid_zip(tmp_path / "sales.zip"))
    data_dir = Path(runtime.record("sales-delta-widget")["data_dir"])

    runtime.uninstall("sales-delta-widget")
    assert not runner.attached("sales-delta-widget")
    assert data_dir.exists()  # preserved until the named purge
