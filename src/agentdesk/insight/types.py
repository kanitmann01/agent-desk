"""The shapes the coupled-intelligence seam passes around.

One context in, one reading out. A family module never reaches for the
server, the preferences file or the clock itself, so a reading is a pure
function of what the dashboard already decided to show and of what the
user already said about themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# recall(subject, limit) -> [{"text": ..., "source": ...}]; None whenever
# memory is absent, locked or sealed, which a family must read as "no
# memory to lean on" rather than as an empty memory.
Recall = Callable[[str, int], list[dict]]

# A reading says at most this much, whatever the density preference asks
# for: a card is a glance, and the button carries the deep version.
MAX_ELEMENTS = 4


@dataclass(frozen=True)
class InsightContext:
    """Everything a family may consult, resolved once per payload."""

    preferences: dict
    now: float
    recall: Recall | None = None
    memory_note: str = ""
    # The next meeting, when the calendar is readable: {"title", "time",
    # "meta", "prep"} or None. Shared so a card about research can be
    # about *this* meeting without reaching for the calendar itself.
    agenda: dict | None = None
    agenda_note: str = ""

    @property
    def density(self) -> str:
        value = str(self.preferences.get("insightDensity") or "normal")
        return value if value in ("quiet", "normal", "chatty") else "normal"

    @property
    def max_elements(self) -> int:
        return {"quiet": 1, "normal": 3, "chatty": MAX_ELEMENTS}[self.density]


@dataclass
class InsightReading:
    """What one family made of one card.

    `elements` are appended to the card's own payload elements, so they
    render through the same ElementView chain as everything else. `press`
    is the offer of a model call (label + route + the disclosure of what
    would be sent); nothing is spent until the user presses it.
    """

    elements: list[dict] = field(default_factory=list)
    # Row indices the reading would select if the user pressed it, in the
    # workbook's own row numbering. Empty for every family but the workbook.
    suggested: tuple[int, ...] = ()
    press: dict | None = None
    note: str = ""
    status: str = ""


class InsightError(Exception):
    """A refused reading or draft request. The code is stable and the
    message is written for the person reading it, never for a log."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
