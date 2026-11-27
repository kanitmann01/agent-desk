"""The rendered card's press is a real control, and it escapes what it carries.

A press is the only place a card may spend a model call, so the form that
carries it is a boundary: every hidden value is authored HTML, and a card
without a press must keep today's markup exactly.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from agentdesk.insight import press
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
            "thread": {"subject": "Q3 numbers", "sender": "Ada Lovelace"},
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
        {"label": "Draft", "kind": "reply-draft",
         "thread": {"subject": "<script>alert(1)</script>"}},
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


def test_a_press_that_nests_its_thread_still_sends_flat_fields():
    press_payload = {
        "label": "Draft a reply",
        "route": "/api/insight/draft",
        "kind": "reply-draft",
        "thread": {"subject": "Budget", "sender": "Priya Raman", "last": "Here are the numbers."},
    }
    html = app._press_form(_card(), press_payload)
    for name, value in (
        ("subject", "Budget"),
        ("sender", "Priya Raman"),
        ("last", "Here are the numbers."),
    ):
        assert f'name="{name}" value="{value}"' in html
    # The form's spelling re-parses into the request the route parses, so
    # the no-JS surface and the SPA press the same press.
    fields = {
        name: value
        for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', html)
    }
    assert press.press_from_form(fields) == {
        "kind": "reply-draft",
        "thread": {"subject": "Budget", "sender": "Priya Raman",
                   "last": "Here are the numbers."},
    }


def _stage_form_fields(page: str) -> dict[str, str]:
    """The hidden fields of the one stage form the page rendered."""
    import html as html_mod
    import re

    for form in re.findall(r"<form[^>]*>.*?</form>", page, re.S):
        if "Stage as a reply card" in form:
            return {
                name: html_mod.unescape(value)
                for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', form)
            }
    raise AssertionError("the page offered no stage form")


def _mail_desk(tmp_path):
    """A booted desk with one message in the folder and a model behind it."""
    import sqlite3
    import time

    from agentdesk.inbox.store import InboxStore
    from agentdesk.mail.store import MailStore
    from agentdesk.settings import SettingsStore
    from tests.server_harness import Booted

    folder = tmp_path / "mail"
    folder.mkdir()
    (folder / "budget.eml").write_bytes(
        b"From: Priya Raman <priya@example.com>\r\nTo: employee@example.com\r\n"
        b"Subject: Budget\r\nDate: Wed, 11 Nov 2026 09:00:00 +0000\r\n"
        b"Message-ID: <budget-1@example.com>\r\nMIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nHere are the numbers.\r\n"
    )
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    settings.set("mail_enabled", True)
    settings.set("mail_folder", str(folder))
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    booted = Booted(
        llm=lambda _prompt: "Thanks, I will send the revised budget by Friday.",
        llm_endpoint="http://llm.test/v1",
        inbox_store=inbox,
        mail_store=MailStore(sqlite3.connect(":memory:", check_same_thread=False), time.time),
        settings_store=settings,
    )
    booted.server.settings.set("endpoint_enabled", True)
    return booted


def test_a_pressed_card_can_stage_its_draft_as_one_card(tmp_path):
    booted = _mail_desk(tmp_path)
    try:
        auth = booted.exchange()
        status, _headers, body = _post_form(
            booted, auth,
            {
                "kind": "reply-draft",
                "subject": "Budget",
                "sender": "priya@example.com",
                "last": "Here are the numbers.",
            },
        )
        page = body.decode("utf-8")
        assert status == 200
        assert "Thanks, I will send the revised budget by Friday." in page
        assert page.index("Sends: the thread") < page.index("Stage as a reply card")
        fields = _stage_form_fields(page)
        status, _headers, body = _post_form(booted, auth, fields)
        staged_page = body.decode("utf-8")
    finally:
        booted.close()
    assert status == 200
    assert "Staged as a card:" in staged_page
    assert "Stage as a reply card" not in staged_page
    waiting = booted.server.inbox.waiting()
    assert len(waiting) == 1
    assert waiting[0].title == "Drafted reply: Re: Budget"
    assert waiting[0].draft == "Thanks, I will send the revised budget by Friday."


# -- the audit trail (spec 017 workstream 3) -------------------------------


def _press_rows(booted) -> list:
    from agentdesk.assistant import audit as audit_store
    return [e for e in audit_store.entries(booted.server.audit_conn)
            if e["action"] == "insight.press"]


def test_a_page_press_writes_one_insight_press_row(tmp_path):
    booted = _mail_desk(tmp_path)
    try:
        auth = booted.exchange()
        status, _headers, _body = _post_form(
            booted, auth,
            {"kind": "reply-draft", "subject": "Budget", "sender": "priya@example.com"},
        )
        assert status == 200
        rows = _press_rows(booted)
    finally:
        booted.close()
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["target"] == "<budget-1@example.com>"
    assert rows[0]["detail"] == "reply-draft:model"


def test_a_refused_page_press_records_an_error_row(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    from tests.server_harness import Booted

    booted = Booted()
    try:
        auth = booted.exchange()
        status, _headers, body = _post_form(
            booted, auth,
            {"kind": "explain-range", "text": "Booked falls as Margin rises."},
        )
        assert status == 200  # the page keeps the refusal sentence
        rows = _press_rows(booted)
    finally:
        booted.close()
    # What the user sees matches what the log says: the page carries the
    # named refusal sentence (never a bare status), and the row the audit
    # page shows for the same press is an error, not a working one
    # (spec 017 workstream 8d; the SPA door pins the same pairing in
    # frontend press tests, the alert role with the desk's sentence).
    page = body.decode("utf-8")
    assert "Nothing was explained: model calls are off on this desk" in page
    assert '<div class="alert"><p>' in page
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["detail"] == "insight:model-off"
    assert [r for r in rows if r["status"] == "ok"] == []


# -- the counter-evidence press on the page -------------------------------


def test_a_counter_check_answer_page_shows_its_disclosure_then_the_answer(tmp_path, monkeypatch):
    """A pressed check lands on the same page shape as an explanation."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    from tests.server_harness import Booted

    booted = Booted(
        llm=lambda _prompt: "The discount spike could be seasonal; check last November.",
        llm_endpoint="http://llm.test/v1",
    )
    try:
        booted.server.settings.set("endpoint_enabled", True)
        auth = booted.exchange()
        status, _headers, body = _post_form(
            booted, auth,
            {"kind": "check-counter", "text": "Booked falls while Margin rises."},
        )
    finally:
        booted.close()
    page = body.decode("utf-8")
    assert status == 200
    assert "Check counter-evidence" in page
    # The page escapes its own copy, so the promise is read up to the
    # apostrophe, the same way the explanation page pins its disclosure.
    disclosure = "Sends: the stored answer summary and the desk"
    assert disclosure in page
    assert "falsification criterion." in page
    assert page.index(disclosure) < page.index("The discount spike could be seasonal")
    assert 'Source: <span class="mono">model</span>' in page
    # The page names the press in words, never as the raw kind it travelled as.
    assert "check-counter" not in page
    assert "Stage as a reply card" not in page


def test_a_counter_check_refusal_keeps_the_page_and_names_the_model_off(tmp_path, monkeypatch):
    """With Your AI off the page keeps the desk's refusal, and offers nothing."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    from tests.server_harness import Booted

    booted = Booted()
    try:
        auth = booted.exchange()
        status, _headers, body = _post_form(
            booted, auth, {"kind": "check-counter", "text": "Booked falls while Margin rises."},
        )
    finally:
        booted.close()
    page = body.decode("utf-8")
    assert status == 200
    assert "Nothing was checked: model calls are off on this desk" in page
    assert '<div class="alert"><p>' in page
    assert "Stage as a reply card" not in page
    assert "check-counter" not in page

