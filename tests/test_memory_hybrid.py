"""Hybrid recall arithmetic: tokens, entity tiers, fusion, recency, windows.

Pure functions, no I/O, the clock always passed in: the ranking must be
deterministic (same facts, same query, same now, same order, every
time). Everything here ports the donor's memory-bank sources exactly
(src/tokens.ts, src/names.ts, src/hybrid.ts, src/recall.ts,
src/time-window.ts): the fusion is reciprocal rank (k sixty, unit
weights), recency halves per thirty days with undated facts at zero,
and a time cue restricts recall to its window with a small prior for
the facts inside it. Small hand-computed cases pin every formula.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.memory.core import Fact
from agentdesk.memory.hybrid import (
    RRF_K,
    TIME_PRIOR,
    EntityLink,
    estimate_tokens,
    event_instant,
    fuse_parts,
    graph_scores,
    keyword_scores,
    meaningful_tokens,
    name_parts,
    normalize_name,
    parse_time_window,
    passes_window,
    rank_hybrid,
    rank_ids,
    recency_factor,
    score_entity_name,
    tokenize,
)

# A fixed now: Sunday 2026-11-15 at noon UTC. Weeks start Monday, so
# this week is Nov 9..15 inclusive and the window is [Nov 9, Nov 16).
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc).timestamp()
DAY = 86400.0


def _ts(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


def _fact(fact_id, text, created_ts=NOW, occurrence_ts=None):
    return Fact(
        id=fact_id,
        text=text,
        source="page",
        created_ts=created_ts,
        occurrence_ts=occurrence_ts,
    )


def _links(fact_entities):
    """fact id -> its entity links, for the graph leg."""
    out = {}
    for fact_id, entities in fact_entities.items():
        out[fact_id] = [
            EntityLink(id=eid, name=name, aliases=tuple(aliases))
            for eid, name, aliases in entities
        ]
    return out


# -- tokenization ---------------------------------------------------------


def test_tokenize_is_the_raw_donor_split():
    # Raw tokens: nothing is dropped, not even stopword-length or
    # single-character tokens (the meaningful filter is a separate step).
    assert tokenize("The Revenue Total is 220!") == [
        "the",
        "revenue",
        "total",
        "is",
        "220",
    ]
    assert tokenize("I AB") == ["i", "ab"]
    assert tokenize("") == []
    assert tokenize("... !!! ___") == []


def test_tokenize_normalizes_nfkc_before_splitting():
    # The fi ligature and fullwidth digits fold to their ASCII forms.
    assert tokenize("ﬁve ２２０") == ["five", "220"]


def test_meaningful_tokens_drop_stopwords_short_tokens_and_duplicates():
    # Two-character tokens stay (ab), stopwords and length-one go, and
    # first-seen order is preserved.
    assert meaningful_tokens("The the revenue is AB a 220 to in of") == [
        "revenue",
        "ab",
        "220",
    ]
    assert meaningful_tokens("") == []


def test_the_stopword_list_matches_the_donor():
    from agentdesk.memory.hybrid import STOPWORDS

    assert len(STOPWORDS) == 61
    for word in (
        "a",
        "an",
        "the",
        "and",
        "of",
        "is",
        "about",
        "into",
        "whom",
        "why",
    ):
        assert word in STOPWORDS
    assert "revenue" not in STOPWORDS
    assert "220" not in STOPWORDS


def test_estimate_tokens_rounds_up_four_characters_per_token():
    assert estimate_tokens("") == 0
    assert estimate_tokens("   ") == 0
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("  abcd  ") == 1  # trimmed before counting


# -- name normalization ---------------------------------------------------


def test_normalize_name_drops_case_punctuation_and_extra_spaces():
    assert normalize_name("  Acme Corp. ") == "acme corp"
    # The apostrophe vanishes; other punctuation becomes a space.
    assert normalize_name("O'Brien-Smith (Jr.)") == "obrien smith jr"
    assert normalize_name("ＡＣＭＥ") == "acme"  # NFKC fullwidth fold
    assert normalize_name("   ") == ""


def test_name_parts_split_the_normalized_name():
    assert name_parts("Acme Corp") == ["acme", "corp"]
    assert name_parts("   ") == []


# -- entity-name scoring tiers --------------------------------------------


def test_phrase_tier_scores_ten_plus_three_per_part():
    # The whole normalized name sits inside the query as a phrase.
    assert score_entity_name(
        "Acme Corp", [], "acme corp shipped widgets", {"acme", "corp", "shipped", "widgets"}
    ) == 10 + 2 * 3


def test_alias_phrase_beats_a_weaker_canonical_match():
    # Best across canonical and aliases: the alias hits the phrase tier.
    assert score_entity_name(
        "Acme", ["Acme Corp"], "acme corp", {"acme", "corp"}
    ) == 10 + 2 * 3


def test_all_parts_tier_scores_five_plus_two_per_part():
    # Every part appears in the query tokens but not as a phrase.
    assert score_entity_name(
        "Acme Corp", [], "corp acme deal", {"corp", "acme", "deal"}
    ) == 5 + 2 * 2


def test_partial_tier_scores_two_per_overlapping_part():
    assert score_entity_name("Acme Corp", [], "acme alone", {"acme", "alone"}) == 2


def test_short_parts_never_count_as_overlaps():
    # "jo" is under three characters, so only "ltd" overlaps: the
    # partial tier, not the all-parts tier (and the query is not the
    # name as a phrase, which would win the top tier instead).
    assert score_entity_name("Jo Ltd", [], "ltd jo filing", {"ltd", "jo", "filing"}) == 2


def test_phrase_needs_the_whole_name_not_a_prefix():
    # "acme corporation" contains "acme corpor..." but not the phrase
    # "acme corp" followed by a boundary.
    assert score_entity_name(
        "Acme Corp", [], "acme corporation", {"acme", "corporation"}
    ) == 2


def test_entity_name_of_no_overlap_is_zero():
    assert score_entity_name("Acme Corp", [], "nothing here", {"nothing", "here"}) == 0


# -- keyword leg ----------------------------------------------------------


def test_keyword_scores_count_meaningful_query_tokens_in_raw_fact_tokens():
    facts = [
        _fact(1, "The Revenue Total is 220"),
        _fact(2, "revenue only"),
        _fact(3, "nothing matches"),
    ]
    tokens = meaningful_tokens("revenue 220 total")
    assert keyword_scores(facts, tokens) == {1: 3, 2: 1}


def test_keyword_leg_matches_tokens_the_old_scorer_dropped():
    # The fact side is the raw token set: two-character and stopword
    # tokens count as hits even though the query side never produces
    # them as such (the query token "ab" is meaningful, length two).
    facts = [_fact(1, "AB test runs"), _fact(2, "a 220 note")]
    assert keyword_scores(facts, ["ab"]) == {1: 1}
    assert keyword_scores(facts, ["220"]) == {2: 1}


def test_keyword_scores_of_no_tokens_is_empty():
    facts = [_fact(1, "revenue is 220")]
    assert keyword_scores(facts, []) == {}


# -- graph leg ------------------------------------------------------------


def test_graph_scores_weight_a_matched_entitys_facts():
    facts = [_fact(1, "the board approved the budget"), _fact(2, "acme hired staff")]
    links = _links(
        {
            1: [(7, "Acme", [])],
            2: [(7, "Acme", [])],
        }
    )
    # "acme" as a phrase in the query: 10 + 1*3, added to both facts.
    assert graph_scores(facts, links, "acme", meaningful_tokens("acme")) == {1: 13, 2: 13}


def test_graph_scores_match_an_alias_too():
    facts = [_fact(1, "quarterly review moved")]
    links = _links({1: [(7, "Acme", ["Acme Industries"])]})
    # The alias "acme industries" hits the phrase tier: 10 + 2*3.
    assert graph_scores(facts, links, "acme industries", meaningful_tokens("acme industries")) == {
        1: 16
    }


def test_graph_scores_one_hop_seed_neighbor_facts_at_one():
    facts = [
        _fact(1, "the board approved the budget"),
        _fact(2, "the offsite is in may"),
        _fact(3, "payroll runs friday"),
    ]
    links = _links(
        {
            1: [(7, "Acme", []), (8, "Globex", [])],
            2: [(8, "Globex", [])],
            3: [(8, "Globex", [])],
        }
    )
    # Acme matches and scores fact 1 at 13. Globex was not named but
    # links to the scored fact, so its other facts seed at 1; fact 3
    # already has a direct score? No: fact 3 links only Globex, so it
    # seeds at 1 as well. A directly scored fact keeps its weight.
    scores = graph_scores(facts, links, "acme", meaningful_tokens("acme"))
    assert scores == {1: 13, 2: 1.0, 3: 1.0}


def test_graph_scores_of_no_matched_entity_is_empty():
    facts = [_fact(1, "the board approved the budget")]
    links = _links({1: [(7, "Acme", [])]})
    assert graph_scores(facts, links, "unrelated query", meaningful_tokens("unrelated query")) == {}
    assert graph_scores(facts, {}, "acme", meaningful_tokens("acme")) == {}


# -- rank ids and fusion --------------------------------------------------


def test_rank_ids_order_score_desc_then_id_asc():
    # Scores 2 tie between ids 1 and 3 (id ascending), then score 1.
    assert rank_ids({3: 2, 1: 2, 2: 1}) == [1, 3, 2]


def test_fuse_parts_contribution_is_weight_over_k_plus_rank_plus_one():
    fused = fuse_parts([([10, 11], 1.0), ([11, 12], 1.0)], RRF_K)
    assert fused[10] == pytest.approx(1 / 61)
    assert fused[11] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[12] == pytest.approx(1 / 62)


def test_fuse_parts_skips_zero_weights_and_honors_the_k_constant():
    assert fuse_parts([([5], 0.0), ([6], 2.0)], 1) == {6: pytest.approx(2 / 2)}


def test_fuse_parts_of_no_lists_is_empty():
    assert fuse_parts([], RRF_K) == {}


# -- recency --------------------------------------------------------------


def test_recency_halves_every_thirty_days():
    assert recency_factor(NOW, NOW) == 1.0
    assert recency_factor(NOW - 30 * DAY, NOW) == 0.5
    assert recency_factor(NOW - 60 * DAY, NOW) == 0.25
    assert recency_factor(NOW - 15 * DAY, NOW) == pytest.approx(0.5 ** 0.5)


def test_recency_of_a_future_instant_is_one_and_undated_is_zero():
    assert recency_factor(NOW + 10 * DAY, NOW) == 1.0
    assert recency_factor(None, NOW) == 0.0


def test_recency_honors_the_half_life_argument():
    assert recency_factor(NOW - 15 * DAY, NOW, half_life_days=15) == 0.5


# -- event instant --------------------------------------------------------


def test_event_instant_prefers_the_occurrence_over_creation():
    assert event_instant(5.0, 9.0) == 5.0
    assert event_instant(None, 9.0) == 9.0
    assert event_instant(None, None) is None


# -- the time window ------------------------------------------------------


def test_iso_day_window_is_that_utc_day():
    assert parse_time_window("notes from 2026-01-05", NOW) == (
        _ts(2026, 1, 5),
        _ts(2026, 1, 6),
    )


def test_iso_day_rejects_invalid_calendar_dates():
    assert parse_time_window("2026-02-30", NOW) is None
    assert parse_time_window("2026-13-01", NOW) is None


def test_month_day_resolves_the_missing_year_against_now():
    # March 5 of the current year is in the past: keep 2026.
    assert parse_time_window("march 5", NOW) == (_ts(2026, 3, 5), _ts(2026, 3, 6))
    # December 20 of the current year is in the future: fall back to 2025.
    assert parse_time_window("december 20", NOW) == (_ts(2025, 12, 20), _ts(2025, 12, 21))
    # December 31 resolves like any day: 2026 is not over yet, so 2025.
    assert parse_time_window("31st december", NOW) == (_ts(2025, 12, 31), _ts(2026, 1, 1))


def test_month_day_with_explicit_year_and_ordinals():
    assert parse_time_window("march 5, 2024", NOW) == (_ts(2024, 3, 5), _ts(2024, 3, 6))
    assert parse_time_window("5th march 2024", NOW) == (_ts(2024, 3, 5), _ts(2024, 3, 6))
    assert parse_time_window("MARCH 5 2024", NOW) == (_ts(2024, 3, 5), _ts(2024, 3, 6))
    assert parse_time_window("may 5th", NOW) == (_ts(2026, 5, 5), _ts(2026, 5, 6))


def test_leap_days_validate_like_any_calendar_date():
    assert parse_time_window("february 29 2028", NOW) == (_ts(2028, 2, 29), _ts(2028, 3, 1))
    assert parse_time_window("february 29 2027", NOW) is None
    assert parse_time_window("february 29", NOW) is None  # 2026 is no leap year
    assert parse_time_window("february 30", NOW) is None


def test_day_month_window_reads_day_first():
    assert parse_time_window("5 march", NOW) == (_ts(2026, 3, 5), _ts(2026, 3, 6))
    assert parse_time_window("21 March 2025", NOW) == (_ts(2025, 3, 21), _ts(2025, 3, 22))


def test_in_month_and_month_year_open_whole_months():
    assert parse_time_window("in march", NOW) == (_ts(2026, 3, 1), _ts(2026, 4, 1))
    assert parse_time_window("in march 2024", NOW) == (_ts(2024, 3, 1), _ts(2024, 4, 1))
    assert parse_time_window("june 2025", NOW) == (_ts(2025, 6, 1), _ts(2025, 7, 1))


def test_relative_day_cues_are_single_utc_days():
    assert parse_time_window("today", NOW) == (_ts(2026, 11, 15), _ts(2026, 11, 16))
    assert parse_time_window("yesterday", NOW) == (_ts(2026, 11, 14), _ts(2026, 11, 15))
    assert parse_time_window("tomorrow", NOW) == (_ts(2026, 11, 16), _ts(2026, 11, 17))


def test_week_cues_start_on_monday():
    # NOW is a Sunday: its week began Monday Nov 9 and ends Monday Nov 16.
    assert parse_time_window("this week", NOW) == (_ts(2026, 11, 9), _ts(2026, 11, 16))
    assert parse_time_window("last week", NOW) == (_ts(2026, 11, 2), _ts(2026, 11, 9))
    # A Monday now: its week is the seven days starting that day.
    monday = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc).timestamp()
    assert parse_time_window("this week", monday) == (_ts(2026, 11, 16), _ts(2026, 11, 23))


def test_month_cues_open_the_adjacent_month():
    assert parse_time_window("this month", NOW) == (_ts(2026, 11, 1), _ts(2026, 12, 1))
    assert parse_time_window("last month", NOW) == (_ts(2026, 10, 1), _ts(2026, 11, 1))


def test_a_query_without_a_cue_names_no_window():
    assert parse_time_window("revenue total", NOW) is None
    assert parse_time_window("", NOW) is None


def test_impossible_day_numbers_are_rejected():
    assert parse_time_window("99 march", NOW) is None
    assert parse_time_window("march 99", NOW) is None


def test_leftmost_cue_wins_even_when_a_later_cue_is_longer():
    assert parse_time_window("may 5 or 2026-01-05", NOW) == (_ts(2026, 5, 5), _ts(2026, 5, 6))
    assert parse_time_window("2026-01-05 in march", NOW) == (_ts(2026, 1, 5), _ts(2026, 1, 6))


def test_month_words_do_not_match_inside_larger_words():
    assert parse_time_window("mayor visited", NOW) is None
    assert parse_time_window("in mayor", NOW) is None


# -- window membership ----------------------------------------------------


def test_passes_window_is_half_open_and_drops_undated_instants():
    window = (100.0, 200.0)
    assert passes_window(100.0, window)  # inclusive start
    assert passes_window(199.0, window)
    assert not passes_window(200.0, window)  # exclusive end
    assert not passes_window(99.0, window)
    assert not passes_window(None, window)  # undated facts drop
    # No window keeps everything, undated instants included.
    assert passes_window(None, None)
    assert passes_window(50.0, None)


# -- the hybrid ranker ----------------------------------------------------


def test_rank_fuses_the_keyword_leg_with_recency():
    facts = [
        _fact(1, "revenue is 220"),
        _fact(2, "revenue is checked every monday"),
        _fact(3, "the meeting room is booked"),
    ]
    ranked = rank_hybrid("revenue 220", facts, {}, NOW)
    # Keyword scores 2 then 1; ranks 0 and 1 give 1/61 and 1/62; both
    # facts are created at NOW so recency is 1. Fact 3 has no signal.
    assert [fact.id for _s, fact in ranked] == [1, 2]
    assert ranked[0][0] == pytest.approx(1 / 61)
    assert ranked[1][0] == pytest.approx(1 / 62)


def test_rank_puts_the_newer_fact_first_at_equal_keyword_scores():
    facts = [
        _fact(1, "revenue is checked", created_ts=NOW - 30 * DAY),
        _fact(2, "revenue is filed", created_ts=NOW),
    ]
    ranked = rank_hybrid("revenue", facts, {}, NOW)
    # Equal keyword scores: the RRF ranks go to ids ascending, but the
    # older fact's recency halves and drops it below the newer one.
    assert [fact.id for _s, fact in ranked] == [2, 1]
    assert ranked[0][0] == pytest.approx(1 / 62)
    assert ranked[1][0] == pytest.approx(0.5 / 61)


def test_rank_recalls_a_linked_fact_through_a_paraphrased_query():
    # The fact shares no token with the query; the entity name carries it.
    facts = [_fact(1, "the board approved the budget")]
    links = _links({1: [(7, "Acme", [])]})
    ranked = rank_hybrid("acme", facts, links, NOW)
    assert [fact.id for _s, fact in ranked] == [1]
    # The phrase match gives fact 1 rank 0 of the graph leg; the fused
    # score is that rank's contribution (RRF weights rank, not the
    # leg's raw score magnitude).
    assert ranked[0][0] == pytest.approx(1 / 61)


def test_rank_one_hop_seeds_the_neighbours_other_facts():
    facts = [
        _fact(1, "the board approved the budget"),
        _fact(2, "the offsite is planned"),
    ]
    links = _links(
        {
            1: [(7, "Acme", []), (8, "Globex", [])],
            2: [(8, "Globex", [])],
        }
    )
    ranked = rank_hybrid("acme", facts, links, NOW)
    assert [fact.id for _s, fact in ranked] == [1, 2]
    # Fact 1 (score 13) holds rank 0 of the graph leg and the seeded
    # fact 2 (score 1) rank 1; the fused scores are those ranks'
    # contributions.
    assert ranked[0][0] == pytest.approx(1 / 61)
    assert ranked[1][0] == pytest.approx(1 / 62)


def test_rank_drops_out_of_window_facts_and_grants_the_in_window_prior():
    facts = [
        _fact(1, "sprint review happened", created_ts=_ts(2026, 11, 10)),
        _fact(2, "revenue archive", created_ts=_ts(2026, 11, 1)),
        _fact(3, "revenue report", created_ts=_ts(2026, 11, 12)),
    ]
    ranked = rank_hybrid("this week revenue", facts, {}, NOW)
    # The window is [Nov 9, Nov 16): fact 2 is outside and drops even
    # though its text matches the keyword. Facts 2 and 3 both match
    # "revenue", so the keyword ranks go 2 then 3 (id tie-break), which
    # makes fact 3's contribution 1/62. Fact 1 stays on the prior alone.
    assert [fact.id for _s, fact in ranked] == [3, 1]
    assert ranked[0][0] == pytest.approx((1 / 62 + TIME_PRIOR) * 0.5 ** (3.5 / 30))
    assert ranked[1][0] == pytest.approx(TIME_PRIOR * 0.5 ** (5.5 / 30))


def test_rank_orders_by_recency_when_the_window_prior_is_all_there_is():
    facts = [
        _fact(1, "sprint review happened", created_ts=_ts(2026, 11, 10)),
        _fact(2, "standup notes written", created_ts=_ts(2026, 11, 14)),
        _fact(3, "demo rehearsed twice", created_ts=_ts(2026, 11, 11)),
        _fact(4, "demo rehearsed again", created_ts=_ts(2026, 11, 11)),
    ]
    ranked = rank_hybrid("this week", facts, {}, NOW)
    # Fusion is equal (the prior alone); recency orders them and the
    # identical facts 3 and 4 fall back to id ascending.
    assert [fact.id for _s, fact in ranked] == [2, 3, 4, 1]


def test_rank_of_an_empty_query_or_no_facts_is_empty():
    assert rank_hybrid("   ", [_fact(1, "revenue")], {}, NOW) == []
    assert rank_hybrid("revenue", [], {}, NOW) == []


def test_rank_never_recalls_facts_without_a_signal():
    facts = [_fact(1, "the meeting room is booked")]
    assert rank_hybrid("revenue", facts, {}, NOW) == []


def test_rank_is_deterministic_across_repeated_calls():
    facts = [
        _fact(1, "revenue lives in the sales workbook"),
        _fact(2, "revenue is checked every monday", created_ts=NOW - 5 * DAY),
        _fact(3, "the offsite is planned"),
    ]
    links = _links({3: [(7, "Acme", [])]})
    first = rank_hybrid("revenue acme", facts, links, NOW)
    for _ in range(5):
        assert rank_hybrid("revenue acme", facts, links, NOW) == first
