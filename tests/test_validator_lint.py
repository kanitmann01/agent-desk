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


def test_ui_schema_file_without_card_type_is_bad_json(tmp_path):
    manifest = manifest_copy()

    verdict = validate_plugin(
        write_plugin(tmp_path, manifest, files={"widget.ui.json": '{"type": "list"}'})
    )

    assert failures(verdict) == [
        (
            "bad-json",
            'ui-schema file widget.ui.json must be a JSON object with "type": "card"',
        )
    ]
