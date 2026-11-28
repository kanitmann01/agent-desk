"""Fixture-suite tests: the valid manifest passes and broken manifests fail
with their named reason. Each fixture lives in tests/fixtures/validator."""

from . import test_validator_support  # noqa: F401  (puts src/ on sys.path)
from .test_validator_support import fixture

from nexuusbot.validator import validate_plugin


def codes(verdict):
    return [f.code for f in verdict.failures]


def test_valid_manifest_passes():
    verdict = validate_plugin(fixture("valid-manifest"))

    assert verdict.ok, verdict.as_dict()
    assert verdict.failures == ()


def test_shell_permission_fixture_fails_with_named_reason():
    verdict = validate_plugin(fixture("shell-permission"))

    assert codes(verdict) == ["shell-permission"]
    assert verdict.failures[0].message == 'permissions.shell must be "none", got "cmd"'


def test_unscoped_filesystem_fixture_fails_with_named_reason():
    verdict = validate_plugin(fixture("unscoped-filesystem"))

    assert codes(verdict) == ["unscoped-filesystem"]
    assert verdict.failures[0].message == (
        "filesystem glob not rooted under ${workspace}/ or ${pluginData}: reports/*.xlsx"
    )


def test_plugin_html_fixture_fails_with_named_reason():
    verdict = validate_plugin(fixture("plugin-html"))

    assert codes(verdict) == ["plugin-html"]
    assert verdict.failures[0].message == (
        "render must not contain plugin-supplied keys: template"
    )


def test_over_permission_fixture_fails_with_named_reason():
    verdict = validate_plugin(fixture("over-permission"))

    assert codes(verdict) == ["over-permission"]
    assert verdict.failures[0].message == (
        "filesystem read glob is not referenced by any data source: "
        "${workspace}/data/*.csv"
    )


def test_hash_mismatch_fixture_fails_with_named_reason():
    verdict = validate_plugin(fixture("hash-mismatch"))

    assert codes(verdict) == ["hash-mismatch"]
    assert verdict.failures[0].message == "sha256 mismatch for widget.ui.json"


def test_release_lock_with_correct_hash_passes():
    verdict = validate_plugin(fixture("valid-with-lock"))

    assert verdict.ok, verdict.as_dict()
