"""The settings form's preferences route, driven over real sockets.

The page's six preference fields post as a form, which means strings
where the store wants a list and a whole number. These tests hold the
route to its two promises: it converts without guessing, and a refusal
comes back as the store's own sentence rather than a silent partial
save. The page's rendering of that sentence is the settings view's own
test; this file stops at the wire.
"""

import json
from urllib.parse import urlencode

import pytest

from server_harness import Booted
from nexuusbot.insight.preferences import PreferenceStore


@pytest.fixture()
def booted(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    boot = Booted()
    yield boot
    boot.close()


@pytest.fixture()
def auth(booted):
    return booted.exchange()


def _form(booted, auth, fields):
    data = urlencode(fields).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Content-Length": str(len(data))}
    headers.update(auth)
    return booted.request("POST", "/settings/preferences", headers=headers, body=data)


def _stored(tmp_path):
    return PreferenceStore(tmp_path).read()


def test_form_post_saves_all_six_and_redirects(booted, auth, tmp_path):
    status, headers, _ = _form(booted, auth, {
        "chart": "line", "replyTone": "warm", "replyLength": "short",
        "insightDensity": "quiet",
        "focusTopics": "pricing review\n\nhiring plan",
        "prepMinutes": "45",
    })
    assert status == 303
    assert headers["Location"] == "/settings?preferences_saved=1"
    stored = _stored(tmp_path)
    assert stored["chart"] == "line"
    assert stored["replyTone"] == "warm"
    assert stored["replyLength"] == "short"
    assert stored["insightDensity"] == "quiet"
    assert stored["focusTopics"] == ["pricing review", "hiring plan"]
    assert stored["prepMinutes"] == 45


def test_emptied_fields_mean_none_not_a_silent_default(booted, auth, tmp_path):
    _form(booted, auth, {"focusTopics": "pricing", "prepMinutes": "30"})
    status, _, _ = _form(booted, auth, {"focusTopics": "", "prepMinutes": ""})
    assert status == 303
    stored = _stored(tmp_path)
    assert stored["focusTopics"] == []
    assert stored["prepMinutes"] == 0


def test_a_word_in_the_minute_field_is_refused_and_nothing_is_saved(booted, auth, tmp_path):
    _form(booted, auth, {"prepMinutes": "30", "chart": "bar"})
    status, headers, _ = _form(booted, auth, {"prepMinutes": "half an hour", "chart": "line"})
    assert status == 303
    location = headers["Location"]
    assert location.startswith("/settings?preferences_error=")
    assert "whole%20number" in location or "whole+number" in location
    stored = _stored(tmp_path)
    assert stored["prepMinutes"] == 30
    assert stored["chart"] == "bar"


def test_a_bad_vocabulary_value_returns_the_stores_sentence(booted, auth, tmp_path):
    status, headers, _ = _form(booted, auth, {"chart": "pie"})
    assert status == 303
    assert headers["Location"].startswith("/settings?preferences_error=")
    assert "chart" in headers["Location"]
    assert _stored(tmp_path)["chart"] == "auto"


def test_the_json_route_still_answers_the_document(booted, auth, tmp_path):
    status, _, body = booted.post_json("/api/preferences", {"replyLength": "paragraph"}, auth)
    assert status == 200
    assert json.loads(body)["replyLength"] == "paragraph"
    assert _stored(tmp_path)["replyLength"] == "paragraph"


def test_a_topics_box_is_capped_by_the_store_not_the_route(booted, auth, tmp_path):
    eleven = "\n".join(f"topic {n}" for n in range(11))
    status, headers, _ = _form(booted, auth, {"focusTopics": eleven})
    assert status == 303
    assert headers["Location"].startswith("/settings?preferences_error=")
    assert _stored(tmp_path)["focusTopics"] == []
