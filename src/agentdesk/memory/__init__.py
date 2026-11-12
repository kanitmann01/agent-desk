"""Memory: persistent facts the assistant may recall, and nothing more.

The facts live in SQLite (a restart keeps them), recall ranks by token
overlap deterministically, and nothing here is captured automatically:
a fact is created only from the memory page's add form or from an
accepted inbox card that carries one.
"""

from agentdesk.memory.core import Fact, UnknownFact
from agentdesk.memory.service import MAX_CHARS, MAX_FACTS, build_facts_block, rank, tokenize

__all__ = [
    "MAX_CHARS",
    "MAX_FACTS",
    "Fact",
    "UnknownFact",
    "build_facts_block",
    "rank",
    "tokenize",
]
