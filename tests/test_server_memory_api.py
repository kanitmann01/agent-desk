"""Memory over HTTP: the page, the assistant prompt, and no auto-capture.

The seam tests drive the real server: the memory page's list, add, edit,
delete and recall preview, the bounded facts block in the assistant
prompt, the accepted-card creation path, and the deliberate absence of
any other creation path (a chat exchange must never create a fact).
"""

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


class CaptureLlm:
    """The stub adapter the assistant tests use: records every prompt."""

    def __init__(self, reply: str = "A short answer.") -> None:
        self.prompts: list[str] = []
        self.reply = reply

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


@pytest.fixture()
def env(tmp_path):
    booted = server_harness.Booted(llm=CaptureLlm())
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


def _facts(env):
    return env.server.memory.all()


# -- the gate and the page -----------------------------------------------


def test_memory_endpoints_require_a_session(env):
    status, _h, _b = env.post_json("/memory/add", {"text": "x"}, env.host_header())
    assert status == 401
    status, _h, _b = env.request("GET", "/memory", env.host_header())
    assert status == 401


def test_empty_memory_page_names_the_object_and_offers_add_and_recall(env, auth):
    status, _h, body = env.request("GET", "/memory", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "Memory" in page
    assert "/memory/add" in page
    assert "/memory/recall" in page
    assert "No facts yet" in page


def test_add_lists_and_the_page_shows_the_fact_with_its_source(env, auth):
    _add_fact(env, auth, "revenue is 220")
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "revenue is 220" in page
    # The rendered source row, not a substring the page's own copy has.
    assert "source page" in page


def test_add_with_a_form_post_redirects_back_to_the_page(env, auth):
    body = "text=revenue+is+220".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, headers_out, _b = env.request("POST", "/memory/add", headers, body)
    assert status == 303
    assert headers_out["Location"] == "/memory"
    assert [f.text for f in _facts(env)] == ["revenue is 220"]


def test_add_without_text_is_refused(env, auth):
    status, _h, _b = env.post_json("/memory/add", {"text": "   "}, auth)
    assert status == 400


def test_edit_changes_the_text_only(env, auth):
    fact = _add_fact(env, auth, "revenue is 220")
    status, _h, body = env.post_json(
        f"/memory/{fact['id']}/edit", {"text": "revenue is 480"}, auth
    )
    assert status == 200
    stored = _facts(env)[0]
    assert stored.text == "revenue is 480"
    assert stored.source == "page"


def test_edit_of_an_unknown_fact_is_a_404(env, auth):
    status, _h, _b = env.post_json("/memory/999/edit", {"text": "x"}, auth)
    assert status == 404


def test_delete_removes_the_fact_from_the_page(env, auth):
    fact = _add_fact(env, auth, "revenue is 220")
    status, _h, _b = env.post_json(f"/memory/{fact['id']}/delete", {}, auth)
    assert status == 200
    assert _facts(env) == []
    status, _h, body = env.request("GET", "/memory", auth)
    assert "revenue is 220" not in body.decode("utf-8")


def test_delete_of_an_unknown_fact_is_a_404(env, auth):
    status, _h, _b = env.post_json("/memory/999/delete", {}, auth)
    assert status == 404


def test_recall_renders_a_ranked_preview_best_first(env, auth):
    # Both facts match the query; the full-overlap one must rank first.
    # Added in the other order, so the saved-facts list cannot make the
    # assertion pass for the wrong reason.
    _add_fact(env, auth, "revenue is checked every monday")
    _add_fact(env, auth, "revenue is 220")
    body = "query=revenue+220".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, _h, raw = env.request("POST", "/memory/recall", headers, body)
    assert status == 200
    page = raw.decode("utf-8")
    best_at = page.find("revenue is 220")
    lesser_at = page.find("revenue is checked every monday")
    assert 0 < best_at < lesser_at, "the stronger overlap must rank first"
    assert "Recall preview" in page


def test_recall_preview_escapes_fact_text(env, auth):
    _add_fact(env, auth, "<script>alert(1)</script>")
    body = "query=script".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, _h, raw = env.request("POST", "/memory/recall", headers, body)
    page = raw.decode("utf-8")
    assert status == 200
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_recall_preview_recalls_a_linked_fact_by_entity_name(env, auth):
    # The hybrid ranker's graph leg (ticket #90): a query naming the
    # entity recalls the fact even though it shares no keyword with it.
    _add_fact(env, auth, "the board approved the budget")
    conn = env.server.memory.conn
    cursor = conn.execute(
        "INSERT INTO entities (canonical_name, aliases_json, type, created_ts)"
        " VALUES ('Acme', '[]', 'org', ?)",
        (_facts(env)[0].created_ts,),
    )
    conn.execute(
        "INSERT INTO edges (fact_id, entity_id) VALUES (?, ?)",
        (_facts(env)[0].id, int(cursor.lastrowid)),
    )
    body = "query=acme".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, _h, raw = env.request("POST", "/memory/recall", headers, body)
    page = raw.decode("utf-8")
    assert status == 200
    assert "the board approved the budget" in page
    assert "Recall preview" in page


# -- the settings source rail --------------------------------------------


def test_settings_rail_links_the_memory_page(env, auth):
    status, _h, body = env.request("GET", "/settings", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert 'href="/memory"' in page


# -- the assistant prompt -------------------------------------------------


def test_assistant_prompt_prepends_the_bounded_facts_block(env, auth):
    for text in ("revenue is 220", "the meeting room is booked"):
        _add_fact(env, auth, text)
    status, _h, body = env.post_json(
        "/assistant/ask", {"question": "what is the revenue?"}, auth
    )
    assert status == 200
    assert json.loads(body)["status"] == "ok"
    prompt = env.server.llm.prompts[0]
    assert "Known facts about the user" in prompt
    assert "- revenue is 220" in prompt
    assert "revenue" in prompt.split("Known facts")[1].split("Connected widget")[0]


def test_assistant_prompt_without_facts_gains_no_block(env, auth):
    status, _h, body = env.post_json(
        "/assistant/ask", {"question": "what is the revenue?"}, auth
    )
    assert status == 200
    prompt = env.server.llm.prompts[0]
    assert "Known facts about the user" not in prompt


def test_assistant_prompt_facts_stay_bounded_to_five_facts_and_500_chars(env, auth):
    long_fact = "revenue " * 40  # 320 characters with its trailing space
    for _ in range(4):
        _add_fact(env, auth, long_fact)
    _add_fact(env, auth, "revenue is 220")
    _add_fact(env, auth, "revenue is checked every monday")
    status, _h, _b = env.post_json(
        "/assistant/ask", {"question": "revenue revenue revenue revenue revenue revenue"}, auth
    )
    assert status == 200
    prompt = env.server.llm.prompts[0]
    block = prompt.split("Known facts about the user", 1)[1].split("Connected widget context", 1)[0]
    lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(lines) <= 5
    assert sum(len(ln) for ln in lines) <= 500
    # Whole facts only: every rendered line is exactly one stored fact.
    stored = {f"- {f.text}" for f in _facts(env)}
    assert set(lines) <= stored


def test_research_prompt_gains_no_facts_block(env, auth):
    _add_fact(env, auth, "revenue is 220")
    status, _h, _b = env.post_json("/research", {"question": "revenue?"}, auth)
    assert status == 200
    prompt = env.server.llm.prompts[0]
    assert "Known facts about the user" not in prompt


# -- creation paths: accepted cards yes, conversation never ---------------


def _add_card(env, auth, **overrides):
    payload = {
        "kind": "suggestion",
        "origin": "You asked for this breakdown 5 times.",
        "title": "Save the revenue note?",
        "body": "It would record the revenue total.",
        "actionLabel": "Accept",
        "meta": {},
    }
    payload.update(overrides)
    status, _h, body = env.post_json("/inbox/cards", payload, auth)
    assert status == 201
    return json.loads(body)


def test_accepting_a_card_that_carries_a_fact_creates_exactly_one_fact(env, auth):
    card = _add_card(env, auth, meta={"fact": "revenue is 220"})
    status, _h, _b = env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    assert status == 200
    facts = _facts(env)
    assert [f.text for f in facts] == ["revenue is 220"]
    assert facts[0].source.startswith("inbox card ")


def test_dismissing_a_fact_card_creates_no_fact(env, auth):
    card = _add_card(env, auth, meta={"fact": "revenue is 220"})
    status, _h, _b = env.post_json(f"/inbox/cards/{card['id']}/dismiss", {}, auth)
    assert status == 200
    assert _facts(env) == []


def test_accepting_a_card_without_fact_meta_creates_no_fact(env, auth):
    card = _add_card(env, auth)
    status, _h, _b = env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    assert status == 200
    assert _facts(env) == []


def test_the_accepted_fact_is_audit_visible_without_its_text(env, auth):
    card = _add_card(env, auth, meta={"fact": "revenue is 220"})
    env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    entries = audit_store.entries(env.server.audit_conn)
    row = next(e for e in entries if e["action"] == "memory.fact")
    assert row["detail"].startswith("inbox card ")
    assert "revenue is 220" not in row["detail"]


def test_a_chat_exchange_alone_creates_no_fact(env, auth):
    """The no-auto-capture test: the teammate's memory remembered any
    sentence containing " is "; ours never derives a fact from what the
    user types. Creation is the page's add form or an accepted card."""
    status, _h, _b = env.post_json(
        "/assistant/ask",
        {"question": "The revenue total is 220 and the meeting room is booked."},
        auth,
    )
    assert status == 200
    status, _h, _b = env.post_json(
        "/research",
        {"question": "The revenue total is 220."},
        auth,
    )
    assert status == 200
    assert _facts(env) == []
