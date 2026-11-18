"""The rendered card's press is a real control, and it escapes what it carries.

A press is the only place a card may spend a model call, so the form that
carries it is a boundary: every hidden value is authored HTML, and a card
without a press must keep today's markup exactly.
"""

from __future__ import annotations

from urllib.parse import urlencode

from agentdesk.server import app


def _card(**extra) -> dict:
    card = {"id": "excel-report~bookings", "pluginId": "excel-report", "title": "Q3 bookings"}
    card.update(extra)
    return card


def test_a_press_draws_a_form_with_every_hidden_field():
    html = app._press_form(
        _card(instanceId="bookings"),
        {
            "label": "Draft a reply",
            "route": "/api/insight/draft",
            "kind": "reply-draft",
            "subject": "Q3 numbers",
            "sender": "Ada Lovelace",
        },
    )
    assert 'method="post"' in html
    assert 'action="/insight/press"' in html
    for name, value in (
        ("kind", "reply-draft"),
        ("subject", "Q3 numbers"),
        ("sender", "Ada Lovelace"),
        ("pluginId", "excel-report"),
        ("instanceId", "bookings"),
    ):
        assert f'name="{name}" value="{value}"' in html
    assert "Draft a reply" in html
    assert "btn btn-secondary" in html


def test_a_press_value_is_escaped_at_the_boundary():
    html = app._press_form(
        _card(),
        {"label": "Draft", "kind": "reply-draft", "subject": "<script>alert(1)</script>"},
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_only_the_fields_the_press_carries_are_sent():
    html = app._press_form(
        _card(),
        {"label": "Explain this range", "kind": "explain-range", "text": "Booked falls as Margin rises."},
    )
    assert 'name="text"' in html
    assert 'name="subject"' not in html
    assert 'name="sender"' not in html
    assert "Explain this range" in html


def test_a_card_without_a_press_draws_nothing_new():
    assert app._press_form(_card(), None) == ""
    assert app._press_form(_card(), {"label": "", "kind": "reply-draft"}) == ""
    assert app._press_form(_card(), {"label": "Draft", "kind": ""}) == ""
    assert app._press_form(_card(), "not a press") == ""


def test_a_card_without_an_instance_sends_no_instance():
    html = app._press_form(
        {"id": "excel-report", "pluginId": "excel-report"},
        {"label": "Explain this range", "kind": "explain-range", "text": "x"},
    )
    assert 'name="pluginId" value="excel-report"' in html
    assert 'name="instanceId"' not in html

# -- the page a press lands on ------------------------------------------


def _post_form(booted, auth, fields: dict[str, str]):
    data = urlencode(fields).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(data)),
    }
    headers.update(auth)
    return booted.request("POST", "/insight/press", headers=headers, body=data)


def test_the_model_off_page_says_so_and_offers_nothing_to_press(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    from tests.server_harness import Booted

    booted = Booted()
    try:
        auth = booted.exchange()
        status, _headers, body = _post_form(
            booted, auth,
            {"kind": "explain-range", "text": "Booked falls as Margin rises."},
        )
    finally:
        booted.close()
    page = body.decode("utf-8")
    assert status == 200
    assert "Nothing was explained: model calls are off on this desk" in page
    assert "Stage as a reply card" not in page
    assert "<pre" not in page


def test_an_unknown_kind_is_refused_on_the_page(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    from tests.server_harness import Booted

    booted = Booted()
    try:
        auth = booted.exchange()
        status, _headers, body = _post_form(booted, auth, {"kind": "write-a-poem"})
    finally:
        booted.close()
    page = body.decode("utf-8")
    assert status == 200
    assert "write-a-poem is not something the desk drafts." in page
    assert "Stage as a reply card" not in page

def test_an_explanation_page_shows_the_disclosure_then_the_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    from tests.server_harness import Booted

    booted = Booted(llm=lambda prompt: "Booked falls while Margin rises; check the discount line.", llm_endpoint="http://llm.test/v1")
    try:
        booted.server.settings.set("endpoint_enabled", True)
        auth = booted.exchange()
        status, _headers, body = _post_form(
            booted, auth,
            {"kind": "explain-range", "text": "Booked falls as Margin rises."},
        )
    finally:
        booted.close()
    page = body.decode("utf-8")
    assert status == 200
    disclosure = "Sends: the one sentence this card already shows"
    assert disclosure in page
    assert page.index(disclosure) < page.index("Booked falls while Margin rises")
    assert "Source: <span class=\"mono\">model</span>" in page
    # An explanation has no thread, so nothing can be staged from it.
    assert "Stage as a reply card" not in page
