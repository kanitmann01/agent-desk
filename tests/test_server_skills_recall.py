"""The saved-skill run over HTTP: the bounded facts block, ranked
against the skill's own prompt (ticket #169).

A skill is the assistant's saved ask, so its run recalls facts on the
same terms the assistant panel does: the block rides first in the
research prompt when the skill's prompt overlaps a stored fact, stays
absent when nothing ranks, and a locked bank still answers with no
block, because the run is never worth breaking over recall.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.memory.crypto import load_key
from agentdesk.memory.store import MemoryStore


KEY = load_key(bytes(range(32)))


class CaptureLlm:
    """The stub adapter the assistant tests use: records every prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "A short answer."


@pytest.fixture()
def env():
    booted = server_harness.Booted(llm=CaptureLlm())
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _add_fact(env, auth, text):
    status, _h, _b = env.post_json("/memory/add", {"text": text}, auth)
    assert status == 201


def _activate_skill(env, prompt):
    skill = env.server.skills.activate("Revenue note", "Summarizes the revenue.", prompt)
    return skill["id"]


def _run_skill(env, auth, skill_id):
    status, _h, body = env.post_json(f"/skills/{skill_id}/run", {}, auth)
    return status, json.loads(body)


def test_a_skill_prompt_overlapping_a_fact_carries_the_block(env, auth):
    _add_fact(env, auth, "revenue is 220")
    skill_id = _activate_skill(env, "What is the revenue this week?")
    status, payload = _run_skill(env, auth, skill_id)
    assert status == 200 and payload["status"] == "ok"
    prompt = env.server.llm.prompts[0]
    assert "Known facts about the user" in prompt
    assert "- revenue is 220" in prompt
    # The block rides first, ahead of the widget context, like the
    # assistant's.
    assert "revenue" in prompt.split("Known facts")[1].split("Connected widget")[0]


def test_a_skill_prompt_with_no_overlapping_facts_sends_no_block(env, auth):
    _add_fact(env, auth, "revenue is 220")
    skill_id = _activate_skill(env, "Prepare my meeting notes for the board")
    status, payload = _run_skill(env, auth, skill_id)
    assert status == 200 and payload["status"] == "ok"
    assert "Known facts about the user" not in env.server.llm.prompts[0]


def test_a_locked_memory_store_leaves_the_skill_run_working(tmp_path):
    db = tmp_path / "memory.sqlite3"
    key_path = tmp_path / "memory.key"
    first = sqlite3.connect(str(db), check_same_thread=False)
    seeded = MemoryStore(first, time.time, key=KEY)
    seeded.add("revenue is 220", source="page")
    first.close()
    conn = sqlite3.connect(str(db), check_same_thread=False)
    store = MemoryStore(conn, time.time, key_path=key_path)
    assert store.locked_cause is not None
    booted = server_harness.Booted(memory_store=store, llm=CaptureLlm())
    original_close = booted.close

    def close():
        original_close()
        conn.close()

    booted.close = close
    try:
        auth = booted.exchange()
        skill = booted.server.skills.activate(
            "Revenue note", "Summarizes the revenue.", "What is the revenue?"
        )
        status, _h, body = booted.post_json(f"/skills/{skill['id']}/run", {}, auth)
        assert status == 200
        assert json.loads(body)["status"] == "ok"
        assert "Known facts" not in booted.server.llm.prompts[0]
    finally:
        booted.close()
