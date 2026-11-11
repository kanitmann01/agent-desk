"""CLI behavior: exit codes, human output, --json determinism, zip input,
and the identity property (CLI verdict equals library verdict)."""

import json
import subprocess
import sys
import zipfile

from . import test_validator_support
from .test_validator_support import VALID_MANIFEST, fixture, run_cli, write_plugin


def run_cli_decoded(*args: str) -> subprocess.CompletedProcess:
    """run_cli variant that decodes child output as UTF-8 (what main() emits)."""
    return subprocess.run(
        [sys.executable, "-m", "agentdesk.validator", *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=test_validator_support.cli_env(),
        cwd=str(test_validator_support.REPO_ROOT),
    )


def run_cli_legacy_stdio(*args: str) -> subprocess.CompletedProcess:
    """Run the CLI without the UTF-8 env overrides this dev box sets.

    The child then uses its platform pipe encoding (cp1252 on Western
    Windows), which is the deployment scenario the finding describes.
    """
    env = test_validator_support.cli_env()
    for var in ("PYTHONUTF8", "PYTHONIOENCODING"):
        env.pop(var, None)
    return subprocess.run(
        [sys.executable, "-m", "agentdesk.validator", *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(test_validator_support.REPO_ROOT),
    )


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


def test_cli_json_output_is_lf_only_bytes():
    """--json must be byte-deterministic across CI runners: LF only."""
    for name in ("valid-manifest", "hash-mismatch"):
        result = subprocess.run(
            [sys.executable, "-m", "agentdesk.validator", "--json", str(fixture(name))],
            capture_output=True,
            env=test_validator_support.cli_env(),
            cwd=str(test_validator_support.REPO_ROOT),
        )
        out = result.stdout

        assert b"\r" not in out, repr(out[-80:])
        assert out.endswith(b"\n")
        assert not out.endswith(b"\n\n")
        json.loads(out.decode("utf-8"))


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


def test_cli_accepts_uppercase_zip_suffix(tmp_path):
    ok_zip = zip_fixture(tmp_path / "valid.ZIP", fixture("valid-manifest"))

    result = run_cli(str(ok_zip))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("PASS")


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


def test_cli_cjk_unknown_key_reports_fail_not_traceback(tmp_path):
    """A cp1252 pipe must still print the verdict when a message carries CJK.

    Failure messages embed manifest strings; an unencodable stdout used to
    raise UnicodeEncodeError in the CLI child, leaving empty output.
    """
    manifest = {**VALID_MANIFEST, "遥测": True}

    result = run_cli_legacy_stdio(str(write_plugin(tmp_path / "plugin", manifest)))

    assert result.returncode == 1
    assert "FAIL unknown-key:" in result.stdout
    assert "FAILED (1)" in result.stdout
    assert "Traceback" not in result.stderr


def test_main_reconfigures_output_streams_to_utf8(tmp_path, monkeypatch):
    """main() must not lose the verdict to a non-UTF-8 stdout codec.

    In-process variant that stays deterministic on every platform: hand
    main() cp1252 TextIOWrappers and require UTF-8 bytes out.
    """
    import io

    from agentdesk.validator import cli

    out_buf, err_buf = io.BytesIO(), io.BytesIO()
    out = io.TextIOWrapper(out_buf, encoding="cp1252")
    err = io.TextIOWrapper(err_buf, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    manifest = {**VALID_MANIFEST, "遥测": True}
    exit_code = cli.main([str(write_plugin(tmp_path / "plugin", manifest))])

    out.flush()
    err.flush()
    assert exit_code == 1
    assert b"FAIL unknown-key:" in out_buf.getvalue()
    assert b"FAILED (1)" in out_buf.getvalue()
    assert err_buf.getvalue() == b""
