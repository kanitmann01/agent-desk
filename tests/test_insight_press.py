"""The pressed path: one finding explained, one reply drafted, nothing sent.

Every test here drives `press.draft_reply` directly. The route in front of
it only reads preferences and passes the model closure through, and that
wiring is covered by the seam suite.
"""

from __future__ import annotations

import pytest

from agentdesk.insight import press
from agentdesk.insight.preferences import defaults
from agentdesk.insight.types import InsightError


def _prefs() -> dict:
    return defaults()


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
