"""Read one confirmed tracker instance. The path and the columns come
from the instance config. Nothing else is opened.
"""

from __future__ import annotations

import json
import time

from nexuusbot.plugins.config import InstanceStore
from nexuusbot.plugins.preview import preview_table
from nexuusbot.plugins.sources import cell_date

_CHARTS = ("line", "column", "area")
_SERIES_CAP = 60
_SCALAR_LIMIT = 500
_SERIES_LIMIT = 5000


def pace_line(spent: float, elapsed: float, plan: float, period: float) -> str:
    """Compare the reading's daily rate against the plan's daily rate in one line.

    Both sides divide by their day count; ``elapsed`` and ``period`` arrive
    strictly positive because the config validation refuses anything else.
    """
    return f"{spent / elapsed:.2f} per day against {plan / period:.2f} per day"


def read_tracker(store: InstanceStore, plugin_id: str, instance_id: str) -> dict:
    """Read a confirmed tracker's file and return its value, history and provenance.

    Only the granted file is opened. With no time column the first 500 data rows
    are read and the points are the last 30 re-reads of that total. With a time
    column the first 5000 rows are bucketed and the points are those periods.
    The configured row selection indexes the preview, so row numbers are positions
    in the preview rather than in the sheet. The value is appended to the instance's
    ``history.json`` when it differs from the previous reading. ``sample`` is true when the file sits
    under a ``sample`` folder, which is the shipped demo fixture rather than a file
    the user connected.
    """
    document = store.read(plugin_id, instance_id)
    path = store.granted_file(plugin_id, instance_id)
    tracking = document.get("tracking") or {}
    chart = str(tracking.get("chart") or "line").lower()
    if chart not in _CHARTS:
        chart = "line"
    date_name = str(tracking.get("dateColumn") or "").strip()
    preview = preview_table(
        path,
        sheet=None,
        header_row=int((document.get("source") or {}).get("headerRow") or 1),
        range_text=(document.get("source") or {}).get("range"),
        limit=_SERIES_LIMIT if date_name else _SCALAR_LIMIT,
    )
    headers = [cell.strip().lower() for cell in preview["headers"]]
    value_at = _index(headers, tracking.get("valueColumn"))
    body = list(preview["rows"])
    selected = tracking.get("rows")
    if isinstance(selected, list):
        body = [body[index] for index in selected if isinstance(index, int) and 0 <= index < len(body)]
    series_note = ""
    labels: list[str] = []
    axis = "reading"
    buckets = _buckets(headers, body, date_name, value_at, tracking.get("aggregate") or "sum")
    if buckets is not None and buckets.get("missing"):
        series_note = "The time column is not in this file, so this is the history of readings."
        buckets = None
    if buckets is None:
        numbers = []
        for row in body:
            if value_at is None or value_at >= len(row):
                continue
            number = _number(row[value_at])
            if number is not None:
                numbers.append(number)
        value = _aggregate(numbers, tracking.get("aggregate") or "sum")
        history = _remember(store, plugin_id, instance_id, value)
        delta, direction = _delta(history)
        points = history[-30:]
        delta_label = "" if len(history) < 2 else "since the last reading"
    elif not buckets["points"]:
        value = 0.0
        _remember(store, plugin_id, instance_id, value)
        delta, direction = "First reading", "flat"
        points = []
        series_note = "No points in the time column."
        delta_label = ""
        axis = "time"
    else:
        value = buckets["points"][-1]
        _remember(store, plugin_id, instance_id, value)
        points = buckets["points"]
        labels = buckets["labels"]
        axis = "time"
        if buckets["truncated"]:
            series_note = "Older periods are not on the chart."
        if len(points) < 2:
            delta, direction = "First reading", "flat"
            delta_label = ""
        else:
            delta, direction = _delta(points[-2:])
            delta_label = "since the previous period"
    pace = tracking.get("pace")
    pace_note = ""
    if isinstance(pace, dict):
        pace_note = pace_line(value, pace["elapsedDays"], pace["plan"], pace["periodDays"])
    goal = tracking.get("goal") if isinstance(tracking.get("goal"), dict) else None
    return {
        "value": value,
        "delta": delta,
        "direction": direction,
        "points": points,
        "chart": chart,
        "axis": axis,
        "labels": labels,
        "deltaLabel": delta_label,
        "seriesNote": series_note,
        "file": path.name,
        "unit": str(tracking.get("unit") or ""),
        "paceNote": pace_note,
        "goal": goal,
        "labelColumn": tracking.get("labelColumn"),
        "valueColumn": tracking.get("valueColumn"),
        "rowsSeen": len(body),
        # The same rows the value came from, as cells: the reading a
        # relationship needs, capped so one card stays one small payload.
        "table": {
            "headers": [str(cell) for cell in preview["headers"][:10]],
            "rows": [[str(cell) for cell in row[:10]] for row in body[:60]],
        },
        # Provenance: the card says when this reading happened, and whether
        # the source is the app's own sample folder (demo fixture) rather
        # than a file the user connected.
        "readAt": time.time(),
        "sample": any(part.lower() == "sample" for part in path.parent.parts),
    }


def _buckets(headers, body, date_name: str, value_at, mode: str):
    """Group rows by the time column, or None when the tracker has no time column.

    A time column that is not a header returns ``{"missing": True}``. Blank
    cells are skipped. Parsed dates share a ``YYYY-MM-DD`` label and, when
    every kept bucket parsed, the buckets are sorted by that label. Otherwise
    the first-seen file order stands. At most the newest 60 buckets come back.
    """
    if not date_name:
        return None
    date_at = _index(headers, date_name)
    if date_at is None:
        return {"missing": True}
    order: list[str] = []
    grouped: dict[str, list[float]] = {}
    parsed_all = True
    for row in body:
        if date_at >= len(row):
            continue
        raw = str(row[date_at]).strip()
        if not raw:
            continue
        when = cell_date(row[date_at])
        if when is None and raw.isdigit():
            when = cell_date(float(raw))
        if when is None:
            parsed_all = False
            key = raw
        else:
            key = when.date().isoformat()
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        if value_at is not None and value_at < len(row):
            number = _number(row[value_at])
            if number is not None:
                grouped[key].append(number)
    labels = []
    points = []
    for key in order:
        if not grouped[key]:
            continue
        labels.append(key)
        points.append(_aggregate(grouped[key], mode))
    if parsed_all and labels:
        paired = sorted(zip(labels, points))
        labels = [label for label, _point in paired]
        points = [point for _label, point in paired]
    truncated = len(points) > _SERIES_CAP
    if truncated:
        labels = labels[-_SERIES_CAP:]
        points = points[-_SERIES_CAP:]
    return {"missing": False, "labels": labels, "points": points, "truncated": truncated}


def _index(headers, name):
    """Return a header's position, matched case- and whitespace-insensitively, or None
    when the row no longer has that column.
    """
    wanted = str(name or "").strip().lower()
    if wanted in headers:
        return headers.index(wanted)
    return None


def _number(value):
    """Parse a cell into a float, tolerating thousands separators and a leading dollar
    sign; None when the cell holds nothing numeric.
    """
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _aggregate(numbers, mode) -> float:
    """Reduce the collected numbers with the configured mode.

    ``count`` counts the numbers, not the rows, so a row whose value cell is unparsable
    is not counted; ``latest`` is the last number in file order, not the largest. An
    empty selection reads 0.0.
    """
    if mode == "count":
        return float(len(numbers))
    if not numbers:
        return 0.0
    if mode == "latest":
        return numbers[-1]
    if mode == "min":
        return min(numbers)
    if mode == "max":
        return max(numbers)
    return float(sum(numbers))


def _remember(store: InstanceStore, plugin_id: str, instance_id: str, value: float) -> list:
    """Append a reading to the instance's history file and return the trimmed history.

    A value equal to the last one is not appended, so ``delta`` measures change
    rather than a re-read; the newest 30 values are kept and the file is rewritten on
    every read.
    """
    path = store._instance_dir(plugin_id, instance_id) / "history.json"
    history = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history = [float(item) for item in loaded]
        except (OSError, ValueError):
            history = []
    if not history or history[-1] != value:
        history.append(value)
    history = history[-30:]
    path.write_text(json.dumps(history), encoding="utf-8")
    return history


def _signed(change: float) -> str:
    """Format a change with an explicit sign for the card.

    Whole changes print as integers and the rest with two decimals; the minus is
    U+2212 so it matches the other numbers rather than reading as a hyphen.
    """
    number = abs(change)
    text = str(int(number)) if float(number).is_integer() else f"{number:.2f}"
    if change > 0:
        return f"+{text}"
    if change < 0:
        return f"−{text}"
    return "0"


def _delta(history: list) -> tuple[str, str]:
    """Return the formatted change since the previous reading and its direction.

    A single reading has nothing to compare with, so it reports "First reading" and
    a flat direction.
    """
    if len(history) < 2:
        return "First reading", "flat"
    return _signed(history[-1] - history[-2]), (
        "up" if history[-1] > history[-2] else "down" if history[-1] < history[-2] else "flat"
    )
