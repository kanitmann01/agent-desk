"""Generate docs/ops/compatibility.md from tools/naming/allowlist.json.

Ticket 06 of Spec 032 (issue 360, story 52 of the parent spec): the
compatibility table is an operator document naming every retained
identifier with its exact context, its owner and its review trigger.
It is generated, never hand-maintained: one row per allowlist entry,
in the allowlist's order, read from the same structured list the
naming guard reads.

    python tools/naming/generate_compatibility_table.py

Run it after editing the allowlist; the table tests fail on a stale
committed copy. The script reads two files and writes one: no desk, no
walk, no application.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / "tools" / "naming" / "allowlist.json"
TABLE = ROOT / "docs" / "ops" / "compatibility.md"

HEADER = """\
# Compatibility identifiers

The product and the agent are Nexuus Bot. The names in this table are
compatibility identifiers, not the product name and not a second
wordmark: each one is a data folder, environment variable, browser
key, wire identity, command, launcher, artifact, share, compliance or
legal contract that keeps its existing spelling so existing desks,
plugins, scripts and operator rules keep working.

This document is generated from `tools/naming/allowlist.json`, the
same structured allowlist the naming guard (`tools/naming_guard.py`)
reads. Edit the allowlist, then regenerate; a hand-edited table fails
the table tests:

    python tools/naming/generate_compatibility_table.py

One row per allowlist entry, in the allowlist's order. The exact
context column is the entry's own documented context: an identifier is
tolerated only there, never globally.

| Category | Identifier | Exact context | Owner | Review trigger |
| --- | --- | --- | --- | --- |
"""


def load_allowlist() -> dict:
    """Read the structured allowlist the guard reads."""
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))


def _cell(text: str) -> str:
    """One table cell: pipes escaped, line breaks flattened."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def build_table(data: dict) -> str:
    """The whole document text: header plus one row per entry."""
    lines = [HEADER]
    for entry in data["entries"]:
        lines.append(
            f"| {_cell(entry['category'])} "
            f"| `{_cell(entry['identifier'])}` "
            f"| `{_cell(entry['context'])}` "
            f"| {_cell(entry['owner'])} "
            f"| {_cell(entry['review_trigger'])} |\n"
        )
    return "".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Regenerate docs/ops/compatibility.md and report the row count."""
    data = load_allowlist()
    TABLE.write_text(build_table(data), encoding="utf-8", newline="\n")
    print(f"wrote {TABLE.relative_to(ROOT).as_posix()} "
          f"({len(data['entries'])} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
