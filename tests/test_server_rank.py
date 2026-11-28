"""Ranking reaches the dashboard and the no-JS page, and stays quiet when off (spec 016 §6.3, §9.2, §13)."""

import datetime
import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from nexuusbot.inbox.store import InboxStore
from nexuusbot.ledger.store import Ledger
from nexuusbot.memory.store import MemoryStore
from nexuusbot.server import app as server_app
from nexuusbot.settings import SettingsStore

MORNING = datetime.datetime(2026, 11, 20, 9, 0, 0)


class FakeClock:
    """A clock the whole desk shares, frozen one November morning."""

    def __init__(self, start):
        self.now = start.astimezone().timestamp()

    def __call__(self):
        return self.now


class StubEndpoint:
    """A loopback chat endpoint that records each request and returns one reply."""

    def __init__(self):
        outer = self
        self.requests = []
        self.reply = "[]"

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                outer.requests.append(self.rfile.read(length))
                body = json.dumps(
                    {"choices": [{"message": {"content": outer.reply}}]}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _stores():
    clock = FakeClock(MORNING)
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    memory = MemoryStore(sqlite3.connect(":memory:", check_same_thread=False), clock)
    ledger = Ledger(":memory:", clock=clock)
    return settings, inbox, memory, ledger


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "desk-data"))
    stores = _stores()
    settings, inbox, memory, ledger = stores
    booted = server_harness.Booted(
        settings_store=settings,
        inbox_store=inbox,
        memory_store=memory,
        ledger=ledger,
    )
    booted.stores = stores
    try:
        yield booted
    finally:
        booted.close()


def _auth(desk):
    return desk.exchange()


def _toggle(desk, auth, key):
    status, _headers, body = desk.post_json("/settings/toggle", {"key": key}, auth)
    assert status == 200, body
    return json.loads(body)["value"]


def _recommendations(desk, auth):
    status, _headers, body = desk.request("GET", "/api/dashboard", auth)
    assert status == 200
    return json.loads(body)["recommendations"]


def test_ranked_reason_reaches_dashboard_and_page(desk, tmp_path, monkeypatch):
    stub = StubEndpoint()
    try:
        auth = _auth(desk)
        assert _toggle(desk, auth, "sample_data") is True
        recs = _recommendations(desk, auth)
        harborlight = next(r for r in recs if r["title"].startswith("Harborlight Freight"))
        settings = desk.stores[0]
        settings.set("llm_base", stub.base_url)
        settings.set("llm_key", "test-key")
        settings.set("llm_model", "stub-model")
        stub.reply = json.dumps(
            [
                {
                    "id": harborlight["cardId"],
                    "score": 9,
                    "why": "Renewal closes in 25 days and it is your largest account.",
                }
            ]
        )

        first = desk.server.agent_loop.run_pass(only={"rank"})
        assert first and first[0]["name"] == "rank" and first[0]["ok"], first
        recs = _recommendations(desk, auth)
        ranked = next(r for r in recs if r["cardId"] == harborlight["cardId"])
        assert ranked["why"] == "Renewal closes in 25 days and it is your largest account."
        assert ranked["whySource"] == "model"
        assert ranked["score"] == 9
        assert len(stub.requests) == 1

        rows = desk.server.audit_conn.execute(
            "SELECT action, model, request_bytes, detail FROM audit WHERE action = 'llm.rank'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "stub-model"
        assert rows[0][2] > 0
        assert "Harborlight" not in " ".join(str(value) for value in rows[0])

        second = desk.server.agent_loop.run_pass(only={"rank"})
        assert second and second[0]["name"] == "rank" and second[0]["ok"], second
        assert len(stub.requests) == 1

        monkeypatch.setattr(server_app, "SPA_DIR", tmp_path / "no-spa")
        status, _headers, body = desk.request("GET", "/", auth)
        assert status == 200
        page = body.decode("utf-8")
        assert "Renewal closes in 25 days and it is your largest account." in page
        assert "ranked by your endpoint" in page
    finally:
        stub.close()


def test_rank_step_is_skipped_when_endpoint_or_switch_is_off(desk):
    stub = StubEndpoint()
    try:
        auth = _auth(desk)
        assert _toggle(desk, auth, "sample_data") is True
        settings = desk.stores[0]
        settings.set("llm_base", stub.base_url)
        settings.set("llm_key", "test-key")
        settings.set("llm_model", "stub-model")

        settings.set("recommend_model_rank", False)
        desk.server.agent_loop.run_pass(only={"rank"})
        assert stub.requests == []

        settings.set("recommend_model_rank", True)
        settings.set("endpoint_enabled", False)
        desk.server.agent_loop.run_pass(only={"rank"})
        assert stub.requests == []
    finally:
        stub.close()
