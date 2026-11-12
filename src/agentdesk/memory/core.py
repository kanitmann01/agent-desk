"""The memory facts' shared vocabulary: the row shape and its error."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Fact:
    """One remembered fact: what, where it came from, and when.

    `created_ts` is part of the recall tie-break, so it rides with the
    row instead of being looked up separately.
    """

    id: int
    text: str
    source: str
    created_ts: float


class UnknownFact(Exception):
    """No fact by that id."""
