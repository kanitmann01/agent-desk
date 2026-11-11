"""Inbox: everything the agent initiates, under a strict interruption budget.

Cards wait here; notifications are spent, never sprayed. The budget is
the contract from the spec: quiet hours default 18:00-08:00 local, at
most three proactive notifications per day, digest batching, and nothing
expires silently. What cannot notify waits in the inbox visibly.
"""

from agentdesk.inbox.budget import decide_budget
from agentdesk.inbox.core import (
    KIND_BRIEF,
    KIND_SKILL_PROPOSAL,
    KIND_SUGGESTION,
    KIND_UPDATE_CONSENT,
    STATUS_ACCEPTED,
    STATUS_DISMISSED,
    STATUS_WAITING,
    Card,
    UnknownCard,
)
from agentdesk.inbox.store import InboxStore

__all__ = [
    "Card",
    "InboxStore",
    "KIND_BRIEF",
    "KIND_SKILL_PROPOSAL",
    "KIND_SUGGESTION",
    "KIND_UPDATE_CONSENT",
    "STATUS_ACCEPTED",
    "STATUS_DISMISSED",
    "STATUS_WAITING",
    "UnknownCard",
    "decide_budget",
]
