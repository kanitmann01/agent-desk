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


@dataclass(frozen=True)
class Observation:
    """One derived observation (ticket #93, the donor's
    ObservationRecord): what the model concluded, how confident it was,
    and which facts it cites. `fact_ids` is the citation list; the
    scope key that grouped the reflect run stays a store concern and
    never rides this row out."""

    id: int
    text: str
    confidence: float
    fact_ids: tuple[int, ...]
    created_ts: float = 0.0
    updated_ts: float = 0.0


@dataclass(frozen=True)
class SourceExcerpt:
    """One retained excerpt (the sources table): the text a retain
    extracted its candidate facts from, who spoke it, the context the
    retain recorded, and when it was saved."""

    id: int
    text: str
    speaker: str = ""
    context: str = ""
    created_ts: float = 0.0


@dataclass(frozen=True)
class SavedObservation:
    """What one save wrote (the donor's saveObservations result, reduced
    to the single-observation shape the approval cards need): the
    observation as stored, and the ids of the same-scope rows this save
    dropped as no longer kept."""

    observation: Observation
    removed_ids: tuple[int, ...] = ()


def normalize_fact_text(text: str) -> str:
    """The donor's normalizeFactText: trim, collapse internal whitespace
    runs to single spaces, lowercase. Punctuation stays, so this is an
    exact-text match, not a semantic comparison. Shared vocabulary:
    write-time dedupe, observation upserts and the reflect filters all
    compare through it."""
    return " ".join(text.split()).lower()
