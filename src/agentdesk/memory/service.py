"""The bounded prompt block over whatever ranking the store returns.

Pure function, no I/O, like the snooze arithmetic in inbox/snooze.py.

Recall ranks through memory/hybrid.py (the production scorer: donor
hybrid recall, entity graph, RRF fusion, recency, time windows); this
module's one job is the bounded block that rides on whatever ranking the
store returns, so the assistant sees at most MAX_FACTS facts and at most
MAX_CHARS characters of fact payload, never a fact silently half-cut.
"""

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
