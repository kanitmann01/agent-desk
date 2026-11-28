"""Shadow copy tests: the copy's own semantics.

The copy-before-parse invariant is the watcher's business (tested there);
these pin what the copy itself must guarantee: it never inherits the
source's read-only attribute, and two same-named workbooks never share
one destination.
"""

import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.excel.shadow import copy_to_shadow


def test_the_shadow_copy_drops_the_read_only_attribute(tmp_path):
    """A read-only workbook (an IT-generated report) must not turn the
    shadow copy read-only: the next poll overwrites the same copy, and a
    read-only dest would lock the watch forever with a false 'open in
    Excel' cause."""
    src = tmp_path / "Q4-sales.xlsx"
    src.write_bytes(b"placeholder workbook bytes")
    os.chmod(src, stat.S_IREAD)
    assert not (src.stat().st_mode & stat.S_IWRITE)  # the premise: read-only source
    dest = copy_to_shadow(str(src), workdir=tmp_path)
    assert dest.is_file()
    assert dest.stat().st_mode & stat.S_IWRITE  # the copy stays writable


def test_same_named_workbooks_in_different_folders_never_share_a_copy(tmp_path):
    """Two watches on same-named workbooks used to write one shared dest,
    so one could parse the other's half-written copy."""
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    folder_a.mkdir()
    folder_b.mkdir()
    (folder_a / "report.xlsx").write_bytes(b"aaa")
    (folder_b / "report.xlsx").write_bytes(b"bbb")
    first = copy_to_shadow(str(folder_a / "report.xlsx"), workdir=tmp_path)
    second = copy_to_shadow(str(folder_b / "report.xlsx"), workdir=tmp_path)
    assert first != second
    assert first.read_bytes() == b"aaa"
    assert second.read_bytes() == b"bbb"
