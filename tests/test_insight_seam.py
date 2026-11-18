"""The coupled-intelligence seam: one reading per card, one refusal story.

Ticket 01 pins the seam before any family fills it, so the rules asserted
here are the ones every later family inherits:

- A reading is appended to the card's own payload elements, and only
  element kinds the renderer knows can travel.
- A family that raises leaves the card exactly as it was and says why.
- A plugin with no family, or a card with no payload, is untouched.
- Preferences are refused by name when the key or the value is unknown,
  and a stored document always reads back complete.
- The wire routes answer with the same document the store holds, and a
  draft request states its disclosure before anything is composed.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.insight import PreferenceStore, PreferencesError
from agentdesk.insight import service
from agentdesk.insight.context import build_context
from agentdesk.insight.preferences import changed, defaults, prompt_lines
from agentdesk.insight.service import attach_cards
from agentdesk.insight.types import InsightContext, InsightError, InsightReading


def _context(**preferences) -> InsightContext:
    document = defaults()
    document.update(preferences)
    return InsightContext(preferences=document, now=1_700_000_000.0)


def _card(plugin_id: str = "excel-report", elements=None) -> dict:
    return {
        "id": plugin_id,
        "pluginId": plugin_id,
        "payload": {"elements": list(elements or []), "status": "fresh"},
    }


# -- the seam ------------------------------------------------------------


def test_a_reading_is_appended_to_the_cards_own_elements(monkeypatch):
    reading = InsightReading(
        elements=[{"kind": "text", "label": "Reading", "text": "Revenue tracks headcount."}],
        press={"label": "Explain this range", "route": "/api/insight/draft"},
    )
    monkeypatch.setitem(service.FAMILIES, "excel-report", lambda card, payload, ctx: reading)
    card = _card(elements=[{"kind": "metric", "label": "Value", "value": "12"}])

    attach_cards([card], _context(chart="line"))

    kinds = [element["kind"] for element in card["payload"]["elements"]]
    assert kinds == ["metric", "text"]
    assert card["payload"]["insight"] == {
        "status": "ok",
        "source": "local",
        "preferences": ["chart"],
        "note": "",
        "press": reading.press,
        "suggested": [],
    }


def test_a_failing_family_leaves_the_card_and_names_the_reason(monkeypatch):
    def explode(card, payload, ctx):
        raise RuntimeError("a bug in a family")

    monkeypatch.setitem(service.FAMILIES, "excel-report", explode)
    card = _card(elements=[{"kind": "metric", "label": "Value", "value": "12"}])

    attach_cards([card], _context())

    assert card["payload"]["elements"] == [{"kind": "metric", "label": "Value", "value": "12"}]
    assert card["payload"]["insight"]["status"] == "unavailable"
    assert card["payload"]["insight"]["note"]


def test_a_refused_family_keeps_its_own_sentence(monkeypatch):
    def refuse(card, payload, ctx):
        raise InsightError("insight:no-table", "This workbook reading has no table yet.")

    monkeypatch.setitem(service.FAMILIES, "excel-report", refuse)
    card = _card()

    attach_cards([card], _context())

    assert card["payload"]["insight"]["note"] == "This workbook reading has no table yet."


def test_a_plugin_without_a_family_is_untouched():
    card = _card(plugin_id="plugin-health")

    attach_cards([card], _context())

    assert card["payload"] == {"elements": [], "status": "fresh"}


def test_a_card_without_a_payload_is_untouched():
    card = {"pluginId": "outlook-digest", "payload": None}

    attach_cards([card], _context())

    assert card["payload"] is None


def test_an_unknown_element_kind_never_reaches_the_renderer(monkeypatch):
    reading = InsightReading(
        elements=[
            {"kind": "hologram", "text": "not renderable"},
            {"kind": "text", "text": "renderable"},
        ]
    )
    monkeypatch.setitem(service.FAMILIES, "excel-report", lambda card, payload, ctx: reading)
    card = _card()

    attach_cards([card], _context())

    assert card["payload"]["elements"] == [{"kind": "text", "text": "renderable"}]


def test_a_quiet_reading_stays_one_element(monkeypatch):
    reading = InsightReading(
        elements=[{"kind": "text", "text": f"line {index}"} for index in range(4)]
    )
    monkeypatch.setitem(service.FAMILIES, "excel-report", lambda card, payload, ctx: reading)
    card = _card()

    attach_cards([card], _context(insightDensity="quiet"))

    assert len(card["payload"]["elements"]) == 1


# -- the context ---------------------------------------------------------


def test_a_sealed_memory_is_a_note_not_a_crash():
    sealed = SimpleNamespace(is_sealed=True, recall=lambda query: [])

    context = build_context(SimpleNamespace(memory=sealed), defaults())

    assert context.recall is None
    assert "locked" in context.memory_note


def test_a_missing_memory_is_a_note_not_a_crash():
    context = build_context(SimpleNamespace(memory=None), defaults())

    assert context.recall is None
    assert context.memory_note


def test_the_next_meeting_rides_in_the_context():
    view = {
        "upcoming": [{"time": "2026-11-19T09:30:00+00:00", "title": "Pricing review", "meta": "Zoom"}],
        "items": [{"text": "Confirm with Dana", "done": False, "due": "2026-11-19T09:30:00+00:00"}],
    }
    server = SimpleNamespace(memory=None, calendar=SimpleNamespace(day_view=lambda: view))

    context = build_context(server, defaults())

    assert context.agenda == {
        "title": "Pricing review",
        "time": "2026-11-19T09:30:00+00:00",
        "meta": "Zoom",
        "prep": ["Confirm with Dana"],
    }


def test_no_calendar_is_a_note_not_a_crash():
    context = build_context(SimpleNamespace(memory=None, calendar=None), defaults())

    assert context.agenda is None
    assert "calendar" in context.agenda_note


def test_recall_forgets_the_score_and_keeps_the_source():
    class Fact:
        def __init__(self, text, source):
            self.text = text
            self.source = source

    memory = SimpleNamespace(is_sealed=False, recall=lambda query: [(0.9, Fact("pricing call", "inbox"))])

    context = build_context(SimpleNamespace(memory=memory), defaults())

    assert context.recall is not None
    assert context.recall("pricing", 3) == [{"text": "pricing call", "source": "inbox"}]


def test_a_recall_that_raises_reads_as_no_memory():
    def explode(query):
        raise RuntimeError("store gone")

    memory = SimpleNamespace(is_sealed=False, recall=explode)

    context = build_context(SimpleNamespace(memory=memory), defaults())

    assert context.recall is not None
    assert context.recall("anything", 3) == []


# -- preferences ---------------------------------------------------------


def test_a_fresh_store_reads_complete_defaults(tmp_path):
    assert PreferenceStore(tmp_path).read() == defaults()


def test_a_write_merges_over_what_is_stored(tmp_path):
    store = PreferenceStore(tmp_path)

    store.write({"chart": "line"})
    document = store.write({"focusTopics": ["pricing", " Pricing ", "churn"]})

    assert document["chart"] == "line"
    assert document["focusTopics"] == ["pricing", "churn"]
    assert PreferenceStore(tmp_path).read()["chart"] == "line"


def test_an_unknown_key_is_refused_by_name(tmp_path):
    with pytest.raises(PreferencesError) as caught:
        PreferenceStore(tmp_path).write({"chartt": "line"})

    assert caught.value.code == "preferences:unknown-key"
    assert "chartt" in caught.value.message


def test_a_value_outside_the_vocabulary_is_refused(tmp_path):
    with pytest.raises(PreferencesError) as caught:
        PreferenceStore(tmp_path).write({"chart": "pie"})

    assert caught.value.code == "preferences:invalid-value"


def test_a_corrupt_file_reads_as_defaults(tmp_path):
    (tmp_path / "preferences.json").write_text("{ not json", encoding="utf-8")

    assert PreferenceStore(tmp_path).read() == defaults()


def test_prompt_lines_carry_only_what_the_user_set():
    assert prompt_lines(defaults()) == []

    document = defaults()
    document.update({"chart": "bar", "replyTone": "warm", "focusTopics": ["churn"]})

    lines = prompt_lines(document)

    assert any("bar" in line for line in lines)
    assert any("warm" in line for line in lines)
    assert any("churn" in line for line in lines)
    assert changed(document) == ["chart", "replyTone", "focusTopics"]


# -- the wire ------------------------------------------------------------


@pytest.fixture()
def booted(tmp_path, monkeypatch):
    # The desk stores preferences under the data dir, which the gate leaves
    # at the real profile: a test that writes must move it first.
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def test_the_wire_returns_what_the_store_holds(booted):
    auth = booted.exchange()

    status, _headers, body = booted.request("GET", "/api/preferences", auth)
    assert status == 200
    assert json.loads(body)["chart"] == "auto"

    status, _headers, body = booted.post_json("/api/preferences", {"chart": "line"}, auth)
    assert status == 200
    assert json.loads(body)["chart"] == "line"

    status, _headers, body = booted.request("GET", "/api/preferences", auth)
    assert json.loads(body)["chart"] == "line"


def test_the_wire_refuses_an_unknown_key(booted):
    auth = booted.exchange()

    status, _headers, body = booted.post_json("/api/preferences", {"chartt": "line"}, auth)

    assert status == 400
    assert json.loads(body)["code"] == "preferences:unknown-key"


def test_a_draft_states_its_disclosure_before_composing(booted):
    auth = booted.exchange()

    status, _headers, body = booted.post_json(
        "/api/insight/draft",
        {"kind": "reply-draft", "thread": {"subject": "Pricing review"}},
        auth,
    )

    payload = json.loads(body)
    assert status == 200
    assert payload["disclosure"]
    assert payload["status"] == "empty"


def test_a_draft_without_a_thread_is_refused(booted):
    auth = booted.exchange()

    status, _headers, body = booted.post_json("/api/insight/draft", {"kind": "reply-draft"}, auth)

    assert status == 400
    assert json.loads(body)["code"] == "insight:bad-request"


def test_the_dashboard_still_answers_with_the_seam_attached(booted):
    auth = booted.exchange()

    status, _headers, body = booted.request("GET", "/api/dashboard", auth)

    assert status == 200
    assert json.loads(body)["plugins"]["cards"] == []
