"""The name is Agent Desk (spec 017 workstream 8a).

One grep, pinned: no user-visible surface carries the retired working
name. The walk covers every shipped string source: the Python package
(including the committed SPA build under server/static/spa), the tools
and launchers, the README title, and the frontend sources the SPA build
is compiled from. Case-insensitive on purpose: a mixed-case occurrence
is still the retired name on screen.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED_NAME = "nexuus"

SCAN_ROOTS = (
    ROOT / "src",
    ROOT / "tools",
    ROOT / "frontend" / "src",
)
SCAN_FILES = (
    ROOT / "README.md",
    ROOT / "frontend" / "index.html",
)
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache", ".venv"}


def _iter_files():
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
                continue
            yield path
    yield from SCAN_FILES


def test_every_surface_says_agent_desk_not_the_retired_name():
    hits = []
    for path in _iter_files():
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
