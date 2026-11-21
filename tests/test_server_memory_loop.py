"""The memory loop over HTTP: capture from the Assistant and Research,
review on the Memory page, removal with its preview, and undo."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store


class ReplyLlm:
    """Answers the turn; any extraction prompt gets a facts payload."""

    def __init__(self, facts=None) -> None:
        self.prompts: list[str] = []
        self.facts = facts

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "durable memory facts" in prompt and self.facts is not None:
            return json.dumps({"facts": self.facts})
        if "You keep one short observation about" in prompt:
            name = prompt.split("observation about ", 1)[1].split(" in a work", 1)[0]
            ids = [int(line.split(" |", 1)[0]) for line in
                   prompt.split("Facts (id | date | text):\n", 1)[1].splitlines()]
            return json.dumps({"text": f"{name} stands on {len(ids)} facts.",
                               "sourceFactIds": ids[:1]})
        return "Noted."


@pytest.fixture()
def env():
    booted = server_harness.Booted(llm=ReplyLlm(), llm_endpoint="http://endpoint.test/v1")
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _loop(env, auth):
    status, _h, body = env.request("GET", "/api/memory/loop", auth)
    assert status == 200
    return json.loads(body)


def _ask(env, auth, question):
    status, _h, _b = env.post_json("/assistant/ask", {"question": question}, auth)
    assert status == 200


def test_a_transient_memory_failure_reads_as_no_facts_on_the_assistant(env, auth, caplog):
    # A locked store file (a backup or sync process holding it) raises
    # OperationalError mid-read; the turn must answer without facts, the
    # way a locked bank already does, never the generic error page.
    import logging
    import sqlite3

    def locked(_query):
        raise sqlite3.OperationalError("database is locked")

    env.server.memory.recall = locked
    with caplog.at_level(logging.WARNING, logger="agentdesk.server"):
        _ask(env, auth, "what is the revenue?")
    assert any("could not be read just now" in record.getMessage()
               for record in caplog.records)
    # The turn proceeded: the prompt carried no facts block.
    assert "Known facts about the user" not in env.server.llm.prompts[-1]


def test_the_loop_state_needs_a_session(env):
    status, _h, _b = env.request("GET", "/api/memory/loop", env.host_header())
    assert status == 401


def test_an_assistant_turn_stages_a_reviewable_candidate_with_its_excerpt(env, auth):
    env.server.llm.facts = [{"text": "Priya Shah owns the Acme Corp renewal.", "kind": "world",
                             "entities": [{"name": "Priya Shah", "type": "person"},
                                          {"name": "Acme Corp", "type": "org"}]}]
    _ask(env, auth, "Priya Shah owns the Acme Corp renewal, can you track it?")
    state = _loop(env, auth)
    assert state["counts"]["facts"] == 0
    [candidate] = state["candidates"]
    assert candidate["text"] == "Priya Shah owns the Acme Corp renewal."
    assert candidate["channel"] == "assistant" and candidate["method"] == "model"
    assert candidate["excerpt"]["text"].startswith("You: Priya Shah owns")
    assert state["lastCapture"]["staged"] == 1
    # Approve through the inbox's own route, the one approval path.
    status, _h, _b = env.post_json(f"/inbox/cards/{candidate['cardId']}/accept", {}, auth)
    assert status == 200
    state = _loop(env, auth)
    [fact] = state["facts"]
    assert fact["origin"]["id"] == "review:assistant"
    assert sorted(e["name"] for e in fact["entities"]) == ["Acme Corp", "Priya Shah"]
    assert fact["excerpt"] is not None
    assert state["candidates"] == []
    rows = audit_store.entries(env.server.audit_conn)
    capture = next(r for r in rows if r["action"] == "memory.capture")
    assert "Priya" not in capture["detail"]


def test_without_an_endpoint_the_rules_capture_the_users_own_words(env, auth):
    env.post_json("/settings/toggle", {"key": "endpoint_enabled"}, auth)
    _ask(env, auth, "Remember that the Berlin office has 40 people.")
    state = _loop(env, auth)
    assert state["extractor"]["mode"] == "rules"
    assert [c["text"] for c in state["candidates"]] == ["The Berlin office has 40 people."]
    assert state["candidates"][0]["method"] == "rules"


def test_auto_approve_saves_at_once_and_switches_are_respected(env, auth):
    env.post_json("/settings/toggle", {"key": "endpoint_enabled"}, auth)
    status, _h, body = env.post_json("/settings/toggle", {"key": "memory_auto_approve"}, auth)
    assert json.loads(body) == {"key": "memory_auto_approve", "value": True}
    _ask(env, auth, "The Berlin office has 40 people.")
    state = _loop(env, auth)
    assert [f["text"] for f in state["facts"]] == ["The Berlin office has 40 people."]
    assert state["facts"][0]["origin"]["id"] == "auto:assistant"
    env.post_json("/settings/toggle", {"key": "memory_capture_assistant"}, auth)
    _ask(env, auth, "The Pune office has 12 people.")
    assert len(_loop(env, auth)["facts"]) == 1
    env.post_json("/settings/toggle", {"key": "memory_capture_assistant"}, auth)
    env.post_json("/settings/toggle", {"key": "memory_capture"}, auth)
    _ask(env, auth, "The Pune office has 12 people.")
    assert len(_loop(env, auth)["facts"]) == 1
    assert _loop(env, auth)["capture"]["enabled"] is False


def test_research_is_a_capture_channel(env, auth):
    env.post_json("/settings/toggle", {"key": "endpoint_enabled"}, auth)
    status, _h, _b = env.post_json("/research", {"question": "The EU price list changed on Nov 3."}, auth)
    assert status == 200
    [candidate] = _loop(env, auth)["candidates"]
    assert candidate["channel"] == "research" and candidate["channelLabel"] == "Research"
    env.post_json("/settings/toggle", {"key": "memory_capture_research"}, auth)
    env.post_json("/research", {"question": "The US price list changed on Nov 9."}, auth)
    assert len(_loop(env, auth)["candidates"]) == 1


def _add(env, auth, text):
    status, _h, body = env.post_json("/memory/add", {"text": text}, auth)
    assert status == 201
    return json.loads(body)["id"]


def test_remove_preview_remove_and_undo(env, auth):
    memory = env.server.memory
    from agentdesk.memory import loop
    a = loop.store_fact(memory, "Priya Shah owns the Acme Corp renewal.", source="page",
                        entities=[("Acme Corp", "org"), ("Priya Shah", "person")]).fact
    loop.store_fact(memory, "Acme Corp signed for three years.", source="page",
                    entities=[("Acme Corp", "org")])
    status, _h, body = env.post_json("/api/memory/remove/preview",
                                     {"target": {"type": "fact", "id": a.id}}, auth)
    assert status == 200
    plan = json.loads(body)["plan"]
    assert [e["name"] for e in plan["entitiesRemoved"]] == ["Priya Shah"]
    assert len(plan["observationsRemoved"]) == 1
    assert len(memory.all()) == 2, "a preview writes nothing"
    status, _h, body = env.post_json("/api/memory/remove",
                                     {"target": {"type": "fact", "id": a.id}}, auth)
    assert status == 200
    answer = json.loads(body)
    assert answer["removed"]["facts"] == [a.id]
    assert len(memory.all()) == 1 and memory.observations() == []
    row = next(r for r in audit_store.entries(env.server.audit_conn) if r["action"] == "memory.remove")
    assert "Priya" not in row["detail"] and row["target"] == f"fact {a.id}"
    status, _h, _b = env.post_json("/api/memory/undo", {"token": answer["undo"]["token"]}, auth)
    assert status == 200
    assert len(memory.all()) == 2 and len(memory.observations()) == 1
    status, _h, _b = env.post_json("/api/memory/undo", {"token": answer["undo"]["token"]}, auth)
    assert status == 410


def test_remove_refuses_bad_and_unknown_targets(env, auth):
    status, _h, _b = env.post_json("/api/memory/remove", {"target": {"type": "fact", "id": "1"}}, auth)
    assert status == 400
    status, _h, _b = env.post_json("/api/memory/remove", {"target": {"type": "entity", "id": 9}}, auth)
    assert status == 404


def test_keep_both_puts_a_replaced_fact_back_into_recall(env, auth):
    old = _add(env, auth, "The Acme renewal is due December 1.")
    new = _add(env, auth, "The Acme renewal is due December 15.")
    state = _loop(env, auth)
    by_id = {f["id"]: f for f in state["facts"]}
    assert by_id[old]["replacedBy"] == new and by_id[new]["replaces"] == [old]
    assert state["counts"]["replaced"] == 1
    status, _h, _b = env.post_json(f"/api/memory/facts/{old}/keep", {}, auth)
    assert status == 200
    assert _loop(env, auth)["counts"]["replaced"] == 0


def test_removing_an_excerpt_also_rejects_its_waiting_cards(env, auth):
    env.post_json("/settings/toggle", {"key": "endpoint_enabled"}, auth)
    _ask(env, auth, "The Berlin office has 40 people. Acme Corp signed for three years.")
    state = _loop(env, auth)
    source_id = state["candidates"][0]["excerpt"]["id"]
    assert len(state["candidates"]) == 2
    status, _h, _b = env.post_json("/api/memory/remove", {"target": {"type": "source", "id": source_id}}, auth)
    assert status == 200
    state = _loop(env, auth)
    assert state["candidates"] == [] and state["sources"] == []


def test_the_memory_page_mounts_the_loop_island_over_the_server_forms(env, auth, monkeypatch):
    from agentdesk.server import app as app_module
    monkeypatch.setattr(app_module, "memory_loop_island_built", lambda: True)
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode()
    assert status == 200
    assert 'id="memory-loop-root" data-endpoint="/api/memory/loop"' in page
    assert "/static/spa/assets/memory-loop.js" in page
    assert "/static/spa/assets/memory-loop.css" in page
    assert 'class="doc doc-wide"' in page
    # The no-JavaScript page lives inside the root and still posts.
    root = page.split('id="memory-loop-root"', 1)[1].split("</div><link", 1)[0]
    assert 'action="/memory/add"' in root
    # Maintenance stays on the server page, below the island: one tile,
    # folded away, a plain line per action.
    tile = page.split("id='memory-maintenance'", 1)[1].split("</details>", 1)[0]
    assert "<details class='ml-maint'" in page and " open" not in tile.split(">", 1)[0]
    assert "Check what the assistant would recall" in tile
    assert "action='/memory/recall'" in tile and "href='/memory/sweep'" in tile
    # A recall query renders the server page, which shows its answer.
    status, _h, body = env.post_json("/memory/recall", {"query": "revenue"}, auth)
    assert status == 200 and 'id="memory-loop-root"' not in body.decode()


def test_without_the_build_the_memory_page_stays_server_rendered(env, auth, monkeypatch):
    from agentdesk.server import app as app_module
    monkeypatch.setattr(app_module, "memory_loop_island_built", lambda: False)
    _s, _h, body = env.request("GET", "/memory", auth)
    page = body.decode()
    assert 'id="memory-loop-root"' not in page
    assert 'class="doc"' in page


def test_with_an_endpoint_the_model_writes_each_entity_observation(env, auth):
    first = _add(env, auth, "Priya Shah owns the Acme Corp renewal.")
    second = _add(env, auth, "Acme Corp signed for three years.")
    state = _loop(env, auth)
    [obs] = state["observations"]
    assert obs["text"] == "Acme Corp stands on 2 facts."
    assert obs["method"] == "model" and obs["entityName"] == "Acme Corp"
    assert obs["factIds"] == [second]
    rows = [r for r in audit_store.entries(env.server.audit_conn) if r["action"] == "llm.observe"]
    assert rows and "1 observation written" in rows[0]["detail"]
    assert "Priya Shah owns" not in rows[0]["detail"]

    # The preview shows what the observation will read after the removal;
    # the removal writes that text.
    third = _add(env, auth, "Acme Corp is based in Pune.")
    status, _h, body = env.post_json("/api/memory/remove/preview",
                                     {"target": {"type": "fact", "id": first}}, auth)
    [row] = json.loads(body)["plan"]["observationsUpdated"]
    assert row["text"] == "Acme Corp stands on 3 facts."
    assert row["after"] == "Acme Corp stands on 2 facts." and row["afterMethod"] == "model"
    env.post_json("/api/memory/remove", {"target": {"type": "fact", "id": first}}, auth)
    [obs] = _loop(env, auth)["observations"]
    assert obs["text"] == "Acme Corp stands on 2 facts." and obs["factIds"] == [third]


def test_without_endpoint_calls_the_rules_write_a_compact_summary(env, auth):
    env.post_json("/settings/toggle", {"key": "endpoint_enabled"}, auth)  # off
    _add(env, auth, "Priya Shah owns the Acme Corp renewal.")
    _add(env, auth, "Acme Corp signed for three years.")
    [obs] = _loop(env, auth)["observations"]
    assert obs["method"] == "rules" and obs["text"].startswith("2 facts about Acme Corp. Latest")
    assert not any("You keep one short observation" in p for p in env.server.llm.prompts)


def test_the_graph_names_the_entity_first_on_its_observation(env, auth):
    _add(env, auth, "Jordan Lee moved the Halvorsen Freight renewal to legal.")
    _add(env, auth, "Jordan Lee closed the Halvorsen Freight renewal.")
    _add(env, auth, "Halvorsen Freight is based in Oslo.")
    status, _h, body = env.request("GET", "/api/memory/graph", auth)
    assert status == 200
    labels = sorted(n["label"] for n in json.loads(body)["nodes"] if n["kind"] == "observation")
    assert len(labels) == 2 and labels[0].startswith("Halvorsen Freight: ")
    assert labels[1].startswith("Jordan Lee: ")


def test_a_changed_workbook_row_is_captured_for_review(env, auth):
    from agentdesk.excel.core import Delta
    hook = env.server.excel.change_hook
    hook("tracker.xlsx", ["Deal", "Stage", "Owner"],
         Delta(added=[["Halvorsen Freight", "Legal", "Jordan Lee"]],
               removed=[["Halvorsen Freight", "Proposal", "Jordan Lee"]]))
    state = _loop(env, auth)
    [card] = state["candidates"]
    assert card["text"] == "Halvorsen Freight: Stage changed from Proposal to Legal."
    assert card["channel"] == "workbook"
    assert "tracker.xlsx" in card["excerpt"]["text"]
    channels = {c["id"]: c for c in state["capture"]["channels"]}
    assert channels["workbook"]["on"] and channels["workbook"]["label"] == "Workbook tracker"

    # Its own switch under Read from turns it off.
    status, _h, _b = env.post_json("/settings/toggle", {"key": "memory_capture_workbook"}, auth)
    assert status in (200, 303)
    hook("tracker.xlsx", ["Deal", "Stage"], Delta(added=[["Brightwater", "Intro"]], removed=[]))
    assert len(_loop(env, auth)["candidates"]) == 1
