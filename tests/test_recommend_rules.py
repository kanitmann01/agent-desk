"""The deadline rule: saved dates become recommendation candidates.

The rule reads facts only; no inbox, no settings, no clock of its own. These
tests pin its forward resolution (bare dates roll to the next occurrence),
its horizon window, and the card copy it hands the builder.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agentdesk.memory.core import Fact
from agentdesk.recommend.rules import Candidate, deadline_candidates
from agentdesk.server.demo_data import SAMPLE_MEMORY_SOURCE

NOV_20 = datetime(2026, 11, 20, 9, 0)


def _fact(fact_id: int, text: str, *, source: str = "page", created: datetime | None = None) -> Fact:
    """One stored fact, created at a fixed local time unless told otherwise."""
    created_at = created or datetime(2026, 11, 3, 12, 0)
    return Fact(id=fact_id, text=text, source=source, created_ts=created_at.timestamp())


def _dates(candidates: list[Candidate]) -> list[str]:
    """The resolved day of each candidate, as an ISO date string."""
    return [
        datetime.fromtimestamp(candidate.due_ts).date().isoformat()
        for candidate in candidates
    ]


@pytest.mark.parametrize(
    "text, horizon_days, expected_day, expected_days",
    [
        ("Sign the renewal before December 15.", 30, "2026-12-15", 25),
        ("The contract is due 2026-12-01.", 30, "2026-12-01", 11),
        ("January 5 kickoff with the client.", 60, "2027-01-05", 46),
        ("Board review on 15 December.", 30, "2026-12-15", 25),
        ("Delivery on Dec 15, 2027.", 500, "2027-12-15", 390),
    ],
)
def test_deadline_forward_resolution(text, horizon_days, expected_day, expected_days):
    candidates = deadline_candidates(
        [_fact(7, text)], set(), {}, NOV_20, horizon_days,
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.key == f"deadline:7:{expected_day}"
    assert candidate.cites == (7,)
    assert candidate.due_ts == datetime.fromisoformat(expected_day).timestamp()
    assert f"(in {expected_days} days)" in candidate.title


def test_deadline_in_the_past_rolls_forward():
    # The same bare date on the day after it passed names next year's
    # occurrence, which is outside a short horizon, so nothing is emitted.
    now = datetime(2026, 12, 16, 9, 0)
    assert deadline_candidates([_fact(1, "Renewal due December 15.")], set(), {}, now, 30) == []
    next_year = deadline_candidates([_fact(1, "Renewal due December 15.")], set(), {}, now, 400)
    assert _dates(next_year) == ["2027-12-15"]


def test_deadline_and_tomorrow_wording():
    today = datetime(2026, 12, 15, 9, 0)
    candidates = deadline_candidates([_fact(2, "Renewal due December 15.")], set(), {}, today, 30)
    assert candidates[0].title.endswith("(today)")
    assert candidates[0].why == "You told the desk this deadline; it is today."
    tomorrow = datetime(2026, 12, 14, 9, 0)
    candidates = deadline_candidates([_fact(2, "Renewal due December 15.")], set(), {}, tomorrow, 30)
    assert candidates[0].title.endswith("(tomorrow)")
    assert candidates[0].why == "You told the desk this deadline; it is tomorrow."


def test_february_29_skips_non_leap_years():
    # 2027 is not a leap year; the next real February 29 is 2028.
    text = "Leap review on February 29."
    assert deadline_candidates([_fact(3, text)], set(), {}, NOV_20, 30) == []
    candidates = deadline_candidates([_fact(3, text)], set(), {}, NOV_20, 900)
    assert _dates(candidates) == ["2028-02-29"]


def test_superseded_facts_are_ignored():
    facts = [_fact(4, "Renewal due December 15."), _fact(5, "Renewal due December 20.")]
    candidates = deadline_candidates(facts, {4}, {}, NOV_20, 30)
    assert [candidate.cites for candidate in candidates] == [(5,)]


def test_entity_name_becomes_the_subject():
    candidates = deadline_candidates(
        [_fact(6, "Renewal due December 15.")], set(), {6: "Halvorsen Freight"}, NOV_20, 30,
    )
    assert candidates[0].title.startswith("Halvorsen Freight: December 15 (in 25 days)")


def test_fact_text_cut_at_48_becomes_the_subject():
    text = "The Halvorsen Freight renewal agreement has to be signed before December 15."
    candidates = deadline_candidates([_fact(8, text)], set(), {}, NOV_20, 30)
    assert candidates[0].title.startswith(text[:48] + ": December 15")


def test_one_candidate_per_fact_and_day():
    text = "Review the renewal on December 15 and again on 15 December."
    candidates = deadline_candidates([_fact(9, text)], set(), {}, NOV_20, 30)
    assert len(candidates) == 1
    assert candidates[0].key == "deadline:9:2026-12-15"


def test_card_copy_quotes_the_fact_and_says_when_it_was_saved():
    fact = _fact(10, "Renewal due December 15.")
    candidate = deadline_candidates([fact], set(), {}, NOV_20, 30)[0]
    assert candidate.body == '"Renewal due December 15."\nSaved Nov 3'
    assert candidate.rule == "deadline"
    assert candidate.href == "/agents"
    assert candidate.action_label == "Open Agents"
    assert candidate.sample is False


def test_sample_source_marks_the_candidate():
    sample = _fact(11, "Renewal due December 15.", source=SAMPLE_MEMORY_SOURCE)
    page = _fact(12, "Review due December 16.")
    candidates = {
        candidate.cites[0]: candidate
        for candidate in deadline_candidates([sample, page], set(), {}, NOV_20, 30)
    }
    assert candidates[11].sample is True
    assert candidates[12].sample is False


def test_undated_facts_emit_nothing():
    assert deadline_candidates([_fact(13, "The renewal is still open.")], set(), {}, NOV_20, 30) == []
