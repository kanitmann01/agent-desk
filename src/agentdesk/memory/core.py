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


class UnknownEntity(Exception):
    """No entity by that id."""


@dataclass(frozen=True)
class EditResult:
    """The outcome of an edit (ticket #92, the donor's updateFact): the
    fact that now carries the text, which is a different row when the
    edit merged into an existing duplicate, and whether it did."""

    fact: Fact
    merged_into: bool = False


@dataclass(frozen=True)
class EntitySummary:
    """One entity as the memory page lists it: names, type and how many
    facts mention it."""

    id: int
    canonical_name: str
    aliases: tuple[str, ...] = ()
    type: str = "other"
    fact_count: int = 0


@dataclass(frozen=True)
class SweepCandidate:
    """One junk-sweep candidate: the fact and the reason retain would
    drop it (memory/knowledge_gap's vocabulary)."""

    fact: Fact
    reason: str


@dataclass(frozen=True)
class RemovedFacts:
    """What a many-fact delete removed (the donor's removeFacts): the
    facts, the observations left uncited by the deletion, and the
    entities left with zero edges."""

    fact_ids: tuple[int, ...]
    observation_ids: tuple[int, ...] = ()
    entity_ids: tuple[int, ...] = ()
