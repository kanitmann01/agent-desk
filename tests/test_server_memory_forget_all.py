"""The Memory page explains itself and can be emptied (ticket #283).

The seam is the one the memory suites already use: the real server over
a real socket, driven the way a browser without scripting drives it. A
page's words and controls, an HTTP status, a row in the audit export and
what the next assistant answer carries are what a user can see or do;
nothing here reads a helper or a stylesheet.
"""

import re
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from nexuusbot.assistant import audit as audit_store


class CaptureLlm:
    """The stub adapter the memory suites use: records every prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "A short answer."


@pytest.fixture(params=[True, False], ids=["island", "plain"])
def env(request):
    """The real server in both postures a user can meet: the committed
    build, which mounts the island over the server forms (the product),
    and a checkout without it. The suite's default points the build
    directory nowhere, so the island posture is switched on the way the
    existing page tests switch it."""
    from nexuusbot.server import memory_api

    if request.param:
        patch = request.getfixturevalue("monkeypatch")
        patch.setattr(memory_api, "memory_loop_island_built", lambda: True)
        patch.setattr(memory_api, "memory_graph_island_built", lambda: True)
    booted = server_harness.Booted(llm=CaptureLlm())
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _post_form(env, auth, path, fields):
    """One plain HTML form post, exactly as a browser without scripting sends it."""
    body = urlencode(fields).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    return env.request("POST", path, headers, body)


def _element(page, marker, closing):
    """The inside of the first element that opens with marker, up to its closing tag.

    The marker may sit inside the opening tag or be all of it; either way
    what comes back is the element's content, never its own attributes."""
    rest = page.split(marker, 1)[1].split(closing, 1)[0]
    if not rest.lstrip().startswith("<"):
        rest = rest.split(">", 1)[1]
    return rest


def _words(markup):
    """The words a reader sees in a fragment of page: tags dropped, text unescaped."""
    import html

    text = re.sub(r"<[^>]+>", " ", markup)
    return " ".join(html.unescape(text).split()).split(" ")


# -- the explanation ---------------------------------------------------------


def test_the_memory_page_leads_with_a_short_explanation_in_plain_words(env, auth):
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    block = _element(page, 'id="how-memory-works"', "</section>")
    words = _words(block)
    assert len("".join(words)) >= 200, "the explanation has something to read"
    assert len(words) < 90, f"{len(words)} words: {words}"
    text = " ".join(words)
    # What it remembers, how it learns, who controls it, and the two promises.
    for phrase in ("remembers facts", "as you work", "where it came from",
                   "edit or forget", "keys, passwords", "text of emails",
                   "this computer"):
        assert phrase in text, phrase
    # Plain language for a non-technical manager (GLOSSARY.md).
    for banned in ("entit", "observation", "provenance", "capture", "retain",
                   "extract", "endpoint", "provider"):
        assert banned not in text.lower(), banned
    # It leads: before the facts, before the island and before every action.
    assert page.index('id="how-memory-works"') < page.index('action="/memory/add"')
    if 'id="memory-loop-root"' in page:
        assert page.index('id="how-memory-works"') < page.index('id="memory-loop-root"')


# -- the control and its confirmation ----------------------------------------


def _add(env, auth, text):
    status, _h, body = env.post_json("/memory/add", {"text": text}, auth)
    assert status == 201
    return json.loads(body)["id"]


def _rows(memory):
    """What the bank holds, by kind: facts, the names they are filed under, their links, summaries and excerpts."""
    edges = memory.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return (len(memory.all()), len(memory.entities()), edges,
            len(memory.observations()), len(memory.sources()))


def test_the_page_offers_forget_everything_as_a_form_to_its_own_address(env, auth):
    _add(env, auth, "The Acme renewal is due December 15.")
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    forms = re.findall(r"<form[^>]*>", page)
    forget = [form for form in forms if 'action="/memory/forget-all"' in form]
    assert len(forget) == 1, forms
    assert "Forget everything" in page


def test_a_first_post_shows_the_confirmation_and_deletes_nothing(env, auth):
    from nexuusbot.memory import loop

    memory = env.server.memory
    _add(env, auth, "The Acme renewal is due December 15.")
    _add(env, auth, "Acme signed for three years.")
    memory.resolve_and_link(2, [("Acme", "org")])
    loop.reconcile_observations(memory)
    before = _rows(memory)
    assert before[0] == 2 and before[1] == 1 and before[3] == 1, before

    status, headers, body = _post_form(env, auth, "/memory/forget-all", {})
    page = body.decode("utf-8")
    assert status == 200, status
    assert headers.get("Location") is None, "the question renders, no redirect"
    # One form still posts there, and it is the confirmation: it says it
    # cannot be undone and carries the confirm field the second submit
    # sends. The action and the field are read literally (double quotes)
    # because the readiness checks read them the same way.
    forms = re.findall(r"<form[^>]*>.*?</form>", page, re.S)
    confirm = [form for form in forms if 'action="/memory/forget-all"' in form]
    assert len(confirm) == 1, forms
    assert "cannot be undone" in " ".join(_words(confirm[0])).lower()
    assert 'name="confirm" value="yes"' in confirm[0], confirm[0]
    assert re.search(r"type=['\"]submit['\"][^>]*>Forget everything</button>", confirm[0])
    # The way out is one link back to the page.
    assert re.search(r"href=['\"]/memory['\"]", confirm[0])
    # Nothing was deleted, nothing was recorded, and the facts are still listed.
    assert _rows(memory) == before
    assert "The Acme renewal is due December 15." in page
    assert not [row for row in audit_store.entries(env.server.audit_conn)
                if row["action"] == "memory.forget_all"]


# -- the action --------------------------------------------------------------


def _a_bank_with_everything_derived(env, auth):
    """Two standing facts, one a replaced older value, their names, a summary
    and an original excerpt: something in every table a fact feeds."""
    from nexuusbot.memory import loop

    memory = env.server.memory
    _add(env, auth, "The Acme renewal is due December 1.")
    _add(env, auth, "The Acme renewal is due December 15.")
    _add(env, auth, "Acme signed for three years.")
    memory.add_source("You: Acme signed for three years.", speaker="You", context="assistant")
    loop.reconcile_observations(memory)
    held = _rows(memory)
    assert all(held), held
    return held


def test_the_confirmed_post_forgets_every_fact_and_everything_made_from_them(env, auth):
    memory = env.server.memory
    _a_bank_with_everything_derived(env, auth)
    status, headers, body = _post_form(env, auth, "/memory/forget-all", {"confirm": "yes"})
    assert status == 303, status
    assert headers["Location"].split("?", 1)[0] == "/memory"
    assert _rows(memory) == (0, 0, 0, 0, 0), _rows(memory)
    assert memory.superseded_map() == {}
    # A replaced older value was a fact too: it went with the rest.
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert "Acme renewal is due" not in page
    assert "signed for three years" not in page


def test_only_the_exact_confirm_field_performs_the_action(env, auth):
    memory = env.server.memory
    _add(env, auth, "The Acme renewal is due December 15.")
    for fields in ({"confirm": "on"}, {"confirm": "true"}, {"confirm": "yes "}):
        status, _h, _b = _post_form(env, auth, "/memory/forget-all", fields)
        assert status == 200, fields
    assert len(memory.all()) == 1, "nothing but the exact confirm field deletes"


def test_an_empty_bank_lands_back_on_the_page_and_deletes_nothing(env, auth):
    memory = env.server.memory
    assert memory.all() == []
    status, headers, _b = _post_form(env, auth, "/memory/forget-all", {})
    assert (status, headers["Location"].split("?", 1)[0]) == (303, "/memory")
    status, headers, _b = _post_form(env, auth, "/memory/forget-all", {"confirm": "yes"})
    assert (status, headers["Location"].split("?", 1)[0]) == (303, "/memory")
    assert _rows(memory) == (0, 0, 0, 0, 0)


def test_the_route_sits_behind_the_same_guard_as_every_form_post(env, auth):
    _add(env, auth, "The Acme renewal is due December 15.")
    # No session: refused, and the fact survives.
    status, _h, _b = _post_form(env, env.host_header(), "/memory/forget-all", {"confirm": "yes"})
    assert status == 401
    # A page on another origin posting the form: refused the same way.
    status, _h, _b = _post_form(env, {**auth, "Origin": "https://example.com"},
                                "/memory/forget-all", {"confirm": "yes"})
    assert status == 403
    assert len(env.server.memory.all()) == 1


# -- what the action records, keeps and leaves -------------------------------


def _forget_everything(env, auth):
    status, headers, _b = _post_form(env, auth, "/memory/forget-all", {"confirm": "yes"})
    assert (status, headers["Location"].split("?", 1)[0]) == (303, "/memory")


def test_the_audit_export_gains_a_row_that_counts_and_never_quotes(env, auth):
    _a_bank_with_everything_derived(env, auth)
    _forget_everything(env, auth)
    status, _h, body = env.request("GET", "/audit/export.csv", auth)
    export = body.decode("utf-8")
    assert status == 200
    [row] = [line for line in export.splitlines() if "memory.forget_all" in line]
    assert row.startswith("agent-desk,memory.forget_all,3 facts,")
    assert "Acme" not in export
    # An empty bank writes no row: there was nothing to record.
    status, _h, body = env.request("GET", "/audit/export.csv", auth)
    _forget_everything(env, auth)
    status, _h, after = env.request("GET", "/audit/export.csv", auth)
    assert after == body


def test_the_it_page_describes_the_action_in_plain_words(env, auth):
    status, _h, body = env.request("GET", "/what-this-touches", auth)
    page = body.decode("utf-8")
    assert status == 200
    row = _element(page, "<td class='mono'>memory.forget_all</td>", "</tr>")
    statement = " ".join(_words(row)).lower()
    assert "in use" not in statement, "nothing has run yet"
    assert "forget everything" in statement
    assert "settings" in statement and "not touched" in statement
    for banned in ("entit", "observation", "source", "excerpt", "provenance"):
        assert banned not in statement, banned
    _add(env, auth, "The Acme renewal is due December 15.")
    _forget_everything(env, auth)
    status, _h, body = env.request("GET", "/what-this-touches", auth)
    row = _element(body.decode("utf-8"), "<td class='mono'>memory.forget_all</td>", "</tr>")
    assert "in use" in row


def test_the_settings_are_untouched(env, auth):
    _add(env, auth, "The Acme renewal is due December 15.")
    env.post_json("/settings/toggle", {"key": "memory_auto_approve"}, auth)
    env.post_json("/settings/toggle", {"key": "memory_capture_assistant"}, auth)
    status, _h, before = env.request("GET", "/widgets/settings", auth)
    assert status == 200
    _forget_everything(env, auth)
    status, _h, after = env.request("GET", "/widgets/settings", auth)
    assert status == 200
    assert after == before


def test_the_encryption_key_is_untouched_on_a_sealed_bank(tmp_path):
    import sqlite3
    import time

    from nexuusbot.memory.store import MemoryStore

    db = tmp_path / "memory.sqlite3"
    key_path = tmp_path / "memory.key"
    conn = sqlite3.connect(str(db), check_same_thread=False)
    store = MemoryStore(conn, time.time, key_path=key_path)
    booted = server_harness.Booted(memory_store=store)
    auth = booted.exchange()
    _add(booted, auth, "The Acme renewal is due December 15.")
    status, _h, body = _post_form(booted, auth, "/memory/encrypt", {"confirm": "on"})
    assert (status, _h["Location"].split("?", 1)[0]) == (303, "/memory"), body
    sealed_key = key_path.read_bytes()
    raw_before = db.read_bytes()
    assert b"Acme renewal" not in raw_before

    _forget_everything(booted, auth)

    assert key_path.read_bytes() == sealed_key
    assert b"Acme renewal" not in db.read_bytes()
    status, _h, body = booted.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert "Memory is empty" in page
    # Still sealed: the page says so, and a fact typed afterwards is stored as ciphertext.
    assert "encrypted at rest" in page
    _add(booted, auth, "A fact typed after forgetting.")
    assert b"A fact typed after forgetting" not in db.read_bytes()
    booted.close()
    conn.close()


def test_the_page_says_memory_is_empty_once_everything_is_forgotten(env, auth):
    _a_bank_with_everything_derived(env, auth)
    _forget_everything(env, auth)
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "Memory is empty" in page
    assert 'action="/memory/forget-all"' not in page, "nothing is left to forget"
    for text in ("Acme renewal is due", "signed for three years"):
        assert text not in page


def _answer_prompts(llm, since=0):
    """The prompts that asked for an answer since an earlier count: a turn
    also asks the model to read the exchange for facts, and those are
    not the answer's own prompt."""
    return [p for p in llm.prompts[since:] if "durable memory facts" not in p]


def test_a_later_answer_no_longer_carries_a_forgotten_fact(env, auth):
    _add(env, auth, "The Berlin office has 40 people.")
    env.post_json("/assistant/ask", {"question": "how many people work in Berlin?"}, auth)
    [first] = _answer_prompts(env.server.llm)
    assert "The Berlin office has 40 people." in first
    asked = len(env.server.llm.prompts)
    _forget_everything(env, auth)
    env.post_json("/assistant/ask", {"question": "how many people work in Berlin?"}, auth)
    [second] = _answer_prompts(env.server.llm, asked)
    assert "The Berlin office has 40 people." not in second
    assert "Known facts about the user" not in second


def test_review_cards_waiting_on_the_forgotten_excerpts_are_rejected():
    import sqlite3
    import time

    from nexuusbot.settings import SettingsStore

    # Review first: a turn stages its facts as cards instead of saving them.
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    settings.set("memory_auto_approve", False)
    settings.set("endpoint_enabled", False)
    booted = server_harness.Booted(llm=CaptureLlm(), settings_store=settings)
    auth = booted.exchange()
    try:
        _add(booted, auth, "The Acme renewal is due December 15.")
        booted.post_json("/assistant/ask", {"question": "The Berlin office has 40 people."}, auth)
        [card] = [c for c in booted.server.inbox.waiting() if c.kind == "memory_draft"]
        _forget_everything(booted, auth)
        assert booted.server.inbox.waiting() == [], "nothing waits on a forgotten excerpt"
        assert booted.server.inbox.get(card.id).status == "dismissed"
    finally:
        booted.close()


# -- hardening: pending content, a locked store, two clicks --------------------


def _review_first_boot():
    """A review-first desk over HTTP: automatic saving off and endpoint
    calls off, so a turn leaves a saved excerpt and waiting review cards
    instead of facts."""
    import sqlite3
    import time

    from nexuusbot.settings import SettingsStore

    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    settings.set("memory_auto_approve", False)
    settings.set("endpoint_enabled", False)
    return server_harness.Booted(llm=CaptureLlm(), settings_store=settings)


def test_pending_excerpts_and_waiting_cards_go_even_when_no_fact_stands():
    booted = _review_first_boot()
    auth = booted.exchange()
    try:
        memory = booted.server.memory
        booted.post_json("/assistant/ask",
                         {"question": "The Berlin office has 40 people."}, auth)
        assert memory.all() == [], "review first: nothing stands yet"
        assert len(memory.sources()) == 1, "the turn's excerpt is saved"
        [card] = [c for c in booted.server.inbox.waiting()
                  if c.kind == "memory_draft"]

        # The question still comes first: there is something to forget.
        status, _h, _b = _post_form(booted, auth, "/memory/forget-all", {})
        assert status == 200, status
        status, _h, body = booted.post_json("/memory/forget-all",
                                            {"confirm": "yes"}, auth)
        assert status == 200, status
        payload = json.loads(body)
        assert payload["status"] == "ok"
        assert payload["forgot"] == 0
        assert payload["excerpts"] == 1
        assert payload["cards"] == 1

        assert _rows(memory) == (0, 0, 0, 0, 0), _rows(memory)
        assert booted.server.inbox.waiting() == []
        assert booted.server.inbox.get(card.id).status == "dismissed"
        status, _h, export = booted.request("GET", "/audit/export.csv", auth)
        [row] = [line for line in export.decode("utf-8").splitlines()
                 if "memory.forget_all" in line]
        assert row.startswith("agent-desk,memory.forget_all,0 facts,"), row
        # The export carries the target only; the detail is read back
        # from the store, the way the reflect suite reads its rows.
        [entry] = [entry for entry in audit_store.entries(booted.server.audit_conn)
                   if entry["action"] == "memory.forget_all"]
        assert "1 excerpts forgotten" in entry["detail"], entry["detail"]
        assert "1 review card rejected" in entry["detail"], entry["detail"]
        status, _h, page = booted.request("GET", "/memory", auth)
        assert "Memory is empty" in page.decode("utf-8")
    finally:
        booted.close()


class _ScriptedReflector:
    """Answers reflect runs with the given drafts, recording nothing."""

    def __init__(self, drafts) -> None:
        self.drafts = list(drafts)

    def reflect(self, topic, facts):
        return list(self.drafts)


def test_waiting_reflection_cards_are_rejected_with_the_facts(env, auth):
    from nexuusbot.memory.reflect import ObservationDraft

    memory = env.server.memory
    first = _add(env, auth, "Maya left Acme.")
    second = _add(env, auth, "Acme ships widgets.")
    env.server.reflector = _ScriptedReflector([
        ObservationDraft(text="Maya moved on from Acme", confidence=0.9,
                         fact_ids=(first, second)),
    ])
    status, _h, _b = env.post_json("/memory/reflect", {}, auth)
    assert status == 200, status
    [card] = [c for c in env.server.inbox.waiting()
              if c.kind == "memory_reflection"]

    _forget_everything(env, auth)

    assert _rows(memory) == (0, 0, 0, 0, 0), _rows(memory)
    assert env.server.inbox.waiting() == [], "no reflection outlives its facts"
    assert env.server.inbox.get(card.id).status == "dismissed"


def test_a_locked_store_answers_a_form_post_with_the_locked_page_never_json(tmp_path):
    import sqlite3
    import time

    from nexuusbot.memory.crypto import load_key
    from nexuusbot.memory.store import MemoryStore

    # A bank sealed in a previous life, reopened without its key.
    db = tmp_path / "memory.sqlite3"
    first = sqlite3.connect(str(db), check_same_thread=False)
    seeded = MemoryStore(first, time.time, key=load_key(bytes(range(32))))
    seeded.add("revenue is 220", source="page")
    first.close()
    conn = sqlite3.connect(str(db), check_same_thread=False)
    store = MemoryStore(conn, time.time, key_path=tmp_path / "memory.key")
    assert store.locked_cause is not None
    booted = server_harness.Booted(memory_store=store, llm=CaptureLlm())
    auth = booted.exchange()
    try:
        status, headers, body = _post_form(booted, auth, "/memory/forget-all",
                                           {"confirm": "yes"})
        page = body.decode("utf-8")
        assert status == 200, status
        assert "text/html" in headers.get("Content-Type", ""), headers
        assert '"error"' not in page, "a browser form never meets raw JSON"
        assert "Memory is locked" in page
        assert "key file is missing" in page

        # The same post as fetch still gets the JSON cause.
        status, _h, body = booted.post_json("/memory/forget-all",
                                            {"confirm": "yes"}, auth)
        assert status == 503, status
        assert json.loads(body)["error"] == store.locked_cause
    finally:
        booted.close()
        conn.close()


def _forget_all_rows(env, auth):
    """The forget-all audit rows in the export, as (target, detail) fields."""
    status, _h, export = env.request("GET", "/audit/export.csv", auth)
    assert status == 200
    return [line.split(",") for line in export.decode("utf-8").splitlines()
            if "memory.forget_all" in line]


def test_two_confirmed_posts_back_to_back_both_answer_and_one_row_names_it(env, auth):
    memory = env.server.memory
    _a_bank_with_everything_derived(env, auth)
    first = _post_form(env, auth, "/memory/forget-all", {"confirm": "yes"})
    second = _post_form(env, auth, "/memory/forget-all", {"confirm": "yes"})
    assert first[0] == 303 and second[0] == 303, (first[0], second[0])
    assert _rows(memory) == (0, 0, 0, 0, 0), _rows(memory)
    [row] = _forget_all_rows(env, auth)
    assert row[2] == "3 facts", row
    status, _h, page = env.request("GET", "/memory", auth)
    assert "Memory is empty" in page.decode("utf-8")


def test_two_confirmed_posts_at_the_same_time_both_answer_without_error(env, auth):
    import threading

    memory = env.server.memory
    _a_bank_with_everything_derived(env, auth)
    answers = []

    def fire() -> None:
        answers.append(_post_form(env, auth, "/memory/forget-all",
                                  {"confirm": "yes"}))

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(answers) == 2
    for status, _h, _b in answers:
        assert status < 500, status
    assert _rows(memory) == (0, 0, 0, 0, 0), _rows(memory)
    rows = _forget_all_rows(env, auth)
    # One row names what went; a racing second row may only say nothing
    # was left. Nothing else is acceptable.
    assert [row for row in rows if row[2] == "3 facts"], rows
    for row in rows:
        assert row[2] in ("3 facts", "0 facts"), row


# -- each fact: where it came from, and its own Forget -----------------------


class ReplyLlm:
    """Answers the turn; the extraction prompt gets one durable fact."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "durable memory facts" in prompt:
            return json.dumps({"facts": [{"text": "The Berlin office has 40 people.", "kind": "world"}]})
        return "Noted."


def test_a_fact_learned_from_a_turn_is_listed_with_its_origin_and_a_forget(env, auth):
    env.server.llm = ReplyLlm()
    typed = _add(env, auth, "The Acme renewal is due December 15.")
    env.post_json("/assistant/ask", {"question": "The Berlin office has 40 people."}, auth)
    [learned] = [f for f in env.server.memory.all() if f.text == "The Berlin office has 40 people."]
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    row = _element(page, f"id='fact-{learned.id}'", "</div>")
    words = _words(row)
    assert "The Berlin office has 40 people." in " ".join(words)
    assert "Assistant, saved automatically, saved" in " ".join(words), " ".join(words)
    assert re.search(rf"action=['\"]/memory/{learned.id}/delete['\"]", row), row
    assert re.search(r">Forget</button>", row), row
    # A typed fact says so, and still edits and forgets on its own row.
    typed_row = _element(page, f"id='fact-{typed}'", "</div>")
    assert "Typed on this page" in " ".join(_words(typed_row))
    assert re.search(rf"action=['\"]/memory/{typed}/edit['\"]", typed_row)
    assert re.search(rf"action=['\"]/memory/{typed}/delete['\"]", typed_row)
    # The stored bookkeeping never reaches the page in its raw form.
    assert "auto:" not in page


def test_forgetting_one_fact_from_its_row_removes_that_fact_only(env, auth):
    kept = _add(env, auth, "The Acme renewal is due December 15.")
    gone = _add(env, auth, "The Berlin office has 40 people.")
    status, headers, _b = _post_form(env, auth, f"/memory/{gone}/delete", {})
    assert (status, headers["Location"].split("?", 1)[0]) == (303, "/memory")
    assert [fact.id for fact in env.server.memory.all()] == [kept]


# -- the maintenance tools ---------------------------------------------------


TOOLS = ("/memory/graph", "/memory/sweep", "/memory/encrypt")


def _disclosures(page):
    """Every disclosure on the page, each as (its opening tag, its inside)."""
    found = []
    for block in re.findall(r"<details[^>]*>.*?</details>", page, re.S):
        opening, inside = block.split(">", 1)
        found.append((opening, inside))
    return found


def test_the_graph_the_sweep_and_encryption_sit_behind_one_maintenance_disclosure(env, auth):
    _add(env, auth, "The Acme renewal is due December 15.")
    status, _h, body = env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    [(opening, tile)] = _disclosures(page)
    assert "Maintenance" in tile.split("</summary>", 1)[0]
    assert " open" not in opening, "folded away until asked for"
    outside = page.replace(opening + ">" + tile, "")
    for address in TOOLS:
        assert address in tile, address
        assert address not in outside, f"{address} is offered outside the disclosure"
    assert 'id="memory-graph-root"' not in outside
    assert "Show in graph" not in page


def test_a_maintenance_tool_shows_its_own_result_inside_the_open_disclosure(env, auth):
    memory = env.server.memory
    _add(env, auth, "I do not have any information about that.")
    _add(env, auth, "revenue is checked every monday")
    _add(env, auth, "revenue is 220")
    memory.add_source("we met Tuesday")

    # The sweep's preview, at its own address.
    status, _h, body = env.request("GET", "/memory/sweep", auth)
    assert status == 200
    page = body.decode("utf-8")
    [(opening, tile)] = _disclosures(page)
    assert " open" in opening, "a result the user asked for is shown, not folded away"
    assert 'action="/memory/sweep"' in tile.replace("'", '"')
    assert 'name="sweep_1"' in tile or "name='sweep_1'" in tile
    assert 'name="sweep_2"' not in tile and "name='sweep_2'" not in tile

    # The recall check's answer.
    status, _h, body = _post_form(env, auth, "/memory/recall", {"query": "revenue 220"})
    assert status == 200
    page = body.decode("utf-8")
    [(opening, tile)] = _disclosures(page)
    assert " open" in opening
    preview = _element(tile, "id='recall-preview'", "</ol>")
    assert "revenue is 220" in preview and "revenue is checked every monday" in preview

    # Encryption's dry run, with its confirm checkbox.
    status, _h, body = env.request("GET", "/memory/encrypt", auth)
    assert status == 200
    page = body.decode("utf-8")
    [(opening, tile)] = _disclosures(page)
    assert " open" in opening
    assert "name='confirm'" in tile or 'name="confirm"' in tile
    for count in ("3 facts", "1 source"):
        assert count in tile, count
