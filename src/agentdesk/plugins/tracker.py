"""Read one confirmed tracker instance. The path and the columns come
from the instance config. Nothing else is opened.
"""

from __future__ import annotations

import json
import time

from agentdesk.plugins.config import InstanceStore
from agentdesk.plugins.preview import preview_table


def pace_line(spent: float, elapsed: float, plan: float, period: float) -> str:
    """Compare the reading's daily rate against the plan's daily rate in one line.

    Both sides divide by their day count; ``elapsed`` and ``period`` arrive
    strictly positive because the config validation refuses anything else.
    """
    return f"{spent / elapsed:.2f} per day against {plan / period:.2f} per day"


def read_tracker(store: InstanceStore, plugin_id: str, instance_id: str) -> dict:
    """Read a confirmed tracker's file and return its value, history and provenance.

    Only the granted file is opened, and only its first 500 data rows are read; the
    configured row selection then indexes those rows, so row numbers are positions
    in the preview rather than in the sheet. The value is reduced with the configured
    aggregate and appended to the instance's ``history.json`` when it differs from
    the previous reading; the newest 30 values come back as ``points``, with ``delta``
    and ``direction`` comparing the last two. ``sample`` is true when the file sits
    under a ``sample`` folder, which is the shipped demo fixture rather than a file
    the user connected.
    """
    document = store.read(plugin_id, instance_id)
    path = store.granted_file(plugin_id, instance_id)
    tracking = document.get("tracking") or {}
    preview = preview_table(
        path,
        sheet=None,
        header_row=int((document.get("source") or {}).get("headerRow") or 1),
        range_text=(document.get("source") or {}).get("range"),
        limit=500,
    )
    headers = [cell.strip().lower() for cell in preview["headers"]]
    label_at = _index(headers, tracking.get("labelColumn"))
    value_at = _index(headers, tracking.get("valueColumn"))
    body = list(preview["rows"])
    selected = tracking.get("rows")
    if isinstance(selected, list):
        body = [body[index] for index in selected if isinstance(index, int) and 0 <= index < len(body)]
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
    pace = tracking.get("pace")
    pace_note = ""
    if isinstance(pace, dict):
        pace_note = pace_line(value, pace["elapsedDays"], pace["plan"], pace["periodDays"])
    goal = tracking.get("goal") if isinstance(tracking.get("goal"), dict) else None
    return {
        "value": value,
        "delta": delta,
        "direction": direction,
        "points": history[-30:],
        "file": path.name,
        "unit": str(tracking.get("unit") or ""),
        "paceNote": pace_note,
        "goal": goal,
        "labelColumn": tracking.get("labelColumn"),
        "valueColumn": tracking.get("valueColumn"),
        "rowsSeen": len(body),
        # Provenance: the card says when this reading happened, and whether
        # the source is the app's own sample folder (demo fixture) rather
        # than a file the user connected.
        "readAt": time.time(),
        "sample": any(part.lower() == "sample" for part in path.parent.parts),
    }


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
