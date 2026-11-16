"""The reflect seam over HTTP (ticket #93): derived observations into
approval cards.

These tests drive the real server with a scripted reflector (the
retained tests' second seam, reused): one card per surviving
observation citing the gathered fact ids, acceptance writing the
observation with the EDITED draft text and its citations, dismissal
writing nothing, every filter rejection counting itself out of the
payload, re-reflecting the same scope upserting and dropping unkept
rows, the empty gather and both reflector failures leaving the bank
untouched with a plain-language notice, the llm.reflect and
memory.observation audit rows, the memory page's observations section,
and the same flow over a sealed bank. The memory page renders
server-side, so its observations section is asserted here too.
"""

import json
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.llm import LlmUnavailable
from agentdesk.memory.crypto import load_key
from agentdesk.memory.reflect import (
    REFLECT_SYSTEM_PROMPT,
    ObservationDraft,
    ReflectFailed,
    ReflectorUnavailable,
)
from agentdesk.memory.store import MemoryStore

KEY = load_key(bytes(range(32)))


class FakeReflector:
    """The scripted reflector the boot injects: records every call and
    answers with the given drafts, or raises the given error."""

    def __init__(self, drafts=(), error=None) -> None:
        self.calls = []
        self.drafts = list(drafts)
        self.error = error

    def reflect(self, topic, facts):
        self.calls.append({"topic": topic, "fact_ids": [f.id for f in facts]})
        if self.error is not None:
            raise self.error
        return list(self.drafts)


class ScriptedLlm:
    """A prompt-to-text callable for testing the built-in reflector end
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


def _draft(text, confidence=0.9, fact_ids=(1, 2)) -> ObservationDraft:
    return ObservationDraft(text=text, confidence=confidence, fact_ids=fact_ids)


def _file_memory(tmp_path, key=None):
    path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(str(path), check_same_thread=False)
    store = MemoryStore(conn, time.time, key=key)
    return store, path


@pytest.fixture()
def boot(tmp_path):
    """A boot with a file-backed memory bank (so byte-identity can be
    asserted) and no reflector; tests inject one via boot.server."""
    memory, path = _file_memory(tmp_path)
    booted = server_harness.Booted(memory_store=memory)
    booted._bank_path = path
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def sealed_boot(tmp_path):
    """A boot whose memory bank is encrypted at rest from the start."""
    memory, path = _file_memory(tmp_path, key=KEY)
    booted = server_harness.Booted(memory_store=memory)
    booted._bank_path = path
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(boot):
    return boot.exchange()


@pytest.fixture()
def sealed_auth(sealed_boot):
    return sealed_boot.exchange()


def _seed(boot, texts):
    return [boot.server.memory.add(text, source="page") for text in texts]


def _inject(boot, reflector) -> None:
    boot.server.reflector = reflector


def _reflect(boot, auth, **overrides):
    payload = overrides.pop("payload", {})
    payload.update(overrides)
    return boot.post_json("/memory/reflect", payload, auth)


def _bank_bytes(boot) -> bytes:
    return boot._bank_path.read_bytes()


def _audit_rows(boot, action):
    return [
        e for e in audit_store.entries(boot.server.audit_conn)
        if e["action"] == action
    ]


def _observations(boot):
    return boot.server.memory.observations()


def _raw_observation_rows(boot):
    return boot.server.memory.conn.execute(
        "SELECT id, scope_key, text, text_enc, confidence FROM observations"
        " ORDER BY id"
    ).fetchall()


# -- the reflect route: cards from drafts -------------------------------------


def test_one_card_per_surviving_observation_citing_the_gathered_facts(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets", "Pune is home"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
        _draft("Acme ships on a weekly rhythm", 0.7, (facts[1].id, facts[2].id)),
    ]))
    status, _h, body = _reflect(boot, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["rejected"] == 0
    cards = boot.server.inbox.waiting()
    assert [c.kind for c in cards] == ["memory_reflection"] * 2
    assert [c.draft for c in cards] == [
        "Maya moved on from Acme", "Acme ships on a weekly rhythm",
    ]
    assert [c.action_label for c in cards] == ["Save observation"] * 2
    # The recency gather handed the reflector every seeded fact, newest
    # first, with no topic line.
    (call,) = _inject_calls(boot)
    assert call["topic"] == ""
    assert call["fact_ids"] == [fact.id for fact in reversed(facts)]
    # The card body names the cited facts' texts and the meta carries
    # what acceptance writes.
    first = cards[0]
    assert facts[0].text in first.body and facts[1].text in first.body
    assert facts[2].text not in first.body
    meta = first.meta["memoryObservation"]
    assert meta["confidence"] == 0.9
    assert meta["source_fact_ids"] == [facts[0].id, facts[1].id]
    assert isinstance(meta["scope_key"], str) and meta["scope_key"]


def _inject_calls(boot):
    return boot.server.reflector.calls


def test_the_reflect_call_is_audited_as_llm_reflect(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([_draft("Maya moved on from Acme")]))
    _reflect(boot, auth)
    rows = _audit_rows(boot, "llm.reflect")
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"


def test_without_an_injection_the_builtin_reflector_rides_the_llm_seam(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    facts = boot.server.memory.all()
    reply = json.dumps({
        "observations": [
            {"text": "Maya moved on from Acme", "confidence": 0.9,
             "sourceFactIds": [facts[0].id, facts[1].id]},
        ]
    })
    boot.server.llm = ScriptedLlm(reply=reply)
    status, _h, _b = _reflect(boot, auth)
    assert status == 200
    (card,) = boot.server.inbox.waiting()
    assert card.draft == "Maya moved on from Acme"
    (prompt,) = boot.server.llm.prompts
    assert prompt.startswith(REFLECT_SYSTEM_PROMPT + "\n\n")
    assert "Facts:\n" in prompt
    row = _audit_rows(boot, "llm.reflect")[0]
    assert row["status"] == "ok"
    assert row["request_bytes"] > 0


# -- acceptance: one observation, its citations, one audit row ----------------


def test_accepting_an_edited_card_writes_the_observation_with_citations(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
    ]))
    _reflect(boot, auth)
    (card,) = boot.server.inbox.waiting()
    boot.post_json(f"/inbox/cards/{card.id}/edit",
                   {"draft": "Maya moved on for good"}, auth)
    status, _h, _b = boot.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    assert status == 200
    stored = _observations(boot)
    assert len(stored) == 1
    assert stored[0].text == "Maya moved on for good", "the edited draft is what lands"
    assert stored[0].confidence == 0.9
    assert stored[0].fact_ids == (facts[0].id, facts[1].id)
    rows = _audit_rows(boot, "memory.observation")
    assert len(rows) == 1
    assert rows[0]["target"] == str(stored[0].id)


def test_dismissing_a_reflection_card_writes_nothing(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    before = _bank_bytes(boot)
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
    ]))
    _reflect(boot, auth)
    (card,) = boot.server.inbox.waiting()
    status, _h, _b = boot.post_json(f"/inbox/cards/{card.id}/dismiss", {}, auth)
    assert status == 200
    assert card.id in {c.id for c in boot.server.inbox.dismissed()}
    assert _observations(boot) == []
    assert _audit_rows(boot, "memory.observation") == []
    assert _bank_bytes(boot) == before


def test_a_card_whose_cited_facts_vanished_writes_nothing_on_accept(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
    ]))
    _reflect(boot, auth)
    (card,) = boot.server.inbox.waiting()
    boot.server.memory.delete(facts[0].id)
    boot.server.memory.delete(facts[1].id)
    status, _h, _b = boot.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    assert status == 200
    assert _observations(boot) == []
    assert _audit_rows(boot, "memory.observation") == []


# -- the acceptance filters over the wire -------------------------------------


def test_speculative_and_meta_drafts_are_rejected(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets", "Pune is home"])
    ids = (facts[0].id, facts[1].id)
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, ids),
        _draft("Acme might ship in December", 0.9, ids),
        _draft("Acme is separate from the Pune office", 0.9, ids),
        _draft("Acme ships on a weekly rhythm", 0.8, ids),
    ]))
    payload = json.loads(_reflect(boot, auth)[2])
    cards = boot.server.inbox.waiting()
    assert [c.draft for c in cards] == [
        "Maya moved on from Acme", "Acme ships on a weekly rhythm",
    ]
    assert payload["rejected"] == 2


def test_when_nothing_survives_the_notice_says_so_and_writes_nothing(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    before = _bank_bytes(boot)
    ids = (facts[0].id, facts[1].id)
    _inject(boot, FakeReflector([_draft("Acme might ship in December", 0.9, ids)]))
    status, _h, body = _reflect(boot, auth)
    # Degraded, not errored: retain's JSON surface for a model turn
    # that produced nothing usable.
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "degraded"
    assert "Nothing was written" in payload["cause"]
    assert boot.server.inbox.waiting() == []
    # The reflector call itself still happened, and is audited.
    assert [r["status"] for r in _audit_rows(boot, "llm.reflect")] == ["ok"]
    assert _bank_bytes(boot) == before


def test_single_fact_citations_are_rejected_outside_a_single_entity_scope(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
        _draft("Maya moved on her own", 0.9, (facts[0].id,)),
    ]))
    payload = json.loads(_reflect(boot, auth)[2])
    (card,) = boot.server.inbox.waiting()
    assert card.draft == "Maya moved on from Acme"
    assert payload["rejected"] == 1


def test_a_single_entity_scope_allows_one_citation(boot, auth):
    _seed(boot, ["Maya left Acme", "Maya joined the review"])
    facts = boot.server.memory.all()
    _inject(boot, FakeReflector([_draft("Maya moved on", 0.9, (facts[0].id,))]))
    status, _h, body = _reflect(boot, auth, entity="Maya")
    payload = json.loads(body)
    assert payload["rejected"] == 0
    (card,) = boot.server.inbox.waiting()
    assert card.draft == "Maya moved on"
    # The single-entity scope rides the query path and names the topic.
    (call,) = _inject_calls(boot)
    assert call["topic"] == "Maya"
    assert call["fact_ids"], "the entity query gathered facts"


def test_near_duplicates_collapse_keeping_the_higher_confidence(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    ids = (facts[0].id, facts[1].id)
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.6, ids),
        _draft("  maya   moved on from Acme ", 0.95, ids),
    ]))
    payload = json.loads(_reflect(boot, auth)[2])
    (card,) = boot.server.inbox.waiting()
    assert card.draft == "maya   moved on from Acme"
    assert card.meta["memoryObservation"]["confidence"] == 0.95
    assert payload["rejected"] == 1, "the collapsed twin made no card"


def test_citing_a_fact_outside_the_gather_rejects_the_draft(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
        _draft("Citing an ungathered fact", 0.9, (facts[1].id, 999)),
    ]))
    payload = json.loads(_reflect(boot, auth)[2])
    (card,) = boot.server.inbox.waiting()
    assert card.draft == "Maya moved on from Acme"
    assert payload["rejected"] == 1


# -- re-reflecting the same scope ---------------------------------------------


def test_re_reflecting_updates_matching_and_removes_unkept(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets", "Pune is home"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.8, (facts[0].id, facts[1].id)),
        _draft("Acme ships on a weekly rhythm", 0.7, (facts[1].id, facts[2].id)),
    ]))
    _reflect(boot, auth)
    for card in boot.server.inbox.waiting():
        boot.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    assert len(_observations(boot)) == 2
    # A second run re-derives only the first observation (same words,
    # new confidence); nothing returns the second one.
    _inject(boot, FakeReflector([
        _draft("  maya moved on from acme ", 0.95, (facts[0].id, facts[1].id)),
    ]))
    _reflect(boot, auth)
    (card,) = boot.server.inbox.waiting()
    boot.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    stored = _observations(boot)
    assert len(stored) == 1, "the unre-derived observation went"
    assert stored[0].text == "maya moved on from acme"
    assert stored[0].confidence == 0.95


# -- the plain-language failure surfaces ---------------------------------------


def test_an_empty_gather_is_a_plain_error_and_writes_nothing(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    before = _bank_bytes(boot)
    _inject(boot, FakeReflector([_draft("Nothing to see")]))
    status, _h, body = _reflect(boot, auth, topic="zzz unmatched topic")
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "degraded"
    assert "found no facts in that scope" in payload["cause"]
    assert boot.server.inbox.waiting() == []
    assert _observations(boot) == []
    # No reflector call, so no model audit row either.
    assert _audit_rows(boot, "llm.reflect") == []
    assert _bank_bytes(boot) == before


def test_a_reflector_unavailable_failure_surfaces_a_plain_notice(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    before = _bank_bytes(boot)
    cause = "the endpoint did not answer; nothing was written"
    _inject(boot, FakeReflector(error=ReflectorUnavailable(cause)))
    status, _h, body = _reflect(boot, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "degraded"
    assert cause in payload["cause"]
    assert boot.server.inbox.waiting() == []
    assert [r["status"] for r in _audit_rows(boot, "llm.reflect")] == ["error"]
    assert _bank_bytes(boot) == before


def test_a_reflector_failed_payload_surfaces_a_plain_notice(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector(error=ReflectFailed("bad payload. Nothing was written.")))
    status, _h, body = _reflect(boot, auth)
    assert status == 200
    payload = json.loads(body)
    assert "bad payload" in payload["cause"]
    assert [r["status"] for r in _audit_rows(boot, "llm.reflect")] == ["error"]
    assert boot.server.inbox.waiting() == []


def test_a_broken_reply_through_the_llm_seam_surfaces_a_plain_notice(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    boot.server.llm = ScriptedLlm(reply="not json at all")
    status, _h, body = _reflect(boot, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "degraded"
    assert "Nothing was written" in payload["cause"]
    assert [r["status"] for r in _audit_rows(boot, "llm.reflect")] == ["error"]


def test_an_unreachable_llm_through_the_seam_names_the_cause(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    boot.server.llm = ScriptedLlm(error=LlmUnavailable("the endpoint is down"))
    status, _h, body = _reflect(boot, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "degraded"
    assert "the endpoint is down" in payload["cause"]


def test_the_endpoint_gate_blocks_reflect_before_any_call(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    boot.server.settings.set("endpoint_enabled", False)
    _inject(boot, FakeReflector([_draft("Maya moved on from Acme")]))
    before = _bank_bytes(boot)
    status, _h, body = _reflect(boot, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "degraded"
    assert "turned off in settings" in payload["cause"]
    assert _inject_calls(boot) == []
    assert boot.server.inbox.waiting() == []
    assert _audit_rows(boot, "llm.reflect") == []
    assert _bank_bytes(boot) == before


# -- the scope: since, until, and the form -------------------------------------


def test_since_and_until_bounds_flow_into_the_gather(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    # A window past every fact gathers nothing.
    status, _h, body = _reflect(boot, auth, since="2030-01-01")
    assert status == 200
    assert "found no facts" in json.loads(body)["cause"]
    # A window covering everything gathers, and the scope key carries
    # the epoch bounds so a later re-reflect with the same window
    # upserts against the same scope.
    facts = boot.server.memory.all()
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
    ]))
    status, _h, body = _reflect(
        boot, auth, since="2000-01-01", until="2030-01-01"
    )
    assert status == 200
    (card,) = boot.server.inbox.waiting()
    parts = card.meta["memoryObservation"]["scope_key"].split("\n")
    assert len(parts) == 5
    assert parts[:3] == ["", "", ""]
    assert float(parts[3]) == datetime(2000, 1, 1, tzinfo=UTC).timestamp()
    assert float(parts[4]) == datetime(2030, 1, 1, tzinfo=UTC).timestamp()


def test_an_unreadable_window_bound_is_a_plain_400(boot, auth):
    _seed(boot, ["Maya left Acme"])
    _inject(boot, FakeReflector([_draft("Maya moved on from Acme")]))
    status, _h, body = _reflect(boot, auth, since="sometime soon")
    assert status == 400
    assert "ISO-8601" in json.loads(body)["error"]
    assert _inject_calls(boot) == []


def test_a_form_post_reflect_lands_in_the_inbox(boot, auth):
    _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([_draft("Maya moved on from Acme", 0.9, None)]))
    facts = boot.server.memory.all()
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
    ]))
    body = "topic=Acme".encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    status, headers_out, _b = boot.request("POST", "/memory/reflect", headers, body)
    assert status == 303
    assert headers_out["Location"] == "/inbox"
    (card,) = boot.server.inbox.waiting()
    assert card.draft == "Maya moved on from Acme"


# -- the page surfaces ---------------------------------------------------------


def test_the_memory_page_lists_observations_with_citations_and_the_form(boot, auth):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.95, (facts[0].id, facts[1].id)),
    ]))
    _reflect(boot, auth)
    (card,) = boot.server.inbox.waiting()
    boot.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    status, _h, page = boot.request("GET", "/memory", auth)
    text = page.decode("utf-8")
    assert status == 200
    assert "<h2>Observations</h2>" in text
    assert "Maya moved on from Acme" in text
    assert "confidence 0.95" in text
    assert f'href="#fact-{facts[0].id}"' in text
    assert "Maya left Acme" in text, "the citation names its fact"
    assert 'action="/memory/reflect"' in text
    assert 'name="topic"' in text
    assert 'name="entity"' in text


def test_the_memory_page_has_an_honest_empty_observations_state(boot, auth):
    _seed(boot, ["Maya left Acme"])
    status, _h, page = boot.request("GET", "/memory", auth)
    text = page.decode("utf-8")
    assert status == 200
    assert "<h2>Observations</h2>" in text
    assert "No observations yet" in text


def test_the_inbox_renders_reflection_cards_under_the_save_observation_label(
    boot, auth
):
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
    ]))
    _reflect(boot, auth)
    status, _h, page = boot.request("GET", "/inbox", auth)
    text = page.decode("utf-8")
    assert status == 200
    assert "Save observation" in text
    assert "Maya moved on from Acme" in text


# -- the same flow over a sealed bank ------------------------------------------


def test_the_reflect_flow_over_a_sealed_bank(sealed_boot, sealed_auth):
    boot, auth = sealed_boot, sealed_auth
    facts = _seed(boot, ["Maya left Acme", "Acme ships widgets"])
    _inject(boot, FakeReflector([
        _draft("Maya moved on from Acme", 0.9, (facts[0].id, facts[1].id)),
    ]))
    status, _h, _b = _reflect(boot, auth)
    assert status == 200
    (card,) = boot.server.inbox.waiting()
    status, _h, _b = boot.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    assert status == 200
    stored = _observations(boot)
    assert [o.text for o in stored] == ["Maya moved on from Acme"]
    assert stored[0].fact_ids == (facts[0].id, facts[1].id)
    rows = _raw_observation_rows(boot)
    assert rows[0][2] == "", "the plaintext column is blank on the sealed bank"
    assert rows[0][3] is not None
    # The memory page decrypts and renders the observation.
    status, _h, page = boot.request("GET", "/memory", auth)
    assert status == 200
    assert "Maya moved on from Acme" in page.decode("utf-8")
