"""The embeddings surfaces over HTTP (ticket #95): the probe-gated
semantic half, the backfill action, and the audit rows.

The probe and the endpoint are scripted: the gate's cached result goes
straight into the capabilities cache (the same cache-then-retest shape
the page writes), and the embeddings endpoint is a real loopback
http.server. With the toggle off, or the probe never passed, or no
endpoint saved, every semantic behavior is inert and recall is
byte-identical to the deterministic hybrid, scores included.
"""

import json
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.memory.embed import encode_embedding
from agentdesk.memory.hybrid import rank_hybrid
from agentdesk.probe.core import FAIL, PASS, UNKNOWN, GateResult


class ScriptedEmbeddingsEndpoint:
    """One loopback endpoint answering every /embeddings POST with the
    scripted status and body (a dict, or a callable over the request
    payload); requests are recorded for the one-request and payload
    assertions."""

    def __init__(self, status=200, body=None) -> None:
        outer = self
        self.requests: list[dict] = []
        self.status = status
        self.body = body if body is not None else {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                outer.requests.append({"path": self.path, "body": payload})
                answered = outer.body(payload) if callable(outer.body) else outer.body
                payload_bytes = json.dumps(answered).encode("utf-8")
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload_bytes)))
                self.end_headers()
                self.wfile.write(payload_bytes)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _vector_body(vector, model="text-embedding-3-small") -> dict:
    return {"data": [{"embedding": list(vector), "index": 0}], "model": model}


def _gate_result(status=PASS, key="embeddings", number=6) -> GateResult:
    return GateResult(
        key=key,
        number=number,
        title="Endpoint embeddings",
        status=status,
        evidence=("scripted probe",),
    )


class Boot:
    """A booted server with its own settings store and capabilities
    cache over one scripted endpoint; helpers seed the probe's cached
    answer and the endpoint rows."""

    def __init__(self, endpoint: ScriptedEmbeddingsEndpoint, memory_store=None) -> None:
        self.memory_store = memory_store
        # Only override the harness's inert memory default when a test
        # really brought its own store: an explicit None here would
        # fall through create_server to the real user data directory.
        kwargs = {} if memory_store is None else {"memory_store": memory_store}
        self.booted = server_harness.Booted(**kwargs)
        self.settings = self.booted.server.settings
        self.cache = self.booted.server.capabilities_cache
        self.endpoint = endpoint

    def seed_probe(self, status=PASS) -> None:
        self.cache.save_result(_gate_result(status=status))

    def point_at_endpoint(self) -> None:
        self.settings.set("llm_base", self.endpoint.url)
        self.settings.set("llm_key", "test-key")

    def activate(self, status=PASS) -> None:
        self.seed_probe(status)
        self.point_at_endpoint()

    def auth(self) -> dict:
        return self.booted.exchange()

    def close(self) -> None:
        self.booted.close()


@pytest.fixture()
def endpoint():
    scripted = ScriptedEmbeddingsEndpoint(body=_vector_body([0.3, 0.4, 0.5]))
    try:
        yield scripted
    finally:
        scripted.close()


@pytest.fixture()
def boot(endpoint):
    booted = Boot(endpoint)
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(boot):
    return boot.auth()


def _add_fact(boot, auth, text):
    status, _h, body = boot.booted.post_json("/memory/add", {"text": text}, auth)
    assert status == 201
    return json.loads(body)


def _embedding_row(server, fact_id: int):
    return server.memory.conn.execute(
        "SELECT embedding, embedding_model, embedding_dim FROM facts WHERE id = ?",
        (fact_id,),
    ).fetchone()


def _audit_rows(server, action="memory.embeddings"):
    return audit_store.decision_entries(server.audit_conn, (action,), limit=100)


def _call_rows(server):
    """The per-endpoint-call audit rows (llm.embeddings), the
    _model_audit pattern's fields."""
    return _audit_rows(server, action="llm.embeddings")


# -- the gate and auth -------------------------------------------------------


def test_the_backfill_route_requires_a_session(boot):
    status, _h, _b = boot.booted.post_json(
        "/memory/embeddings/backfill", {}, boot.booted.host_header()
    )
    assert status == 401


# -- write-time embedding, probe-gated ---------------------------------------


def test_add_embeds_only_when_the_probe_passed_and_the_toggle_is_on(boot, auth):
    boot.activate()
    fact = _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    row = _embedding_row(boot.booted.server, fact["id"])
    assert row[1] == "text-embedding-3-small"
    assert row[2] > 0 and row[0] is not None
    assert len(boot.endpoint.requests) == 1
    assert boot.endpoint.requests[0]["path"] == "/embeddings"
    assert boot.endpoint.requests[0]["body"]["input"] == fact["text"]

    # The endpoint call is audited: endpoint, model, size, never the text.
    rows = _call_rows(boot.booted.server)
    assert rows, "every embedding call is audited"
    assert rows[0]["action"] == "llm.embeddings"
    assert rows[0]["status"] == "ok"
    assert rows[0]["model"] == "text-embedding-3-small"
    assert rows[0]["request_bytes"] == len(fact["text"].encode("utf-8"))


def test_add_without_a_passed_probe_stores_no_vector_and_asks_nothing(boot, auth):
    # No cached probe result at all: the never-passed state.
    boot.point_at_endpoint()
    fact = _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    assert _embedding_row(boot.booted.server, fact["id"]) == (None, None, None)
    assert boot.endpoint.requests == []


def test_add_with_a_failed_probe_stores_no_vector(boot, auth):
    boot.activate(status=FAIL)
    fact = _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    assert _embedding_row(boot.booted.server, fact["id"]) == (None, None, None)
    assert boot.endpoint.requests == []


def test_add_with_the_toggle_off_is_inert_even_with_a_passing_probe(boot, auth):
    boot.activate()
    boot.settings.set("semantic_memory", False)
    fact = _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    assert _embedding_row(boot.booted.server, fact["id"]) == (None, None, None)
    assert boot.endpoint.requests == []


def test_recall_with_embeddings_inactive_is_byte_identical_to_the_hybrid(boot, auth):
    boot.activate()
    boot.settings.set("semantic_memory", False)
    for text in ("revenue is 220", "standup moved to nine", "alice runs the graph team"):
        _add_fact(boot, auth, text)
    memory = boot.booted.server.memory
    # One frozen instant for both calls: the store's live clock reads
    # time.time, and recency multiplies by it, so two readings differ
    # in the last bits for reasons that have nothing to do with
    # embeddings.
    frozen = memory.clock()
    memory.clock = lambda: frozen
    deterministic = rank_hybrid(
        "revenue total", memory.all(), memory._entity_links(), now=frozen
    )
    assert memory.recall("revenue total") == deterministic


def test_a_paraphrase_with_zero_keyword_overlap_recalls_through_the_vector_leg(
    boot, auth, endpoint
):
    mapping = {
        # The query embeds onto the revenue fact's direction; the
        # printer note's vector points away, so its cosine is negative
        # and the ranker (score > 0 only) never surfaces it.
        "the quarterly revenue total is 220 thousand": [1.0, 0.0],
        "unrelated note about printers": [-1.0, 0.0],
        "how much money did we make": [0.95, 0.05],
    }
    endpoint.body = lambda payload: _vector_body(
        mapping.get(payload["input"], [0.1, 0.99])
    )
    boot.activate()
    fact = _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    _add_fact(boot, auth, "unrelated note about printers")
    status, _h, body = boot.booted.post_json(
        "/memory/recall", {"query": "how much money did we make"}, auth
    )
    assert status == 200
    page = body.decode("utf-8")
    assert "recall-preview" in page
    preview = page.split("recall-preview", 1)[1].split("</ol>", 1)[0]
    assert fact["text"] in preview, "the vector leg alone surfaced the fact"
    assert "unrelated note about printers" not in preview


# -- the backfill action ------------------------------------------------------


def test_backfill_reports_counts_and_writes_the_missing_vectors(boot, auth):
    boot.activate()
    boot.settings.set("semantic_memory", False)
    first = _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    second = _add_fact(boot, auth, "unrelated note about printers")
    boot.settings.set("semantic_memory", True)

    status, _h, body = boot.booted.post_json("/memory/embeddings/backfill", {}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["embedded"] == 2
    assert payload["remaining"] == 0
    server = boot.booted.server
    assert _embedding_row(server, first["id"])[0] is not None
    assert _embedding_row(server, second["id"])[0] is not None

    # The action's own audit row names counts, never text.
    rows = _audit_rows(server)
    assert any(
        row["target"] == "2 embedded, 0 remaining" for row in rows
    ), [row["target"] for row in rows]


def test_the_memory_page_shows_the_live_counts(boot, auth):
    boot.activate()
    boot.settings.set("semantic_memory", False)
    _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    status, _h, body = boot.booted.request("GET", "/memory", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "embeddings-counts" in page
    assert "0 embedded" in page and "1 remaining" in page
    assert "/memory/embeddings/backfill" in page


def test_backfill_as_a_form_post_renders_the_page_with_the_counts(boot, auth):
    boot.activate()
    boot.settings.set("semantic_memory", False)
    _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    boot.settings.set("semantic_memory", True)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": "0",
        **auth,
    }
    status, _headers, page = boot.booted.request(
        "POST", "/memory/embeddings/backfill", headers, b""
    )
    assert status == 200
    text = page.decode("utf-8")
    assert "1 embedded" in text and "0 remaining" in text


def test_backfill_without_an_active_client_refuses_in_plain_language(boot, auth):
    boot.point_at_endpoint()  # the probe never passed
    _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    status, _h, body = boot.booted.post_json("/memory/embeddings/backfill", {}, auth)
    assert status == 409
    payload = json.loads(body)
    assert "probe" in payload["error"].lower()
    assert boot.endpoint.requests == []


def test_a_backfill_that_cannot_embed_reports_the_cause_and_keeps_counts(boot, auth):
    boot.activate()
    boot.settings.set("semantic_memory", False)
    _add_fact(boot, auth, "the quarterly revenue total is 220 thousand")
    boot.settings.set("semantic_memory", True)
    boot.endpoint.status = 500
    boot.endpoint.body = {"error": "boom"}

    status, _h, body = boot.booted.post_json("/memory/embeddings/backfill", {}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["embedded"] == 0
    assert payload["remaining"] == 1
    assert payload["status"] == "error"
    assert payload["cause"]
    # The action row still lands, with the counts.
    rows = _audit_rows(boot.booted.server)
    assert any(row["target"] == "0 embedded, 1 remaining" for row in rows)


# -- the probe card rides the cache -------------------------------------------


def test_the_embeddings_probe_result_is_cached_and_retestable(boot, auth):
    boot.seed_probe(status=UNKNOWN)
    cached = boot.cache.cached("embeddings")
    assert cached is not None
    assert cached.result.status == UNKNOWN
    assert cached.result.number == 6
    status, _h, body = boot.booted.request("GET", "/capabilities", auth)
    assert status == 200
    assert "/capabilities/embeddings/retest" in body.decode("utf-8")


# -- the settings page carries the toggle -------------------------------------


def test_the_semantic_memory_toggle_is_on_the_settings_page(boot, auth):
    status, _h, body = boot.booted.request("GET", "/settings", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "semantic_memory" in page
    status, _h, body = boot.booted.post_json(
        "/settings/toggle", {"key": "semantic_memory"}, auth
    )
    assert status == 200
    assert boot.settings.get("semantic_memory") is False


# -- the sealed bank over HTTP ------------------------------------------------


def test_embed_add_and_recall_over_an_encrypted_bank(endpoint):
    key = bytes(range(32))
    memory = server_harness.MemoryStore(
        sqlite3.connect(":memory:", check_same_thread=False), time.time, key=key
    )
    booted = Boot(endpoint, memory_store=memory)
    try:
        booted.activate()
        auth = booted.auth()
        fact = _add_fact(booted, auth, "the quarterly revenue total is 220 thousand")
        server = booted.booted.server
        row = _embedding_row(server, fact["id"])
        assert row[0] != encode_embedding([1.0, 0.0]), "sealed banks store ciphertext"
        assert row[0][0] == 1, "the byte envelope's version byte"
        assert server.memory.is_sealed

        # Recall decrypts in memory; the deterministic legs still work.
        ranked = server.memory.recall("revenue total")
        assert ranked and ranked[0][1].id == fact["id"]
    finally:
        booted.close()
