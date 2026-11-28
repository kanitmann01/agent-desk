"""The one no-JS authored-HTML renderer for plugin elements.

The dashboard serves plugin cards as HTML on the pages that have no SPA, and
this module is the renderer those pages use for every element kind. The SPA
draws the same payload through ElementView; keeping both surfaces on the same
vocabulary is what makes the HTML card and the JSON card describe one reading.
Nothing a plugin reports is trusted markup: every value is escaped here.
"""

from __future__ import annotations

import html
import math

from nexuusbot.plugins.vocabulary import (
    CHECKLIST,
    DELTA,
    LIST,
    METRIC,
    PROGRESS,
    SPARKLINE,
    STATUS,
    TABLE,
    TEXT,
    TIMELINE,
)


def element_html(element: dict) -> str:
    """Render one payload element as authored HTML, escaped at this boundary.

    Unknown kinds and malformed elements render as the empty string, so a page
    skips an element it cannot draw rather than showing half a card. The
    return value is markup for one element only; callers join elements.
    """
    if not isinstance(element, dict):
        return ""
    renderer = _RENDERERS.get(element.get("kind"))
    if renderer is None:
        return ""
    return renderer(element)


def _escape(value: object) -> str:
    """Escape any reported value for use as HTML text."""
    return html.escape(str(value))


def _label_line(element: dict) -> str:
    """Return the element's optional label as a note paragraph, or ""."""
    label = str(element.get("label") or "").strip()
    if not label:
        return ""
    return '<p class="w-note">' + _escape(label) + "</p>"


def _title_line(element: dict) -> str:
    """Return the element's optional title as a note paragraph, or ""."""
    title = str(element.get("title") or "").strip()
    if not title:
        return ""
    return '<p class="w-note">' + _escape(title) + "</p>"


def _number(value: object) -> float | None:
    """Read a finite number from a reported value, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _format_number(value: float) -> str:
    """Format a number for a note: whole values plain, everything else two decimals."""
    return str(int(value)) if value.is_integer() else f"{value:.2f}"


def _render_metric(element: dict) -> str:
    """Draw a metric as its large value plus an optional label."""
    value = '<p class="w-big">' + _escape(element.get("value", "")) + "</p>"
    return value + _label_line(element)


def _render_text(element: dict) -> str:
    """Draw a text element as its one note paragraph."""
    return '<p class="w-note">' + _escape(element.get("text", "")) + "</p>"


def _render_delta(element: dict) -> str:
    """Draw a delta as one note line: label, value and direction."""
    label = str(element.get("label") or "").strip()
    value = _escape(element.get("value", ""))
    direction = str(element.get("direction") or "").strip()
    text = (_escape(label) + ": " if label else "") + value
    if direction:
        text += " " + _escape(direction)
    return '<p class="w-note">' + text + "</p>"


def _render_progress(element: dict) -> str:
    """Draw a progress bar with its value-of-target note, or nothing lacking a value."""
    value = _number(element.get("value"))
    if value is None:
        return ""
    target = _number(element.get("target"))
    unit = str(element.get("unit") or "").strip()
    parts = []
    if target is not None and target > 0:
        percent = max(0.0, min(100.0, value / target * 100.0))
        shown = round(percent)
        parts.append(
            '<div class="w-progress" role="progressbar" aria-valuemin="0" '
            'aria-valuemax="100" aria-valuenow="' + str(shown) + '">'
            '<span style="width: ' + str(shown) + '%"></span></div>'
        )
        note = _format_number(value) + " of " + _format_number(target)
        if unit:
            note += " " + unit
    else:
        note = "No target reported."
    parts.append('<p class="w-note">' + _escape(note) + "</p>")
    return "".join(parts)


def _row_cells(row: object) -> list[str]:
    """Read one table row as display cells, whether it is a list or a mapping."""
    if isinstance(row, dict):
        return [str(row.get(key) or "").strip()
                for key in ("primary", "secondary", "meta")]
    if isinstance(row, (list, tuple)):
        return [str(cell) for cell in row]
    return []


def _render_list(element: dict) -> str:
    """Draw a list as its title plus one note line per row's cells."""
    lines = []
    title = str(element.get("title") or "").strip()
    if title:
        lines.append('<p class="w-note">' + _escape(title) + "</p>")
    rows = element.get("rows")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        text = " · ".join(
            str(row.get(key) or "").strip()
            for key in ("primary", "secondary", "meta")
            if str(row.get(key) or "").strip()
        )
        if text:
            lines.append('<p class="w-note">' + _escape(text) + "</p>")
    return "".join(lines)


def _render_table(element: dict) -> str:
    """Draw a table from its columns and rows, under an optional title."""
    columns = element.get("columns")
    columns = [str(column) for column in columns] if isinstance(columns, list) else []
    if not columns:
        return ""
    head = "".join("<th>" + _escape(column) + "</th>" for column in columns)
    rows = element.get("rows")
    body = []
    for row in rows if isinstance(rows, list) else []:
        cells = _row_cells(row)
        if not cells:
            continue
        body.append("<tr>" + "".join("<td>" + _escape(cell) + "</td>" for cell in cells) + "</tr>")
    return (
        _title_line(element)
        + '<div class="table-scroll"><table class="w-table"><thead><tr>' + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _render_sparkline(element: dict) -> str:
    """Draw a sparkline as an inline SVG line over its numeric points."""
    points = element.get("points")
    values = []
    for point in points if isinstance(points, list) else []:
        number = _number(point)
        if number is not None:
            values.append(number)
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = high - low or 1.0
    coords = " ".join(
        f"{index / (len(values) - 1) * 100:.1f},{28 - (value - low) / span * 24:.1f}"
        for index, value in enumerate(values)
    )
    label = str(element.get("label") or "").strip() or "History"
    return (
        _label_line(element)
        + '<svg class="w-spark" viewBox="0 0 100 30" role="img" aria-label="'
        + _escape(label)
        + '"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="'
        + coords
        + '"/></svg>'
    )


def _render_status(element: dict) -> str:
    """Draw a status as its one note paragraph; tone is colour, not text."""
    return '<p class="w-note">' + _escape(element.get("text") or "") + "</p>"


def _render_timeline(element: dict) -> str:
    """Draw a timeline as an ordered list of time, title and meta per item."""
    items = element.get("items")
    entries = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    lines = []
    for item in entries:
        time = str(item.get("time") or "").strip()
        title = str(item.get("title") or "").strip()
        meta = str(item.get("meta") or "").strip()
        if not (time or title or meta):
            continue
        parts = []
        if time:
            parts.append('<span class="w-list-meta">' + _escape(time) + "</span>")
        if title:
            parts.append('<span class="w-list-primary">' + _escape(title) + "</span>")
        if meta:
            parts.append('<span class="w-list-secondary">' + _escape(meta) + "</span>")
        lines.append("<li>" + "".join(parts) + "</li>")
    if not lines:
        return ""
    return _title_line(element) + '<ol class="w-timeline">' + "".join(lines) + "</ol>"


def _render_checklist(element: dict) -> str:
    """Draw a checklist as its title plus one note line per item text."""
    lines = []
    title = str(element.get("title") or "").strip()
    if title:
        lines.append('<p class="w-note">' + _escape(title) + "</p>")
    items = element.get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            lines.append('<p class="w-note">' + _escape(text) + "</p>")
    return "".join(lines)


# One renderer per vocabulary kind, keyed by the kind names themselves.
_RENDERERS = {
    METRIC: _render_metric,
    TEXT: _render_text,
    DELTA: _render_delta,
    PROGRESS: _render_progress,
    LIST: _render_list,
    TABLE: _render_table,
    SPARKLINE: _render_sparkline,
    STATUS: _render_status,
    TIMELINE: _render_timeline,
    CHECKLIST: _render_checklist,
}
