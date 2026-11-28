"""A local preview of the file the user just opened.

The first rows stay on this machine. Suggestion is a separate step and
only runs when the user asks for it.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from nexuusbot.excel.xlsx import parse_workbook_file
from nexuusbot.plugins.config import ConfigError


def preview_table(path, *, sheet, header_row, range_text, limit: int = 20) -> dict:
    """Read the top of a file as a header row plus the data rows under it.

    CSV and JSON are a single sheet named after the file; a workbook reports the
    sheet names it finds, and ``sheet`` chooses which of them is reported, though the
    rows themselves come from the workbook parse, which is not sheet-aware here.
    ``limit`` caps the returned rows, not the work: a workbook is parsed whole.
    Raises ``config:missing-file``, ``config:unreadable``, ``config:not-a-table``,
    ``config:empty-table`` or ``config:bad-preview`` with a message meant for the
    person who opened the file.
    """
    candidate = Path(path)
    if not candidate.is_file():
        raise ConfigError("config:missing-file", f"That file does not exist: {candidate}")
    suffix = candidate.suffix.lower()
    if suffix == ".csv":
        grid = _csv_grid(candidate)
        sheets = [candidate.stem]
        chosen = sheets[0]
    elif suffix == ".json":
        grid = _json_grid(candidate)
        sheets = [candidate.stem]
        chosen = sheets[0]
    else:
        sheets = _sheet_names(candidate)
        chosen = sheet if sheet in sheets else (sheets[0] if sheets else "Sheet")
        grid = [[_cell(value) for value in row] for row in parse_workbook_file(candidate)]
    header_index = max(int(header_row or 1), 1) - 1
    window = _apply_range(grid, range_text)
    if header_index >= len(window):
        raise ConfigError("config:bad-preview", "That header row is past the end of the file.")
    headers = [str(cell) for cell in window[header_index]]
    body = window[header_index + 1: header_index + 1 + limit]
    rows = [[_cell(cell) for cell in row] for row in body]
    return {
        "sheets": sheets,
        "sheet": chosen,
        "headerRow": header_index + 1,
        "headers": headers,
        "rows": rows,
    }


def _cell(value) -> str:
    """Render one cell as the string the preview shows.

    Booleans print as true/false, whole floats lose their decimal point, other floats
    keep at most two decimals with trailing zeros trimmed, and None prints as an empty
    string so a missing cell reads like an empty one.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if value is None:
        return ""
    return str(value)


def _csv_grid(path: Path) -> list[list]:
    """Read a CSV into a grid of strings, accepting a UTF-8 BOM at the start.

    A file that cannot be read or decoded raises ``config:unreadable`` instead of
    surfacing the codec error.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError("config:unreadable", f"The file could not be read: {exc}")
    return [list(row) for row in csv.reader(io.StringIO(text))]


def _json_grid(path: Path) -> list[list]:
    """A JSON export as the same grid a workbook gives: headers first.

    Two shapes are tables: the array of objects an export usually is, and
    an object holding one such array under any key ({"data": [...]}). An
    array of scalars becomes a single "value" column. Anything else is
    reported in the same plain language as an unreadable workbook, never
    as a traceback.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError("config:unreadable", f"The file could not be read: {exc}")
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise ConfigError("config:unreadable", f"That file is not valid JSON: {exc}")
    records = _json_records(parsed)
    if records is None:
        raise ConfigError(
            "config:not-a-table",
            "That JSON is not a table. Open a JSON file that holds a list of objects.",
        )
    headers = []
    for record in records:
        for key in record:
            if key not in headers:
                headers.append(key)
    if not headers:
        raise ConfigError("config:empty-table", "That JSON has no rows to preview.")
    grid = [headers]
    for record in records:
        grid.append([_json_value(record.get(key)) for key in headers])
    return grid


def _json_records(parsed):
    """Find the table inside parsed JSON, or None when the document is not one.

    An array of objects is the table, an array of scalars becomes one "value"
    column, and an object is searched depth-first for the first value that is itself a
    table. Mixed arrays and objects with nothing table-shaped return None.
    """
    if isinstance(parsed, list):
        if all(isinstance(item, dict) for item in parsed):
            return parsed
        if parsed and not any(isinstance(item, (dict, list)) for item in parsed):
            return [{"value": item} for item in parsed]
        return None
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, (list, dict)):
                found = _json_records(value)
                if found:
                    return found
    return None


def _json_value(value) -> str:
    """Render one JSON value for a cell.

    Objects and arrays are serialised as compact JSON, since a preview cell has to be
    one string; everything else goes through ``_cell``.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return _cell(value)


def _sheet_names(path: Path) -> list[str]:
    """List the sheet names in a workbook without parsing its cells.

    A file that is not a readable zip or has no ``xl/workbook.xml`` reads as no
    sheets rather than an error, which is what lets the caller fall back to a default
    name.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("xl/workbook.xml")
    except (OSError, zipfile.BadZipFile, KeyError):
        return []
    names = []
    for _event, elem in ET.iterparse(io.BytesIO(raw), events=("end",)):
        if elem.tag.rsplit("}", 1)[-1] == "sheet":
            name = elem.get("name")
            if name:
                names.append(name)
            elem.clear()
    return names


def _apply_range(grid: list[list], range_text) -> list[list]:
    """Clip a grid to an A1:B10-style range.

    A range that is missing, is not a string, lacks a colon, or has an unreadable
    start corner returns the grid untouched. Rows count from 1 and either row bound may
    be omitted; the column slice applies to every kept row, so a row shorter than the
    start column contributes an empty list.
    """
    if not range_text or not isinstance(range_text, str) or ":" not in range_text:
        return grid
    start, end = range_text.split(":", 1)
    start_col, start_row = _ref(start)
    end_col, end_row = _ref(end)
    if start_col is None or end_col is None:
        return grid
    sliced = []
    for index, row in enumerate(grid, start=1):
        if start_row and index < start_row:
            continue
        if end_row and index > end_row:
            break
        sliced.append(row[start_col:end_col + 1])
    return sliced


def _ref(text: str):
    """Turn a cell reference such as B7 into a column index and a row number.

    The column is zero-based and the row one-based, matching the grid and the A1 range
    it comes from. Letters are read as a base-26 label, so AA is column 26; a
    reference with no letters yields None for the column and one with no digits yields
    None for the row.
    """
    letters = []
    digits = []
    for char in text.strip().upper():
        if char.isalpha():
            letters.append(char)
        elif char.isdigit():
            digits.append(char)
    if not letters:
        return None, None
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    row = int("".join(digits)) if digits else None
    return index - 1, row
