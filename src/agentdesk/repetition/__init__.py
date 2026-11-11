"""Repetition detector and skills: the same ask, done for you.

The detector observes only what flows through the app (research and
assistant asks), clusters similar requests, and at about the fifth
similar ask proposes a one-click skill into the inbox. Skills are
versioned SKILL.md documents in the agentskills.io shape; acceptance is
honestly undoable through that history. No keystrokes, no screen.
"""

from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.cluster import normalize, similarity, cluster_requests
from agentdesk.repetition.service import (
    COOLDOWN_DAYS,
    PROPOSAL_THRESHOLD,
    Consolidator,
    pattern_hash,
)
from agentdesk.repetition.skills import SkillStore

__all__ = [
    "ActivityLog",
    "COOLDOWN_DAYS",
    "PROPOSAL_THRESHOLD",
    "Consolidator",
    "SkillStore",
    "cluster_requests",
    "normalize",
    "pattern_hash",
    "similarity",
]
