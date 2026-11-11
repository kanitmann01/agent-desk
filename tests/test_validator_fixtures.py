"""Fixture-suite tests: the valid manifest passes and broken manifests fail
with their named reason. Each fixture lives in tests/fixtures/validator."""

from . import test_validator_support  # noqa: F401  (puts src/ on sys.path)
from .test_validator_support import fixture

from agentdesk.validator import validate_plugin


def test_valid_manifest_passes():
    verdict = validate_plugin(fixture("valid-manifest"))

    assert verdict.ok, verdict.as_dict()
    assert verdict.failures == ()
