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
    assert app._plugin_element_html({"kind": "sparkline", "points": [1, 2]}) == ""


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
