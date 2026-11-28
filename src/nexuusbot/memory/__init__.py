"""Memory: persistent facts the assistant may recall.

The facts live in SQLite (a restart keeps them) and recall ranks through
memory/hybrid.py, the production scorer (donor hybrid recall: entity
graph, RRF fusion, recency, time windows). Capture exists and is gated by
settings: the memory loop offers what flows through the channels the user
left on (memory/loop.py, the memory_capture switches, review mode the
default), and besides it a fact is created from the memory page's add
form or from an accepted inbox card that carries one.
"""

from nexuusbot.memory.core import Fact, UnknownFact
from nexuusbot.memory.service import MAX_CHARS, MAX_FACTS, build_facts_block

__all__ = [
    "MAX_CHARS",
    "MAX_FACTS",
    "Fact",
    "UnknownFact",
    "build_facts_block",
]
