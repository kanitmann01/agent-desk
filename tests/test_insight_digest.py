"""The digest families, and the one draft they offer.

outlook-digest already ranks the folder and waiting-on-you already flags
the inbound threads past the threshold, so nothing here scores a message
again. The family reads the threads a card already printed, matches them
against the user's focus topics and the desk's memory, and offers one
draft built from the thread's own lines:

- A thread that touches a focus topic or a remembered fact earns one
  sentence saying which, and at most one memory row beneath it.
- A card whose threads touch nothing gains no element at all.
- A draft needs someone to answer: a subject alone composes nothing, and
  the press still states its disclosure.
- The model path is called once, with a prompt under MAX_PROMPT carrying
  the tone and length lines; a model that fails or answers nothing falls
  back to the same template the local path builds.
"""

import json

import pytest

import server_harness
from agentdesk.insight import digest, press
from agentdesk.server import app as server_app
from agentdesk.insight.types import InsightContext

NOW = 1_760_000_000.0

THREAD = {
    "subject": "Pricing review",
    "sender": "Priya Raman",
    "last": "Can you confirm the new tiers by Friday?",
    "age": "2 h ago",
}


def context(**kwargs) -> InsightContext:
    preferences = kwargs.pop("preferences", {})
    return InsightContext(preferences=preferences, now=NOW, **kwargs)


def outlook_payload() -> dict:
    """The elements outlook-digest renders, in the order it renders them."""
    return {
        "elements": [
            {"kind": "metric", "label": "Active messages (24h)", "value": 12},
            {"kind": "text", "label": "Most important email", "text": "Pricing review"},
            {"kind": "text", "label": "From", "text": "Priya Raman · 2 h ago"},
            {
                "kind": "text",
                "label": "Why this one",
                "text": "It asks a question and arrived this morning.",
            },
            {
                "kind": "list",
                "title": "Active threads",
                "rows": [
                    {
                        "primary": "Pricing review",
                        "secondary": "Priya Raman",
                        "meta": "3 msg · 2 h ago",
                    },
                    {"primary": "Q3 hiring plan", "secondary": "Tom Yates", "meta": "1 msg · 5 h ago"},
                ],
            },
            {
                "kind": "list",
                "title": "Reply starters",
                "rows": [
                    {
                        "primary": 'Good question. I will check the details on "pricing" and come back.',
                        "secondary": "Direct",
                        "meta": "reply starter",
                    }
                ],
            },
            {"kind": "text", "label": "Scope", "text": "Mail from the last 24 hours."},
        ]
    }


def waiting_payload() -> dict:
    return {
        "elements": [
            {
                "kind": "list",
                "title": "Threads waiting on you",
                "rows": [{"primary": "Invoice for March", "secondary": "Dana Whitfield", "meta": "3d"}],
            },
            {"kind": "metric", "label": "Open threads", "value": 2},
        ]
    }


# --- what the card already printed ---------------------------------------


def test_thread_facts_reads_the_threads_the_card_prints():
    threads = digest.thread_facts(outlook_payload())
    assert [thread["subject"] for thread in threads] == ["Pricing review", "Q3 hiring plan"]
    assert threads[0]["sender"] == "Priya Raman"
    assert threads[0]["age"] == "2 h ago"
    assert threads[1]["sender"] == "Tom Yates"
    assert threads[1]["age"] == "1 msg · 5 h ago"


def test_reply_starters_are_not_threads():
    subjects = [thread["subject"] for thread in digest.thread_facts(outlook_payload())]
    assert not any("Good question" in subject for subject in subjects)


def test_a_card_with_no_thread_offers_no_draft():
    reading = digest.derive(
        {"pluginId": "outlook-digest"},
        {"elements": [{"kind": "metric", "label": "Active messages (24h)", "value": 0}]},
        context(),
    )
    assert reading.elements == []
    assert reading.press is None
    assert reading.status == "empty"


# --- the coupling the card did not have ----------------------------------


def test_a_focus_topic_names_the_thread_it_matches():
    reading = digest.derive(
        {"pluginId": "outlook-digest"},
        outlook_payload(),
        context(preferences={"focusTopics": ["pricing"]}),
    )
    assert reading.status == "ok"
    assert [element["kind"] for element in reading.elements] == ["text"]
    text = reading.elements[0]["text"]
    assert text.startswith("Pricing review, from Priya Raman (2 h ago).")
    assert "That matches your focus topic pricing." in text
    assert reading.press == {
        "label": "Draft a reply",
        "route": "/api/insight/draft",
        "kind": "reply-draft",
        # Only what the disclosure names travels with the press.
        "thread": {"subject": "Pricing review", "sender": "Priya Raman"},
    }


def test_memory_names_the_fact_behind_the_thread():
    facts = [
        {"text": "Priya owns the pricing model.", "source": "notes"},
        {"text": "The pricing sheet is in the drive folder.", "source": "drive"},
    ]
    reading = digest.derive(
        {"pluginId": "outlook-digest"},
        outlook_payload(),
        context(recall=lambda subject, limit: facts),
    )
    assert reading.status == "ok"
    assert "In your notes: Priya owns the pricing model." in reading.elements[0]["text"]
    assert reading.elements[1] == {
        "kind": "list",
        "title": "From your notes",
        "rows": [
            {
                "primary": "The pricing sheet is in the drive folder.",
                "secondary": "",
                "meta": "drive",
            }
        ],
    }


def test_a_card_whose_threads_touch_nothing_gains_no_element():
    payload = outlook_payload()
    before = json.loads(json.dumps(payload))
    reading = digest.derive(
        {"pluginId": "outlook-digest"},
        payload,
        context(preferences={"focusTopics": ["renewals"]}),
    )
    assert reading.elements == []
    assert reading.status == "empty"
    assert payload == before
    # The card's own pick is still the thread worth drafting from.
    assert reading.press["thread"]["subject"] == "Pricing review"


def test_waiting_card_says_who_is_waiting():
    reading = digest.derive(
        {"pluginId": "waiting-on-you"},
        waiting_payload(),
        context(preferences={"focusTopics": ["invoice"]}),
    )
    assert reading.elements[0]["text"].startswith(
        "Dana Whitfield is waiting on Invoice for March (3d)."
    )


# --- the draft ------------------------------------------------------------


def test_a_subject_alone_is_not_a_draft():
    assert digest.compose_draft({"subject": "Pricing review"}, {}) == ("", "none")


def test_compose_without_a_model_is_the_users_template():
    text, source = digest.compose_draft(THREAD, {"replyTone": "warm", "replyLength": "short"})
    assert source == "template"
    assert text.startswith("Hi Priya,")
    assert "Thanks for sending this over." in text
    assert 'You asked: "Can you confirm the new tiers by Friday?"' in text


def test_template_adds_no_fact_of_its_own():
    text, _ = digest.compose_draft({"subject": "Pricing review", "sender": "Priya Raman"}, {})
    assert "I have your note on Pricing review and will come back to you by [date]." in text
    assert "Friday" not in text
    assert "tomorrow" not in text


def test_one_line_length_is_one_line():
    text, _ = digest.compose_draft(
        {"subject": "Pricing review", "sender": "Priya Raman"}, {"replyLength": "one-line"}
    )
    assert "\n" not in text


def test_formal_tone_addresses_the_sender_by_name():
    text, _ = digest.compose_draft(THREAD, {"replyTone": "formal", "replyLength": "paragraph"})
    assert text.startswith("Dear Priya,")
    assert "Thank you for your message." in text


def test_compose_with_a_model_calls_it_once_with_a_bounded_prompt():
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return "Hi Priya, the tiers are confirmed."

    preferences = {
        "replyTone": "formal",
        "replyLength": "paragraph",
        "focusTopics": ["pricing", "renewals"],
    }
    text, source = digest.compose_draft(THREAD, preferences, complete=complete)
    assert source == "model"
    assert text == "Hi Priya, the tiers are confirmed."
    assert len(prompts) == 1
    prompt = prompts[0]
    assert len(prompt) < digest.MAX_PROMPT
    assert "Subject: Pricing review" in prompt
    assert "Reply tone: formal. Length: paragraph." in prompt
    assert "Focus topics: pricing, renewals." in prompt
    assert "Do not invent deadlines" in prompt
    # The tone and length travel once, in the line above.
    assert "Replies:" not in prompt


def test_a_long_thread_is_still_a_short_prompt():
    thread = {
        "subject": "Pricing review " * 40,
        "sender": "Priya Raman " * 20,
        "last": "Can you confirm the tiers? " * 40,
        "age": "2 h ago",
    }
    prompts = []
    digest.compose_draft(thread, {}, complete=lambda prompt: prompts.append(prompt) or "ok")
    assert len(prompts[0]) < digest.MAX_PROMPT


@pytest.mark.parametrize("answer", [RuntimeError("the model is off"), "", "   "])
def test_a_failed_or_empty_answer_falls_back_to_the_template(answer):
    def complete(prompt):
        if isinstance(answer, Exception):
            raise answer
        return answer

    text, source = digest.compose_draft(THREAD, {}, complete=complete)
    assert source == "template"
    assert text == digest.compose_draft(THREAD, {})[0]


# --- the press ----------------------------------------------------------


def test_press_refuses_to_dress_a_skeleton_as_a_draft():
    from agentdesk.insight.types import InsightError

    with pytest.raises(InsightError) as caught:
        press.draft_reply(
            None,
            {"kind": "reply-draft", "thread": THREAD},
            preferences={"replyTone": "direct"},
        )
    assert caught.value.status == 409
    assert caught.value.code == "insight:model-off"
    # The refusal repeats what would have travelled, so the promise and the
    # refusal are the same sentence.
    assert "Sends: the thread's subject" in caught.value.message
    assert "Does not send: the rest of the thread" in caught.value.message


def test_press_falls_back_to_a_labelled_skeleton_when_the_model_fails():
    def complete(prompt):
        raise RuntimeError("the model stopped")

    reply = press.draft_reply(
        None,
        {"kind": "reply-draft", "thread": THREAD},
        preferences={"replyTone": "direct"},
        complete=complete,
    )
    assert reply["status"] == "draft"
    assert reply["source"] == "template"
    assert reply["note"] == press.SKELETON_NOTE
    assert "Pricing review" in reply["text"]
    assert len(reply["disclosure"]) == 2


def test_press_passes_a_model_answer_through_unchanged():
    reply = press.draft_reply(
        None,
        {"kind": "reply-draft", "thread": THREAD},
        preferences={},
        complete=lambda prompt: "Confirmed.",
    )
    assert reply["source"] == "model"
    assert reply["text"] == "Confirmed."
    assert reply["note"] == ""


def test_press_refuses_a_request_without_a_thread():
    from agentdesk.insight.types import InsightError

    with pytest.raises(InsightError) as caught:
        press.draft_reply(None, {"kind": "reply-draft", "thread": {}}, preferences={})
    assert caught.value.code == "insight:bad-request"


def test_press_states_its_disclosure_before_an_empty_draft():
    reply = press.draft_reply(
        None, {"kind": "reply-draft", "thread": {"subject": "Pricing review"}}, preferences={}
    )
    assert reply["status"] == "empty"
    assert reply["text"] == ""
    assert reply["disclosure"]


# --- the wire, as the card's own button reaches it ------------------------


@pytest.fixture
def booted(tmp_path, monkeypatch):
    # The preference store writes under the data dir, which the gate leaves
    # at the real profile, so a test that reads it must move it first.
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def test_the_draft_route_refuses_with_409_when_the_model_is_off(booted):
    auth = booted.exchange()

    status, _headers, body = booted.post_json(
        "/api/insight/draft", {"kind": "reply-draft", "thread": THREAD}, auth
    )

    payload = json.loads(body)
    assert status == 409
    assert payload["code"] == "insight:model-off"
    assert "Sends: the thread's subject" in payload["error"]


def test_the_draft_route_returns_a_model_draft_when_one_is_injected(booted, monkeypatch):
    monkeypatch.setattr(
        server_app.DashboardHandler,
        "_insight_complete",
        lambda self: (lambda prompt: "Hi Priya, the tiers are confirmed."),
    )
    auth = booted.exchange()

    status, _headers, body = booted.post_json(
        "/api/insight/draft", {"kind": "reply-draft", "thread": THREAD}, auth
    )

    payload = json.loads(body)
    assert status == 200
    assert payload["source"] == "model"
    assert payload["text"] == "Hi Priya, the tiers are confirmed."
    assert payload["note"] == ""
