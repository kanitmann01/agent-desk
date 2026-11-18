"""JSON exports: the same preview, confirm, and tracker path as workbooks."""

import json

import pytest

from agentdesk.plugins.config import ConfigError, InstanceStore
from agentdesk.plugins.preview import preview_table
from agentdesk.plugins.tracker import read_tracker


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_an_array_of_objects_previews_as_a_table(tmp_path):
    export = _write(tmp_path / "pipeline.json", [
        {"Deal": "Acme", "Amount": 1200.5},
        {"Deal": "Globex", "Amount": 800},
    ])
    table = preview_table(export, sheet=None, header_row=1, range_text=None)
    assert table["headers"] == ["Deal", "Amount"]
    assert table["rows"] == [["Acme", "1200.5"], ["Globex", "800"]]


def test_an_object_holding_one_list_of_rows_is_unwrapped(tmp_path):
    export = _write(tmp_path / "rows.json", {"rows": [{"Deal": "Acme", "Amount": 5}]})
    table = preview_table(export, sheet=None, header_row=1, range_text=None)
    assert table["headers"] == ["Deal", "Amount"]
    assert table["rows"] == [["Acme", "5"]]


def test_json_that_is_not_a_table_says_so(tmp_path):
    export = _write(tmp_path / "notes.json", {"note": "hello"})
    with pytest.raises(ConfigError) as refused:
        preview_table(export, sheet=None, header_row=1, range_text=None)
    assert refused.value.code == "config:not-a-table"


def test_a_json_instance_tracks_the_rows_the_user_chose(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    export = _write(workspace / "pipeline.json", [
        {"Deal": "Acme", "Amount": 1200},
        {"Deal": "Globex", "Amount": 800},
        {"Deal": "Initech", "Amount": 200},
    ])
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "main", "Pipeline")
    store.stage_file("excel-report", "main", export)
    store.confirm("excel-report", "main", {
        "labelColumn": "Deal",
        "valueColumn": "Amount",
        "aggregate": "sum",
        "rows": [0, 2],
    })
    reading = read_tracker(store, "excel-report", "main")
    assert reading["value"] == 1400
    assert reading["rowsSeen"] == 2
    assert reading["file"] == "pipeline.json"


def test_a_reading_carries_its_time_and_its_folder_truth(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "sample").mkdir(parents=True)
    real = _write(workspace / "pipeline.json", [{"Deal": "Acme", "Amount": 5}])
    fixture = _write(workspace / "sample" / "sample-pipeline.json", [{"Deal": "Sample", "Amount": 9}])
    store = InstanceStore(tmp_path / "data", workspace)
    store.create("excel-report", "real", "Pipeline")
    store.stage_file("excel-report", "real", real)
    store.confirm("excel-report", "real", {
        "labelColumn": "Deal", "valueColumn": "Amount", "aggregate": "sum", "rows": [0],
    })
    store.create("excel-report", "demo", "Demo pipeline")
    store.stage_file("excel-report", "demo", fixture)
    store.confirm("excel-report", "demo", {
        "labelColumn": "Deal", "valueColumn": "Amount", "aggregate": "sum", "rows": [0],
    })
    real_reading = read_tracker(store, "excel-report", "real")
    demo_reading = read_tracker(store, "excel-report", "demo")
    assert real_reading["readAt"] > 0
    assert real_reading["sample"] is False
    assert demo_reading["sample"] is True
