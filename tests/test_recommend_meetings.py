"""The meeting-prep rule: a calendar event naming a known account becomes
a recommendation (spec 016 §6.3, ticket #197).

The rule is pure and runs on a frozen clock. The builder tests use the real
inbox and ledger with a small calendar fake, because the withdrawal promise
is about the card row, not about parsing a calendar file. The server test
covers the sample path end to end: Sample data on gives a Prep row on the
dashboard payload.
"""

import datetime
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from nexuusbot.calendar.watcher import Adapters as CalendarAdapters, CalendarBridge
from nexuusbot.inbox.core import STATUS_DISMISSED
from nexuusbot.inbox.store import InboxStore
from nexuusbot.ledger.store import Ledger
from nexuusbot.memory.core import EntitySummary, Fact
from nexuusbot.memory.store import MemoryStore
from nexuusbot.recommend.builder import RecommendationBuilder
from nexuusbot.recommend.rules import meeting_candidates
from nexuusbot.server import demo_data
from nexuusbot.settings import SettingsStore

MORNING = datetime.datetime(2026, 11, 20, 9, 0, 0)


class Clock:
    """A settable clock shared by every store in one test."""

    def __init__(self, moment: datetime.datetime) -> None:
        self.ts = moment.astimezone().timestamp()

    def __call__(self) -> float:
        return self.ts


class FakeCalendar:
    """The small part of the calendar bridge the builder reads."""

    def __init__(self, events) -> None:
        self.events = list(events)

    def upcoming(self, now: datetime.datetime, within_hours: float = 1.0) -> list:
        horizon = now + datetime.timedelta(hours=within_hours)
        return [event for event in self.events if now <= event.start <= horizon]


class FakeMemory:
    """The small part of the memory store the builder reads."""

    def __init__(self, facts, entities, links) -> None:
        self.facts = list(facts)
        self._entities = list(entities)
        self._links = dict(links)

    def all(self):
        return list(self.facts)

    def superseded_map(self):
        return {}

    def entities(self):
        return list(self._entities)

    def fact_entity_ids(self):
        return dict(self._links)


def _event(subject: str, start: datetime.datetime, event_id: str = "evt-1"):
    return SimpleNamespace(id=event_id, subject=subject, start=start, end=start + datetime.timedelta(hours=1))


def _fact(fact_id: int, text: str, created: float) -> Fact:
    return Fact(id=fact_id, text=text, source="page", created_ts=created)


def test_meeting_match_cites_three_newest():
    now = MORNING.astimezone()
    event = _event("Harborlight Freight renewal call", now + datetime.timedelta(hours=3))
    facts = [
        _fact(1, "Oldest Harborlight fact.", 100.0),
        _fact(2, "Second Harborlight fact.", 200.0),
        _fact(3, "Third Harborlight fact.", 300.0),
        _fact(4, "Newest Harborlight fact.", 400.0),
    ]

    candidates = meeting_candidates(
        [event],
        {7: "Harborlight Freight"},
        {7: facts},
        now,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.rule == "meeting-prep"
    assert candidate.key == "meeting-prep:evt-1:2026-11-20"
    assert candidate.title == (
        "Prep for Harborlight Freight renewal call: 3 things you know about Harborlight Freight"
    )
    assert candidate.cites == (4, 3, 2)
    assert candidate.href == "/assistant"
    assert candidate.action_label == "Prep in Assistant"
    assert candidate.body.count("\n") == 2
    assert "Newest Harborlight fact." in candidate.body.splitlines()[0]


def test_no_match_no_card():
    now = MORNING.astimezone()
    event = _event("Quarterly all hands", now + datetime.timedelta(hours=2))
    candidates = meeting_candidates(
        [event],
        {7: "Harborlight Freight"},
        {7: [_fact(1, "Harborlight fact.", 100.0)]},
        now,
    )
    assert candidates == []


def test_the_match_folds_case():
    now = MORNING.astimezone()
    event = _event("HARBORLIGHT FREIGHT renewal call", now + datetime.timedelta(hours=2))
    candidates = meeting_candidates(
        [event],
        {7: "Harborlight Freight"},
        {7: [_fact(1, "Harborlight fact.", 100.0)]},
        now,
    )
    assert len(candidates) == 1
    assert candidates[0].title.startswith("Prep for HARBORLIGHT FREIGHT renewal call")


def test_past_events_and_far_events_do_not_become_cards():
    now = MORNING.astimezone()
    events = [
        _event("Harborlight Freight yesterday", now - datetime.timedelta(hours=2), "past"),
        _event("Harborlight Freight next week", now + datetime.timedelta(days=7), "far"),
    ]
    assert meeting_candidates(
        events, {7: "Harborlight Freight"}, {7: [_fact(1, "Harborlight fact.", 100.0)]}, now
    ) == []


def _builder(settings: dict | None = None, settings_store: SettingsStore | None = None):
    clock = Clock(MORNING)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    settings_store = settings_store or SettingsStore(conn, clock)
    settings_store.set("recommend_deadlines", False)
    for key, value in (settings or {}).items():
        settings_store.set(key, value)
    inbox = InboxStore(conn, clock)
    ledger = Ledger(":memory:", clock=clock)
    now = MORNING.astimezone()
    event = _event("Harborlight Freight renewal call", now + datetime.timedelta(hours=3))
    facts = [
        _fact(1, "Oldest Harborlight fact.", 100.0),
        _fact(2, "Second Harborlight fact.", 200.0),
        _fact(3, "Third Harborlight fact.", 300.0),
        _fact(4, "Newest Harborlight fact.", 400.0),
    ]
    memory = FakeMemory(
        facts,
        [EntitySummary(id=7, canonical_name="Harborlight Freight", type="org", fact_count=4)],
        {1: [7], 2: [7], 3: [7], 4: [7]},
    )
    calendar = FakeCalendar([event])
    builder = RecommendationBuilder(
        inbox=inbox,
        memory=memory,
        calendar=calendar,
        settings=settings_store,
        ledger=ledger,
        clock=clock,
    )
    return builder, calendar, clock, event, inbox


def test_withdraw_when_event_leaves_window():
    builder, calendar, _clock, _event_value, inbox = _builder()
    assert builder.refresh() == {"added": 1, "withdrawn": 0}
    card = builder.waiting()[0]
    assert card.meta["recommendation"]["rule"] == "meeting-prep"

    calendar.events = []
    assert builder.refresh() == {"added": 0, "withdrawn": 1}
    gone = inbox.get(card.id)
    assert gone.status == STATUS_DISMISSED
    assert "meeting" in gone.origin.lower()
    assert builder.waiting() == []


def test_unread_calendar_keeps_the_waiting_card():
    builder, calendar, _clock, _event_value, _inbox = _builder()
    assert builder.refresh() == {"added": 1, "withdrawn": 0}

    calendar.events = []
    calendar.has_document = lambda: False
    assert builder.refresh() == {"added": 0, "withdrawn": 0}
    assert len(builder.waiting()) == 1

    calendar.has_document = lambda: True
    assert builder.refresh() == {"added": 0, "withdrawn": 1}
    assert builder.waiting() == []


def test_past_start_does_not_withdraw():
    builder, calendar, clock, event, _inbox = _builder()
    assert builder.refresh() == {"added": 1, "withdrawn": 0}

    clock.ts = (event.start + datetime.timedelta(minutes=30)).timestamp()
    calendar.events = []
    assert builder.refresh() == {"added": 0, "withdrawn": 0}
    assert len(builder.waiting()) == 1


def test_not_now_permanent():
    builder, _calendar, _clock, _event_value, inbox = _builder()
    assert builder.refresh()["added"] == 1
    card = builder.waiting()[0]
    inbox.dismiss(card.id)
    assert builder.refresh() == {"added": 0, "withdrawn": 0}
    assert builder.waiting() == []


def test_disabled_switch():
    builder, _calendar, _clock, _event_value, _inbox = _builder({"recommend_meetings": False})
    assert builder.refresh() == {"added": 0, "withdrawn": 0}
    assert builder.waiting() == []


def test_turning_the_switch_off_leaves_the_waiting_card_alone():
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), Clock(MORNING))
    builder, _calendar, _clock, _event_value, _inbox = _builder(settings_store=settings)
    assert builder.refresh()["added"] == 1

    settings.set("recommend_meetings", False)

    assert builder.refresh() == {"added": 0, "withdrawn": 0}
    assert len(builder.waiting()) == 1


def test_sample_calendar_names_a_sample_account():
    """The sample calendar must exercise the meeting rule, not just parse."""
    document = json.loads(demo_data.sample_calendar_bytes(MORNING.astimezone()))
    subjects = " ".join(item["subject"] for item in document["events"])
    assert "Harborlight" in subjects


def _stores():
    clock = Clock(MORNING)
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    settings.set("recommend_deadlines", False)
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    memory = MemoryStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    ledger = Ledger(":memory:", clock=clock)
    return settings, inbox, memory, ledger, clock


def test_server_dashboard_shows_the_prep_row_with_sample_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "desk-data"))
    settings, inbox, memory, ledger, clock = _stores()
    calendar = CalendarBridge(
        sqlite3.connect(":memory:", check_same_thread=False),
        CalendarAdapters(read_calendar=lambda: None, clock=clock),
        llm=lambda prompt: "",
    )
    booted = server_harness.Booted(
        settings_store=settings,
        inbox_store=inbox,
        memory_store=memory,
        ledger=ledger,
        calendar=calendar,
    )
    try:
        auth = booted.exchange()
        status, _headers, body = booted.post_json(
            "/settings/toggle", {"key": "sample_data"}, auth
        )
        assert status == 200, body

        status, _headers, body = booted.request("GET", "/api/dashboard", auth)
        assert status == 200
        rows = [
            row for row in json.loads(body)["recommendations"]
            if row["title"].startswith("Prep for ")
        ]
        assert len(rows) == 1
        row = rows[0]
        assert row["title"] == (
            "Prep for Harborlight Freight renewal call: 3 things you know about Harborlight Freight"
        )
        assert row["whySource"] == "rule"
        assert row["actionLabel"] == "Prep in Assistant"
        assert row["href"] == "/assistant"
        assert row["sample"] is True
        assert len(row["cites"]) == 3

        status, _headers, page = booted.request("GET", "/", auth)
        assert status == 200
        text = page.decode("utf-8")
        assert "Prep for Harborlight Freight renewal call" in text
        assert "Prep in Assistant" in text
        assert 'href="/assistant"' in text
    finally:
        booted.close()