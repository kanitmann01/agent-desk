"""Pure data model for inbox cards.

A card is one thing the agent initiated: a suggestion, a skill proposal,
an update re-consent, a brief. The origin line is the reason it exists in
plain language, and every time-bound card carries its window so nothing
can expire quietly.
"""

from dataclasses import dataclass, field
from datetime import datetime

KIND_SUGGESTION = "suggestion"
KIND_SKILL_PROPOSAL = "skill_proposal"
KIND_UPDATE_CONSENT = "update_consent"
KIND_BRIEF = "brief"
CARD_KINDS = (KIND_SUGGESTION, KIND_SKILL_PROPOSAL, KIND_UPDATE_CONSENT, KIND_BRIEF)

STATUS_WAITING = "waiting"
STATUS_ACCEPTED = "accepted"
STATUS_DISMISSED = "dismissed"

RECOVERY_DAYS = 30.0


class UnknownCard(Exception):
    """No card by that id."""


@dataclass
class Card:
    """One inbox entry. `origin` is the always-present reason line."""

    id: str
    kind: str
    origin: str
    title: str
    body: str = ""
    action_label: str = ""
    status: str = STATUS_WAITING
    created_ts: float = 0.0
    window_hours: float | None = None  # time-bound cards say so, loudly
    notified_ts: float | None = None
    dismissed_ts: float | None = None
    accepted_ts: float | None = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in CARD_KINDS:
            raise ValueError(f"unknown card kind: {self.kind!r}")
        if not self.origin.strip():
            raise ValueError("a card without an origin line is not a card")

    def is_expired(self, now_ts: float) -> bool:
        if self.window_hours is None:
            return False
        return now_ts >= self.created_ts + self.window_hours * 3600

    def dismissed_for_days(self, now_ts: float) -> float:
        if self.dismissed_ts is None:
            return 0.0
        return (now_ts - self.dismissed_ts) / 86400

    def to_json(self, now_ts: float) -> dict:
        """The API payload: state, origin, window, aging. Nothing hidden."""
        return {
            "id": self.id,
            "kind": self.kind,
            "origin": self.origin,
            "title": self.title,
            "body": self.body,
            "actionLabel": self.action_label,
            "status": self.status,
            "createdTs": self.created_ts,
            "createdIso": datetime.fromtimestamp(self.created_ts).isoformat() if self.created_ts else "",
            "windowHours": self.window_hours,
            "expired": self.is_expired(now_ts),
            "notified": self.notified_ts is not None,
            "dismissedDays": round(self.dismissed_for_days(now_ts), 1),
            "meta": self.meta,
        }
