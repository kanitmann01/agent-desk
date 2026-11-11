"""FAILURE_CODES must cover every failure code the validator emits."""

import ast
from pathlib import Path

from . import test_validator_support  # noqa: F401  (puts src/ on sys.path)
import agentdesk.validator
from agentdesk.validator.core import FAILURE_CODES

EMITTING_MODULES = ("schema", "lint", "hashes")


def failure_code_literals(module_name: str) -> set[str]:
    """First positional string argument of every Failure(...) call in a module."""
    source = Path(agentdesk.validator.__file__).parent / f"{module_name}.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    literals = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_failure = (isinstance(func, ast.Name) and func.id == "Failure") or (
            isinstance(func, ast.Attribute) and func.attr == "Failure"
        )
        if is_failure and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                literals.add(arg.value)
    return literals


def test_every_emitted_code_is_member_of_failure_codes():
    for module_name in EMITTING_MODULES:
        literals = failure_code_literals(module_name)
        assert literals, f"scan found no Failure codes in {module_name}.py"
        unknown = literals - set(FAILURE_CODES)
        assert not unknown, (
            f"{module_name}.py emits codes missing from FAILURE_CODES: {sorted(unknown)}"
        )


def test_failure_codes_has_no_duplicates():
    assert len(FAILURE_CODES) == len(set(FAILURE_CODES))
