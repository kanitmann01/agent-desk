"""The feeder's structural privacy promise, checked over every module.

The collectors are native readers of local stores, so the whole
package, collectors included, may import a local database, a plist
parser, an XML parser, a file copier, tempfile, sys and pathlib. None
of it may import a network client, a subprocess, or the model client:
a header-only pass has no reason to leave the machine.
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _p in (str(SRC), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FEEDER = SRC / "nexuusbot" / "feeder"

# Direct imports only: a module that reaches a banned package through a
# third party is not this scan's business.
BANNED = (
    "http",
    "socket",
    "subprocess",
    "urllib",
    "requests",
    "nexuusbot.llm",
)

ALLOWED_LOCAL = (
    "sqlite3",
    "plistlib",
    "xml",
    "shutil",
    "tempfile",
    "sys",
    "pathlib",
)


def _is_banned(module: str) -> bool:
    """Whether a dotted module path names a banned package or a child."""
    return any(module == name or module.startswith(name + ".")
               for name in BANNED)


def _imported_modules(tree: ast.AST) -> list[str]:
    """Every module a parsed file imports directly, by dotted path."""
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def test_every_feeder_module_avoids_forbidden_imports():
    files = sorted(FEEDER.rglob("*.py"))
    assert files, "the feeder package must contain modules"
    offenders = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree):
            if _is_banned(module):
                offenders.append(f"{path.relative_to(ROOT)}: {module}")
    assert offenders == []


@pytest.mark.parametrize("module", ALLOWED_LOCAL)
def test_the_allowed_local_modules_are_not_banned(module):
    """The reader's local-only dependencies stay explicitly allowed."""
    assert not _is_banned(module)
