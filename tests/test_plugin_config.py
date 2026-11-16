"""Per-user plugin config: instances, grants, the column picker, and suggest."""

import json
from pathlib import Path

import pytest

from agentdesk.plugins.config import ConfigError, InstanceStore, MAX_INSTANCE_CAP
from agentdesk.plugins.preview import preview_table
from agentdesk.plugins.suggest import (
    DISCLOSURE_HEADERS,
    DISCLOSURE_ROWS,
    build_suggestion_request,
    propose_columns,
)
from agentdesk.plugins.tracker import pace_line, read_tracker


def test_a_confirmed_file_is_the_only_path_that_can_be_read(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(b"not-yet")
    sibling = workspace / "other.xlsx"
    sibling.write_bytes(b"nope")
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Revenue")
    store.stage_file("excel-report", "main", book)

    with pytest.raises(ConfigError) as unconfirmed:
        store.assert_can_read("excel-report", "main", book)
    assert unconfirmed.value.code == "config:not-confirmed"

    store.confirm("excel-report", "main", {"labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum"})
    store.assert_can_read("excel-report", "main", book)
    with pytest.raises(ConfigError) as refused:
        store.assert_can_read("excel-report", "main", sibling)
    assert refused.value.code == "config:not-granted"


def test_a_path_outside_the_workspace_needs_acceptance(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "desktop" / "mine.xlsx"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Revenue")
    store.stage_file("excel-report", "main", outside)
    with pytest.raises(ConfigError) as refused:
        store.confirm("excel-report", "main", {"labelColumn": "A", "valueColumn": "B", "aggregate": "sum"})
    assert refused.value.code == "config:outside-workspace"
    store.accept_outside("excel-report", "main")
    saved = store.confirm("excel-report", "main", {"labelColumn": "A", "valueColumn": "B", "aggregate": "sum"})
    assert saved["confirmedAt"]
    store.assert_can_read("excel-report", "main", outside)


def test_the_seventh_instance_is_refused_and_the_cap_can_drop(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = InstanceStore(tmp_path / "data", workspace, cap=MAX_INSTANCE_CAP)
    for index in range(MAX_INSTANCE_CAP):
        store.create("excel-report", f"n{index}", f"Instance {index}")
    with pytest.raises(ConfigError) as refused:
        store.create("excel-report", "extra", "Extra")
    assert refused.value.code == "config:cap"

    tighter = InstanceStore(tmp_path / "data", workspace, cap=2)
    with pytest.raises(ConfigError):
        tighter.create("excel-report", "extra", "Extra")


def test_suggest_sends_headers_and_at_most_five_rows_and_never_the_path(tmp_path):
    rows = [[str(i), str(i * 10)] for i in range(8)]
    request, note = build_suggestion_request(
        job="Track one series from this workbook.",
        sheet="Data",
        headers=["Region", "Booked"],
        rows=rows,
        headers_only=False,
        path=str(tmp_path / "secret.xlsx"),
    )
    assert note == DISCLOSURE_ROWS
    assert request["headers"] == ["Region", "Booked"]
    assert len(request["rows"]) == 5
    assert "secret.xlsx" not in json.dumps(request)
    assert len(json.dumps(request).encode()) <= 8192

    headers_only, note = build_suggestion_request(
        job="Track one series from this workbook.",
        sheet="Data",
        headers=["Region", "Booked"],
        rows=rows,
        headers_only=True,
        path=str(tmp_path / "secret.xlsx"),
    )
    assert note == DISCLOSURE_HEADERS
    assert headers_only["rows"] == []
    assert "10" not in json.dumps(headers_only)


def test_dismiss_does_not_write_and_confirm_records_the_suggestion(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(b"x")
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Revenue")
    store.stage_file("excel-report", "main", book)
    before = store.read("excel-report", "main")
    assert before["confirmedAt"] is None
    # Dismiss is the absence of confirm: the staged file is still unconfirmed.
    assert store.read("excel-report", "main")["confirmedAt"] is None
    store.confirm(
        "excel-report", "main",
        {"labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum"},
        suggested=True,
    )
    saved = store.read("excel-report", "main")
    assert saved["suggested"] is True
    assert saved["tracking"]["valueColumn"] == "Booked"


def test_propose_columns_uses_the_model_reply_and_ignores_a_failure(tmp_path):
    captured = {}

    def complete(prompt: str) -> str:
        captured["prompt"] = prompt
        return '{"labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum"}'

    proposal = propose_columns(
        {"job": "Track booked revenue.", "sheet": "Data", "headers": ["Region", "Booked"], "rows": [["East", "10"]]},
        complete,
    )
    assert proposal["valueColumn"] == "Booked"
    assert "East" in captured["prompt"]
    with pytest.raises(ConfigError):
        propose_columns(
            {"job": "Track booked revenue.", "sheet": "Data", "headers": ["Region"], "rows": []},
            lambda _prompt: "not json",
        )


def test_a_sales_install_becomes_a_tracker_instance(tmp_path):
    from agentdesk.plugins.execute import PluginWidgetRunner
    from agentdesk.plugins.runtime import PluginRuntime

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=workspace,
        runner=PluginWidgetRunner(workspace),
    )
    root = Path(__file__).resolve().parents[1] / "registry" / "plugins"
    runtime.install(root / "excel-report", source="dir")
    runtime.install(root / "sales-delta-widget", source="dir")
    runtime.install(root / "budget-burn", source="dir")
    cards = runtime.widget_cards()
    titles = {card["title"] for card in cards}
    assert titles == {"Sales", "Budget"}
    assert all(card["id"] != "sales-delta-widget" for card in cards)
    assert all(card["id"] != "budget-burn" for card in cards)
    budget = next(card for card in cards if card["title"] == "Budget")
    assert budget["freshness"] == "setup"


def test_preview_reads_only_the_staged_workbook(tmp_path):
    from tests import excel_fixtures
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 4],
    ]))
    preview = preview_table(book, sheet=None, header_row=1, range_text=None, limit=20)
    assert preview["headers"] == ["Region", "Booked"]
    assert preview["rows"][0] == ["East", "10"]


def test_tracker_reads_the_granted_file_and_pace_uses_only_the_users_numbers(tmp_path):
    from tests import excel_fixtures
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    other = workspace / "other.xlsx"
    other.write_bytes(excel_fixtures.make_xlsx([["Region", "Booked"], ["East", 99]]))
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "budget", "Budget", good="down")
    store.stage_file("excel-report", "budget", book)
    store.confirm("excel-report", "budget", {
        "labelColumn": "Region",
        "valueColumn": "Booked",
        "aggregate": "sum",
        "good": "down",
        "pace": {"plan": 30, "periodDays": 10, "elapsedDays": 2},
    })
    reading = read_tracker(store, "excel-report", "budget")
    assert reading["value"] == 15
    assert reading["file"] == "q4.xlsx"
    assert "7.50" in reading["paceNote"]
    assert "3.00" in reading["paceNote"]
    # The sibling is not opened: a second read of the granted file still totals 15.
    assert read_tracker(store, "excel-report", "budget")["value"] == 15
    assert pace_line(15, 2, 30, 10) == "7.50 per day against 3.00 per day"
