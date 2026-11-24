"""The retain seam over HTTP: extraction into approval cards.

These tests drive the real server with an injected fake extractor (the
spec's second seam): one card per surviving candidate sharing one
source id, acceptance writing exactly one fact with the edited draft
and its resolved graph, dismissal writing nothing, both extractor
failures leaving the bank byte-identical, the endpoint gate, the audit
rows, and the chat surface's button. The legacy "fact" meta path is
covered by test_server_memory_api.py and must stay green untouched.
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
from agentdesk.assistant import audit as audit_store
from agentdesk.llm import LlmUnavailable
from agentdesk.memory.extract import (
    EXTRACTION_SYSTEM_PROMPT,
    ExtractionFailed,
    ExtractorUnavailable,
    CandidateFact,
)


class FakeExtractor:
    """The scripted extractor the boot injects: records every call and
    answers with the given candidates, or raises the given error."""

    def __init__(self, candidates=(), error=None) -> None:
        self.calls = []
        self.candidates = list(candidates)
        self.error = error

    def extract(self, content, speaker="", context="", mentioned_at=None):
        self.calls.append(
            {"content": content, "speaker": speaker, "context": context,
             "mentioned_at": mentioned_at}
        )
        if self.error is not None:
            raise self.error
        return list(self.candidates)


class ScriptedLlm:
    """A prompt-to-text callable for testing the built-in extractor end
    to end through the llm seam."""

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.prompts: list[str] = []
        self.reply = reply
        self.error = error

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


MAYA = CandidateFact(
    text="Maya lives in Pune",
    kind="world",
    entities=(("Maya Rahman", "person"),),
)
ACME = CandidateFact(text="Acme ships widgets", kind="world")
MEMO = CandidateFact(text="I drafted the memo", kind="experience")


def _file_memory(tmp_path):
    path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(str(path), check_same_thread=False)
    from agentdesk.memory.store import MemoryStore

    return MemoryStore(conn, time.time), path


@pytest.fixture()
def boot(tmp_path):
    """A boot with a file-backed memory bank (so byte-identity can be
    asserted) and no extractor; tests inject one via boot.extractor."""
    memory, path = _file_memory(tmp_path)
    booted = server_harness.Booted(memory_store=memory)
    booted._bank_path = path
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(boot):
    return boot.exchange()


def _inject(boot, extractor) -> None:
    boot.server.extractor = extractor


def _retain(boot, auth, excerpt="You: we met Tuesday and Maya said she lives in Pune", **overrides):
    payload = {"excerpt": excerpt}
    payload.update(overrides)
    return boot.post_json("/memory/retain", payload, auth)


def _bank_bytes(boot) -> bytes:
    return boot._bank_path.read_bytes()


def _audit_rows(boot, action):
    return [e for e in audit_store.entries(boot.server.audit_conn) if e["action"] == action]


def _sources(boot):
    rows = boot.server.memory.conn.execute(
        "SELECT id, text, speaker, context FROM sources ORDER BY id"
    ).fetchall()
    return list(rows)


def _entities(boot):
    rows = boot.server.memory.conn.execute(
        "SELECT id, canonical_name, type FROM entities ORDER BY id"
    ).fetchall()
    return list(rows)


def _edges(boot):
    rows = boot.server.memory.conn.execute(
        "SELECT fact_id, entity_id FROM edges ORDER BY fact_id, entity_id"
    ).fetchall()
    return list(rows)


# -- the retain route: cards from candidates -------------------------------


def test_three_candidates_become_three_editable_cards_sharing_one_source(boot, auth):
    extractor = FakeExtractor([MAYA, ACME, MEMO])
    _inject(boot, extractor)
    status, _h, body = _retain(boot, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    cards = boot.server.inbox.waiting()
    assert [c.kind for c in cards] == ["memory_draft"] * 3
    assert [c.draft for c in cards] == [MAYA.text, ACME.text, MEMO.text]
    source_ids = {c.meta["memoryFact"]["source_id"] for c in cards}
    assert len(source_ids) == 1
    source_row = _sources(boot)
    assert len(source_row) == 1
    assert source_row[0][1].startswith("You: we met Tuesday")
    # The structured meta carries what acceptance needs.
    maya_card = cards[0]
    fact_meta = maya_card.meta["memoryFact"]
    assert fact_meta["kind"] == "world"
    assert fact_meta["occurrence_ts"] is None
    assert fact_meta["entities"] == [["Maya Rahman", "person"]]
    assert payload["sourceId"] == source_row[0][0]
    # The extract call carried the posted excerpt.
    assert extractor.calls[0]["content"].startswith("You: we met Tuesday")


def test_the_inbox_page_renders_memory_cards_as_editable_drafts(boot, auth):
    _inject(boot, FakeExtractor([MAYA]))
    _retain(boot, auth)
    status, _h, body = boot.request("GET", "/inbox", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "Save to memory" in page
    assert "Maya lives in Pune" in page
    card_id = boot.server.inbox.waiting()[0].id
    assert f"id='draft-{card_id}' name='draft'" in page


def test_the_extract_call_is_audited_as_llm_retain(boot, auth):
    _inject(boot, FakeExtractor([MAYA]))
    _retain(boot, auth)
    rows = _audit_rows(boot, "llm.retain")
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"


# -- acceptance: one fact, its graph, one audit row -------------------------


def test_accepting_an_edited_card_writes_exactly_one_fact_with_its_graph(boot, auth):
    when = 1700000000.0
    candidate = CandidateFact(
        text="Maya joined the Tuesday review",
        kind="experience",
        occurrence_ts=when,
        entities=(("Maya Rahman", "person"),),
    )
    _inject(boot, FakeExtractor([candidate, ACME]))
    _retain(boot, auth, excerpt="You: Maya joined the Tuesday review")
    cards = boot.server.inbox.waiting()
    assert len(cards) == 2
    source_id = cards[0].meta["memoryFact"]["source_id"]
    # The user edits the draft before accepting.
    status, _h, _b = boot.post_json(
        f"/inbox/cards/{cards[0].id}/edit", {"draft": "I ran the Tuesday review"}, auth
    )
    assert status == 200
    status, _h, _b = boot.post_json(f"/inbox/cards/{cards[0].id}/accept", {}, auth)
    assert status == 200
    facts = boot.server.memory.all()
    assert [f.text for f in facts] == ["I ran the Tuesday review"]
    assert facts[0].kind == "experience"
    assert facts[0].occurrence_ts == pytest.approx(when)
    assert facts[0].source_id == source_id
    assert facts[0].source.startswith("inbox card ")
    # The mention edge resolved to a canonical entity.
    assert _entities(boot) == [(1, "Maya Rahman", "person")]
    assert _edges(boot) == [(facts[0].id, 1)]
    rows = _audit_rows(boot, "memory.fact")
    assert len(rows) == 1
    assert rows[0]["detail"].startswith("inbox card ")
    # The untouched sibling card is still waiting.
    assert [c.draft for c in boot.server.inbox.waiting()] == [ACME.text]


def test_dismissing_a_memory_card_writes_nothing(boot, auth):
    _inject(boot, FakeExtractor([MAYA]))
    _retain(boot, auth)
    (card,) = boot.server.inbox.waiting()
    status, _h, _b = boot.post_json(f"/inbox/cards/{card.id}/dismiss", {}, auth)
    assert status == 200
    assert boot.server.memory.all() == []
    assert _entities(boot) == []
    assert _edges(boot) == []
    assert _sources(boot) != []  # the retain itself wrote the source
    assert _audit_rows(boot, "memory.fact") == []


# -- failure modes: the bank stays untouched --------------------------------


def test_an_endpoint_failure_leaves_the_bank_byte_identical(boot, auth):
    cause = "could not resolve the host llm.example.com: check the base URL"
    _inject(boot, FakeExtractor(error=ExtractorUnavailable(cause)))
    before = _bank_bytes(boot)
    status, _h, body = _retain(boot, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "degraded"
    assert cause in payload["cause"]
    assert boot.server.inbox.waiting() == []
    assert boot.server.memory.all() == []
    assert _sources(boot) == []
    assert _bank_bytes(boot) == before
    rows = _audit_rows(boot, "llm.retain")
    assert len(rows) == 1
    assert rows[0]["status"] == "error"


def test_an_unusable_payload_leaves_the_bank_byte_identical(boot, auth):
    cause = "Extractor returned invalid JSON. Nothing was written."
    _inject(boot, FakeExtractor(error=ExtractionFailed(cause)))
    before = _bank_bytes(boot)
    status, _h, body = _retain(boot, auth)
    payload = json.loads(body)
    assert payload["status"] == "degraded"
    assert cause in payload["cause"]
    assert boot.server.inbox.waiting() == []
    assert _sources(boot) == []
    assert _bank_bytes(boot) == before


def test_a_blank_excerpt_is_refused_without_calling_the_extractor(boot, auth):
    extractor = FakeExtractor([MAYA])
    _inject(boot, extractor)
    before = _bank_bytes(boot)
    status, _h, _b = _retain(boot, auth, excerpt="   ")
    assert status == 400
    assert extractor.calls == []
    assert _bank_bytes(boot) == before


# -- the donor post-filters at the seam --------------------------------------


def test_knowledge_gap_candidates_never_become_cards(boot, auth):
    gap = CandidateFact(text="I do not have any information about that.", kind="world")
    _inject(boot, FakeExtractor([gap, MAYA]))
    _retain(boot, auth)
    cards = boot.server.inbox.waiting()
    assert [c.draft for c in cards] == [MAYA.text]


def test_six_candidates_cap_at_five(boot, auth):
    candidates = [
        CandidateFact(text=f"Maya keeps harbor note {n}.", kind="world")
        for n in range(6)
    ]
    _inject(boot, FakeExtractor(candidates))
    _retain(boot, auth)
    assert len(boot.server.inbox.waiting()) == 5


def test_an_occurrence_survives_only_when_the_excerpt_names_one(boot, auth):
    when = 1700000000.0
    dated = CandidateFact(text="Maya joined the review", kind="world",
                          occurrence_ts=when)
    # The excerpt names an occurrence: the extracted time is kept.
    _inject(boot, FakeExtractor([dated]))
    _retain(boot, auth, excerpt="You: we met Maya on Tuesday")
    (card,) = boot.server.inbox.waiting()
    assert card.meta["memoryFact"]["occurrence_ts"] == pytest.approx(when)
    boot.server.inbox.dismiss(card.id)
    # A clock time or a preference in the fact is not an occurrence
    # when the excerpt itself names none.
    _inject(boot, FakeExtractor([dated]))
    _retain(boot, auth, excerpt="You: Maya says the review matters")
    (card,) = boot.server.inbox.waiting()
    assert card.meta["memoryFact"]["occurrence_ts"] is None


def test_no_surviving_candidates_writes_nothing(boot, auth):
    gap = CandidateFact(text="I'm not sure who that is.", kind="world")
    _inject(boot, FakeExtractor([gap]))
    before = _bank_bytes(boot)
    status, _h, body = _retain(boot, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["cards"] == []
    assert payload["sourceId"] is None
    assert _sources(boot) == []
    assert _bank_bytes(boot) == before


# -- the gate, and the built-in extractor over the llm seam ------------------


def test_endpoint_disabled_blocks_the_action_before_any_call(boot, auth):
    boot.server.settings.set("endpoint_enabled", False)
    extractor = FakeExtractor([MAYA])
    _inject(boot, extractor)
    before = _bank_bytes(boot)
    status, _h, body = _retain(boot, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "degraded"
    assert "turned off in settings" in payload["cause"]
    assert extractor.calls == []
    assert boot.server.inbox.waiting() == []
    assert _bank_bytes(boot) == before
    assert _audit_rows(boot, "llm.retain") == []


def test_without_an_injection_the_builtin_extractor_rides_the_llm_seam(boot, auth):
    payload_json = json.dumps(
        {
            "facts": [
                {"text": "Maya lives in Pune", "kind": "world",
                 "entities": [{"name": "Maya Rahman", "type": "person"}]}
            ]
        }
    )
    boot.server.llm = ScriptedLlm(reply=payload_json)
    status, _h, _b = _retain(boot, auth)
    assert status == 200
    cards = boot.server.inbox.waiting()
    assert [c.draft for c in cards] == ["Maya lives in Pune"]
    (prompt,) = boot.server.llm.prompts
    assert prompt.startswith(EXTRACTION_SYSTEM_PROMPT)
    assert "content:\nYou: we met Tuesday" in prompt
    row = _audit_rows(boot, "llm.retain")[0]
    assert row["status"] == "ok"
    assert row["request_bytes"] == len(prompt.encode("utf-8"))


def test_an_endpoint_failure_through_the_seam_degrades_in_plain_language(boot, auth):
    cause = "no AI connection is saved"
    boot.server.llm = ScriptedLlm(error=LlmUnavailable(cause))
    status, _h, body = _retain(boot, auth)
    payload = json.loads(body)
    assert payload["status"] == "degraded"
    assert cause in payload["cause"]
    assert boot.server.inbox.waiting() == []
    assert _sources(boot) == []


# -- the chat surface --------------------------------------------------------


def test_the_assistant_page_offers_save_to_memory_with_the_turn_structure(boot, auth):
    boot.server.llm = ScriptedLlm(reply="A short answer.")
    boot.post_json("/assistant/ask", {"question": "what changed?"}, auth)
    status, _h, body = boot.request("GET", "/assistant", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert 'action="/memory/retain"' in page
    assert "Save to memory" in page
    assert "You: what changed?" in page
    assert "Assistant: A short answer." in page


def test_the_posted_excerpt_stays_bounded(boot, auth):
    long_question = "word " * 200  # ~1000 characters per turn
    for _ in range(6):
        boot.post_json("/assistant/ask", {"question": long_question}, auth)
    from agentdesk.server.research import RETAIN_EXCERPT_MAX_CHARS

    status, _h, body = boot.request("GET", "/assistant", auth)
    page = body.decode("utf-8")
    start = page.index('name="excerpt" value="') + len('name="excerpt" value="')
    end = page.index('"', start)
    # The rendered attribute is escaped; its length still bounds the
    # excerpt's own length from above.
    assert end - start <= RETAIN_EXCERPT_MAX_CHARS * 1.2


def test_a_form_post_from_the_chat_surface_lands_in_the_inbox(boot, auth):
    _inject(boot, FakeExtractor([MAYA]))
    body = "excerpt=You%3A+we+met+Tuesday".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, headers_out, _b = boot.request("POST", "/memory/retain", headers, body)
    assert status == 303
    assert headers_out["Location"].split("?", 1)[0] == "/inbox"
    (card,) = boot.server.inbox.waiting()
    assert card.draft == MAYA.text


def test_a_form_post_failure_renders_a_plain_language_error(boot, auth):
    cause = "the endpoint failed on its own side (HTTP 500); nothing is wrong with the key or the base URL"
    _inject(boot, FakeExtractor(error=ExtractorUnavailable(cause)))
    body = "excerpt=You%3A+we+met+Tuesday".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, _h, page = boot.request("POST", "/memory/retain", headers, body)
    assert status == 502
    text = page.decode("utf-8")
    assert "Save to memory" in text
    assert cause in text
    assert boot.server.inbox.waiting() == []
    assert _sources(boot) == []


def test_a_form_post_with_the_gate_off_refuses_like_the_mail_surfaces(boot, auth):
    boot.server.settings.set("endpoint_enabled", False)
    body = "excerpt=You%3A+we+met+Tuesday".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, _h, page = boot.request("POST", "/memory/retain", headers, body)
    assert status == 409
    assert "turned off in settings" in page.decode("utf-8")
