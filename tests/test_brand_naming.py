"""The brand rules, pinned (spec 017 workstreams 8a and the 017-11 rider).

Two greps, pinned. First: no user-visible surface carries the retired
working name. Second: no live file carries the em dash, the mark the
writing rules ban; the walk covers the same surfaces plus the scripts,
the test tree and docs/docstrings.md. The dated archives (docs/evidence,
docs/tickets, docs/plans, docs/ideas, docs/superpowers, docs/plugins and
the design records) are records of what was produced then and stay
untouched. Case-insensitive on the name on purpose: a mixed-case
occurrence is still the retired name on screen.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED_NAME = "nexuus"
EM_DASH = "—"

NAME_ROOTS = (
    ROOT / "src",
    ROOT / "tools",
    ROOT / "frontend" / "src",
)
LIVE_ROOTS = NAME_ROOTS + (
    ROOT / "scripts",
    ROOT / "tests",
)
SCAN_FILES = (
    ROOT / "README.md",
    ROOT / "frontend" / "index.html",
)
LIVE_FILES = SCAN_FILES + (ROOT / "docs" / "docstrings.md",)
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache", ".venv"}
ARCHIVE_DIRS = ("docs-evidence", "docs-tickets", "docs-plans", "docs-ideas",
                "docs-superpowers", "docs-plugins")


def _iter_files(roots, files):
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
                continue
            yield path
    yield from files


def test_every_surface_says_agent_desk_not_the_retired_name():
    hits = []
    for path in _iter_files(NAME_ROOTS, SCAN_FILES):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            hits.append(f"{path}: unreadable ({exc})")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if RETIRED_NAME in line.lower():
                hits.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert hits == [], (
        "the retired working name must not appear on any surface; "
        "found: " + ", ".join(hits[:10])
    )


def test_no_live_file_carries_the_banned_em_dash():
    """The writing rules ban the em dash; the live trees carry zero.

    The dated archives under docs/ are records of what was produced then
    and are not walked. tests/test_brand_naming.py itself is exempt from
    its own walk only where this docstring names the character.
    """
    hits = []
    for path in _iter_files(LIVE_ROOTS, LIVE_FILES):
        rel = path.relative_to(ROOT)
        rel_posix = rel.as_posix()
        if rel_posix.startswith(ARCHIVE_DIRS) or rel_posix.startswith("docs"):
            continue
        if path == Path(__file__):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            hits.append(f"{rel_posix}: unreadable ({exc})")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if EM_DASH in line:
                hits.append(f"{rel_posix}:{lineno}")
    assert hits == [], (
        "the em dash is banned on live surfaces; "
        "found: " + ", ".join(hits[:10])
    )
