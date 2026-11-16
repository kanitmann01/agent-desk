"""Pure host-side rendering of ui-schema elements (T1).

No plugin code runs here: render_elements maps a ui-schema document plus
an already-computed binding dict into the element DTOs the dashboard
draws, and render_sample proves a v2 manifest's fixture renders without
touching anything outside the plugin directory.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.plugins.render import (  # noqa: E402
    ELEMENT_KINDS,
    PluginRenderError,
    render_elements,
    render_sample,
)


def _render(elements, bindings):
    return render_elements({"type": "card", "elements": elements}, bindings)


def test_element_kinds_are_the_ten_contract_kinds():
    assert ELEMENT_KINDS == (
        "metric", "text", "delta", "progress", "list", "table",
        "sparkline", "status", "timeline", "checklist",
    )


def test_metric_binds_a_scalar_as_text():
    out = _render([{"type": "metric", "binding": "count", "label": "Rows"}],
                  {"count": 4})
    assert out == [{"kind": "metric", "state": "ok", "label": "Rows",
                    "value": "4"}]


def test_text_uses_binding_or_literal_text():
    out = _render([
        {"type": "text", "binding": "note"},
        {"type": "text", "text": "Static note"},
        {"type": "text", "text": "With label", "label": "Hint"},
    ], {"note": "Bound note"})
    assert out == [
        {"kind": "text", "state": "ok", "text": "Bound note"},
        {"kind": "text", "state": "ok", "text": "Static note"},
        {"kind": "text", "state": "ok", "text": "With label", "label": "Hint"},
    ]


def test_delta_carries_direction_and_window():
    out = _render([{
        "type": "delta", "binding": "change", "directionBinding": "dir",
        "window": "24h", "label": "Changed",
    }], {"change": 12, "dir": "up"})
    assert out == [{"kind": "delta", "state": "ok", "label": "Changed",
                    "value": "12", "direction": "up", "window": "24h"}]


def test_delta_direction_defaults_to_flat_and_window_to_empty():
    out = _render([{"type": "delta", "binding": "change", "label": "Changed"}],
                  {"change": 0})
    assert out[0]["direction"] == "flat"
    assert out[0]["window"] == ""


def test_progress_binds_value_target_unit_and_tone():
    out = _render([{
        "type": "progress", "binding": "used", "targetBinding": "budget",
        "unit": "%", "toneBinding": "tone", "label": "Budget",
    }], {"used": 40, "budget": 100, "tone": "attention"})
    assert out == [{"kind": "progress", "state": "ok", "label": "Budget",
                    "value": 40, "target": 100, "unit": "%",
                    "tone": "attention"}]


def test_progress_accepts_a_literal_target_and_default_tone():
    out = _render([{"type": "progress", "binding": "used",
                    "target": 10, "unit": "items", "label": "Done"}],
                  {"used": "4"})
    assert out[0]["target"] == 10
    assert out[0]["tone"] == "ok"
    assert out[0]["value"] == 4


def test_list_renders_dict_rows():
    out = _render([{"type": "list", "rowsBinding": "rows", "title": "Top"}], {
        "rows": [
            {"primary": "North", "secondary": "10 sales", "meta": "up"},
            {"primary": "South", "secondary": "8 sales", "meta": "down"},
        ],
    })
    assert out == [{"kind": "list", "state": "ok", "title": "Top", "rows": [
        {"primary": "North", "secondary": "10 sales", "meta": "up"},
        {"primary": "South", "secondary": "8 sales", "meta": "down"},
    ]}]


def test_list_accepts_plain_strings():
    out = _render([{"type": "list", "rowsBinding": "rows"}],
                  {"rows": ["one", "two"]})
    assert out[0]["rows"] == [
        {"primary": "one", "secondary": "", "meta": ""},
        {"primary": "two", "secondary": "", "meta": ""},
    ]


def test_table_renders_columns_and_string_cells():
    out = _render([{"type": "table", "rowsBinding": "rows",
                    "columns": ["Region", "Sales"], "title": "By region"}], {
        "rows": [["North", 10], ["South", 8]],
    })
    assert out == [{"kind": "table", "state": "ok", "title": "By region",
                    "columns": ["Region", "Sales"],
                    "rows": [["North", "10"], ["South", "8"]]}]


def test_sparkline_computes_min_and_max_from_points():
    points = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    out = _render([{"type": "sparkline", "pointsBinding": "points",
                    "label": "Trend"}], {"points": points})
    assert out == [{"kind": "sparkline", "state": "ok", "label": "Trend",
                    "points": points, "min": 1, "max": 12}]


def test_status_uses_tone_binding_or_literal_and_text_binding():
    out = _render([
        {"type": "status", "toneBinding": "tone", "binding": "message"},
        {"type": "status", "tone": "alarm", "binding": "message"},
        {"type": "status", "binding": "message"},
    ], {"tone": "attention", "message": "3 rows changed"})
    assert out == [
        {"kind": "status", "state": "ok", "tone": "attention",
         "text": "3 rows changed"},
        {"kind": "status", "state": "ok", "tone": "alarm",
         "text": "3 rows changed"},
        {"kind": "status", "state": "ok", "tone": "ok",
         "text": "3 rows changed"},
    ]


def test_timeline_renders_items():
    out = _render([{"type": "timeline", "itemsBinding": "items",
                    "title": "Today"}], {
        "items": [{"time": "09:00", "title": "Standup", "meta": "15m"}],
    })
    assert out == [{"kind": "timeline", "state": "ok", "title": "Today",
                    "items": [{"time": "09:00", "title": "Standup",
                               "meta": "15m"}]}]


def test_checklist_renders_items_and_coerces_done():
    out = _render([{"type": "checklist", "itemsBinding": "items",
                    "title": "Today"}], {
        "items": [
            {"text": "Send report", "done": True, "due": "10:00"},
            {"text": "Call back", "done": False, "due": ""},
        ],
    })
    assert out == [{"kind": "checklist", "state": "ok", "title": "Today",
                    "items": [
                        {"text": "Send report", "done": True, "due": "10:00"},
                        {"text": "Call back", "done": False, "due": ""},
                    ]}]


def test_missing_binding_renders_blank_never_zero():
    out = _render([{"type": "metric", "binding": "invented",
                    "label": "Made up"}], {})
    assert out == [{"kind": "metric", "state": "blank", "label": "Made up",
                    "value": "", "reason": "no value for binding invented"}]
    assert out[0]["value"] != "0"


def test_missing_structured_binding_renders_blank_never_crashes():
    out = _render([
        {"type": "list", "rowsBinding": "rows"},
        {"type": "table", "rowsBinding": "rows", "columns": []},
        {"type": "sparkline", "pointsBinding": "points"},
        {"type": "timeline", "itemsBinding": "items"},
        {"type": "checklist", "itemsBinding": "items"},
    ], {})
    assert [element["state"] for element in out] == ["blank"] * 5
    assert all(element["reason"].startswith("no value for binding")
               for element in out)
    assert out[0]["rows"] == []
    assert out[2]["points"] == []


def test_malformed_structured_data_is_blank_not_a_crash():
    out = _render([
        {"type": "list", "rowsBinding": "rows"},
        {"type": "table", "rowsBinding": "rows", "columns": "nope"},
        {"type": "sparkline", "pointsBinding": "points"},
        {"type": "timeline", "itemsBinding": "items"},
        {"type": "checklist", "itemsBinding": "items"},
    ], {"rows": "not a list", "points": ["x"], "items": {"nope": True}})
    assert [element["state"] for element in out] == ["blank"] * 5
    assert out[0]["rows"] == []
    assert out[2]["points"] == []


def test_unknown_kind_raises_with_the_contract_code():
    with pytest.raises(PluginRenderError) as info:
        _render([{"type": "chart", "binding": "x"}], {"x": 1})
    assert info.value.code == "plugin:unknown-element"
    assert "chart" in str(info.value)


def test_non_dict_elements_are_skipped():
    out = _render([42, {"type": "text", "text": "kept"}, None], {})
    assert out == [{"kind": "text", "state": "ok", "text": "kept"}]


def _write_sample_plugin(directory: Path, *, sample=None, state="ok",
                         checked_at="2026-11-15T09:00:00", elements=None):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps({
        "schemaVersion": 2,
        "id": "sample-widget",
        "name": "Sample widget",
        "version": "1.0.0",
        "publisher": "desk",
        "class": "declarative",
        "engines": {"dashboardHost": ">=1.0.0"},
        "license": "MIT",
        "permissions": {"shell": "none"},
        "activationEvents": ["onWidget:sample"],
        "category": "finance",
        "tags": ["sales"],
        "icon": "chart",
        "summary": "Sample widget.",
        "description": "A sample widget used by the render tests.",
        "highlights": ["a", "b", "c"],
        "sample": "sample.json",
        "contributes": {"widgets": [{
            "id": "sample",
            "dataSource": {"type": "excel-watch",
                           "file": "${workspace}/reports/*.xlsx"},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }), encoding="utf-8")
    (directory / "widget.ui.json").write_text(json.dumps({
        "type": "card",
        "elements": elements or [
            {"type": "metric", "binding": "count", "label": "Rows"},
        ],
    }), encoding="utf-8")
    if sample is not None:
        (directory / "sample.json").write_text(json.dumps(sample),
                                               encoding="utf-8")
    return directory


def test_render_sample_returns_the_bound_payload(tmp_path):
    plugin = _write_sample_plugin(tmp_path / "plugin", sample={
        "bindings": {"count": 3},
        "state": "ok",
        "checkedAt": "2026-11-15T09:00:00",
    })
    assert render_sample(plugin) == {
        "elements": [{"kind": "metric", "state": "ok", "label": "Rows",
                      "value": "3"}],
        "status": "fresh",
        "cause": "",
        "checked_at": "2026-11-15T09:00:00",
    }


def test_render_sample_maps_a_non_ok_state_to_attention(tmp_path):
    plugin = _write_sample_plugin(tmp_path / "plugin", sample={
        "bindings": {},
        "state": "stale",
        "checkedAt": "2026-11-15T08:00:00",
    })
    out = render_sample(plugin)
    assert out["status"] == "attention"
    assert out["checked_at"] == "2026-11-15T08:00:00"


def test_render_sample_missing_sample_file_raises(tmp_path):
    plugin = _write_sample_plugin(tmp_path / "plugin", sample=None)
    with pytest.raises(PluginRenderError) as info:
        render_sample(plugin)
    assert "sample" in str(info.value).lower()


def test_render_sample_refuses_a_path_outside_the_plugin_dir(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"bindings": {"count": 1}}), encoding="utf-8")
    plugin = _write_sample_plugin(tmp_path / "plugin", sample={
        "bindings": {"count": 3}})
    manifest = json.loads((plugin / "manifest.json").read_text(encoding="utf-8"))
    manifest["sample"] = "../outside.json"
    (plugin / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PluginRenderError):
        render_sample(plugin)


def test_render_sample_unknown_element_kind_raises(tmp_path):
    plugin = _write_sample_plugin(tmp_path / "plugin", sample={
        "bindings": {"count": 3},
    }, elements=[{"type": "chart", "binding": "count"}])
    with pytest.raises(PluginRenderError) as info:
        render_sample(plugin)
    assert info.value.code == "plugin:unknown-element"
    assert "chart" in str(info.value)
