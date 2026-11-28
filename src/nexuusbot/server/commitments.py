"""The commitments widget: bridge status rendered into the shell, plus
the calendar walkthrough page. Mapping only; every dynamic value is
escaped here before it reaches pages.py.
"""

import html
from datetime import datetime

from nexuusbot import PRODUCT_NAME
from nexuusbot.calendar.watcher import (
    STATE_CLEAR,
    STATE_EMPTY,
    STATE_HEALTHY,
    STATE_STALE,
    STATE_UNREADABLE,
)
from nexuusbot.server.core import ATTENTION, FRESH, Freshness
from nexuusbot.server.demo import Widget

WALKTHROUGH_PATH = "/walkthrough/calendar"

_CHECK_ON_SVG = (
    '<span class="box" aria-hidden="true"><svg width="11" height="11" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>'
)


def freshness_for(state: str, generated_at: datetime | None, now: datetime) -> Freshness:
    """Freshness from the bridge state and the file's own timestamp."""
    if generated_at is None:
        return Freshness(ATTENTION, "No calendar data", "")
    hhmm = generated_at.strftime("%H:%M")
    updated = generated_at.strftime("%Y-%m-%dT%H:%M:%S")
    if state in (STATE_STALE, STATE_UNREADABLE):
        return Freshness(ATTENTION, f"Stale, {hhmm}", updated)
    return Freshness(FRESH, f"Synced {hhmm}", updated)


def _check_line(idx: int, text: str, checked: bool, event_id: str) -> str:
    """One breakdown subtask as a toggleable check row.

    The data-check, data-event and data-idx attributes are the handles the page script
    toggles and posts back; idx is the subtask's position in its breakdown, and text is
    escaped here.
    """
    return (
        f'<div class="check" role="checkbox" aria-checked="{"true" if checked else "false"}" '
        f'tabindex="0" data-check data-event="{html.escape(event_id)}" data-idx="{idx}">'
        f"{_CHECK_ON_SVG}<span>{html.escape(text)}</span></div>"
    )


def _healthy_body(status: dict) -> str:
    """Body HTML for a healthy bridge: the key event, its breakdown and follow-ups.

    start and end are parsed as ISO datetimes and rendered as two times in one cell.
    Subtasks become check rows keyed by their stringified index, which is the key checks
    uses; each follow-up carries its deadline when it has one.
    """
    event = status["keyEvent"]
    start = datetime.fromisoformat(event["start"])
    end = datetime.fromisoformat(event["end"])
    when = f"{start.strftime('%H:%M')}<br>{end.strftime('%H:%M')}"
    where = f"<small>{html.escape(event['location'])}" if event.get("location") else "<small>"
    if event.get("attendees"):
        where += f", {event['attendees']} attendees"
    parts = [
        '<div class="event"><span class="when">' + when + "</span><div><b>"
        + html.escape(event["subject"]) + "</b>" + where + "</small></div></div>"
    ]
    breakdown = status.get("breakdown") or {"subtasks": [], "followups": []}
    parts.append('<div><div class="subhead subhead-tight">Agent\'s breakdown</div>')
    checks = status.get("checks") or {}
    for idx, text in enumerate(breakdown.get("subtasks", [])):
        parts.append(_check_line(idx, text, bool(checks.get(str(idx))), event["id"]))
    parts.append("</div>")
    for followup in breakdown.get("followups", []):
        deadline = followup.get("deadline", "")
        label = html.escape(followup["text"])
        if deadline:
            label += ", by " + html.escape(deadline)
        parts.append(f'<span class="follow">{label}</span>')
    return "".join(parts)


def render_commitments_unavailable(now: datetime) -> Widget:
    """The bridge itself is not running (its store could not open): the
    plain truth, with no invented meeting in the meantime."""
    return Widget(
        id="key-commitment",
        title="Today's key commitment",
        col="col-5",
        freshness=Freshness(ATTENTION, "Unavailable", now.strftime("%Y-%m-%dT%H:%M:%S")),
        body_html=(
            '<div class="well"><p class="q">The calendar bridge is not running '
            "on this machine, so today's commitments cannot be read. Restarting "
            f"{PRODUCT_NAME} usually brings it back.</p></div>"
        ),
        foot_html="Nothing is being read while the bridge is unavailable.",
    )


def render_commitments_widget(status: dict, now: datetime) -> Widget | None:
    """The connected commitments widget in whichever state the bridge is in."""
    state = status["state"]
    # The file's own generatedAt is the freshness truth.
    generated = (
        datetime.fromisoformat(status["generatedAt"]) if status.get("generatedAt") else None
    )
    fresh = freshness_for(state, generated, now)

    if state == "disabled":
        return Widget(
            id="key-commitment",
            title="Today's key commitment",
            col="col-5",
            freshness=Freshness(ATTENTION, "Paused", ""),
            body_html=(
                '<div class="well"><p class="q">Calendar reading is turned off in '
                "settings. Your day is not being read right now.</p></div>"
                '<a class="btn btn-primary btn-start" href="/settings">Turn it back on</a>'
            ),
            foot_html="No ingestion while off.",
        )
    if state == STATE_HEALTHY:
        body = _healthy_body(status)
        foot = "From your calendar via the OneDrive sync. Nothing leaves the machine but the meeting's name."
        extra = ""
    elif state == STATE_CLEAR:
        body = '<div class="well"><p class="q">Your calendar is clear for the rest of today. Nothing needs preparing.</p></div>'
        foot = "From your calendar via the OneDrive sync."
        extra = ""
    elif state == STATE_EMPTY:
        body = (
            f'<div class="well"><p class="q">No calendar data yet. {PRODUCT_NAME} watches '
            '<span class="id-scroll"><code class="nowrap">agent-desk/calendar_sync.json'
            "</code></span> in your OneDrive. A 3-step "
            "browser walkthrough creates the flow that writes it.</p></div>"
            f'<a class="btn btn-primary btn-start" href="{WALKTHROUGH_PATH}">Connect your calendar</a>'
        )
        foot = "Setup happens in your browser. No terminal, no admin."
        extra = ""
    elif state == STATE_STALE:
        body = (
            f'<div class="alert"><span>{html.escape(status["cause"])}</span></div>'
            '<button class="btn btn-secondary btn-start" data-calendar-retest>Re-test now</button>'
            f'<a class="btn btn-secondary btn-start" href="{WALKTHROUGH_PATH}">Open the walkthrough</a>'
        )
        foot = "Stale data is labeled, never shown as current."
        extra = "amber"
    else:  # unreadable
        body = (
            f'<div class="alert"><span>{html.escape(status["cause"])}</span></div>'
            '<button class="btn btn-secondary btn-start" data-calendar-retest>Re-test now</button>'
        )
        foot = "The file is there but not readable as calendar data."
        extra = "amber"

    first = status.get("firstDetected")
    if first and state == STATE_HEALTHY:
        detected = datetime.fromisoformat(first)
        foot += f" Connected {detected.strftime('%H:%M')}."

    return Widget(
        id="key-commitment",
        title="Today's key commitment",
        col="col-5",
        freshness=fresh,
        body_html=body,
        foot_html=foot,
        extra_classes=extra,
    )
