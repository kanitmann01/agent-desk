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
    text = f"The Halvorsen renewal is due {target:%B} {target.day}."
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
