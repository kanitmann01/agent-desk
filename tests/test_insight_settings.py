"""The settings card where the desk is told what to assume (ticket 02).

The card reads its six values back from the preference store on every
render, so these tests ask the store and the card separately: a save is
only real when both agree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import server_harness  # noqa: E402
from nexuusbot.server import settings_view  # noqa: E402

CARD_OPEN = "<section class='card settings-card' id='preferences'>"

# The six fields as the browser sends them: every value a string, because
# a form post is strings all the way down.
FORM_DEFAULTS = {
    "chart": "auto",
    "replyTone": "direct",
    "replyLength": "short",
    "insightDensity": "normal",
    "focusTopics": "",
    "prepMinutes": "15",
}


@pytest.fixture()
def booted(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    app = server_harness.Booted()
    try:
        yield app
    finally:
        app.close()


@pytest.fixture()
def auth(booted):
    return booted.exchange()


def _settings(booted, auth, path="/settings"):
    status, _headers, body = booted.request("GET", path, headers=auth)
    assert status == 200
    return body.decode("utf-8")


def _card(page):
    start = page.index(CARD_OPEN)
    return page[start:page.index("</section>", start)]


def _document(booted, auth):
    status, _headers, body = booted.request(
        "GET", "/api/preferences", headers=auth)
    assert status == 200
    return json.loads(body)


def _post_card(booted, auth, **fields):
    payload = dict(FORM_DEFAULTS, **fields)
    headers = dict(auth)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    headers["Content-Length"] = str(len(urlencode(payload)))
    return booted.request(
        "POST", "/settings/preferences",
        headers=headers, body=urlencode(payload).encode("utf-8"))


def test_the_card_shows_the_six_stored_values(booted, auth):
    page = _settings(booted, auth)
    card = _card(page)

    assert "What the desk knows about you" in card
    assert "only preferences the desk uses" in card
    assert "never infers them" in card
    # Values are in the markup, not fetched: the card reads with no script.
    for expected in (
        "<option value='auto' selected>",
        "<option value='direct' selected>",
        "<option value='short' selected>",
        "<option value='normal' selected>",
        "<input id='pref-prepMinutes' name='prepMinutes' type='number' "
        "min='0' max='120' step='1' value='15'>",
    ):
        assert expected in card, expected
    # Every control is labelled, and each label points at its own control.
    for key in ("chart", "replyTone", "replyLength", "insightDensity",
                "focusTopics", "prepMinutes"):
        assert f"for='pref-{key}'" in card, key
    assert "<span class='stamp'>DEFAULTS</span>" in card
    # Nothing has been saved in this test, so the page claims nothing.
    assert "id='preferences-note' hidden" in card


def test_a_saved_section_round_trips_through_the_store(booted, auth):
    status, headers, _body = _post_card(
        booted, auth,
        chart="bar",
        replyTone="warm",
        replyLength="paragraph",
        insightDensity="chatty",
        focusTopics="pricing\nlaunch notes",
        prepMinutes="45",
    )

    assert status == 303
    assert headers["Location"] == "/settings?preferences_saved=1"
    document = _document(booted, auth)
    assert document["chart"] == "bar"
    assert document["replyTone"] == "warm"
    assert document["replyLength"] == "paragraph"
    assert document["insightDensity"] == "chatty"
    assert document["focusTopics"] == ["pricing", "launch notes"]
    assert document["prepMinutes"] == 45

    # The redirect lands on the page the user sees, and that page reads
    # the store back: the confirmation is never a claim on its own.
    card = _card(_settings(booted, auth, headers["Location"]))
    assert "Saved." in card
    assert "<option value='bar' selected>" in card
    assert "<option value='warm' selected>" in card
    assert "<option value='paragraph' selected>" in card
    assert "<option value='chatty' selected>" in card
    assert "value='45'" in card
    assert "pricing\nlaunch notes" in card
    assert "<span class='stamp'>6 SET</span>" in card


def test_a_refused_value_keeps_the_store_and_names_the_reason(booted, auth):
    sentence = "chart must be one of auto, bar, line, table."
    status, headers, _body = _post_card(booted, auth, chart="pie")

    assert status == 303
    location = headers["Location"]
    assert location.startswith("/settings?preferences_error=")
    query = parse_qs(location.partition("?")[2])
    # The store's own sentence travels back, not a generic failure.
    assert query["preferences_error"] == [sentence]
    assert _document(booted, auth)["chart"] == "auto"

    # The redirect's destination carries the store's sentence into the card.
    card = _card(_settings(booted, auth, location))
    assert sentence in card
    assert "id='preferences-note' hidden" not in card


def test_the_section_states_the_notice_it_is_given():
    defaults = {
        "version": 1, "chart": "auto", "replyTone": "direct",
        "replyLength": "short", "insightDensity": "normal",
        "focusTopics": [], "prepMinutes": 15, "updatedAt": 0.0,
    }
    refused = settings_view._preferences_section(
        defaults, "chart must be one of auto, bar, line, table.")
    assert ">chart must be one of auto, bar, line, table.</div>" in refused
    assert "id='preferences-note' hidden" not in refused

    saved = settings_view._preferences_section(defaults, "Saved.")
    assert ">Saved.</div>" in saved

    # A message is text, not markup.
    escaped = settings_view._preferences_section(defaults, "<b>no</b> & co")
    assert "&lt;b&gt;no&lt;/b&gt; &amp; co" in escaped
    assert "<b>no</b>" not in escaped


def test_the_page_carries_the_notice_through_the_renderer():
    defaults = {
        "version": 1, "chart": "auto", "replyTone": "direct",
        "replyLength": "short", "insightDensity": "normal",
        "focusTopics": [], "prepMinutes": 15, "updatedAt": 0.0,
    }
    page = settings_view.render_settings_page(
        [], [], {}, "0",
        settings_values=dict.fromkeys(settings_view._LABELS, False),
        preferences=defaults,
        preference_notice="chart must be one of auto, bar, line, table.",
    )
    assert ">chart must be one of auto, bar, line, table.</div>" in page
    assert "chart must be one of" not in page.split(CARD_OPEN)[0]
