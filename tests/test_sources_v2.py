"""The twelve data sources: one fixture each, and the honest states.

These are unit tests over sources.read_source plus one end-to-end runner
test for the payload envelope. Every fixture is a real file in tmp_path;
the network and desk-state seams are injected, so no test touches the
network, the user's files, or a live desk.
"""
import json
import os
from datetime import datetime

import pytest

from agentdesk.plugins.execute import PluginWidgetRunner
from agentdesk.plugins.sources import (
    STATES,
    SourceContext,
    SourceResult,
    read_source,
)
from agentdesk.validator import validate_plugin
from test_validator_support import VALID_MANIFEST, write_plugin

NOW = datetime(2026, 11, 15, 12, 0, 0)
DAY = 86400.0
NL = "\n"


def make_ctx(tmp_path, **kwargs):
    workspace = tmp_path / "workspace"
    data = tmp_path / "data"
    workspace.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    return SourceContext(
        plugin_id=kwargs.pop("plugin_id", "p"),
        workspace_dir=workspace,
        data_dir=data,
        now=NOW,
        **kwargs,
    )


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_csv(path, text):
    path = write(path, text)
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    return path


def age(path, seconds):
    stamp = NOW.timestamp() - seconds
    os.utime(path, (stamp, stamp))
    return path


def csv_source(path, **overrides):
    source = {
        "type": "csv-watch",
        "file": str(path),
        "keyColumn": "Region",
        "valueColumn": "Sales",
        "aggregate": "sum",
        "window": "24h",
    }
    source.update(overrides)
    return source


# ---- one fixture per source type ----

def test_csv_watch_reads_ok_with_rows_and_value(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write_csv(ctx.workspace_dir / "sales.csv",
                     "Region,Sales\nNorth,10\nSouth,5\n")

    result = read_source(csv_source(path), ctx)

    assert result.state == "ok"
    assert result.reason == "ok"
    assert result.as_of
    assert result.bindings["value"] == 15
    assert result.bindings["count"] == 2
    assert result.bindings["rows"] == [
        {"primary": "North", "secondary": "10", "meta": ""},
        {"primary": "South", "secondary": "5", "meta": ""},
    ]
    assert result.bindings["table"] == [["North", "10", ""], ["South", "5", ""]]


def test_csv_watch_date_column_ages_rows_and_windows_the_aggregate(tmp_path):
    """A dated CSV gets relative aging on every row and, when a window is
    declared, its aggregate covers only the rows inside that window."""
    ctx = make_ctx(tmp_path)
    path = write_csv(
        ctx.workspace_dir / "ar.csv",
        "Customer,Balance,DueDate\n"
        "Acme,120,2026-11-10\n"
        "Beta,80,2026-09-01\n"
        "Gamma,40,2020-01-01\n",
    )

    result = read_source(
        csv_source(path, keyColumn="Customer", valueColumn="Balance",
                   dateColumn="DueDate", window="90d", aggregate="sum"),
        ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 200  # Gamma is outside the 90d window
    assert result.bindings["count"] == 2
    assert result.bindings["rowsSeen"] == 2  # legacy alias of count
    assert result.bindings["rows"] == [
        {"primary": "Acme", "secondary": "120", "meta": "5 days overdue"},
        {"primary": "Beta", "secondary": "80", "meta": "75 days overdue"},
    ]
    assert result.detail["windowedRows"] == 2
    assert result.detail["dateColumn"] == "DueDate"


def test_csv_watch_date_column_marks_future_dates_as_due(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write_csv(ctx.workspace_dir / "ar.csv",
                     "Customer,Balance,DueDate\nAcme,10,2026-12-01\n")

    result = read_source(
        csv_source(path, keyColumn="Customer", valueColumn="Balance",
                   dateColumn="DueDate"), ctx)

    assert result.state == "ok"
    assert result.bindings["rows"] == [
        {"primary": "Acme", "secondary": "10", "meta": "due in 16 days"}]


def test_csv_watch_missing_date_column_blanks_with_its_name(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write_csv(ctx.workspace_dir / "ar.csv",
                     "Customer,Balance\nAcme,10\n")

    result = read_source(
        csv_source(path, keyColumn="Customer", valueColumn="Balance",
                   dateColumn="ClosedOn", window="90d"), ctx)

    assert result.state == "blank"
    assert result.reason == "bad-schema"
    assert "ClosedOn" in result.human


def test_csv_watch_window_with_no_rows_blanks_honestly(tmp_path):
    """No row inside the window is a blank that names the window, never a
    confident zero."""
    ctx = make_ctx(tmp_path)
    path = write_csv(ctx.workspace_dir / "ar.csv",
                     "Customer,Balance,DueDate\nAcme,10,2020-01-01\n")

    result = read_source(
        csv_source(path, keyColumn="Customer", valueColumn="Balance",
                   dateColumn="DueDate", window="90d", aggregate="sum"), ctx)

    assert result.state == "blank"
    assert result.reason == "no-rows"
    assert "90d" in result.human


def test_json_watch_reads_an_object_path(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write(ctx.workspace_dir / "feed.json", json.dumps({"a": {"b": 7}}))

    result = read_source(
        {"type": "json-watch", "selector": "$.a.b", "file": str(path)}, ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 7
    assert result.as_of


def test_json_watch_reads_a_list_field(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write(ctx.workspace_dir / "feed.json", json.dumps(
        {"a": [{"n": 1}, {"n": 2}, {"n": 3}]}))

    result = read_source(
        {"type": "json-watch", "selector": "$.a[*].n", "file": str(path)}, ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 6
    assert result.bindings["count"] == 3
    assert result.bindings["points"] == [1, 2, 3]


def test_markdown_watch_counts_checkboxes_and_next_due(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write(ctx.workspace_dir / "today.md", (
        "# Today\n"
        "- [ ] Send report due: 2026-11-20\n"
        "- [x] Standup\n"
        "- [ ] Follow up due: 2026-11-18\n"
    ))

    result = read_source(
        {"type": "markdown-watch", "file": str(path)}, ctx)

    assert result.state == "ok"
    assert result.bindings["openCount"] == 2
    assert result.bindings["doneCount"] == 1
    assert result.bindings["nextDue"] == "2026-11-18"
    assert result.bindings["items"][0]["done"] is False


def test_manual_metric_reads_value_target_and_history(tmp_path):
    ctx = make_ctx(tmp_path)
    write(ctx.data_dir / "manual.json", json.dumps({
        "value": 42, "target": 50, "unit": "kg",
        "updatedAt": NOW.isoformat(timespec="seconds"),
        "history": [{"value": 40, "at": "2026-11-01"},
                    {"value": 42, "at": "2026-11-15"}],
    }))

    result = read_source({"type": "manual-metric"}, ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 42
    assert result.bindings["target"] == 50
    assert result.bindings["history"] == [40, 42]
    assert result.bindings["delta"] == 2
    assert result.bindings["lastUpdated"] == NOW.isoformat(timespec="seconds")


def test_desk_state_reads_the_injected_callback_only(tmp_path):
    ctx = make_ctx(tmp_path, desk_state={
        "runtime": lambda: {"value": 3, "status": "running"},
    })

    result = read_source({"type": "desk-state", "selector": "runtime"}, ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 3
    assert result.bindings["status"] == "running"
    assert result.as_of


def test_desk_state_without_the_callback_is_blank_naming_it(tmp_path):
    ctx = make_ctx(tmp_path)

    result = read_source({"type": "desk-state", "selector": "audit"}, ctx)

    assert result.state == "blank"
    assert result.reason == "no-desk-state"
    assert "audit" in result.human


def test_compare_emits_left_only_right_only_and_counts(tmp_path):
    ctx = make_ctx(tmp_path)
    left = write_csv(ctx.workspace_dir / "left.csv",
                     "Region,Sales\nNorth,1\nSouth,2\n")
    right = write_csv(ctx.workspace_dir / "right.csv",
                      "Region,Sales\nNorth,1\nEast,3\n")

    result = read_source({
        "type": "compare",
        "left": csv_source(left),
        "right": csv_source(right),
    }, ctx)

    assert result.state == "ok"
    assert result.bindings["leftOnly"] == ["South"]
    assert result.bindings["rightOnly"] == ["East"]
    assert result.bindings["both"] == ["North"]
    assert result.bindings["delta"] == 0
    assert result.bindings["direction"] == "flat"


def test_aggregate_sums_dependency_values(tmp_path):
    ctx = make_ctx(tmp_path)
    write_csv(ctx.workspace_dir / "one.csv", "Region,Sales\nA,10\n")
    write_csv(ctx.workspace_dir / "two.csv", "Region,Sales\nB,5\n")
    dependencies = {
        "one": {"contributes": {"widgets": [{"dataSource": csv_source(
            ctx.workspace_dir / "one.csv")}]}},
        "two": {"requires": ["one"], "contributes": {"widgets": [
            {"dataSource": csv_source(ctx.workspace_dir / "two.csv")}]}},
    }
    ctx = make_ctx(tmp_path, dependencies=dependencies, plugin_id="totals")

    result = read_source(
        {"type": "aggregate", "over": ["one", "two"]}, ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 15
    assert result.bindings["contributors"] == ["one", "two"]
    assert len(result.bindings["rows"]) == 2


def test_aggregate_defaults_to_the_plugins_requires(tmp_path):
    ctx = make_ctx(tmp_path)
    write_csv(ctx.workspace_dir / "one.csv", "Region,Sales\nA,10\n")
    dependencies = {
        "totals": {"requires": ["one"]},
        "one": {"contributes": {"widgets": [{"dataSource": csv_source(
            ctx.workspace_dir / "one.csv")}]}},
    }
    ctx = make_ctx(tmp_path, dependencies=dependencies, plugin_id="totals")

    result = read_source({"type": "aggregate"}, ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 10
    assert result.bindings["contributors"] == ["one"]


def test_aggregate_cycle_is_blank_and_names_the_ids(tmp_path):
    dependencies = {
        "a": {"requires": ["b"]},
        "b": {"requires": ["a"]},
    }
    ctx = make_ctx(tmp_path, dependencies=dependencies, plugin_id="a")

    result = read_source({"type": "aggregate", "over": ["a"]}, ctx)

    assert result.state == "blank"
    assert result.reason == "cycle"
    assert "a" in result.human and "b" in result.human


def test_aggregate_missing_dependency_is_blank_naming_the_id(tmp_path):
    ctx = make_ctx(tmp_path, dependencies={}, plugin_id="totals")

    result = read_source({"type": "aggregate", "over": ["ghost"]}, ctx)

    assert result.state == "blank"
    assert result.reason == "missing-dependency"
    assert "ghost" in result.human


def test_http_get_hashes_and_reports_changed(tmp_path):
    body = [b'{"value": 9}']

    def transport(url, timeout, max_bytes):
        return 200, {}, body[0]

    ctx = make_ctx(tmp_path, network_allow=("https://api.example.com/*",),
                   transport=transport)
    source = {"type": "http-get", "url": "https://api.example.com/data",
              "allow": ["api.example.com"]}

    first = read_source(source, ctx)
    body[0] = b'{"value": 10}'
    second = read_source(source, ctx)

    assert first.state == "ok"
    assert first.bindings["value"] == 9
    assert first.bindings["status"] == 200
    assert first.bindings["changed"] is False
    assert first.bindings["fetchedAt"]
    assert second.bindings["changed"] is True
    assert second.bindings["value"] == 10
    state = json.loads((ctx.data_dir / "http-state.json").read_text())
    assert state["https://api.example.com/data"]["sha256"]


def test_http_get_timeout_and_oversize_are_blank(tmp_path):
    def timeout(url, timeout_s, max_bytes):
        raise TimeoutError("slow")

    ctx = make_ctx(tmp_path, network_allow=("https://api.example.com/*",),
                   transport=timeout)
    source = {"type": "http-get", "url": "https://api.example.com/data",
              "allow": ["api.example.com"]}
    assert read_source(source, ctx).reason == "timeout"

    ctx = make_ctx(tmp_path, network_allow=("https://api.example.com/*",),
                   transport=lambda url, timeout_s, max_bytes: (
                       200, {}, b"x" * (257 * 1024)))
    result = read_source(source, ctx)
    assert result.state == "blank"
    assert result.reason == "oversize"


def test_http_get_host_must_be_allowlisted(tmp_path):
    called = []
    ctx = make_ctx(tmp_path, network_allow=("https://api.example.com/*",),
                   transport=lambda *args: called.append(args) or (200, {}, b"ok"))
    source = {"type": "http-get", "url": "https://evil.example.net/data",
              "allow": ["api.example.com"]}

    result = read_source(source, ctx)

    assert result.state == "blank"
    assert result.reason == "host-not-allowed"
    assert called == []


def test_excel_watch_uses_the_existing_binding_path(tmp_path):
    ctx = make_ctx(tmp_path, excel_bindings=lambda source: (
        {"status": "fresh", "cause": "", "checked_at": NOW.isoformat(),
         "state": "healthy"},
        {"delta24h": "No changes", "rowsSeen": 4, "file": "sales.xlsx"}))
    path = write(ctx.workspace_dir / "reports" / "sales.xlsx", "x")

    result = read_source(
        {"type": "excel-watch", "file": str(path)}, ctx)

    assert result.state == "ok"
    assert result.bindings["rowsSeen"] == 4
    assert result.as_of


def test_excel_watch_falls_back_to_csv_in_the_coarse_state(tmp_path):
    ctx = make_ctx(tmp_path)
    csv_path = write_csv(ctx.workspace_dir / "fallback.csv",
                         "Region,Sales\nNorth,8\nSouth,2\n")
    source = {
        "type": "excel-watch",
        "file": "${workspace}/reports/*.xlsx",
        "fallback": {
            "type": "csv-watch", "file": str(csv_path),
            "keyColumn": "Region", "valueColumn": "Sales",
        },
    }

    result = read_source(source, ctx)

    assert result.state == "coarse"
    assert result.reason == "fallback-used"
    assert str(csv_path) in result.human
    assert result.bindings["value"] == 10
    assert result.bindings["file"] == "fallback.csv"


def test_excel_fallback_with_wrong_columns_is_blank(tmp_path):
    ctx = make_ctx(tmp_path)
    csv_path = write_csv(ctx.workspace_dir / "fallback.csv",
                         "Region,Amount\nNorth,8\n")
    source = {
        "type": "excel-watch",
        "file": "${workspace}/reports/*.xlsx",
        "fallback": {
            "type": "csv-watch", "file": str(csv_path),
            "keyColumn": "Region", "valueColumn": "Sales",
        },
    }

    result = read_source(source, ctx)

    assert result.state == "blank"
    assert result.reason == "missing-file"
    assert "Sales" in result.human


@pytest.mark.parametrize("source_type,pipeline", [
    ("calendar-read", "calendar-read"),
    ("mail-digest", "mail-digest"),
    ("research-brief", "research-brief"),
])
def test_pipeline_sources_delegate(tmp_path, source_type, pipeline):
    ctx = make_ctx(tmp_path, pipeline_status=lambda requested: (
        {"status": "fresh", "cause": "", "checked_at": NOW.isoformat()},
        {"value": 1, "pipeline": requested}))
    result = read_source({"type": source_type}, ctx)
    assert result.state == "ok"
    assert result.bindings["pipeline"] == pipeline
    assert result.as_of


def test_all_twelve_sources_execute_and_carry_state_and_as_of(tmp_path):
    ctx = make_ctx(tmp_path)
    csv_path = write_csv(ctx.workspace_dir / "sales.csv",
                         "Region,Sales\nNorth,10\n")
    json_path = write(ctx.workspace_dir / "feed.json", '{"a": {"b": 1}}')
    md_path = write(ctx.workspace_dir / "todo.md", "- [ ] one\n")
    write(ctx.data_dir / "manual.json", json.dumps({
        "value": 1, "updatedAt": NOW.isoformat(timespec="seconds")}))
    xlsx = write(ctx.workspace_dir / "reports" / "sales.xlsx", "x")
    fresh = lambda requested: (
        {"status": "fresh", "cause": "", "checked_at": NOW.isoformat()},
        {"value": 1})

    cases = [
        ({"type": "excel-watch", "file": str(xlsx)}, {"excel_bindings":
            lambda source: ({"status": "fresh", "cause": "",
                             "checked_at": NOW.isoformat()}, {"value": 1})}),
        (csv_source(csv_path), {}),
        ({"type": "json-watch", "selector": "$.a.b", "file": str(json_path)}, {}),
        ({"type": "markdown-watch", "file": str(md_path)}, {}),
        ({"type": "manual-metric"}, {}),
        ({"type": "desk-state", "selector": "policy"},
         {"desk_state": {"policy": lambda: {"value": "auto"}}}),
        ({"type": "compare", "left": csv_source(csv_path),
          "right": csv_source(csv_path)}, {}),
        ({"type": "aggregate", "over": ["dep"]},
         {"plugin_id": "totals", "dependencies": {"dep": {"contributes": {
             "widgets": [{"dataSource": csv_source(csv_path)}]}}}}),
        ({"type": "http-get", "url": "https://api.example.com/data",
          "allow": ["api.example.com"]},
         {"network_allow": ("https://api.example.com/*",),
          "transport": lambda url, timeout, max_bytes: (200, {}, b"{}")}),
        ({"type": "calendar-read"}, {"pipeline_status": fresh}),
        ({"type": "mail-digest"}, {"pipeline_status": fresh}),
        ({"type": "research-brief"}, {"pipeline_status": fresh}),
    ]
    seen = set()
    for source, extra in cases:
        result = read_source(source, make_ctx(tmp_path, **extra))
        assert isinstance(result, SourceResult)
        assert result.state in STATES, source["type"]
        assert result.reason, source["type"]
        assert result.as_of, source["type"]
        assert result.human, source["type"]
        seen.add(source["type"])
    assert seen == {case[0]["type"] for case in cases}
    assert len(seen) == 12


# ---- the state matrix ----

def test_missing_csv_is_blank_with_the_path(tmp_path):
    ctx = make_ctx(tmp_path)
    missing = ctx.workspace_dir / "absent.csv"

    result = read_source(csv_source(missing), ctx)

    assert result.state == "blank"
    assert result.reason == "missing-file"
    assert str(missing) in result.human
    assert result.bindings == {}


def test_stale_csv_keeps_the_last_value_and_its_date(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write_csv(ctx.workspace_dir / "sales.csv",
                     "Region,Sales\nNorth,10\n")
    age(path, 2 * DAY)

    result = read_source(csv_source(path, window="24h"), ctx)

    assert result.state == "stale"
    assert result.reason == "older-than-window"
    assert result.bindings["value"] == 10
    assert result.as_of
    assert datetime.fromisoformat(result.as_of).date() < NOW.date()


def test_partial_csv_reports_n_of_n(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write_csv(ctx.workspace_dir / "sales.csv",
                     "Region,Sales\nNorth,10\nSouth,5\nEast\n")

    result = read_source(csv_source(path), ctx)

    assert result.state == "partial"
    assert result.reason == "partial-rows"
    assert "2 of 3" in result.human
    assert result.bindings["value"] == 15
    assert result.detail["parsedRows"] == 2


@pytest.mark.parametrize("selector", ["$.a[*]", "$..a", "$.a[0].b", "a.b"])
def test_json_selectors_outside_the_grammar_are_blank(tmp_path, selector):
    ctx = make_ctx(tmp_path)
    path = write(ctx.workspace_dir / "feed.json", '{"a": [{"b": 1}]}')

    result = read_source(
        {"type": "json-watch", "selector": selector, "file": str(path)}, ctx)

    assert result.state == "blank"
    assert result.reason == "bad-schema"


# ---- runner envelope ----

def _csv_plugin(tmp_path):
    version = tmp_path / "plugin"
    version.mkdir()
    (version / "widget.ui.json").write_text(json.dumps({
        "type": "card",
        "elements": [
            {"type": "metric", "binding": "value", "label": "Sales"},
            {"type": "list", "rowsBinding": "rows"},
        ],
    }), encoding="utf-8")
    manifest = {
        "id": "csv-widget",
        "contributes": {"widgets": [{
            "id": "csv",
            "dataSource": {
                "type": "csv-watch", "file": "${workspace}/sales.csv",
                "keyColumn": "Region", "valueColumn": "Sales",
            },
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }
    return manifest, version


def test_payload_carries_the_source_envelope_and_maps_states(tmp_path):
    runner = PluginWidgetRunner(tmp_path / "workspace")
    manifest, version = _csv_plugin(tmp_path)
    path = write_csv(tmp_path / "workspace" / "sales.csv",
                     "Region,Sales\nNorth,10\n")
    # The runner judges freshness against the real clock, so this one file
    # is stamped now rather than at the fixture clock.
    os.utime(path, None)

    status = runner.attach("p", manifest, version, tmp_path / "data")
    payload = runner.payload("p")

    assert status["status"] == "fresh"
    assert status["state"] == "ok"
    assert payload["status"] == "fresh"
    assert payload["source"] == {
        "type": "csv-watch", "value": 10, "asOf": payload["source"]["asOf"],
        "source": str(path), "state": "ok", "reason": "ok",
        "human": payload["source"]["human"], "files": [str(path)],
    }
    assert payload["source"]["asOf"]
    assert payload["elements"][0]["value"] == "10"

    age(path, 2 * DAY)
    stale = runner.payload("p")
    assert stale["status"] == "fresh"
    assert stale["source"]["state"] == "stale"
    assert stale["source"]["value"] == 10


def test_blank_payload_attention_cause_is_the_human_line(tmp_path):
    runner = PluginWidgetRunner(tmp_path / "workspace")
    manifest, version = _csv_plugin(tmp_path)

    status = runner.attach("p", manifest, version, tmp_path / "data")
    payload = runner.payload("p")
    missing = tmp_path / "workspace" / "sales.csv"

    assert status["status"] == "attention"
    assert status["cause"] == payload["source"]["human"]
    assert str(missing) in payload["source"]["human"]
    assert payload["source"]["state"] == "blank"
    assert payload["source"]["value"] is None
    assert payload["elements"] == []


def test_fake_transport_is_never_asked_for_the_network(tmp_path):
    calls = []

    def transport(url, timeout, max_bytes):
        calls.append((url, timeout, max_bytes))
        return 200, {}, b'{"value": 2}'

    runner = PluginWidgetRunner(tmp_path / "workspace", http_transport=transport)
    version = tmp_path / "plugin"
    version.mkdir()
    (version / "widget.ui.json").write_text(json.dumps({
        "type": "card", "elements": [{"type": "metric", "binding": "value"}],
    }), encoding="utf-8")
    manifest = {
        "id": "net-widget",
        "optionalPermissions": {"network": {"allow": [
            "https://api.example.com/*"]}},
        "contributes": {"widgets": [{
            "id": "net",
            "dataSource": {"type": "http-get",
                           "url": "https://api.example.com/data",
                           "allow": ["api.example.com"]},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }

    runner.attach("p", manifest, version, tmp_path / "data")
    payload = runner.payload("p")

    # attach reads once for its status, payload reads once more.
    assert len(calls) == 2
    url, timeout, max_bytes = calls[0]
    assert url == "https://api.example.com/data"
    assert timeout == 5.0
    assert max_bytes == 256 * 1024
    assert payload["source"]["state"] == "ok"
    assert payload["elements"][0]["value"] == "2"


def test_markdown_tone_flags_overdue_items(tmp_path):
    ctx = make_ctx(tmp_path)
    path = write(ctx.workspace_dir / "today.md",
                 "- [ ] Late due: 2026-11-10\n- [ ] Today due: 2026-11-15\n")

    result = read_source({"type": "markdown-watch", "file": str(path)}, ctx)

    assert result.bindings["tone"] == "attention"


def test_http_get_direction_tracks_the_numeric_value(tmp_path):
    body = [b'{"value": 9}']
    ctx = make_ctx(tmp_path, network_allow=("https://api.example.com/*",),
                   transport=lambda url, timeout, max_bytes: (200, {}, body[0]))
    source = {"type": "http-get", "url": "https://api.example.com/data",
              "allow": ["api.example.com"]}

    read_source(source, ctx)
    body[0] = b'{"value": 10}'
    up = read_source(source, ctx)
    body[0] = b'{"value": 8}'
    down = read_source(source, ctx)

    assert up.bindings["direction"] == "up"
    assert down.bindings["direction"] == "down"


def test_desk_state_merges_callback_supplied_rows(tmp_path):
    ctx = make_ctx(tmp_path, desk_state={"runtime": lambda: {
        "value": 1, "healthRows": [{"primary": "watcher", "secondary": "ok",
                                    "meta": ""}],
        "policyMode": "auto", "windowNote": "today"}})

    result = read_source({"type": "desk-state", "selector": "runtime"}, ctx)

    assert result.bindings["healthRows"][0]["primary"] == "watcher"
    assert result.bindings["policyMode"] == "auto"
    assert result.bindings["windowNote"] == "today"


# ---- validator rules ----

def test_http_get_plus_filesystem_read_is_rejected(tmp_path):
    manifest = {
        "schemaVersion": 2, "id": "both", "name": "Both",
        "version": "1.0.0", "license": "MIT",
        "permissions": {"shell": "none",
                        "filesystem": {"read": ["${workspace}/reports/*.xlsx"],
                                       "write": []},
                        "network": {"allow": []}},
        "contributes": {"widgets": [{
            "id": "both",
            "dataSource": {"type": "http-get",
                           "file": "${workspace}/reports/*.xlsx",
                           "url": "https://api.example.com/x",
                           "allow": ["api.example.com"]},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }
    verdict = validate_plugin(write_plugin(
        tmp_path, manifest, files={"widget.ui.json": '{"elements": []}'}))
    codes = [failure.code for failure in verdict.failures]
    assert "unsafe-network-filesystem" in codes


def test_json_watch_selector_is_checked_at_lint_time(tmp_path):
    manifest = dict(VALID_MANIFEST)
    manifest["contributes"] = {"widgets": [{
        "id": "w",
        "dataSource": {"type": "json-watch", "selector": "$..a",
                       "file": "${workspace}/reports/*.xlsx"},
        "render": {"type": "ui-schema", "file": "widget.ui.json"},
    }]}
    manifest["permissions"] = {"shell": "none",
                               "filesystem": {"read": ["${workspace}/reports/*.xlsx"],
                                              "write": []}}
    verdict = validate_plugin(write_plugin(tmp_path, manifest))
    assert any(f.code == "bad-schema" and "selector" in f.message
               for f in verdict.failures)


@pytest.mark.parametrize("element,needle", [
    ({"type": "sparkline", "label": "Trend"}, "pointsBinding"),
    ({"type": "table", "rowsBinding": "rows"}, "columns"),
    ({"type": "progress", "binding": "value"}, "target"),
])
def test_element_source_compatibility_is_bad_schema(tmp_path, element, needle):
    manifest = dict(VALID_MANIFEST)
    verdict = validate_plugin(write_plugin(
        tmp_path, manifest,
        files={"widget.ui.json": json.dumps({"elements": [element]})}))
    assert any(f.code == "bad-schema" and needle in f.message
               for f in verdict.failures), verdict.as_dict()


# ---- filesystem read scope at execution time ----

def test_undeclared_absolute_file_is_permission_denied(tmp_path):
    """A manifest with no read permission cannot read an absolute path."""
    ctx = make_ctx(tmp_path)
    secret = tmp_path.parent / f"{tmp_path.name}-secret.csv"
    write_csv(secret, "Region,Sales\nNorth,10\n")

    result = read_source(csv_source(secret), ctx)

    assert result.state == "blank"
    assert result.reason == "permission-denied"
    assert str(secret.resolve()) in result.human
    assert result.bindings == {}
    assert result.detail["declared"] == str(secret)


def test_relative_escape_from_the_workspace_is_permission_denied(tmp_path):
    ctx = make_ctx(tmp_path)
    write_csv(tmp_path / "secret.csv", "Region,Sales\nNorth,10\n")

    result = read_source(csv_source("../secret.csv"), ctx)

    assert result.state == "blank"
    assert result.reason == "permission-denied"


def test_declared_workspace_glob_permits_the_workspace_file(tmp_path):
    ctx = make_ctx(tmp_path, read_globs=("${workspace}/reports/*.csv",))
    path = write_csv(ctx.workspace_dir / "reports" / "sales.csv",
                     "Region,Sales\nNorth,10\n")

    result = read_source(csv_source(path), ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 10


def test_declared_plugin_data_glob_permits_the_data_file(tmp_path):
    ctx = make_ctx(tmp_path, read_globs=("${pluginData}/*.csv",))
    path = write_csv(ctx.data_dir / "sales.csv", "Region,Sales\nNorth,10\n")

    result = read_source(csv_source(path), ctx)

    assert result.state == "ok"
    assert result.bindings["value"] == 10


def test_declared_absolute_glob_permits_a_path_outside_both_roots(tmp_path):
    shared = tmp_path / "shared"
    path = write_csv(shared / "sales.csv", "Region,Sales\nNorth,10\n")

    denied = read_source(csv_source(path), make_ctx(tmp_path))
    ctx = make_ctx(tmp_path, read_globs=(str(shared / "*.csv"),))
    result = read_source(csv_source(path), ctx)

    assert denied.reason == "permission-denied"
    assert result.state == "ok"
    assert result.bindings["value"] == 10


def test_runner_attach_refuses_an_undeclared_absolute_workbook(tmp_path):
    runner = PluginWidgetRunner(tmp_path / "workspace")
    secret = tmp_path.parent / f"{tmp_path.name}-secret.xlsx"
    secret.write_bytes(b"not a workbook")
    version = tmp_path / "plugin"
    version.mkdir()
    (version / "widget.ui.json").write_text(
        '{"type": "card", "elements": []}', encoding="utf-8")
    manifest = {
        "id": "abs-widget",
        "permissions": {"filesystem": {"read": []}},
        "contributes": {"widgets": [{
            "id": "abs",
            "dataSource": {"type": "excel-watch", "file": str(secret)},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }

    status = runner.attach("p", manifest, version, tmp_path / "data")

    assert status["status"] == "attention"
    assert status["state"] == "blank"
    assert str(secret.resolve()) in status["cause"]
    assert not runner.attached("p")