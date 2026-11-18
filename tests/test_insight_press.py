"""The pressed path: one finding explained, one reply drafted, nothing sent.

Every test here drives `press.draft_reply` directly, with a stand-in for the
mail view and a real inbox. The route in front of it only reads preferences
and passes the model closure through; that wiring is covered by
tests/test_insight_staging against the running server.
"""

from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace

import pytest

from agentdesk.inbox.store import InboxStore
from agentdesk.insight import press
from agentdesk.insight.preferences import defaults
from agentdesk.insight.types import InsightError
from agentdesk.mail.core import parse_eml, with_threads


def _prefs() -> dict:
    return defaults()


def _eml(message_id: str, subject: str, sender: str, to: str = "you@desk") -> object:
    """One message as the folder read hands it over: headers, no body."""
    lines = [
        f"From: {sender}",
        f"To: {to}",
        f"Subject: {subject}",
        "Date: Wed, 11 Nov 2026 09:00:00 +0000",
        f"Message-ID: {message_id}",
        "",
        "placeholder body",
    ]
    return parse_eml("\r\n".join(lines) + "\r\n")


class _Mail:
    """The mail view a press reads: the watch's read-only payload.

    Only the two facts press.py uses are modelled, the state and the
    threaded messages, because reading a folder is the watcher's job and is
    covered where the watcher is.
    """

    def __init__(self, *messages: object, state: str = "watching") -> None:
        self._messages = list(messages)
        self._state = state
        self.self_address = "you@desk"

    def view(self) -> dict:
        messages = with_threads(list(self._messages)) if self._state == "watching" else []
        return {"state": self._state, "messages": messages}


def _server(mail: object = None, inbox: object = None) -> SimpleNamespace:
    return SimpleNamespace(mail=mail, inbox=inbox)


def _inbox() -> InboxStore:
    return InboxStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _answer(server, body: dict, complete=None) -> dict:
    return press.draft_reply(
        server, body, preferences=_prefs(),
        complete=complete if complete is not None else (lambda _prompt: "Thanks."),
    )


def test_an_explanation_states_what_travels_and_what_does_not():
    with pytest.raises(InsightError) as caught:
        press.draft_reply(None, {"kind": "explain-range", "text": "Booked falls as Margin rises."},
                          preferences=_prefs(), complete=None)
    assert caught.value.status == 409
    assert caught.value.code == "insight:model-off"
    assert "model calls are off" in caught.value.message
    assert "Does not send: the workbook" in caught.value.message


def test_an_explanation_sends_only_the_finding(monkeypatch):
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return "Two of your regions grew while the total stayed flat."

    answer = press.draft_reply(
        None,
        {"kind": "explain-range", "text": "Region A carries 62% of the range."},
        preferences=_prefs(),
        complete=complete,
    )
    assert answer["status"] == "draft"
    assert answer["source"] == "model"
    assert answer["text"].startswith("Two of your regions")
    assert answer["disclosure"] == list(press.EXPLAIN_DISCLOSURE)
    assert len(prompts) == 1
    assert "Region A carries 62% of the range." in prompts[0]
    assert len(prompts[0]) < press.MAX_FINDING + len(press.EXPLAIN_PROMPT) + 8


def test_a_model_that_fails_explains_nothing_rather_than_crashing():
    def complete(_prompt: str) -> str:
        raise TimeoutError("the endpoint stopped answering")

    answer = press.draft_reply(
        None, {"kind": "explain-range", "text": "Booked falls as Margin rises."},
        preferences=_prefs(), complete=complete,
    )
    assert answer["status"] == "empty"
    assert answer["text"] == ""
    assert answer["source"] == "none"
    assert "did not answer" in answer["note"]


def test_an_explanation_needs_the_finding():
    with pytest.raises(InsightError) as caught:
        press.draft_reply(None, {"kind": "explain-range"}, preferences=_prefs(),
                          complete=lambda _prompt: "x")
    assert caught.value.code == "insight:bad-request"


def test_an_oversized_finding_is_refused_before_any_call():
    calls: list[str] = []
    with pytest.raises(InsightError) as caught:
        press.draft_reply(
            None, {"kind": "explain-range", "text": "x" * (press.MAX_FINDING + 1)},
            preferences=_prefs(), complete=lambda prompt: calls.append(prompt) or "y",
        )
    assert caught.value.status == 400
    assert calls == []


def test_an_unknown_kind_is_named_back():
    with pytest.raises(InsightError) as caught:
        press.draft_reply(None, {"kind": "rewrite-the-sheet"}, preferences=_prefs(),
                          complete=lambda _prompt: "x")
    assert caught.value.code == "insight:unknown-kind"
    assert "rewrite-the-sheet" in caught.value.message


# -- which thread a draft answers -----------------------------------------


def test_one_thread_resolves_and_echoes_recipients():
    server = _server(_Mail(
        _eml("<m1@example.com>", "Budget", "Priya Raman <priya@example.com>"),
        _eml("<other@example.com>", "Lunch", "Tom <tom@example.com>"),
    ))
    answer = _answer(server, {
        "kind": "reply-draft",
        "subject": "  budget ",
        "sender": "priya raman",
    })
    assert answer["thread"] == {
        "id": "<m1@example.com>",
        "to": ["Priya Raman <priya@example.com>"],
        "subject": "Re: Budget",
    }
    assert answer["source"] == "model"
    assert "staged" not in answer
    assert "cardId" not in answer


def test_a_reply_subject_resolves_the_thread_it_belongs_to():
    server = _server(_Mail(_eml("<m1@example.com>", "Budget", "priya@example.com")))
    answer = _answer(server, {"kind": "reply-draft", "subject": "Re: Budget",
                              "sender": "priya@example.com"})
    assert answer["thread"]["id"] == "<m1@example.com>"
    assert answer["thread"]["subject"] == "Re: Budget"


def test_two_threads_with_one_subject_refuse_and_name_the_senders():
    inbox = _inbox()
    server = _server(_Mail(
        _eml("<a@example.com>", "Budget", "Priya Raman <priya@example.com>"),
        _eml("<b@example.com>", "Budget", "priya@example.com"),
    ), inbox)
    with pytest.raises(InsightError) as caught:
        _answer(server, {"kind": "reply-draft", "subject": "Budget",
                         "sender": "priya@example.com", "stage": True})
    assert caught.value.code == "insight:thread-ambiguous"
    assert caught.value.status == 409
    message = caught.value.message
    assert 'more than one message has the subject "Budget"' in message
    assert "Priya Raman and priya@example.com" in message
    assert press.DISCLOSURE[1] in message
    assert inbox.waiting() == []


def test_a_thread_that_is_not_there_is_named_back():
    inbox = _inbox()
    server = _server(_Mail(_eml("<m1@example.com>", "Budget", "priya@example.com")), inbox)
    with pytest.raises(InsightError) as caught:
        _answer(server, {"kind": "reply-draft", "subject": "Q3 plan",
                         "sender": "priya@example.com", "stage": True})
    assert caught.value.code == "insight:thread-missing"
    assert caught.value.status == 404
    assert '"Q3 plan"' in caught.value.message
    assert press.DISCLOSURE[0] in caught.value.message
    assert inbox.waiting() == []


def test_mail_off_refuses_and_says_what_would_have_travelled():
    with pytest.raises(InsightError) as caught:
        _answer(_server(None), {"kind": "reply-draft", "subject": "Budget",
                                "sender": "priya@example.com"})
    assert caught.value.code == "insight:mail-off"
    assert caught.value.status == 503
    assert "mail digest is off on this desk" in caught.value.message
    assert "Turn it on in Settings, then ask again." in caught.value.message
    assert press.DISCLOSURE[0] in caught.value.message


def test_a_desk_without_a_mail_folder_names_the_setting_to_fix():
    server = _server(_Mail(state="unconfigured"))
    with pytest.raises(InsightError) as caught:
        _answer(server, {"kind": "reply-draft", "subject": "Budget",
                         "sender": "priya@example.com"})
    assert caught.value.code == "insight:mail-off"
    assert caught.value.status == 503
    assert "no mail folder has been chosen yet" in caught.value.message
    assert "Choose the folder in Settings, then ask again." in caught.value.message


def test_a_press_without_a_sender_keeps_todays_answer():
    answer = _answer(None, {"kind": "reply-draft",
                            "thread": {"subject": "Budget", "last": "Can we talk?"}})
    assert set(answer) == {"status", "text", "source", "disclosure", "note"}


# -- staging one card -----------------------------------------------------


def test_staging_adds_one_card_and_a_repeat_press_adds_nothing():
    inbox = _inbox()
    server = _server(
        _Mail(_eml("<m1@example.com>", "Budget", "Priya Raman <priya@example.com>")), inbox
    )
    body = {"kind": "reply-draft", "subject": "Budget",
            "sender": "priya@example.com", "stage": True}
    first = _answer(server, body)
    assert first["staged"] is True
    card = inbox.waiting()[0]
    assert card.id == first["cardId"]
    assert card.kind == "suggestion"
    assert card.title == "Drafted reply: Re: Budget"
    assert card.draft == "Thanks."
    assert card.origin.startswith("Drafted by the model")
    assert card.meta == {"mailDraft": {
        "messageId": "<m1@example.com>",
        "to": "Priya Raman <priya@example.com>",
        "subject": "Re: Budget",
        "thread": "Budget",
    }}
    repeat = _answer(server, body)
    assert repeat["staged"] is False
    assert repeat["cardId"] == first["cardId"]
    assert len(inbox.waiting()) == 1
    edited = _answer(server, dict(body, text="A different sentence."))
    assert edited["staged"] is True
    assert edited["cardId"] != first["cardId"]
    assert len(inbox.waiting()) == 2


def test_a_skeleton_says_it_is_not_a_model_draft():
    def complete(_prompt: str) -> str:
        raise TimeoutError("the endpoint stopped answering")

    inbox = _inbox()
    server = _server(_Mail(_eml("<m1@example.com>", "Budget", "priya@example.com")), inbox)
    answer = _answer(server, {"kind": "reply-draft", "subject": "Budget",
                              "sender": "priya@example.com", "stage": True},
                     complete=complete)
    assert answer["source"] == "template"
    assert answer["staged"] is True
    card = inbox.waiting()[0]
    assert card.origin.startswith("Skeleton, not a model draft")
    assert card.draft == answer["text"]


def test_a_stage_request_without_a_sender_stages_nothing():
    inbox = _inbox()
    with pytest.raises(InsightError) as caught:
        _answer(_server(_Mail(), inbox),
                {"kind": "reply-draft", "subject": "Budget", "stage": True})
    assert caught.value.code == "insight:thread-missing"
    assert caught.value.status == 404
    assert "does not say who the thread" in caught.value.message
    assert inbox.waiting() == []
