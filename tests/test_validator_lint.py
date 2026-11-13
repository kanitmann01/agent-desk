"""Permission-lint rules beyond shell and filesystem: render, data sources,
over-permission. These use generated plugins (write_plugin) to isolate rules."""

import copy

from .test_validator_support import VALID_MANIFEST, write_plugin
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
