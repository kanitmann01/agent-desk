"""The demo readiness tool boots, walks and reports (spec 022, ticket 022-6).

The tool is the spec's measure of "done", so its own contract is pinned
here: it runs hermetically, prints one line per check and the metric
line, exits by the count, and leaves nothing behind (no changed
environment variable, no temporary folder). Which checks pass belongs to
the product; nothing here requires any of them to, so this test is green
on a checkout where the product does not yet have the behaviour.

    tools/demo_readiness.py
"""

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "demo_readiness.py"


@pytest.fixture(scope="module")
def readiness():
    """The tool as a module, by path (tools is not a package)."""
    spec = importlib.util.spec_from_file_location("demo_readiness_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _leftovers() -> list[str]:
    """The walk's temporary folders still present in the temp directory."""
    return sorted(name for name in os.listdir(tempfile.gettempdir())
                  if name.startswith("agentdesk-ready-"))


def test_the_walk_reports_every_check_and_the_metric(readiness, capsys):
    before = {name: os.environ.get(name)
              for name in ("AGENTDESK_DATA",) + readiness.PINNED_EMPTY}
    folders = _leftovers()

    code = readiness.main()

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    verdicts = [line for line in lines if line.startswith(("PASS R", "FAIL R"))]
    # A new check is a new number (spec 022's frozen-list rule); 24 and
    # 25 belong to the sibling slices, so the walk's numbers jump there.
    assert [int(line[6:8]) for line in verdicts] == list(readiness.CHECK_NUMBERS)
    assert len(verdicts) == readiness.CHECK_COUNT
    assert readiness.CHECK_NUMBERS[-1] == 29
    assert all(line.startswith(("PASS R", "FAIL R")) for line in verdicts)
    passed = sum(line.startswith("PASS") for line in verdicts)
    assert lines[-1] == f"METRIC ready={passed}"
    assert code == (0 if passed == readiness.CHECK_COUNT else 1)
    # Nothing the walk touched outlives it.
    assert {name: os.environ.get(name) for name in before} == before
    assert _leftovers() == folders


def test_the_mock_endpoint_lists_models_and_remembers_what_it_was_sent(readiness):
    mock = readiness._load_mock()
    assert "mock-chat" in mock.MODELS
    reply = mock.reply_for(
        "You turn a conversation snippet into a few durable memory facts.\n\ncontent:\n"
        "You: Remember this: The Acme renewal is due December 15\nAssistant: Noted.")
    assert "The Acme renewal is due December 15" in reply
    quiet = mock.reply_for(
        "You turn a conversation snippet into a few durable memory facts.\n\ncontent:\n"
        "You: What changed?\nAssistant: Nothing.")
    assert '"facts": []' in quiet
    # The engine turn gets two calls the boundary's vocabulary knows, so
    # the side-car smoke proves the action path and not only the stream.
    engine = json.loads(mock.reply_for(
        "You act for a small business desk.\n\nThe desk's context:\n{}"))
    assert [call["tool"] for call in engine] == ["desk_names", "add_card"]


class _FakeDesk:
    """The two HTTP reads and one undo post the R28/R29 halves make."""

    def __init__(self, *, dashboard=None, ledger=None, audit=None) -> None:
        """Hold the canned payloads and record the undo posts."""
        self.dashboard = dashboard or {}
        self.ledger = list(ledger or [])
        self.audit = list(audit or [])
        self.posts = []

    def get_json(self, path):
        """One canned answer by path."""
        if path == "/api/dashboard":
            return self.dashboard
        if path.startswith("/api/ledger"):
            return {"entries": list(self.ledger)}
        if path == "/audit/tail":
            return {"entries": list(self.audit)}
        return {}

    def post_json(self, path, payload=None):
        """Undo marks the entry undone; anything else is a 404."""
        self.posts.append((path, payload))
        if path == "/api/ledger/undo":
            target = (payload or {}).get("id")
            for row in self.ledger:
                if row["id"] == target:
                    row["undoneBy"] = "undo-entry"
            return 200, {}, b"{}"
        return 404, {}, b"{}"


def _engine_row(*, backend: str, ok: bool = True, actions: int = 0,
                acted: int = 0, refused: int = 0, note: str = "") -> dict:
    """One engine step row in the shape the loop writes it."""
    return {"name": "engine", "ok": ok, "ms": 1,
            "note": note or f"backend {backend}",
            "detail": {"backend": backend, "ok": ok, "actions": actions,
                       "acted": acted, "refused": refused,
                       "note": note}}


def test_r28_zero_cards_fail_when_the_connect_step_is_in_the_build(readiness):
    """The old pass-on-empty rule is gone: a missing line is a failure."""
    desk = _FakeDesk(dashboard={"plugins": {"cards": []}})
    ok, detail = readiness._connect_lines_name_held(
        desk, {"Halvorsen Freight"}, connect_present=True)
    assert ok is False
    assert "none carries" in detail


def test_r28_zero_cards_are_honest_without_the_connect_step(readiness):
    """A build without the connect step says so instead of claiming a line."""
    desk = _FakeDesk(dashboard={"plugins": {"cards": []}})
    ok, detail = readiness._connect_lines_name_held(
        desk, {"Halvorsen Freight"}, connect_present=False)
    assert ok is True
    assert "not in this build" in detail


def test_r28_a_real_line_passes_and_an_unheld_name_fails(readiness):
    """A card line naming a held name passes; one naming another fails."""
    held = "Also in your desk: Halvorsen Freight, 3 things you told the desk."
    desk = _FakeDesk(dashboard={"plugins": {"cards": [
        {"payload": {"insight": {"blocks": [{"text": held}]}}}]}})
    ok, detail = readiness._connect_lines_name_held(
        desk, {"Halvorsen Freight"}, connect_present=True)
    assert ok is True and "1 connect line" in detail
    unheld = "Also in your desk: Quiebro Nova, 1 thing you told the desk."
    desk = _FakeDesk(dashboard={"plugins": {"cards": [
        {"payload": {"insight": {"blocks": [{"text": unheld}]}}}]}})
    ok, detail = readiness._connect_lines_name_held(
        desk, {"Halvorsen Freight"}, connect_present=True)
    assert ok is False and "quiebro nova" in detail


def test_r29_engine_half_fails_without_an_engine_action(readiness):
    """A row that is ok but proposed nothing does not pass the engine half."""
    desk = _FakeDesk()
    status = {"lastSteps": [_engine_row(backend="sidecar", note="0 action(s)")]}
    ok, detail = readiness._engine_half(desk, status, [], installed=True)
    assert ok is False
    assert "proposed no action" in detail


def test_r29_a_fallback_note_passes_only_the_fallback_half(readiness):
    """The honest fallback passes the toll half, never the side-car half."""
    desk = _FakeDesk()
    row = _engine_row(backend="fallback", actions=0,
                      note=readiness.FALLBACK_NOTE)
    status = {"lastSteps": [row]}
    assert readiness._engine_half(desk, status, [], installed=False)[0] is True
    assert readiness._engine_half(desk, status, [], installed=True)[0] is False
    window = [{"id": "e1", "ts": 1, "action": "recommend.added",
               "subject": "recommendation/deadline:x", "undoable": True}]
    assert readiness._pass_toll_half(_FakeDesk(ledger=window), window)[0] is True


def test_r29_a_successful_engine_action_passes_both_halves(readiness):
    """An engine entry and a clean engine row satisfy the engine and toll halves."""
    window = [{"id": "e1", "ts": 2, "action": "recommend.added",
               "subject": "recommendation/engine:abc", "undoable": True}]
    desk = _FakeDesk(ledger=window, audit=[{
        "action": "engine.pass", "status": "ok",
        "detail": "2 action(s), 2 acted, 0 refused"}])
    status = {"lastSteps": [_engine_row(
        backend="sidecar", actions=2, acted=2, refused=0,
        note="2 action(s)")]}
    assert readiness._engine_half(desk, status, window, installed=True)[0] is True
    assert readiness._pass_toll_half(desk, window)[0] is True


def test_the_pass_waits_base_on_the_engine_turn_ceiling(readiness):
    """R27 and R29 wait past a real side-car turn, not 30 seconds."""
    assert readiness.READY_PASS_WAIT_S >= 150.0


def test_the_sample_tracker_boot_opens_a_dashboard_card(readiness, tmp_path, monkeypatch):
    """R28's sample boot installs the tracker and opens the sample workbook.

    The card is the thing R28's connect-line half reads; this pins that
    the boot step really produces one, independently of whether this
    build carries the connect producer.
    """
    for name in readiness.PINNED_EMPTY:
        monkeypatch.setenv(name, "")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("AGENTDESK_DATA", str(data))
    desk = readiness.Desk(data, tmp_path / "keychain.json",
                          readiness._free_udp_port())
    try:
        desk.login()
        status, _headers, _body = desk.post_json(
            "/settings/toggle", {"key": "sample_data"})
        assert status == 200
        ok, detail = readiness._open_sample_tracker(desk)
        assert ok, detail
        cards = ((desk.get_json("/api/dashboard").get("plugins") or {})
                 .get("cards") or [])
        assert any(card.get("pluginId") == "excel-report" for card in cards), cards
    finally:
        desk.post_json("/settings/toggle", {"key": "sample_data"})
        desk.close()
