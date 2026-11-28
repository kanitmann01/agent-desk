"""Pre-meeting briefs, calendar-only.

The brief is assembled from data already in the app: the meeting's own
details, open commitments and follow-up chips involving its attendees,
and what the research panel has been asked about them. Only when at
least one of those connects does a brief exist: a meeting with nothing
to say produces no card. Mail and message bodies are structurally
absent: there is no input here that could carry them, and the brief's
payload enumerates its sources so that stays checkable.
"""

import json
from datetime import datetime

from nexuusbot.calendar.store import get_checks
from nexuusbot.inbox.store import InboxStore
from nexuusbot.repetition.activity import ActivityLog

SOURCES = ["calendar", "commitments", "research_history"]
LEAD_HOURS = 1.0


def _match(names: tuple[str, ...], text: str) -> bool:
    """Return True when any of the names appears in text, ignoring case.

    Names of two characters or fewer are skipped: a substring that short
    matches ordinary prose and would connect a meeting to unrelated text.
    """
    lowered = text.lower()
    return any(name.lower() in lowered for name in names if len(name) > 2)


def _open_commitments(conn, event_id: str) -> list[str]:
    """Unchecked subtasks for one event, from the newest real breakdown.

    Generic fallback breakdowns are advice, not tracked commitments, and
    never become brief lines."""
    rows = conn.execute(
        "SELECT payload FROM breakdowns WHERE cache_key LIKE ? ORDER BY rowid DESC",
        (f"{event_id}:%",),
    )
    for (payload,) in rows:
        parsed = json.loads(payload)
        if parsed.get("fallback"):
            continue  # advice, not commitments; an older real one may exist
        checks = get_checks(conn, event_id)
        return [s for i, s in enumerate(parsed.get("subtasks", [])) if not checks.get(i)]
    return []


def _followups(conn, names: tuple[str, ...]) -> list[str]:
    """Follow-up chips from any real breakdown that name an attendee."""
    out: list[str] = []
    for (payload,) in conn.execute("SELECT payload FROM breakdowns"):
        parsed = json.loads(payload)
        if parsed.get("fallback"):
            continue
        for followup in parsed.get("followups", []):
            text = followup.get("text", "")
            if text and _match(names, text) and text not in out:
                out.append(text)
    return out


def _research_lines(activity: ActivityLog, names: tuple[str, ...]) -> list[str]:
    """Return "You asked:" lines for research turns that name an attendee.

    Only the newest 200 activity entries are searched, oldest first, and each
    line appears once.
    """
    out: list[str] = []
    for entry in activity.entries(200):
        if entry["kind"] not in ("research", "assistant"):
            continue
        if _match(names, entry["text"]):
            line = f"You asked: {entry['text']}"
            if line not in out:
                out.append(line)
    return out


def generate_briefs(bridge, inbox: InboxStore, activity: ActivityLog, clock, lead_hours: float = LEAD_HOURS) -> int:
    """Create brief cards for upcoming meetings worth briefing. Returns
    the number created; one brief per meeting, ever."""
    now = datetime.fromtimestamp(clock()).astimezone()
    upcoming = bridge.upcoming(now, within_hours=lead_hours)
    if not upcoming:
        return 0
    conn = bridge.conn
    created = 0
    for event in upcoming:
        if _has_brief(inbox, event.id):
            continue
        names = event.attendee_names
        lines: list[str] = []
        if names:
            lines.append("Attendees: " + ", ".join(names))
        elif event.attendees:
            lines.append(f"Attendees: {event.attendees} people")
        for commitment in _open_commitments(conn, event.id):
            lines.append(f"Open commitment: {commitment}")
        for followup in _followups(conn, names):
            lines.append(f"Follow-up chip: {followup}")
        for research_line in _research_lines(activity, names):
            lines.append(research_line)
        if len(lines) <= 1:
            continue  # only-when-actionable: a bare meeting is not a brief
        window = max(0.5, (event.start - now).total_seconds() / 3600)
        inbox.add(
            kind="brief",
            origin=f"Before your {event.start.strftime('%H:%M')} {event.subject}.",
            title=event.subject,
            body="\n".join(lines),
            action_label="Got it",
            window_hours=round(window, 2),
            meta={"meetingId": event.id, "sources": SOURCES},
        )
        created += 1
    return created


def _has_brief(inbox: InboxStore, meeting_id: str) -> bool:
    """Return True when a card in any status carries this meeting's id.

    Every status counts: one brief per meeting, ever. Accepted cards are
    read here too, so a "Got it" cannot mint a twin of the brief it
    answered, and snoozed and dismissed cards count as before (hiding a
    brief for an hour must not mint a twin of it).
    """
    return any(card.meta.get("meetingId") == meeting_id for card in inbox.all_cards())
