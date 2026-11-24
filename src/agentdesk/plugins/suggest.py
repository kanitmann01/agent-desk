"""A column suggestion. Nothing is sent unless a key is saved and the
columns step has opened. The disclosure sentence lists what left the machine.
"""

from __future__ import annotations

import json

from agentdesk.plugins.config import ConfigError
from agentdesk.plugins.sources import cell_date

DISCLOSURE_ROWS = (
    "This sends the column names and up to 5 rows to your AI. "
    "The file path stays on this machine."
)
DISCLOSURE_HEADERS = (
    "This sends the column names to your AI. "
    "No cell values and no file path leave this machine."
)
_MAX_BYTES = 8192
_MAX_ROWS = 5


def build_suggestion_request(*, job, sheet, headers, rows, headers_only, path) -> tuple[dict, str]:
    """Build the suggestion payload and the disclosure sentence that goes with it.

    The file path is dropped on purpose: only the job, the sheet name, the headers and
    at most five rows travel, and rows are popped from the end until the encoded
    request fits in 8 KiB. ``headers_only`` empties the rows and pairs the request with
    the headers-only sentence, so the disclosure always matches what was kept.
    """
    del path  # the path is never part of the request
    kept = [] if headers_only else [list(row) for row in list(rows or [])[:_MAX_ROWS]]
    request = {
        "job": str(job or ""),
        "sheet": str(sheet or ""),
        "headers": [str(cell) for cell in (headers or [])],
        "rows": kept,
    }
    while request["rows"] and len(json.dumps(request).encode("utf-8")) > _MAX_BYTES:
        request["rows"].pop()
    note = DISCLOSURE_HEADERS if headers_only or not request["rows"] else DISCLOSURE_ROWS
    if headers_only:
        request["rows"] = []
        note = DISCLOSURE_HEADERS
    return request, note


def heuristic(headers: list, rows: list) -> dict:
    """Pick a value column and a label column without calling a model.

    The value is the numeric column with the greatest variance. The label
    is the text column with the fewest distinct values.
    """
    headers = [str(cell) for cell in headers]
    if not headers:
        raise ConfigError("config:suggest-failed", "The file has no columns to suggest.")
    best_index = 0
    best_score = (-1.0, -1)
    numeric_at = []
    for index, _header in enumerate(headers):
        series = [_number(row[index]) for row in rows if index < len(row)]
        series = [number for number in series if number is not None]
        numeric_at.append(series)
        if not series:
            continue
        score = (_variance(series), len(series))
        if score > best_score:
            best_score = score
            best_index = index
    label_index = _label_index(headers, rows, best_index)
    chosen_rows = [
        index for index, row in enumerate(rows)
        if best_index < len(row) and _number(row[best_index]) is not None
    ]
    value_name = headers[best_index]
    label_name = headers[label_index]
    date_index = _date_index(rows, best_index)
    date_name = headers[date_index] if date_index is not None else None
    return {
        "labelColumn": label_name,
        "valueColumn": value_name,
        "dateColumn": date_name,
        "chart": "line" if date_name else "column",
        "aggregate": "sum",
        "rows": chosen_rows,
        "reason": f"{value_name} looks like the amount; {label_name} groups rows.",
        "source": "heuristic",
    }


def _number(value):
    """Parse a cell as a float for the variance scoring, or None when it is not a number.

    Booleans are rejected before the numeric branch so a flag cell does not read as 1;
    strings lose their separators and a leading dollar sign first.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _variance(values: list) -> float:
    """Population variance of the values, and 0.0 for fewer than two.

    The divisor is the count, not count minus one, so columns with different numbers
    of readable cells stay comparable.
    """
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _date_index(rows, value_index: int):
    """The column whose sampled cells mostly parse as dates, or None.

    The value column is skipped. A column qualifies when at least half of
    its filled cells parse, and the one with the most parsed cells wins.
    """
    best = None
    best_hits = 0
    width = max((len(row) for row in rows), default=0)
    for index in range(width):
        if index == value_index:
            continue
        hits = 0
        seen = 0
        for row in rows:
            if index >= len(row):
                continue
            text = str(row[index]).strip()
            if not text:
                continue
            seen += 1
            if cell_date(row[index]) is not None:
                hits += 1
        if seen and hits * 2 >= seen and hits > best_hits:
            best = index
            best_hits = hits
    return best


def _label_index(headers, rows, value_index: int) -> int:
    """Pick the column that names rows: the one with the fewest distinct texts.

    The value column is skipped, and a column whose cells parse as numbers does not
    count as text. When no column has any text left, the fallback is the first column
    that is not the value column.
    """
    best = None
    best_count = None
    for index, _header in enumerate(headers):
        if index == value_index:
            continue
        texts = []
        for row in rows:
            if index >= len(row):
                continue
            if _number(row[index]) is not None and not isinstance(row[index], str):
                continue
            text = str(row[index]).strip()
            if text and _number(text) is None:
                texts.append(text)
        if not texts:
            continue
        distinct = len(set(texts))
        if best_count is None or distinct < best_count:
            best = index
            best_count = distinct
    if best is None:
        return 0 if value_index != 0 else min(1, len(headers) - 1)
    return best


EVALUATION_PROMPT = (
    "You review a user's column and row choice for a tracker before it is saved. "
    "The user chose a label column (the row's name), a value column (the number to "
    "aggregate), and the rows to count. Decide whether that pairing makes sense: the "
    "label should identify rows, the value should be numeric and aggregatable, and the "
    "row set should be a coherent slice. Reply with one JSON object and nothing else: "
    '{"verdict": "ok" or "adjust", "message": "one short sentence", '
    '"recommendation": {"labelColumn": "...", "valueColumn": "...", '
    '"rows": [0, 1], "reason": "one short sentence"} or null}. '
    "Use recommendation null when the choice is fine. Use only column names present in "
    "the request. Row numbers refer to rowCount in the request, not to the sampled rows.\n"
)


def build_evaluation_request(*, job, sheet, headers, rows, choice, row_count) -> tuple[dict, str]:
    """The user's own choice, plus the rows it covers, capped like suggest.

    The path is never part of the request; only the selected row values and
    their positions are. The row count lets a recommendation name rows the
    five-row sample does not show without inventing numbers.
    """
    headers = [str(cell) for cell in (headers or [])]
    selected = [index for index in (choice.get("rows") or []) if isinstance(index, int)]
    sampled = [index for index in selected if 0 <= index < len(rows)][:_MAX_ROWS]
    request = {
        "job": str(job or ""),
        "sheet": str(sheet or ""),
        "headers": headers,
        "rowCount": int(row_count or 0),
        "choice": {
            "labelColumn": str(choice.get("labelColumn") or ""),
            "valueColumn": str(choice.get("valueColumn") or ""),
            "rows": sampled,
        },
        "rows": [list(rows[index]) for index in sampled],
    }
    while request["rows"] and len(json.dumps(request).encode("utf-8")) > _MAX_BYTES:
        request["rows"].pop()
    note = DISCLOSURE_HEADERS if not request["rows"] else DISCLOSURE_ROWS
    return request, note


def evaluate_choice(request: dict, complete) -> dict:
    """One model opinion on the user's choice. Never raises, never blocks.

    No endpoint, a timeout, or an answer that cannot be parsed all return
    verdict "unchecked" with a plain cause; the caller keeps the user's
    choice and confirm still succeeds.
    """
    if complete is None:
        return {
            "verdict": "unchecked",
            "message": "Model check skipped: no AI is saved. Your choice is used as chosen.",
            "recommendation": None,
            "source": "none",
        }
    try:
        raw = complete(EVALUATION_PROMPT + json.dumps(request))
    except Exception as exc:  # noqa: BLE001 - the check is advice, never a gate
        return {
            "verdict": "unchecked",
            "message": f"Model check skipped: {exc}. Your choice is used as chosen.",
            "recommendation": None,
            "source": "none",
        }
    text = str(raw or "")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {
            "verdict": "unchecked",
            "message": "The endpoint did not return a verdict, so your choice is used as chosen.",
            "recommendation": None,
            "source": "none",
        }
    try:
        parsed = json.loads(text[start:end + 1])
    except ValueError:
        return {
            "verdict": "unchecked",
            "message": "The endpoint did not return a verdict, so your choice is used as chosen.",
            "recommendation": None,
            "source": "none",
        }
    if not isinstance(parsed, dict):
        return {
            "verdict": "unchecked",
            "message": "The endpoint did not return a verdict, so your choice is used as chosen.",
            "recommendation": None,
            "source": "none",
        }
    verdict = "adjust" if str(parsed.get("verdict") or "").strip().lower() == "adjust" else "ok"
    message = str(parsed.get("message") or "").strip()[:240]
    if not message:
        message = "The pairing looks right." if verdict == "ok" else "The pairing may need a change."
    return {
        "verdict": verdict,
        "message": message,
        "recommendation": _validated_recommendation(parsed.get("recommendation"), request),
        "source": "model",
    }


def _validated_recommendation(rec, request: dict):
    """A recommendation is applied only if every name and row exists."""
    if not isinstance(rec, dict):
        return None
    headers = set(request.get("headers") or [])
    label = str(rec.get("labelColumn") or "").strip()
    value = str(rec.get("valueColumn") or "").strip()
    if not label or not value or label not in headers or value not in headers:
        return None
    row_count = int(request.get("rowCount") or 0)
    raw_rows = rec.get("rows")
    rows = None
    if isinstance(raw_rows, list):
        rows = [index for index in raw_rows if isinstance(index, int) and 0 <= index < row_count]
        if not rows:
            rows = None
    reason = str(rec.get("reason") or "").strip()[:240]
    return {
        "labelColumn": label,
        "valueColumn": value,
        "rows": rows,
        "reason": reason or f"{value} by {label} fits the chosen rows better.",
    }


def propose_columns(request: dict, complete) -> dict:
    """Ask the model which columns to track.

    Every failure (an endpoint that raises, an answer with no JSON object, or a
    column name that was not in the request) raises ``config:suggest-failed`` so the
    picker can keep the user's own choice. An unknown aggregate falls back to sum, and
    a missing row list means every row that was sampled.
    """
    prompt = (
        "Choose which columns to track. Reply with one JSON object and nothing else, "
        "with keys labelColumn, valueColumn, dateColumn (a header of dates or periods, "
        "or null), chart (line, column, or area), aggregate (sum, count, latest, min, "
        "or max), and reason. Use only the column names in this request.\n"
        + json.dumps(request)
    )
    try:
        raw = complete(prompt)
    except Exception as exc:  # noqa: BLE001 - the picker stays where it was
        raise ConfigError("config:suggest-failed", f"The endpoint failed: {exc}")
    start = str(raw or "").find("{")
    end = str(raw or "").rfind("}")
    if start < 0 or end <= start:
        raise ConfigError("config:suggest-failed", "The endpoint did not return a column choice.")
    try:
        parsed = json.loads(str(raw)[start:end + 1])
    except ValueError as exc:
        raise ConfigError("config:suggest-failed", f"The endpoint did not return a column choice: {exc}")
    if not isinstance(parsed, dict):
        raise ConfigError("config:suggest-failed", "The endpoint did not return a column choice.")
    names = [str(cell) for cell in (request.get("headers") or [])]
    headers = set(names)
    by_lower = {name.lower(): name for name in names}
    label = str(parsed.get("labelColumn") or "")
    value = str(parsed.get("valueColumn") or "")
    if headers and (label not in headers or value not in headers):
        raise ConfigError("config:suggest-failed", "The suggestion named a column that is not in the file.")
    aggregate = str(parsed.get("aggregate") or "sum").lower()
    if aggregate not in ("sum", "count", "latest", "min", "max"):
        aggregate = "sum"
    date = str(parsed.get("dateColumn") or "").strip()
    if not date or date.lower() == "null" or date.lower() == value.lower() or date.lower() not in by_lower:
        date = None
    else:
        date = by_lower[date.lower()]
    chart = str(parsed.get("chart") or "line").lower()
    if chart not in ("line", "column", "area"):
        chart = "line"
    return {
        "labelColumn": label,
        "valueColumn": value,
        "dateColumn": date,
        "chart": chart,
        "aggregate": aggregate,
        "rows": None,
        "reason": str(parsed.get("reason") or f"{value} looks like the amount; {label} groups rows."),
        "source": "model",
    }
