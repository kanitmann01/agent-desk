"""The recommend step in the agent loop (spec 016 section 6.2, tickets 05-07).

The builder is covered on its own; this proves the loop actually calls it in
a pass, through the same HTTP surfaces a user hits. Recommendations are kept
off until the fact is saved, so the card can only come from the pass.
"""

import datetime
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import server_harness


def _wait_until(predicate, timeout: float = 5.0, step: float = 0.02) -> bool:
    """Poll a predicate with short sleeps until it holds or the deadline passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def _get_json(env, auth, path):
    status, _headers, body = env.request("GET", path, auth)
    assert status == 200, body
    return json.loads(body)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture
def auth(env):
    return env.exchange()


def test_a_pass_builds_the_deadline_recommendation(env, auth):
    # The fact arrives while the feature is off, so no card can appear from
    # the memory write alone.
    env.server.settings.set("recommendations", False)
    target = datetime.date.today() + datetime.timedelta(days=10)
    if (target.month, target.day) == (2, 29):
        # The deadline rules deliberately skip Feb 29.
        target += datetime.timedelta(days=1)
    text = f"The Harborlight renewal is due {target:%B} {target.day}."
    status, _headers, body = env.post_json("/memory/add", {"text": text}, auth)
    assert status == 201, body
    fact = json.loads(body)
    assert _get_json(env, auth, "/api/dashboard")["recommendations"] == []

    # Switch it on through the store, not the route: the route runs its own
    # refresh, and this test is about the pass.
    env.server.settings.set("recommendations", True)
    status, _headers, body = env.post_json("/api/agent-loop/run", {}, auth)
    assert status == 200, body
    assert _wait_until(lambda: env.server.agent_loop.status()["running"] is False)

    steps = env.server.agent_loop.status()["lastSteps"]
    row = next(step for step in steps if step["name"] == "recommend")
    assert row["ok"] is True
    assert row["note"].startswith("added 1")

    recs = _get_json(env, auth, "/api/dashboard")["recommendations"]
    card = next(rec for rec in recs if rec["due"] == target.isoformat())
    assert fact["id"] in card["cites"]


def test_the_rank_step_pays_the_ledger_and_undo_restores_the_card(env, auth, monkeypatch):
    """The ledger toll on the rank step (spec 023), over the user's surfaces.

    One Run-now pass ranks the waiting recommendation through the stubbed
    endpoint reply; the change must appear in the ledger with its Undo, and
    Undo must put the rule's why line back on the card.
    """
    from agentdesk.recommend import rank as rank_module

    target = datetime.date.today() + datetime.timedelta(days=10)
    if (target.month, target.day) == (2, 29):
        target += datetime.timedelta(days=1)
    text = f"The Harborlight renewal is due {target:%B} {target.day}."
    status, _headers, body = env.post_json("/memory/add", {"text": text}, auth)
    assert status == 201, body
    rule_row = next(rec for rec in _get_json(env, auth, "/api/dashboard")["recommendations"]
                    if rec["due"] == target.isoformat())
    assert rule_row["whySource"] == "rule"

    model_why = "Renewal is close and it is your largest account."

    def stub_chat(prompt):
        """Score every waiting recommendation above the threshold."""
        return json.dumps([
            {"id": card.id, "score": 9, "why": model_why}
            for card in env.server.inbox.waiting()
            if (card.meta or {}).get("recommendation")
        ])

    monkeypatch.setattr(rank_module, "settings_chat", lambda settings: stub_chat)
    status, _headers, body = env.post_json("/api/agent-loop/run", {}, auth)
    assert status == 200, body
    assert _wait_until(lambda: env.server.agent_loop.status()["running"] is False)

    ranked = next(rec for rec in _get_json(env, auth, "/api/dashboard")["recommendations"]
                  if rec["due"] == target.isoformat())
    assert ranked["whySource"] == "model"
    assert ranked["why"] == model_why

    # The change is in the ledger, undoable, and Undo restores the rule's why.
    entry = next(row for row in _get_json(env, auth, "/api/ledger")["entries"]
                 if row["action"] == "recommend.ranked")
    assert entry["undoable"] is True
    stored = env.server.ledger.get(entry["id"])
    assert stored.undo_kind == "card-ranked"
    assert stored.actor == "agent"
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": entry["id"]}, auth)
    assert status == 200, body

    restored = next(rec for rec in _get_json(env, auth, "/api/dashboard")["recommendations"]
                    if rec["due"] == target.isoformat())
    assert restored["whySource"] == "rule"
    assert restored["why"] == rule_row["why"]
    undone = env.server.ledger.get(entry["id"])
    assert undone.undone_by is not None
    assert env.server.ledger.get(undone.undone_by).undoes == entry["id"]
