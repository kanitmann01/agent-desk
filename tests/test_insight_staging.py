"""Staging a drafted reply: one card, one acceptance, one outbox file.

The press and the acceptance run through the booted server, so the promise
that a staged card is written by the same path a hand-typed reply uses is
proven end to end rather than by calling the writer directly.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.inbox.store import InboxStore
from agentdesk.insight import press
from agentdesk.mail.store import MailStore
from agentdesk.settings import SettingsStore

MESSAGE_ID = "<budget-1@example.com>"
MODEL_TEXT = "Thanks for the numbers. I will send the revised budget by Friday."


def _eml() -> bytes:
    """One message in the folder, the fixtures' shape."""
    lines = [
        "From: Priya Raman <priya@example.com>",
        "To: employee@example.com",
        "Subject: Budget",
        "Date: Wed, 11 Nov 2026 09:00:00 +0000",
        f"Message-ID: {MESSAGE_ID}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "",
        "placeholder body",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


@pytest.fixture()
def env(tmp_path):
    folder = tmp_path / "mail"
    folder.mkdir()
    (folder / "budget.eml").write_bytes(_eml())
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    settings.set("mail_enabled", True)
    settings.set("mail_folder", str(folder))
    settings.set("mail_self_address", "employee@example.com")
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    store = MailStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    outbox = tmp_path / "outbox"
    booted = server_harness.Booted(
        llm=lambda _prompt: MODEL_TEXT,
        llm_endpoint="http://127.0.0.1:9/v1",
        outbox_dir=outbox,
        inbox_store=inbox,
        mail_store=store,
        settings_store=settings,
    )
    booted.outbox = outbox
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _post(env, auth, body: dict) -> tuple[int, dict]:
    status, _headers, raw = env.post_json("/api/insight/draft", body, auth)
    return status, json.loads(raw) if raw else {}


def _drafted(env) -> list:
    """The drafted-reply cards still waiting: the mail watch files its own."""
    return [
        card for card in env.server.inbox.waiting()
        if card.kind == "suggestion" and card.title.startswith("Drafted reply:")
    ]


def test_a_press_stages_one_card_and_acceptance_writes_one_eml(env, auth):
    body = {"kind": "reply-draft",
            "thread": {"subject": "Budget", "sender": "priya@example.com"},
            "stage": True}
    status, answer = _post(env, auth, body)
    assert status == 200
    assert answer["staged"] is True
    assert answer["source"] == "model"
    assert answer["text"] == MODEL_TEXT
    assert answer["thread"] == {
        "id": MESSAGE_ID,
        "to": ["Priya Raman <priya@example.com>"],
        "subject": "Re: Budget",
    }
    # Headers and a draft travel; the message's body never reaches the answer.
    assert "placeholder body" not in json.dumps(answer)

    cards = _drafted(env)
    assert len(cards) == 1
    card = cards[0]
    assert card.id == answer["cardId"]
    print(json.dumps(card.to_json(env.server.inbox.now_ts()), indent=2, sort_keys=True))
    assert card.origin.startswith("Drafted by the model")
    assert card.draft == MODEL_TEXT
    assert card.meta == {"mailDraft": {
        "messageId": MESSAGE_ID,
        "to": "Priya Raman <priya@example.com>",
        "subject": "Re: Budget",
        "thread": "Budget",
    }}

    status, repeat = _post(env, auth, body)
    assert status == 200
    assert repeat["staged"] is False
    assert repeat["cardId"] == card.id
    assert len(_drafted(env)) == 1

    status, edited = _post(env, auth, dict(body, text="A shorter answer."))
    assert status == 200
    assert edited["staged"] is True
    assert edited["cardId"] != card.id
    assert len(_drafted(env)) == 2

    status, _headers, _raw = env.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    assert status == 200
    files = list(env.outbox.glob("*.eml"))
    assert len(files) == 1
    text = files[0].read_bytes().decode("utf-8")
    headers = text.split("\r\n\r\n", 1)[0]
    assert f"In-Reply-To: {MESSAGE_ID}" in headers
    assert "To: Priya Raman <priya@example.com>" in headers
    assert "Subject: Re: Budget" in headers
    assert "Message-ID: <reply-" in headers
    assert MODEL_TEXT in text


def test_a_press_that_names_no_thread_refuses_and_stages_nothing(env, auth):
    status, answer = _post(env, auth, {
        "kind": "reply-draft",
        "thread": {"subject": "Q3 plan", "sender": "priya@example.com"},
        "stage": True,
    })
    assert status == 404
    assert answer["code"] == "insight:thread-missing"
    assert '"Q3 plan"' in answer["error"]
    assert press.DISCLOSURE[0] in answer["error"]
    assert _drafted(env) == []


# -- the audit trail on the JSON door (spec 017 workstream 3) --------------


def _press_rows(env) -> list:
    return [e for e in audit_store.entries(env.server.audit_conn)
            if e["action"] == "insight.press"]


def test_a_json_press_writes_the_row_its_no_js_twin_writes(env, auth):
    status, answer = _post(env, auth, {
        "kind": "reply-draft",
        "thread": {"subject": "Budget", "sender": "priya@example.com"},
        "stage": True,
    })
    assert status == 200
    rows = _press_rows(env)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ok"
    # The row names the thread and the source, never the words.
    assert row["target"] == MESSAGE_ID
    assert row["detail"] == "reply-draft:model: staged " + answer["cardId"]
    assert MODEL_TEXT not in row["detail"]


def test_a_json_press_refused_before_any_call_records_an_error_row(env, auth):
    status, answer = _post(env, auth, {
        "kind": "reply-draft",
        "thread": {"subject": "Q3 plan", "sender": "priya@example.com"},
        "stage": True,
    })
    assert status == 404
    assert answer["code"] == "insight:thread-missing"
    rows = _press_rows(env)
    # The refusal is the only row, and it is an error: nothing claims a
    # call was spent or a card staged.
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["detail"] == "insight:thread-missing"
    assert [r for r in rows if r["status"] == "ok"] == []
    assert _drafted(env) == []
