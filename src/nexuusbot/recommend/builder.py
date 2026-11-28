"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, cron/suggestions.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The recommendation builder: candidates become waiting inbox cards.

Recommendations are ordinary suggestion cards, so the inbox, its budget and
its Undo already know what to do with them; this module only decides which
candidates deserve a card. Hermes' add_suggestion supplies the shape kept
here: a stable dedup key, a pending cap, and no repeat while one waits. The
latch makes Not now permanent even if the card row is later removed.
"""

import hashlib
import json
import logging
import time
from datetime import datetime

from nexuusbot.inbox.core import KIND_SUGGESTION
from nexuusbot.recommend.rules import Candidate, deadline_candidates, meeting_candidates

LOG = logging.getLogger(__name__)

# Hermes cron/suggestions.py MAX_PENDING: the desk never stacks more than
# this many waiting suggestions; the soonest deadline earns the slot.
MAX_PENDING = 5

# The builder's latch prefix in the ledger, and the reason a withdrawn card
# shows in place of its original why line.
LATCH_PREFIX = "rec:"
WITHDRAWN_ORIGIN = "Withdrawn: the fact behind it was removed or replaced."
MEETING_WITHDRAWN_ORIGIN = "Withdrawn: the meeting is no longer in the next 24 hours."


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
        withdrawn, live = self._withdraw_stale(
            live, self._meeting_candidate_keys()
        )
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

    def add_engine_card(self, *, title: str, body: str, why: str = "",
                        href: str = "/inbox",
                        action_label: str = "Review") -> tuple | None:
        """Add one suggestion the desk's engine proposed, as an ordinary card.

        The card takes the same shape, cap, latch and ledger entry every
        recommendation does (rule "engine", no cites, so the withdrawal
        check never retracts it on a guess), and its entry carries the
        card-added undo kind, so Undo dismisses it. None when
        recommendations are off, when the waiting cap is already full,
        or when a card for the same content is already waiting or was
        latched: the desk never floods or stacks the same suggestion.
        A record that fails removes the card and the latch it wrote, so
        a suggestion without its ledger entry leaves nothing behind.
        """
        if self._ledger is None or self._inbox is None:
            return None
        if not self._settings.get("recommendations"):
            return None
        live = self._live()
        if len(live) >= MAX_PENDING:
            return None
        key = "engine:" + hashlib.sha256(
            f"{title}\n{body}".encode("utf-8")).hexdigest()[:16]
        taken = {self._key(card) for card in live}
        if key in taken or self._ledger.latched(LATCH_PREFIX + key):
            return None
        candidate = Candidate(
            rule="engine", key=key, title=title, why=why or "The desk suggests this.",
            body=body, cites=(), href=href, action_label=action_label,
            due_ts=None, sample=False,
        )
        card = self._inbox.add(
            kind=KIND_SUGGESTION,
            origin=candidate.why,
            title=candidate.title,
            body=candidate.body,
            action_label=candidate.action_label,
            meta=self._meta(candidate),
        )
        self._ledger.latch(LATCH_PREFIX + key)
        try:
            entry = self._record(
                "recommend.added",
                card,
                candidate,
                "The desk suggested this while working on its own.",
                undo_kind="card-added",
            )
        except Exception:
            # The card and its latch are this call's only writes; a record
            # that failed cannot leave them standing.
            try:
                self._inbox.delete(card.id)
            except Exception:  # noqa: BLE001 - the original failure is the news
                LOG.exception("engine card %s could not be removed after a failed record",
                              card.id)
            try:
                self._ledger.unlatch(LATCH_PREFIX + key)
            except Exception:  # noqa: BLE001 - the original failure is the news
                LOG.exception("the engine card latch %s could not be cleared", key)
            raise
        return card, entry

    def _add_candidates(self, live: list) -> int:
        """Add cards for kept candidates until the pending cap is reached."""
        candidates: list[Candidate] = []
        if self._settings.get("recommend_deadlines"):
            candidates.extend(deadline_candidates(
                self._memory.all(),
                set(self._memory.superseded_map()),
                self._entity_names(),
                self._now(),
                int(self._settings.get("recommend_horizon_days")),
            ))
        if self._settings.get("recommend_meetings"):
            candidates.extend(
                meeting_candidates(
                    self._calendar_events(),
                    self._entity_id_names(),
                    self._facts_by_entity(),
                    self._now_aware(),
                )
            )
        candidates.sort(key=lambda candidate: (candidate.due_ts or 0.0, candidate.key))
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

    def _withdraw_stale(self, live: list, meeting_keys: set[str] | None) -> tuple[int, list]:
        """Dismiss cards whose facts are gone, or whose meeting left the window.

        A card with no cites cannot prove its fact went away, so it is left
        alone rather than withdrawn on a guess. A meeting card whose start is
        already past is kept too; the user may still want the prep notes.
        """
        existing = {fact.id for fact in self._memory.all()}
        superseded = set(self._memory.superseded_map())
        now_ts = self._now_aware().timestamp()
        withdrawn = 0
        kept: list = []
        for card in live:
            metadata = _recommendation(card) or {}
            cites = [cite for cite in metadata.get("cites") or [] if isinstance(cite, int)]
            rule = str(metadata.get("rule") or "")
            due = metadata.get("dueTs")
            meeting_gone = (
                meeting_keys is not None
                and rule == "meeting-prep"
                and isinstance(due, (int, float))
                and due >= now_ts
                and str(metadata.get("key") or "") not in meeting_keys
            )
            if meeting_gone or (cites and all(cite in superseded or cite not in existing for cite in cites)):
                origin = MEETING_WITHDRAWN_ORIGIN if meeting_gone else WITHDRAWN_ORIGIN
                self._withdraw(card, metadata, origin)
                withdrawn += 1
            else:
                kept.append(card)
        return withdrawn, kept

    def _withdraw(self, card, metadata: dict, origin: str) -> None:
        """Dismiss one awaiting card and record why the desk took it back."""
        self._inbox.withdraw(card.id, origin)
        candidate = Candidate(
            rule=str(metadata.get("rule") or ""),
            key=str(metadata.get("key") or ""),
            title=card.title,
            why=origin,
            body=card.body,
            cites=tuple(metadata.get("cites") or ()),
            href=str(metadata.get("href") or ""),
            action_label=card.action_label,
            due_ts=None,
            sample=bool(metadata.get("sample")),
        )
        self._record("recommend.withdrawn", card, candidate, origin, undo_kind="none")

    def _record(self, action: str, card, candidate: Candidate, why: str, *, undo_kind: str):
        """Append the ledger entry that the Activity page shows.

        The detail holds the rule and fact ids only; the quoted fact stays
        on the card body, so the ledger never captures memory text.
        """
        return self._ledger.record(
            actor="agent",
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
                "whySource": "engine" if candidate.rule == "engine" else "rule",
            }
        }

    def _calendar_events(self) -> list:
        """The next 24 hours of events, or nothing when no calendar is wired."""
        if self._calendar is None:
            return []
        return self._calendar.upcoming(self._now_aware(), within_hours=24)

    def _meeting_candidate_keys(self) -> set[str] | None:
        """The meeting keys still inside the window, for the withdrawal check.

        None means there is no trustworthy view of the calendar yet, so the
        meeting cards keep waiting. A bridge that has never read a document
        answers with no events, which must not be mistaken for an empty day.
        """
        if not self._settings.get("recommend_meetings") or self._calendar is None:
            return None
        has_document = getattr(self._calendar, "has_document", None)
        if callable(has_document) and not has_document():
            return None
        return {
            candidate.key
            for candidate in meeting_candidates(
                self._calendar_events(),
                self._entity_id_names(),
                self._facts_by_entity(),
                self._now_aware(),
            )
        }

    def _entity_id_names(self) -> dict[int, str]:
        """The account-like entities the meeting rule may match.

        Concepts are deliberately left out: an event called "Q4 pipeline
        review" names a topic, not an account to prepare for.
        """
        return {
            entity.id: entity.canonical_name
            for entity in self._memory.entities()
            if entity.type in ("org", "person")
        }

    def _facts_by_entity(self) -> dict[int, list]:
        """Each entity's linked facts, newest first, for the prep card body."""
        by_id = {fact.id: fact for fact in self._memory.all()}
        linked: dict[int, list] = {}
        for fact_id, entity_ids in self._memory.fact_entity_ids().items():
            fact = by_id.get(fact_id)
            if fact is None:
                continue
            for entity_id in entity_ids:
                linked.setdefault(entity_id, []).append(fact)
        for facts in linked.values():
            facts.sort(
                key=lambda fact: (getattr(fact, "created_ts", 0.0), getattr(fact, "id", 0)),
                reverse=True,
            )
        return linked

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
        return datetime.fromtimestamp(self._clock())

    def _now_aware(self):
        """The local wall clock, timezone-aware for comparing calendar starts."""
        return datetime.fromtimestamp(self._clock()).astimezone()

    def _due_sort_key(self, card) -> tuple:
        """Soonest due first; a card with no due time sorts last."""
        due = (_recommendation(card) or {}).get("dueTs")
        return (due if isinstance(due, (int, float)) else float("inf"), card.created_ts)

    @staticmethod
    def _key(card) -> str:
        """The dedup key a live card holds, if it holds one."""
        return str((_recommendation(card) or {}).get("key") or "")
