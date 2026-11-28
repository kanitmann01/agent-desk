"""Docstring coverage gate: the ratchet that keeps every function documented.

The current gap is recorded in docs/docstring-baseline.txt, one "path:name"
per line. Each batch of documentation work deletes its own lines; when the
file is empty it is deleted and the gate reads as a plain check.

The gate fails in both directions: a function without a docstring that the
baseline does not list (a new gap), and a baseline line whose function now
has one (a stale line the batch must remove). Failing on stale lines is what
forces progress to be recorded instead of quietly accumulating.

Usage:
    python3 tools/docstring_gate.py                  # check, exit 1 on any gap
    python3 tools/docstring_gate.py --write-baseline # record today's gap
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "docstring-baseline.txt"

PY_ROOTS = ("src/nexuusbot", "tools", "scripts")
TS_ROOTS = ("frontend/src",)

SKIP_DIRS = {
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    ".worktrees",
    ".pytest_cache",
    "egg-info",
    ".scratch",
}

TS_SKIP_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".d.ts")
TS_SKIP_NAMES = {"routeTree.gen.ts"}
TS_SKIP_PREFIXES = ("frontend/src/test/",)
TS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "else", "do", "try",
    "function", "constructor", "new", "typeof", "case", "await", "yield",
}

TS_FUNCTION = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*[(<]"
)
TS_ARROW = re.compile(
    r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
    r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=;]+)?=>"
)
TS_METHOD = re.compile(
    r"^\s{2}(?:(?:public|private|protected|static|async|readonly|get|set|override)\s+)*"
    r"([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\([^;]*\)\s*(?::[^{;]+)?\{\s*$"
)


def _rel(path: Path) -> str:
    """Repo-relative POSIX path, the prefix of every key the gate reports."""
    return path.relative_to(ROOT).as_posix()


def _skipped(path: Path) -> bool:
    """True when a path lives in a directory the gate never reads.

    Only parts below the repo root count: the gate itself may run from a
    worktree checked out inside the ignored .worktrees directory, and matching
    against the absolute path would then skip the whole tree.
    """
    try:
        parts = path.relative_to(ROOT).parts
    except ValueError:
        parts = path.parts
    return bool(SKIP_DIRS & set(parts))


def missing_in_source(source: str, name_prefix: str = "") -> list[str]:
    """Return the qualified names of functions in one module without a docstring.

    Nested functions and methods are reported with their enclosing names, so a
    key points at exactly one function even when two classes share a method
    name. A file that does not parse raises SyntaxError; the caller decides
    whether that counts as a gate failure.
    """
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if ast.get_docstring(node) is not None:
            continue
        names = [node.name]
        parent = parents.get(node)
        while parent is not None and isinstance(
            parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            names.append(parent.name)
            parent = parents.get(parent)
        missing.append(name_prefix + ".".join(reversed(names)))
    return sorted(missing)


def collect_python() -> tuple[list[str], list[str]]:
    """Walk the Python roots and return missing keys plus unreadable files."""
    missing: list[str] = []
    broken: list[str] = []
    for root_name in PY_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if _skipped(path):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                names = missing_in_source(source)
            except (OSError, SyntaxError):
                broken.append(_rel(path))
                continue
            missing.extend(f"{_rel(path)}:{name}" for name in names)
    return sorted(missing), sorted(broken)


def _has_jsdoc(lines: list[str], index: int) -> bool:
    """True when a /** ... */ block ends just above the declaration at index."""
    cursor = index - 1
    while cursor >= 0 and not lines[cursor].strip():
        cursor -= 1
    if cursor < 0 or not lines[cursor].strip().endswith("*/"):
        return False
    while cursor >= 0:
        stripped = lines[cursor].strip()
        if stripped.startswith("/**"):
            return True
        if stripped.startswith("/*"):
            return False
        cursor -= 1
    return False


def _ts_declaration(line: str) -> str | None:
    """Return the function name declared on this line, or None."""
    for pattern in (TS_FUNCTION, TS_ARROW, TS_METHOD):
        match = pattern.match(line)
        if match:
            name = match.group(1)
            if name in TS_KEYWORDS:
                return None
            return name
    return None


def collect_typescript() -> list[str]:
    """Walk the TypeScript roots and return the keys of undocumented functions.

    The pass is regex-based on purpose: a real answer needs the TypeScript
    compiler, and depending on frontend/node_modules would make the gate
    unrunnable on a fresh checkout.
    """
    missing: list[str] = []
    for root_name in TS_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".ts", ".tsx"} or _skipped(path):
                continue
            if path.name in TS_SKIP_NAMES or path.name.endswith(TS_SKIP_SUFFIXES):
                continue
            if _rel(path).startswith(TS_SKIP_PREFIXES):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for index, line in enumerate(lines):
                name = _ts_declaration(line)
                if name and not _has_jsdoc(lines, index):
                    missing.append(f"{_rel(path)}:{name}")
    return sorted(set(missing))


def collect(include_typescript: bool = True) -> tuple[list[str], list[str]]:
    """Return every undocumented function key in scope, plus unreadable files."""
    missing, broken = collect_python()
    if include_typescript:
        missing = sorted(set(missing) | set(collect_typescript()))
    return missing, broken


def read_baseline() -> set[str]:
    """Read the recorded gap; a missing file means an empty gap."""
    if not BASELINE.exists():
        return set()
    lines = BASELINE.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def write_baseline(keys: list[str]) -> None:
    """Record keys as the new baseline, deleting the file when the gap is empty."""
    if not keys:
        if BASELINE.exists():
            BASELINE.unlink()
        return
    header = "# Functions without a docstring. Delete a line when you document it.\n"
    BASELINE.write_text(header + "\n".join(sorted(keys)) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the gate and return a process exit code."""
    parser = argparse.ArgumentParser(description="Docstring coverage gate (ratchet).")
    parser.add_argument("--write-baseline", action="store_true", help="record today's gap")
    parser.add_argument("--no-typescript", action="store_true", help="skip frontend/src")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PREFIX",
        help="drop keys under this path prefix (repeatable)",
    )
    parser.add_argument(
        "--ignore-baseline",
        action="store_true",
        help="report only undocumented functions in scope; used while a batch is open",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        metavar="PREFIX",
        help="only judge keys under this path prefix (repeatable); use while a batch is open",
    )
    args = parser.parse_args(argv)

    missing, broken = collect(include_typescript=not args.no_typescript)
    if args.scope:
        missing = [key for key in missing if key.startswith(tuple(args.scope))]
    if args.exclude:
        missing = [key for key in missing if not key.startswith(tuple(args.exclude))]

    if args.write_baseline:
        write_baseline(missing)
        print(f"baseline written: {len(missing)} undocumented functions")
        for path in broken:
            print(f"unreadable: {path}")
        return 0

    if args.ignore_baseline:
        print(f"undocumented in scope: {len(missing)}")
        for key in missing[:40]:
            print(f"  missing docstring: {key}")
        if len(missing) > 40:
            print(f"  ... and {len(missing) - 40} more")
        return 1 if missing else 0

    baseline = read_baseline()
    if args.scope:
        baseline = {key for key in baseline if key.startswith(tuple(args.scope))}
    new_gaps = [key for key in missing if key not in baseline]
    stale = sorted(baseline - set(missing))

    print(f"known gap (baseline or newly found): {len(missing)}")
    print(f"new gaps: {len(new_gaps)}")
    print(f"stale baseline lines: {len(stale)}")
    for key in new_gaps[:40]:
        print(f"  missing docstring: {key}")
    if len(new_gaps) > 40:
        print(f"  ... and {len(new_gaps) - 40} more")
    for key in stale[:40]:
        print(f"  stale baseline line (delete it): {key}")
    if len(stale) > 40:
        print(f"  ... and {len(stale) - 40} more")
    for path in broken:
        print(f"  unreadable: {path}")

    return 1 if new_gaps or stale or broken else 0


if __name__ == "__main__":
    sys.exit(main())
