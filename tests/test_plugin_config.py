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
from tests.plugin_fixtures import write_alias_plugin


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


def test_the_heuristic_picks_the_numeric_column_and_the_grouping_label():
    from agentdesk.plugins.suggest import heuristic
    choice = heuristic(
        ["Region", "Booked"],
        [["East", "10"], ["East", "40"], ["West", "4"]],
    )
    assert choice["valueColumn"] == "Booked"
    assert choice["labelColumn"] == "Region"
    assert choice["rows"] == [0, 1, 2]
    assert choice["source"] == "heuristic"
    assert choice["reason"] == "Booked looks like the amount; Region groups rows."


def test_a_row_selection_totals_only_the_ticked_rows(tmp_path):
    from tests import excel_fixtures
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Q4 bookings")
    store.stage_file("excel-report", "main", book)
    store.confirm("excel-report", "main", {
        "labelColumn": "Region",
        "valueColumn": "Booked",
        "aggregate": "sum",
        "rows": [0],
    })
    assert read_tracker(store, "excel-report", "main")["value"] == 10


def test_a_second_reading_is_a_signed_delta_and_a_sparkline(tmp_path):
    from tests import excel_fixtures
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Q4 bookings")
    store.stage_file("excel-report", "main", book)
    store.confirm("excel-report", "main", {
        "labelColumn": "Region",
        "valueColumn": "Booked",
        "aggregate": "sum",
        "unit": "USD",
    })
    first = read_tracker(store, "excel-report", "main")
    assert first["delta"] == "First reading"
    assert first["points"] == [15]
    assert first["unit"] == "USD"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 18],
        ["West", 7],
    ]))
    second = read_tracker(store, "excel-report", "main")
    assert second["value"] == 25
    assert second["delta"] == "+10"
    assert second["direction"] == "up"
    assert second["points"] == [15, 25]


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


def test_two_aliases_expand_to_their_tracker_instances(tmp_path):
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
    runtime.install(write_alias_plugin(
        tmp_path, "sales-alias", "Sales 24h Delta", "Sales"),
        source="dir")
    runtime.install(write_alias_plugin(
        tmp_path, "budget-alias", "Budget 24h Delta", "Budget"),
        source="dir")
    cards = runtime.widget_cards()
    titles = {card["title"] for card in cards}
    assert titles == {"Sales", "Budget"}
    assert all(card["id"] != "sales-alias" for card in cards)
    assert all(card["id"] != "budget-alias" for card in cards)
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


def test_the_fixture_plugin_is_a_valid_config_backed_plugin():
    """The qbr-pack fixture stays honest: the shared validator accepts it,
    it declares the workbook kind, and it is not the historical tracker."""
    from agentdesk.validator.core import validate_plugin

    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests" / "fixtures" / "plugins" / "qbr-pack"
    verdict = validate_plugin(fixture)
    assert verdict.ok, [failure.message for failure in verdict.failures]
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] != "excel-report"
    assert manifest["config"]["kinds"] == ["workbook"]


def test_the_setup_flow_serves_a_plugin_that_is_not_the_tracker(tmp_path):
    """The pick/stage/preview/confirm flow is not pinned to one plugin id:
    the fixture plugin's config lands under its own namespace and never
    under the historical tracker's."""
    from agentdesk.plugins import setup_flow
    from agentdesk.plugins.runtime import PluginRuntime
    from tests import excel_fixtures

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=workspace,
    )
    staged = setup_flow.stage(runtime, 6, "pipeline", "Pipeline", str(book),
                              plugin_id="qbr-pack")
    assert Path(staged["instance"]["source"]["path"]).name == "q4.xlsx"
    shown = setup_flow.preview(runtime, 6, "pipeline", plugin_id="qbr-pack")
    assert shown["preview"]["headers"] == ["Region", "Booked"]
    saved = setup_flow.confirm(
        runtime, 6, "pipeline",
        {"labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum"},
        suggested=False, plugin_id="qbr-pack")
    assert saved["instance"]["confirmedAt"]
    assert (tmp_path / "data" / "qbr-pack" / "instances" / "pipeline" / "config.json").is_file()
    assert not (tmp_path / "data" / "excel-report" / "instances").exists()


def test_a_grant_for_one_plugin_never_authorizes_another_plugin(tmp_path):
    """Two plugin ids on one desk, one instance name each: neither config,
    grant, nor confirmed state is visible across the plugin boundary."""
    from tests import excel_fixtures
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("pipeline-pack", "main", "Pipeline")
    store.stage_file("pipeline-pack", "main", book)
    store.confirm("pipeline-pack", "main", {
        "labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum",
    })

    # The other plugin has no instance of its own: nothing to read with.
    with pytest.raises(ConfigError) as missing:
        store.assert_can_read("desk-pack", "main", book)
    assert missing.value.code == "config:missing"

    # Even after staging the same file, the second plugin's instance is
    # unconfirmed, so its grant alone authorizes nothing.
    store.create("desk-pack", "main", "Desk")
    store.stage_file("desk-pack", "main", book)
    with pytest.raises(ConfigError) as unconfirmed:
        store.assert_can_read("desk-pack", "main", book)
    assert unconfirmed.value.code == "config:not-confirmed"

    # Once each has confirmed its own instance, both read the same file
    # through their own grants and neither owes the other anything.
    store.confirm("desk-pack", "main", {
        "labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum",
    })
    assert read_tracker(store, "pipeline-pack", "main")["value"] == 15
    assert read_tracker(store, "desk-pack", "main")["value"] == 15


def test_the_cap_is_per_plugin_and_uniform_for_every_config_backed_plugin(tmp_path):
    """Six instances cap one plugin; the next plugin on the same desk
    still gets its own full cap from the same store."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = InstanceStore(tmp_path / "data", workspace, cap=MAX_INSTANCE_CAP)
    for index in range(MAX_INSTANCE_CAP):
        store.create("qbr-pack", f"n{index}", f"Instance {index}")
    with pytest.raises(ConfigError) as refused:
        store.create("qbr-pack", "extra", "Extra")
    assert refused.value.code == "config:cap"
    store.create("desk-pack", "main", "Desk")
    assert len(store.list("desk-pack")) == 1


def test_a_second_config_backed_plugin_gets_its_own_instance_cards(tmp_path):
    """The runtime expands every workbook-kind plugin into per-instance
    card keys, one setup wireframe before any confirm, and a fresh card
    bound to that plugin's own confirmed file."""
    from agentdesk.plugins.runtime import PluginRuntime
    from tests import excel_fixtures

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=workspace,
    )
    root = Path(__file__).resolve().parents[1]
    runtime.install(root / "registry" / "plugins" / "excel-report", source="dir")
    runtime.install(root / "tests" / "fixtures" / "plugins" / "qbr-pack", source="dir")

    keys = runtime.layout_keys()
    assert keys == ["excel-report", "qbr-pack"]
    cards = runtime.widget_cards()
    setup_card = next(card for card in cards if card["id"] == "qbr-pack")
    assert setup_card["freshness"] == "setup"
    assert setup_card["payload"]["setup"]["pluginId"] == "qbr-pack"
    assert setup_card["payload"]["setup"]["step"] == "source"

    store = InstanceStore(runtime.data_dir, workspace)
    store.create("qbr-pack", "pipeline", "Pipeline")
    store.stage_file("qbr-pack", "pipeline", book)
    store.confirm("qbr-pack", "pipeline", {
        "labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum",
    })
    assert runtime.layout_keys() == ["excel-report", "qbr-pack~pipeline"]
    cards = runtime.widget_cards()
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "fresh"
    metrics = {element["label"]: element["value"]
               for element in card["payload"]["elements"] if element["kind"] == "metric"}
    assert metrics["Value"] == "15"


def test_confirm_records_the_row_selection_and_the_reader_honors_the_order(tmp_path):
    """T4: the ordered zero-based data rows ride the confirm payload, land
    in the stored tracking document, and are read back in that order:
    "latest" over the selection [1, 0] must return the first picked row's
    value, not the file's physically last row."""
    from tests import excel_fixtures
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Q4 bookings")
    store.stage_file("excel-report", "main", book)
    saved = store.confirm("excel-report", "main", {
        "labelColumn": "Region",
        "valueColumn": "Booked",
        "aggregate": "latest",
        "rows": [1, 0],
    })
    assert saved["tracking"]["rows"] == [1, 0]
    assert read_tracker(store, "excel-report", "main")["value"] == 10


def test_confirm_without_a_selection_keeps_todays_meaning(tmp_path):
    """T4: a confirm whose tracking carries no rows stores rows as None,
    and the read totals every row exactly as it did before the selection
    existed."""
    from tests import excel_fixtures
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Q4 bookings")
    store.stage_file("excel-report", "main", book)
    saved = store.confirm("excel-report", "main", {
        "labelColumn": "Region",
        "valueColumn": "Booked",
        "aggregate": "sum",
    })
    assert saved["tracking"]["rows"] is None
    assert read_tracker(store, "excel-report", "main")["value"] == 15


def test_confirm_refuses_a_selection_past_the_staged_file(tmp_path):
    """T4: rows past the end of the staged file mean the preview went
    stale underneath the modal: the confirm is refused with the existing
    mismatched-file code (config:not-granted, the same 400 envelope), the
    instance stays unconfirmed, and the boundary row itself still
    confirms."""
    from tests import excel_fixtures
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Q4 bookings")
    store.stage_file("excel-report", "main", book)
    with pytest.raises(ConfigError) as refused:
        store.confirm("excel-report", "main", {
            "labelColumn": "Region",
            "valueColumn": "Booked",
            "aggregate": "sum",
            "rows": [0, 2],
        })
    assert refused.value.code == "config:not-granted"
    assert store.read("excel-report", "main")["confirmedAt"] is None
    saved = store.confirm("excel-report", "main", {
        "labelColumn": "Region",
        "valueColumn": "Booked",
        "aggregate": "sum",
        "rows": [0, 1],
    })
    assert saved["tracking"]["rows"] == [0, 1]


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
