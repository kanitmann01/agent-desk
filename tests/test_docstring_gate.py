"""The docstring ratchet stays green: no new gap, no stale baseline line."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "docstring_gate.py"


def _load_gate():
    """Import tools/docstring_gate.py by path so the test needs no sys.path edit."""
    spec = importlib.util.spec_from_file_location("docstring_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_passes_on_this_tree():
    """The tree carries no undocumented function outside the baseline."""
    result = subprocess.run(
        [sys.executable, str(GATE)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_gate_detects_a_missing_docstring():
    """A function without a docstring is reported by its qualified name."""
    gate = _load_gate()
    assert gate.missing_in_source("def undocumented():\n    return 1\n") == ["undocumented"]
    documented = 'def documented():\n    """Say what it does."""\n    return 1\n'
    assert gate.missing_in_source(documented) == []


def test_gate_qualifies_nested_functions():
    """Two classes with a same-named method produce two distinct keys."""
    gate = _load_gate()
    source = (
        "class A:\n    def run(self):\n        pass\n\n"
        "class B:\n    def run(self):\n        pass\n"
    )
    assert gate.missing_in_source(source) == ["A.run", "B.run"]
