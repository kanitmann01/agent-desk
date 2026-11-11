"""Manifest schema rules: required keys, types, unknown keys, manifest file."""

from .test_validator_support import VALID_MANIFEST, write_plugin
from agentdesk.validator import validate_plugin


def failures(verdict):
    return [(f.code, f.message) for f in verdict.failures]


def codes(verdict):
    return [f.code for f in verdict.failures]


def test_missing_required_key_is_bad_schema(tmp_path):
    manifest = {k: v for k, v in VALID_MANIFEST.items() if k != "name"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("bad-schema", "missing required key: name") in failures(verdict)


def test_unknown_top_level_key_is_unknown_key(tmp_path):
    manifest = {**VALID_MANIFEST, "telemetry": True}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("unknown-key", "unknown top-level key: telemetry") in failures(verdict)


def test_wrong_type_top_level_key_is_bad_schema(tmp_path):
    manifest = {**VALID_MANIFEST, "id": 7}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("bad-schema", "key 'id' must be a string") in failures(verdict)


def test_optional_permissions_may_be_absent(tmp_path):
    manifest = {k: v for k, v in VALID_MANIFEST.items() if k != "optionalPermissions"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert "bad-schema" not in codes(verdict)


def test_manifest_not_an_object_is_bad_schema(tmp_path):
    dest = write_plugin(tmp_path)
    (dest / "manifest.json").write_text("[]", encoding="utf-8")

    verdict = validate_plugin(dest)

    assert failures(verdict) == [("bad-schema", "manifest must be a JSON object")]


def test_missing_manifest_file_is_missing_file(tmp_path):
    dest = tmp_path / "empty-plugin"
    dest.mkdir()

    verdict = validate_plugin(dest)

    assert failures(verdict) == [("missing-file", "missing manifest.json")]


def test_unparseable_manifest_is_bad_json(tmp_path):
    dest = tmp_path / "broken-plugin"
    dest.mkdir()
    (dest / "manifest.json").write_text("{not json", encoding="utf-8")

    verdict = validate_plugin(dest)

    assert codes(verdict) == ["bad-json"]
    assert verdict.failures[0].message.startswith("manifest.json is not valid JSON")


def test_schema_version_must_be_one(tmp_path):
    manifest = {**VALID_MANIFEST, "schemaVersion": 2}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("bad-schema", "schemaVersion must be 1, got 2") in failures(verdict)


def test_class_must_be_declarative(tmp_path):
    manifest = {**VALID_MANIFEST, "class": "imperative"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ('bad-schema', 'class must be "declarative", got "imperative"') in failures(
        verdict
    )


def test_version_must_be_semver(tmp_path):
    manifest = {**VALID_MANIFEST, "version": "1.2"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "bad-schema",
        "version must be a semver string like 1.2.0, got '1.2'",
    ) in failures(verdict)


def test_engines_dashboard_host_must_be_nonempty_string(tmp_path):
    manifest = {**VALID_MANIFEST, "engines": {"dashboardHost": ""}}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "bad-schema",
        "engines.dashboardHost must be a nonempty string",
    ) in failures(verdict)


def test_engines_dashboard_host_missing_is_bad_schema(tmp_path):
    manifest = {**VALID_MANIFEST, "engines": {}}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "bad-schema",
        "engines.dashboardHost must be a nonempty string",
    ) in failures(verdict)


def test_license_outside_allowlist_is_bad_license(tmp_path):
    manifest = {**VALID_MANIFEST, "license": "GPL-3.0"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("bad-license", "license 'GPL-3.0' is not in the allowlist") in failures(
        verdict
    )


def test_license_allowlist_accepts_all_five(tmp_path):
    for license_id in ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"):
        manifest = {**VALID_MANIFEST, "license": license_id}

        verdict = validate_plugin(write_plugin(tmp_path, manifest))

        assert "bad-license" not in codes(verdict), license_id
