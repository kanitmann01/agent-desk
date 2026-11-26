"""The approved name and the banned em dash, pinned.

Nexuus Bot is the product name and the agent-face name. The README title
and the one canonical client constant carry the approved name. No live
file carries the em dash. The dated archives under docs/evidence,
docs/tickets, docs/plans, docs/ideas, docs/superpowers, docs/plugins and
the design records stay untouched.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)

NAME_ROOTS = (
    ROOT / "src",
    ROOT / "tools",
    ROOT / "scripts",
    ROOT / "docs" / "ops",
    ROOT / "frontend" / "src",
)
LIVE_ROOTS = NAME_ROOTS + (
    ROOT / "scripts",
    ROOT / "tests",
)
SCAN_FILES = (
    ROOT / "README.md",
    ROOT / "DEMO.md",
    ROOT / "frontend" / "README.md",
    ROOT / "frontend" / "package.json",
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


def test_readme_uses_the_approved_product_name():
    first_line = (ROOT / "README.md").read_text(
        encoding="utf-8", errors="replace"
    ).splitlines()[0]
    assert first_line == "# Nexuus Bot"


def test_agent_face_keeps_the_approved_name():
    source = (ROOT / "frontend" / "src" / "face" / "name.ts").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "export const AGENT_NAME = 'Nexuus Bot';" in source


def test_no_live_file_carries_the_banned_em_dash():
    """The writing rules ban the em dash; the live trees carry zero.

    The dated archives under docs/ are records of what was produced then
    and are not walked.
    """
    hits = []
    for path in _iter_files(LIVE_ROOTS, LIVE_FILES):
        rel = path.relative_to(ROOT)
        rel_posix = rel.as_posix()
        if rel_posix.startswith(ARCHIVE_DIRS) or rel_posix.startswith("docs"):
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
