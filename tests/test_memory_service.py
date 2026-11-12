"""Memory recall arithmetic: tokenize, rank, and the bounded block.

Pure functions, no I/O, like the snooze arithmetic: the ranking must be
deterministic (same store, same query, same order, every time) and the
prompt block must stay bounded (at most 5 facts, 500 characters, whole
facts only). The scoring ports the teammate's keyword-overlap fraction;
the deliberate divergences are documented on the module.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.memory.core import Fact
from agentdesk.memory.service import (
    MAX_CHARS,
    MAX_FACTS,
    build_facts_block,
    rank,
    score,
    tokenize,
)


def _fact(fact_id: int, text: str, created_ts: float = 100.0) -> Fact:
    return Fact(id=fact_id, text=text, source="page", created_ts=created_ts)


# -- tokenize ------------------------------------------------------------


def test_tokenize_lowercases_splits_and_drops_short_tokens():
    assert tokenize("The Revenue Total is 220!") == ["the", "revenue", "total", "220"]


def test_tokenize_drops_tokens_of_two_characters_or_fewer():
    assert tokenize("I like AB") == ["like"]


def test_tokenize_of_silence_is_empty():
    assert tokenize("") == []
    assert tokenize("... !!! ___") == []


# -- score ---------------------------------------------------------------


def test_score_is_the_fraction_of_query_tokens_found_in_the_fact():
    query = tokenize("revenue total")
    assert score(query, tokenize("the revenue total was 220")) == 1.0
    assert score(query, tokenize("revenue only")) == 0.5
    assert score(query, tokenize("nothing matches here")) == 0.0


def test_score_of_an_empty_side_is_zero():
    assert score([], tokenize("revenue")) == 0.0
    assert score(tokenize("revenue"), []) == 0.0


# -- rank ----------------------------------------------------------------


def test_rank_orders_by_overlap_most_relevant_first():
    facts = [
        _fact(1, "the revenue total lives in channel-weekly.xlsx"),
        _fact(2, "the revenue total for October is 220"),
    ]
    ranked = rank("revenue total october", facts)
    assert [fact.id for _s, fact in ranked] == [2, 1]


def test_rank_excludes_facts_with_zero_overlap():
    facts = [
        _fact(1, "revenue is 220"),
        _fact(2, "the meeting room is booked"),
    ]
    ranked = rank("revenue", facts)
    assert [fact.id for _s, fact in ranked] == [1]


def test_rank_is_deterministic_across_calls():
    facts = [
        _fact(1, "revenue lives in the sales workbook"),
        _fact(2, "revenue is checked every monday"),
    ]
    first = rank("revenue workbook", facts)
    for _ in range(5):
        assert rank("revenue workbook", facts) == first


def test_rank_breaks_ties_by_created_timestamp_then_id():
    # Same overlap for both facts: the older one wins; identical
    # timestamps fall back to the smaller id.
    facts = [
        _fact(2, "revenue monthly note", created_ts=200.0),
        _fact(1, "revenue weekly note", created_ts=100.0),
        _fact(3, "revenue daily note", created_ts=100.0),
    ]
    ranked = rank("revenue note", facts)
    assert [fact.id for _s, fact in ranked] == [1, 3, 2]


def test_rank_of_a_query_without_tokens_is_empty():
    facts = [_fact(1, "revenue is 220")]
    assert rank("ab", facts) == []
    assert rank("", facts) == []


def test_rank_scores_carry_the_overlap_fraction():
    facts = [_fact(1, "revenue is 220")]
    ranked = rank("revenue workbook", facts)
    assert ranked[0][0] == 0.5


# -- the bounded block ---------------------------------------------------


def test_block_of_no_recall_is_empty():
    assert build_facts_block([]) == ""


def test_block_names_itself_as_derived_and_lines_each_fact():
    ranked = [(0.5, _fact(1, "revenue is 220"))]
    block = build_facts_block(ranked)
    assert "Known facts about the user" in block
    assert "- revenue is 220" in block


def test_block_caps_at_five_facts():
    ranked = [(0.5, _fact(i, f"fact number {i} is here")) for i in range(1, 9)]
    block = build_facts_block(ranked)
    lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(lines) == MAX_FACTS
    # The kept facts are the top-ranked ones, in rank order.
    assert lines[0] == "- fact number 1 is here"
    assert lines[-1] == "- fact number 5 is here"


def test_block_keeps_the_fact_payload_within_500_characters():
    long_fact = "revenue " * 40  # 320 characters
    ranked = [(0.5, _fact(i, long_fact)) for i in range(1, 4)]
    block = build_facts_block(ranked)
    payload = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert sum(len(ln) for ln in payload) <= MAX_CHARS


def test_block_drops_whole_facts_and_never_cuts_one_in_half():
    long_fact = "revenue " * 40  # does not fit next to the short one
    short_fact = "revenue is 220"
    ranked = [
        (0.5, _fact(1, long_fact)),
        (0.4, _fact(2, long_fact)),
        (0.3, _fact(3, short_fact)),
    ]
    block = build_facts_block(ranked)
    payload = [ln for ln in block.splitlines() if ln.startswith("- ")]
    # The two long facts cannot both fit: the first is kept whole, the
    # second is dropped whole, and the short third still fits after it.
    assert payload == [f"- {long_fact}", f"- {short_fact}"]
    assert short_fact in block
    assert block.count(long_fact) == 1


def test_block_of_facts_that_all_fit_keeps_every_fact():
    ranked = [(0.5, _fact(1, "revenue is 220")), (0.4, _fact(2, "meeting room is booked"))]
    block = build_facts_block(ranked)
    assert "- revenue is 220" in block
    assert "- meeting room is booked" in block
