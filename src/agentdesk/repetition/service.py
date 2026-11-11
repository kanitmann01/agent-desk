"""The consolidation run: activity in, at most one proposal out.

A pattern that has reached about five similar asks proposes once; a
dismissed pattern stays quiet for its cooldown while a genuinely new
pattern can still propose. The proposal carries the pattern, the count,
and an honest will/will-not body, and its metadata is everything Accept
needs to activate the skill.
"""

import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from agentdesk.inbox.store import InboxStore
from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.cluster import cluster_requests, pattern_hash, similarity
from agentdesk.repetition.skills import SkillStore

PROPOSAL_THRESHOLD = 5
COOLDOWN_DAYS = 14.0
_SEED_SIMILARITY = 0.6

_COOLDOWN_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposal_cooldowns (
  pattern TEXT PRIMARY KEY,
  dismissed_ts REAL NOT NULL
);
"""


class Consolidator:
    """Activity + inbox + skills + cooldowns, one pass per run."""

    def __init__(
        self,
        activity: ActivityLog,
        inbox: InboxStore,
        skills: SkillStore,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.activity = activity
        self.inbox = inbox
        self.skills = skills
        self.clock = clock
        with activity.conn:
            activity.conn.executescript(_COOLDOWN_SCHEMA)

    def consolidate(self, now: datetime | None = None) -> dict:
        """One pass: cluster, find a countable new pattern, propose once."""
        now = now or datetime.fromtimestamp(self.clock()).astimezone()
        asks = [e for e in self.activity.entries(500) if e["kind"] in ("research", "assistant")]
        if not asks:
            return {"proposed": False}
        texts = [e["text"] for e in asks]
        for cluster in cluster_requests(texts):
            if len(cluster) < PROPOSAL_THRESHOLD:
                continue
            seed_text = texts[cluster[0]]
            pattern = pattern_hash(seed_text)
            if self._on_cooldown(pattern, now):
                continue
            if self._already_proposed(pattern):
                continue
            count = len(cluster)
            sample = seed_text.strip()
            name = _skill_name(sample)
            card = self.inbox.add(
                kind="skill_proposal",
                origin=f"Pattern noticed, {count}th time: you keep asking to {sample[:80]}",
                title=f"Turn this into one click? ({count} times)",
                body=(
                    f"The skill would re-run this exact ask: {sample[:120]}. "
                    "It will use your connected widgets' context and the company "
                    "endpoint, and it will be logged like every other call. "
                    "It will not read anything the dashboard cannot already see, "
                    "and it will not send anything new anywhere."
                ),
                action_label="Accept skill",
                meta={"patternHash": pattern, "count": count, "skillName": name, "prompt": sample},
            )
            return {"proposed": True, "cardId": card.id, "pattern": pattern, "count": count}
        return {"proposed": False}

    def dismiss_cooldown(self, pattern: str) -> None:
        with self.activity.conn:
            self.activity.conn.execute(
                "INSERT INTO proposal_cooldowns (pattern, dismissed_ts) VALUES (?, ?)"
                " ON CONFLICT(pattern) DO UPDATE SET dismissed_ts = excluded.dismissed_ts",
                (pattern, self.clock()),
            )

    def _on_cooldown(self, pattern: str, now: datetime) -> bool:
        row = self.activity.conn.execute(
            "SELECT dismissed_ts FROM proposal_cooldowns WHERE pattern = ?", (pattern,)
        ).fetchone()
        if row is None:
            return False
        dismissed = datetime.fromtimestamp(row[0]).astimezone()
        return now - dismissed < timedelta(days=COOLDOWN_DAYS)

    def _already_proposed(self, pattern: str) -> bool:
        """One live proposal per pattern: accepted or waiting is enough."""
        for card in self.inbox.waiting() + self.inbox.dismissed():
            if card.meta.get("patternHash") == pattern:
                return True
        for skill in self.skills.active():
            if pattern_hash(skill["prompt"]) == pattern:
                return True
        return False


def _skill_name(sample: str) -> str:
    words = sample.strip().split()[:5]
    return " ".join(words) if words else "saved ask"
