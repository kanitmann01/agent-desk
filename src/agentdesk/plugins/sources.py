"""Read the twelve declarative plugin data sources into honest states.

Every reader is a pure function of its inputs plus the files it is
allowed to read: no globals, no host callbacks beyond the ones the
SourceContext injects, and no exceptions that escape (a broken source
is a blank state with a reason, never a crash). The output is a
SourceResult whose state is one of the five honest states in STATES
and whose reason is a stable machine slug the UI can key on. human is
the one sentence a card shows.

The state vocabulary is deliberately small:

    ok      a complete, current read
    stale   a complete read older than its declared window; the last
            good value and its date are still bound
    blank   nothing real to show (missing file, connection, selector)
    coarse  a declared fallback was used instead of the primary source
    partial only some of the rows parsed ("n of N")

A blank never binds a zero: the bindings dict is empty, so the render
layer shows nothing rather than an invented number.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from fnmatch import fnmatch
from glob import glob
from pathlib import Path
from urllib.parse import urlsplit

STATES = ("ok", "stale", "blank", "coarse", "partial")

DEFAULT_WINDOW = "24h"
HTTP_TIMEOUT_DEFAULT = 5.0
HTTP_TIMEOUT_CAP = 15.0
HTTP_MAX_BYTES = 256 * 1024

# Source types a compare/aggregate expression may nest. Network sources
# are deliberately absent: a local comparison must not be able to turn
# into an outbound call.
LOCAL_TYPES = (
    "excel-watch", "csv-watch", "json-watch", "markdown-watch",
    "manual-metric", "desk-state", "compare", "aggregate",
    "calendar-read", "mail-digest", "outlook-brief", "research-brief",
)

_JSON_OBJECT = re.compile(r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
_JSON_LIST = re.compile(
    r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*)+\[\*\]\.[A-Za-z_][A-Za-z0-9_]*$")
_JSON_PATH_PART = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)")
_WINDOW = re.compile(r"^(\d+)([hdwm])$")
_CHECKBOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$")
_DUE = re.compile(r"due:\s*([^\s)]+)", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class SourceContext:
    """Everything a reader may touch, injected by the host.

    excel_bindings keeps the existing ExcelWatch binding path
    byte-identical: the runner hands the reader the same (status,
    bindings) pair it used before. pipeline_status does the same for
    calendar-read, mail-digest and research-brief.
    """

    plugin_id: str
    workspace_dir: Path
    data_dir: Path
    now: datetime
    transport: object = None
    dependencies: dict | None = None
    desk_state: object = None
    history: object = None
    excel_bindings: object = None
    pipeline_status: object = None
    network_allow: tuple = ()
    read_globs: tuple = ()
    visiting: tuple = ()


@dataclass
class SourceResult:
    state: str
    reason: str
    human: str
    as_of: str
    source: str
    bindings: dict = field(default_factory=dict)
    files: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def _result(state, reason="", human="", as_of="", source="",
            bindings=None, files=None, detail=None) -> SourceResult:
    return SourceResult(
        state=state,
        reason=reason,
        human=human,
        as_of=as_of,
        source=source,
        bindings=dict(bindings or {}),
        files=list(files or []),
        detail=dict(detail or {}),
    )


def _blank(reason: str, human: str, source: str = "", files=None,
           detail=None) -> SourceResult:
    return _result("blank", reason, human, "", source, {}, files, detail)


def _now_iso(ctx: SourceContext) -> str:
    return ctx.now.isoformat(timespec="seconds")


def read_source(source: dict, ctx: SourceContext) -> SourceResult:
    """Read one declared data source; never raises."""
    if not isinstance(source, dict):
        return _blank("bad-schema", "The data source declaration is not an object.")
    source_type = str(source.get("type", ""))
    reader = _READERS.get(source_type)
    if reader is None:
        return _blank("unknown-source",
                      f"The source type {source_type or '(none)'} is not executable.")
    try:
        return reader(source, ctx)
    except _PermissionDenied as denied:
        return _blank(
            "permission-denied",
            f"The plugin may not read {denied.path}: it is outside the "
            f"workspace and the plugin's data directory, and no declared "
            f"read glob covers {denied.declared}.",
            source=denied.path, detail={"declared": denied.declared})
    except Exception as exc:  # noqa: BLE001 - a source read must never crash
        return _blank("source-error",
                      f"The {source_type} source could not be read: {exc}.",
                      detail={"exception": type(exc).__name__})


class _PermissionDenied(Exception):
    """A requested path that no declared read scope covers."""

    def __init__(self, declared: str, path: str) -> None:
        super().__init__(f"not permitted: {path}")
        self.declared = declared
        self.path = path


def _expand(path, ctx: SourceContext) -> Path:
    text = str(path).replace("${workspace}", str(ctx.workspace_dir))
    text = text.replace("${pluginData}", str(ctx.data_dir))
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = Path(ctx.workspace_dir) / candidate
    return candidate


def _inside(path: Path, root) -> bool:
    try:
        Path(path).relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _permitted(path: Path, ctx: SourceContext) -> bool:
    """Inside a host root, or covered by a declared read glob."""
    if _inside(path, ctx.workspace_dir) or _inside(path, ctx.data_dir):
        return True
    for declared in ctx.read_globs or ():
        if isinstance(declared, str) and fnmatch(
                str(path), str(_expand(declared, ctx))):
            return True
    return False


def _resolve(path, ctx: SourceContext) -> Path:
    candidate = _expand(path, ctx).resolve()
    if not _permitted(candidate, ctx):
        raise _PermissionDenied(str(path), str(candidate))
    return candidate


def _first_match(pattern, ctx: SourceContext):
    """The first permitted file matching a declared glob (or the path itself)."""
    if not pattern:
        return None
    expanded = _expand(pattern, ctx)
    if any(char in str(expanded) for char in "*?["):
        matches = sorted(glob(str(expanded), recursive=True))
        for match in matches:
            candidate = Path(match).resolve()
            if _permitted(candidate, ctx):
                return candidate
        if matches:
            raise _PermissionDenied(str(pattern), str(matches[0]))
        if not _permitted(expanded.resolve(), ctx):
            raise _PermissionDenied(str(pattern), str(expanded))
        return None
    resolved = _resolve(pattern, ctx)
    return resolved if resolved.exists() else None


def first_permitted_match(declared, ctx: SourceContext):
    """The first permitted match for a declared glob, or None when denied."""
    try:
        return _first_match(declared, ctx)
    except _PermissionDenied:
        return None


def window_seconds(value, default: float = 86400.0) -> float:
    text = str(value or "").strip().lower()
    if text in ("daily", "day"):
        return 86400.0
    if text in ("weekly", "week"):
        return 7 * 86400.0
    if text in ("monthly", "month"):
        return 30 * 86400.0
    match = _WINDOW.match(text)
    if not match:
        return default
    amount, unit = int(match.group(1)), match.group(2)
    return amount * {"h": 3600.0, "d": 86400.0,
                     "w": 7 * 86400.0, "m": 30 * 86400.0}[unit]


def _stale(path: Path, window, now: datetime) -> bool:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return False
    return (now - mtime).total_seconds() > window_seconds(window)


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(
            timespec="seconds")
    except OSError:
        return ""


def _parse_ts(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def cell_date(value):
    """A calendar date from one spreadsheet or CSV cell, or None.

    Spreadsheet readers surface date cells as Excel serial numbers
    because they read no styles, so a serial in a plausible range is
    converted; ISO text and the common day-first and month-first text
    formats parse too. Anything unrecognisable returns None so callers
    can treat the cell as undated rather than guess.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        serial = float(value)
        if 20000 <= serial <= 80000:
            return datetime(1899, 12, 30) + timedelta(days=serial)
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
                "%m-%d-%Y", "%d %b %Y", "%b %d, %Y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _relative_day(when, now: datetime) -> str:
    """The human age of a dated row: overdue, due soon, or due today."""
    if when is None:
        return ""
    days = (now.date() - when.date()).days
    if days > 0:
        return f"{days} day{'s' if days != 1 else ''} overdue"
    if days < 0:
        ahead = -days
        return f"due in {ahead} day{'s' if ahead != 1 else ''}"
    return "due today"


def _older_than_iso(value, window, now: datetime) -> bool:
    parsed = _parse_ts(value)
    if parsed is None:
        return False
    seconds = window_seconds(window)
    try:
        return (now - parsed).total_seconds() > seconds
    except TypeError:
        return (now.replace(tzinfo=None)
                - parsed.replace(tzinfo=None)).total_seconds() > seconds


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scalar(value):
    if isinstance(value, bool):
        return value
    number = _number(value)
    if number is not None:
        return int(number) if number.is_integer() else number
    return value


def _rows_from_mapping(mapping, limit=40):
    return [{"primary": str(key), "secondary": str(value), "meta": ""}
            for key, value in list(mapping.items())[:limit]]


def _points(values, limit=30):
    numbers = [_number(value) for value in values]
    numbers = [number for number in numbers if number is not None]
    return [int(n) if n.is_integer() else n for n in numbers[-limit:]]


def _table_from_rows(rows):
    return [[row.get("primary", ""), row.get("secondary", ""),
             row.get("meta", "")] for row in rows]


# ---- excel-watch (legacy binding path, plus a declared CSV fallback) ----

def _excel_watch(source, ctx: SourceContext) -> SourceResult:
    declared = source.get("file", "")
    primary = _first_match(declared, ctx)
    if primary is None:
        fallback = source.get("fallback")
        if isinstance(fallback, dict):
            return _excel_fallback(source, fallback, ctx)
        return _blank(
            "missing-file",
            f"no file matches {declared}",
            source=str(declared),
            detail={"declared": declared})

    if ctx.excel_bindings is None:
        return _blank("excel-unavailable",
                      "The Excel watcher is not available for this source.",
                      source=str(primary), files=[str(primary)])
    status, bindings = ctx.excel_bindings(source)
    fresh = str(status.get("status", "")) == "fresh"
    return _result(
        "ok" if fresh else "blank",
        "ok" if fresh else str(
            status.get("reason") or status.get("state") or "attention"),
        (f"Read the workbook {primary}." if fresh else
         str(status.get("cause") or "the workbook needs attention")),
        _now_iso(ctx) if fresh else str(status.get("checked_at", "")),
        str(primary),
        bindings,
        [str(primary)],
        {"file": str(primary), "rawState": status.get("state", "")})


def _excel_fallback(source, fallback, ctx: SourceContext) -> SourceResult:
    columns = (fallback.get("keyColumn"), fallback.get("valueColumn"))
    if fallback.get("type") != "csv-watch" or not all(columns):
        return _blank(
            "missing-file",
            f"no file matches {source.get('file', '')}",
            source=str(source.get("file", "")),
            detail={"declared": source.get("file", "")})
    result = read_source(fallback, ctx)
    if result.state == "blank":
        return _blank(
            "missing-file",
            f"no file matches {source.get('file', '')}; the declared CSV "
            f"fallback {fallback.get('file', '')} could not be read either: "
            f"{result.human}",
            source=str(source.get("file", "")),
            files=result.files,
            detail={"fallbackReason": result.reason})
    bindings = dict(result.bindings)
    bindings.setdefault("file", Path(result.source).name)
    return _result(
        "coarse",
        "fallback-used",
        f"Using the declared CSV fallback at {result.source} because the "
        f"workbook matching {source.get('file', '')} is missing.",
        result.as_of,
        result.source,
        bindings,
        result.files,
        {"fallback": "csv-watch", "primary": source.get("file", ""),
         "fallbackFile": result.source})


# ---- csv-watch ----

def _csv_watch(source, ctx: SourceContext) -> SourceResult:
    declared = source.get("file", "")
    path = _first_match(declared, ctx)
    if path is None:
        target = _resolve(declared, ctx)
        return _blank(
            "missing-file", f"The data file {target} does not exist yet.",
            source=str(target), detail={"declared": declared})
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return _blank("unreadable", f"The file {path} could not be read: {exc}.",
                      source=str(path), files=[str(path)])

    delimiter = str(source.get("delimiter", ",")) or ","
    try:
        records = [row for row in csv.reader(io.StringIO(text),
                                             delimiter=delimiter)]
    except csv.Error as exc:
        return _blank("bad-json", f"The CSV file {path} did not parse: {exc}.",
                      source=str(path), files=[str(path)])
    records = [row for row in records if any(cell.strip() for cell in row)]
    if not records:
        return _blank("empty-file", f"The CSV file {path} is empty.",
                      source=str(path), files=[str(path)])
    header = [cell.strip() for cell in records[0]]
    key_name = str(source.get("keyColumn", ""))
    value_name = str(source.get("valueColumn", ""))
    date_name = str(source.get("dateColumn", "") or "").strip()
    lower = [cell.lower() for cell in header]
    declared = [name for name in (key_name, value_name, date_name) if name]
    missing = [name for name in declared if name.lower() not in lower]
    if missing:
        return _blank(
            "bad-schema",
            f"The CSV file {path} is missing the column(s) "
            f"{', '.join(missing)}.",
            source=str(path), files=[str(path)],
            detail={"columns": header})
    key_at = lower.index(key_name.lower())
    value_at = lower.index(value_name.lower())
    date_at = lower.index(date_name.lower()) if date_name else None
    mode = str(source.get("aggregate", "sum")).lower()
    if mode not in ("sum", "count", "latest", "min", "max"):
        mode = "sum"

    total = len(records) - 1
    parsed = []
    for row in records[1:]:
        if len(row) != len(header):
            continue
        key = row[key_at].strip()
        raw_value = row[value_at].strip()
        number = _number(raw_value)
        if mode != "count" and number is None:
            continue
        when = cell_date(row[date_at]) if date_at is not None else None
        parsed.append((key, raw_value, number, when))
    if not parsed:
        return _blank("no-rows",
                      f"The CSV file {path} has no valid rows.",
                      source=str(path), files=[str(path)])

    # An optional dateColumn plus a window narrows both the rows and the
    # aggregate to the window. Undated rows stay in: dropping them would
    # silently lose data the file really holds.
    window = source.get("window")
    cutoff_date = None
    if date_at is not None and window:
        cutoff_date = (ctx.now
                       - timedelta(seconds=window_seconds(window))).date()
    selected = [item for item in parsed
                if cutoff_date is None or item[3] is None
                or item[3].date() >= cutoff_date]
    if not selected and mode != "count":
        return _blank(
            "no-rows",
            f"No rows in the CSV file {path} fall inside the "
            f"{window or DEFAULT_WINDOW} window.",
            source=str(path), files=[str(path)],
            detail={"columns": header, "dateColumn": date_name})

    values = [number for _, _, number, _ in selected if number is not None]
    if mode == "count":
        value = len(selected)
    elif not values:
        return _blank("no-rows", f"The CSV file {path} has no numeric values.",
                      source=str(path), files=[str(path)])
    elif mode == "sum":
        value = sum(values)
    elif mode == "latest":
        value = values[-1]
    elif mode == "min":
        value = min(values)
    else:
        value = max(values)
    if isinstance(value, float) and value.is_integer():
        value = int(value)

    stale = _stale(path, source.get("window", DEFAULT_WINDOW), ctx.now)
    if stale:
        state, reason = "stale", "older-than-window"
        human = (f"The file {path} has not changed since "
                 f"{_mtime_iso(path)}; showing its last good value.")
    elif len(parsed) < total:
        state, reason = "partial", "partial-rows"
        human = (f"{len(parsed)} of {total} rows parsed; the rest were "
                 f"malformed and skipped.")
    else:
        state, reason = "ok", "ok"
        human = f"Read {len(selected)} rows from {path}."
    rows = [{"primary": key, "secondary": raw,
             "meta": _relative_day(when, ctx.now)}
            for key, raw, _, when in selected]
    bindings = {
        "value": value,
        "count": len(selected),
        "rowsSeen": len(selected),
        "rows": rows,
        "table": _table_from_rows(rows),
        "points": _points([raw for _, raw, _, _ in selected]),
        "file": path.name,
        "columns": header,
    }
    return _result(state, reason, human, _mtime_iso(path), str(path),
                   bindings, [str(path)],
                   {"totalRows": total, "parsedRows": len(parsed),
                    "windowedRows": len(selected),
                    "aggregate": mode,
                    "dateColumn": date_name,
                    "window": source.get("window", DEFAULT_WINDOW)})


# ---- json-watch (mini selector grammar: $.a.b and $.a[*].n) ----

def selector_valid(selector) -> bool:
    return isinstance(selector, str) and bool(
        _JSON_OBJECT.match(selector) or _JSON_LIST.match(selector))


def _json_select(document, selector: str):
    if _JSON_LIST.match(selector):
        path_part, field = selector.rsplit("[*].", 1)
        found, node = _json_walk(document, path_part)
        if not found or not isinstance(node, list):
            return False, []
        values = [item.get(field) for item in node if isinstance(item, dict)
                  and field in item]
        return True, values
    found, node = _json_walk(document, selector)
    return (True, node) if found else (False, None)


def _json_walk(document, path_part: str):
    node = document
    for key in _JSON_PATH_PART.findall(path_part):
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
    return True, node


def _json_watch(source, ctx: SourceContext) -> SourceResult:
    selector = source.get("selector", "")
    if not selector_valid(selector):
        return _blank(
            "bad-schema",
            f"The JSON selector {selector or '(none)'} is not one of the "
            "supported forms $.a.b or $.a[*].n.")
    declared = source.get("file", "")
    path = _first_match(declared, ctx)
    if path is None:
        return _blank(
            "missing-file", f"The data file {declared} does not exist yet.",
            source=str(declared), detail={"declared": declared})
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _blank("bad-json", f"The file {path} did not parse: {exc}.",
                      source=str(path), files=[str(path)])

    found, node = _json_select(document, selector)
    if not found:
        return _blank("missing-value",
                      f"The selector {selector} found no value in {path}.",
                      source=str(path), files=[str(path)])
    values = node if isinstance(node, list) else [node]
    numeric = [n for n in (_number(value) for value in values) if n is not None]
    if isinstance(node, dict):
        value = len(node)
        rows = _rows_from_mapping(node)
    elif isinstance(node, list):
        value = sum(numeric) if numeric else len(node)
        rows = [{"primary": str(index), "secondary": str(item), "meta": ""}
                for index, item in enumerate(node[:20])]
    else:
        value = _scalar(node)
        rows = [{"primary": selector, "secondary": str(value), "meta": ""}]
    stale = _stale(path, source.get("window", DEFAULT_WINDOW), ctx.now)
    if stale:
        state, reason = "stale", "older-than-window"
        human = (f"The file {path} has not changed since {_mtime_iso(path)}; "
                 f"showing its last good value.")
    else:
        state, reason = "ok", "ok"
        human = f"Read {selector} from {path}."
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    bindings = {
        "value": value,
        "count": len(node) if isinstance(node, (list, dict)) else 1,
        "rows": rows,
        "table": _table_from_rows(rows),
        "asOf": _mtime_iso(path),
        "file": path.name,
    }
    if numeric:
        bindings["points"] = _points(numeric)
    return _result(state, reason, human, _mtime_iso(path), str(path),
                   bindings, [str(path)], {"selector": selector})


# ---- markdown-watch ----

def _markdown_watch(source, ctx: SourceContext) -> SourceResult:
    declared = source.get("file", "")
    path = _first_match(declared, ctx)
    if path is None:
        return _blank(
            "missing-file", f"The file {declared} does not exist yet.",
            source=str(declared), detail={"declared": declared})
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return _blank("unreadable", f"The file {path} could not be read: {exc}.",
                      source=str(path), files=[str(path)])

    heading = source.get("heading")
    headings = ([heading] if isinstance(heading, str) else list(heading or []))
    active = not headings
    items = []
    for line in lines:
        heading_match = _HEADING.match(line)
        if heading_match:
            title = heading_match.group(2).strip()
            active = (not headings or
                      any(str(h).lower() in title.lower() for h in headings))
            continue
        if not active:
            continue
        box = _CHECKBOX.match(line)
        if box is None:
            continue
        text = box.group(2).strip()
        due_match = _DUE.search(text)
        due = due_match.group(1) if due_match else ""
        clean = _DUE.sub("", text).strip()
        items.append({"text": clean, "done": box.group(1).lower() == "x",
                      "due": due})
    if not items:
        return _blank("no-rows",
                      f"The markdown file {path} has no checkboxes"
                      + (f" under {heading}" if heading else "") + ".",
                      source=str(path), files=[str(path)])
    open_items = [item for item in items if not item["done"]]
    done = len(items) - len(open_items)
    due_values = sorted(item["due"] for item in open_items if item["due"])
    today = ctx.now.date().isoformat()
    overdue = any(due < today for due in due_values)
    due_today = any(due == today for due in due_values)
    tone = "attention" if overdue else ("warn" if due_today else "ok")
    stale = (_stale(path, source["window"], ctx.now)
             if source.get("window") else False)
    if stale:
        state, reason = "stale", "older-than-window"
        human = (f"The file {path} has not changed since {_mtime_iso(path)}; "
                 f"showing its last good value.")
    else:
        state, reason = "ok", "ok"
        human = f"{len(open_items)} open and {done} done in {path}."
    bindings = {
        "value": len(open_items),
        "openCount": len(open_items),
        "doneCount": done,
        "count": len(items),
        "items": items,
        "tone": tone,
        "rows": [{"primary": item["text"],
                  "secondary": "done" if item["done"] else "open",
                  "meta": item["due"]} for item in items],
        "file": path.name,
    }
    if due_values:
        bindings["nextDue"] = due_values[0]
    return _result(state, reason, human, _mtime_iso(path), str(path),
                   bindings, [str(path)], {"checkboxes": len(items)})


# ---- manual-metric ----

def _manual_metric(source, ctx: SourceContext) -> SourceResult:
    declared = source.get("file") or "${pluginData}/manual.json"
    path = _resolve(declared, ctx)
    if not path.exists():
        return _blank("missing-file",
                      f"The manual metric file {path} does not exist yet.",
                      source=str(path), files=[str(path)])
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _blank("bad-json", f"The manual metric file {path} did not "
                      f"parse: {exc}.", source=str(path), files=[str(path)])
    if not isinstance(document, dict):
        return _blank("bad-json",
                      f"The manual metric file {path} must be a JSON object.",
                      source=str(path), files=[str(path)])
    number = _number(document.get("value"))
    if number is None:
        return _blank("bad-value",
                      f"The manual metric file {path} has no numeric value.",
                      source=str(path), files=[str(path)])
    value = int(number) if number.is_integer() else number
    updated = str(document.get("updatedAt", "") or "")
    history = (document.get("history")
               if isinstance(document.get("history"), list) else [])
    points = _points([entry.get("value") for entry in history
                      if isinstance(entry, dict)])
    stale = bool(updated) and _older_than_iso(
        updated, source.get("cadence", DEFAULT_WINDOW), ctx.now)
    if stale:
        state, reason = "stale", "older-than-window"
        human = (f"The manual value was last updated at {updated}; showing "
                 f"that last good value.")
    else:
        state, reason = "ok", "ok"
        human = f"Manual value {value} read from {path}."
    target = document.get("target")
    bindings = {
        "value": value,
        "unit": str(document.get("unit", "")),
        "history": points,
        "lastUpdated": updated,
        "count": len(points) or 1,
        "points": points,
        "file": path.name,
    }
    if target is not None:
        bindings["target"] = _scalar(target)
    if len(points) >= 2:
        bindings["delta"] = _scalar(points[-1] - points[-2])
    rows = [{"primary": str(entry.get("at", "")),
             "secondary": str(entry.get("value", "")), "meta": ""}
            for entry in history if isinstance(entry, dict)]
    if rows:
        bindings["rows"] = rows
        bindings["table"] = _table_from_rows(rows)
    return _result(state, reason, human, updated or _mtime_iso(path),
                   str(path), bindings, [str(path)],
                   {"cadence": source.get("cadence", DEFAULT_WINDOW),
                    "history": history})


# ---- desk-state ----

def _desk_state(source, ctx: SourceContext) -> SourceResult:
    selector = str(source.get("selector", ""))
    if selector not in ("runtime", "audit", "policy"):
        return _blank("bad-schema",
                      f"The desk-state selector {selector or '(none)'} is not "
                      "one of runtime, audit, policy.")
    callback = None
    injected = ctx.desk_state
    if isinstance(injected, dict):
        callback = injected.get(selector)
    elif injected is not None:
        callback = getattr(injected, selector, None)
    if not callable(callback):
        return _blank("no-desk-state",
                      f"The host provides no {selector} state callback.")
    try:
        raw = callback()
    except Exception as exc:  # noqa: BLE001 - an injected callback may fail
        return _blank("desk-state-error",
                      f"The {selector} state callback failed: {exc}.")
    if isinstance(raw, dict):
        candidate = raw.get("state")
        state = candidate if candidate in STATES else "ok"
        bindings = dict(raw.get("bindings") or {})
        for key in ("healthRows", "updateRows", "auditRows", "postureItems",
                    "windowNote", "policyMode", "direction"):
            if key in raw:
                bindings.setdefault(key, raw[key])
        value = raw.get("value")
        if value is not None:
            bindings.setdefault("value", value)
        bindings.setdefault("status", str(raw.get("status") or state))
        bindings.setdefault("tone", str(raw.get("tone") or "ok"))
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                bindings.setdefault("rows", value)
                bindings.setdefault("items", value)
            else:
                bindings.setdefault("points", _points(value))
        bindings.setdefault(
            "count", len(value) if isinstance(value, list) else 1)
        reason = str(raw.get("reason") or ("ok" if state == "ok" else state))
        human = str(raw.get("human") or raw.get("cause")
                    or f"Read the {selector} state from the host.")
        return _result(state, reason, human,
                       str(raw.get("asOf") or _now_iso(ctx)),
                       f"desk-state:{selector}", bindings, [],
                       {"selector": selector})
    value = _scalar(raw)
    bindings = {"value": value, "count": 1, "status": "ok", "tone": "ok"}
    if isinstance(raw, list):
        bindings["count"] = len(raw)
        bindings["points"] = _points(raw)
    return _result("ok", "ok", f"Read the {selector} state from the host.",
                   _now_iso(ctx), f"desk-state:{selector}", bindings, [],
                   {"selector": selector})


# ---- compare ----

def _compare(source, ctx: SourceContext) -> SourceResult:
    left_source, right_source = source.get("left"), source.get("right")
    for side, spec in (("left", left_source), ("right", right_source)):
        if not isinstance(spec, dict):
            return _blank("bad-schema",
                          f"The compare source has no {side} source object.")
        if str(spec.get("type", "")) not in LOCAL_TYPES:
            return _blank("unsafe-source",
                          f"The compare source may only read local sources; "
                          f"the {side} side is {spec.get('type', '(none)')}.")
    left = read_source(left_source, replace(ctx, visiting=ctx.visiting))
    right = read_source(right_source, replace(ctx, visiting=ctx.visiting))
    for side, result in (("left", left), ("right", right)):
        if result.state == "blank":
            return _blank("blank-side",
                          f"The {side} side of the comparison is blank: "
                          f"{result.human}", source=result.source,
                          files=result.files)
    left_keys = _compare_keys(left)
    right_keys = _compare_keys(right)
    both = sorted(left_keys & right_keys)
    left_only = sorted(left_keys - right_keys)
    right_only = sorted(right_keys - left_keys)
    states = [left.state, right.state]
    if "partial" in states:
        state, reason = "partial", "partial-rows"
        human = (f"{len(both)} keys matched; one side only parsed part of "
                 f"its rows.")
    elif "stale" in states:
        state, reason = "stale", "older-than-window"
        human = (f"{len(both)} keys matched; at least one side is older than "
                 f"its window.")
    elif "coarse" in states:
        state, reason = "coarse", "fallback-used"
        human = f"{len(both)} keys matched; at least one side used a fallback."
    else:
        state, reason = "ok", "ok"
        human = (f"{len(both)} keys in both, {len(left_only)} only left, "
                 f"{len(right_only)} only right.")
    rows = ([{"primary": key, "secondary": "left only", "meta": ""}
             for key in left_only]
            + [{"primary": key, "secondary": "right only", "meta": ""}
               for key in right_only]
            + [{"primary": key, "secondary": "both", "meta": ""}
               for key in both])
    delta = len(left_keys) - len(right_keys)
    bindings = {
        "value": len(both),
        "count": len(both),
        "left": len(left_keys),
        "right": len(right_keys),
        "delta": delta,
        "direction": "flat" if delta == 0 else ("up" if delta > 0 else "down"),
        "leftOnly": left_only,
        "rightOnly": right_only,
        "both": both,
        "leftCount": len(left_keys),
        "rightCount": len(right_keys),
        "rows": rows,
        "table": _table_from_rows(rows),
        "file": "",
    }
    return _result(state, reason, human, max(left.as_of, right.as_of),
                   f"compare:{left.source}|{right.source}", bindings,
                   left.files + right.files, {"left": left.detail,
                                              "right": right.detail})


def _compare_keys(result: SourceResult) -> set:
    rows = result.bindings.get("rows")
    if isinstance(rows, list):
        return {str(row.get("primary", "")) for row in rows
                if isinstance(row, dict)}
    items = result.bindings.get("items")
    if isinstance(items, list):
        return {str(item.get("text", "")) for item in items
                if isinstance(item, dict)}
    if "value" in result.bindings:
        return {str(result.bindings["value"])}
    return set()


# ---- aggregate ----

def _aggregate(source, ctx: SourceContext) -> SourceResult:
    dependencies = ctx.dependencies if isinstance(ctx.dependencies, dict) else {}
    over = source.get("over")
    if not isinstance(over, list) or not over:
        # The documented form aggregates over the plugin's own requires[].
        own = dependencies.get(ctx.plugin_id)
        requires = own.get("requires") if isinstance(own, dict) else None
        over = [item for item in (requires or []) if isinstance(item, str)]
    if not over or not all(isinstance(item, str) for item in over):
        return _blank("bad-schema",
                      "The aggregate source needs the plugin's requires or a "
                      "non-empty over list of plugin ids.")
    cycle = _find_cycle(ctx.plugin_id, dependencies)
    if cycle:
        return _blank("cycle",
                      "Dependency cycle: " + " -> ".join(cycle) + ".",
                      detail={"cycle": cycle})
    mode = str(source.get("aggregate", "sum")).lower()
    if mode not in ("sum", "count", "latest", "min", "max"):
        mode = "sum"

    values, rows, as_ofs, files = [], [], [], []
    stale = partial = coarse = False
    for dep_id in over:
        if dep_id in ctx.visiting:
            return _blank("cycle",
                          "Dependency cycle: " + " -> ".join(
                              list(ctx.visiting) + (dep_id,)) + ".",
                          detail={"cycle": list(ctx.visiting) + [dep_id]})
        manifest = dependencies.get(dep_id)
        if not isinstance(manifest, dict):
            return _blank("missing-dependency",
                          f"The aggregate needs {dep_id}, which is not installed.",
                          detail={"missing": dep_id})
        widgets = manifest.get("contributes", {}).get("widgets", [])
        if not widgets or not isinstance(widgets[0], dict):
            return _blank("missing-dependency",
                          f"The installed plugin {dep_id} contributes no widget.",
                          detail={"missing": dep_id})
        dep_source = widgets[0].get("dataSource")
        if not isinstance(dep_source, dict):
            return _blank("missing-dependency",
                          f"The installed plugin {dep_id} has no data source.",
                          detail={"missing": dep_id})
        result = read_source(dep_source, replace(
            ctx, plugin_id=dep_id, visiting=ctx.visiting + (ctx.plugin_id,)))
        if result.state == "blank":
            return _blank("blank-dependency",
                          f"The aggregate is blank because {dep_id} is blank: "
                          f"{result.human}", detail={"dependency": dep_id})
        stale = stale or result.state == "stale"
        partial = partial or result.state == "partial"
        coarse = coarse or result.state == "coarse"
        files.extend(result.files)
        if result.as_of:
            as_ofs.append(result.as_of)
        value = _number(result.bindings.get("value"))
        if value is not None:
            values.append(value)
            rows.append({"primary": dep_id,
                         "secondary": str(result.bindings.get("value")),
                         "meta": result.state})
    if mode == "count":
        value = len(values)
    elif not values:
        return _blank("no-values",
                      "None of the aggregate's dependencies supplied a numeric "
                      "value.")
    elif mode == "sum":
        value = sum(values)
    elif mode == "latest":
        value = values[-1]
    elif mode == "min":
        value = min(values)
    else:
        value = max(values)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if partial:
        state, reason = "partial", "partial-rows"
        human = "Some dependencies only parsed part of their rows."
    elif stale:
        state, reason = "stale", "older-than-window"
        human = "At least one dependency is older than its window."
    elif coarse:
        state, reason = "coarse", "fallback-used"
        human = "At least one dependency used a declared fallback."
    else:
        state, reason = "ok", "ok"
        human = f"Aggregated {len(values)} dependencies with {mode}."
    return _result(state, reason, human, max(as_ofs) if as_ofs else "",
                   "aggregate:" + ",".join(over),
                   {"value": value, "count": len(values),
                    "contributors": list(over), "rows": rows,
                    "table": _table_from_rows(rows),
                    "points": _points(values)},
                   files, {"mode": mode, "over": over})


def _find_cycle(start: str, dependencies: dict):
    requires = {}
    for dep_id, manifest in dependencies.items():
        if isinstance(manifest, dict):
            needs = manifest.get("requires") or []
            requires[dep_id] = [need for need in needs
                                if isinstance(need, str)]
    path = []
    seen = set()

    def visit(node: str):
        if node in path:
            return path[path.index(node):] + [node]
        if node in seen:
            return None
        seen.add(node)
        path.append(node)
        for need in requires.get(node, []):
            found = visit(need)
            if found:
                return found
        path.pop()
        return None

    return visit(start)


# ---- http-get ----

def _host_allowed(url: str, patterns) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    for pattern in patterns or ():
        pattern = str(pattern)
        if "://" in pattern:
            if fnmatch(url, pattern) or url.startswith(pattern.rstrip("*")):
                return True
            pattern_host = (urlsplit(pattern).hostname or "").lower()
            if pattern_host and fnmatch(host, pattern_host):
                return True
        elif fnmatch(host, pattern.lower()):
            return True
    return False


def _http_get(source, ctx: SourceContext) -> SourceResult:
    url = str(source.get("url", ""))
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return _blank("bad-schema",
                      f"The http-get URL {url or '(none)'} must be an "
                      "absolute http(s) URL.")
    allow = source.get("allow")
    if not isinstance(allow, list) or not allow:
        return _blank("host-not-allowed",
                      f"The http-get source for {parts.hostname} declares no "
                      "host allowlist.")
    if not _host_allowed(url, allow):
        return _blank("host-not-allowed",
                      f"The host {parts.hostname} is not in the source's "
                      "declared allowlist.", detail={"host": parts.hostname})
    if not _host_allowed(url, ctx.network_allow):
        return _blank("network-not-allowed",
                      f"The plugin has no granted network permission for "
                      f"{parts.hostname}.")
    if ctx.transport is None:
        return _blank("no-transport",
                      "The host has no HTTP transport available for this plugin.")

    timeout = _number(source.get("timeoutSeconds"))
    timeout = HTTP_TIMEOUT_DEFAULT if timeout is None else min(
        max(timeout, 0.1), HTTP_TIMEOUT_CAP)
    max_bytes = HTTP_MAX_BYTES
    smaller = _number(source.get("maxBytes"))
    if smaller is not None:
        max_bytes = min(int(smaller), HTTP_MAX_BYTES)

    try:
        response = ctx.transport(url, timeout, max_bytes)
    except TimeoutError:
        return _blank("timeout",
                      f"The request to {parts.hostname} timed out after "
                      f"{timeout:g}s.")
    except Exception as exc:  # noqa: BLE001 - a transport may fail any way
        return _blank("transport-error",
                      f"The request to {parts.hostname} failed: {exc}.")
    try:
        status_code, headers, body = response
    except (TypeError, ValueError):
        return _blank("transport-error",
                      "The HTTP transport returned an unreadable response.")
    status_code = int(status_code)
    raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
    if len(raw) > max_bytes:
        return _blank("oversize",
                      f"The response from {parts.hostname} is {len(raw)} bytes, "
                      f"over the {max_bytes}-byte cap.")
    if status_code >= 400:
        return _blank(f"http-{status_code}",
                      f"{parts.hostname} returned HTTP {status_code}.")
    if status_code >= 300:
        return _blank("http-redirect",
                      f"{parts.hostname} returned a redirect; the host does "
                      "not follow redirects.")

    digest = hashlib.sha256(raw).hexdigest()
    state_path = Path(ctx.data_dir) / "http-state.json"
    previous = ""
    previous_value = None
    state = {}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
        else:
            entry = state.get(url)
            if isinstance(entry, dict):
                previous = str(entry.get("sha256", ""))
                previous_value = entry.get("value")
    except (OSError, ValueError):
        state = {}
    changed = bool(previous) and previous != digest
    fetched_at = _now_iso(ctx)

    text = raw.decode("utf-8", errors="replace")
    parsed = None
    try:
        parsed = json.loads(text)
    except ValueError:
        pass
    bindings = {"changed": changed, "status": status_code,
                "fetchedAt": fetched_at, "sha256": digest, "url": url,
                "file": "", "count": 1}
    if isinstance(parsed, dict):
        value = parsed.get("value")
        bindings["value"] = (_scalar(value) if value is not None
                             else len(parsed))
        bindings["count"] = len(parsed)
        bindings["rows"] = _rows_from_mapping(parsed)
        bindings["table"] = _table_from_rows(bindings["rows"])
    elif isinstance(parsed, list):
        numeric = [n for n in (_number(item) for item in parsed)
                   if n is not None]
        bindings["value"] = sum(numeric) if numeric else len(parsed)
        bindings["count"] = len(parsed)
        bindings["points"] = _points(parsed)
        rows = [{"primary": str(index), "secondary": str(item), "meta": ""}
                for index, item in enumerate(parsed[:20])]
        bindings["rows"] = rows
        bindings["table"] = _table_from_rows(rows)
    else:
        bindings["value"] = _scalar(parsed) if parsed is not None else text[:200]
    current_number = _number(bindings.get("value"))
    previous_number = _number(previous_value)
    if current_number is None or previous_number is None:
        direction = "flat"
    elif current_number > previous_number:
        direction = "up"
    elif current_number < previous_number:
        direction = "down"
    else:
        direction = "flat"
    bindings["direction"] = direction
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state[url] = {"sha256": digest, "checkedAt": fetched_at,
                      "status": status_code, "value": bindings.get("value")}
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass  # an unwritable state file must not lose the read
    human = (f"Fetched {parts.hostname} ({len(raw)} bytes); "
             + ("the response changed since the last read." if changed
                else "the content hash is unchanged."))
    return _result("ok", "ok", human, fetched_at, url, bindings, [],
                   {"status": status_code, "bytes": len(raw),
                    "previousSha256": previous, "changed": changed})


# ---- pipeline-backed sources (delegate to the runner's existing code) ----

def _pipeline(source, ctx: SourceContext) -> SourceResult:
    source_type = str(source.get("type", ""))
    if ctx.pipeline_status is None:
        return _blank("pipeline-unavailable",
                      f"The {source_type} pipeline is not available.")
    status, bindings = ctx.pipeline_status(source_type)
    fresh = str(status.get("status", "")) == "fresh"
    return _result(
        "ok" if fresh else "blank",
        "ok" if fresh else str(status.get("reason") or
                               status.get("state") or "attention"),
        (f"Read the {source_type} pipeline." if fresh else
         str(status.get("cause") or "the pipeline needs attention")),
        str(status.get("checked_at", "")),
        source_type, bindings, [],
        {"rawState": status.get("state", "")})


_READERS = {
    "excel-watch": _excel_watch,
    "csv-watch": _csv_watch,
    "json-watch": _json_watch,
    "markdown-watch": _markdown_watch,
    "manual-metric": _manual_metric,
    "desk-state": _desk_state,
    "compare": _compare,
    "aggregate": _aggregate,
    "http-get": _http_get,
    "calendar-read": _pipeline,
    "mail-digest": _pipeline,
    "outlook-brief": _pipeline,
    "research-brief": _pipeline,
}

SOURCE_TYPES = tuple(_READERS)