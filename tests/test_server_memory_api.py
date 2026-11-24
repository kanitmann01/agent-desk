"""Memory over HTTP: the page, the assistant prompt, and capture that waits for review.

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


def _review_first_settings():
    """The loop's switches as this suite assumes them: auto-approve off,
    so a chat exchange stages candidates instead of saving. Spec 016
    flipped the stored default to True for new folders."""
    import sqlite3
    import time

    from agentdesk.settings import SettingsStore

    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False),
                             time.time)
    settings.set("memory_auto_approve", False)
    return settings


@pytest.fixture()
def env(tmp_path):
    booted = server_harness.Booted(llm=CaptureLlm(),
                                   settings_store=_review_first_settings())
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


def test_add_lists_and_the_page_shows_the_fact_with_its_origin(env, auth):
    _add_fact(env, auth, "revenue is 220")
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "revenue is 220" in page
    # The rendered origin row, in plain words (ticket #283): not a
    # substring the page's own copy has, and never the stored bookkeeping.
    assert "Typed on this page, saved" in page
    assert "source page" not in page


def test_add_with_a_form_post_redirects_back_to_the_page(env, auth):
    body = "text=revenue+is+220".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, headers_out, _b = env.request("POST", "/memory/add", headers, body)
    assert status == 303
    assert headers_out["Location"].split("?", 1)[0] == "/memory"
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


# -- hygiene over HTTP (ticket #92) ------------------------------------------


def test_edit_onto_another_facts_text_reports_the_merge(env, auth):
    first = _add_fact(env, auth, "revenue is 220")
    second = _add_fact(env, auth, "meeting room booked")
    status, _h, body = env.post_json(
        f"/memory/{second['id']}/edit", {"text": "Revenue is 220"}, auth
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["mergedIntoExisting"] is True
    assert payload["id"] == first["id"], "the oldest fact survives"
    facts = _facts(env)
    assert [f.id for f in facts] == [first["id"]]
    assert facts[0].text == "revenue is 220"


def test_edit_to_a_unique_text_reports_no_merge(env, auth):
    fact = _add_fact(env, auth, "revenue is 220")
    status, _h, body = env.post_json(
        f"/memory/{fact['id']}/edit", {"text": "revenue is 480"}, auth
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["mergedIntoExisting"] is False
    assert payload["id"] == fact["id"]
    assert payload["text"] == "revenue is 480"


def test_edit_merge_notice_renders_on_a_form_post(env, auth):
    _add_fact(env, auth, "revenue is 220")
    second = _add_fact(env, auth, "meeting room booked")
    body = "text=revenue+is+220".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, headers_out, raw = env.request(
        "POST", f"/memory/{second['id']}/edit", headers, body
    )
    page = raw.decode("utf-8")
    assert status == 200
    assert headers_out.get("Location") is None, "the merge renders, no redirect"
    assert 'id="memory-notice"' in page
    assert "merged" in page
    assert len(_facts(env)) == 1


def _link_entities(env, fact_id, names):
    env.server.memory.resolve_and_link(fact_id, names)


def test_memory_page_lists_entities_with_a_merge_form(env, auth):
    first = _add_fact(env, auth, "Maya joined Acme")
    second = _add_fact(env, auth, "Acme shipped the widget")
    third = _add_fact(env, auth, "the offsite is planned")
    _link_entities(env, first["id"], [("Maya Rahman", "person"), ("Acme", "org")])
    _link_entities(env, second["id"], [("Acme", "org")])
    _link_entities(env, third["id"], [("Offsite Club", "other")])
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "Entities" in page
    assert "/memory/entities/merge" in page
    # Compact rows: canonical name, aliases, type and the fact count.
    assert "Acme" in page
    assert "2 facts" in page
    assert "Maya Rahman" in page
    assert "org" in page


def test_entity_merge_route_unions_aliases_and_relinks_facts(env, auth):
    first = _add_fact(env, auth, "the acme merger closed")
    second = _add_fact(env, auth, "the bonus pool grew")
    _link_entities(env, first["id"], [("Acme", "org")])
    _link_entities(env, second["id"], [("Globex", "org")])
    status, _h, body = env.post_json(
        "/memory/entities/merge", {"survivor": 1, "removed": 2}, auth
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["survivor"] == 1
    store = env.server.memory
    summaries = store.entities()
    assert len(summaries) == 1
    assert summaries[0].id == 1
    assert summaries[0].aliases == ("Globex",)
    edges = store.conn.execute("SELECT fact_id, entity_id FROM edges").fetchall()
    assert sorted(edges) == [(first["id"], 1), (second["id"], 1)]
    row = next(e for e in audit_store.entries(env.server.audit_conn)
               if e["action"] == "memory.merge")
    assert row["target"] == "1"
    assert "2" in row["detail"]


def test_entity_merge_route_reconciles_the_survivors_observation(env, auth):
    from agentdesk.memory import loop as memory_loop

    facts = [
        _add_fact(env, auth, text) for text in (
            "the acme renewal was signed",
            "acme hired maya",
            "the globex widget shipped",
            "globex opened the office",
        )
    ]
    _link_entities(env, facts[0]["id"], [("Acme", "org")])
    _link_entities(env, facts[1]["id"], [("Acme", "org")])
    _link_entities(env, facts[2]["id"], [("Globex", "org")])
    _link_entities(env, facts[3]["id"], [("Globex", "org")])
    memory_loop.reconcile_observations(env.server.memory)
    assert len(env.server.memory.observations()) == 2
    status, _h, _b = env.post_json(
        "/memory/entities/merge", {"survivor": 1, "removed": 2}, auth
    )
    assert status == 200
    observations = env.server.memory.observations()
    assert len(observations) == 1, "no orphaned Globex observation survives"
    assert observations[0].text.startswith("4 facts about Acme")
    assert set(observations[0].fact_ids) == {fact["id"] for fact in facts}
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert "4 facts about Acme" in page
    assert "facts about Globex" not in page, "no orphaned observation text"


def test_entity_merge_route_refuses_self_and_unknown(env, auth):
    fact = _add_fact(env, auth, "Maya joined Acme")
    _link_entities(env, fact["id"], [("Acme", "org")])
    before = len(env.server.memory.entities())
    status, _h, body = env.post_json(
        "/memory/entities/merge", {"survivor": 1, "removed": 1}, auth
    )
    assert status == 400
    status, _h, body = env.post_json(
        "/memory/entities/merge", {"survivor": 1, "removed": 99}, auth
    )
    assert status == 404
    status, _h, body = env.post_json(
        "/memory/entities/merge", {"survivor": "x", "removed": 2}, auth
    )
    assert status == 400
    assert len(env.server.memory.entities()) == before


def test_get_memory_sweep_lists_candidates_with_reasons(env, auth):
    _add_fact(env, auth, "I do not have any information about that.")
    real = _add_fact(env, auth, "revenue is 220")
    status, _h, body = env.request("GET", "/memory/sweep", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "/memory/sweep" in page
    assert "knowledge-gap" in page
    assert 'name="sweep_1"' in page, "the junk candidate gets a checkbox"
    assert 'name="sweep_2"' not in page, "the real fact is not a candidate"
    assert "revenue is 220" in page, "the page still lists the facts"


def test_post_memory_sweep_deletes_candidates_and_their_orphans(env, auth):
    junk = _add_fact(env, auth, "I do not have any information about that.")
    real = _add_fact(env, auth, "revenue is 220")
    store = env.server.memory
    store.resolve_and_link(junk["id"], [("Nothing Inc", "org")])
    store.resolve_and_link(real["id"], [("Acme", "org")])
    store.conn.execute(
        "INSERT INTO observations (scope_key, text, confidence, created_ts, updated_ts)"
        " VALUES ('all', 'Doomed pattern.', 0.9, 100.0, 100.0)"
    )
    store.conn.execute(
        "INSERT INTO observation_sources (observation_id, fact_id) VALUES (1, ?)",
        (junk["id"],),
    )
    store.conn.commit()
    status, _h, body = env.post_json("/memory/sweep", {"ids": [junk["id"]]}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["deleted"] == 1
    assert payload["removedObservationIds"] == [1]
    assert payload["removedEntityIds"] == [1]
    assert [f.id for f in _facts(env)] == [real["id"]]
    assert store.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    row = next(e for e in audit_store.entries(env.server.audit_conn)
               if e["action"] == "memory.sweep")
    assert "revenue" not in row["detail"], "the audit never carries fact text"


def test_post_memory_sweep_form_checkboxes_delete_the_checked_ones(env, auth):
    junk_one = _add_fact(env, auth, "I do not have any information about that.")
    junk_two = _add_fact(env, auth, "unknown")
    real = _add_fact(env, auth, "revenue is 220")
    body = f"sweep_{junk_one['id']}=on".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, headers_out, _b = env.request("POST", "/memory/sweep", headers, body)
    assert status == 303
    assert headers_out["Location"].split("?", 1)[0] == "/memory"
    texts = [f.id for f in _facts(env)]
    assert junk_one["id"] not in texts
    assert junk_two["id"] in texts
    assert real["id"] in texts


def test_post_memory_sweep_is_all_or_nothing(env, auth):
    junk = _add_fact(env, auth, "I do not have any information about that.")
    status, _h, _b = env.post_json("/memory/sweep", {"ids": [junk["id"], 999]}, auth)
    assert status == 404
    assert [f.id for f in _facts(env)] == [junk["id"]], "nothing was deleted"


def test_post_memory_sweep_refuses_a_fact_that_is_not_junk(env, auth):
    real = _add_fact(env, auth, "revenue is 220")
    status, _h, _b = env.post_json("/memory/sweep", {"ids": [real["id"]]}, auth)
    assert status == 400
    assert [f.id for f in _facts(env)] == [real["id"]]


def test_post_memory_sweep_without_ids_is_refused(env, auth):
    status, _h, _b = env.post_json("/memory/sweep", {}, auth)
    assert status == 400


def test_sweep_and_merge_endpoints_require_a_session(env):
    status, _h, _b = env.request("GET", "/memory/sweep", env.host_header())
    assert status == 401
    status, _h, _b = env.post_json("/memory/sweep", {"ids": [1]}, env.host_header())
    assert status == 401
    status, _h, _b = env.post_json(
        "/memory/entities/merge", {"survivor": 1, "removed": 2}, env.host_header()
    )
    assert status == 401


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
    # The preview sits inside the Maintenance disclosure, below the saved
    # facts (ticket #283), so the rank is read in the preview itself.
    preview = page.split("id='recall-preview'", 1)[1].split("</ol>", 1)[0]
    best_at = preview.find("revenue is 220")
    lesser_at = preview.find("revenue is checked every monday")
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
    # Ticket #92: write-time dedup reuses the row for identical text, so
    # the four long facts carry a marker each and stay distinct; the
    # bound is genuinely exercised over five facts.
    long_fact = "revenue " * 40  # 320 characters with its trailing space
    for index in range(4):
        _add_fact(env, auth, f"{long_fact}mark {index}")
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
    """Capture proposes, the user decides: with the default review mode
    a chat exchange stages candidates for review and writes no fact.
    (The teammate's memory remembered any sentence containing " is "
    straight away; ours waits for an approval.)"""
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
