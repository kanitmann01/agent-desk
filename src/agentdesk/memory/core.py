"""The memory facts' shared vocabulary: the row shape and its error."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Fact:
    """One remembered fact: what, where it came from, and when.

    `created_ts` is part of the recall tie-break, so it rides with the
    row instead of being looked up separately. `kind` splits world
    knowledge from lived experience and `occurrence_ts` is when the
    event itself happened (creation time stays when it was told to the
    desk); both arrive with schema v2 (ticket #89). `source_id` links a
    retained conversation excerpt once the sources table gains rows, a
    later ticket's write path.
    """

    id: int
    text: str
    source: str
    created_ts: float
    kind: str = "world"
    occurrence_ts: float | None = None
    source_id: int | None = None


class UnknownFact(Exception):
    """No fact by that id."""
