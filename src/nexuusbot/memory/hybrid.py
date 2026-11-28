"""Deterministic hybrid recall: keyword, entity graph, recency, windows.

Pure functions, no I/O, `now` always passed in: the same facts, query
and clock produce the same order forever. This module replaces token
overlap as the store's recall (ticket #90) and ports the donor's
memory-bank sources exactly: the tokenizer and stopword list from
src/tokens.ts, the name normalization and scoring tiers from
src/names.ts and src/recall.ts, the fusion, graph expansion and recency
from src/hybrid.ts, and the window parser from src/time-window.ts.

The pipeline replicates the donor's rankHybridFacts: each leg scores
the facts, each scored list is ranked (score descending, id ascending),
the lists fuse by reciprocal rank fusion (contribution weight over k
plus rank plus one, rank zero-based, k sixty, unit weights; the vector
leg joins at unit weight when embeddings arrive), then recency
multiplies (one half per thirty-day half-life of occurrence-else-
creation age; an undated instant factors zero). A time cue in the
query restricts recall to that window: facts without an instant or
outside it drop, and in-window facts gain a small constant prior so
the window can surface on its own. Final order: fused score
descending, creation time descending, id ascending.

One recorded divergence: the ticket and spec call the stopword list
63 words; the donor's list (the exact list this module ports) holds 61
words. The list itself is authoritative, so it is copied verbatim.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
UTC = timezone.utc  # datetime.UTC needs 3.11; the declared floor is 3.10

from nexuusbot.memory.core import Fact

RRF_K = 60
HALF_LIFE_DAYS = 30.0
# Unit weights (donor DEFAULT_HYBRID_WEIGHTS): every leg counts the same.
KEYWORD_WEIGHT = 1.0
VECTOR_WEIGHT = 1.0
GRAPH_WEIGHT = 1.0
# Small enough that one real list hit outranks a time-only fact at the
# same recency (donor TIME_PRIOR = 1 / (k + 1000)).
TIME_PRIOR = 1 / (RRF_K + 1000)
DAY_SECONDS = 86_400.0

# The donor's STOPWORDS from src/tokens.ts, verbatim (61 words).
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "from",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "we",
        "they",
        "he",
        "she",
        "them",
        "his",
        "her",
        "their",
        "my",
        "your",
        "our",
        "not",
        "no",
        "do",
        "did",
        "does",
        "about",
        "into",
        "over",
        "after",
        "before",
        "what",
        "when",
        "where",
        "who",
        "whom",
        "which",
        "how",
        "why",
    }
)


@dataclass(frozen=True)
class EntityLink:
    """One entity joined to a fact through an edge: what the graph leg
    needs to score and expand (the store loads these from entities and
    edges; the row's type column rides in the database, not here)."""

    id: int
    name: str
    aliases: tuple[str, ...] = ()


# -- tokens (src/tokens.ts) -----------------------------------------------


def tokenize(text: str) -> list[str]:
    """The donor's raw tokenize: NFKC, lowercase, split on
    non-alphanumerics, keep every non-empty piece. Nothing is filtered
    here: the keyword leg tests its query tokens against this raw set,
    and the meaningful filter below is a separate, explicit step."""
    return [
        token
        for token in re.split(r"[^a-z0-9]+", unicodedata.normalize("NFKC", text).lower())
        if token
    ]


def meaningful_tokens(text: str) -> list[str]:
    """The donor's meaningfulTokens: raw tokens with at least two
    characters, stopwords dropped, duplicates dropped, first-seen
    order kept. This is the query side of every leg."""
    seen: set[str] = set()
    tokens: list[str] = []
    for token in tokenize(text):
        if len(token) < 2 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def estimate_tokens(text: str) -> int:
    """The donor's estimateTokens: roughly four characters per token,
    on the trimmed text; blank text costs nothing."""
    trimmed = text.strip()
    if not trimmed:
        return 0
    return math.ceil(len(trimmed) / 4)


# -- names (src/names.ts) --------------------------------------------------


def normalize_name(name: str) -> str:
    """The donor's normalizeName: NFKC, lowercase, apostrophes removed,
    remaining punctuation to spaces, whitespace collapsed and trimmed."""
    folded = unicodedata.normalize("NFKC", name).lower().replace("'", "").replace("\u2019", "")
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", folded).split())


def name_parts(name: str) -> list[str]:
    """The normalized name split into its parts (empty when blank)."""
    normalized = normalize_name(name)
    return normalized.split(" ") if normalized else []


# -- the legs --------------------------------------------------------------


def keyword_scores(facts: list[Fact], tokens: list[str]) -> dict[int, float]:
    """The keyword leg: plus one per meaningful query token present in
    the fact's raw token set. Facts without a hit stay out."""
    scores: dict[int, float] = {}
    if not tokens:
        return scores
    for fact in facts:
        fact_tokens = set(tokenize(fact.text))
        total = sum(1 for token in tokens if token in fact_tokens)
        if total > 0:
            scores[fact.id] = total
    return scores


def graph_scores(
    facts: list[Fact],
    links: dict[int, list[EntityLink]],
    query: str,
    tokens: list[str],
) -> dict[int, float]:
    """The graph leg: score every linked entity's names against the
    query, add matched entities' weights to their facts, then expand
    one hop: entities linked to already-scored facts but not directly
    matched seed their other facts at one."""
    scores: dict[int, float] = {}
    query_norm = normalize_name(query)
    query_tokens = set(tokens)
    entity_score: dict[int, float] = {}
    seen_entities: set[int] = set()
    for fact in facts:
        for link in links.get(fact.id, []):
            if link.id in seen_entities:
                continue
            seen_entities.add(link.id)
            best = score_entity_name(link.name, link.aliases, query_norm, query_tokens)
            if best > 0:
                entity_score[link.id] = best
    if not entity_score:
        return scores

    facts_by_entity: dict[int, list[int]] = {}
    for fact in facts:
        for link in links.get(fact.id, []):
            facts_by_entity.setdefault(link.id, []).append(fact.id)

    direct_entities: set[int] = set()
    for entity_id, weight in entity_score.items():
        direct_entities.add(entity_id)
        for fact_id in facts_by_entity.get(entity_id, []):
            scores[fact_id] = scores.get(fact_id, 0.0) + weight

    neighbors: set[int] = set()
    for fact in facts:
        if fact.id not in scores:
            continue
        for link in links.get(fact.id, []):
            if link.id not in direct_entities:
                neighbors.add(link.id)
    for entity_id in neighbors:
        for fact_id in facts_by_entity.get(entity_id, []):
            if fact_id not in scores:
                scores[fact_id] = 1.0
    return scores


def score_entity_name(
    canonical: str,
    aliases,
    query_norm: str,
    query_tokens: set[str],
) -> int:
    """The donor's three tiers over the canonical name and every alias,
    best wins: the name as a phrase inside the query scores ten plus
    three per part; every part of at least three characters present in
    the query tokens scores five plus two per part; any overlap scores
    two per overlapping part."""
    padded = f" {query_norm} "
    best = 0
    for name in [canonical, *aliases]:
        norm = normalize_name(name)
        if not norm:
            continue
        parts = norm.split(" ")
        if f" {norm} " in padded:
            best = max(best, 10 + len(parts) * 3)
            continue
        overlap = [part for part in parts if len(part) >= 3 and part in query_tokens]
        if len(overlap) == len(parts):
            best = max(best, 5 + len(parts) * 2)
        elif overlap:
            best = max(best, len(overlap) * 2)
    return best


# -- fusion ----------------------------------------------------------------


def rank_ids(scores: dict[int, float]) -> list[int]:
    """A leg's ranking: score descending, id ascending (the donor's
    rankIds tie-break, which keeps the fusion independent of input
    order)."""
    return [
        fact_id
        for fact_id, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


def fuse_parts(lists, k: int = RRF_K) -> dict[int, float]:
    """Reciprocal rank fusion: each list contributes weight over
    k plus rank plus one (rank zero-based) to every id it holds; a
    fact's fused score is the sum over the lists. The vector leg joins
    here as one more (ids, weight) pair at unit weight."""
    fused: dict[int, float] = {}
    for ids, weight in lists:
        if weight == 0:
            continue
        for rank, fact_id in enumerate(ids):
            fused[fact_id] = fused.get(fact_id, 0.0) + weight / (k + rank + 1)
    return fused


# -- recency and instants --------------------------------------------------


def event_instant(occurrence_ts: float | None, created_ts: float | None) -> float | None:
    """When the fact's event happened: the occurrence when present,
    else the creation time. Both missing means undated."""
    if occurrence_ts is not None:
        return occurrence_ts
    return created_ts


def recency_factor(
    when: float | None,
    now: float,
    half_life_days: float = HALF_LIFE_DAYS,
) -> float:
    """The donor's recency: one half per thirty-day half-life of age,
    one for a now-or-future instant, zero for an undated one."""
    if when is None:
        return 0.0
    age_days = (now - when) / DAY_SECONDS
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


# -- time windows (src/time-window.ts) --------------------------------------

# Inclusive start, exclusive end, both UTC epoch seconds.
Window = tuple[float, float]

_MONTH = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    "jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    "nov(?:ember)?|dec(?:ember)?"
)

_MONTH_INDEX = {
    "jan": 0,
    "feb": 1,
    "mar": 2,
    "apr": 3,
    "may": 4,
    "jun": 5,
    "jul": 6,
    "aug": 7,
    "sep": 8,
    "oct": 9,
    "nov": 10,
    "dec": 11,
}

_ISO_DAY = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_DAY = re.compile(
    rf"\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b"
)
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})(?:\s+(\d{{4}}))?\b")
_IN_MONTH = re.compile(rf"\bin\s+({_MONTH})(?:\s+(\d{{4}}))?\b")
_MONTH_YEAR = re.compile(rf"\b({_MONTH})\s+(\d{{4}})\b")

_CUE_YESTERDAY = re.compile(r"\byesterday\b")
_CUE_TODAY = re.compile(r"\btoday\b")
_CUE_TOMORROW = re.compile(r"\btomorrow\b")
_CUE_LAST_WEEK = re.compile(r"\blast week\b")
_CUE_THIS_WEEK = re.compile(r"\bthis week\b")
_CUE_LAST_MONTH = re.compile(r"\blast month\b")
_CUE_THIS_MONTH = re.compile(r"\bthis month\b")


def parse_time_window(query: str, now: float) -> Window | None:
    """Pull one time window out of a query, UTC throughout. Weeks start
    Monday (a Sunday's week began the Monday before). No cue returns
    None. The leftmost cue wins; a longer cue wins a tie."""
    text = query.lower()
    hits: list[tuple[int, int, Window]] = []

    def consider(index: int, length: int, window: Window | None) -> None:
        """Keep one candidate, unless its cue was absent or its date unreal.

        index is the cue's offset and length its width; the leftmost-then-
        longest tie-break later sorts on exactly those two. -1 means the
        pattern never matched and None means the date it named does not exist,
        so both are dropped here rather than filtered by the caller.
        """
        if window is None or index < 0:
            return
        hits.append((index, length, window))

    for match in _ISO_DAY.finditer(text):
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        consider(match.start(), len(match.group(0)), _utc_day_window(year, month - 1, day))

    for match in _MONTH_DAY.finditer(text):
        month = _month_index(match.group(1))
        if month is None:
            continue
        day = int(match.group(2))
        explicit = int(match.group(3)) if match.group(3) else None
        year = _year_for_day(month, day, now, explicit)
        consider(match.start(), len(match.group(0)), _utc_day_window(year, month, day))

    for match in _DAY_MONTH.finditer(text):
        day = int(match.group(1))
        month = _month_index(match.group(2))
        if month is None:
            continue
        explicit = int(match.group(3)) if match.group(3) else None
        year = _year_for_day(month, day, now, explicit)
        consider(match.start(), len(match.group(0)), _utc_day_window(year, month, day))

    for match in _IN_MONTH.finditer(text):
        month = _month_index(match.group(1))
        if month is None:
            continue
        explicit = int(match.group(2)) if match.group(2) else None
        year = _year_for_month(month, now, explicit)
        consider(match.start(), len(match.group(0)), _utc_month_window(year, month))

    for match in _MONTH_YEAR.finditer(text):
        month = _month_index(match.group(1))
        if month is None:
            continue
        consider(match.start(), len(match.group(0)), _utc_month_window(int(match.group(2)), month))

    day_start = _start_of_utc_day(now)
    week_start = _start_of_utc_week(now)
    consider(
        _cue_index(text, _CUE_YESTERDAY), len("yesterday"), _shift_days(day_start, -1, 1)
    )
    consider(_cue_index(text, _CUE_TODAY), len("today"), _shift_days(day_start, 0, 1))
    consider(_cue_index(text, _CUE_TOMORROW), len("tomorrow"), _shift_days(day_start, 1, 1))
    consider(_cue_index(text, _CUE_LAST_WEEK), len("last week"), _shift_days(week_start, -7, 7))
    consider(_cue_index(text, _CUE_THIS_WEEK), len("this week"), _shift_days(week_start, 0, 7))
    consider(_cue_index(text, _CUE_LAST_MONTH), len("last month"), _adjacent_month(now, -1))
    consider(_cue_index(text, _CUE_THIS_MONTH), len("this month"), _adjacent_month(now, 0))

    if not hits:
        return None
    hits.sort(key=lambda hit: (hit[0], -hit[1]))
    return hits[0][2]


def passes_window(when: float | None, window: Window | None) -> bool:
    """A window keeps only facts with an instant inside it (inclusive
    start, exclusive end); an undated instant never survives a window.
    No window keeps everything."""
    if window is None:
        return True
    return when is not None and window[0] <= when < window[1]


def _cue_index(text: str, pattern) -> int:
    """Offset of the cue's first occurrence, or -1 when the text lacks it.

    -1 rather than None is what makes the result directly comparable with a
    regex match's start, which is the value it competes with.
    """
    match = pattern.search(text)
    return match.start() if match else -1


def _month_index(word: str) -> int | None:
    """The zero-based month of a month name, or None if it is not one.

    Keyed on the first three letters alone, so "January", "Jan" and a
    fully-spelled name from any of the patterns all resolve alike.
    """
    return _MONTH_INDEX.get(word[:3])


def _year_for_month(month: int, now: float, explicit: int | None) -> int:
    """A bare month means this year when the month has started, else
    last year (the donor's missing-year rule against now)."""
    if explicit is not None:
        return explicit
    year = _utc_year(now)
    start = _rolled_utc_epoch(year, month, 1)
    return year if start is not None and start <= now else year - 1


def _year_for_day(month: int, day: int, now: float, explicit: int | None) -> int:
    """The year a bare month/day means: this one if it has started, else last.

    An explicit year wins outright. The rollover test asks whether the date's
    first instant is at or before now, so today's date stays in this year, and a
    date still ahead of now reads as last year. An impossible date such as
    February 30 still gets a year here; _utc_day_window refuses it afterwards.
    """
    if explicit is not None:
        return explicit
    year = _utc_year(now)
    start = _rolled_utc_epoch(year, month, day)
    return year if start is not None and start <= now else year - 1


def _utc_year(now: float) -> int:
    """The calendar year holding this epoch instant, read in UTC."""
    return datetime.fromtimestamp(now, tz=UTC).year


def _rolled_utc_epoch(year: int, month: int, day: int) -> float | None:
    """The donor's Date.UTC calendar: months roll (month 12 is next
    January) and a day is an offset from the month's first, so a day
    past the end spills into the next month. Years outside Python's
    calendar return None (invalid)."""
    year += month // 12
    month %= 12
    try:
        first = datetime(year, month + 1, 1, tzinfo=UTC)
    except ValueError:
        return None
    return first.timestamp() + (day - 1) * DAY_SECONDS


def _utc_day_window(year: int, month: int, day: int) -> Window | None:
    """One UTC day, when the calendar date is real: the roundtrip probe
    rejects rollovers like February 30 the way the donor's does."""
    if month < 0 or month > 11 or day < 1 or day > 31:
        return None
    start = _rolled_utc_epoch(year, month, day)
    if start is None:
        return None
    probe = datetime.fromtimestamp(start, tz=UTC)
    if (probe.year, probe.month, probe.day) != (year, month + 1, day):
        return None
    return (start, start + DAY_SECONDS)


def _utc_month_window(year: int, month: int) -> Window | None:
    """A whole month as [first instant, first of the next month), or None.

    month is zero-based, so 11 (December) ends at the next year's January 1.
    None when the month is out of range or either boundary falls outside
    Python's calendar.
    """
    if month < 0 or month > 11:
        return None
    start = _rolled_utc_epoch(year, month, 1)
    end = _rolled_utc_epoch(year, month + 1, 1)
    if start is None or end is None:
        return None
    return (start, end)


def _start_of_utc_day(now: float) -> float:
    """Midnight UTC of the day containing now, as epoch seconds."""
    moment = datetime.fromtimestamp(now, tz=UTC)
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC).timestamp()


def _start_of_utc_week(now: float) -> float:
    """Monday of the week: Python's weekday() counts days since Monday
    directly, which is exactly the donor's offset (a Sunday maps to 6,
    back into the previous week)."""
    day_start = _start_of_utc_day(now)
    since_monday = datetime.fromtimestamp(now, tz=UTC).weekday()
    return day_start - since_monday * DAY_SECONDS


def _shift_days(start: float, offset_days: int, length_days: int) -> Window:
    """A window of whole days beginning offset_days from start.

    Both counts are multiples of 86_400 seconds, so every boundary this returns
    is a UTC midnight and no local DST rule can shorten or lengthen the window.
    """
    begin = start + offset_days * DAY_SECONDS
    return (begin, begin + length_days * DAY_SECONDS)


def _adjacent_month(now: float, delta: int) -> Window | None:
    """The month shifted by delta from now's month (Date.UTC-style
    rolling through the year boundary)."""
    moment = datetime.fromtimestamp(now, tz=UTC)
    start = _rolled_utc_epoch(moment.year, moment.month - 1 + delta, 1)
    end = _rolled_utc_epoch(moment.year, moment.month + delta, 1)
    if start is None or end is None:
        return None
    return (start, end)


# -- the ranker -------------------------------------------------------------


def rank_hybrid(
    query: str,
    facts: list[Fact],
    links: dict[int, list[EntityLink]] | None,
    now: float,
    *,
    vector_scores: dict[int, float] | None = None,
    rrf_k: int = RRF_K,
    half_life_days: float = HALF_LIFE_DAYS,
) -> list[tuple[float, Fact]]:
    """The store's recall order, the donor's rankHybridFacts: keyword
    and graph lists fuse by reciprocal rank fusion, recency multiplies,
    a time window restricts and priors, and the final order is fused
    score descending, creation descending, id ascending. Facts without
    a signal never recall (silence is the designed empty); when a
    window is present, in-window facts recall on the prior alone.

    `vector_scores` is the semantic leg (ticket #95): fact id to cosine
    score, computed by the store from the query vector and the rows
    whose model and dimension match, exactly the donor's vectorScores.
    None or empty means no vector leg, and the output is then identical
    to the deterministic fusion in order and in score. The leg joins
    the fusion at unit weight.
    """
    if not query.strip() or not facts:
        return []
    tokens = meaningful_tokens(query)
    window = parse_time_window(query, now)

    keyword_ids = rank_ids(keyword_scores(facts, tokens))
    graph_ids = rank_ids(graph_scores(facts, links or {}, query, tokens))
    vector_ids = rank_ids(vector_scores or {})
    fused = fuse_parts(
        [
            (keyword_ids, KEYWORD_WEIGHT),
            (vector_ids, VECTOR_WEIGHT),
            (graph_ids, GRAPH_WEIGHT),
        ],
        rrf_k,
    )

    ranked: list[tuple[float, Fact]] = []
    for fact in facts:
        when = event_instant(fact.occurrence_ts, fact.created_ts)
        if not passes_window(when, window):
            continue
        fusion = fused.get(fact.id, 0.0)
        prior = TIME_PRIOR if window is not None else 0.0
        if fusion + prior <= 0:
            continue
        recency = recency_factor(when, now, half_life_days)
        ranked.append(((fusion + prior) * recency, fact))

    ranked.sort(key=lambda item: (-item[0], -item[1].created_ts, item[1].id))
    return ranked
