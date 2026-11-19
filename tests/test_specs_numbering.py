"""Spec numbers are unique, and each file says which number it is.

Three branches each opened their own spec 009 before any of them merged, so
the repository ended up holding three: coupled intelligence, function
docstrings and workbook recovery. Nothing failed, because no test read the
specs directory: a reader simply had two documents answering to the same
address, and every reference to "specs/009-..." had to guess which one was
meant. The numbers are an address, so the invariant is uniqueness, and the
heading has to agree with the filename or a reader arriving from a link
cannot tell what they opened.

The first four specs predate the numbering and keep their headings as they
were written; the rule holds from 005 onwards.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1] / "specs"
LEGACY = (
    "001-agent-desk-v1.md",
    "002-memory-bank-port.md",
    "003-ui-ux-polish.md",
    "004-personal-agent-plugins.md",
)
HEADING = re.compile(r"^(\d{3})[-:]?\s")


def test_every_spec_number_belongs_to_exactly_one_file():
    numbers: dict[str, list[str]] = defaultdict(list)
    for path in sorted(SPECS.glob("*.md")):
        match = re.match(r"^(\d{3})-", path.name)
        assert match, f"{path.name} does not start with a three-digit number"
        numbers[match.group(1)].append(path.name)

    shared = {number: names for number, names in numbers.items() if len(names) > 1}
    assert not shared, f"one spec number addresses several files: {shared}"


def test_every_spec_heading_names_the_number_in_its_filename():
    for path in sorted(SPECS.glob("*.md")):
        if path.name in LEGACY:
            continue
        number = path.name[:3]
        heading = path.read_text(encoding="utf-8").splitlines()[0]
        assert number in heading, (
            f"{path.name} opens with {heading!r}, which does not name {number}"
        )
