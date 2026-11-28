"""The provenance contract: a reading can say why, and cite its facts.

Wave 1 ticket 01 pins the `why` drilldown before any surface draws it:

- An integer fact id rides through recall and the agenda helper so a
  citation can name a fact without quoting it; a bool is not an id, and
  the mock `Fact(text, source)` rows the seam tests use keep their exact
  shape.
- `blocks` resolves the reading's why onto the receipts block, keeping
  only the five bounded fields (claim, columns, cells capped at six,
  rule, fact citations) and never a fact's text; an empty why leaves the
  blocks byte-identical to what the pinned tests already assert.
- The digest and calendar families populate why with the matched thread
  or meeting, the rule and threshold (focus and prep window included)
  and the cited fact ids, without moving an element or a receipt.
- The connect step exposes the entities its line names, as a pure
  projection, without changing `connect_line`'s own shape.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from types import SimpleNamespace

from nexuusbot.insight import agenda, calendar, digest, insight_connect
from nexuusbot.insight import reading as presentation
from nexuusbot.insight import service
from nexuusbot.insight.context import build_context
from nexuusbot.insight.preferences import defaults
from nexuusbot.insight.types import InsightContext, InsightReading

NOW = 1_760_000_000.0


def _context(**kwargs) -> InsightContext:
    preferences = kwargs.pop("preferences", {})
    return InsightContext(preferences=preferences, now=NOW, **kwargs)


def _card(elements=None) -> dict:
    return {
        "id": "excel-report",
        "pluginId": "excel-report",
        "payload": {"elements": list(elements or [{"kind": "metric", "value": "91"}]),
                    "status": "fresh"},
    }


@dataclass
class _Fact:
    """A memory fact object, with the optional integer id a store carries."""

    text: str
    source: str
    id: int | None = None


def _recall_with_ids(subject: str, limit: int = 3) -> list[dict]:
    """Two facts that mention a pricing subject, each carrying its id."""
    return [
        {"text": "Priya owns the pricing model.", "source": "notes", "id": 7},
        {"text": "The pricing sheet is in the drive folder.", "source": "drive", "id": 11},
    ][:limit]


# -- the reading gains why and falsify at the end -------------------------


def test_the_reading_gains_why_and_falsify_at_the_end_of_its_fields():
    names = [field.name for field in dataclasses.fields(InsightReading)]
    assert names[:-2] == [
        "elements", "suggested", "press", "note", "status",
        "used", "inputs", "memory_notes",
    ]
    assert names[-2:] == ["why", "falsify"]
    # An old positional construction still says what it did.
    reading = InsightReading(
        [{"kind": "text", "text": "x"}], (1,), None, "note", "ok", ("chart",), ("rows",), 2
    )
    assert reading.used == ("chart",) and reading.memory_notes == 2
    assert reading.why == () and reading.falsify == ""


# -- the integer fact id rides along --------------------------------------


def test_recall_preserves_an_integer_fact_id():
    memory = SimpleNamespace(
        is_sealed=False,
        recall=lambda query: [(0.9, _Fact("pricing call", "inbox", id=5))],
    )
    context = build_context(SimpleNamespace(memory=memory), defaults())

    assert context.recall("pricing", 3) == [
        {"text": "pricing call", "source": "inbox", "id": 5}
    ]


def test_recall_excludes_a_bool_id_and_the_mock_fact_stays_exact():
    class Fact:
        """The mock the seam tests build: no id attribute at all."""

        def __init__(self, text, source):
            self.text = text
            self.source = source

    memory = SimpleNamespace(
        is_sealed=False,
        recall=lambda query: [
            (0.9, Fact("pricing call", "inbox")),
            (0.8, _Fact("second fact", "mail", id=True)),
            (0.7, _Fact("third fact", "notes", id=False)),
        ],
    )
    context = build_context(SimpleNamespace(memory=memory), defaults())

    assert context.recall("anything", 3) == [
        {"text": "pricing call", "source": "inbox"},
        {"text": "second fact", "source": "mail"},
        {"text": "third fact", "source": "notes"},
    ]


def test_recalled_preserves_the_id_the_adapter_carried():
    def recall(subject, limit):
        return [
            {"text": "Priya owns the pricing model.", "source": "notes", "id": 4},
            {"text": "The pricing sheet is on the drive.", "source": "drive", "id": True},
            {"text": "Another pricing note.", "source": "mail"},
        ]

    ctx = _context(recall=recall)
    rows = agenda.recalled(ctx, "Quarterly pricing review", limit=3)
    assert rows[0] == {
        "text": "Priya owns the pricing model.", "source": "notes", "id": 4
    }
    # A bool is not an id, and a row without one stays exactly as before.
    assert rows[1] == {"text": "The pricing sheet is on the drive.", "source": "drive"}
    assert rows[2] == {"text": "Another pricing note.", "source": "mail"}


# -- the receipts block resolves why ---------------------------------------


def _receipted_reading(**values) -> InsightReading:
    """A reading whose receipt line exists, so the why has something to ride."""
    return InsightReading(
        used=("chart",),
        inputs=("memory", "rows"),
        memory_notes=2,
        note="A note.",
        **values,
    )


def test_the_why_rides_on_the_receipts_block():
    reading = _receipted_reading(
        why=(
            {
                "claim": "Booked falls as Margin rises.",
                "columns": ["Booked", "Margin"],
                "cells": ["Row 3: 10", "Row 4: 11"],
                "rule": "Rank trend across the Booked column",
                "facts": [{"id": 3, "source": "notes"}],
            },
        )
    )
    assert presentation.blocks(reading) == [
        {
            "kind": "receipts",
            "text": "Used: your chart preference · memory (2 notes) · this card's rows.",
            "why": [
                {
                    "claim": "Booked falls as Margin rises.",
                    "columns": ["Booked", "Margin"],
                    "cells": ["Row 3: 10", "Row 4: 11"],
                    "rule": "Rank trend across the Booked column",
                    "facts": [{"id": 3, "source": "notes"}],
                }
            ],
        },
        {"kind": "note", "text": "A note."},
    ]


def test_a_why_entry_keeps_only_the_five_bounded_fields_and_never_fact_prose():
    reading = InsightReading(
        inputs=("rows",),
        why=(
            {
                "claim": "A claim.",
                "rule": "A rule.",
                "threshold": "p 0.05",
                "facts": [
                    {"id": 3, "source": "notes", "text": "Priya owns the pricing model."}
                ],
                "extra": {"deep": "value"},
            },
            "not a dict",
            {},
        ),
    )
    blocks = presentation.blocks(reading)
    assert blocks[0]["kind"] == "receipts"
    assert len(blocks[0]["why"]) == 1
    assert set(blocks[0]["why"][0]) == {"claim", "rule", "facts"}
    assert blocks[0]["why"][0]["facts"] == [{"id": 3, "source": "notes"}]
    dumped = json.dumps(blocks)
    assert "Priya" not in dumped and "threshold" not in dumped


def test_cells_and_columns_are_capped_at_six_short_strings():
    reading = InsightReading(
        inputs=("rows",),
        why=(
            {
                "cells": [f"row {number}" for number in range(9)],
                "columns": [f"column {number}" for number in range(9)],
            },
        ),
    )
    entry = presentation.blocks(reading)[0]["why"][0]
    assert len(entry["cells"]) == 6
    assert len(entry["columns"]) == 6


def test_a_bool_fact_id_is_never_cited_and_an_entity_summary_is_kept():
    reading = InsightReading(
        inputs=("rows",),
        why=(
            {
                "facts": [
                    {"id": True, "source": "notes"},
                    {"id": 3, "source": "notes"},
                    {"entityId": 2, "name": "Harborlight Freight", "factCount": 3},
                    {"entityId": 4, "name": "No count"},
                ],
            },
        ),
    )
    entry = presentation.blocks(reading)[0]["why"][0]
    assert entry["facts"] == [
        {"id": 3, "source": "notes"},
        {"entityId": 2, "name": "Harborlight Freight", "factCount": 3},
    ]


def test_the_why_key_is_omitted_when_why_is_empty():
    reading = _receipted_reading()
    assert presentation.blocks(reading) == [
        {"kind": "receipts", "text": "Used: your chart preference · memory (2 notes) · this card's rows."},
        {"kind": "note", "text": "A note."},
    ]
    assert presentation.blocks(_receipted_reading(why=())) == presentation.blocks(reading)


def test_a_why_without_a_receipts_block_has_nothing_to_ride_on():
    reading = InsightReading(note="A note.", why=({"claim": "A claim."},))
    assert presentation.blocks(reading) == [{"kind": "note", "text": "A note."}]


def test_the_payload_carries_the_why_through_attach_cards(monkeypatch):
    reading = InsightReading(
        inputs=("rows",),
        why=({"claim": "Booked falls as Margin rises.", "facts": [
            {"id": 3, "source": "notes", "text": "Priya owns the pricing model."},
        ]},),
    )
    monkeypatch.setitem(service.FAMILIES, "excel-report", lambda card, payload, ctx: reading)

    card = _card()
    service.attach_cards([card], _context())

    insight = card["payload"]["insight"]
    assert insight["blocks"][0]["why"] == [
        {"claim": "Booked falls as Margin rises.", "facts": [{"id": 3, "source": "notes"}]}
    ]
    # The trust payload never carries the fact's text.
    assert "Priya" not in json.dumps(insight)


# -- the digest family cites its facts -------------------------------------


def _threads_payload() -> dict:
    return {
        "elements": [
            {
                "kind": "list",
                "title": "Active threads",
                "rows": [
                    {
                        "primary": "Pricing review",
                        "secondary": "Priya Raman",
                        "meta": "3 msg · 2 h ago",
                    }
                ],
            }
        ]
    }


def test_the_digest_cites_the_matched_thread_rule_and_fact_ids():
    preferences = {"focusTopics": ["pricing"]}
    with_ids = digest.derive(
        {"pluginId": "outlook-digest"},
        _threads_payload(),
        _context(preferences=preferences, recall=_recall_with_ids),
    )
    assert with_ids.why == (
        {
            "claim": "Thread this reading matched: Pricing review",
            "rule": "First thread a focus topic or a recalled fact touches"
                    "; focus matched: pricing",
            "facts": [{"id": 7, "source": "notes"}, {"id": 11, "source": "drive"}],
        },
    )
    # The citations name ids and sources, never the facts' text.
    assert "Priya" not in json.dumps(with_ids.why)


def test_the_digest_why_changes_no_element_and_no_receipt():
    preferences = {"focusTopics": ["pricing"]}
    with_ids = digest.derive(
        {"pluginId": "outlook-digest"},
        _threads_payload(),
        _context(preferences=preferences, recall=_recall_with_ids),
    )
    without_ids = digest.derive(
        {"pluginId": "outlook-digest"},
        _threads_payload(),
        _context(
            preferences=preferences,
            recall=lambda subject, limit: [
                {"text": row["text"], "source": row["source"]}
                for row in _recall_with_ids(subject, limit)
            ],
        ),
    )
    assert with_ids.elements == without_ids.elements
    assert presentation.receipts(with_ids) == presentation.receipts(without_ids)
    assert with_ids.status == without_ids.status == "ok"


def test_the_digest_cites_nothing_when_the_facts_carry_no_id():
    plain = digest.derive(
        {"pluginId": "outlook-digest"},
        _threads_payload(),
        _context(
            preferences={"focusTopics": ["pricing"]},
            recall=lambda subject, limit: [
                {"text": row["text"], "source": row["source"]}
                for row in _recall_with_ids(subject, limit)
            ],
        ),
    )
    # The matched thread and the rule stand; there is simply nothing to cite.
    assert set(plain.why[0]) == {"claim", "rule"}


# -- the calendar family cites its facts -----------------------------------


def _meeting() -> dict:
    return {
        "title": "Quarterly pricing review",
        "time": "Today 14:00",
        "meta": "Studio 2",
        "prep": [],
    }


def _calendar_payload() -> dict:
    return {
        "elements": [
            {"kind": "text", "label": "Next", "text": "Quarterly pricing review"},
            {"kind": "metric", "label": "Events today", "value": 3},
        ]
    }


def test_the_calendar_cites_the_meeting_window_and_fact_ids():
    preferences = {"prepMinutes": 20, "focusTopics": ["pricing"]}
    reading = calendar.derive(
        {"pluginId": "meeting-prep"},
        _calendar_payload(),
        _context(agenda=_meeting(), preferences=preferences, recall=_recall_with_ids),
    )
    assert reading.why == (
        {
            "claim": "Next meeting this reading prepared for: Quarterly pricing review",
            "rule": "Set aside 20 minutes before this. Focus: pricing.",
            "facts": [{"id": 7, "source": "notes"}, {"id": 11, "source": "drive"}],
        },
    )


def test_the_calendar_why_changes_no_element_and_no_receipt():
    preferences = {"prepMinutes": 20, "focusTopics": ["pricing"]}
    with_ids = calendar.derive(
        {"pluginId": "meeting-prep"},
        _calendar_payload(),
        _context(agenda=_meeting(), preferences=preferences, recall=_recall_with_ids),
    )
    without_ids = calendar.derive(
        {"pluginId": "meeting-prep"},
        _calendar_payload(),
        _context(
            agenda=_meeting(),
            preferences=preferences,
            recall=lambda subject, limit: [
                {"text": row["text"], "source": row["source"]}
                for row in _recall_with_ids(subject, limit)
            ],
        ),
    )
    assert with_ids.elements == without_ids.elements
    assert presentation.receipts(with_ids) == presentation.receipts(without_ids)


def test_a_calendar_without_a_meeting_has_no_why():
    reading = calendar.derive(
        {"pluginId": "meeting-prep"}, _calendar_payload(), _context()
    )
    assert reading.status == "empty"
    assert reading.why == ()


# -- the connect helper's projection ---------------------------------------


@dataclass
class _Entity:
    """Only what build_index reads off the store's entity summaries."""

    id: int
    canonical_name: str
    aliases: tuple = ()
    type: str = "org"
    fact_count: int = 0


def test_connect_named_exposes_the_entities_the_line_names():
    from datetime import datetime, timezone

    index = insight_connect.build_index(
        [
            _Entity(1, "Harborlight Freight", fact_count=3),
            _Entity(2, "Kestrel Foods", fact_count=2),
        ],
        {"title": "Renewal call: Harborlight Freight", "time": "2026-11-23T14:38:00"},
        datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc).timestamp(),
    )
    rows = ["Harborlight Freight renewal", "Kestrel Foods pilot"]

    line, notes, named = insight_connect.connect_named(rows, index)

    assert (line, notes) == insight_connect.connect_line(rows, index)
    assert [entry.entity_id for entry in named] == [1, 2]
    assert [entry.names[0] for entry in named] == ["Harborlight Freight", "Kestrel Foods"]
    assert [entry.fact_count for entry in named] == [3, 2]
    # The agenda's clause rides the entity it names, and nobody else.
    assert named[0].event_clause.endswith("14:38")
    assert named[1].event_clause == ""
