"""Connection testing, model discovery and health through the HTTP seam
(spec 018, ticket #232).

A real loopback endpoint (the research suite's StubEndpoint shape,
extended to answer the model-list GET too) records every request's
method, path, Authorization header and body, so the tests prove the
whole contract in bytes: the Test route sends the free model-list GET
with the connection's own key, saving sends nothing at all, the
one-token completion happens only when the deeper check is pressed, and
the status mapping (401/403 error, 429 ok-limited, 5xx and timeouts
transient) lands in the row the badge renders from.
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.keys import health
from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain

SECRET = "sk-live-quietly-aaaaaaaaaaaaaaaa-9999"


class RecordingEndpoint:
    """A loopback OpenAI-compatible endpoint that records everything.

    The research suite's StubEndpoint shape, plus a GET handler: every
    request lands in ``requests`` with its method, path, Authorization
    header, api-key header, gateway header and body, the models listing
    is scriptable per test (status plus list, mutable between calls) and
    the chat route answers a minimal reply, so one stub serves both
    checks and every test can prove which requests did and did not
    happen.
    """

    def __init__(self, models=("model-a", "model-b"), models_status=200,
                 chat_status=200, models_headers=None, delay=0.0) -> None:
        outer = self
        self.models = list(models)
        self.models_status = models_status
        self.chat_status = chat_status
        self.models_headers = models_headers or {}
        self.delay = delay
        self.requests: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def _record(self, body: bytes) -> None:
                outer.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "apiKeyHeader": self.headers.get("api-key"),
                    "gateway": self.headers.get("X-Gateway"),
                    "body": body,
                })

            def _answer(self, status: int, payload: bytes,
                        extra: dict | None = None) -> None:
                if outer.delay:
                    time.sleep(outer.delay)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for name, value in (extra or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):  # noqa: N802
                self._record(b"")
                listing = json.dumps({
                    "object": "list",
                    "data": [{"id": m, "object": "model"} for m in outer.models],
                }).encode("utf-8")
                self._answer(outer.models_status, listing, outer.models_headers)

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                self._record(self.rfile.read(length))
                reply = json.dumps(
                    {"choices": [{"message": {"content": "one token"}}]}
                ).encode("utf-8")
                self._answer(outer.chat_status, reply)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def models_requests(self) -> list[dict]:
        """The recorded model-list GETs."""
        return [r for r in self.requests if r["path"].endswith("/models")]

    def chat_requests(self) -> list[dict]:
        """The recorded chat completions (any of them is a finding unless
        the deeper check was pressed)."""
        return [r for r in self.requests if r["path"].endswith("/chat/completions")]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def stub():
    endpoint = RecordingEndpoint()
    try:
        yield endpoint
    finally:
        endpoint.close()


@pytest.fixture()
def env(stub):
    booted = server_harness.Booted(keychain=KeychainSecrets(MemoryKeychain()))
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _connection(env, auth, stub, clear_requests=True, **overrides):
    """One saved connection pointing at the stub, key in the keychain.

    The save itself runs the free check when a key is present (story 3),
    so by default the stub's recording is cleared afterwards and each
    test starts from the saved state; tests that assert on the save's
    own requests pass clear_requests=False."""
    body = {"label": "Work gateway", "provider": "custom",
            "baseUrl": stub.base_url + "/v1", "apiKey": SECRET, **overrides}
    status, _h, out = env.post_json("/api/connections", body, auth)
    assert status == 201, out
    if clear_requests:
        stub.requests.clear()
    return json.loads(out)


def _test(env, auth, connection, **fields):
    """One Test press, as JSON."""
    return env.post_json(f"/api/connections/{connection['id']}/test", fields, auth)


# -- the free check: what goes over the wire -----------------------------------


def test_the_test_route_sends_the_models_get_with_the_connections_key(
        env, auth, stub):
    connection = _connection(env, auth, stub)
    status, _h, body = _test(env, auth, connection)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["lastError"] == ""
    assert payload["lastCheckedAt"] > 0
    # The free check is exactly one model-list GET, authenticated with
    # the connection's own key, and nothing else left the desk.
    assert len(stub.models_requests()) == 1
    request = stub.requests[0]
    assert request["method"] == "GET"
    assert request["path"] == "/v1/models"
    assert request["auth"] == f"Bearer {SECRET}"
    assert stub.chat_requests() == []  # never a chat completion
    # The listing answered, so the cache carries it with a fetched-at.
    assert payload["models"] == ["model-a", "model-b"]
    assert payload["modelsFetchedAt"] > 0


def test_saving_with_a_key_runs_the_free_check_once_and_never_a_chat(
        env, auth, stub):
    """Story 3: the save itself checks the key (a free model-list GET,
    never a chat) and the save response carries the outcome, so the form
    shows the result inline right after saving. An empty-key edit keeps
    the stored key and checks nothing; local presets skip the check."""
    status, _h, body = env.post_json("/api/connections", {
        "label": "Work gateway", "provider": "custom",
        "baseUrl": stub.base_url + "/v1", "apiKey": SECRET}, auth)
    assert status == 201
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["lastError"] == ""
    assert payload["lastCheckedAt"] > 0
    assert payload["models"] == ["model-a", "model-b"]  # cached on save
    assert len(stub.models_requests()) == 1
    assert stub.models_requests()[0]["method"] == "GET"
    assert stub.models_requests()[0]["path"] == "/v1/models"
    assert stub.models_requests()[0]["auth"] == f"Bearer {SECRET}"
    assert stub.chat_requests() == []  # never a chat completion on save
    # Typing a new key on edit checks again, with the new key.
    stub.requests.clear()
    env.post_json(f"/api/connections/{payload['id']}/update", {
        "label": "Work gateway", "provider": "custom",
        "baseUrl": stub.base_url + "/v1",
        "apiKey": "sk-rotated-bbbbbbbbbbbbbbbb-7777"}, auth)
    assert len(stub.models_requests()) == 1
    assert stub.models_requests()[0]["auth"] == "Bearer sk-rotated-bbbbbbbbbbbbbbbb-7777"
    assert stub.chat_requests() == []
    # The empty-key edit (keep stored) and local presets check nothing.
    stub.requests.clear()
    env.post_json(f"/api/connections/{payload['id']}/update", {
        "label": "Work gateway", "provider": "custom",
        "baseUrl": stub.base_url + "/v1", "apiKey": ""}, auth)
    env.post_json("/api/connections", {
        "label": "Desk ollama", "provider": "ollama",
        "baseUrl": stub.base_url + "/v1"}, auth)
    assert stub.requests == []


def test_a_rejected_check_never_refuses_the_save(env, auth, stub):
    """Non-blocking semantics: a 401 answer marks the row error with the
    named cause, but the save lands and the page tells the truth."""
    stub.models_status = 401
    status, _h, body = env.post_json("/api/connections", {
        "label": "Typo'd key", "provider": "custom",
        "baseUrl": stub.base_url + "/v1", "apiKey": SECRET}, auth)
    assert status == 201  # the save is never refused over a check
    payload = json.loads(body)
    assert payload["status"] == "error"
    assert payload["lastError"] == (
        "the endpoint rejected the API key (HTTP 401); check the key")
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    assert [c["label"] for c in listing["connections"]] == ["Typo'd key"]
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "conn-error" in page
    assert "rejected the API key" in page


def test_an_unreachable_check_never_refuses_the_save(env, auth):
    """A dead endpoint stamps its transport cause and keeps the save;
    the status stays unknown, the spec's transient mapping."""
    status, _h, body = env.post_json("/api/connections", {
        "label": "Dead endpoint", "provider": "custom",
        "baseUrl": "http://127.0.0.1:9/v1", "apiKey": SECRET}, auth)
    assert status == 201
    payload = json.loads(body)
    assert payload["status"] == "unknown"
    assert "refused" in payload["lastError"]
    assert payload["lastCheckedAt"] > 0


def test_a_local_connection_without_a_key_sends_no_auth_header(env, auth, stub):
    connection = _connection(env, auth, stub, provider="ollama", apiKey="")
    status, _h, body = _test(env, auth, connection)
    assert status == 200
    assert json.loads(body)["status"] == "ok"
    assert stub.models_requests()[0]["auth"] is None


def test_extra_gateway_headers_ride_the_models_request(env, auth, stub):
    connection = _connection(env, auth, stub,
                             headers={"X-Gateway": "corp"})
    _test(env, auth, connection)
    assert stub.models_requests()[0]["gateway"] == "corp"


# -- the status mapping, asserted through the stub ------------------------------


def test_a_rejected_key_turns_the_badge_to_error_with_the_named_cause(
        env, auth, stub):
    for code in (401, 403):
        connection = _connection(env, auth, stub, label=f"Rejected {code}")
        stub.models_status = code
        status, _h, body = _test(env, auth, connection)
        payload = json.loads(body)
        assert payload["status"] == "error"
        # The adapter's own sentence, verbatim, never a bare status code.
        assert payload["lastError"] == (
            f"the endpoint rejected the API key (HTTP {code}); check the key")
        # The page shows the same words inline with the badge.
        page = env.request("GET", "/settings", auth)[2].decode("utf-8")
        assert f"the endpoint rejected the API key (HTTP {code})" in page


def test_a_rate_limited_key_stays_ok_with_a_limited_note(env, auth, stub):
    connection = _connection(env, auth, stub)
    before = json.loads(
        env.request("GET", "/api/connections", auth)[2])["connections"][0]
    stub.models_status = 429
    status, _h, body = _test(env, auth, connection)
    payload = json.loads(body)
    assert payload["status"] == "ok"  # a quota answer is not an outage
    assert "rate limiting" in payload["lastError"]
    assert payload["lastCheckedAt"] > before["lastCheckedAt"]
    # The quota answer refreshed neither the cache nor its fetched-at.
    assert payload["models"] == before["models"]
    assert payload["modelsFetchedAt"] == before["modelsFetchedAt"]


def test_a_5xx_is_transient_and_keeps_the_last_status(env, auth, stub):
    connection = _connection(env, auth, stub)
    _test(env, auth, connection)  # a real answer set ok
    ok_checked_at = json.loads(
        env.request("GET", "/api/connections", auth)[2]
    )["connections"][0]["lastCheckedAt"]
    stub.models_status = 503
    status, _h, body = _test(env, auth, connection)
    payload = json.loads(body)
    assert payload["status"] == "ok"  # one bad minute flips nothing
    assert "failed on its own side" in payload["lastError"]
    assert payload["lastCheckedAt"] > ok_checked_at  # the check still stamped
    # And the error case keeps its error through a later 5xx too.
    stub.models_status = 401
    _test(env, auth, connection)
    stub.models_status = 503
    payload = json.loads(_test(env, auth, connection)[2])
    assert payload["status"] == "error"


def test_a_timeout_is_transient_and_keeps_the_last_status(
        env, auth, stub, monkeypatch):
    monkeypatch.setattr(health, "CHECK_TIMEOUT_S", 0.3)
    connection = _connection(env, auth, stub)
    _test(env, auth, connection)  # ok first, so there is a status to keep
    stub.delay = 1.0
    status, _h, body = _test(env, auth, connection)
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert "did not answer within" in payload["lastError"]
    assert payload["lastCheckedAt"] > 0


def test_a_portal_redirect_is_reported_never_chased(env, auth, stub):
    connection = _connection(env, auth, stub)
    stub.models_status = 302
    stub.models_headers = {"Location": "/sso/login"}
    status, _h, body = _test(env, auth, connection)
    payload = json.loads(body)
    assert payload["status"] == "error"
    assert "redirect" in payload["lastError"]
    assert len(stub.requests) == 1  # the hop was named, not followed


# -- the models cache ------------------------------------------------------------


def test_the_models_route_serves_the_cache_and_refresh_refetches(env, auth, stub):
    # A keyless local connection saves without checking, so it starts
    # with the empty cache: fetched-at absent, never an error.
    connection = _connection(env, auth, stub, provider="ollama", apiKey="")
    payload = json.loads(
        env.request("GET", f"/api/connections/{connection['id']}/models", auth)[2])
    assert payload == {"id": connection["id"], "models": [], "fetchedAt": None,
                       "status": "unknown", "lastError": ""}
    _test(env, auth, connection)
    first = json.loads(
        env.request("GET", f"/api/connections/{connection['id']}/models", auth)[2])
    assert first["models"] == ["model-a", "model-b"]
    assert first["fetchedAt"] > 0
    fetched = len(stub.models_requests())
    # A plain read answers from the cache: no new upstream request.
    again = json.loads(
        env.request("GET", f"/api/connections/{connection['id']}/models", auth)[2])
    assert again["models"] == first["models"]
    assert len(stub.models_requests()) == fetched
    # The explicit refresh re-fetches server-side and replaces the cache.
    stub.models = ["model-a", "model-c"]
    refreshed = json.loads(env.request(
        "GET", f"/api/connections/{connection['id']}/models?refresh=1", auth)[2])
    assert refreshed["models"] == ["model-a", "model-c"]
    assert len(stub.models_requests()) == fetched + 1
    assert refreshed["fetchedAt"] >= first["fetchedAt"]


def test_the_models_route_answers_404_and_503_like_the_other_connection_routes(
        env, auth):
    status, _h, _b = env.request("GET", "/api/connections/gone/models", auth)
    assert status == 404
    env.server.keys = None
    status, _h, _b = env.request("GET", "/api/connections/any/models", auth)
    assert status == 503


# -- the deeper check ------------------------------------------------------------


def test_the_deeper_check_is_one_explicit_one_token_completion(env, auth, stub):
    connection = _connection(env, auth, stub)
    assert stub.chat_requests() == []  # nothing before the button
    status, _h, body = env.post_json(
        f"/api/connections/{connection['id']}/check",
        {"model": "typed-by-hand"}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    chats = stub.chat_requests()
    assert len(chats) == 1
    assert chats[0]["auth"] == f"Bearer {SECRET}"
    sent = json.loads(chats[0]["body"])
    assert sent["model"] == "typed-by-hand"
    assert sent["max_tokens"] == 1  # exactly one token, ever


def test_the_deeper_check_refuses_a_blank_model(env, auth, stub):
    connection = _connection(env, auth, stub)
    status, _h, body = env.post_json(
        f"/api/connections/{connection['id']}/check", {}, auth)
    assert status == 400
    assert "model" in json.loads(body)["error"]
    assert stub.requests == []


def test_a_missing_listing_never_blocks_manual_entry(env, auth, stub):
    """The Anthropic compatibility case: no model list, so the free check
    verifies nothing, the badge honestly keeps unknown, and the typed
    model plus the deeper check is the path that proves the key."""
    stub.models_status = 404
    connection = _connection(env, auth, stub)
    status, _h, body = _test(env, auth, connection)
    payload = json.loads(body)
    assert payload["status"] == "unknown"  # nothing was verified either way
    assert "no model listing" in payload["lastError"]
    # The models route answers the empty cache, never an error.
    listing = json.loads(
        env.request("GET", f"/api/connections/{connection['id']}/models", auth)[2])
    assert listing["models"] == []
    # The deeper check with a typed model verifies the key after all.
    status, _h, body = env.post_json(
        f"/api/connections/{connection['id']}/check",
        {"model": "claude-compat-model"}, auth)
    assert json.loads(body)["status"] == "ok"
    assert stub.chat_requests()[0]["auth"] == f"Bearer {SECRET}"


def test_the_deeper_check_maps_a_rejected_key_to_error(env, auth, stub):
    connection = _connection(env, auth, stub)
    stub.chat_status = 401
    status, _h, body = env.post_json(
        f"/api/connections/{connection['id']}/check", {"model": "m"}, auth)
    payload = json.loads(body)
    assert payload["status"] == "error"
    assert "rejected the API key" in payload["lastError"]


# -- the audit trail and the no-JS forms -----------------------------------------


def test_keys_test_lands_in_the_trail_without_secret_material(env, auth, stub):
    connection = _connection(env, auth, stub)
    stub.models_status = 401
    _test(env, auth, connection)
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    row = next(e for e in entries if e["action"] == "keys.test")
    assert row["target"] == connection["id"]
    assert row["status"] == "error"
    assert SECRET not in json.dumps(entries)
    assert "sk-live-quietly" not in json.dumps(entries)
    # The deeper check lands as keys.test too, named as itself.
    stub.models_status = 200
    env.post_json(f"/api/connections/{connection['id']}/check",
                  {"model": "m"}, auth)
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    assert any(e["action"] == "keys.test" and "deeper check" in e["detail"]
               for e in entries)
    # The vocabulary row describes it on the touches page and the trail
    # shows it on the activity page.
    touches = env.request("GET", "/what-this-touches", auth)[2].decode("utf-8")
    assert "keys.test" in touches
    activity = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "keys.test" in activity


def test_the_forms_work_without_javascript(env, auth, stub):
    connection = _connection(env, auth, stub)
    form_headers = dict(auth)
    form_headers["Content-Type"] = "application/x-www-form-urlencoded"
    # The row's Test button is a plain form post back to Settings.
    status, headers, _b = env.request(
        "POST", f"/api/connections/{connection['id']}/test",
        form_headers, urlencode({}).encode("utf-8"))
    assert status == 303
    assert headers["Location"] == "/settings"
    assert json.loads(
        env.request("GET", "/api/connections", auth)[2]
    )["connections"][0]["status"] == "ok"
    # The deeper-check form posts its typed model the same way.
    status, _h, _b = env.request(
        "POST", f"/api/connections/{connection['id']}/check",
        form_headers, urlencode({"model": "typed-in-the-form"}).encode("utf-8"))
    assert status == 303
    sent = json.loads(stub.chat_requests()[0]["body"])
    assert sent["model"] == "typed-in-the-form"
    assert sent["max_tokens"] == 1


def test_last_used_at_is_stamped_by_the_live_traffic_path(env, auth, stub):
    """The live-traffic leg (spec 018): record_use exists for the call
    path and stamps only last_used_at. The assertion that real traffic
    calls it belongs to [018-03], where calls flow through connections."""
    connection = _connection(env, auth, stub)
    stamped = env.server.keys.record_use(connection["id"])
    assert stamped.last_used_at > 0
    payload = json.loads(
        env.request("GET", "/api/connections", auth)[2])["connections"][0]
    assert payload["lastUsedAt"] == stamped.last_used_at
