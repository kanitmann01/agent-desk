"""Manifest schema rules: required keys, types, unknown keys, manifest file."""

import copy
import json

import pytest

from .test_validator_support import VALID_MANIFEST, write_plugin
from agentdesk.validator import validate_plugin


def failures(verdict):
    return [(f.code, f.message) for f in verdict.failures]


def codes(verdict):
    return [f.code for f in verdict.failures]


def manifest_copy():
    """A deep copy of the valid manifest, safe to mutate in a test."""
    return copy.deepcopy(VALID_MANIFEST)


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


def test_bom_prefixed_manifest_parses(tmp_path):
    """Windows-authored manifests may carry a UTF-8 BOM; that must parse."""
    dest = write_plugin(tmp_path)
    bom = b"\xef\xbb\xbf"
    (dest / "manifest.json").write_bytes(
        bom + json.dumps(manifest_copy(), indent=2).encode("utf-8")
    )

    verdict = validate_plugin(dest)

    assert verdict.ok, verdict.as_dict()


def test_unparseable_manifest_is_bad_json(tmp_path):
    dest = tmp_path / "broken-plugin"
    dest.mkdir()
    (dest / "manifest.json").write_text("{not json", encoding="utf-8")

    verdict = validate_plugin(dest)

    assert codes(verdict) == ["bad-json"]
    assert verdict.failures[0].message.startswith("manifest.json is not valid JSON")


def test_schema_version_must_be_one_or_two(tmp_path):
    manifest = {**VALID_MANIFEST, "schemaVersion": 3}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("bad-schema", "schemaVersion must be 1 or 2, got 3") in failures(verdict)

# ---- manifest v2 (T1) ----

V2_REQUIRED_VALUES = {
    "category": "finance",
    "tags": ["sales", "weekly"],
    "icon": "chart",
    "summary": "Track workbook changes at a glance.",
    "description": "A declarative widget that tracks workbook rows and changes.",
    "highlights": ["Tracks changes", "Shows deltas", "No plugin code"],
    "sample": "sample.json",
}

V2_OPTIONAL_VALUES = {
    "requires": ["other-widget"],
    "minHost": "1.0.0",
}


def v2_manifest():
    manifest = manifest_copy()
    manifest["schemaVersion"] = 2
    manifest.update(copy.deepcopy(V2_REQUIRED_VALUES))
    manifest.update(copy.deepcopy(V2_OPTIONAL_VALUES))
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


def test_v1_manifest_remains_valid(tmp_path):
    assert validate_plugin(write_plugin(tmp_path)).ok


def test_v2_full_manifest_is_valid(tmp_path):
    verdict = validate_plugin(write_v2(tmp_path))

    assert verdict.ok, verdict.as_dict()


def test_v2_optional_fields_may_be_absent(tmp_path):
    manifest = v2_manifest()
    manifest.pop("requires")
    manifest.pop("minHost")

    verdict = validate_plugin(write_v2(tmp_path, manifest))

    assert verdict.ok, verdict.as_dict()


@pytest.mark.parametrize("field", sorted(V2_REQUIRED_VALUES))
def test_v2_missing_required_field_names_the_field(tmp_path, field):
    manifest = v2_manifest()
    del manifest[field]

    verdict = validate_plugin(write_v2(tmp_path, manifest))

    assert ("bad-schema", f"missing required key: {field}") in failures(verdict)


def test_v2_only_key_at_v1_is_still_unknown_key(tmp_path):
    manifest = {**VALID_MANIFEST, "category": "finance"}

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("unknown-key", "unknown top-level key: category") in failures(verdict)


def test_unknown_key_at_v2_is_unknown_key(tmp_path):
    manifest = v2_manifest()
    manifest["telemetry"] = True

    verdict = validate_plugin(write_v2(tmp_path, manifest))

    assert ("unknown-key", "unknown top-level key: telemetry") in failures(verdict)


def test_v2_category_must_be_in_the_enum(tmp_path):
    manifest = v2_manifest()
    manifest["category"] = "legal"

    verdict = validate_plugin(write_v2(tmp_path, manifest))

    assert has(failures(verdict), "bad-schema", "category")


def test_v2_icon_must_be_in_the_enum(tmp_path):
    manifest = v2_manifest()
    manifest["icon"] = "rocket"

    verdict = validate_plugin(write_v2(tmp_path, manifest))

    assert has(failures(verdict), "bad-schema", "icon")


def test_v2_tags_are_capped_at_eight(tmp_path):
    manifest = v2_manifest()
    manifest["tags"] = [f"tag-{index}" for index in range(9)]

    verdict = validate_plugin(write_v2(tmp_path, manifest))

    assert has(failures(verdict), "bad-schema", "tags")


def test_v2_tags_must_be_unique_slugs(tmp_path):
    manifest = v2_manifest()
    manifest["tags"] = ["sales", "sales"]
    verdict = validate_plugin(write_v2(tmp_path, manifest))
    assert has(failures(verdict), "bad-schema", "tags")

    manifest = v2_manifest()
    manifest["tags"] = ["Sales Team"]
    verdict = validate_plugin(write_v2(tmp_path, manifest, files={
        "sample.json": json.dumps({"bindings": {}},
                                  ensure_ascii=False)}))
    assert has(failures(verdict), "bad-schema", "tag")


def test_v2_summary_is_required_to_be_short_and_nonempty(tmp_path):
    manifest = v2_manifest()
    manifest["summary"] = ""
    verdict = validate_plugin(write_v2(tmp_path, manifest))
    assert has(failures(verdict), "bad-schema", "summary")

    manifest = v2_manifest()
    manifest["summary"] = "x" * 121
    verdict = validate_plugin(write_v2(tmp_path, manifest))
    assert has(failures(verdict), "bad-schema", "summary")


def test_v2_description_is_capped(tmp_path):
    manifest = v2_manifest()
    manifest["description"] = "x" * 4001

    verdict = validate_plugin(write_v2(tmp_path, manifest))

    assert has(failures(verdict), "bad-schema", "description")


def test_v2_highlights_must_be_exactly_three(tmp_path):
    manifest = v2_manifest()
    manifest["highlights"] = ["one", "two"]
    verdict = validate_plugin(write_v2(tmp_path, manifest))
    assert has(failures(verdict), "bad-schema", "highlights")

    manifest = v2_manifest()
    manifest["highlights"] = ["one", "", "three"]
    verdict = validate_plugin(write_v2(tmp_path, manifest))
    assert has(failures(verdict), "bad-schema", "highlight")


def test_v2_sample_path_must_stay_relative(tmp_path):
    for sample in ("../outside.json", "/abs/sample.json", "sub\\sample.json",
                   "sample.txt"):
        manifest = v2_manifest()
        manifest["sample"] = sample

        verdict = validate_plugin(write_v2(tmp_path, manifest))

        assert has(failures(verdict), "bad-schema", "sample"), sample


def test_v2_requires_must_be_unique_safe_and_not_self(tmp_path):
    manifest = v2_manifest()
    manifest["requires"] = ["other-widget", "other-widget"]
    verdict = validate_plugin(write_v2(tmp_path, manifest))
    assert has(failures(verdict), "bad-schema", "requires")

    manifest = v2_manifest()
    manifest["requires"] = [manifest["id"]]
    verdict = validate_plugin(write_v2(tmp_path, manifest))
    assert has(failures(verdict), "bad-schema", "requires")

    manifest = v2_manifest()
    manifest["requires"] = ["../evil"]
    verdict = validate_plugin(write_v2(tmp_path, manifest))
    assert has(failures(verdict), "bad-schema", "requires")


def test_v2_min_host_must_be_nonempty(tmp_path):
    manifest = v2_manifest()
    manifest["minHost"] = ""

    verdict = validate_plugin(write_v2(tmp_path, manifest))

    assert has(failures(verdict), "bad-schema", "minHost")



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


def test_permissions_without_shell_key_is_bad_schema(tmp_path):
    manifest = manifest_copy()
    del manifest["permissions"]["shell"]

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert ("bad-schema", "permissions must declare shell") in failures(verdict)


def test_unscoped_write_glob_is_unscoped_filesystem(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["write"] = ["${home}/agent/out"]

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "unscoped-filesystem",
        "filesystem glob not rooted under ${workspace}/ or ${pluginData}: ${home}/agent/out",
    ) in failures(verdict)


def test_approved_filesystem_roots_pass(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"] = {
        "read": ["${workspace}/reports/*.xlsx", "${workspace}/notes.txt"],
        "write": ["${pluginData}", "${pluginData}/cache/*.json"],
    }

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert "unscoped-filesystem" not in codes(verdict)


def test_non_string_glob_entry_is_bad_schema(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["filesystem"]["read"] = [42]

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "bad-schema",
        "permissions.filesystem globs must be strings",
    ) in failures(verdict)


def test_nonempty_network_allow_in_permissions_is_over_permission(tmp_path):
    manifest = manifest_copy()
    manifest["permissions"]["network"]["allow"] = ["https://api.example.com/*"]

    verdict = validate_plugin(write_plugin(tmp_path, manifest))

    assert (
        "over-permission",
        "permissions.network.allow must be empty; network access belongs in optionalPermissions",
    ) in failures(verdict)


def test_schema_version_true_is_rejected_not_treated_as_1(tmp_path):
    """bool is an int subclass: True must not validate as schemaVersion 1."""
    from .test_validator_support import write_plugin

    manifest = dict(VALID_MANIFEST, schemaVersion=True)
    verdict = validate_plugin(write_plugin(tmp_path / "p", manifest))
    assert not verdict.ok
    assert "bad-schema" in [f.code for f in verdict.failures]
