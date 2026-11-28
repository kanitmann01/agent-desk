"""Optional web research for one presentation run.

Off unless the user turns it on. The query is the topic and the planned
section titles. Memory and workbook text are not sent. At most five
results, and the fetch itself is bounded.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlsplit

RESULT_LIMIT = 5
FETCH_TIMEOUT_S = 10
MAX_RESPONSE_BYTES = 1_000_000

# Loopback hosts never leave this machine, so a research provider running
# beside the desk (a local gateway, a test stub) may speak plain http: the
# https rule exists to protect a key in transit, and there is no transit
# to protect on the loopback.
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _plain_http_allowed(url: str) -> bool:
    """Whether this URL may be plain http: loopback only, nothing else."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.hostname in _LOOPBACK_HOSTS


def fetch_sources(url: str, key: str, topic: str, sections: list[str],
                  timeout: float = FETCH_TIMEOUT_S, limit: int = RESULT_LIMIT) -> list[dict]:
    """POST the topic and section titles. Return at most `limit` sources.

    The provider URL must be https, the one exception being a loopback
    host (a local research gateway never leaves the machine, so plain
    http costs no secret in transit). The body is capped, so a huge
    response cannot be pulled into the prompt.
    """
    if not str(url).lower().startswith("https://") and not _plain_http_allowed(url):
        raise ValueError("the research provider URL must start with https://")
    payload = json.dumps({"topic": topic, "sections": list(sections)}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("the research response is too large")
    document = json.loads(raw.decode("utf-8"))
    rows = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        return []
    kept = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        kept.append({
            "title": str(row.get("title") or "")[:200],
            "url": str(row.get("url") or "")[:500],
            "snippet": str(row.get("snippet") or "")[:500],
        })
    return kept


def as_sources(rows: list[dict], start_id: int) -> list[dict]:
    """Web rows as numbered sources, continuing after the desk sources."""
    sources = []
    for offset, row in enumerate(rows):
        sources.append({
            "id": start_id + offset,
            "kind": "web-research",
            "label": row.get("title") or row.get("url") or "Web",
            "text": row.get("snippet") or "",
            "at": "",
            "url": row.get("url") or "",
            "title": row.get("title") or "",
            "snippet": row.get("snippet") or "",
        })
    return sources
