"""The reflect port's pure half (ticket #93): the donor's src/reflect.ts
acceptance filters, src/bank.ts gatherFacts and scopeKey, and the
src/reflector.ts prompt, message shape and tolerant reply parse.

These tests pin the port before the endpoint-backed half exists: the
regexes and thresholds verbatim, the citation rules (subset of the
gathered facts, two at least, one only in a single-entity scope), the
near-duplicate drop (normalized equal or token Jaccard at least 0.55,
keeping the higher confidence; the embedding cosine joins with #95),
the five-observation cap, the gather cutoff at half the best score
with the since-inclusive until-exclusive window, and the scope key's
composition. The embedding-cosine leg is deliberately absent: it is
commented in reflect.py and lands with ticket #95.
"""

import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.llm import LlmUnavailable
from agentdesk.memory.core import Fact
from agentdesk.memory.reflect import (
    MAX_OBSERVATIONS,
    EndpointReflector,
    ObservationDraft,
    ReflectEmpty,
    ReflectFailed,
    REFLECT_SYSTEM_PROMPT,
    ReflectorUnavailable,
    accept_observations,
    gather_facts,
    is_low_value_observation,
    parse_reflection_payload,
    parse_scope_date,
    reflect_user_message,
    scope_key,
)


def _fact(fact_id: int, text: str, created_ts: float = 1000.0,
          occurrence_ts: float | None = None) -> Fact:
    return Fact(
        id=fact_id, text=text, source="page", created_ts=created_ts,
        occurrence_ts=occurrence_ts,
    )


def _draft(text: str, confidence: float = 0.9,
           fact_ids=(1, 2)) -> ObservationDraft:
    return ObservationDraft(text=text, confidence=confidence, fact_ids=fact_ids)


# -- the low-value filter (src/reflect.ts SPECULATIVE and META verbatim) -----


@pytest.mark.parametrize(
    "text",
    [
        "Maya suggests a weekly review",
        "This indicates the rollout is late",
        "It seems the budget is settled",
        "Acme might ship in December",
        "The invoice may be paid",
        "Possibly the contract renewed",
        "She will probably join",
        "That is likely the plan",
        "Perhaps the review moved",
        "The team could pivot",
        "Her reply appeared to confirm it",
    ],
)
def test_speculative_words_reject_a_draft(text):
    assert is_low_value_observation(text)


@pytest.mark.parametrize(
    "text",
    [
        "Maya is separate from Acme",
        "The note was mentioned in the context of the review",
        "That came up in the context of hiring",
        "The budget is unrelated to the party",
        "Hiring is distinct from payroll",
        "Pune as opposed to Mumbai",
        "The invoice is not related to the refund",
    ],
)
def test_meta_phrases_reject_a_draft(text):
    assert is_low_value_observation(text)


def test_a_direct_statement_is_not_low_value():
    assert not is_low_value_observation("Maya leads the Acme review")


def test_an_assistant_knowledge_gap_is_not_an_observation():
    # The gap detector rides the accept path beside the low-value
    # filter (the donor's isAssistantKnowledgeGap check).
    kept = accept_observations(
        [
            _draft("I do not have any information about that", fact_ids=(1, 2)),
            _draft("Maya leads the review", fact_ids=(1, 2)),
        ],
        {1, 2},
    )
    assert [draft.text for draft in kept] == ["Maya leads the review"]


# -- accept_observations: the donor's filters in order -----------------------


def test_a_draft_with_no_text_is_dropped():
    # Nothing surviving is the donor's refusal, not an empty list.
    with pytest.raises(ReflectFailed):
        accept_observations([_draft("   ")], {1, 2})


def test_non_finite_or_out_of_range_confidence_is_dropped():
    bad = [
        _draft("Maya leads the review", confidence=float("nan")),
        _draft("Maya leads the review", confidence=-0.1),
        _draft("Maya leads the review", confidence=1.1),
    ]
    with pytest.raises(ReflectFailed):
        accept_observations(bad, {1, 2})
    assert accept_observations(
        [_draft("Maya leads the review", confidence=0.0)], {1, 2}
    ) == [_draft("Maya leads the review", confidence=0.0)]
    assert accept_observations(
        [_draft("Maya leads the review", confidence=1.0)], {1, 2}
    ) == [_draft("Maya leads the review", confidence=1.0)]


def test_citations_outside_the_gathered_facts_reject_the_draft():
    with pytest.raises(ReflectFailed):
        accept_observations([_draft("Maya leads the review", fact_ids=(1, 9))],
                            {1, 2})


def test_zero_citations_reject_the_draft():
    with pytest.raises(ReflectFailed):
        accept_observations([_draft("Maya leads the review", fact_ids=())],
                            {1, 2})


def test_repeated_citations_collapse_before_the_count_check():
    kept = accept_observations([_draft("Maya leads the review", fact_ids=(1, 1, 2))],
                               {1, 2})
    assert kept == [_draft("Maya leads the review", fact_ids=(1, 2))]


def test_a_single_citation_needs_two_facts_outside_a_single_entity_scope():
    with pytest.raises(ReflectFailed):
        accept_observations([_draft("Maya leads the review", fact_ids=(1,))],
                            {1, 2})


def test_a_single_citation_passes_in_a_single_entity_scope():
    kept = accept_observations([_draft("Maya leads the review", fact_ids=(1,))],
                               {1, 2}, single_entity=True)
    assert kept == [_draft("Maya leads the review", fact_ids=(1,))]


def test_two_citations_are_not_required_when_only_one_fact_was_gathered():
    kept = accept_observations([_draft("Maya leads the review", fact_ids=(7,))], {7})
    assert kept == [_draft("Maya leads the review", fact_ids=(7,))]


def test_normalized_equal_drafts_collapse_keeping_the_higher_confidence():
    kept = accept_observations(
        [
            _draft("Maya left Acme", confidence=0.6),
            _draft("  maya   left acme ", confidence=0.95),
        ],
        {1, 2},
    )
    # The kept text is the trimmed original (the donor's), not the
    # normalized form; the store normalizes again for the upsert match.
    assert kept == [_draft("maya   left acme", confidence=0.95)]


def _tokens(prefix: str, count: int, start: int = 0) -> list[str]:
    return [f"{prefix}{start + index}" for index in range(count)]


def _jaccard_texts(shared: int, left_only: int, right_only: int) -> tuple[str, str]:
    left = _tokens("s", shared) + _tokens("l", left_only)
    right = _tokens("s", shared) + _tokens("r", right_only)
    return " ".join(left), " ".join(right)


def test_token_jaccard_at_the_boundary_is_a_duplicate():
    # 11 shared tokens over a union of 20 is exactly 0.55.
    left, right = _jaccard_texts(shared=11, left_only=4, right_only=5)
    assert len(left.split()) == 15 and len(right.split()) == 16
    kept = accept_observations(
        [_draft(left, confidence=0.5), _draft(right, confidence=0.9)], {1, 2}
    )
    assert [draft.text for draft in kept] == [right]


def test_token_jaccard_below_the_boundary_keeps_both():
    # 11 shared over a union of 21 is about 0.52.
    left, right = _jaccard_texts(shared=11, left_only=5, right_only=5)
    kept = accept_observations(
        [_draft(left, confidence=0.5), _draft(right, confidence=0.9)], {1, 2}
    )
    # Survivors come back highest confidence first.
    assert [draft.text for draft in kept] == [right, left]


def test_the_cap_keeps_the_five_highest_confidence_observations():
    drafts = [
        _draft(
            f"Fact {index} concerns topic{index} and thing{index} directly",
            confidence=index / 10,
        )
        for index in range(1, 8)
    ]
    kept = accept_observations(drafts, {1, 2})
    assert len(kept) == MAX_OBSERVATIONS == 5
    assert [draft.confidence for draft in kept] == [0.7, 0.6, 0.5, 0.4, 0.3]


def test_a_custom_cap_applies():
    drafts = [
        _draft(f"Fact {index} concerns topic{index} and thing{index} directly",
               confidence=0.5)
        for index in range(4)
    ]
    assert len(accept_observations(drafts, {1, 2}, max_observations=2)) == 2


def test_nothing_surviving_raises_and_writes_nothing():
    with pytest.raises(ReflectFailed) as excinfo:
        accept_observations([_draft("This might be nothing")], {1, 2})
    assert "Nothing was written" in str(excinfo.value)


# -- gathering (src/bank.ts gatherFacts) -------------------------------------


def test_the_query_path_keeps_scores_above_half_the_best():
    recalled = [
        (1.0, _fact(1, "Acme ships widgets")),
        (0.6, _fact(2, "Acme raised a round")),
        (0.4, _fact(3, "Acme hired Maya")),
        (0.0, _fact(4, "Unrelated")),
    ]
    gathered = gather_facts("acme", recalled, [])
    assert [fact.id for fact in gathered] == [1, 2]


def test_the_query_path_keeps_a_score_exactly_at_the_cutoff():
    recalled = [(1.0, _fact(1, "Acme ships widgets")), (0.5, _fact(2, "Acme hired"))]
    assert [fact.id for fact in gather_facts("acme", recalled, [])] == [1, 2]


def test_the_query_path_considers_at_most_forty_recalled_facts():
    recalled = [(1.0, _fact(41, "The best fact stands alone"))] + [
        (0.5, _fact(index, f"Filler fact number {index}")) for index in range(1, 41)
    ]
    gathered = gather_facts("query", recalled, [])
    assert [fact.id for fact in gathered] == [41] + list(range(1, 40))


def test_a_fruitless_query_path_does_not_fall_back_to_recency():
    # The donor gathers through the recall path only when a query is
    # given; nothing scoring above zero is an empty gather, never a
    # quiet switch to the recency path.
    with pytest.raises(ReflectEmpty):
        gather_facts("query", [(0.0, _fact(1, "Silent"))], [_fact(2, "Stored")])


def test_the_no_query_path_takes_the_forty_most_recent_by_creation():
    facts = [_fact(index, f"Fact {index}", created_ts=float(index))
             for index in range(1, 46)]
    gathered = gather_facts("", None, facts)
    assert [fact.id for fact in gathered] == list(range(45, 5, -1))


def test_the_window_filters_on_occurrence_else_creation_time():
    gathered = gather_facts(
        "",
        None,
        [
            _fact(1, "Dated event", created_ts=50.0, occurrence_ts=200.0),
            _fact(2, "Plain fact", created_ts=150.0),
            _fact(3, "Too early", created_ts=99.0),
            _fact(4, "At until", created_ts=48.0, occurrence_ts=300.0),
        ],
        since=100.0,
        until=300.0,
    )
    # The recency path's order stands: newest creation first.
    assert [fact.id for fact in gathered] == [2, 1]


def test_since_is_inclusive_and_until_exclusive_on_creation_time():
    gathered = gather_facts(
        "", None,
        [_fact(1, "Edge in", created_ts=100.0), _fact(2, "Edge out", created_ts=200.0)],
        since=100.0, until=200.0,
    )
    assert [fact.id for fact in gathered] == [1]


def test_an_empty_gather_raises_before_any_model_call():
    with pytest.raises(ReflectEmpty) as excinfo:
        gather_facts("", None, [])
    assert "Nothing was written" in str(excinfo.value)
    with pytest.raises(ReflectEmpty):
        gather_facts("nomatch", [], [])


# -- the scope key (src/reflect.ts scopeKey) ---------------------------------


def test_the_scope_key_joins_entity_topic_query_since_until_lowercased():
    assert scope_key(entity="Maya", topic="Work") == "maya\nwork\n\n\n"
    assert scope_key(query="acme review") == "\n\nacme review\n\n"


def test_the_scope_key_trims_and_lowers_each_part():
    assert scope_key(entity="  Maya  ", topic="Work Stuff") == "maya\nwork stuff\n\n\n"


def test_the_scope_key_renders_window_bounds():
    assert scope_key(since=1.5, until=2.0) == "\n\n\n1.5\n2.0"


def test_equal_scopes_match_regardless_of_part_order():
    assert scope_key(entity="Maya", topic="Work") == scope_key(topic="Work", entity="maya")


# -- the donor prompt and user message (src/reflector.ts, verbatim) ----------


def test_the_system_prompt_is_the_donor_s_verbatim():
    assert REFLECT_SYSTEM_PROMPT == (
        "You write durable observations about the topic from the facts listed.\n"
        'Reply with JSON only:\n'
        '{"observations":[{"text":"...","confidence":0.0,"sourceFactIds":["..."]}]}\n'
        "Quality:\n"
        "- One observation per distinct pattern. Do not restate one pattern in different words.\n"
        "- Cite at least two facts. A single fact is not an observation.\n"
        "- State the pattern directly. No hedging and no words such as suggesting, indicating, seems, might, or possibly.\n"
        "- Do not restate a single fact in new words.\n"
        '- Do not write meta comments such as "X is separate from Y" or "mentioned in the context of".\n'
        "- Use only facts about the topic. Ignore the rest.\n"
        "- confidence is from 0 to 1. At most 5 observations.\n"
        "- Do not say the assistant lacks knowledge or just did something in this chat."
    )


def test_the_user_message_lists_id_kind_created_text_lines():
    facts = [_fact(3, "Maya left Acme", created_ts=1700000000.0)]
    assert reflect_user_message("", facts) == (
        "Facts:\n3 | world | 2023-11-14T22:13:20Z | Maya left Acme"
    )


def test_a_topic_rides_ahead_of_the_fact_lines():
    message = reflect_user_message("Acme", [_fact(3, "Maya left Acme")])
    assert message.startswith("Topic: Acme\n\nFacts:\n")


def test_a_blank_topic_sends_no_topic_line():
    assert not reflect_user_message("   ", []).startswith("Topic:")


# -- the tolerant reply parse (src/reflector.ts readObservations) ------------


def test_a_clean_payload_parses_to_drafts():
    reply = (
        'Sure! {"observations": ['
        '{"text": "Maya leads the review", "confidence": 0.9,'
        ' "sourceFactIds": [1, 2]}]}'
    )
    assert parse_reflection_payload(reply) == [
        _draft("Maya leads the review", confidence=0.9, fact_ids=(1, 2))
    ]


def test_think_blocks_are_stripped_before_the_parse():
    reply = (
        "<think>reasoning about the facts</think>"
        '{"observations": [{"text": "Acme ships", "confidence": 0.5,'
        ' "sourceFactIds": ["1", 2]}]}'
    )
    assert parse_reflection_payload(reply) == [
        _draft("Acme ships", confidence=0.5, fact_ids=(1, 2))
    ]


def test_digit_string_fact_ids_parse_as_ids():
    reply = ('{"observations": [{"text": "Acme ships", "confidence": 0.5,'
             ' "sourceFactIds": ["1", "2"]}]}')
    assert parse_reflection_payload(reply)[0].fact_ids == (1, 2)


@pytest.mark.parametrize(
    "reply",
    [
        "no braces at all",
        "not json { at all }",
        '{"facts": []}',
        '{"observations": "nope"}',
    ],
)
def test_unusable_payloads_raise_reflect_failed(reply):
    with pytest.raises(ReflectFailed) as excinfo:
        parse_reflection_payload(reply)
    assert "Nothing was written" in str(excinfo.value)


def test_a_non_string_reply_raises_reflect_failed():
    with pytest.raises(ReflectFailed):
        parse_reflection_payload(None)


def test_a_malformed_draft_reads_as_empty():
    reply = ('{"observations": [42,'
             ' {"text": 5, "confidence": "high", "sourceFactIds": "all"}]}')
    drafts = parse_reflection_payload(reply)
    assert len(drafts) == 2
    for draft in drafts:
        assert draft.text == ""
        assert math.isnan(draft.confidence)
        assert draft.fact_ids == ()


# -- the endpoint-backed reflector (src/reflector.ts, adapted to the seam) ---


class ScriptedLlm:
    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.prompts: list[str] = []
        self.reply = reply
        self.error = error

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


def test_the_endpoint_reflector_sends_one_prompt_and_parses_the_reply():
    llm = ScriptedLlm(
        reply='{"observations": [{"text": "Maya leads the review",'
              ' "confidence": 0.9, "sourceFactIds": [1, 2]}]}'
    )
    reflector = EndpointReflector(llm)
    drafts = reflector.reflect(
        "Work", [_fact(1, "Maya runs the review"), _fact(2, "The review is weekly")]
    )
    assert drafts == [_draft("Maya leads the review", confidence=0.9, fact_ids=(1, 2))]
    (prompt,) = llm.prompts
    assert prompt.startswith(REFLECT_SYSTEM_PROMPT + "\n\n")
    assert "Topic: Work\n\nFacts:\n" in prompt
    assert reflector.last_request_bytes == len(prompt.encode("utf-8"))


def test_an_unreachable_endpoint_raises_reflector_unavailable():
    cause = LlmUnavailable("The endpoint did not answer.")
    with pytest.raises(ReflectorUnavailable) as excinfo:
        EndpointReflector(ScriptedLlm(error=cause)).reflect("", [])
    assert "The endpoint did not answer." in str(excinfo.value)


def test_any_other_endpoint_failure_raises_reflector_unavailable():
    with pytest.raises(ReflectorUnavailable):
        EndpointReflector(ScriptedLlm(error=RuntimeError("boom"))).reflect("", [])


# -- the scope window's date parsing (the reflect form's since/until) --------


def test_a_bare_date_parses_as_utc_midnight():
    assert parse_scope_date("2026-11-01") == datetime(
        2026, 11, 1, tzinfo=UTC
    ).timestamp()


def test_a_full_timestamp_parses_with_its_offset():
    assert parse_scope_date("2026-11-01T10:30:00Z") == datetime(
        2026, 11, 1, 10, 30, tzinfo=UTC
    ).timestamp()


def test_blank_and_missing_dates_parse_as_none():
    assert parse_scope_date(None) is None
    assert parse_scope_date("") is None
    assert parse_scope_date("   ") is None


def test_an_unreadable_date_is_a_value_error():
    with pytest.raises(ValueError):
        parse_scope_date("sometime soon")
