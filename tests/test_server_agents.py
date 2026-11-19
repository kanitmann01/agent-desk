"""The agents surface over HTTP: recall into one prompt, one endpoint
call, the honest run row, and the no-JavaScript page.

The seam is the booted server (the house rule): the fake endpoint
client is injected the way the assistant tests inject theirs, facts are
added over the memory routes, and every assertion reads the wire, the
injected stores or the captured prompts.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.llm import LlmUnavailable, chat_client
from agentdesk.memory.crypto import load_key
from agentdesk.memory.store import MemoryStore


class CaptureLlm:
    """The stub adapter the agent tests use: records every prompt."""

    def __init__(self, reply: str = "A plain answer.") -> None:
        self.prompts = []
        self.reply = reply

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


SLIDES_REPLY = json.dumps(
    {"title": "Q3 Review", "slides": [{"title": "Revenue", "bullets": ["revenue is 220"]}]}
)


@pytest.fixture()
def env():
    booted = server_harness.Booted(llm=CaptureLlm(reply=SLIDES_REPLY))
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _add_fact(env, auth, text):
    status, _h, body = env.post_json("/memory/add", {"text": text}, auth)
    assert status == 201
    return json.loads(body)


def _run(env, auth, brief="the Q3 review should cover revenue", agent="presentation"):
    return env.post_json("/agents/run", {"agent": agent, "brief": brief}, auth)


def _runs(env):
    return env.server.agents.recent()


def _audit_rows(env, action):
    return [e for e in audit_store.entries(env.server.audit_conn) if e["action"] == action]


# -- the run --------------------------------------------------------------


def test_a_run_creates_an_ok_row_whose_receipt_lists_the_recalled_facts(env, auth):
    _add_fact(env, auth, "revenue is 220")
    status, _h, body = _run(env, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["artifact"]["kind"] == "slides"
    assert payload["artifact"]["title"] == "Q3 Review"
    assert [row["text"] for row in payload["facts"]] == ["revenue is 220"]
    stored = _runs(env)
    assert len(stored) == 1
    assert stored[0]["status"] == "ok"
    assert stored[0]["facts"] == payload["facts"]


def test_the_prompt_carries_the_bounded_block_when_facts_overlap_the_brief(env, auth):
    _add_fact(env, auth, "revenue is 220")
    _run(env, auth)
    prompt = env.server.llm.prompts[0]
    assert "Known facts about the user" in prompt
    assert "- revenue is 220" in prompt
    # The query ranked the fact: agent name joined to the brief.
    assert "the Q3 review should cover revenue" in prompt


def test_without_overlap_the_receipt_says_used_nothing_and_the_prompt_carries_no_block(env, auth):
    _add_fact(env, auth, "the meeting room is booked")
    status, _h, body = _run(env, auth, brief="q3 business review")
    payload = json.loads(body)
    assert status == 200
    assert payload["facts"] == []
    assert "Known facts about the user" not in env.server.llm.prompts[0]
    status, _h, page = env.request("GET", "/agents", auth)
    assert b"used nothing" in page


# -- honest degradation ----------------------------------------------------


def test_the_endpoint_switched_off_records_a_degraded_run_with_the_named_cause(env, auth):
    env.server.settings.set("endpoint_enabled", False)
    status, _h, body = _run(env, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "degraded"
    assert "turned off in settings" in payload["cause"]
    assert payload["artifact"] is None
    assert env.server.llm.prompts == []
    rows = _runs(env)
    assert len(rows) == 1
    assert rows[0]["status"] == "degraded"
    assert "turned off in settings" in rows[0]["cause"]


def test_an_unconfigured_endpoint_degrades_with_the_adapter_cause(env, auth):
    env.server.llm = chat_client("", "k", "m")
    status, _h, body = _run(env, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "degraded"
    assert payload["cause"] == "no corporate endpoint configured"
    assert _runs(env)[0]["artifact"] is None


def test_a_failing_endpoint_degrades_with_its_named_cause(env, auth):
    def broken(prompt):
        raise LlmUnavailable("the endpoint did not answer: boom")

    env.server.llm = broken
    status, _h, body = _run(env, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "degraded"
    assert payload["cause"] == "the endpoint did not answer: boom"


# -- the page --------------------------------------------------------------


def test_the_agents_page_renders_roster_and_history_as_plain_forms(env, auth):
    _add_fact(env, auth, "revenue is 220")
    _run(env, auth)
    _run(env, auth, brief="q3 business review")
    status, _h, body = env.request("GET", "/agents", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "Presentation" in page
    assert 'action="/agents/run"' in page
    assert 'name="brief"' in page
    assert 'href="/agents"' in page
    # The history: newest first, with the receipt and the artifact.
    assert "the Q3 review should cover revenue" in page
    assert "- revenue is 220" in page or "revenue is 220" in page
    assert "Q3 Review" in page
    assert "used nothing" in page


def test_model_output_is_escaped_never_raw_html(env, auth):
    hostile = json.dumps(
        {"title": "<script>alert(1)</script>", "slides": [{"title": "x", "bullets": ["<img src=x>"]}]}
    )
    env.server.llm = CaptureLlm(reply=hostile)
    _run(env, auth)
    status, _h, body = env.request("GET", "/agents", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "<img src=x>" not in page


def test_the_empty_page_names_the_roster_and_honest_empties(env, auth):
    status, _h, body = env.request("GET", "/agents", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "No runs yet" in page
    assert "Presentation" in page


# -- the sealed bank -------------------------------------------------------


KEY = load_key(bytes(range(32)))


def test_a_locked_memory_bank_still_runs_with_no_block(tmp_path):
    db = tmp_path / "memory.sqlite3"
    seeded = MemoryStore(
        sqlite3.connect(str(db), check_same_thread=False), time.time, key=KEY
    )
    seeded.add("revenue is 220", source="page")
    seeded.conn.close()
    locked = MemoryStore(
        sqlite3.connect(str(db), check_same_thread=False), time.time,
        key_path=tmp_path / "memory.key",
    )
    assert locked.locked_cause is not None
    booted = server_harness.Booted(memory_store=locked, llm=CaptureLlm(reply=SLIDES_REPLY))
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/agents/run",
            {"agent": "presentation", "brief": "the Q3 review should cover revenue"},
            auth,
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "ok"
        assert payload["facts"] == []
        assert "Known facts about the user" not in booted.server.llm.prompts[0]
    finally:
        booted.close()


# -- the form and the refusals ---------------------------------------------


def test_a_form_post_redirects_back_to_the_agents_page(env, auth):
    body = "agent=presentation&brief=the+Q3+review".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, headers_out, _b = env.request("POST", "/agents/run", headers, body)
    assert status == 303
    assert headers_out["Location"] == "/agents"
    assert len(_runs(env)) == 1


def test_an_unknown_agent_id_is_refused_with_a_named_error(env, auth):
    status, _h, body = env.post_json(
        "/agents/run", {"agent": "chef", "brief": "cook"}, auth
    )
    assert status == 400
    assert "unknown agent" in json.loads(body)["error"]
    assert _runs(env) == []


def test_a_blank_brief_is_refused(env, auth):
    status, _h, body = env.post_json(
        "/agents/run", {"agent": "presentation", "brief": "   "}, auth
    )
    assert status == 400
    assert "brief" in json.loads(body)["error"]


def test_an_oversize_brief_is_refused(env, auth):
    status, _h, body = env.post_json(
        "/agents/run", {"agent": "presentation", "brief": "x" * 401}, auth
    )
    assert status == 400
    assert "400" in json.loads(body)["error"]


def test_the_agents_routes_require_a_session(env):
    status, _h, _b = env.post_json(
        "/agents/run", {"agent": "presentation", "brief": "x"}, env.host_header()
    )
    assert status == 401
    status, _h, _b = env.request("GET", "/agents", env.host_header())
    assert status == 401


# -- feedback: how a run landed becomes a reviewable memory fact ------------

# A declarative sentence the deterministic rules retain (it names Dana),
# so the capture tests never depend on an endpoint answering.
FEEDBACK = "My manager Dana prefers concise slide decks."


def _post_feedback(env, auth, run_id, text):
    return env.post_json(f"/agents/runs/{run_id}/feedback", {"feedback": text}, auth)


def _loop(env, auth):
    status, _h, body = env.request("GET", "/api/memory/loop", auth)
    assert status == 200
    return json.loads(body)


def test_posting_feedback_stages_one_agents_channel_card_built_from_the_own_words(env, auth):
    _run(env, auth)  # an ok run, so the transcript carries a real artifact
    run_id = _runs(env)[0]["id"]
    env.server.settings.set("endpoint_enabled", False)  # the rules read the feedback
    status, _h, body = _post_feedback(env, auth, run_id, FEEDBACK)
    assert status == 200
    payload = json.loads(body)
    assert payload["feedback"] == FEEDBACK and payload["feedbackTs"] is not None
    state = _loop(env, auth)
    [candidate] = state["candidates"]
    assert candidate["channel"] == "agents" and candidate["channelLabel"] == "Agents"
    assert candidate["method"] == "rules" and candidate["text"] == FEEDBACK
    # The excerpt is the run transcript: agent, brief, artifact, feedback.
    excerpt = candidate["excerpt"]["text"]
    assert "the Q3 review should cover revenue" in excerpt
    assert "Q3 Review" in excerpt
    assert FEEDBACK in excerpt
    # The card's own origin copy names the channel, like every other origin.
    [card] = env.server.inbox.waiting()
    assert "Agents" in card.origin
    # The feedback is stored on the run, timestamped.
    stored = _runs(env)[0]
    assert stored["feedback"] == FEEDBACK and stored["feedbackTs"] is not None


def test_feedback_becomes_a_fact_the_next_run_recalls(env, auth):
    _run(env, auth, brief="a deck for the Q3 business review")
    run_id = _runs(env)[0]["id"]
    env.server.settings.set("endpoint_enabled", False)
    status, _h, _b = _post_feedback(env, auth, run_id, FEEDBACK)
    assert status == 200
    env.server.settings.set("endpoint_enabled", True)
    [candidate] = _loop(env, auth)["candidates"]
    status, _h, _b = env.post_json(
        f"/inbox/cards/{candidate['cardId']}/accept", {}, auth
    )
    assert status == 200
    state = _loop(env, auth)
    [fact] = state["facts"]
    assert fact["text"] == FEEDBACK
    assert fact["origin"]["id"] == "review:agents"
    assert fact["origin"]["label"] == "Agents"
    # The next brief overlaps the feedback, and the receipt names the fact.
    status, _h, body = _run(env, auth, brief="my manager wants the Q3 deck kept concise")
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert [row["text"] for row in payload["facts"]] == [FEEDBACK]


def test_without_an_endpoint_the_rules_still_stage_a_candidate(env, auth):
    env.server.llm = chat_client("", "k", "m")  # nothing configured
    _run(env, auth)
    run_id = _runs(env)[0]["id"]
    status, _h, _b = _post_feedback(env, auth, run_id, FEEDBACK)
    assert status == 200
    state = _loop(env, auth)
    [candidate] = state["candidates"]
    assert candidate["channel"] == "agents"
    # The endpoint could not be asked, so the candidate is the user's own
    # words read by the deterministic rules.
    assert candidate["text"] == FEEDBACK and candidate["method"] == "rules"


def test_the_agents_channel_has_its_own_switch_and_the_master_switch_stops_it(env, auth):
    _run(env, auth)
    run_id = _runs(env)[0]["id"]
    channels = {c["id"]: c for c in _loop(env, auth)["capture"]["channels"]}
    assert channels["agents"] == {
        "id": "agents", "label": "Agents",
        "setting": "memory_capture_agents", "on": True,
    }
    # The switch itself flips through the settings route.
    status, _h, body = env.post_json(
        "/settings/toggle", {"key": "memory_capture_agents"}, auth
    )
    assert status == 200
    assert json.loads(body) == {"key": "memory_capture_agents", "value": False}
    _post_feedback(env, auth, run_id, FEEDBACK)
    assert _loop(env, auth)["candidates"] == []
    # The master switch off stops every channel, agents included.
    status, _h, _b = env.post_json(
        "/settings/toggle", {"key": "memory_capture_agents"}, auth
    )
    env.server.settings.set("memory_capture", False)
    _post_feedback(env, auth, run_id, FEEDBACK)
    assert _loop(env, auth)["candidates"] == []
    assert _loop(env, auth)["capture"]["enabled"] is False


def test_rejecting_the_card_leaves_nothing_stored(env, auth):
    env.server.settings.set("endpoint_enabled", False)
    _run(env, auth)
    run_id = _runs(env)[0]["id"]
    _post_feedback(env, auth, run_id, FEEDBACK)
    [candidate] = _loop(env, auth)["candidates"]
    status, _h, _b = env.post_json(
        f"/inbox/cards/{candidate['cardId']}/dismiss", {}, auth
    )
    assert status == 200
    state = _loop(env, auth)
    assert state["candidates"] == [] and state["facts"] == []
    # The dismissed words are not re-proposed: the inbox keeps the
    # rejection for its thirty-day window, like every other channel.
    _post_feedback(env, auth, run_id, FEEDBACK)
    assert _loop(env, auth)["candidates"] == []


def test_a_form_feedback_post_redirects_back_and_the_page_shows_it(env, auth):
    _run(env, auth)
    run_id = _runs(env)[0]["id"]
    body = f"feedback={quote(FEEDBACK)}".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, headers_out, _b = env.request(
        "POST", f"/agents/runs/{run_id}/feedback", headers, body
    )
    assert status == 303
    assert headers_out["Location"] == "/agents"
    status, _h, page = env.request("GET", "/agents", auth)
    text = page.decode("utf-8")
    assert status == 200
    assert FEEDBACK in text
    assert "Feedback (" in text  # the record carries its timestamp


def test_blank_and_oversize_feedback_are_refused_with_named_errors(env, auth):
    _run(env, auth)
    run_id = _runs(env)[0]["id"]
    status, _h, body = _post_feedback(env, auth, run_id, "   ")
    assert status == 400
    assert "feedback" in json.loads(body)["error"]
    status, _h, body = _post_feedback(env, auth, run_id, "x" * 4001)
    assert status == 400
    assert "4000" in json.loads(body)["error"]
    assert _runs(env)[0]["feedback"] == ""


def test_feedback_on_an_unknown_run_is_a_404(env, auth):
    status, _h, body = _post_feedback(env, auth, 99, FEEDBACK)
    assert status == 404
    assert "run" in json.loads(body)["error"]


def test_each_feedback_writes_one_agents_feedback_audit_row(env, auth):
    env.server.settings.set("endpoint_enabled", False)
    _run(env, auth)
    run_id = _runs(env)[0]["id"]
    _post_feedback(env, auth, run_id, FEEDBACK)
    rows = _audit_rows(env, "agents.feedback")
    assert len(rows) == 1
    assert rows[0]["target"] == "presentation"
    # Counts and ids only, never the feedback's words.
    assert "Dana" not in rows[0]["detail"]
    assert f"run {run_id}" in rows[0]["detail"]


# -- the audit row and the hermetic default ---------------------------------


def test_each_run_writes_one_agents_run_audit_row(env, auth):
    _add_fact(env, auth, "revenue is 220")
    _run(env, auth)
    rows = _audit_rows(env, "agents.run")
    assert len(rows) == 1
    assert rows[0]["target"] == "presentation"
    assert rows[0]["status"] == "ok"
    assert "used 1" in rows[0]["detail"] or "1 fact" in rows[0]["detail"]


def test_a_degraded_run_audits_as_an_error_naming_its_cause(env, auth):
    env.server.settings.set("endpoint_enabled", False)
    _run(env, auth)
    rows = _audit_rows(env, "agents.run")
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert "degraded" in rows[0]["detail"]


def test_a_boot_with_no_injection_never_writes_the_real_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    booted = server_harness.Booted(llm=CaptureLlm(reply=SLIDES_REPLY))
    try:
        auth = booted.exchange()
        status, _h, _b = booted.request("GET", "/agents", auth)
        assert status == 200
        assert not (tmp_path / "agents.sqlite3").exists()
    finally:
        booted.close()
