"""Research panel and assistant tests through the real HTTP seam.

The corporate endpoint is a real local HTTP server speaking just enough
OpenAI to answer, so the acceptance line about requests going to the
configured base URL is tested against an actual socket. The endpoint-down
case points the adapter at a closed port.
"""

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
from nexuusbot.llm import chat


class StubEndpoint:
    """A minimal OpenAI-compatible endpoint on the loopback.

    Records every request (path, auth header, body) and answers with a
    fixed reply; the reply content is configurable per test.
    """

    def __init__(self, content: str) -> None:
        outer = self
        self.requests: list[dict] = []
        self.content = content

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                outer.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
                )
                reply = json.dumps(
                    {"choices": [{"message": {"content": outer.content}}]}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.adapter = lambda prompt: chat(self.base_url, "test-key", "test-model", prompt)  # noqa: E731

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def stub():
    content = json.dumps(
        {
            "summary": "Five of nine EU partners reflected the new prices.",
            "sources": ["eu-price-memo.pdf", "channel-weekly.xlsx, tab EU"],
        }
    )
    endpoint = StubEndpoint(content)
    try:
        yield endpoint
    finally:
        endpoint.close()


@pytest.fixture()
def env(stub):
    booted = server_harness.Booted(
        llm=stub.adapter, llm_endpoint=stub.base_url, llm_model="test-model"
    )
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def test_research_returns_summary_with_source_chips(env, auth, stub):
    status, _h, body = env.post_json(
        "/research", {"question": "What changed in the EU channel?"}, auth
    )
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "ok"
    assert "EU partners" in payload["summary"]
    assert payload["sources"] == ["eu-price-memo.pdf", "channel-weekly.xlsx, tab EU"]
    # The request really went to the configured base URL, authenticated.
    assert stub.requests[0]["path"] == "/chat/completions"
    assert stub.requests[0]["auth"] == "Bearer test-key"


def test_research_requires_a_question(env, auth):
    status, _h, _b = env.post_json("/research", {}, auth)
    assert status == 400


def test_assistant_uses_widget_context_without_restating_it(env, auth, stub, tmp_path):
    from nexuusbot.excel.watcher import Adapters, ExcelWatch
    from nexuusbot.excel.xlsx import parse_workbook_bytes
    from excel_fixtures import base_workbook

    workbook = tmp_path / "Q4-sales.xlsx"
    workbook.write_bytes(base_workbook())
    clock = [1_000_000.0]
    watch = ExcelWatch(
        sqlite3.connect(":memory:", check_same_thread=False),
        Adapters(
            copy_shadow=lambda p: Path(p),
            parse_workbook=lambda p: parse_workbook_bytes(Path(p).read_bytes()),
            clock=lambda: clock[0],
        ),
    )
    old_llm = env.server.llm
    old_excel = env.server.excel
    env.server.excel = watch
    env.server.llm = stub.adapter
    try:
        watch.register(str(workbook))
        status, _h, body = env.post_json(
            "/assistant/ask",
            {"question": "What changed in my workbook, and what should I do?"},
            auth,
        )
    finally:
        env.server.llm = old_llm
        env.server.excel = old_excel

    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    # The prompt the endpoint received carried the workbook's context: the
    # manager never had to restate it.
    # The first request is the turn itself; memory capture may follow.
    sent_prompt = stub.requests[0]["body"]["messages"][0]["content"]
    assert "Q4-sales.xlsx" in sent_prompt
    assert "Atlas ERP modules" in sent_prompt


def test_assistant_thread_persists_across_page_loads(env, auth, stub):
    env.post_json("/assistant/ask", {"question": "What is due today?"}, auth)
    status, _h, body = env.request("GET", "/assistant", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "What is due today?" in page
    assert "Assistant" in page


def test_endpoint_down_degrades_alone(env, auth):
    from nexuusbot.llm import chat as real_chat

    dead_base = "http://127.0.0.1:9"  # closed port
    env.server.llm = lambda prompt: real_chat(dead_base, "k", "m", prompt)

    research_status, _h, body = env.post_json("/research", {"question": "q"}, auth)
    payload = json.loads(body)
    assert research_status == 200
    assert payload["status"] == "degraded"
    assert "AI provider" in payload["cause"]

    ask_status, _h, body = env.post_json("/assistant/ask", {"question": "q"}, auth)
    assert ask_status == 200
    assert json.loads(body)["status"] == "degraded"

    # Degradation is contained: the widgets keep answering.
    assert env.request("GET", "/widgets/sales-24h", auth)[0] == 200
    assert env.request("GET", "/widgets/commitments", auth)[0] == 200
    assert env.request("GET", "/health", auth)[0] == 200


def test_every_outbound_call_is_audited_without_file_contents(env, auth, stub):
    env.post_json("/research", {"question": "summarize the EU channel memo"}, auth)
    env.post_json("/assistant/ask", {"question": "what should I prepare?"}, auth)
    status, _h, body = env.request("GET", "/audit/tail", auth)
    entries = json.loads(body)["entries"]
    assert status == 200
    actions = [e["action"] for e in entries]
    assert "llm.research" in actions and "llm.assistant" in actions
    for entry in entries:
        assert entry["target"] == stub.base_url
        assert entry["ts"] > 0
        # The audit row describes the call; it never carries the prompt.
        assert "EU channel" not in json.dumps(entry)
        assert "Atlas" not in json.dumps(entry)


def test_failed_calls_are_audited_as_errors(env, auth):
    from nexuusbot.llm import chat as real_chat

    env.server.llm = lambda prompt: real_chat("http://127.0.0.1:9", "k", "m", prompt)
    env.post_json("/research", {"question": "q"}, auth)
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    assert entries[0]["status"] == "error"
    assert entries[0]["action"] == "llm.research"


def test_research_degraded_names_the_actual_cause_from_the_endpoint(env, auth):
    """The research bar speaks the adapter's vocabulary (#62): the cause
    is what the endpoint did, not a standing generic line."""
    from test_llm_chat import ScriptedEndpoint

    rejected = ScriptedEndpoint(status=401, body=b'{"error": "bad key"}')
    try:
        env.server.llm = lambda prompt: chat(rejected.base_url, "k", "m", prompt)
        payload = json.loads(env.post_json("/research", {"question": "q"}, auth)[2])
        assert payload["status"] == "degraded"
        assert "rejected the API key" in payload["cause"]
    finally:
        rejected.close()

def test_research_answers_are_stored_for_plugin_cards(env, auth):
    """The panel's sourced answers persist locally (#64): the research
    store keeps the latest one so a plugin card can show it without any
    endpoint call of its own. Assistant turns and failures never land
    there: the store is what research concluded, nothing else."""
    status, _h, _b = env.post_json(
        "/research", {"question": "What changed in the EU channel?"}, auth)
    assert status == 200
    latest = env.server.research_store.latest()
    assert latest is not None
    assert "EU partners" in latest["summary"]
    assert latest["sources"] == ["eu-price-memo.pdf", "channel-weekly.xlsx, tab EU"]
    assert latest["answeredTs"] > 0

    status, _h, _b = env.post_json(
        "/assistant/ask", {"question": "What should I prepare?"}, auth)
    assert status == 200
    assert "EU partners" in env.server.research_store.latest()["summary"]  # untouched


def test_failed_research_answers_are_not_stored(env, auth):
    from nexuusbot.llm import chat as real_chat

    env.server.llm = lambda prompt: real_chat("http://127.0.0.1:9", "k", "m", prompt)
    env.post_json("/research", {"question": "q"}, auth)
    assert env.server.research_store.latest() is None
