"""The live sales widget: watcher status rendered into the shell.

Mapping only: poll states become freshness and body content, delta rows
become example lines. Every dynamic value is escaped here before it
reaches pages.py, which treats widget footers and bodies as authored HTML.
"""

import html
from datetime import datetime

from agentdesk.excel.core import (
    STATE_FIRST_SNAPSHOT,
    STATE_HEALTHY,
    STATE_LOCKED,
    STATE_UNREADABLE,
)
from agentdesk.excel.store import WINDOW_24H
from agentdesk.server.core import ATTENTION, FRESH, Freshness
from agentdesk.server.demo import Widget

# Example rows shown on the card; the full delta lives in the API payload.
MAX_EXAMPLE_ROWS = 8


def render_sales_disabled(now: datetime) -> Widget:
    """The designed paused state: no ingestion, an honest stamp, and the
    reconnect path one click away."""
    return Widget(
        id="sales-24h",
        title="Sales, last 24 hours",
        col="col-7",
        freshness=Freshness(ATTENTION, "Paused", now.strftime("%Y-%m-%dT%H:%M:%S")),
        body_html=(
            '<div class="well"><p class="q">Sales watching is turned off in '
            "settings. Nothing is being read from the workbook right now.</p></div>"
            '<a class="btn btn-primary btn-start" href="/settings">Turn it back on</a>'
        ),
        foot_html="No ingestion while off. Your snapshots stay on this machine.",
    )


def render_sales_unconfigured(now: datetime) -> Widget:
    """The honest not-connected state: no numbers exist yet, so none are
    shown; the native picker is the only connect path, and its failure
    gets the amber note, never a typed-path form (the product line)."""
    return Widget(
        id="sales-24h",
        title="Sales, last 24 hours",
        col="col-7",
        freshness=Freshness(ATTENTION, "Not connected", now.strftime("%Y-%m-%dT%H:%M:%S")),
        body_html=(
            '<div class="well"><p class="q">No workbook is connected yet, so '
            "there is nothing to show here. Once one is connected, this card "
            "reports what changed in the file over the last 24 hours.</p></div>"
            '<button class="btn btn-primary btn-start" data-pick>Connect a workbook</button>'
            '<div class="alert" id="pick-note" hidden></div>'
        ),
        foot_html="Read-only: the file is picked with the file dialog, copied before parsing, never opened in place.",
    )


def _fmt(value) -> str:
    """Cell value to display text: whole numbers grouped, text as is."""
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    return str(value)


def _row_line(row: list) -> str:
    """One example row as a text line: its first four non-empty cells, joined.

    Grouped numbers come from _fmt, and the whole line is escaped as text because it
    lands inside a table cell as content, not markup.
    """
    cells = [_fmt(v) for v in row[:4] if v != ""]
    return html.escape(" · ".join(cells) if cells else "(empty row)")


def freshness_for(state: str, last_ok_ts: float | None) -> Freshness:
    """The freshness contract from a poll state and the last good poll."""
    if last_ok_ts is None:
        return Freshness(ATTENTION, "Never polled", "")
    when = datetime.fromtimestamp(last_ok_ts)
    hhmm = when.strftime("%H:%M")
    updated = when.strftime("%Y-%m-%dT%H:%M:%S")
    if state == "stale":
        return Freshness(ATTENTION, f"Stale since {hhmm}", updated)
    if state in (STATE_LOCKED, STATE_UNREADABLE):
        return Freshness(ATTENTION, f"Blocked, {hhmm}", updated)
    if state == STATE_FIRST_SNAPSHOT:
        return Freshness(FRESH, f"Snapshot {hhmm}", updated)
    return Freshness(FRESH, f"Updated {hhmm}", updated)


def _window_label(status: dict) -> "tuple[str, str, str]":
    """The KPI label, its sub line and the zero-change line, truthful
    about the diff window.

    The reference is the newest snapshot at or before the 24-hour mark, so
    up to one poll interval past 24 h is still the promised window; a
    longer gap (a closed laptop over a weekend) is named with its own
    length and moment, never rounded down to '24 hours'.
    """
    ref_ts = status.get("reference_ts")
    last_ok = status.get("last_ok_ts")
    if not ref_ts or not last_ok or (last_ok - ref_ts) <= WINDOW_24H + 3600.0:
        return (
            "Rows changed, 24 h",
            "Row-hash diff against the snapshot from 24 hours ago",
            "No changes in the last 24 hours.",
        )
    hours = int((last_ok - ref_ts) // 3600) + 1  # rounded up, never understated
    when = datetime.fromtimestamp(ref_ts).strftime("%b %d, %H:%M")
    return (
        f"Rows changed, {hours} h",
        f"Row-hash diff against the newest snapshot before the 24-hour mark ({when})",
        f"No changes in the last {hours} hours.",
    )


def _healthy_body(status: dict) -> str:
    """Body HTML for a healthy poll: the row-change count and examples.

    added and removed are the row-hash delta against the reference snapshot,
    whose true window _window_label names. At most MAX_EXAMPLE_ROWS of each
    are listed, and the remainder is counted in one trailing line so the
    card never implies it showed everything.
    """
    delta = status["delta"] or {"added": [], "removed": [], "unchanged": 0}
    added, removed = delta["added"], delta["removed"]
    changed = len(added) + len(removed)
    label, sub, empty_line = _window_label(status)
    parts = [
        '<div class="kpi"><div><div class="label">'
        f"{html.escape(label)}</div>"
        f'<div class="value">{changed}</div>'
        f'<div class="sub">{html.escape(sub)}</div></div></div>'
    ]
    if changed == 0:
        parts.append(f'<p class="empty">{html.escape(empty_line)}</p>')
        return "".join(parts)
    examples = [
        f'<span class="delta up">+</span> {_row_line(r)}' for r in added[:MAX_EXAMPLE_ROWS]
    ] + [f'<span class="delta down">-</span> {_row_line(r)}' for r in removed[:MAX_EXAMPLE_ROWS]]
    shown = len(added[:MAX_EXAMPLE_ROWS]) + len(removed[:MAX_EXAMPLE_ROWS])
    rows_html = "".join(f"<tr><td>{line}</td></tr>" for line in examples)
    if changed > shown:
        rows_html += f'<tr><td class="empty">+ {changed - shown} more row(s) in the full delta</td></tr>'
    parts.append(f'<table class="rows"><tbody>{rows_html}</tbody></table>')
    return "".join(parts)


def _amber_body(cause: str, with_retest: bool) -> str:
    """Body HTML for a blocked or stale poll: the cause, plus the Re-test button.

    The cause is escaped. The button is only included when with_retest is set.
    """
    parts = [f'<div class="alert"><span>{html.escape(cause)}</span></div>']
    if with_retest:
        parts.append(
            '<button class="btn btn-secondary btn-start" data-retest>Re-test now</button>'
        )
    return "".join(parts)


def render_sales_widget(status: dict) -> Widget:
    """The connected sales widget, in whichever state the last poll left it."""
    state = status["state"]
    fresh = freshness_for(state, status.get("last_ok_ts"))
    if state == STATE_HEALTHY:
        body = _healthy_body(status)
    elif state == STATE_FIRST_SNAPSHOT:
        body = (
            '<div class="well"><p class="q">First snapshot taken. '
            "The 24-hour view starts with the next poll; nothing is invented "
            "in the meantime.</p></div>"
        )
    elif state == "stale":
        body = _amber_body(
            "This data is old, so it is shown as stale rather than current. "
            "Re-test to refresh it now.",
            with_retest=True,
        )
    else:  # locked, unreadable
        body = _amber_body(status["cause"], with_retest=True)
    name = html.escape((status.get("path") or "workbook").rsplit("\\", 1)[-1].rsplit("/", 1)[-1])
    return Widget(
        id="sales-24h",
        title="Sales, last 24 hours",
        col="col-7",
        freshness=fresh,
        body_html=body,
        foot_html=f"Watches {name}, hourly, read-only. The file is copied before parsing, never opened in place.",
        extra_classes="amber" if state in ("stale", STATE_LOCKED, STATE_UNREADABLE) else "",
    )
