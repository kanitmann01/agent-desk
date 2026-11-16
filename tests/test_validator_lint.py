"""Permission-lint rules beyond shell and filesystem: render, data sources,
over-permission. These use generated plugins (write_plugin) to isolate rules."""

import copy
import json

import pytest

from .test_validator_support import REPO_ROOT, VALID_MANIFEST, write_plugin
from agentdesk.validator import validate_plugin


def failures(verdict):
    return [(f.code, f.message) for f in verdict.failures]


def codes(verdict):
    return [f.code for f in verdict.failures]


def manifest_copy():
    """A deep copy of the valid manifest, safe to mutate in a test."""
    return copy.deepcopy(VALID_MANIFEST)


def test_render_type_other_than_ui_schema_is_plugin_html(tmp_path):
    manifest = manifest_copy()
    manifest["contributes"]["widgets"][0]["render"] = {"type": "html", "file": "widget.html"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ('plugin-html', 'render.type must be "ui-schema", got "html"') in failures(
        verdict
    )


def test_render_file_not_json_is_plugin_html(tmp_path):
    manifest = manifest_copy()
    manifest["contributes"]["widgets"][0]["render"] = {"type": "ui-schema", "file": "widget.html"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "plugin-html",
        'render.file must end with .json, got "widget.html"',
    ) in failures(verdict)


def test_ui_schema_file_missing_is_missing_file(tmp_path):
    manifest = manifest_copy()
    manifest["contributes"]["widgets"][0]["render"] = {
        "type": "ui-schema",
        "file": "absent.ui.json",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "missing-file",
        "ui-schema file not found: absent.ui.json",
    ) in failures(verdict)


def test_ui_schema_file_unparseable_is_bad_json(tmp_path):
    manifest = manifest_copy()

    verdict = validate_plugin(
        write_plugin(tmp_path, manifest, files={"widget.ui.json": "{nope"})
    )

    assert codes(verdict) == ["bad-json"]
    assert verdict.failures[0].message.startswith(
        "ui-schema file widget.ui.json is not valid JSON"
    )


def test_ui_schema_file_object_without_card_type_passes(tmp_path):
    """The contract requires a parseable JSON object, nothing deeper."""
    manifest = manifest_copy()

    verdict = validate_plugin(
        write_plugin(tmp_path, manifest, files={"widget.ui.json": '{"type": "list"}'})
    )

    assert verdict.ok


def test_ui_schema_file_non_object_is_bad_json(tmp_path):
    manifest = manifest_copy()

    verdict = validate_plugin(
        write_plugin(tmp_path, manifest, files={"widget.ui.json": "[1, 2]"})
    )

    assert failures(verdict) == [
        ("bad-json", "ui-schema file widget.ui.json must be a JSON object")
    ]


def test_bom_prefixed_ui_schema_file_parses(tmp_path):
    """Windows-authored ui-schema files may carry a UTF-8 BOM."""
    dest = write_plugin(tmp_path, manifest_copy())
    (dest / "widget.ui.json").write_bytes(b'\xef\xbb\xbf{"type": "list"}')

    verdict = validate_plugin(dest)

    assert verdict.ok, verdict.as_dict()


def test_unknown_data_source_type_is_unknown_datasource(tmp_path):
    manifest = manifest_copy()
    manifest["contributes"]["widgets"][0]["dataSource"] = {
        "type": "rss-poll",
        "file": "${workspace}/reports/*.xlsx",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("unknown-datasource", "unknown dataSource.type: rss-poll") in failures(
        verdict
    )


def test_all_v1_data_source_types_pass_the_type_check(tmp_path):
    known_files = {
        "excel-watch": "${workspace}/reports/*.xlsx",
        "json-watch": "${workspace}/data/feed.json",
    }
    for source_type in ("excel-watch", "json-watch", "http-get", "calendar-read",
                        "mail-digest", "research-brief"):
        manifest = manifest_copy()
        data_source = {"type": source_type}
        if source_type in known_files:
            data_source["file"] = known_files[source_type]
            manifest["permissions"]["filesystem"]["read"] = [known_files[source_type]]
        else:
            manifest["permissions"]["filesystem"]["read"] = []
        manifest["contributes"]["widgets"][0]["dataSource"] = data_source

        verdict = validate_plugin(write_plugin(tmp_path, manifest))

        assert "unknown-datasource" not in codes(verdict), source_type


def test_read_glob_unused_by_any_data_source_is_over_permission(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = [
        "${workspace}/reports/*.xlsx",
        "${workspace}/extra/*.txt",
    ]

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "over-permission",
        "filesystem read glob is not referenced by any data source: ${workspace}/extra/*.txt",
    ) in failures(verdict)


def test_no_read_globs_and_no_file_references_is_not_over_permission(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = []
    manifest["contributes"]["widgets"][0]["dataSource"] = {"type": "http-get"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert "over-permission" not in codes(verdict)


def test_write_globs_do_not_need_data_source_references(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["write"] = ["${pluginData}", "${pluginData}/logs"]

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert "over-permission" not in codes(verdict)


def test_absolute_data_source_file_without_read_permission_is_rejected(tmp_path):
    """The repro: no read permission and an absolute path off the machine."""
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = []
    manifest["contributes"]["widgets"][0]["dataSource"] = {
        "type": "csv-watch",
        "file": "C:/Users/secret/sales.csv",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert not verdict.ok
    assert has(
        failures(verdict), "over-permission",
        "data source sales-delta reads C:/Users/secret/sales.csv")


def test_data_source_file_outside_declared_read_scope_is_rejected(tmp_path):
    manifest = manifest_copy()
    manifest["contributes"]["widgets"][0]["dataSource"] = {
        "type": "csv-watch",
        "file": "${workspace}/secrets/*.csv",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert not verdict.ok
    assert has(
        failures(verdict), "over-permission",
        "data source sales-delta reads ${workspace}/secrets/*.csv")


def test_declared_workspace_glob_covers_the_data_source_file(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = ["${workspace}/reports/*.csv"]
    manifest["contributes"]["widgets"][0]["dataSource"] = {
        "type": "csv-watch",
        "file": "${workspace}/reports/*.csv",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert verdict.ok, verdict.as_dict()


def test_declared_plugin_data_glob_covers_the_data_source_file(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = ["${pluginData}/rows.csv"]
    manifest["contributes"]["widgets"][0]["dataSource"] = {
        "type": "csv-watch",
        "file": "${pluginData}/rows.csv",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert verdict.ok, verdict.as_dict()


def test_plugin_data_dir_file_needs_no_read_glob(tmp_path):
    """Execution already permits the plugin's own data directory."""
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = []
    manifest["contributes"]["widgets"][0]["dataSource"] = {
        "type": "csv-watch",
        "file": "${pluginData}/rows.csv",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert verdict.ok, verdict.as_dict()


def test_source_types_that_ignore_the_file_field_are_not_checked(tmp_path):
    """A relative manual-metric file is a display hint, not a read scope."""
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = []
    manifest["contributes"]["widgets"][0]["dataSource"] = {
        "type": "manual-metric",
        "file": "data.json",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert verdict.ok, verdict.as_dict()


def test_absolute_manual_metric_file_without_read_permission_is_rejected(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = []
    manifest["contributes"]["widgets"][0]["dataSource"] = {
        "type": "manual-metric",
        "file": "C:/Users/secret/manual.json",
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert not verdict.ok
    assert has(
        failures(verdict), "over-permission",
        "data source sales-delta reads C:/Users/secret/manual.json")


def test_every_registry_plugin_manifest_validates():
    manifests = sorted(
        (REPO_ROOT / "registry" / "plugins").glob("*/manifest.json"))
    assert len(manifests) == 25
    for manifest_path in manifests:
        verdict = validate_plugin(manifest_path.parent)
        assert verdict.ok, (manifest_path.parent.name, verdict.as_dict())

# ---- ui-schema elements and the v2 sample (T1) ----

V2_FIELDS = {
    "category": "finance",
    "tags": ["sales"],
    "icon": "chart",
    "summary": "Track workbook changes.",
    "description": "A declarative widget that tracks workbook rows and changes.",
    "highlights": ["Tracks changes", "Shows deltas", "No plugin code"],
    "sample": "sample.json",
}


def v2_manifest():
    manifest = manifest_copy()
    manifest["schemaVersion"] = 2
    manifest.update(copy.deepcopy(V2_FIELDS))
    return manifest


def write_v2(tmp_path, manifest=None, files=None):
    merged = {
        "sample.json": json.dumps({
            "bindings": {},
            "state": "ok",
            "checkedAt": "2026-11-15T09:00:00",
        })
    }
    merged.update(files or {})
    return write_plugin(tmp_path, v2_manifest() if manifest is None else manifest,
                        merged)


def has(found, code, needle):
    return any(c == code and needle in m for c, m in found)


def test_unknown_element_kind_is_unknown_element(tmp_path):
    manifest = manifest_copy()

    verdict = validate_plugin(write_plugin(
        tmp_path, manifest,
        files={"widget.ui.json": json.dumps({
            "type": "card", "elements": [{"type": "chart", "binding": "x"}],
        })}))

    assert ("unknown-element", "unknown element kind: chart") in failures(verdict)


def test_known_element_kinds_pass(tmp_path):
    manifest = manifest_copy()
    elements = [
        {"type": "metric", "binding": "x"},
        {"type": "text", "text": "note"},
        {"type": "delta", "binding": "x"},
        {"type": "progress", "binding": "x", "target": 1},
        {"type": "list", "rowsBinding": "rows"},
        {"type": "table", "rowsBinding": "rows", "columns": []},
        {"type": "sparkline", "pointsBinding": "points"},
        {"type": "status", "binding": "x"},
        {"type": "timeline", "itemsBinding": "items"},
        {"type": "checklist", "itemsBinding": "items"},
    ]

    verdict = validate_plugin(write_plugin(
        tmp_path, manifest,
        files={"widget.ui.json": json.dumps({
            "type": "card", "elements": elements,
        })}))

    assert "unknown-element" not in codes(verdict)


def test_list_element_is_capped_at_eight_rows(tmp_path):
    manifest = v2_manifest()
    rows = [{"primary": f"row {index}"} for index in range(9)]

    verdict = validate_plugin(write_v2(
        tmp_path, manifest,
        files={
            "widget.ui.json": json.dumps({
                "type": "card",
                "elements": [{"type": "list", "rowsBinding": "rows"}],
            }),
            "sample.json": json.dumps({"bindings": {"rows": rows}}),
        }))

    assert has(failures(verdict), "bad-schema", "list")
    assert has(failures(verdict), "bad-schema", "8")


def test_table_element_is_capped_at_twenty_rows(tmp_path):
    manifest = v2_manifest()
    rows = [["cell"] for _ in range(21)]

    verdict = validate_plugin(write_v2(
        tmp_path, manifest,
        files={
            "widget.ui.json": json.dumps({
                "type": "card",
                "elements": [{"type": "table", "rowsBinding": "rows",
                              "columns": ["c"]}],
            }),
            "sample.json": json.dumps({"bindings": {"rows": rows}}),
        }))

    assert has(failures(verdict), "bad-schema", "table")
    assert has(failures(verdict), "bad-schema", "20")


def test_sparkline_element_requires_twelve_to_thirty_points(tmp_path):
    manifest = v2_manifest()
    for points in ([1] * 5, [1] * 31):
        verdict = validate_plugin(write_v2(
            tmp_path, manifest,
            files={
                "widget.ui.json": json.dumps({
                    "type": "card",
                    "elements": [{"type": "sparkline",
                                  "pointsBinding": "points"}],
                }),
                "sample.json": json.dumps({"bindings": {"points": points}}),
            }))

        assert has(failures(verdict), "bad-schema", "sparkline"), len(points)
        assert has(failures(verdict), "bad-schema", "12"), len(points)


@pytest.mark.parametrize("source_type", [
    "csv-watch", "markdown-watch", "manual-metric", "desk-state",
    "compare", "aggregate",
])
def test_new_data_source_types_pass_the_type_check(tmp_path, source_type):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = []
    manifest["contributes"]["widgets"][0]["dataSource"] = {"type": source_type}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert "unknown-datasource" not in codes(verdict), source_type


def test_v2_sample_must_exist(tmp_path):
    manifest = v2_manifest()
    dest = write_plugin(tmp_path, manifest)  # no sample.json on disk

    verdict = validate_plugin(dest)

    assert ("missing-file", "sample file not found: sample.json") in failures(verdict)


def test_v2_sample_must_be_valid_json(tmp_path):
    manifest = v2_manifest()

    verdict = validate_plugin(write_v2(
        tmp_path, manifest, files={"sample.json": "{nope"}))

    assert has(failures(verdict), "bad-json", "sample file sample.json")


def test_v2_sample_requires_a_bindings_object(tmp_path):
    manifest = v2_manifest()

    verdict = validate_plugin(write_v2(
        tmp_path, manifest,
        files={"sample.json": json.dumps({"bindings": []})}))

    assert has(failures(verdict), "bad-schema", "bindings")


def test_v2_sample_is_capped_at_32_kib(tmp_path):
    manifest = v2_manifest()
    oversized = json.dumps({"bindings": {}, "padding": "x" * 33000})

    verdict = validate_plugin(write_v2(
        tmp_path, manifest, files={"sample.json": oversized}))

    assert has(failures(verdict), "bad-sample", "32768")

