"""CLI behavior: exit codes, human output, --json determinism, zip input,
and the identity property (CLI verdict equals library verdict)."""

import json
import zipfile

from .test_validator_support import fixture, run_cli, write_plugin


def zip_fixture(dest, source_dir):
    """Zip a plugin directory with the manifest at the zip root."""
    with zipfile.ZipFile(dest, "w") as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir).as_posix())
    return dest


def test_cli_passes_valid_fixture(tmp_path):
    result = run_cli(str(fixture("valid-manifest")))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("PASS")


def test_cli_fails_with_named_reason():
    result = run_cli(str(fixture("hash-mismatch")))
    assert result.returncode == 1
    assert "FAIL hash-mismatch:" in result.stdout
    assert "FAILED (1)" in result.stdout


def test_cli_usage_error_on_missing_path(tmp_path):
    result = run_cli(str(tmp_path / "nope"))
    assert result.returncode == 2
    assert result.stderr.strip()


def test_cli_json_is_deterministic_bytes():
    for name in ("valid-manifest", "hash-mismatch"):
        first = run_cli("--json", str(fixture(name)))
        second = run_cli("--json", str(fixture(name)))
        assert first.returncode == second.returncode
        assert first.stdout == second.stdout
        payload = json.loads(first.stdout)
        assert set(payload) == {"ok", "failures"}
        assert isinstance(payload["ok"], bool)
        for failure in payload["failures"]:
            assert set(failure) == {"code", "message"}


def test_cli_accepts_zip_input(tmp_path):
    ok_zip = zip_fixture(tmp_path / "valid.zip", fixture("valid-manifest"))
    bad_zip = zip_fixture(tmp_path / "bad.zip", fixture("hash-mismatch"))
    ok = run_cli(str(ok_zip))
    bad = run_cli(str(bad_zip))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert ok.stdout.strip().endswith("PASS")
    assert bad.returncode == 1
    assert "FAIL hash-mismatch:" in bad.stdout


def test_cli_json_matches_library_verdict(tmp_path):
    from agentdesk.validator import validate_plugin

    for name in ("valid-manifest", "hash-mismatch", "shell-permission"):
        result = run_cli("--json", str(fixture(name)))
        assert json.loads(result.stdout) == validate_plugin(fixture(name)).as_dict()


def test_cli_reports_every_failure_code_fixture():
    result = run_cli(str(fixture("shell-permission")))
    assert result.returncode == 1
    assert "FAIL shell-permission:" in result.stdout


def test_main_is_exported_and_callable():
    from agentdesk.validator import main

    assert callable(main)


def test_cli_no_arguments_is_usage_error():
    result = run_cli()
    assert result.returncode == 2
    assert result.stderr.strip()
