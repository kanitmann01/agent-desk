"""Tests for scripts/sbom.py: declared Python runtime dependencies.

Every entry in [project].dependencies must become one CycloneDX
component: its licence comes from [tool.agent-desk-licenses] and its
version from the installed environment. A dependency without a licence
annotation, or one that is not installed, refuses rather than being
guessed at, and two builds of the same tree must agree byte for byte.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sbom.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbom_under_test", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sbom = _load_module()


def _pypi_components(document: dict) -> list[dict]:
    return [
        component
        for component in document["components"]
        if str(component.get("purl", "")).startswith("pkg:pypi/")
    ]


def _metadata_property(document: dict, name: str) -> str:
    for prop in document["metadata"]["properties"]:
        if prop["name"] == name:
            return prop["value"]
    raise AssertionError(f"no {name} property in the document")


def test_declared_dependency_becomes_one_licensed_component() -> None:
    document = sbom.build_sbom(ROOT)
    crypto = [c for c in document["components"] if c.get("name") == "cryptography"]
    assert len(crypto) == 1, "one component per [project].dependencies entry"
    component = crypto[0]
    assert component["version"] == importlib.metadata.version("cryptography")
    assert component["licenses"] == [{"expression": "Apache-2.0 OR BSD-3-Clause"}]
    assert component["purl"].startswith("pkg:pypi/cryptography@")
    assert component["bom-ref"] == component["purl"]
    assert component.get("scope", "required") == "required"


def test_metadata_names_the_resolved_runtime_dependencies() -> None:
    document = sbom.build_sbom(ROOT)
    value = _metadata_property(document, "agentdesk:python-runtime-dependencies")
    assert value != "none"
    assert "cryptography" in value


def test_dependency_component_records_its_upstream_licence_text() -> None:
    document = sbom.build_sbom(ROOT)
    component = next(c for c in document["components"] if c.get("name") == "cryptography")
    paths = [
        prop["value"]
        for prop in component.get("properties", [])
        if prop["name"] == sbom.LICENSE_FILE_PROPERTY
    ]
    assert paths, "a distributed component needs an upstream licence text"
    assert (ROOT / paths[0]).is_file(), paths[0]


def test_dependency_missing_from_the_licence_table_refuses() -> None:
    pyproject = {
        "project": {"dependencies": ["left-pad>=1", "urllib3"]},
        "tool": {"agent-desk-licenses": {"urllib3": "MIT"}},
    }
    with pytest.raises(SystemExit, match="left-pad") as caught:
        sbom._python_components(pyproject)
    assert "agent-desk-licenses" in str(caught.value)


def test_uninstalled_dependency_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(sbom.importlib.metadata, "version", missing)
    pyproject = {
        "project": {"dependencies": ["cryptography>=44"]},
        "tool": {"agent-desk-licenses": {"cryptography": "Apache-2.0 OR BSD-3-Clause"}},
    }
    with pytest.raises(SystemExit, match="not installed"):
        sbom._python_components(pyproject)


def test_single_licence_id_is_emitted_as_an_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sbom.importlib.metadata, "version", lambda name: "2.2.3")
    pyproject = {
        "project": {"dependencies": ["urllib3"]},
        "tool": {"agent-desk-licenses": {"urllib3": "MIT"}},
    }
    components = sbom._python_components(pyproject)
    urlli = [c for c in components if c.get("name") == "urllib3"]
    assert len(urlli) == 1
    assert urlli[0]["licenses"] == [{"license": {"id": "MIT"}}]
    assert urlli[0]["version"] == "2.2.3"


@pytest.mark.parametrize(
    ("requirement", "name"),
    [
        ("cryptography>=44", "cryptography"),
        ("urllib3", "urllib3"),
        (" requests[security]>=2.31 ", "requests"),
        ("cryptography>=44,<49", "cryptography"),
        ("pywin32; sys_platform == 'win32'", "pywin32"),
    ],
)
def test_requirement_names_read_the_bare_name(requirement: str, name: str) -> None:
    assert sbom._requirement_name(requirement) == name


def test_two_builds_are_identical_for_the_dependency_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1760000000")
    first = sbom.build_sbom(ROOT)
    second = sbom.build_sbom(ROOT)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    deps_first = _pypi_components(first)
    assert deps_first, "the dependency component must be present"
    assert deps_first == _pypi_components(second)
