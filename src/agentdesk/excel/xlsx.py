"""A minimal .xlsx reader on the standard library alone.

Scope, on purpose: first worksheet, cell values only (numbers and text,
including formula cached values), no styles, no merged-cell semantics.
That is everything the delta contract needs: rows in, rows out, values
hashed downstream. Date-styled cells surface as their serial numbers,
which is harmless for change detection. A workbook we cannot open raises
WorkbookUnreadable so the widget can say why in plain language.
"""

import io
import re
import zipfile
import xml.etree.ElementTree as ET

from agentdesk.excel.core import WorkbookUnreadable

_COLUMN = re.compile(r"([A-Z]+)")


def _local(tag: str) -> str:
    """Element local name: the spreadsheet namespaces are irrelevant here."""
    return tag.rsplit("}", 1)[-1]


def _column_index(cell_ref: str) -> int:
    """'A' -> 0, 'B' -> 1, 'AA' -> 26; 0 when the ref has no letters."""
    match = _COLUMN.match(cell_ref or "")
    if not match:
        return 0
    index = 0
    for ch in match.group(1):
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """The shared string table, in cell-index order.

    An absent part is an empty list: a workbook that keeps every string inline is
    valid and has no table.
    """
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    strings: list[str] = []
    for _event, elem in ET.iterparse(io.BytesIO(raw), events=("end",)):
        if _local(elem.tag) == "si":
            strings.append("".join(t.text or "" for t in elem.iter() if _local(t.tag) == "t"))
            elem.clear()
    return strings


_R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _declared_first_sheet(zf: zipfile.ZipFile, names: list[str]) -> str | None:
    """The first worksheet by the workbook's declared tab order.

    workbook.xml lists the tabs in display order; its rels map each
    sheet's r:id to the worksheet part. None when the declaration or the
    rels cannot be read, or when no declared sheet resolves to a part we
    carry: the caller falls back to the archive-name order.
    """
    try:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return None
    targets = {
        rel.get("Id"): rel.get("Target") or ""
        for rel in rels
        if _local(rel.tag) == "Relationship"
    }
    carried = set(names)
    for sheet in workbook.iter():
        if _local(sheet.tag) != "sheet":
            continue
        target = targets.get(sheet.get(_R_NS + "id") or "")
        if not target:
            continue
        part = target[1:] if target.startswith("/") else f"xl/{target}"
        if part in carried:
            return part
    return None


def _first_sheet_name(zf: zipfile.ZipFile) -> str:
    """The archive path of the worksheet to read.

    The workbook's declared tab order decides (a tab reorder in Excel
    keeps part names but rewrites workbook.xml); only when the
    declaration cannot be resolved does the sorted archive name pick. A
    workbook with no worksheet raises WorkbookUnreadable.
    """
    names = sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/") and n.endswith(".xml"))
    if not names:
        raise WorkbookUnreadable("no worksheet inside the workbook")
    return _declared_first_sheet(zf, names) or names[0]


def parse_workbook_bytes(data: bytes) -> list[list]:
    """Parse the first worksheet into rows of float/str values.

    File input is a trust boundary: anything malformed in the parts a
    real workbook needs (torn XML, a shared-string index pointing past
    the table) becomes WorkbookUnreadable, the amber cause, never an
    exception escaping to the page.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise WorkbookUnreadable("that file is not a .xlsx workbook") from exc
    try:
        with zf:
            shared = _read_shared_strings(zf)
            sheet_raw = zf.read(_first_sheet_name(zf))
    except WorkbookUnreadable:
        raise
    except (KeyError, ET.ParseError, IndexError, ValueError) as exc:
        raise WorkbookUnreadable("the workbook's parts could not be read") from exc

    rows: list[list] = []
    row: list = []
    inline_text: list[str] = []
    cell_index = 0
    cell_inline = False
    try:
        for event, elem in ET.iterparse(io.BytesIO(sheet_raw), events=("start", "end")):
            tag = _local(elem.tag)
            if event == "start":
                if tag == "c":
                    cell_index = _column_index(elem.get("r", ""))
                    cell_inline = elem.get("t", "") == "inlineStr"
                continue
            if tag == "t" and cell_inline:
                inline_text.append(elem.text or "")
            elif tag == "c":
                value = "".join(inline_text) if cell_inline else _cell_value(elem, shared)
                if cell_index >= len(row):
                    row.extend([""] * (cell_index + 1 - len(row)))
                row[cell_index] = value
                inline_text = []
                cell_inline = False
                elem.clear()
            elif tag == "row":
                if row and any(v != "" for v in row):
                    rows.append(row)
                row = []
                elem.clear()
    except (ET.ParseError, IndexError, ValueError) as exc:
        raise WorkbookUnreadable(f"the worksheet could not be parsed: {exc}") from exc
    return rows


def _cell_value(elem, shared: list[str]):
    """One cell's value: shared string, boolean, number, or raw text."""
    kind = elem.get("t", "n")
    if kind == "inlineStr":
        return ""  # already collected from the <is><t> children
    v = next((child for child in elem if _local(child.tag) == "v"), None)
    if v is None or v.text is None:
        return ""
    if kind == "s":
        return shared[int(v.text)]
    if kind == "b":
        return "TRUE" if v.text.strip() == "1" else "FALSE"
    try:
        return float(v.text)
    except ValueError:
        return v.text  # cached formula text, error tokens


def parse_workbook_file(path) -> list[list]:
    """Read a (shadow) workbook file and parse it."""
    from pathlib import Path

    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise WorkbookUnreadable(f"could not read {Path(path).name}") from exc
    return parse_workbook_bytes(data)
