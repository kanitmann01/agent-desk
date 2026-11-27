"""The compatibility table: generated from the allowlist, proved complete.

Ticket 06 of Spec 032 (issue 360, stories 52 and 53 of the parent spec).
The operator document docs/ops/compatibility.md is generated from
tools/naming/allowlist.json, the same structured allowlist the naming
guard reads; it is never hand-maintained as a duplicate. These tests
fail when the committed table is stale against the allowlist, when the
table names an identifier the allowlist does not contain, and when an
allowlist entry has no row in the table.

The tests read tracked files only: no desk, no walk, no application.
"""

import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "tools" / "naming" / "allowlist.json"
TABLE = ROOT / "docs" / "ops" / "compatibility.md"
TOOL = ROOT / "tools" / "naming" / "generate_compatibility_table.py"

CATEGORIES = (
    "import-compatibility",
    "data-and-local-state",
    "environment-and-tooling",
    "browser-and-secrets",
    "wire-and-recorded-identity",
    "commands-and-launchers",
    "public-distribution",
    "compliance-metadata",
    "legal-text",
)

# A data row: the category, then the backticked identifier, then the
# context, owner and review-trigger cells.
ROW = re.compile(r"^\| ([a-z-]+) \| `([^`]+)` \| `([^`]+)` \| (.+) \| (.+) \|$")


def _generator():
    """Import the generator by path, the way the naming-guard tests do."""
    if "generate_compatibility_table" in sys.modules:
        return sys.modules["generate_compatibility_table"]
    spec = importlib.util.spec_from_file_location(
        "generate_compatibility_table", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_compatibility_table"] = module
    spec.loader.exec_module(module)
    return module


def _allowlist():
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))


def _rows(text):
    """The data rows of a table text, as their five cells."""
    rows = []
    for line in text.splitlines():
        match = ROW.match(line)
        if match:
            rows.append(tuple(group.strip() for group in match.groups()))
    return rows


def _unknown_identifiers(rows):
    """Every table row whose identifier is not in the allowlist."""
    known = {entry["identifier"] for entry in _allowlist()["entries"]}
    return sorted({identifier for _cat, identifier, _ctx, _own, _trig in rows
                   if identifier not in known})


def _entries_without_rows(rows):
    """Every allowlist entry whose (category, identifier) has no row."""
    present = Counter((category, identifier)
                      for category, identifier, _c, _o, _t in rows)
    missing = []
    for entry in _allowlist()["entries"]:
        pair = (entry["category"], entry["identifier"])
        if present[pair] <= 0:
            missing.append(pair)
        present[pair] -= 1
    return missing + [pair for pair, left in present.items() if left > 0]


def test_the_committed_table_is_the_generator_output():
    """A stale or hand-edited table fails; regenerate instead."""
    assert TABLE.is_file(), "docs/ops/compatibility.md does not exist"
    generated = _generator().build_table(_allowlist())
    committed = TABLE.read_text(encoding="utf-8")
    assert committed == generated, (
        "docs/ops/compatibility.md is not the current generator output; "
        "run python tools/naming/generate_compatibility_table.py"
    )


def test_the_table_has_one_row_per_allowlist_entry():
    """The row count and the (category, identifier) pairs match exactly."""
    entries = _allowlist()["entries"]
    rows = _rows(TABLE.read_text(encoding="utf-8"))
    assert len(rows) == len(entries), (
        f"the table has {len(rows)} rows for {len(entries)} entries"
    )
    assert Counter((category, identifier)
                   for category, identifier, _c, _o, _t in rows) == Counter(
        (entry["category"], entry["identifier"]) for entry in entries)


def test_the_table_names_only_allowlist_identifiers():
    """A planted unknown identifier is caught by the same check."""
    rows = _rows(TABLE.read_text(encoding="utf-8"))
    assert rows, "the table has no data rows"
    assert _unknown_identifiers(rows) == []
    planted = rows + [("public-distribution", "NexuusBot-installer.exe",
                       "a planted row", "nobody", "never")]
    assert _unknown_identifiers(planted) == ["NexuusBot-installer.exe"]


def test_every_allowlist_entry_has_a_row():
    """A dropped entry is caught by the same check."""
    rows = _rows(TABLE.read_text(encoding="utf-8"))
    assert _entries_without_rows(rows) == []
    assert _entries_without_rows(rows[:-1]) != [], (
        "removing a row did not fail the coverage check"
    )


def test_every_row_carries_context_owner_and_review_trigger():
    """No row may name an identifier without its contract fields."""
    for category, identifier, context, owner, trigger in _rows(
            TABLE.read_text(encoding="utf-8")):
        assert category in CATEGORIES, f"{identifier}: unknown category"
        assert context.strip(), f"{identifier}: no exact context"
        assert owner.strip(), f"{identifier}: no owner"
        assert trigger.strip(), f"{identifier}: no review trigger"
