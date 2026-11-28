"""The reading's lines are resolved once, in nexuusbot.insight.reading.

The card payload carries the resolved blocks, and both surfaces print the
text as it came: the no-JS card draws the block paragraphs, and the SPA
renders the very same strings. Nothing outside the presentation module keeps
a phrase table, so these tests pin the one place a key becomes a phrase, the
order and normalisation of what a reading declares, and the wire shape -
including the absence of the names (receipts, suggested) that used to leak
through to the surfaces.
"""

from __future__ import annotations

from html import escape as html_escape
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

from nexuusbot.insight import reading as presentation
from nexuusbot.insight import service
from nexuusbot.insight.preferences import FIELDS, defaults
from nexuusbot.insight.press import KINDS as PRESS_KINDS, press_to_fields
from nexuusbot.insight.types import InsightContext, InsightReading
from nexuusbot.server import app

NOW = 1_760_000_000.0


def _context(**preferences) -> InsightContext:
    document = defaults()
    document.update(preferences)
    return InsightContext(preferences=document, now=NOW)


def _reading(**values) -> InsightReading:
    """One reading with exactly the values a test declares."""
    return InsightReading(**values)


class _QuietParagraphs(HTMLParser):
    """Collect the text of every quiet (w-note) paragraph in a card."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self._open: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag == "p" and "w-note" in classes:
            self._open = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._open is not None:
            self.lines.append("".join(self._open).strip())
            self._open = None

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open.append(data)


def _quiet_lines(body: str) -> list[str]:
    """The text of the quiet paragraphs a rendered card carries, in order."""
    parser = _QuietParagraphs()
    parser.feed(body)
    parser.close()
    return parser.lines


def _card(elements: list[dict] | None = None) -> dict:
    return {
        "id": "excel-report",
        "pluginId": "excel-report",
        "title": "Q3 bookings",
        "version": "0.1.0",
        "pilot": False,
        "state": "enabled",
        "freshness": "fresh",
        "cause": "",
        "checked_at": "2026-11-18T09:00:00",
        "payload": {
            "elements": list(elements or [{"kind": "metric", "value": "91"}]),
            "status": "fresh",
        },
    }


def _attached(monkeypatch, derived: InsightReading) -> dict:
    """One card after the presentation attached the reading a family derived."""
    monkeypatch.setattr(
        app,
        "build_insight_context",
        lambda server, preferences: InsightContext(preferences=preferences, now=NOW),
    )
    monkeypatch.setitem(service.FAMILIES, "excel-report", lambda card, payload, ctx: derived)
    return app.with_insight(SimpleNamespace(), [_card()])[0]


# -- the vocabulary ------------------------------------------------------


def test_the_phrase_tables_cover_the_seams_own_vocabularies():
    # A name the seam can declare must have a phrase here, or the line would
    # silently drop something the reading really used.
    assert set(presentation.RECEIPT_PHRASES) == set(FIELDS)
    assert set(presentation.INPUT_PHRASES) == set(presentation.INPUT_NAMES)
    assert set(presentation.PRESS_LABELS) == set(PRESS_KINDS)


@pytest.mark.parametrize(
    "kind, label",
    [("reply-draft", "Draft a reply"), ("explain-range", "Explain this range")],
)
def test_a_known_press_kind_reads_as_its_sentence(kind, label):
    assert presentation.press_label(kind) == label


def test_an_unknown_press_kind_never_reads_as_a_raw_identifier():
    assert presentation.press_label("write-a-poem") == presentation.DEFAULT_PRESS_LABEL
    assert presentation.press_label("") == presentation.DEFAULT_PRESS_LABEL
    assert presentation.press_label(None) == presentation.DEFAULT_PRESS_LABEL


# -- the receipt line ----------------------------------------------------


def test_the_line_reads_preferences_first_and_then_the_inputs():
    receipt = {
        "preferences": ["replyTone", "chart"],
        "inputs": ["memory", "rows"],
        "counts": {"memory": 2},
    }
    assert presentation.receipt_line(receipt) == (
        "Used: your reply tone · your chart preference · memory (2 notes) · this card's rows."
    )


def test_one_note_reads_in_the_singular():
    receipt = {"preferences": [], "inputs": ["memory"], "counts": {"memory": 1}}
    assert presentation.receipt_line(receipt) == "Used the defaults; read memory (1 note)."


def test_a_reading_that_used_only_its_defaults_says_so():
    only_rows = {"preferences": [], "inputs": ["rows"]}
    assert presentation.receipt_line(only_rows) == presentation.DEFAULTS_RECEIPT
    with_memory = {"preferences": [], "inputs": ["memory", "calendar"]}
    assert presentation.receipt_line(with_memory) == (
        "Used the defaults; read memory and this calendar."
    )


def test_a_reading_that_read_nothing_says_nothing():
    assert presentation.receipt_line({"preferences": [], "inputs": []}) == ""
    assert presentation.receipt_line({}) == ""
    assert presentation.receipt_line(None) == ""
    # A preference alone (no input) is still something used, so it prints.
    assert presentation.receipt_line({"preferences": ["chart"], "inputs": []}) == (
        "Used: your chart preference."
    )


def test_a_name_outside_the_vocabulary_draws_nothing():
    receipt = {"preferences": ["<b>chart</b>"], "inputs": ["sqlite", "rows"]}
    line = presentation.receipt_line(receipt)
    assert line == presentation.DEFAULTS_RECEIPT
    assert "sqlite" not in line
    assert "<b>" not in line


def test_declared_names_survive_once_and_in_declared_order():
    receipt = presentation.receipts(
        _reading(used=("chart", "chart", "colour", "replyTone"), inputs=("memory", "sqlite", "rows", "memory"))
    )
    assert receipt == {"preferences": ["chart", "replyTone"], "inputs": ["memory", "rows"]}


def test_a_count_rides_only_on_a_declared_memory_input():
    counted = presentation.receipts(_reading(inputs=("memory",), memory_notes=2))
    assert counted["counts"] == {"memory": 2}
    assert "counts" not in presentation.receipts(_reading(inputs=("rows",), memory_notes=2))
    assert "counts" not in presentation.receipts(_reading(inputs=("memory",), memory_notes=0))
    assert "counts" not in presentation.receipts(_reading(inputs=("memory",), memory_notes=True))


# -- the blocks ----------------------------------------------------------


def test_the_blocks_carry_the_receipt_then_the_note_in_print_order():
    derived = _reading(
        used=("chart",),
        inputs=("memory", "rows"),
        memory_notes=2,
        note="Only the rows under the chart were looked at.",
    )
    assert presentation.blocks(derived) == [
        {"kind": "receipts", "text": "Used: your chart preference · memory (2 notes) · this card's rows."},
        {"kind": "note", "text": "Only the rows under the chart were looked at."},
    ]


def test_a_reading_with_nothing_to_say_carries_no_blocks():
    assert presentation.blocks(_reading()) == []
    assert presentation.blocks(_reading(note="   ")) == []


@pytest.mark.parametrize(
    "inputs, note, kinds",
    [
        ((), "A note.", ["note"]),
        (("rows",), "", ["receipts"]),
        (("rows",), "A note.", ["receipts", "note"]),
    ],
)
def test_each_block_appears_only_when_it_has_something_to_say(inputs, note, kinds):
    derived = _reading(inputs=inputs, note=note)
    assert [block["kind"] for block in presentation.blocks(derived)] == kinds


# -- the press -----------------------------------------------------------


def test_a_full_press_keeps_the_fields_the_action_posts():
    press = {
        "label": "Draft the reply",
        "route": "/api/insight/draft",
        "kind": "reply-draft",
        "thread": {"subject": "Q4 forecast", "sender": "Dana Whitfield"},
        "text": "ignored for a reply",
        "extra": "not carried",
    }
    assert presentation.press(press) == {
        "label": "Draft the reply",
        "route": "/api/insight/draft",
        "kind": "reply-draft",
        "thread": {"subject": "Q4 forecast", "sender": "Dana Whitfield"},
        "text": "ignored for a reply",
    }


def test_a_press_without_a_label_reads_as_its_kind():
    resolved = presentation.press({"route": "/api/insight/draft", "kind": "explain-range"})
    assert resolved == {
        "label": "Explain this range",
        "route": "/api/insight/draft",
        "kind": "explain-range",
    }


def test_a_press_without_a_kind_is_not_drawable():
    assert presentation.press(None) is None
    assert presentation.press("Draft a reply") is None
    assert presentation.press({"label": "Draft a reply"}) is None
    assert presentation.press({"label": "Draft a reply", "kind": "   "}) is None


def test_a_thread_keeps_only_the_bounded_facts_the_action_sends():
    resolved = presentation.press(
        {
            "kind": "reply-draft",
            "route": "/api/insight/draft",
            "thread": {"subject": "Q4 forecast", "sender": " ", "last": "Any news?", "bcc": "x@y"},
        }
    )
    assert resolved["thread"] == {"subject": "Q4 forecast", "last": "Any news?"}


# -- the wire ------------------------------------------------------------


def _derived_reading() -> InsightReading:
    """A reading that used something, says something, and offers a press."""
    return _reading(
        used=("chart",),
        inputs=("memory", "rows"),
        memory_notes=2,
        note="Only the rows under the chart were looked at.",
        press={
            "label": "Explain this range",
            "route": "/api/insight/draft",
            "kind": "explain-range",
            "text": "Booked falls as Margin rises.",
        },
    )


def test_the_payload_carries_resolved_blocks_and_never_the_names(monkeypatch):
    derived = _derived_reading()
    card = _attached(monkeypatch, derived)
    insight = card["payload"]["insight"]

    assert set(insight) == {"status", "source", "preferences", "note", "blocks", "press"}
    assert "receipts" not in insight
    assert "suggested" not in insight
    assert insight["blocks"] == [
        {"kind": "receipts", "text": "Used: your chart preference · memory (2 notes) · this card's rows."},
        {"kind": "note", "text": "Only the rows under the chart were looked at."},
    ]
    assert insight["press"] == presentation.press(derived.press)


def test_the_rendered_card_prints_exactly_the_payload_block_texts(monkeypatch):
    card = _attached(monkeypatch, _derived_reading())
    insight = card["payload"]["insight"]

    widget = app.DashboardHandler._plugin_widget(None, card)

    # One quiet paragraph per block, the same text the JSON payload carries:
    # the two surfaces cannot drift because neither resolves a line itself.
    assert _quiet_lines(widget.body_html) == [block["text"] for block in insight["blocks"]]


def test_the_rendered_card_escapes_a_blocks_text(monkeypatch):
    derived = _reading(note="<script>alert(1)</script>")
    card = _attached(monkeypatch, derived)

    widget = app.DashboardHandler._plugin_widget(None, card)

    assert "<script>" not in widget.body_html
    assert "&lt;script&gt;" in widget.body_html
    # The payload keeps the text as the family wrote it; escaping is the
    # boundary's job, not the phrase table's.
    assert card["payload"]["insight"]["blocks"][0]["text"] == "<script>alert(1)</script>"


def test_the_card_draws_the_press_fields_the_action_posts(monkeypatch):
    derived = _reading(
        press={
            "route": "/api/insight/draft",
            "kind": "reply-draft",
            "thread": {"subject": "<script>Budget</script>", "sender": "Ada Lovelace"},
        }
    )
    card = _attached(monkeypatch, derived)
    pressed = card["payload"]["insight"]["press"]
    # The label was resolved from the kind once; the button shows it.
    assert pressed["label"] == "Draft a reply"

    body = app.DashboardHandler._plugin_widget(None, card).body_html

    assert '<form method="post" action="/insight/press"' in body
    for name, value in press_to_fields(pressed).items():
        assert 'name="' + name + '" value="' + html_escape(value) + '"' in body
    assert "Draft a reply" in body
    assert "<script>Budget</script>" not in body
