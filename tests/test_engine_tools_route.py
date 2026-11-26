"""The engine tools route: one token-gated, loopback-only surface, on the wire.

These tests drive the real server over real sockets through the shared
harness (spec 023, ticket 023-3): the route's guard and token, the four
tools of the desk's vocabulary, the ledger toll every write pays (an
undoable entry or a refusal), and the two pass shapes, the engine pass
that acts through the route and the side-car-less pass that is exactly
today's. The engine is the harness's FakeEngine; no test starts the
real side-car.
"""

import json
import sys
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.engine import TurnResult
from agentdesk.server import app as server_app
from server_harness import Booted, FakeEngine, _engine_actions

FACT = "The Harborlight Freight renewal is settled for this quarter."
CARD_TITLE = "The desk suggests a look at the renewal"


def _memory_with_entity():
    """A memory store holding one linked fact, so desk_names has a name."""
    from server_harness import _inert_memory

    memory = _inert_memory()
    fact = memory.add(FACT, source="page")
    memory.resolve_and_link(fact.id, [("Harborlight Freight", "org")])
    return memory


def _headers(booted: Booted) -> dict[str, str]:
    """Session headers for the desk's own pages and APIs."""
    return booted.exchange()


def _get_json(booted: Booted, path: str) -> dict:
    """GET a gated JSON path with the session's headers."""
    _status, _ignored, body = booted.request("GET", path, headers=_headers(booted))
    return json.loads(body)


def _get_page(booted: Booted, path: str) -> str:
    """GET a gated page with the session's headers, as text."""
    _status, _ignored, body = booted.request("GET", path, headers=_headers(booted))
    return body.decode("utf-8")


def _engine_post(booted: Booted, payload: dict, token: str | None = "right",
                 host: str | None = None):
    """One POST to the tools route with the token (or without, or wrong)."""
    headers = {"Content-Type": "application/json"}
    if token is not None:
        value = booted.server.engine_token if token == "right" else "not-the-token"
        headers["Authorization"] = f"Bearer {value}"
    if host is not None:
        headers["Host"] = host
    return booted.post_json("/api/engine/tools", payload, headers=headers)


def _wait_for_pass(booted: Booted, want_step: str | None = None,
                   seconds: float = 10.0) -> dict:
    """Run one pass now and wait for it to finish, optionally naming a step."""
    status, _ignored, body = booted.post_json("/api/agent-loop/run", {},
                                              headers=_headers(booted))
    assert status == 200, f"Run now answered {status}: {body[:120]!r}"
    deadline = time.monotonic() + seconds
    payload = {}
    while time.monotonic() < deadline:
        payload = _get_json(booted, "/api/agent-loop")
        names = [row.get("name") for row in payload.get("lastSteps") or []]
        if not payload.get("running") and (want_step is None or want_step in names):
            return payload
        time.sleep(0.05)
    return payload


def _ledger_json(booted: Booted) -> list[dict]:
    """The ledger API's entries, newest first."""
    return _get_json(booted, "/api/ledger?limit=50").get("entries") or []


def _undo(booted: Booted, entry_id: str):
    """Undo one entry through the Activity page's own route."""
    return booted.post_json("/api/ledger/undo", {"id": entry_id},
                            headers=_headers(booted))


def test_the_route_answers_only_with_this_boots_token():
    """No token and a wrong token are named refusals; the right one answers."""
    booted = Booted()
    try:
        status, _h, body = _engine_post(booted, {"tool": "desk_names"}, token=None)
        assert status == 403 and b"token-required" in body
        status, _h, body = _engine_post(booted, {"tool": "desk_names"}, token="wrong")
        assert status == 403 and b"token-unknown" in body
        status, _h, body = _engine_post(booted, {"tool": "desk_names"})
        assert status == 200 and b"desk_names" in body
        # The boot's engine token is its own secret, never the session's.
        assert booted.server.engine_token != booted.server.sessions.bootstrap_token()
    finally:
        booted.close()


def test_the_route_is_loopback_only_even_with_sanctioned_hosts():
    """A foreign Host header is refused by the guard before the token is read."""
    booted = Booted()
    try:
        booted.server.settings.set("extra_allowed_hosts", "workbox.example:1")
        status, _h, body = _engine_post(
            booted, {"tool": "desk_names"}, host="workbox.example:1")
        assert status == 403 and b"engine:blocked" in body
    finally:
        booted.close()


def test_an_unknown_tool_is_refused_before_anything_runs():
    """A tool name the vocabulary does not carry is a 400, never a guess."""
    booted = Booted()
    try:
        status, _h, body = _engine_post(booted, {"tool": "format_the_disk"})
        assert status == 400 and b"tool-unknown" in body
    finally:
        booted.close()


def test_desk_names_read_what_the_desk_holds():
    """The names tool answers the memory names the desk holds, nothing invented."""
    booted = Booted(memory_store=_memory_with_entity())
    try:
        status, _h, body = _engine_post(booted, {"tool": "desk_names"})
        assert status == 200
        names = json.loads(body)["names"]
        memory_names = [row["name"] for row in names["memory"]]
        assert "Harborlight Freight" in memory_names
        assert names["workbook"] is None
        assert names["agenda"] is None
    finally:
        booted.close()


def test_add_card_runs_through_the_builder_and_pays_the_ledger():
    """One engine card: waiting in the inbox, on the dashboard, undoable in Activity."""
    booted = Booted()
    try:
        status, _h, body = _engine_post(booted, {"tool": "add_card", "args": {
            "title": CARD_TITLE, "body": "The renewal is worth a look.",
            "why": "It is due soon."}})
        assert status == 201, body
        made = json.loads(body)
        assert made["cardId"] and made["entryId"]
        # A user sees the card waiting, on the dashboard's recommendations.
        dashboard = _get_json(booted, "/api/dashboard")
        cards = dashboard.get("recommendations") or []
        assert CARD_TITLE in [card["title"] for card in cards]
        shown = next(card for card in cards if card["title"] == CARD_TITLE)
        assert shown["whySource"] == "engine"
        # Activity carries the entry with a working Undo.
        entries = [row for row in _ledger_json(booted)
                   if row["id"] == made["entryId"]]
        assert entries and entries[0]["action"] == "recommend.added"
        assert entries[0]["undoable"] is True
        status, _h, body = _undo(booted, made["entryId"])
        assert status == 200
        dashboard = _get_json(booted, "/api/dashboard")
        titles = [card["title"] for card in dashboard.get("recommendations") or []]
        assert CARD_TITLE not in titles
        # The same suggestion is not stacked twice.
        status, _h, body = _engine_post(booted, {"tool": "add_card", "args": {
            "title": CARD_TITLE, "body": "The renewal is worth a look."}})
        assert status == 409
    finally:
        booted.close()


def test_add_card_refuses_with_autonomy_off_and_never_writes():
    """Autonomy off: the refusal names why and no card, no entry exists."""
    booted = Booted()
    try:
        booted.server.settings.set("autonomy", False)
        before = _ledger_json(booted)
        status, _h, body = _engine_post(booted, {"tool": "add_card", "args": {
            "title": CARD_TITLE, "body": "Body."}})
        assert status == 409 and b"Autonomy is off" in body
        assert _ledger_json(booted) == before
    finally:
        booted.close()


def test_add_card_without_its_arguments_is_refused():
    """A write without a title or body changes nothing."""
    booted = Booted()
    try:
        before = _ledger_json(booted)
        status, _h, _b = _engine_post(booted, {"tool": "add_card", "args": {
            "title": CARD_TITLE}})
        assert status == 400
        assert _ledger_json(booted) == before
    finally:
        booted.close()


def test_a_proposed_fact_is_stored_with_an_undo_when_review_is_off():
    """Auto-approve: the fact lands on Memory and its entry's Undo removes it."""
    booted = Booted()
    try:
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 201, body
        entry_id = json.loads(body)["entryId"]
        page = _get_page(booted, "/memory")
        assert "Harborlight Freight" in page
        entries = [row for row in _ledger_json(booted) if row["id"] == entry_id]
        assert entries and entries[0]["action"] == "memory.auto-saved"
        assert entries[0]["undoable"] is True
        status, _h, _b = _undo(booted, entry_id)
        assert status == 200
        page = _get_page(booted, "/memory")
        assert "Harborlight Freight" not in page
    finally:
        booted.close()


def test_a_proposed_fact_is_staged_for_review_when_review_is_on():
    """Review mode: the desk stages the same draft card capture makes, undoably."""
    booted = Booted()
    try:
        booted.server.settings.set("memory_auto_approve", False)
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 201, body
        entry_id = json.loads(body)["entryId"]
        assert _get_json(booted, "/widgets/inbox")["waiting"] == 1
        entries = [row for row in _ledger_json(booted) if row["id"] == entry_id]
        assert entries and entries[0]["action"] == "memory.proposed"
        assert entries[0]["undoable"] is True
        status, _h, _b = _undo(booted, entry_id)
        assert status == 200
        # Undoing the proposal takes the waiting card back off the desk.
        assert _get_json(booted, "/widgets/inbox")["waiting"] == 0
    finally:
        booted.close()


def test_a_proposed_fact_already_held_is_refused():
    """A fact the desk stores, waits on or rejected once is not proposed twice."""
    booted = Booted()
    try:
        first = _engine_post(booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert first[0] == 201
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 409 and b"already holds" in body
    finally:
        booted.close()


def test_a_proposed_fact_refuses_when_capture_or_autonomy_is_off():
    """Both switches refuse before anything is written."""
    booted = Booted()
    try:
        booted.server.settings.set("memory_capture", False)
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 409 and b"capture is off" in body.lower()
        booted.server.settings.set("memory_capture", True)
        booted.server.settings.set("autonomy", False)
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 409 and b"Autonomy is off" in body
    finally:
        booted.close()


def test_desk_probes_run_read_only():
    """The probes tool answers one read-only desk-check run."""
    booted = Booted()
    try:
        before = _get_json(booted, "/api/desk-check")
        status, _h, body = _engine_post(booted, {"tool": "desk_probes"})
        assert status == 200
        probes = json.loads(body)["probes"]
        assert set(probes) == set(before)
        assert isinstance(probes.get("findings"), list)
    finally:
        booted.close()


def test_the_first_engine_pass_acts_through_the_tools_route(monkeypatch):
    """Side-car present: the pass's action lands through the route, undoably."""
    monkeypatch.setattr(server_app, "engine_available", lambda *a, **k: True)
    fake = FakeEngine(_engine_actions(add_card={
        "title": CARD_TITLE, "body": "From the engine's first pass."}))
    booted = Booted(engine_runner=fake)
    try:
        payload = _wait_for_pass(booted, want_step="engine")
        engine_row = next(row for row in payload["lastSteps"]
                          if row["name"] == "engine")
        assert engine_row["ok"] is True
        assert fake.turns and fake.turns[0]["context"]
        dashboard = _get_json(booted, "/api/dashboard")
        titles = [card["title"] for card in dashboard.get("recommendations") or []]
        assert CARD_TITLE in titles
        undoable = [row for row in _ledger_json(booted) if row["undoable"]]
        assert undoable, "the engine's first pass left no undoable entry"
        status, _h, _b = _undo(booted, undoable[0]["id"])
        assert status == 200
    finally:
        booted.close()


def test_without_a_sidecar_the_pass_says_so_and_runs_only_its_fixed_steps(monkeypatch):
    """Side-car absent: the engine row names the fallback and executes nothing."""
    # Pinned absent: the test must hold on a machine that has the real
    # side-car installed, where the pass would otherwise run an engine turn.
    monkeypatch.setattr(server_app, "engine_available", lambda *a, **k: False)
    booted = Booted()
    try:
        payload = _wait_for_pass(booted, want_step="engine")
        names = [row.get("name") for row in payload.get("lastSteps") or []]
        assert "engine" in names
        engine_row = next(row for row in payload["lastSteps"]
                          if row["name"] == "engine")
        assert engine_row["ok"] is True
        assert engine_row["detail"]["backend"] == "fallback"
        assert engine_row["detail"]["actions"] == 0
        assert engine_row["detail"]["acted"] == 0
        assert engine_row["detail"]["refused"] == 0
        assert "side-car is not installed" in engine_row["detail"]["note"]
        # Nothing the engine could have run exists: no suggestion card and
        # no engine-sourced ledger entry.
        dashboard = _get_json(booted, "/api/dashboard")
        assert dashboard.get("recommendations") == []
        subjects = [row.get("subject") or "" for row in _ledger_json(booted)]
        assert not any(subject.startswith("recommendation/engine:")
                       for subject in subjects)
        assert all(row.get("ok") for row in payload["lastSteps"])
    finally:
        booted.close()


def test_a_non_ascii_token_is_a_plain_refusal():
    """A Bearer token that is not ASCII answers 403, never a 500."""
    booted = Booted()
    try:
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer tökén-ünicode"}
        status, _h, body = booted.post_json(
            "/api/engine/tools", {"tool": "desk_names"}, headers=headers)
        assert status == 403 and b"token-unknown" in body
    finally:
        booted.close()


def test_every_tool_call_is_audited_with_its_outcome(monkeypatch):
    """engine.tool lands after the handler, ok for a read and error for a refusal."""
    booted = Booted()
    try:
        status, _h, _b = _engine_post(booted, {"tool": "desk_names"})
        assert status == 200
        status, _h, _b = _engine_post(booted, {"tool": "format_the_disk"})
        assert status == 400
        rows = [row for row in _audit_rows(booted)
                if row.get("action") == "engine.tool"]
        assert [row["status"] for row in rows[:2]] == ["error", "ok"]
        refused = next(row for row in rows if row["status"] == "error")
        assert "unknown tool" in refused["detail"]
    finally:
        booted.close()


def _audit_rows(booted: Booted) -> list[dict]:
    """The audit tail's rows, newest first."""
    return _get_json(booted, "/audit/tail").get("entries") or []


def test_add_card_without_a_ledger_is_refused_before_any_write():
    """No ledger: a plain 409 and no card anywhere."""
    booted = Booted()
    try:
        booted.server.ledger = None
        status, _h, body = _engine_post(booted, {"tool": "add_card", "args": {
            "title": CARD_TITLE, "body": "Body.", "why": "Why."}})
        assert status == 409 and b"ledger is not available" in body
        assert _get_json(booted, "/api/dashboard").get("recommendations") == []
        assert _get_json(booted, "/widgets/inbox")["waiting"] == 0
    finally:
        booted.close()


def test_propose_fact_without_a_ledger_is_refused_before_any_write():
    """No ledger: a plain 409 and no fact, card or excerpt."""
    booted = Booted()
    try:
        booted.server.ledger = None
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 409 and b"ledger is not available" in body
        assert booted.server.memory.all() == []
        assert booted.server.memory.sources() == []
    finally:
        booted.close()


def _broken_record(**_kwargs):
    """One ledger record that fails before it can promise an undo."""
    raise RuntimeError("the ledger is unwritable")


def test_add_card_rolls_back_when_the_ledger_record_fails():
    """A failed record leaves no card, no latch and a 500."""
    booted = Booted()
    try:
        booted.server.ledger.record = _broken_record
        status, _h, body = _engine_post(booted, {"tool": "add_card", "args": {
            "title": CARD_TITLE, "body": "Body.", "why": "Why."}})
        assert status == 500 and b"nothing was added" in body
        assert _get_json(booted, "/api/dashboard").get("recommendations") == []
        assert _get_json(booted, "/widgets/inbox")["waiting"] == 0
        rows = booted.server.ledger.conn.execute("SELECT key FROM latches").fetchall()
        assert rows == []
    finally:
        booted.close()


def test_a_stored_fact_rolls_back_when_the_ledger_record_fails():
    """A failed record removes the stored fact before the 500."""
    booted = Booted()
    try:
        booted.server.ledger.record = _broken_record
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 500 and b"nothing was proposed" in body
        assert booted.server.memory.all() == []
    finally:
        booted.close()


def test_a_staged_fact_rolls_back_when_the_ledger_record_fails():
    """A failed record removes the staged card before the 500."""
    booted = Booted()
    try:
        booted.server.settings.set("memory_auto_approve", False)
        booted.server.ledger.record = _broken_record
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 500 and b"nothing was proposed" in body
        assert _get_json(booted, "/widgets/inbox")["waiting"] == 0
        assert booted.server.memory.sources() == []
    finally:
        booted.close()


def test_a_staged_fact_creates_its_excerpt_only_on_approval():
    """Rejecting a staged proposal leaves no source excerpt behind."""
    booted = Booted()
    try:
        booted.server.settings.set("memory_auto_approve", False)
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 201, body
        loop = _get_json(booted, "/api/memory/loop")
        assert loop["counts"]["sources"] == 0
        candidate = loop["candidates"][0]
        assert candidate["excerpt"]["text"].startswith("The desk proposed:")
        booted.post_json(f"/inbox/cards/{candidate['cardId']}/dismiss", {},
                         headers=_headers(booted))
        assert booted.server.memory.sources() == []
        assert booted.server.memory.all() == []
    finally:
        booted.close()


def test_approving_a_staged_fact_creates_the_excerpt_and_the_fact():
    """Approving writes the fact and the source the card carried as text."""
    booted = Booted()
    try:
        booted.server.settings.set("memory_auto_approve", False)
        status, _h, body = _engine_post(
            booted, {"tool": "propose_fact", "args": {"text": FACT}})
        assert status == 201, body
        card_id = _get_json(booted, "/api/memory/loop")["candidates"][0]["cardId"]
        status, _h, _b = booted.post_json(
            f"/inbox/cards/{card_id}/accept", {}, headers=_headers(booted))
        assert status in (200, 201)
        facts = booted.server.memory.all()
        assert [fact.text for fact in facts] == [FACT]
        sources = booted.server.memory.sources()
        assert len(sources) == 1
        assert sources[0].text.startswith("The desk proposed:")
        assert facts[0].source_id == sources[0].id
    finally:
        booted.close()


def test_a_transport_failure_refuses_one_action_and_continues(monkeypatch):
    """A dead socket counts as refused; the next action still runs."""
    booted = Booted()
    try:
        calls = []

        def flaky(server, payload):
            """The first call loses its socket; the second answers 200."""
            calls.append(payload["tool"])
            if len(calls) == 1:
                raise urllib.error.URLError("the desk is not answering")
            return 200, {"tool": payload["tool"]}

        monkeypatch.setattr(server_app, "_engine_tools_post", flaky)
        acted, refused = server_app.execute_engine_actions(
            booted.server, _engine_actions(desk_names={}, desk_probes={}))
        assert calls == ["desk_names", "desk_probes"]
        assert (acted, refused) == (1, 1)
    finally:
        booted.close()


class _FailingEngine(FakeEngine):
    """A turn that reports its own failure and a boundary refusal."""

    def run_turn(self, context: str, *, connection=None, **kwargs) -> TurnResult:
        """Answer a failed turn carrying one boundary refusal."""
        self.turns.append({"context": context, "connection": connection})
        return TurnResult(backend="sidecar", ok=False,
                          note="The engine side-car turn failed.",
                          refusals=("refused an unknown tool call: 'rm'",))


def test_a_failed_turn_is_a_failed_engine_step_and_audit_row(monkeypatch):
    """ok False in the turn becomes ok False in lastSteps and an error audit."""
    monkeypatch.setattr(server_app, "engine_available", lambda *a, **k: True)
    fake = _FailingEngine()
    booted = Booted(engine_runner=fake)
    try:
        payload = _wait_for_pass(booted, want_step="engine")
        row = next(row for row in payload["lastSteps"] if row["name"] == "engine")
        assert row["ok"] is False
        assert row["detail"]["refused"] == 1
        assert row["detail"]["ok"] is False
        passes = [entry for entry in _audit_rows(booted)
                  if entry.get("action") == "engine.pass"]
        assert passes and passes[0]["status"] == "error"
        assert "refused" in passes[0]["detail"]
    finally:
        booted.close()


def test_the_engine_step_does_not_run_the_fixed_loop(monkeypatch):
    """Inside a pass the absent side-car is a sentence, never run_pass."""
    monkeypatch.setattr(server_app, "engine_available", lambda *a, **k: False)
    booted = Booted()
    try:
        calls = []
        loop = booted.server.agent_loop
        monkeypatch.setattr(loop, "run_pass", lambda *a, **k: calls.append("pass"))
        outcome = server_app.engine_step_run(SimpleNamespace(server=booted.server))
        assert calls == []
        assert outcome == {
            "backend": "fallback", "ok": True, "actions": 0, "acted": 0,
            "refused": 0,
            "note": ("The side-car is not installed; the pass's fixed steps "
                     "are the fallback.")}
        assert _ledger_json(booted) == []
    finally:
        booted.close()


def test_the_boot_mints_its_tokens_with_the_secrets_module():
    """Regression: the core merge dropped the module's `import secrets`,
    which left every boot dying with a NameError while minting the
    engine token. One in-process boot proves the mint works again."""
    booted = Booted()
    try:
        token = booted.server.engine_token
        assert isinstance(token, str) and len(token) >= 32
    finally:
        booted.close()
