"""The embeddings port (ticket #95): codecs, cosine, rank, client.

The codecs and math replicate the donor's src/embed.ts exactly:

- encode: a list of floats as little-endian float32 bytes, the form the
  facts.embedding blob stores; an empty vector or any non-finite value
  refuses (ValueError, the caller's misbehaviour, never a stored
  garbage blob).
- decode: bytes plus the row's stored dimension back to floats; a wrong
  byte length or a non-finite value reads as None, never as a wrong
  vector.
- cosine: dot over magnitudes; zero when the lengths differ or either
  magnitude is zero.
- rank: the donor's brute-force cosine ranker (the VectorRanker's only
  required implementation); a hit keeps its score only when the score
  is positive, hits sort by score descending, ties keep the input
  order.

The client side is the chassis's own shape, built on the llm seam the
way the extractor and reflector ports are: an embedder is an object
with a `model` name and an `embed(text)` callable that returns floats
or raises EmbedderUnavailable with a plain-language cause.
EndpointEmbedder binds one endpoint config; SettingsEmbedder resolves
the settings rows on every call so a saved endpoint or model applies
without a restart. The model name comes from the `embeddings_model`
settings row, default text-embedding-3-small (the spec's Further Notes
default). One POST to {base}/embeddings per ask, the app's auth
headers, no redirects followed, a short timeout, one attempt: the same
posture as chat.

Auditing is the caller's job, never this module's: the server wraps the
embedder it injects and records one audit row per call, so an injected
test embedder stays silent and the production endpoint calls are all
recorded.
"""

import http.client
import json
import math
import struct
import urllib.error
import urllib.request

from agentdesk.llm import (
    NO_ENDPOINT_CAUSE,
    REQUEST_TIMEOUT_S,
    WEB_PAGE_CAUSE,
    _NeverRedirect,
    _host_of,
    _http_cause,
    auth_headers,
    base_url_problem,
    effective_llm_config,
    transport_cause,
)

DEFAULT_EMBED_MODEL = "text-embedding-3-small"

# The embeddings route's own wrong-shape wording: the pinned chat cause
# names a chat reply, and this route deserves its own honest words.
EMBED_BAD_SHAPE_CAUSE = (
    "the endpoint answered JSON that is not an OpenAI embeddings reply;"
    " check the base URL is an OpenAI-compatible base, usually ending"
    " in /v1"
)

# One module-level opener with the chat adapter's no-redirect handler:
# the pinned llm posture applies here verbatim, so the handler class is
# imported, not re-spelled.
_OPENER = urllib.request.build_opener(_NeverRedirect)


class EmbedderUnavailable(Exception):
    """The embeddings endpoint could not be asked, or answered nothing
    usable. Plain-language cause, never a traceback; callers degrade in
    their own words (the donor's EmbedderUnavailableError)."""


# -- codecs (src/embed.ts) ----------------------------------------------------


def encode_embedding(values) -> bytes:
    """Little-endian float32 bytes, the stored blob's form. An empty
    vector or a non-finite value is a ValueError: there is no honest
    blob for either."""
    if not values:
        raise ValueError("an embedding needs at least one value")
    for value in values:
        if isinstance(value, bool) or not _is_number(value) or not math.isfinite(value):
            raise ValueError("an embedding must be finite numbers")
    return struct.pack(f"<{len(values)}f", *values)


def decode_embedding(blob, dim) -> list[float] | None:
    """The floats behind one stored blob, or None when the blob cannot
    honestly be the dim-wide vector: a wrong byte length, a non-positive
    or non-integer dim, or a non-finite value inside."""
    if not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0:
        return None
    if blob is None:
        return None
    data = bytes(blob)
    if len(data) != dim * 4:
        return None
    vector = list(struct.unpack(f"<{dim}f", data))
    for value in vector:
        if not math.isfinite(value):
            return None
    return vector


def _is_number(value) -> bool:
    return isinstance(value, (int, float))


def cosine(left, right) -> float:
    """The donor's cosineSimilarity: dot over magnitudes, zero on a
    length mismatch, an empty vector or a zero magnitude."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    magnitude = (left_norm ** 0.5) * (right_norm ** 0.5)
    if magnitude == 0:
        return 0.0
    return dot / magnitude


def rank(query, points) -> list[tuple[int, float]]:
    """The donor's brute-force cosine ranker: every point scored, the
    positive scores kept, sorted score descending, ties in input order.
    Returns (id, score) hits; the fusion ranks and weights them."""
    hits: list[tuple[int, float]] = []
    for point_id, vector in points:
        score = cosine(query, vector)
        if score > 0:
            hits.append((point_id, score))
    hits.sort(key=lambda hit: -hit[1])
    return hits


# -- the payload read (src/embed.ts vectorFromPayload, adapted) ----------------


def vector_from_payload(payload) -> list[float] | None:
    """The float vector in one embeddings reply, or None. The OpenAI
    shape reads first (data[0].embedding), then the donor's tolerant
    Ollama shapes (a batch's first row, then a bare embedding field).
    Every entry must be a finite number."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        read = _finite_numbers(data[0].get("embedding"))
        if read is not None:
            return read
    batch = payload.get("embeddings")
    if isinstance(batch, list) and batch:
        read = _finite_numbers(batch[0])
        if read is not None:
            return read
    return _finite_numbers(payload.get("embedding"))


def _finite_numbers(value) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not _is_number(item) or not math.isfinite(item):
            return None
        numbers.append(float(item))
    return numbers


# -- the endpoint-backed client (src/embed.ts createOllamaEmbedder, adapted) ---


def _post_embeddings(base_url: str, api_key: str, model: str, text: str) -> list[float]:
    """One embeddings call, the chat adapter's posture: the pinned base
    causes, no redirects followed, one attempt, HTTP and transport
    failures mapped to plain language, then the payload read."""
    if not base_url:
        raise EmbedderUnavailable(NO_ENDPOINT_CAUSE)
    problem = base_url_problem(base_url)
    if problem:
        raise EmbedderUnavailable(problem)
    payload = {"model": model, "input": text}
    request = urllib.request.Request(
        base_url.rstrip("/") + "/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers=auth_headers(base_url, api_key),
        method="POST",
    )
    host = _host_of(base_url)
    try:
        with _OPENER.open(request, timeout=REQUEST_TIMEOUT_S) as response:
            raw = response.read().decode("utf-8", "replace")
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise EmbedderUnavailable(_http_cause(exc.code)) from exc
    except urllib.error.URLError as exc:
        raise EmbedderUnavailable(
            transport_cause(exc.reason, host=host, timeout=REQUEST_TIMEOUT_S)
        ) from exc
    except http.client.HTTPException as exc:
        # Broken responses http.client raises without an OSError
        # wrapper; classified like any transport failure (llm.chat).
        raise EmbedderUnavailable(
            transport_cause(exc, host=host, timeout=REQUEST_TIMEOUT_S)
        ) from exc
    except OSError as exc:
        # Timeouts and resets that escape URLError arrive bare.
        raise EmbedderUnavailable(
            transport_cause(exc, host=host, timeout=REQUEST_TIMEOUT_S)
        ) from exc
    if "html" in content_type.lower() or raw.lstrip().lower().startswith("<"):
        raise EmbedderUnavailable(WEB_PAGE_CAUSE)
    try:
        body = json.loads(raw)
    except ValueError:
        raise EmbedderUnavailable(EMBED_BAD_SHAPE_CAUSE) from None
    vector = vector_from_payload(body)
    if vector is None:
        raise EmbedderUnavailable(EMBED_BAD_SHAPE_CAUSE)
    return vector


class EndpointEmbedder:
    """The embeddings client bound to one endpoint config, the donor's
    createOllamaEmbedder over the chassis's OpenAI-compatible route.
    `last_request_bytes` is the size of the input that actually went
    out, for the audit row."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.last_request_bytes = 0

    def embed(self, text: str) -> list[float]:
        self.last_request_bytes = len(text.encode("utf-8"))
        return _post_embeddings(self.base_url, self.api_key, self.model, text)


class SettingsEmbedder:
    """An embeddings client that resolves the settings rows over the
    environment on every call (settings_chat's posture): the base and
    key from the effective llm config, the model from the
    embeddings_model row. Saving an endpoint or model in the app applies
    without a restart."""

    def __init__(self, settings_store=None) -> None:
        self._settings = settings_store
        self.last_request_bytes = 0

    @property
    def model(self) -> str:
        if self._settings is not None:
            saved = self._settings.get("embeddings_model")
            if saved:
                return saved
        return DEFAULT_EMBED_MODEL

    def embed(self, text: str) -> list[float]:
        base, key, _chat_model = effective_llm_config(self._settings)
        self.last_request_bytes = len(text.encode("utf-8"))
        return _post_embeddings(base, key, self.model, text)


def settings_embedder(settings_store=None) -> SettingsEmbedder:
    """The factory the server and the probe runner use, the settings_chat
    shape: an embedder bound to no fixed endpoint."""
    return SettingsEmbedder(settings_store)


def effective_embeddings_model(settings_store=None) -> str:
    """The configured model name: the settings row over the documented
    default (text-embedding-3-small)."""
    if settings_store is not None:
        saved = settings_store.get("embeddings_model")
        if saved:
            return saved
    return DEFAULT_EMBED_MODEL
