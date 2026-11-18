"""Calendar bridge: today's key commitment from the OneDrive JSON file.

The data path is deliberately humble (research A9.2 rule 4): a personal
Power Automate flow writes calendar_sync.json into OneDrive every 30
minutes, the built-in client syncs it local, and this module reads the
file. No Graph consent, no COM, immune to New Outlook. Missing or stale
data is a designed state that points at the walkthrough, never an error.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

# The synced file counts as stale after this long without a refresh. The
# flow writes every 30 minutes; six hours means the sync is genuinely
# broken, not merely between runs.
DEFAULT_STALE_S = 6 * 60 * 60.0


class CalendarUnreadable(Exception):
    """The calendar file exists but is not a calendar document."""


@dataclass(frozen=True)
class CalendarEvent:
    """One calendar entry as the flow writes it.

    Attendees arrive as a count or, when the flow provides them, as
    names; briefs use names when they exist and never invent them.
    """

    id: str
    subject: str
    start: datetime
    end: datetime
    location: str = ""
    attendees: int = 0
    attendee_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class CalendarDocument:
    generated_at: datetime
    events: list  # list[CalendarEvent]


def parse_calendar_document(raw: dict) -> CalendarDocument:
    """Validate and parse one calendar_sync.json body."""
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), list):
        raise CalendarUnreadable("the calendar file has no events list")
    events: list[CalendarEvent] = []
    for item in raw["events"]:
        try:
            raw_attendees = item.get("attendees", 0)
            if isinstance(raw_attendees, list):
                names = tuple(str(n) for n in raw_attendees if str(n).strip())
                count = len(names)
            else:
                names = ()
                count = int(raw_attendees)
            events.append(
                CalendarEvent(
                    id=str(item["id"]),
                    subject=str(item.get("subject", "Busy")),
                    start=_parse_dt(item["start"]),
                    end=_parse_dt(item.get("end", item["start"])),
                    location=str(item.get("location", "")),
                    attendees=count,
                    attendee_names=names,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CalendarUnreadable(f"an event is missing its time fields: {exc}") from exc
    generated = raw.get("generatedAt")
    return CalendarDocument(
        generated_at=_parse_dt(generated) if generated else datetime.now().astimezone(),
        events=events,
    )


def _parse_dt(value) -> datetime:
    """Parse an ISO timestamp into an aware datetime.

    A trailing Z is read as UTC; a value carrying no offset is taken as local
    time, which is what the flow writes when it emits a naive timestamp.
    """
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()  # naive flow output: treat as local
    return parsed


def pick_key_event(events: list, now: datetime) -> CalendarEvent | None:
    """Today's key commitment: the earliest event still ahead of the user.

    Events already over by more than their own length are behind you; the
    day's first one still worth walking into is the commitment. Nothing
    today means an honest empty day, not an error.
    """
    today = now.date()
    todays = [e for e in events if e.start.date() == today]
    todays.sort(key=lambda e: e.start)
    for event in todays:
        if event.end >= now - timedelta(minutes=15):  # small grace for overruns
            return event
    return None
