"""The research family: what a stored answer leaves open.

Ticket 05 asks the research card to remember the question it has already
half answered: the focus topic the stored answer is nearest to, up to three
questions worth researching before the next meeting, and what memory
remembers about the same subject. The card prints its answer as rendered
elements, so these tests build the payload the research widget really
produces rather than a flattened set of bindings.

Nothing here reads the clock or the disk: the context carries the meeting,
the preferences and the memory callable, so every assertion is a pure
function of what the dashboard already decided to show.

Wave 1 ticket 04 adds the falsification loop: a deterministic "What would
change my mind" criterion, its why provenance, and the "Check
counter-evidence" press offer, all derived from the stored answer alone.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.insight import preferences, research, service
from agentdesk.insight import press as press_module
from agentdesk.insight.types import InsightContext

NOW = 1_765_000_000.0

SUMMARY = (
    "Forward-deployed engineering pairs one engineer with a customer team for "
    "90 days; three public case studies report faster onboarding than staff "
    "augmentation."
)

MEETING = {
    "title": "Design review",
    "time": "2026-11-18T14:30:00",
    "meta": "Room 4",
    "prep": ["Bring the two shortlisted vendors"],
}


def _payload(summary: str = SUMMARY, answered: str = "2026-11-13 09:41") -> dict:
    """The research card's payload as the widget renderer leaves it."""
    return {
        "elements": [
            {"kind": "text", "label": "Latest answer", "text": summary},
            {"kind": "metric", "label": "Sources", "value": "5"},
            {"kind": "text", "label": "Answered", "text": answered},
        ],
        "status": "fresh",
        "cause": "",
        "checked_at": "",
        "source": {},
    }


def _context(
    topics=(),
    *,
    agenda=None,
    recall=None,
    memory_note="",
    density="normal",
    now=NOW,
) -> InsightContext:
    document = preferences.defaults()
    document["focusTopics"] = list(topics)
    document["insightDensity"] = density
    return InsightContext(
        preferences=document,
        now=now,
        recall=recall,
        memory_note=memory_note,
        agenda=agenda,
        agenda_note="" if agenda else "Nothing left on the calendar.",
    )


def _card(payload=None) -> dict:
    return {
        "id": "card-1",
        "pluginId": "research-brief",
        "payload": _payload() if payload is None else payload,
    }


def _of_kind(reading, kind):
    return [element for element in reading.elements if element.get("kind") == kind]


def _list_titled(reading, title):
    for element in _of_kind(reading, "list"):
        if element.get("title") == title:
            return element
    return None


def test_no_answer_yet_says_so_and_invents_nothing():
    payload = {"elements": [], "status": "attention", "cause": "no answer", "checked_at": ""}
    reading = research.derive(_card(payload), payload, _context(topics=["pricing"]))

    assert reading.elements == []
    assert reading.status == "empty"
    assert "No research answer is stored yet" in reading.note


def test_focus_line_names_the_closest_topic_by_overlap():
    reading = research.derive(
        _card(), _payload(), _context(topics=["retrieval latency", "forward-deployed engineering"])
    )

    focus = _of_kind(reading, "text")[0]
    assert focus["label"] == "Focus"
    assert focus["text"] == "Closest focus topic: forward-deployed engineering."
    assert _of_kind(reading, "status") == []


def test_focus_line_says_when_no_topic_is_named():
    reading = research.derive(_card(), _payload(), _context(topics=["supply chain risk"]))

    assert _of_kind(reading, "text")[0]["text"] == (
        "None of the focus topics are named in the stored answer."
    )


def test_an_answer_older_than_the_next_meeting_is_a_status():
    reading = research.derive(
        _card(),
        _payload(answered="2026-11-13 09:41"),
        _context(topics=["forward-deployed engineering"], agenda=MEETING),
    )

    status = _of_kind(reading, "status")
    assert len(status) == 1
    assert status[0]["tone"] == "attention"
    assert status[0]["text"] == (
        "The answer is older than Design review at 14:30: worth refreshing. "
        "Closest focus topic: forward-deployed engineering."
    )
    # The stale line carries the focus answer, so no second focus element.
    assert _of_kind(reading, "text") == []


def test_an_answer_after_the_meeting_is_not_stale():
    reading = research.derive(
        _card(), _payload(answered="2026-11-18 15:05"), _context(agenda=MEETING)
    )

    assert _of_kind(reading, "status") == []
    rows = _list_titled(reading, "Worth researching")["rows"]
    assert rows[0]["primary"] == "What should be known before Design review at 14:30?"


def test_three_suggestions_each_name_their_source():
    reading = research.derive(
        _card(),
        _payload(),
        _context(topics=["retrieval latency", "pricing"], agenda=dict(MEETING, meta="")),
    )

    rows = _list_titled(reading, "Worth researching")["rows"]
    assert len(rows) == research.MAX_SUGGESTIONS
    assert [row["meta"] for row in rows] == ["Focus list", "Focus list", "Calendar"]
    assert rows[0]["primary"] == "What is the current picture on retrieval latency?"
    assert rows[0]["secondary"] == (
        "The focus list names retrieval latency, and the stored answer does not."
    )
    assert rows[2]["primary"] == "What should be known before Design review at 14:30?"
    assert "Design review" in rows[2]["secondary"]
    for row in rows:
        assert row["primary"].endswith("?")
        assert row["secondary"]


def test_the_meeting_subject_adds_a_second_calendar_question():
    reading = research.derive(_card(), _payload(), _context(agenda=MEETING))

    rows = _list_titled(reading, "Worth researching")["rows"]
    assert [row["primary"] for row in rows] == [
        "What should be known before Design review at 14:30?",
        "What should be known about Room 4 before Design review?",
    ]


def test_no_topics_and_no_meeting_leaves_one_note_and_the_memory_reason():
    reading = research.derive(
        _card(),
        _payload(),
        _context(memory_note="Memory is not set up on this desk, so nothing was recalled."),
    )

    assert _list_titled(reading, "Worth researching") is None
    assert "nothing to base a suggestion on" in reading.note
    status = _of_kind(reading, "status")
    assert len(status) == 1
    assert status[0]["text"] == (
        "Memory is not set up on this desk, so nothing was recalled."
    )
    assert status[0]["tone"] == "attention"


def test_the_memory_reason_stays_out_when_the_card_has_another_line():
    reading = research.derive(
        _card(),
        _payload(),
        _context(topics=["pricing"], memory_note="Memory is locked, so nothing was recalled."),
    )

    assert _of_kind(reading, "status") == []
    assert all("Memory is locked" not in str(element) for element in reading.elements)


def test_two_remembered_facts_arrive_with_their_sources():
    facts = [
        {"text": "Staff augmentation lost the March review on cost.", "source": "note: March review"},
        {"text": "Two vendors offered six-month pilots instead.", "source": "email: kickoff"},
        {"text": "A third fact that should not fit in two rows.", "source": "note: extra"},
    ]
    seen = {}

    def recall(subject, limit):
        seen["subject"] = subject
        seen["limit"] = limit
        return facts

    reading = research.derive(_card(), _payload(), _context(recall=recall))

    rows = _list_titled(reading, "From memory")["rows"]
    assert len(rows) == research.MAX_RECALL
    assert rows[0]["primary"] == "Staff augmentation lost the March review on cost."
    assert rows[0]["meta"] == "note: March review"
    assert rows[0]["secondary"] == "From memory"
    assert rows[1]["meta"] == "email: kickoff"
    assert seen["subject"] == SUMMARY
    assert seen["limit"] == research.MAX_RECALL


def test_memory_that_only_repeats_the_answer_is_dropped():
    reading = research.derive(
        _card(),
        _payload(),
        _context(recall=lambda subject, limit: [{"text": SUMMARY, "source": "note: answer"}]),
    )

    assert _list_titled(reading, "From memory") is None


def test_a_long_remembered_fact_is_trimmed():
    long_fact = " ".join(["Forward deployed teams work in pairs for ninety days"] * 8)

    reading = research.derive(
        _card(),
        _payload(),
        _context(recall=lambda subject, limit: [{"text": long_fact, "source": "note: long"}]),
    )

    row = _list_titled(reading, "From memory")["rows"][0]
    assert len(row["primary"]) <= research.FACT_CHARS + 3
    assert row["primary"].endswith("...")


def test_memory_that_raises_never_takes_the_card_down():
    def recall(subject, limit):
        raise RuntimeError("the bank is sealed")

    reading = research.derive(_card(), _payload(), _context(topics=["pricing"], recall=recall))

    assert _list_titled(reading, "From memory") is None
    assert _of_kind(reading, "text")[0]["label"] == "Focus"


def test_a_covered_topic_is_never_suggested():
    reading = research.derive(
        _card(),
        _payload(),
        _context(topics=["forward-deployed engineering", "pricing"], agenda=None),
    )

    rows = _list_titled(reading, "Worth researching")["rows"]
    assert [row["primary"] for row in rows] == ["What is the current picture on pricing?"]
    assert all("forward-deployed" not in row["primary"] for row in rows)


def test_every_topic_covered_leaves_no_suggestion():
    reading = research.derive(
        _card(), _payload(), _context(topics=["staff augmentation"], agenda=None)
    )

    assert _list_titled(reading, "Worth researching") is None
    assert reading.note == ""
    assert _of_kind(reading, "text")[0]["text"] == (
        "Closest focus topic: staff augmentation."
    )


def test_the_reading_never_repeats_the_answer_it_reads():
    reading = research.derive(
        _card(),
        _payload(),
        _context(
            topics=["pricing"],
            agenda=MEETING,
            recall=lambda subject, limit: [
                {"text": "Two vendors offered pilots.", "source": "note: vendors"}
            ],
        ),
    )

    assert all(SUMMARY not in str(element) for element in reading.elements)


def test_the_reading_does_not_depend_on_the_clock():
    early = research.derive(_card(), _payload(), _context(topics=["pricing"], agenda=MEETING, now=NOW))
    late = research.derive(
        _card(), _payload(), _context(topics=["pricing"], agenda=MEETING, now=NOW + 90_000)
    )

    assert early.elements == late.elements


def test_the_seam_appends_the_reading_and_keeps_the_answer():
    card = _card()
    service.attach_cards(
        [card],
        _context(topics=["pricing"], agenda=MEETING, density="chatty"),
    )

    payload = card["payload"]
    insight = payload["insight"]
    assert payload["elements"][0]["label"] == "Latest answer"
    assert insight["status"] == "ok"
    assert insight["source"] == "local"
    assert insight["note"] == ""
    appended = payload["elements"][3:]
    assert [element["kind"] for element in appended] == ["status", "list"]
    assert appended[1]["title"] == "Worth researching"


def test_quiet_density_keeps_the_first_line_only():
    card = _card()
    service.attach_cards(
        [card],
        _context(topics=["pricing"], agenda=MEETING, density="quiet"),
    )

    appended = card["payload"]["elements"][3:]
    assert len(appended) == 1
    assert appended[0]["kind"] == "status"


def test_a_meeting_with_no_subject_is_no_more_to_go_on_than_an_empty_calendar():
    busy = {"title": "Busy", "time": "2026-11-18T09:00:00", "meta": "", "prep": []}
    reading = research.derive(_card(), _payload(), _context(agenda=busy))

    assert _list_titled(reading, "Worth researching") is None
    assert "nothing to base a suggestion on" in reading.note


def test_a_sealed_bank_says_why_it_recalled_nothing():
    reading = research.derive(
        _card(),
        _payload(),
        _context(memory_note="Memory is locked, so nothing was recalled."),
    )

    status = _of_kind(reading, "status")
    assert len(status) == 1
    assert status[0] == {
        "kind": "status",
        "text": "Memory is locked, so nothing was recalled.",
        "tone": "attention",
    }


# -- falsification and the counter-evidence press -------------------------


def test_the_falsifier_is_deterministic_and_bounded():
    one = research.derive(_card(), _payload(), _context())
    two = research.derive(_card(), _payload(), _context())

    assert one.falsify == two.falsify
    assert one.falsify.startswith("What would change my mind: ")
    assert len(one.falsify) <= 200


def test_a_comparative_claim_asks_for_a_fair_comparison():
    payload = _payload(summary="Vendor A onboarded faster than vendor B across both pilots.")

    reading = research.derive(_card(payload), payload, _context())

    assert reading.falsify == (
        "What would change my mind: a fair comparison where vendor onboarded "
        "faster does not come out ahead of the alternative."
    )


def test_a_quantitative_claim_asks_for_a_recount():
    payload = _payload(summary="The pilot covered 90 days with 5 sources.")

    reading = research.derive(_card(payload), payload, _context())

    assert reading.falsify == (
        "What would change my mind: a recount where the numbers the answer "
        "gives (90, 5) come out materially different."
    )


def test_a_plain_claim_still_names_what_would_overturn_it():
    payload = _payload(
        summary="Deploying with a paired engineer keeps customers close to the team."
    )

    reading = research.derive(_card(payload), payload, _context())

    assert reading.falsify == (
        "What would change my mind: credible evidence about deploying paired "
        "engineer that points the other way."
    )


def test_an_empty_reading_carries_no_falsify_why_or_press():
    payload = {"elements": [], "status": "attention", "cause": "no answer", "checked_at": ""}

    reading = research.derive(_card(payload), payload, _context(topics=["pricing"]))

    assert reading.falsify == ""
    assert reading.why == ()
    assert reading.press is None


def test_the_why_entry_names_the_claim_rule_and_cited_fact_ids():
    def recall(subject, limit):
        return [
            {
                "text": "Staff augmentation lost the March review on cost.",
                "source": "note: March review",
                "id": 7,
            },
            {
                "text": "Two vendors offered six-month pilots instead.",
                "source": "email: kickoff",
                "id": 11,
            },
        ]

    reading = research.derive(_card(), _payload(), _context(recall=recall))

    entry = reading.why[0]
    assert entry["claim"] == SUMMARY
    assert entry["rule"] == "The falsifier targets a comparative claim in the stored answer"
    assert entry["facts"] == [
        {"id": 7, "source": "note: March review"},
        {"id": 11, "source": "email: kickoff"},
    ]


def test_a_reading_without_memory_cites_no_facts_but_still_names_its_rule():
    reading = research.derive(_card(), _payload(), _context())

    assert set(reading.why[0]) == {"claim", "rule"}


def test_the_press_offer_is_the_counter_evidence_action():
    reading = research.derive(_card(), _payload(), _context())

    offer = reading.press
    assert offer["kind"] == "check-counter"
    assert offer["label"] == "Check counter-evidence"
    assert offer["route"] == "/api/insight/draft"
    assert len(offer["text"]) <= press_module.MAX_FINDING
    assert reading.falsify in offer["text"]


def test_a_long_answer_leaves_room_for_the_criterion_in_the_press_text():
    payload = _payload(summary=" ".join(["Faster ramps beat cheaper bodies."] * 40))

    reading = research.derive(_card(payload), payload, _context())

    assert len(reading.press["text"]) <= press_module.MAX_FINDING
    assert reading.falsify in reading.press["text"]


def test_the_falsify_block_sits_between_receipts_and_note():
    card = _card()
    service.attach_cards(
        [card],
        _context(memory_note="Memory is not set up on this desk, so nothing was recalled."),
    )

    insight = card["payload"]["insight"]
    assert [block["kind"] for block in insight["blocks"]] == ["receipts", "falsify", "note"]
    assert insight["blocks"][1]["text"].startswith("What would change my mind: ")
    # Elements are untouched: the criterion is a block, never an element.
    assert [element["kind"] for element in card["payload"]["elements"][3:]] == ["status"]
