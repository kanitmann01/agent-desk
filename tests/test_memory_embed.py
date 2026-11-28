"""Embedding codecs, cosine math, the brute-force ranker and the
endpoint embeddings client (ticket #95).

The codecs and math port the donor's src/embed.ts exactly: little-endian
float32 blobs, decode refusing a wrong byte length or a non-finite
value, cosine returning zero on a length mismatch or a zero magnitude,
and the brute-force ranker keeping only positive scores. The client is
the chassis's own OpenAI-compatible adapter over the app's llm seam
(auth headers, plain-language causes, one attempt, no redirects); every
failure shape is answered by a real loopback socket, like the llm tests,
so nothing here touches a network.
"""

import json
import math
import socket
import sqlite3
import struct
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

from nexuusbot.llm import (
    NO_ENDPOINT_CAUSE,
    NO_SCHEME_CAUSE,
    NOT_API_BASE_CAUSE,
    REDIRECT_CAUSE,
)
from nexuusbot.memory.embed import (
    DEFAULT_EMBED_MODEL,
    EmbedderUnavailable,
    EndpointEmbedder,
    SettingsEmbedder,
    cosine,
    decode_embedding,
    encode_embedding,
    rank,
)
from nexuusbot.settings import SettingsStore


# -- codecs (src/embed.ts encodeEmbedding / decodeEmbedding) -----------------


def test_encode_is_little_endian_float32():
    blob = encode_embedding([0.5, -1.25, 2.0])
    assert blob == struct.pack("<3f", 0.5, -1.25, 2.0)


def test_encode_rejects_an_empty_vector():
    with pytest.raises(ValueError):
        encode_embedding([])


def test_encode_rejects_non_finite_values():
    for bad in ([float("nan")], [float("inf")], [1.0, float("-inf")]):
        with pytest.raises(ValueError):
            encode_embedding(bad)


def test_decode_roundtrips_encode():
    vector = [0.5, -1.25, 2.0, 0.0]
    assert decode_embedding(encode_embedding(vector), 4) == vector


def test_decode_refuses_a_wrong_byte_length():
    blob = encode_embedding([1.0, 2.0])
    assert decode_embedding(blob, 3) is None
    assert decode_embedding(blob[:-1], 2) is None
    assert decode_embedding(blob + b"\x00", 2) is None


def test_decode_refuses_zero_or_non_integer_dim():
    blob = encode_embedding([1.0])
    assert decode_embedding(blob, 0) is None
    assert decode_embedding(blob, -1) is None
    assert decode_embedding(blob, 1.5) is None


def test_decode_refuses_a_non_finite_value():
    blob = struct.pack("<1f", float("inf"))
    assert decode_embedding(blob, 1) is None


# -- cosine (src/embed.ts cosineSimilarity) -----------------------------------


def test_cosine_of_identical_vectors_is_one():
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_of_opposite_vectors_is_minus_one():
    assert cosine([1.0, 2.0], [-1.0, -2.0]) == pytest.approx(-1.0)


def test_cosine_is_zero_on_a_length_mismatch():
    assert cosine([1.0, 0.0], [1.0]) == 0.0


def test_cosine_is_zero_on_a_zero_magnitude():
    assert cosine([0.0, 0.0], [0.0, 0.0]) == 0.0
    assert cosine([1.0, 0.0], [0.0, 0.0]) == 0.0


def test_cosine_is_zero_on_empty_vectors():
    assert cosine([], []) == 0.0
    assert cosine([1.0], []) == 0.0


def test_cosine_scales_with_direction_not_magnitude():
    assert cosine([2.0, 0.0], [8.0, 0.0]) == pytest.approx(1.0)


# -- rank (src/embed.ts createBruteForceCosineRanker) -------------------------


def test_rank_keeps_only_positive_scores_sorted_descending():
    hits = rank([1.0, 0.0], [(1, [1.0, 0.0]), (2, [0.0, 1.0]), (3, [-1.0, 0.0])])
    assert [fact_id for fact_id, _score in hits] == [1]
    assert hits[0][1] == pytest.approx(1.0)


def test_rank_orders_by_score_descending():
    query = [1.0, 0.0]
    hits = rank(
        query,
        [
            (1, [0.5, 0.5]),   # cosine 0.707
            (2, [1.0, 0.0]),   # cosine 1.0
            (3, [0.25, 0.5]),  # cosine 0.447
        ],
    )
    assert [fact_id for fact_id, _score in hits] == [2, 1, 3]


def test_rank_keeps_input_order_on_a_score_tie():
    hits = rank([1.0, 0.0], [(7, [2.0, 0.0]), (3, [5.0, 0.0])])
    assert [fact_id for fact_id, _score in hits] == [7, 3]


def test_rank_of_an_empty_point_list_is_empty():
    assert rank([1.0, 0.0], []) == []


# -- the endpoint client (the chassis's OpenAI-compatible adapter) ------------


class ScriptedEmbeddingsEndpoint:
    """A minimal loopback embeddings endpoint scripted per test: every
    request is recorded (path, headers, body) and answered with one
    status, content type and body. http.server only, so the client's
    failure classification is tested against a real socket."""

    def __init__(self, status=200, content_type="application/json",
                 body=b"{}", extra_headers=None) -> None:
        outer = self
        self.requests: list[dict] = []
        self.status = status
        self.content_type = content_type
        self.body = body
        self.extra_headers = extra_headers or {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                outer.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": json.loads(self.rfile.read(length)),
                })
                self.send_response(outer.status)
                self.send_header("Content-Type", outer.content_type)
                self.send_header("Content-Length", str(len(outer.body)))
                for name, value in outer.extra_headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(outer.body)

            def do_GET(self):  # noqa: N802
                self.send_response(outer.status)
                self.send_header("Content-Type", outer.content_type)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

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


def _vector_payload(vector=(0.1, 0.2, 0.3), model="embed-model") -> bytes:
    return json.dumps(
        {"data": [{"embedding": list(vector), "index": 0}], "model": model}
    ).encode("utf-8")


def test_embed_posts_to_the_embeddings_route_with_the_model_and_input():
    endpoint = ScriptedEmbeddingsEndpoint(body=_vector_payload())
    try:
        embedder = EndpointEmbedder(endpoint.url, "secret-key", "embed-model")
        vector = embedder.embed("the revenue number")
        assert vector == [0.1, 0.2, 0.3]
        assert len(endpoint.requests) == 1
        request = endpoint.requests[0]
        assert request["path"] == "/embeddings"
        assert request["body"] == {"model": "embed-model", "input": "the revenue number"}
        assert request["headers"].get("Authorization") == "Bearer secret-key"
    finally:
        endpoint.close()


def test_embed_records_the_request_bytes_for_the_audit_row():
    endpoint = ScriptedEmbeddingsEndpoint(body=_vector_payload())
    try:
        embedder = EndpointEmbedder(endpoint.url, "k", "m")
        embedder.embed("abcd")
        assert embedder.last_request_bytes == len("abcd".encode("utf-8"))
    finally:
        endpoint.close()


def test_embed_raises_a_plain_cause_when_no_endpoint_is_configured():
    embedder = EndpointEmbedder("", "", "m")
    with pytest.raises(EmbedderUnavailable) as caught:
        embedder.embed("x")
    assert NO_ENDPOINT_CAUSE in str(caught.value)


def test_embed_raises_a_plain_cause_for_a_bad_base_url():
    embedder = EndpointEmbedder("llm.example.com/v1", "", "m")
    with pytest.raises(EmbedderUnavailable) as caught:
        embedder.embed("x")
    assert NO_SCHEME_CAUSE in str(caught.value)


def test_embed_reports_an_http_error_in_plain_language():
    for status, words in (
        (301, REDIRECT_CAUSE),
        (401, "rejected the API key"),
        (404, NOT_API_BASE_CAUSE),
        (500, "failed on its own side"),
    ):
        endpoint = ScriptedEmbeddingsEndpoint(status=status, body=b"{}")
        try:
            embedder = EndpointEmbedder(endpoint.url, "k", "m")
            with pytest.raises(EmbedderUnavailable) as caught:
                embedder.embed("x")
            assert words in str(caught.value)
        finally:
            endpoint.close()


def test_embed_reports_a_web_page_answer():
    endpoint = ScriptedEmbeddingsEndpoint(
        content_type="text/html", body=b"<html><body>portal</body></html>"
    )
    try:
        embedder = EndpointEmbedder(endpoint.url, "k", "m")
        with pytest.raises(EmbedderUnavailable) as caught:
            embedder.embed("x")
        assert "web page" in str(caught.value)
    finally:
        endpoint.close()


def test_embed_reports_a_wrong_payload_shape():
    for body in (
        json.dumps({"choices": []}).encode("utf-8"),
        json.dumps({"data": []}).encode("utf-8"),
        json.dumps({"data": [{"embedding": []}]}).encode("utf-8"),
        json.dumps({"data": [{"embedding": "nope"}]}).encode("utf-8"),
        b"not json at all",
    ):
        endpoint = ScriptedEmbeddingsEndpoint(body=body)
        try:
            embedder = EndpointEmbedder(endpoint.url, "k", "m")
            with pytest.raises(EmbedderUnavailable) as caught:
                embedder.embed("x")
            assert "embeddings reply" in str(caught.value)
        finally:
            endpoint.close()


def test_embed_reports_a_refused_connection_in_plain_language():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    embedder = EndpointEmbedder(f"http://127.0.0.1:{port}", "k", "m")
    with pytest.raises(EmbedderUnavailable) as caught:
        embedder.embed("x")
    assert "refused" in str(caught.value) or "did not answer" in str(caught.value)


def test_embed_tolerates_the_donor_payload_shapes():
    ollama_batch = json.dumps({"embeddings": [[0.4, 0.5]]}).encode("utf-8")
    ollama_single = json.dumps({"embedding": [0.6, 0.7]}).encode("utf-8")
    for body, expected in (
        (ollama_batch, [0.4, 0.5]),
        (ollama_single, [0.6, 0.7]),
    ):
        endpoint = ScriptedEmbeddingsEndpoint(body=body)
        try:
            embedder = EndpointEmbedder(endpoint.url, "k", "m")
            assert embedder.embed("x") == expected
        finally:
            endpoint.close()


def test_embed_refuses_a_non_finite_vector():
    endpoint = ScriptedEmbeddingsEndpoint(
        body=json.dumps({"data": [{"embedding": [1.0, None]}]}).encode("utf-8")
    )
    try:
        embedder = EndpointEmbedder(endpoint.url, "k", "m")
        with pytest.raises(EmbedderUnavailable):
            embedder.embed("x")
    finally:
        endpoint.close()


# -- the settings-backed client ----------------------------------------------


def test_settings_embedder_defaults_to_the_documented_model():
    embedder = SettingsEmbedder(SettingsStore(_memory_conn(), time.time))
    assert embedder.model == DEFAULT_EMBED_MODEL == "text-embedding-3-small"


def test_the_settings_default_and_the_embed_constant_agree():
    # The default lives in settings.py (the row's factory value) and in
    # memory/embed.py (the adapter's fallback); the two must never drift.
    from nexuusbot.memory.embed import DEFAULT_EMBED_MODEL as embed_default
    from nexuusbot.settings import EMBEDDINGS_MODEL_DEFAULT

    assert embed_default == EMBEDDINGS_MODEL_DEFAULT


def test_settings_embedder_resolves_the_model_row_per_call():
    settings = SettingsStore(_memory_conn(), time.time)
    embedder = SettingsEmbedder(settings)
    settings.set("embeddings_model", "text-embedding-3-large")
    assert embedder.model == "text-embedding-3-large"


def test_settings_embedder_embeds_against_the_saved_endpoint():
    endpoint = ScriptedEmbeddingsEndpoint(body=_vector_payload())
    try:
        settings = SettingsStore(_memory_conn(), time.time)
        settings.set("llm_base", endpoint.url)
        settings.set("llm_key", "saved-key")
        embedder = SettingsEmbedder(settings)
        assert embedder.embed("hello") == [0.1, 0.2, 0.3]
        assert endpoint.requests[0]["headers"].get("Authorization") == "Bearer saved-key"
        assert endpoint.requests[0]["body"]["model"] == DEFAULT_EMBED_MODEL
    finally:
        endpoint.close()


def _memory_conn():
    return sqlite3.connect(":memory:", check_same_thread=False)
