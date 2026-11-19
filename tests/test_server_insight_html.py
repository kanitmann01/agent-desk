"""The coupled reading has to arrive as HTML, not only as JSON.

`_plugin_element_html` is the boundary that escapes every card string, and
`with_insight` is the one call both surfaces make. A regression in either
would leave the reading in the payload where nobody sees it.
"""

from __future__ import annotations

from types import SimpleNamespace

from agentdesk.insight import service
from agentdesk.insight.types import InsightContext, InsightReading
from agentdesk.server import app


def _widget_card(elements: list[dict]) -> dict:
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
        "payload": {"elements": list(elements), "status": "fresh"},
    }


def test_a_list_element_draws_its_title_and_rows():
    html = app._plugin_element_html({
        "kind": "list",
        "title": "Worth researching",
        "rows": [
            {"primary": "Pricing review", "meta": "Focus list"},
            {"primary": "Churn spike", "secondary": "Q3", "meta": "Calendar"},
        ],
    })
    assert "Worth researching" in html
    assert "Pricing review · Focus list" in html
    assert "Churn spike · Q3 · Calendar" in html


def test_a_checklist_element_draws_every_item():
    html = app._plugin_element_html({
        "kind": "checklist",
        "title": "Before the meeting",
        "items": [{"text": "Set aside 30 minutes before this."}, {"text": "Read the Q3 sheet.", "done": True}],
    })
    assert "Before the meeting" in html
    assert "Set aside 30 minutes before this." in html
    assert "Read the Q3 sheet." in html


def test_a_status_element_draws_its_sentence():
    html = app._plugin_element_html({"kind": "status", "text": "Memory is sealed, so no fact could be read.", "tone": "attention"})
    assert "Memory is sealed" in html


def test_a_card_string_is_escaped_at_the_boundary():
    html = app._plugin_element_html({
        "kind": "list",
        "rows": [{"primary": "<script>alert(1)</script>", "meta": "Focus list"}],
    })
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_an_unknown_kind_draws_nothing():
    assert app._plugin_element_html({"kind": "hologram", "points": [1, 2]}) == ""


def test_the_rendered_card_carries_the_reading(monkeypatch):
    monkeypatch.setattr(
        app,
        "build_insight_context",
        lambda server, preferences: InsightContext(preferences=preferences, now=0.0),
    )
    monkeypatch.setitem(
        service.FAMILIES,
        "excel-report",
        lambda card, payload, context: InsightReading(
            elements=[{"kind": "text", "label": "Link", "text": "Booked falls as Margin rises."}]
        ),
    )
    cards = app.with_insight(SimpleNamespace(), [_widget_card([{"kind": "metric", "label": "Value", "value": "91"}])])
    widget = app.DashboardHandler._plugin_widget(None, cards[0])
    assert "Booked falls as Margin rises." in widget.body_html

def _reading_card(blocks: list[dict], elements: list[dict] | None = None) -> dict:
    """A fresh widget card carrying one reading's resolved blocks."""
    card = _widget_card(elements or [{"kind": "text", "text": "Booked falls as Margin rises."}])
    card["payload"]["insight"] = {
        "status": "ok",
        "source": "local",
        "preferences": [],
        "note": "",
        "blocks": blocks,
        "press": None,
    }
    return card


def test_the_rendered_card_prints_what_the_reading_used():
    widget = app.DashboardHandler._plugin_widget(
        None,
        _reading_card(
            [{"kind": "receipts", "text": "Used: your chart preference · memory (2 notes) · this card's rows."}]
        ),
    )
    assert "Used: your chart preference · memory (2 notes) · this card's rows." in widget.body_html


def test_every_block_draws_its_own_quiet_line_in_order():
    widget = app.DashboardHandler._plugin_widget(
        None,
        _reading_card(
            [
                {"kind": "receipts", "text": "Used: your chart preference."},
                {"kind": "note", "text": "Only the rows under the chart were looked at."},
            ]
        ),
    )
    body = widget.body_html
    assert '<p class="w-note">Used: your chart preference.</p>' in body
    assert '<p class="w-note">Only the rows under the chart were looked at.</p>' in body
    assert body.index("Used: your chart preference.") < body.index("Only the rows under the chart")


def test_a_block_is_escaped_at_the_boundary():
    line = app._receipt_line(
        {"insight": {"blocks": [{"kind": "note", "text": "<script>alert(1)</script>"}]}}
    )
    assert "<script>" not in line
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in line


def test_a_reading_that_says_nothing_prints_no_receipt():
    assert app._receipt_line({"insight": {"blocks": []}}) == ""
    assert app._receipt_line({"insight": {"blocks": [{"kind": "note", "text": "   "}]}}) == ""


def test_malformed_blocks_are_skipped_rather_than_drawn():
    line = app._receipt_line(
        {"insight": {"blocks": ["not a block", {"kind": "note"}, {"kind": "note", "text": "Kept."}]}}
    )
    assert line == '<p class="w-note">Kept.</p>'


def test_no_receipt_line_without_a_reading():
    assert app._receipt_line({"elements": []}) == ""
    assert app._receipt_line({"insight": {"status": "ok"}}) == ""
    assert app._receipt_line({"insight": {"blocks": "not a list"}}) == ""

def test_a_rendered_card_with_a_press_draws_a_form_and_escapes_it():
    card = _reading_card([])
    card["payload"]["insight"]["press"] = {
        "label": "Draft a reply",
        "route": "/api/insight/draft",
        "kind": "reply-draft",
        "thread": {"subject": "<script>Budget</script>", "sender": "Priya Raman"},
    }
    widget = app.DashboardHandler._plugin_widget(None, card)
    body = widget.body_html
    assert '<form method="post" action="/insight/press"' in body
    assert 'name="kind" value="reply-draft"' in body
    assert 'name="sender" value="Priya Raman"' in body
    assert "<script>Budget</script>" not in body
    assert "Draft a reply" in body


def test_a_rendered_card_without_a_press_draws_no_form():
    widget = app.DashboardHandler._plugin_widget(None, _reading_card([]))
    assert "/insight/press" not in widget.body_html

