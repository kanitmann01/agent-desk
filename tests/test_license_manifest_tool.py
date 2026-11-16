"""The license manifest tool's Python 3.10 TOML fallback.

pyproject declares requires-python >=3.10 but tomllib only ships with
3.11, and the CI license gate runs on the floor so the fallback is what
actually parses there. These tests pin what the stdlib-only reader
understands and, more importantly, that it refuses rather than
misreads anything outside the pyproject subset. Where tomllib exists
the two readers must agree on that subset, byte for parsed byte.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import license_manifest  # noqa: E402  (tools/ is not a package)

PYPROJECT_SAMPLE = """\
# The reader must cope with a leading comment line.
[project]
name = "agent-desk"
version = "0.1.0"
description = "No-code personal agent web app"
license = "MIT"
requires-python = ">=3.10"
dependencies = [
    "requests>=2.31",  # pinned in pyproject
    "urllib3",
]

[tool.agent-desk-licenses]
requests = "Apache-2.0"
urllib3 = "MIT"

[tool.pytest.ini_options]
testpaths = ["tests"]
"""

SCALAR_SAMPLE = """\
[tool.demo]
enabled = true
retired = false
retries = 3
floor = 12_400
ratio = 2.5
cooling = -0.5
"""


def fallback(text: str) -> dict:
    return license_manifest._parse_toml_subset(text, "sample.toml")


def test_fallback_reads_the_project_table():
    data = fallback(PYPROJECT_SAMPLE)
    project = data["project"]
    assert project["name"] == "agent-desk"
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.10"
    assert project["dependencies"] == ["requests>=2.31", "urllib3"]


def test_fallback_reads_the_license_annotation_table():
    data = fallback(PYPROJECT_SAMPLE)
    assert data["tool"]["agent-desk-licenses"] == {
        "requests": "Apache-2.0",
        "urllib3": "MIT",
    }


def test_fallback_reads_sibling_tables_under_one_parent():
    data = fallback(PYPROJECT_SAMPLE)
    assert set(data["tool"]) == {"agent-desk-licenses", "pytest"}
    assert data["tool"]["pytest"]["ini_options"] == {"testpaths": ["tests"]}


def test_fallback_parses_booleans_and_numbers():
    demo = fallback(SCALAR_SAMPLE)["tool"]["demo"]
    assert demo == {
        "enabled": True,
        "retired": False,
        "retries": 3,
        "floor": 12400,
        "ratio": 2.5,
        "cooling": -0.5,
    }


def test_fallback_parses_string_escapes_and_literal_strings():
    data = fallback(
        '[project]\n'
        'description = "tab:\\there, quote: \\"q\\", unicode: \\u0041"\n'
        "note = 'a literal \\n stays two characters'\n"
    )
    project = data["project"]
    assert project["description"] == 'tab:\there, quote: "q", unicode: A'
    assert project["note"] == r"a literal \n stays two characters"


@pytest.mark.skipif(sys.version_info < (3, 11),
                    reason="tomllib ships with Python 3.11")
def test_fallback_agrees_with_tomllib_on_the_supported_subset():
    import tomllib
    for text in (PYPROJECT_SAMPLE, SCALAR_SAMPLE):
        assert fallback(text) == tomllib.loads(text)


def test_fallback_rejects_inline_tables():
    with pytest.raises(ValueError, match=r"sample.toml:2: inline tables"):
        fallback('[project]\nlicense = { text = "MIT" }\n')


def test_fallback_rejects_multiline_strings():
    with pytest.raises(ValueError, match=r"sample.toml:2: multiline"):
        fallback('[project]\ndescription = """spans\nlines"""\n')


def test_fallback_rejects_dotted_keys():
    with pytest.raises(ValueError, match=r"sample.toml:2: dotted keys"):
        fallback('[project]\nname.first = "Agent Desk"\n')


def test_fallback_rejects_duplicate_table_headers():
    with pytest.raises(ValueError, match=r"sample.toml:4: duplicate table"):
        fallback('[project]\nversion = "0.1.0"\n\n[project]\nversion = "0.2.0"\n')


def test_fallback_rejects_arrays_of_tables():
    with pytest.raises(ValueError, match=r"sample.toml:1: arrays of tables"):
        fallback('[[tool.agents]]\nname = "research"\n')


def test_fallback_rejects_date_values():
    with pytest.raises(ValueError, match=r"sample.toml:2: .*1979-05-27"):
        fallback("[project]\nreleased = 1979-05-27\n")


def test_fallback_rejects_lone_surrogate_escapes():
    with pytest.raises(ValueError, match=r"sample.toml:2: .*D800"):
        fallback('[project]\nname = "\\uD800"\n')


def test_load_toml_uses_the_fallback_when_tomllib_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(license_manifest, "tomllib", None)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(PYPROJECT_SAMPLE, encoding="utf-8")
    data = license_manifest._load_toml(pyproject)
    assert data["tool"]["agent-desk-licenses"]["requests"] == "Apache-2.0"


def test_load_toml_prefers_tomllib_when_available(monkeypatch, tmp_path):
    class FakeTomllib:
        def load(self, fh):
            return {"parsed": "by tomllib"}

    monkeypatch.setattr(license_manifest, "tomllib", FakeTomllib())
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(PYPROJECT_SAMPLE, encoding="utf-8")
    assert license_manifest._load_toml(pyproject) == {"parsed": "by tomllib"}


# -- the dependency list is no longer empty (ticket #94) ---------------------


def test_dual_license_annotation_is_admitted_when_every_part_is_allowed():
    violations = license_manifest.check_dependencies(
        {"cryptography": "Apache-2.0 OR BSD-3-Clause"}
    )
    assert violations == []


def test_dual_license_with_a_disallowed_part_fails():
    violations = license_manifest.check_dependencies(
        {"cryptography": "Apache-2.0 OR GPL-3.0"}
    )
    assert violations and "GPL-3.0" in violations[0]


def test_manifest_with_a_dependency_names_it_and_drops_the_zero_claim():
    rendered = license_manifest.render_manifest(
        {"cryptography": "Apache-2.0 OR BSD-3-Clause"}, "0.1.0"
    )
    assert "cryptography" in rendered
    assert "Apache-2.0 OR BSD-3-Clause" in rendered
    assert "no third-party" not in rendered
    assert "memory encryption at rest" in rendered


def test_manifest_without_dependencies_keeps_the_zero_claim():
    rendered = license_manifest.render_manifest({}, "0.1.0")
    assert "no third-party" in rendered
    assert "cryptography" not in rendered
