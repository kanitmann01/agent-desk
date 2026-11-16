"""A column suggestion. Nothing is sent until the user presses Suggest,
and the disclosure sentence is the list of what leaves the machine.
"""

from __future__ import annotations

import json

from agentdesk.plugins.config import ConfigError

DISCLOSURE_ROWS = (
    "This sends the column names and up to 5 rows to the company endpoint. "
    "The file path stays on this machine."
)
DISCLOSURE_HEADERS = (
    "This sends the column names to the company endpoint. "
    "No cell values and no file path leave this machine."
)
_MAX_BYTES = 8192
_MAX_ROWS = 5


def build_suggestion_request(*, job, sheet, headers, rows, headers_only, path) -> tuple[dict, str]:
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


def propose_columns(request: dict, complete) -> dict:
    prompt = (
        "Choose which columns to track. Reply with one JSON object and nothing else, "
        "with keys labelColumn, valueColumn, and aggregate (sum, count, latest, min, or max). "
        "Use only the column names in this request.\n"
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
    headers = set(request.get("headers") or [])
    label = str(parsed.get("labelColumn") or "")
    value = str(parsed.get("valueColumn") or "")
    if headers and (label not in headers or value not in headers):
        raise ConfigError("config:suggest-failed", "The suggestion named a column that is not in the file.")
    aggregate = str(parsed.get("aggregate") or "sum").lower()
    if aggregate not in ("sum", "count", "latest", "min", "max"):
        aggregate = "sum"
    return {"labelColumn": label, "valueColumn": value, "aggregate": aggregate}
