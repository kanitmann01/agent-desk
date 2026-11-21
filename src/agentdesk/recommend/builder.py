"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, cron/suggestions.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The recommendation builder: candidates become waiting inbox cards.

Recommendations are ordinary suggestion cards, so the inbox, its budget and
its Undo already know what to do with them; this module only decides which
candidates deserve a card. Hermes' add_suggestion supplies the shape kept
here: a stable dedup key, a pending cap, and no repeat while one waits. The
latch makes Not now permanent even if the card row is later removed.
"""

import json
import time

from agentdesk.inbox.core import KIND_SUGGESTION
from agentdesk.recommend.rules import Candidate, deadline_candidates

# Hermes cron/suggestions.py MAX_PENDING: the desk never stacks more than
# this many waiting suggestions; the soonest deadline earns the slot.
MAX_PENDING = 5

# The builder's latch prefix in the ledger, and the reason a withdrawn card
# shows in place of its original why line.
LATCH_PREFIX = "rec:"
WITHDRAWN_ORIGIN = "Withdrawn: the fact behind it was removed or replaced."


def _recommendation(card) -> dict | None:
    """The recommendation metadata a card carries, if it is one."""
    meta = card.meta if isinstance(card.meta, dict) else {}
    value = meta.get("recommendation")
    return value if isinstance(value, dict) else None


class RecommendationBuilder:
    """Turn saved facts into waiting recommendation cards, idempotently."""

    def __init__(self, inbox, memory, calendar, settings, ledger, clock=time.time) -> None:
        """Hold the stores the builder reads; calendar is unused until the
        meeting-prep rule lands in a later ticket."""
        self._inbox = inbox
        self._memory = memory
        self._calendar = calendar
        self._settings = settings
        self._ledger = ledger
        self._clock = clock

    def refresh(self) -> dict:
        """Withdraw stale cards and add the soonest new candidates.

        Returns {"added": n, "withdrawn": m}. With recommendations off the
        builder does nothing at all, so existing cards keep waiting until
        the user dismisses them.
        """
        if not self._settings.get("recommendations"):
            return {"added": 0, "withdrawn": 0}
        live = self._live()
        withdrawn, live = self._withdraw_stale(live)
        added = self._add_candidates(live)
        return {"added": added, "withdrawn": withdrawn}

    def waiting(self) -> list:
        """The waiting recommendation cards, soonest due first.

        Snoozed cards are waiting too, but they are not visible; the
        dashboard reads this list, so only visible cards are returned.
        """
        cards = [card for card in self._inbox.waiting() if _recommendation(card)]
        cards.sort(key=self._due_sort_key)
        return cards

    def _live(self) -> list:
        """Every unsettled recommendation card, snoozed ones included.

        The cap and the dedup key count a snoozed card as taken: it will
        come back, so a second card for the same deadline would be a repeat.
        """
        return [
            card
            for card in self._inbox.waiting(include_snoozed=True)
            if _recommendation(card) is not None
        ]

    def _add_candidates(self, live: list) -> int:
        """Add cards for kept candidates until the pending cap is reached."""
        candidates: list[Candidate] = []
        if self._settings.get("recommend_deadlines"):
            candidates = deadline_candidates(
                self._memory.all(),
                set(self._memory.superseded_map()),
                self._entity_names(),
                self._now(),
                int(self._settings.get("recommend_horizon_days")),
            )
        taken = {self._key(card) for card in live}
        added = 0
        for candidate in candidates:
            if len(live) >= MAX_PENDING:
                break
            if candidate.key in taken or self._ledger.latched(LATCH_PREFIX + candidate.key):
                continue
            card = self._inbox.add(
                kind=KIND_SUGGESTION,
                origin=candidate.why,
                title=candidate.title,
                body=candidate.body,
                action_label=candidate.action_label,
                meta=self._meta(candidate),
            )
            self._ledger.latch(LATCH_PREFIX + candidate.key)
            self._record(
                "recommend.added",
                card,
                candidate,
                "The desk added a recommendation built from facts you saved.",
                undo_kind="card-added",
            )
            taken.add(candidate.key)
            live.append(card)
            added += 1
        return added

    def _withdraw_stale(self, live: list) -> tuple[int, list]:
        """Dismiss the cards whose cited facts are all gone, and count them.

        A card with no cites cannot prove its fact went away, so it is left
        alone rather than withdrawn on a guess.
        """
        existing = {fact.id for fact in self._memory.all()}
        superseded = set(self._memory.superseded_map())
        withdrawn = 0
        kept: list = []
        for card in live:
            metadata = _recommendation(card) or {}
            cites = [cite for cite in metadata.get("cites") or [] if isinstance(cite, int)]
            if cites and all(cite in superseded or cite not in existing for cite in cites):
                self._inbox.withdraw(card.id, WITHDRAWN_ORIGIN)
                candidate = Candidate(
                    rule=str(metadata.get("rule") or ""),
                    key=str(metadata.get("key") or ""),
                    title=card.title,
                    why=WITHDRAWN_ORIGIN,
                    body=card.body,
                    cites=tuple(cites),
                    href=str(metadata.get("href") or ""),
                    action_label=card.action_label,
                    due_ts=None,
                    sample=bool(metadata.get("sample")),
                )
                self._record(
                    "recommend.withdrawn",
                    card,
                    candidate,
                    WITHDRAWN_ORIGIN,
                    undo_kind="none",
                )
                withdrawn += 1
            else:
                kept.append(card)
        return withdrawn, kept

    def _record(self, action: str, card, candidate: Candidate, why: str, *, undo_kind: str) -> None:
        """Append the ledger entry that the Activity page shows.

        The detail holds the rule and fact ids only; the quoted fact stays
        on the card body, so the ledger never captures memory text.
        """
        self._ledger.record(
            actor="agent-desk",
            action=action,
            subject=f"recommendation/{candidate.key}",
            why=why,
            undo_kind=undo_kind,
            before=(
                json.dumps(card.to_json(self._inbox.now_ts()), ensure_ascii=False).encode("utf-8")
                if undo_kind != "none"
                else None
            ),
            detail={"rule": candidate.rule, "cites": list(candidate.cites)},
        )

    def _meta(self, candidate: Candidate) -> dict:
        """The card metadata the dashboard and the inbox read."""
        return {
            "recommendation": {
                "rule": candidate.rule,
                "key": candidate.key,
                "cites": list(candidate.cites),
                "href": candidate.href,
                "dueTs": candidate.due_ts,
                "sample": candidate.sample,
                "score": None,
                "whySource": "rule",
            }
        }

    def _entity_names(self) -> dict[int, str]:
        """Each linked fact's first entity name, for the card subject."""
        names = {entity.id: entity.canonical_name for entity in self._memory.entities()}
        linked: dict[int, str] = {}
        for fact_id, entity_ids in self._memory.fact_entity_ids().items():
            for entity_id in entity_ids:
                if entity_id in names:
                    linked[fact_id] = names[entity_id]
                    break
        return linked

    def _now(self):
        """The local wall clock the deadline rule resolves dates against."""
        from datetime import datetime

        return datetime.fromtimestamp(self._clock())

    def _due_sort_key(self, card) -> tuple:
        """Soonest due first; a card with no due time sorts last."""
        due = (_recommendation(card) or {}).get("dueTs")
        return (due if isinstance(due, (int, float)) else float("inf"), card.created_ts)

    @staticmethod
    def _key(card) -> str:
        """The dedup key a live card holds, if it holds one."""
        return str((_recommendation(card) or {}).get("key") or "")
