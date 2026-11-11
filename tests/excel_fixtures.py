"""Build real .xlsx fixture bytes in-process.

The fixture is a genuine minimal xlsx zip: shared strings, one worksheet,
cell refs included, so the stdlib parser reads it the same way it will
read a real workbook from Excel. Entry timestamps are pinned so builds
are deterministic; nothing here writes to disk.
"""

import io
import zipfile

_FIXED_DATE = (2026, 1, 1, 0, 0, 0)

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)
_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    "<sheets><sheet name=\"Data\" sheetId=\"1\" r:id=\"rId1\" "
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>'
    "</workbook>"
)
_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
    "</Relationships>"
)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _column_letters(index: int) -> str:
    """0 -> A, 1 -> B, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def make_xlsx(rows: list[list]) -> bytes:
    """Build a minimal but genuine .xlsx from rows of str/float/None."""
    shared: list[str] = []
    shared_index: dict[str, int] = {}
    for row in rows:
        for value in row:
            if isinstance(value, str) and value not in shared_index:
                shared_index[value] = len(shared)
                shared.append(value)

    body_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_column_letters(c)}{r}"
            if isinstance(value, bool):
                cells.append(f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>')
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value!r}</v></c>')
            elif isinstance(value, str):
                if value == "":
                    continue  # empty cell: simply absent, like Excel writes
                cells.append(f'<c r="{ref}" t="s"><v>{shared_index[value]}</v></c>')
        body_rows.append(f'<row r="{r}">{"".join(cells)}</row>')

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body_rows)}</sheetData></worksheet>"
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared)}" uniqueCount="{len(shared)}">'
        f"{''.join(f'<si><t>{_xml_escape(s)}</t></si>' for s in shared)}</sst>"
    )

    entries = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _RELS,
        "xl/workbook.xml": _WORKBOOK,
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/sharedStrings.xml": shared_xml,
        "xl/worksheets/sheet1.xml": sheet,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=_FIXED_DATE)
            zf.writestr(info, content)
    return buffer.getvalue()


# A known fixture: the workbook the acceptance tests diff against.
BASE_ROWS = [
    ["Product line", "Units", "Revenue"],
    ["Atlas ERP modules", 41.0, 164000.0],
    ["Field services", 12.0, 58000.0],
    ["Care plans", 7.0, 22500.0],
]


def base_workbook() -> bytes:
    return make_xlsx(BASE_ROWS)
