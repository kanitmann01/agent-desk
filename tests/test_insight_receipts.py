"""Every reading says what it used.

A reading carries two tuples: the preference keys whose stored value shaped
it, and the inputs it consulted. The presentation turns them into the
receipts a card prints, filtered to a fixed vocabulary so no surface has to
look a name up, and so no value ever travels: a focus list cannot ride into
a screenshot on the back of a receipt.

The families are held to the narrow rules the ticket gives them:

- the workbook declares `chart` only once it is off auto, because that is
  when the setting changed the sentence;
- the digest declares `replyTone` and `replyLength` only when resetting
  either to its default would build a different draft;
- the calendar declares `prepMinutes` only when the stored window is not
  the default one;
- the research reading declares no preference at all, because its focus
  topics are already visible in its sentences.

Memory is a declared input when the reading was allowed to read it, and a
sealed bank is not declared: the reading's own note is what says why.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agentdesk.insight import reading as insight_reading
from agentdesk.insight import service
from agentdesk.insight.context import build_context
from agentdesk.insight.preferences import FIELDS, defaults
from agentdesk.insight.types import InsightContext, InsightReading

NOW = 1_760_000_000.0

# The ticket's printed line, in the two shapes that carry no count: the input
# names and the key names are the whole vocabulary the card knows.
EMPTY = {"preferences": [], "inputs": []}


def _context(
    *,
    recall=None,
    agenda=None,
    memory_note="",
    density="normal",
    **preferences,
) -> InsightContext:
    document = defaults()
    document.update(preferences)
    document["insightDensity"] = density
    return InsightContext(
        preferences=document,
        now=NOW,
        recall=recall,
        memory_note=memory_note,
        agenda=agenda,
        agenda_note="" if agenda else "Nothing left on the calendar.",
    )


def _card(plugin_id: str, payload: dict) -> dict:
    return {"id": "card-1", "pluginId": plugin_id, "payload": payload}


def _receipts(plugin_id: str, payload: dict, context: InsightContext) -> dict:
    """The receipts the presentation prints for one card's reading."""
    card = _card(plugin_id, payload)
    derived = service.FAMILIES[plugin_id](card, payload, context)
    return insight_reading.receipts(derived)


def _recall(subject: str, limit: int = 3) -> list[dict]:
    """Two facts that mention the subject, as the context's adapter returns them."""
    return [
        {"text": f"{subject} came up in the last review", "source": "note"},
        {"text": f"{subject} was agreed on Friday", "source": "mail"},
    ][:limit]


def _meeting() -> dict:
    return {
        "title": "Design review",
        "time": "2026-11-18T14:30:00",
        "meta": "Room 4",
        "prep": ["Bring the two shortlisted vendors"],
    }


def _tracker() -> dict:
    """A table with a trend, a share and enough rows for both detectors."""
    rows = []
    regions = ["A"] * 7 + ["B"] * 3 + ["C"] * 2
    booked = [10, 4, 10, 4, 10, 4, 10, 4, 10, 4, 10, 4]
    for index in range(12):
        rows.append([f"2026-{index + 1:02d}-01", 10 + index, regions[index], booked[index]])
    return {"table": {"headers": ["Month", "Booked", "Region", "Booked again"], "rows": rows}}


def _threads() -> dict:
    return {
        "elements": [
            {
                "kind": "list",
                "title": "Active threads",
                "rows": [
                    {
                        "primary": "Pricing review",
                        "secondary": "Priya Raman",
                        "meta": "3 msg · 2 h ago",
                    }
                ],
            }
        ]
    }


def _answer_payload() -> dict:
    return {
        "elements": [
            {
                "kind": "text",
                "label": "Latest answer",
                "text": (
                    "Forward-deployed engineering pairs one engineer with a customer "
                    "team for 90 days."
                ),
            },
            {"kind": "text", "label": "Answered", "text": "2026-11-13 09:41"},
        ]
    }


# -- the vocabulary ------------------------------------------------------


def test_the_service_keeps_the_order_drops_unknown_names_and_dedupes(monkeypatch):
    reading = InsightReading(
        used=("chart", "chart", "colour", "replyTone"),
        inputs=("memory", "sqlite", "rows", "memory"),
    )
    monkeypatch.setitem(service.FAMILIES, "excel-report", lambda card, payload, ctx: reading)

    receipts = _receipts("excel-report", {"elements": []}, _context())

    assert receipts == {"preferences": ["chart", "replyTone"], "inputs": ["memory", "rows"]}


def test_a_count_rides_only_on_a_memory_input_that_was_declared():
    counted = InsightReading(inputs=("memory",), memory_notes=2)
    assert insight_reading.receipts(counted) == {
        "preferences": [],
        "inputs": ["memory"],
        "counts": {"memory": 2},
    }
    # A count without the input it counts would print a number for a source
    # the reading never named, and zero has nothing to count.
    assert "counts" not in insight_reading.receipts(
        InsightReading(inputs=("rows",), memory_notes=2)
    )
    assert "counts" not in insight_reading.receipts(
        InsightReading(inputs=("memory",), memory_notes=0)
    )


def test_a_reading_that_used_nothing_writes_empty_lists(monkeypatch):
    reading = InsightReading(elements=[{"kind": "text", "text": "Booked falls as Margin rises."}])
    monkeypatch.setitem(service.FAMILIES, "excel-report", lambda card, payload, ctx: reading)

    receipts = _receipts("excel-report", {"elements": []}, _context(chart="bar"))

    assert receipts == EMPTY


def test_a_failing_family_degrades_and_declares_nothing(monkeypatch):
    def explode(card, payload, ctx):
        raise RuntimeError("a bug in a family")

    monkeypatch.setitem(service.FAMILIES, "excel-report", explode)
    card = _card("excel-report", {"elements": []})

    service.attach_cards([card], _context(chart="bar"))

    insight = card["payload"]["insight"]
    assert insight["status"] == "unavailable"
    # The failure is the card's whole line: nothing was used, so the only
    # block is the note that says the reading could not be worked out.
    assert insight["blocks"] == [
        {"kind": "note", "text": "This card's reading could not be worked out."}
    ]


# -- the workbook --------------------------------------------------------


def test_the_workbook_declares_a_chart_setting_that_changed_the_sentence():
    assert _receipts("excel-report", {"elements": [], "tracker": _tracker()}, _context(chart="bar")) == {
        "preferences": ["chart"],
        "inputs": ["rows"],
    }


def test_the_workbook_never_receipts_a_chart_left_on_auto():
    receipts = _receipts("excel-report", {"elements": [], "tracker": _tracker()}, _context())
    assert receipts == {"preferences": [], "inputs": ["rows"]}


def test_a_workbook_with_no_table_to_read_declares_nothing():
    assert _receipts("excel-report", {"elements": []}, _context(chart="bar")) == EMPTY


# -- the digest ----------------------------------------------------------


def test_the_digest_declares_the_draft_preferences_that_shaped_the_skeleton():
    receipts = _receipts(
        "outlook-digest",
        _threads(),
        _context(replyTone="warm", replyLength="one-line"),
    )
    assert receipts["preferences"] == ["replyTone", "replyLength"]


def test_the_digest_declares_nothing_when_the_draft_reads_as_it_defaults():
    receipts = _receipts("outlook-digest", _threads(), _context())
    assert receipts["preferences"] == []


@pytest.mark.parametrize(
    "preferences, declared",
    [
        ({"replyTone": "warm"}, ["replyTone"]),
        ({"replyLength": "one-line"}, ["replyLength"]),
        ({"insightDensity": "chatty"}, []),
        ({"focusTopics": ["pricing"]}, []),
    ],
)
def test_each_draft_preference_is_declared_only_when_it_changed_the_skeleton(
    preferences, declared
):
    receipts = _receipts("outlook-digest", _threads(), _context(**preferences))
    assert receipts["preferences"] == declared


def test_a_thread_with_nobody_to_answer_declares_no_draft_preference():
    # A subject alone composes no skeleton, so no tone or length shaped one.
    payload = {
        "elements": [
            {"kind": "list", "rows": [{"primary": "Pricing review", "secondary": "", "meta": ""}]}
        ]
    }
    receipts = _receipts(
        "outlook-digest", payload, _context(replyTone="warm", replyLength="one-line")
    )
    assert receipts["preferences"] == []


# -- the calendar --------------------------------------------------------


def test_the_calendar_declares_the_prep_window_it_was_given():
    receipts = _receipts(
        "calendar-today", {"elements": []}, _context(agenda=_meeting(), prepMinutes=25)
    )
    assert receipts == {"preferences": ["prepMinutes"], "inputs": ["calendar"]}


def test_the_calendar_never_receipts_the_default_prep_window():
    receipts = _receipts("calendar-today", {"elements": []}, _context(agenda=_meeting()))
    assert receipts["preferences"] == []


def test_a_prep_window_of_zero_is_the_users_decision_and_is_declared():
    # Zero is what makes the line say no window is set, so it changed the
    # reading exactly as a 25-minute window would have.
    receipts = _receipts(
        "calendar-today", {"elements": []}, _context(agenda=_meeting(), prepMinutes=0)
    )
    assert receipts["preferences"] == ["prepMinutes"]


def test_a_calendar_with_no_meeting_declares_nothing():
    assert _receipts("calendar-today", {"elements": []}, _context()) == EMPTY


# -- the research reading ------------------------------------------------


def test_the_research_reading_names_its_sources_and_no_preference():
    receipts = _receipts(
        "research-brief",
        _answer_payload(),
        _context(
            agenda=_meeting(),
            recall=_recall,
            focusTopics=["pricing"],
            prepMinutes=40,
            chart="bar",
        ),
    )
    assert receipts == {
        "preferences": [],
        "inputs": ["rows", "calendar", "memory"],
        "counts": {"memory": 2},
    }


# -- memory --------------------------------------------------------------


def test_memory_is_declared_when_it_was_read():
    receipts = _receipts(
        "calendar-today", {"elements": []}, _context(agenda=_meeting(), recall=_recall)
    )
    assert receipts["inputs"] == ["calendar", "memory"]
    assert receipts["counts"] == {"memory": 2}


def test_a_quiet_calendar_does_not_declare_memory_it_never_read():
    # Quiet keeps one element, so the family never asks memory for its rows.
    receipts = _receipts(
        "calendar-today",
        {"elements": []},
        _context(agenda=_meeting(), recall=_recall, density="quiet"),
    )
    assert receipts["inputs"] == ["calendar"]


def test_a_sealed_bank_is_not_declared_and_the_reading_still_says_why():
    sealed = SimpleNamespace(is_sealed=True, recall=lambda query: [])
    server = SimpleNamespace(
        memory=sealed, calendar=None, settings=SimpleNamespace(get=lambda key: False)
    )
    context = build_context(server, defaults())

    receipts = _receipts("research-brief", _answer_payload(), context)

    assert receipts == {"preferences": [], "inputs": ["rows"]}
    card = _card("research-brief", _answer_payload())
    service.attach_cards([card], context)
    texts = [str(element.get("text") or "") for element in card["payload"]["elements"]]
    assert any("locked" in text for text in texts)


# -- the value that must never travel ------------------------------------


def test_no_receipt_ever_carries_a_preference_value():
    values = ("bar", "warm", "one-line", "pricing", "40")
    receipts = [
        _receipts(
            "outlook-digest",
            _threads(),
            _context(replyTone="warm", replyLength="one-line", chart="bar", prepMinutes=40),
        ),
        _receipts(
            "calendar-today",
            {"elements": []},
            _context(agenda=_meeting(), prepMinutes=40, focusTopics=["pricing"]),
        ),
        _receipts(
            "research-brief",
            _answer_payload(),
            _context(focusTopics=["pricing"], prepMinutes=40),
        ),
        _receipts("excel-report", {"elements": [], "tracker": _tracker()}, _context(chart="bar")),
    ]
    printed = json.dumps(receipts)
    for value in values:
        assert value not in printed
    for receipt in receipts:
        assert set(receipt["preferences"]) <= set(FIELDS)
        assert set(receipt["inputs"]) <= set(insight_reading.INPUT_NAMES)
