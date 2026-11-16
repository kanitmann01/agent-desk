"""Tests for scripts/license_gate.py.

The gate must fail closed: allowlisted licences pass, and everything else,
including Commons Clause, GPL, UNLICENSED and missing licence data, fails
with exit code 2 and a readable report. Malformed input is exit code 1.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "license_gate.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "license_gate"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("license_gate_under_test", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_module()


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _sbom(*components: dict) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": list(components),
    }


def _component(name: str, licence: str | None, *, scope: str = "required", **extra) -> dict:
    component: dict = {
        "type": "library",
        "name": name,
        "version": "1.0.0",
        "purl": f"pkg:generic/{name}@1.0.0",
    }
    if scope != "required":
        component["scope"] = scope
    if licence is not None:
        component["licenses"] = [{"license": {"id": licence}}]
    component.update(extra)
    return component


def _exception(value: str) -> dict:
    return {
        "properties": [
            {"name": gate.EXCEPTION_PROPERTY, "value": value},
        ]
    }


def _run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_allowlisted_components_pass() -> None:
    result = gate.evaluate(_fixture("allowed.cdx.json"))
    assert result.ok
    assert result.total == 3
    assert result.passed == 3
    assert result.failures == []


def test_banned_gpl_fails() -> None:
    result = gate.evaluate(_fixture("banned.cdx.json"))
    assert not result.ok
    assert len(result.failures) == 1
    assert "GPL" in result.failures[0].reason


def test_missing_licence_fails() -> None:
    result = gate.evaluate(_fixture("missing.cdx.json"))
    assert not result.ok
    assert len(result.failures) == 1
    assert "no licence declared" in result.failures[0].reason


def test_unlicensed_string_fails() -> None:
    result = gate.evaluate(_sbom(_component("mystery", "UNLICENSED")))
    assert not result.ok
    assert len(result.failures) == 1
    assert "UNLICENSED" in result.failures[0].reason


def test_commons_clause_fails() -> None:
    result = gate.evaluate(_fixture("commons.cdx.json"))
    assert not result.ok
    assert len(result.failures) == 1
    assert "Commons Clause" in result.failures[0].reason


def test_commons_clause_cannot_be_excepted() -> None:
    component = _component(
        "react-bits",
        "Apache-2.0",
        licenses=[{"license": {"name": "Commons Clause"}}],
        **_exception("Commons Clause"),
    )
    result = gate.evaluate(_sbom(component))
    assert not result.ok
    assert "Commons Clause" in result.failures[0].reason


def test_recorded_exception_requires_matching_property() -> None:
    without = gate.evaluate(_sbom(_component("font", "OFL-1.1")))
    assert not without.ok
    assert gate.EXCEPTION_PROPERTY in without.failures[0].reason

    with_property = gate.evaluate(
        _sbom(_component("font", "OFL-1.1", **_exception("OFL-1.1")))
    )
    assert with_property.ok
    assert with_property.excepted == 1
    assert with_property.exceptions[0].license == "OFL-1.1"


def test_exception_property_must_match_licence() -> None:
    result = gate.evaluate(
        _sbom(_component("font", "OFL-1.1", **_exception("PSF-2.0")))
    )
    assert not result.ok
    assert "needs an explicit" in result.failures[0].reason


def test_unknown_licence_cannot_be_excepted() -> None:
    result = gate.evaluate(
        _sbom(_component("weird", "WTFPL", **_exception("WTFPL")))
    )
    assert not result.ok


def test_build_only_scope_is_still_checked() -> None:
    result = gate.evaluate(
        _sbom(_component("dev-copyleft", "GPL-2.0-only", scope="excluded"))
    )
    assert not result.ok
    assert result.excluded == 1
    assert "GPL" in result.failures[0].reason


def test_spdx_expression_is_evaluated_conservatively() -> None:
    component = {
        "type": "library",
        "name": "dual",
        "version": "1.0.0",
        "licenses": [{"expression": "MIT OR GPL-3.0-only"}],
    }
    result = gate.evaluate(_sbom(component))
    assert not result.ok
    assert "GPL" in result.failures[0].reason


def test_dual_allowlisted_expression_passes() -> None:
    component = {
        "type": "library",
        "name": "dual-ok",
        "version": "1.0.0",
        "licenses": [{"expression": "MIT OR Apache-2.0"}],
    }
    assert gate.evaluate(_sbom(component)).ok


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "root must be a JSON object"),
        ({"bomFormat": "SPDX", "specVersion": "1.6", "components": []}, "bomFormat"),
        ({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}, "specVersion"),
        ({"bomFormat": "CycloneDX", "specVersion": "1.6"}, "components"),
        (
            {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": ["x"]},
            "must be an object",
        ),
    ],
)
def test_malformed_sbom_raises(document: object, message: str) -> None:
    with pytest.raises(gate.SbomError, match=message):
        gate.evaluate(document)


def test_cli_passes_with_report(tmp_path: Path) -> None:
    report = tmp_path / "license-report.txt"
    completed = _run(FIXTURES / "allowed.cdx.json", "--report", report)
    assert completed.returncode == 0, completed.stderr
    assert "RESULT: PASS" in completed.stdout
    assert report.read_text(encoding="utf-8") == completed.stdout


def test_cli_exit_2_on_policy_failure(tmp_path: Path) -> None:
    report = tmp_path / "nested" / "report.txt"
    completed = _run(FIXTURES / "commons.cdx.json", "--report", report)
    assert completed.returncode == 2
    assert "RESULT: FAIL" in completed.stdout
    assert "Commons Clause" in completed.stdout
    assert report.is_file()
    assert "FAIL" in report.read_text(encoding="utf-8")


def test_cli_exit_1_on_missing_file(tmp_path: Path) -> None:
    completed = _run(tmp_path / "does-not-exist.json")
    assert completed.returncode == 1
    assert "invalid SBOM" in completed.stderr


def test_cli_exit_1_on_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    completed = _run(bad)
    assert completed.returncode == 1
    assert "not valid JSON" in completed.stderr


def test_real_sbom_passes_if_generated() -> None:
    sbom_path = ROOT / "build" / "sbom.cdx.json"
    if not sbom_path.is_file():
        pytest.skip("build/sbom.cdx.json has not been generated")
    result = gate.evaluate(json.loads(sbom_path.read_text(encoding="utf-8")))
    assert result.ok, [failure.reason for failure in result.failures]
    assert result.total >= 6
