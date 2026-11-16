"""Recall arithmetic: tokenize, score, rank, and the bounded prompt block.

Pure functions, no I/O, like the snooze arithmetic in inbox/snooze.py.

Ported from the teammate's memory module (packages/host/src/memory/
memory.ts): their tokensOf tokenizer and their keyword-overlap fraction
(the share of the query's tokens that appear in the fact). Their total
score adds a 32-bucket hashed cosine on top; both halves are
deterministic, so either port is faithful. The divergence is deliberate
and recorded here: only the overlap fraction is kept, because the vector
term adds ranking noise no fact collection of this size needs, and the
score stays explainable as "how much of the query the fact answers".

Since ticket #90 the store's recall ranks through memory/hybrid.py
(donor hybrid recall: entity graph, RRF fusion, recency, time windows);
this module's rank remains exported and tested as the fallback scorer
and migration baseline, and the bounded block below still rides on
whatever ranking the store returns.

Determinism is explicit everywhere: rank sorts by score descending, then
by created_ts ascending, then by id ascending, so the same facts and the
same query always produce the same order (Python's sort is stable, and
the tie-break keys make that stability independent of input order).
Facts with no overlap never recall: silence is the designed empty.
"""

import re

from agentdesk.memory.core import Fact

# The prompt block's bounds (ticket #42): the assistant may see at most
# five facts and at most 500 characters of fact payload, never a fact
# silently half-cut.
MAX_FACTS = 5
MAX_CHARS = 500

_BLOCK_HEADER = (
    "Known facts about the user (derived abstractions; review them on "
    "the memory page):"
)


def tokenize(text: str) -> list[str]:
    """The donor's tokensOf: lowercase, split on non-alphanumerics, keep
    tokens longer than two characters (the, revenue and 220 survive; I,
    AB and punctuation do not). The split is ASCII-only, an accepted
    divergence matching the donor: text with no a-z0-9 tokens (CJK-only,
    say) tokenizes to nothing and so recalls nothing."""
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if len(token) > 2]


def score(query_tokens: list[str], fact_tokens: list[str]) -> float:
    """The overlap fraction: the share of the query's tokens present in
    the fact. Both sides empty means zero, never a division error."""
    if not query_tokens or not fact_tokens:
        return 0.0
    fact_set = set(fact_tokens)
    overlap = sum(1 for token in query_tokens if token in fact_set)
    return overlap / len(query_tokens)


def rank(query: str, facts: list[Fact]) -> list[tuple[float, Fact]]:
    """The deterministic recall order: scored, best first, ties broken by
    created_ts then id, zero-overlap facts excluded."""
    query_tokens = tokenize(query)
    scored = [
        (score(query_tokens, tokenize(fact.text)), fact) for fact in facts
    ]
    kept = [item for item in scored if item[0] > 0.0]
    kept.sort(key=lambda item: (-item[0], item[1].created_ts, item[1].id))
    return kept


def build_facts_block(
    ranked: list[tuple[float, Fact]],
    max_facts: int = MAX_FACTS,
    max_chars: int = MAX_CHARS,
) -> str:
    """The bounded derived-abstractions block the assistant prompt gains.

    At most `max_facts` facts, and at most `max_chars` characters of
    fact payload together. A fact that does not fit is dropped whole
    (later, shorter facts may still fit; nothing is ever cut in half).
    No recall, no block: the prompt gains nothing.
    """
    if not ranked:
        return ""
    lines: list[str] = []
    used = 0
    for _s, fact in ranked[:max_facts]:
        line = f"- {fact.text}"
        cost = len(line) + (1 if lines else 0)
        if used + cost > max_chars:
            continue
        lines.append(line)
        used += cost
    if not lines:
        return ""
    return "\n".join([_BLOCK_HEADER] + lines)
