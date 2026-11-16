"""The extractor port's unit tests: parse, validate, filter, gate.

The donor's rules are pinned here one by one: the tolerant reply parse
(think blocks stripped, first brace to last brace, a facts array
required), the per-fact validation bounds, the retain post-filters
(knowledge gaps dropped, five at most) and the occurrence gate (the
source text itself must name an occurrence). Everything is a pure
function or a fake llm callable; nothing here touches the network or a
database.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.llm import LlmUnavailable
from agentdesk.memory.extract import (
    ENTITY_TYPES,
    EXTRACTION_SYSTEM_PROMPT,
    EndpointExtractor,
    ExtractionFailed,
    ExtractorUnavailable,
    MAX_FACT_CHARS,
    MAX_RETAINED_FACTS,
    CandidateFact,
    extraction_user_message,
    facts_to_retain,
    occurrence_from_source,
    parse_model_payload,
    source_names_occurrence,
    strip_think_blocks,
)
from agentdesk.memory.knowledge_gap import is_assistant_knowledge_gap


# -- the donor prompt rides verbatim ---------------------------------------


def test_the_system_prompt_is_the_donor_text_verbatim():
    # Pinned head and tail of the donor's EXTRACTION_SYSTEM_PROMPT, so a
    # careless rewording of the port cannot slip through review.
    assert EXTRACTION_SYSTEM_PROMPT.startswith(
        "You turn a conversation snippet into a few durable memory facts "
        "for a personal agent."
    )
    assert '"facts": [' in EXTRACTION_SYSTEM_PROMPT
    assert 'kind "world" is about other people' in EXTRACTION_SYSTEM_PROMPT
    assert 'kind "experience" is only for something the agent itself did' \
        in EXTRACTION_SYSTEM_PROMPT
    assert 'If nothing is worth keeping, return {"facts":[]}.' \
        in EXTRACTION_SYSTEM_PROMPT


def test_the_user_message_shape_matches_the_donor():
    message = extraction_user_message(
        "we met Tuesday",
        speaker="Kanit",
        context="assistant thread",
        mentioned_at="2026-03-10T09:00:00+00:00",
    )
    lines = message.split("\n")
    assert lines[0] == (
        "mentioned_at is when this text was recorded, not when an event "
        "happened. Do not copy it into occurrenceTime."
    )
    assert lines[1] == "mentioned_at: 2026-03-10T09:00:00+00:00"
    assert lines[2] == "speaker: Kanit"
    assert lines[3] == "context: assistant thread"
    assert lines[4] == "content:"
    assert lines[5] == "we met Tuesday"


def test_the_user_message_falls_back_to_unknown_placeholders():
    message = extraction_user_message("hello", speaker="", context="", mentioned_at=None)
    assert "mentioned_at: unknown" in message
    assert "speaker: unknown" in message
    assert "context: none" in message


# -- the tolerant reply parse ----------------------------------------------


def test_strip_think_blocks_removes_reasoning_blocks_case_insensitively():
    text = "<think>pondering 1 + 1</think>{\"facts\": []}"
    assert strip_think_blocks(text) == '{"facts": []}'
    text = "<THINK>loud</THINK>\n<think>more</think>payload"
    assert strip_think_blocks(text) == "payload"


def test_strip_think_blocks_keeps_text_without_blocks():
    assert strip_think_blocks("  plain  ") == "plain"


def _payload(payload_text: str):
    return parse_model_payload(payload_text)


def test_parse_reads_a_clean_json_object():
    assert _payload('{"facts": [{"text": "a"}]}') == [{"text": "a"}]


def test_parse_reads_fenced_json_with_prose_around_it():
    fenced = "Here you go:\n```json\n{\"facts\": [{\"text\": \"a\"}]}\n```\nDone."
    assert _payload(fenced) == [{"text": "a"}]


def test_parse_reads_json_after_think_blocks():
    noisy = (
        "<think>The user talks about Maya.</think>"
        'Leading words {"facts": [{"text": "a"}]} trailing words'
    )
    assert _payload(noisy) == [{"text": "a"}]


def test_parse_slices_from_the_first_brace_to_the_last():
    nested = 'prefix {"facts": [{"text": "a {b} c"}]} suffix'
    assert _payload(nested) == [{"text": "a {b} c"}]


@pytest.mark.parametrize(
    "payload_text",
    [
        "no braces anywhere",
        "not json { broken",
        '{"answers": []}',
        '{"facts": "three"}',
        "",
        "   ",
    ],
)
def test_parse_refuses_unusable_payloads_with_a_plain_cause(payload_text):
    with pytest.raises(ExtractionFailed) as raised:
        _payload(payload_text)
    assert "Nothing was written." in str(raised.value)


def test_parse_refuses_a_non_string_payload_shape():
    with pytest.raises(ExtractionFailed):
        _payload(None)  # type: ignore[arg-type]


# -- per-fact validation ---------------------------------------------------


def _normalize(value):
    from agentdesk.memory.extract import normalize_extracted_facts

    return normalize_extracted_facts(value)


def test_normalize_reads_a_full_fact():
    candidates = _normalize(
        [
            {
                "text": "  Maya lives in Pune  ",
                "kind": "world",
                "occurrenceTime": "2026-03-10T09:00:00Z",
                "entities": [{"name": " Maya ", "type": "person"}],
            }
        ]
    )
    (candidate,) = candidates
    assert candidate.text == "Maya lives in Pune"
    assert candidate.kind == "world"
    assert candidate.occurrence_ts == pytest.approx(
        datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc).timestamp()
    )
    assert candidate.entities == (("Maya", "person"),)


def test_normalize_defaults_entities_to_empty_and_occurrence_to_none():
    (candidate,) = _normalize([{"text": "a", "kind": "experience"}])
    assert candidate.occurrence_ts is None
    assert candidate.entities == ()


def test_normalize_accepts_a_null_occurrence_and_a_date_only_day():
    (candidate,) = _normalize(
        [{"text": "a", "kind": "world", "occurrenceTime": "2026-03-10"}]
    )
    assert candidate.occurrence_ts == pytest.approx(
        datetime(2026, 3, 10, tzinfo=timezone.utc).timestamp()
    )
    (candidate,) = _normalize(
        [{"text": "a", "kind": "world", "occurrenceTime": None}]
    )
    assert candidate.occurrence_ts is None


@pytest.mark.parametrize(
    "fact",
    [
        {},
        "a string",
        {"kind": "world", "text": "   "},
        {"kind": "world"},
        {"kind": "world", "text": "x" * (MAX_FACT_CHARS + 1)},
        {"kind": "rumor", "text": "a"},
        {"kind": "world", "text": "a", "occurrenceTime": "not a date"},
        {"kind": "world", "text": "a", "occurrenceTime": 1700000000},
        {"kind": "world", "text": "a", "entities": {}},
        {"kind": "world", "text": "a", "entities": [{"type": "person"}]},
        {"kind": "world", "text": "a", "entities": [{"name": "  ", "type": "person"}]},
        {"kind": "world", "text": "a", "entities": [{"name": "Maya", "type": "robot"}]},
    ],
)
def test_normalize_refuses_facts_that_break_the_donor_bounds(fact):
    with pytest.raises(ExtractionFailed) as raised:
        _normalize([fact])
    assert "Nothing was written." in str(raised.value)


def test_a_fact_at_the_exact_length_bound_is_kept():
    (candidate,) = _normalize([{"kind": "world", "text": "x" * MAX_FACT_CHARS}])
    assert len(candidate.text) == MAX_FACT_CHARS


def test_the_vocabulary_constants_match_the_donor():
    assert ENTITY_TYPES == ("person", "org", "place", "product", "concept", "other")


# -- the retain post-filters ------------------------------------------------


def test_knowledge_gap_texts_are_dropped_and_other_negatives_stay():
    # The donor retain.test.ts disclaimer list, verbatim.
    gaps = [
        "The assistant does not have specific information about a person named Pepper.",
        "I don't know who Pepper is.",
        "I do not have any information about Pepper.",
        "I don't have information about that.",
        "I'm not sure who that is.",
        "The model does not have information about Pepper.",
        "The assistant doesn't know who that is.",
        "I have no information about a person named Pepper.",
        "I am not sure who Pepper is.",
        "I don\u2019t know who Pepper is.",
        "I'm not familiar with Pepper.",
        "The model has no knowledge of Pepper.",
        "I do not know who that is.",
        "  THE ASSISTANT DOES NOT HAVE SPECIFIC INFORMATION ABOUT A PERSON"
        " NAMED PEPPER.  ",
    ]
    for gap in gaps:
        assert is_assistant_knowledge_gap(gap) is True
        assert facts_to_retain([CandidateFact(text=gap, kind="world")]) == []
    for kept_text in (
        "Maya does not have a preference for morning meetings.",
        "Maya visited Wikipedia yesterday.",
        "Maya keeps harbor note 1.",
    ):
        kept = CandidateFact(text=kept_text, kind="world")
        assert facts_to_retain([kept]) == [kept]


def test_retain_caps_candidates_at_five():
    candidates = [
        CandidateFact(text=f"fact number {n}", kind="world")
        for n in range(MAX_RETAINED_FACTS + 2)
    ]
    kept = facts_to_retain(candidates)
    assert len(kept) == MAX_RETAINED_FACTS
    assert [c.text for c in kept] == [f"fact number {n}" for n in range(5)]


# -- the occurrence gate ----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "we met Tuesday",
        "the standup was on Nov 10 at 9am",
        "she arrived 10 November",
        "the review is on 2026-03-10",
        "we shipped it 3/10",
        "we shipped it 10-3-2026",
        "it happened on the 3rd",
        "the demo was yesterday",
        "I locked the hall tonight",
        "we talked two weeks ago",
        "the launch is next Monday",
        "she visited this morning",
    ],
)
def test_the_source_gate_accepts_every_donor_occurrence_wording(text):
    assert source_names_occurrence(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "9am works for me",
        "Maya prefers morning meetings",
        "the revenue is 220",
        "the server runs on port 8080",
        "meet at 10:30",
    ],
)
def test_the_source_gate_refuses_clock_times_and_preferences(text):
    assert source_names_occurrence(text) is False


def test_the_gate_keeps_an_extracted_occurrence_only_when_the_source_names_one():
    when = 1700000000.0
    assert occurrence_from_source("we met Tuesday", when) == when
    assert occurrence_from_source("9am works for me", when) is None
    assert occurrence_from_source("we met Tuesday", None) is None


# -- the endpoint extractor over the llm seam -------------------------------


class FakeLlm:
    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.prompts: list[str] = []
        self.reply = reply
        self.error = error

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


def _three_facts_payload() -> str:
    import json

    return json.dumps(
        {
            "facts": [
                {"text": "Maya lives in Pune", "kind": "world",
                 "entities": [{"name": "Maya", "type": "person"}]},
                {"text": "Acme ships widgets", "kind": "world",
                 "entities": [{"name": "Acme", "type": "org"}]},
                {"text": "I drafted the memo", "kind": "experience", "entities": []},
            ]
        }
    )


def test_the_endpoint_extractor_sends_the_donor_prompt_and_returns_candidates():
    llm = FakeLlm(reply=_three_facts_payload())
    extractor = EndpointExtractor(llm)
    candidates = extractor.extract(
        "Maya lives in Pune. Acme ships widgets. I drafted the memo.",
        speaker="Kanit",
        context="assistant thread",
        mentioned_at="2026-03-10T09:00:00+00:00",
    )
    assert [c.text for c in candidates] == [
        "Maya lives in Pune",
        "Acme ships widgets",
        "I drafted the memo",
    ]
    assert [c.kind for c in candidates] == ["world", "world", "experience"]
    assert candidates[0].entities == (("Maya", "person"),)
    (prompt,) = llm.prompts
    assert prompt.startswith(EXTRACTION_SYSTEM_PROMPT)
    assert "mentioned_at: 2026-03-10T09:00:00+00:00" in prompt
    assert "speaker: Kanit" in prompt
    assert "context: assistant thread" in prompt
    assert "content:\nMaya lives in Pune." in prompt
    # The audit seam: the bytes of the prompt that actually went out.
    assert extractor.last_request_bytes == len(prompt.encode("utf-8"))


def test_the_endpoint_extractor_maps_llm_unavailable_to_extractor_unavailable():
    cause = "could not resolve the host llm.example.com: check the base URL"
    extractor = EndpointExtractor(FakeLlm(error=LlmUnavailable(cause)))
    with pytest.raises(ExtractorUnavailable) as raised:
        extractor.extract("hello")
    assert cause in str(raised.value)


def test_the_endpoint_extractor_maps_any_other_transport_error_to_unavailable():
    extractor = EndpointExtractor(FakeLlm(error=OSError("connection reset")))
    with pytest.raises(ExtractorUnavailable):
        extractor.extract("hello")


def test_the_endpoint_extractor_maps_a_junk_reply_to_extraction_failed():
    extractor = EndpointExtractor(FakeLlm(reply="I could not produce JSON, sorry."))
    with pytest.raises(ExtractionFailed):
        extractor.extract("hello")
