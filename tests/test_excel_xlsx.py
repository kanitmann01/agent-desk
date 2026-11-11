"""Parser tests against genuine in-memory xlsx fixtures.

The parser must read what Excel writes the ordinary way: shared strings,
sparse rows, inline text, cached formula strings. Anything it cannot read
becomes WorkbookUnreadable, the amber cause, never a traceback.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.excel.core import WorkbookUnreadable
from agentdesk.excel.xlsx import parse_workbook_bytes
from excel_fixtures import make_xlsx


def test_reads_text_and_numbers_from_a_real_fixture():
    rows = parse_workbook_bytes(make_xlsx([["Product", "Units"], ["Atlas", 41.0]]))
    assert rows == [["Product", "Units"], ["Atlas", 41.0]]


def test_sparse_cells_come_back_positionally():
    rows = parse_workbook_bytes(make_xlsx([["A", None, "C"], [1.0, 2.0, 3.0]]))
    assert rows[0] == ["A", "", "C"]
    assert rows[1] == [1.0, 2.0, 3.0]


def test_column_beyond_z_is_read():
    row = [""] * 27
    row[26] = "deep"
    rows = parse_workbook_bytes(make_xlsx([row]))
    assert rows[0][26] == "deep"


def test_repeated_strings_share_one_shared_string_entry():
    rows = parse_workbook_bytes(make_xlsx([["Same", "Same"], ["Same", 1.0]]))
    assert rows == [["Same", "Same"], ["Same", 1.0]]


def test_xml_special_characters_survive():
    rows = parse_workbook_bytes(make_xlsx([['Q4 "sales" <up> & more']]))
    assert rows[0][0] == 'Q4 "sales" <up> & more'


def test_empty_workbook_yields_no_rows():
    assert parse_workbook_bytes(make_xlsx([])) == []


def test_all_empty_row_is_skipped():
    rows = parse_workbook_bytes(make_xlsx([["A"], [""], ["B"]]))
    assert rows == [["A"], ["B"]]


def test_boolean_cells_become_text():
    rows = parse_workbook_bytes(make_xlsx([[True, False]]))
    assert rows == [["TRUE", "FALSE"]]


def test_garbage_bytes_raise_unreadable_not_a_traceback():
    with pytest.raises(WorkbookUnreadable):
        parse_workbook_bytes(b"this is not a zip")


def test_zip_without_a_worksheet_raises_unreadable():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("readme.txt", "nothing spreadsheet-shaped in here")
    with pytest.raises(WorkbookUnreadable):
        parse_workbook_bytes(buffer.getvalue())
