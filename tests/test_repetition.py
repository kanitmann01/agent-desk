"""Repetition detector and skills tests.

Clustering and the consolidation run run on fakes and a frozen clock;
the HTTP-seam tests walk ask-log-consolidate-accept-run-undo end to end.
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.inbox.store import InboxStore
from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.cluster import cluster_requests, pattern_hash, similarity
from agentdesk.repetition.service import Consolidator
from agentdesk.repetition.skills import SkillStore, render_skill_md

NOW = datetime(2026, 11, 11, 9, 0, 0).astimezone()

SIMILAR_ASKS = [
    "What changed in the EU channel this week?",
    "what changed in the EU channel?",
    "What changed in the EU channel since Monday?",
    "Tell me what changed in the EU channel",
    "What changed in the EU channel today?",
]
DIFFERENT_ASK = "Prepare my meeting notes for the board"


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance_to(self, when: datetime) -> None:
        self.now = when.timestamp()


def make_setup(start: datetime = NOW):
    clock = FakeClock(start)
    activity = ActivityLog(sqlite3.connect(":memory:", check_same_thread=False), clock)
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    skills = SkillStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    consolidator = Consolidator(activity, inbox, skills, clock)
    return clock, activity, inbox, skills, consolidator


def test_clustering_groups_similar_shapes_and_separates_different():
    texts = SIMILAR_ASKS + [DIFFERENT_ASK]
    clusters = cluster_requests(texts)
    big = max(clusters, key=len)
    assert len(big) == 5
    different_index = texts.index(DIFFERENT_ASK)
    assert different_index not in big


def test_similarity_is_broad_enough_for_wording_variance():
    assert similarity(SIMILAR_ASKS[0], SIMILAR_ASKS[1]) >= 0.6
    assert similarity(SIMILAR_ASKS[0], DIFFERENT_ASK) < 0.6


def test_five_similar_asks_propose_exactly_once(tmp_path):
    clock, activity, inbox, skills, consolidator = make_setup()
    for text in SIMILAR_ASKS:
        activity.record("research", text)
    result = consolidator.consolidate(NOW)
    assert result["proposed"] is True
    assert result["count"] == 5
    cards = [c for c in inbox.waiting() if c.kind == "skill_proposal"]
    assert len(cards) == 1
    # A second run does not double-propose the same pattern.
    assert consolidator.consolidate(NOW)["proposed"] is False


def test_four_similar_asks_do_not_propose(tmp_path):
    clock, activity, inbox, skills, consolidator = make_setup()
    for text in SIMILAR_ASKS[:4]:
        activity.record("research", text)
    assert consolidator.consolidate(NOW)["proposed"] is False
    assert inbox.waiting() == []


def test_proposal_carries_pattern_count_and_honest_body(tmp_path):
    clock, activity, inbox, skills, consolidator = make_setup()
    for text in SIMILAR_ASKS:
        activity.record("research", text)
    consolidator.consolidate(NOW)
    card = next(c for c in inbox.waiting() if c.kind == "skill_proposal")
    assert "5th time" in card.origin
    assert pattern_hash(SIMILAR_ASKS[0]) == card.meta["patternHash"]
    assert "would" in card.body and "will not" in card.body


def test_dismissed_pattern_cools_down_but_new_pattern_can_propose(tmp_path):
    clock, activity, inbox, skills, consolidator = make_setup()
    for text in SIMILAR_ASKS:
        activity.record("research", text)
    result = consolidator.consolidate(NOW)
    card = inbox.get(result["cardId"])
    inbox.dismiss(card.id)
    consolidator.dismiss_cooldown(card.meta["patternHash"])

    clock.advance_to(NOW + timedelta(days=1))
    assert consolidator.consolidate(NOW + timedelta(days=1))["proposed"] is False

    # A genuinely different pattern is not suppressed by the cooldown.
    for text in [DIFFERENT_ASK] * 5:
        activity.record("assistant", text)
    later = NOW + timedelta(days=2)
    result = consolidator.consolidate(later)
    assert result["proposed"] is True and result["pattern"] != card.meta["patternHash"]


def test_cooldown_expires_after_fourteen_days(tmp_path):
    clock, activity, inbox, skills, consolidator = make_setup()
    for text in SIMILAR_ASKS:
        activity.record("research", text)
    result = consolidator.consolidate(NOW)
    card = inbox.get(result["cardId"])
    inbox.dismiss(card.id)
    consolidator.dismiss_cooldown(card.meta["patternHash"])
    # Accept removes the card from waiting+dismissed, so the cooldown is
    # what keeps it quiet; after 14 days the same pattern may propose again.
    inbox.accept(card.id)
    clock.advance_to(NOW + timedelta(days=15))
    again = consolidator.consolidate(NOW + timedelta(days=15))
    assert again["proposed"] is True


def test_skill_md_matches_agentskills_shape_and_limits():
    markdown = render_skill_md("EU Channel Delta", "Summarizes the EU channel changes.", "What changed in the EU channel?")
    assert markdown.startswith("---\nname: eu-channel-delta\n")
    assert "description: Summarizes the EU channel changes." in markdown
    frontmatter = markdown.split("---")[1]
    for line in frontmatter.strip().splitlines():
        if line.startswith("name:"):
            assert len(line) - len("name: ") <= 64
        if line.startswith("description:"):
            assert len(line) - len("description: ") <= 1024


def test_accept_activate_run_undo_over_http(tmp_path):
    stub_reply = json.dumps({"summary": "Five of nine partners updated.", "sources": ["memo.pdf"]})

    class Stub:
        last_prompt = ""

        def __call__(self, prompt):
            Stub.last_prompt = prompt
            return stub_reply

    clock = FakeClock(NOW)
    activity = ActivityLog(sqlite3.connect(":memory:", check_same_thread=False), clock)
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    skills = SkillStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    booted = server_harness.Booted(
        activity_log=activity, inbox_store=inbox, skill_store=skills, llm=Stub()
    )
    try:
        auth = booted.exchange()
        for text in SIMILAR_ASKS:
            booted.post_json("/research", {"question": text}, auth)
        result = json.loads(booted.post_json("/inbox/consolidate", {}, auth)[2])
        assert result["proposed"] is True
        card = inbox.get(result["cardId"])

        # Accepting the proposal activates the skill.
        status, _h, _b = booted.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
        assert status == 200
        active = skills.active()
        assert len(active) == 1 and active[0]["prompt"] == SIMILAR_ASKS[0]

        # The one-click action produces the expected result from the stub.
        status, _h, body = booted.post_json(f"/skills/{active[0]['id']}/run", {}, auth)
        payload = json.loads(body)
        assert status == 200 and payload["status"] == "ok"
        assert "Five of nine" in payload["summary"]

        # Undo restores the prior state: inactive, and running is refused.
        status, _h, _b = booted.post_json(f"/skills/{active[0]['id']}/undo", {}, auth)
        assert status == 200
        assert skills.active() == []
        assert booted.post_json(f"/skills/{active[0]['id']}/run", {}, auth)[0] == 409
        history = skills.history(active[0]["id"])
        assert [h["active"] for h in history] == [True, False]
    finally:
        booted.close()


def test_activity_log_is_visible_in_settings(env_fixture=None):
    clock = FakeClock(NOW)
    activity = ActivityLog(sqlite3.connect(":memory:", check_same_thread=False), clock)
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    skills = SkillStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    booted = server_harness.Booted(activity_log=activity, inbox_store=inbox, skill_store=skills)
    try:
        auth = booted.exchange()
        booted.post_json("/research", {"question": "What changed in the EU channel?"}, auth)
        status, _h, body = booted.request("GET", "/settings", auth)
        page = body.decode("utf-8")
        assert status == 200
        assert "Activity log" in page
        assert "What changed in the EU channel?" in page
        # The SKILL.md endpoint serves the agentskills-shaped document.
        skills.activate("test skill", "A test.", "a prompt")
        skill_id = skills.active()[0]["id"]
        status, _h, body = booted.request("GET", f"/skills/{skill_id}/skill.md", auth)
        assert status == 200
        assert body.decode("utf-8").startswith("---\nname: test-skill\n")
    finally:
        booted.close()
