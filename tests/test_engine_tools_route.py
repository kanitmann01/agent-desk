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
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.server import app as server_app
from server_harness import Booted, FakeEngine, _engine_actions

FACT = "The Halvorsen Freight renewal is settled for this quarter."
CARD_TITLE = "The desk suggests a look at the renewal"


def _memory_with_entity():
    """A memory store holding one linked fact, so desk_names has a name."""
    from server_harness import _inert_memory

    memory = _inert_memory()
    fact = memory.add(FACT, source="page")
    memory.resolve_and_link(fact.id, [("Halvorsen Freight", "org")])
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
        assert "Halvorsen Freight" in memory_names
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
        assert "Halvorsen Freight" in page
        entries = [row for row in _ledger_json(booted) if row["id"] == entry_id]
        assert entries and entries[0]["action"] == "memory.auto-saved"
        assert entries[0]["undoable"] is True
        status, _h, _b = _undo(booted, entry_id)
        assert status == 200
        page = _get_page(booted, "/memory")
        assert "Halvorsen Freight" not in page
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


def test_without_a_sidecar_the_pass_is_exactly_todays(monkeypatch):
    """Side-car absent: no engine step in the pass, nothing new anywhere."""
    # Pinned absent: the test must hold on a machine that has the real
    # side-car installed, where the pass would otherwise run an engine turn.
    monkeypatch.setattr(server_app, "engine_available", lambda *a, **k: False)
    booted = Booted()
    try:
        payload = _wait_for_pass(booted)
        names = [row.get("name") for row in payload.get("lastSteps") or []]
        assert "engine" not in names
        assert names and all(row.get("ok") for row in payload["lastSteps"])
    finally:
        booted.close()
