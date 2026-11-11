"""Fixture-suite tests: the valid manifest passes and broken manifests fail
with their named reason. Each fixture lives in tests/fixtures/validator."""

from . import test_validator_support  # noqa: F401  (puts src/ on sys.path)
from .test_validator_support import fixture

from agentdesk.validator import validate_plugin


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
