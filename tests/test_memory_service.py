"""The bounded facts block over whatever ranking the store returns.

Pure function, no I/O, like the snooze arithmetic: the block must stay
bounded (at most 5 facts, 500 characters, whole facts only). The ranking
itself is memory/hybrid's, tested there and through the store.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.memory.core import Fact
from nexuusbot.memory.service import (
    MAX_CHARS,
    MAX_FACTS,
    build_facts_block,
)


def _fact(fact_id: int, text: str, created_ts: float = 100.0) -> Fact:
    return Fact(id=fact_id, text=text, source="page", created_ts=created_ts)


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
