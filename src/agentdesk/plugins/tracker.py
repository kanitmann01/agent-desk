"""Read one confirmed tracker instance. The path and the columns come
from the instance config. Nothing else is opened.
"""

from __future__ import annotations

import json

from agentdesk.plugins.config import InstanceStore
from agentdesk.plugins.preview import preview_table


def pace_line(spent: float, elapsed: float, plan: float, period: float) -> str:
    return f"{spent / elapsed:.2f} per day against {plan / period:.2f} per day"


def read_tracker(store: InstanceStore, plugin_id: str, instance_id: str) -> dict:
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
    numbers = []
    for row in preview["rows"]:
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
    return {
        "value": value,
        "delta": delta,
        "direction": direction,
        "points": history[-30:],
        "file": path.name,
        "paceNote": pace_note,
        "labelColumn": tracking.get("labelColumn"),
        "valueColumn": tracking.get("valueColumn"),
        "rowsSeen": len(preview["rows"]),
    }


def _index(headers, name):
    wanted = str(name or "").strip().lower()
    if wanted in headers:
        return headers.index(wanted)
    return None


def _number(value):
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _aggregate(numbers, mode) -> float:
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


def _delta(history: list) -> tuple[str, str]:
    if len(history) < 2:
        return "First reading.", "flat"
    change = history[-1] - history[-2]
    if change > 0:
        return f"{change:.2f}", "up"
    if change < 0:
        return f"{change:.2f}", "down"
    return "0", "flat"
