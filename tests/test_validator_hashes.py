"""Hash pinning: release.lock entries must match the shipped files."""

import hashlib

from .test_validator_support import write_plugin
from agentdesk.validator import validate_plugin


def failures(verdict):
    return [(f.code, f.message) for f in verdict.failures]


def codes(verdict):
    return [f.code for f in verdict.failures]


def test_release_lock_lists_missing_file(tmp_path):
    lock = f"sha256 {'a' * 64} gone.xlsx\n"

    verdict = validate_plugin(write_plugin(tmp_path, files={"release.lock": lock}))

    assert failures(verdict) == [("missing-file", "release.lock lists missing file: gone.xlsx")]


def test_correct_multi_file_lock_passes(tmp_path):
    manifest_lock = "sha256 " + hashlib.sha256(b"{}").hexdigest() + " other/data.json\n"
    files = {
        "release.lock": manifest_lock,
        "other/data.json": "{}",
    }

    verdict = validate_plugin(write_plugin(tmp_path, files=files))

    assert "hash-mismatch" not in codes(verdict)
