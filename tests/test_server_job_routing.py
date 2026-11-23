"""Job routing through the real HTTP seam (spec 018, ticket #233).

The resolution hub's promise is about what leaves the desk over the
wire, so this suite drives the booted server with real requests against
loopback stub providers: every stub records the path hit, the
Authorization header and the body of each request, so a test can prove
which connection served a job, with whose key, asking for which model.
The pure order table itself is the one unit seam
(test_keys_resolution.py); here the legs are proven through the
surfaces that use them: the assistant bar, the presentation run, memory
retain, the insight press and web research.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.keys.resolve import JOBS, JOB_LABELS, NO_AI_KEY
from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain
from agentdesk.llm import chat_client

KEY_A = "sk-live-quietly-aaaaaaaaaaaaaaaa-9999"
KEY_B = "sk-live-quietly-bbbbbbbbbbbbbbbb-4444"

PLAN_REPLY = json.dumps({"sections": [
    {"id": "context", "title": "Context"},
    {"id": "findings", "title": "Findings"},
    {"id": "next", "title": "What we do next"},
]})
FILL_REPLY = json.dumps(
    {"title": "Noted", "bullets": ["No figure was supplied."], "citations": []})
FACTS_REPLY = json.dumps({"facts": []})
SOURCES_REPLY = json.dumps({"sources": [
    {"title": "A found page", "url": "https://example.com/a",
     "snippet": "something the provider found"},
]})


def _instant_check(base_url, api_key, extra_headers=None, timeout=None):
    """A save-time prober that answers instantly, hermetically: this
    suite routes live traffic, it does not exercise the save check."""
    from agentdesk.keys import health
    return health.ProbeResult(health.OUTCOME_OK, "", ["hermetic-model"])


class RecordingEndpoint:
    """A loopback provider that records everything a job sends.

    Chat requests are answered in the shape the asking surface needs (a
    presentation plan for plan prompts, a fill for fill prompts, the
    configured ``chat_reply`` for everything else, which is where a test
    makes the reply a facts-free extraction), every other POST is a
    research provider answer, and a GET is an empty model list. Each
    request lands in ``requests`` with its method, path, Authorization
    header and body, so the stub that got hit is itself the proof of
    which base URL a job used.
    """

    def __init__(self, chat_reply: str = "one token") -> None:
        outer = self
        self.chat_reply = chat_reply
        self.requests: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def _record(self, body: bytes) -> None:
                outer.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "body": body,
                })

            def _answer(self, payload: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):  # noqa: N802
                self._record(b"")
                listing = json.dumps({"object": "list", "data": []}).encode("utf-8")
                self._answer(listing)

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                self._record(body)
                if self.path.endswith("/chat/completions"):
                    prompt = body.decode("utf-8", "replace")
                    if "Presentation plan" in prompt:
                        reply = PLAN_REPLY
                    elif "Presentation fill" in prompt:
                        reply = FILL_REPLY
                    else:
                        reply = outer.chat_reply
                    self._answer(json.dumps(
                        {"choices": [{"message": {"content": reply}}]}
                    ).encode("utf-8"))
                else:
                    self._answer(SOURCES_REPLY.encode("utf-8"))

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def chat_requests(self) -> list[dict]:
        """The recorded chat completions."""
        return [r for r in self.requests if r["path"].endswith("/chat/completions")]

    def research_posts(self) -> list[dict]:
        """The recorded research-provider POSTs (any non-chat POST)."""
        return [r for r in self.requests
                if r["method"] == "POST" and not r["path"].endswith("/chat/completions")]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture()
def stub():
    endpoint = RecordingEndpoint()
    try:
        yield endpoint
    finally:
        endpoint.close()


@pytest.fixture()
def keychain():
    return MemoryKeychain()


@pytest.fixture()
def env(stub, keychain):
    booted = server_harness.Booted(
        keychain=KeychainSecrets(keychain), connection_check=_instant_check)
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _save(env, auth, label, base_url, api_key=KEY_A, provider="custom"):
    """One saved connection; the save's own check is the injected instant
    one, so nothing here reaches a real provider."""
    status, _h, body = env.post_json("/api/connections", {
        "label": label, "provider": provider,
        "baseUrl": base_url, "apiKey": api_key,
    }, auth)
    assert status == 201, body
    return json.loads(body)


def _bind(env, auth, job, connection_id, model=""):
    return env.post_json("/api/bindings", {
        "job": job, "connectionId": connection_id, "model": model,
    }, auth)


def _run_presentation(booted, auth, **extra):
    body = {"agent": "presentation", "brief": "the Q3 review",
            "template": "starter", "variant": "dark", "recipe": "briefing",
            "use_memory": "0", "use_workbook": "0", "use_watch": "0"}
    body.update(extra)
    return booted.post_json("/agents/run", body, auth)


def _post_form(booted, auth, path, fields):
    """A browser-shaped POST: form-urlencoded fields, no JavaScript."""
    data = urlencode(fields).encode("utf-8")
    headers = {**auth, "Content-Type": "application/x-www-form-urlencoded"}
    return booted.request("POST", path, headers, data)


# -- the legs, proven on the wire ---------------------------------------------


def test_two_bound_jobs_each_hit_their_own_connection_with_their_own_key_and_model(
        env, auth, stub):
    other = RecordingEndpoint()
    try:
        personal = _save(env, auth, "Personal", stub.base_url + "/v1", KEY_A)
        work = _save(env, auth, "Work", other.base_url + "/v1", KEY_B)
        assert _bind(env, auth, "assistant", personal["id"], "assistant-model")[0] == 200
        assert _bind(env, auth, "presentations", work["id"], "pres-model")[0] == 200

        status, _h, body = env.post_json(
            "/assistant/ask", {"question": "what is due this week?"}, auth)
        assert json.loads(body)["status"] == "ok"
        chats = stub.chat_requests()
        assert len(chats) == 1
        assert chats[0]["path"] == "/v1/chat/completions"
        assert chats[0]["auth"] == f"Bearer {KEY_A}"
        assert json.loads(chats[0]["body"])["model"] == "assistant-model"
        assert other.requests == []  # the assistant never touched the work key

        personal_chats = len(stub.requests)
        status, _h, body = _run_presentation(env, auth)
        payload = json.loads(body)
        assert payload["status"] == "ok", payload
        work_chats = other.chat_requests()
        assert work_chats
        for chat in work_chats:
            assert chat["auth"] == f"Bearer {KEY_B}"
            assert json.loads(chat["body"])["model"] == "pres-model"
        assert len(stub.requests) == personal_chats  # the run stayed on Work
    finally:
        other.close()


def test_an_unbound_job_serves_through_the_default_binding(env, auth, stub):
    other = RecordingEndpoint()
    try:
        personal = _save(env, auth, "Personal", stub.base_url + "/v1", KEY_A)
        _save(env, auth, "Work", other.base_url + "/v1", KEY_B)
        assert _bind(env, auth, "default", personal["id"], "default-model")[0] == 200
        stub.chat_reply = FACTS_REPLY
        other.chat_reply = FACTS_REPLY

        status, _h, body = env.post_json(
            "/memory/retain",
            {"excerpt": "Rita owns the Q3 report and it is due Friday."}, auth)
        assert json.loads(body)["status"] == "ok"
        chats = stub.chat_requests()
        assert len(chats) == 1
        assert chats[0]["auth"] == f"Bearer {KEY_A}"
        assert json.loads(chats[0]["body"])["model"] == "default-model"
        assert other.requests == []  # the unstarred connection serves nothing
    finally:
        other.close()


def test_a_single_enabled_connection_serves_every_job_without_any_binding(
        env, auth, stub, monkeypatch):
    monkeypatch.delenv("AGENTDESK_LLM_MODEL", raising=False)
    connection = _save(env, auth, "Only", stub.base_url + "/v1", KEY_A)
    env.server.settings.set("memory_capture", False)  # keep the count exact
    stub.chat_reply = FACTS_REPLY

    status, _h, body = env.post_json(
        "/assistant/ask", {"question": "summarize my week"}, auth)
    assert json.loads(body)["status"] == "ok"
    status, _h, body = env.post_json(
        "/memory/retain",
        {"excerpt": "Rita owns the Q3 report and it is due Friday."}, auth)
    assert json.loads(body)["status"] == "ok"

    chats = stub.chat_requests()
    assert len(chats) == 2  # two jobs, one connection, no bindings anywhere
    for chat in chats:
        assert chat["auth"] == f"Bearer {KEY_A}"
        assert json.loads(chat["body"])["model"] == "gpt-4o-mini"
    assert connection["isDefault"] is False


def test_a_single_connection_with_a_model_sends_that_model_on_every_job(
        env, auth, stub, monkeypatch):
    """Spec 022: a connection remembers its model and every call uses it.
    With no model of its own (the test above) a connection keeps sending
    the environment's gpt-4o-mini; with one, nothing asks for gpt-4o-mini."""
    monkeypatch.delenv("AGENTDESK_LLM_MODEL", raising=False)
    status, _h, body = env.post_json("/api/connections", {
        "label": "Mock AI", "provider": "custom",
        "baseUrl": stub.base_url + "/v1", "apiKey": KEY_A,
        "model": "mock-chat"}, auth)
    assert status == 201, body
    env.server.settings.set("memory_capture", False)  # keep the count exact
    stub.chat_reply = FACTS_REPLY

    status, _h, body = env.post_json(
        "/assistant/ask", {"question": "what changed this week?"}, auth)
    assert json.loads(body)["status"] == "ok"
    status, _h, body = env.post_json(
        "/memory/retain",
        {"excerpt": "Rita owns the Q3 report and it is due Friday."}, auth)
    assert json.loads(body)["status"] == "ok"

    chats = stub.chat_requests()
    assert len(chats) == 2  # the assistant turn and one memory call
    for chat in chats:
        assert chat["auth"] == f"Bearer {KEY_A}"
        assert json.loads(chat["body"])["model"] == "mock-chat"


def test_the_environment_serves_when_nothing_is_saved_and_its_key_rides_the_header(
        stub, keychain, monkeypatch):
    monkeypatch.setenv("AGENTDESK_LLM_BASE", stub.base_url + "/v1")
    monkeypatch.setenv("AGENTDESK_LLM_KEY", "env-key-1234")
    monkeypatch.setenv("AGENTDESK_LLM_MODEL", "env-model-9")
    booted = server_harness.Booted(
        keychain=KeychainSecrets(keychain), connection_check=_instant_check)
    try:
        booted.server.settings.set("memory_capture", False)  # keep the count exact
        auth = booted.exchange()
        listing = json.loads(booted.request("GET", "/api/connections", auth)[2])
        assert listing["connections"] == []  # not a single saved connection
        assert keychain.secrets == {}

        status, _h, body = booted.post_json(
            "/assistant/ask", {"question": "any commitments?"}, auth)
        assert json.loads(body)["status"] == "ok"
        chats = stub.chat_requests()
        assert len(chats) == 1
        assert chats[0]["path"] == "/v1/chat/completions"
        assert chats[0]["auth"] == "Bearer env-key-1234"
        assert json.loads(chats[0]["body"])["model"] == "env-model-9"
    finally:
        booted.close()


def test_with_nothing_saved_anywhere_a_model_call_says_no_ai_key_is_saved(
        keychain, monkeypatch):
    for name in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY", "AGENTDESK_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    booted = server_harness.Booted(
        keychain=KeychainSecrets(keychain), connection_check=_instant_check)
    try:
        auth = booted.exchange()
        # The same one sentence answers every surface (spec 022): it names
        # the fix and never a job, a binding or an environment variable.
        for path, payload_body in (
                ("/assistant/ask", {"question": "hello"}),
                ("/memory/retain",
                 {"excerpt": "Rita owns the Q3 report and it is due Friday."})):
            status, _h, body = booted.post_json(path, payload_body, auth)
            payload = json.loads(body)
            assert payload["status"] == "degraded"
            assert payload["cause"] == NO_AI_KEY
            assert "unbound" not in payload["cause"]
            assert "AGENTDESK_" not in payload["cause"]
    finally:
        booted.close()


# -- the surfaces that used to bypass saved settings ---------------------------


def test_an_insight_press_rides_the_insights_job_bound_connection(
        env, auth, stub, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    connection = _save(env, auth, "Insights", stub.base_url + "/v1", KEY_A)
    assert _bind(env, auth, "insights", connection["id"], "insight-model")[0] == 200

    status, _h, body = _post_form(env, auth, "/insight/press", {
        "kind": "explain-range", "text": "Booked falls as Margin rises.",
    })
    assert status == 200
    assert "one token" in body.decode("utf-8")  # the bound endpoint answered
    chats = stub.chat_requests()
    assert len(chats) == 1
    assert chats[0]["auth"] == f"Bearer {KEY_A}"
    assert json.loads(chats[0]["body"])["model"] == "insight-model"


def test_web_research_rides_the_research_web_job_bound_connection(env, auth, stub):
    connection = _save(env, auth, "Research", stub.base_url + "/v1", KEY_A)
    assert _bind(env, auth, "research-web", connection["id"], "")[0] == 200

    status, _h, body = _run_presentation(env, auth, use_research="1")
    payload = json.loads(body)
    assert payload["status"] == "awaiting-review", payload
    fetches = stub.research_posts()
    assert len(fetches) == 1
    assert fetches[0]["path"] == "/v1"  # the connection's own base URL
    assert fetches[0]["auth"] == f"Bearer {KEY_A}"
    sent = json.loads(fetches[0]["body"])
    assert sent["topic"] == "the Q3 review"
    assert sent["sections"] == ["Context", "Findings", "What we do next"]
    web = payload["artifact"]["webSources"]
    assert [row["url"] for row in web] == ["https://example.com/a"]


def test_web_research_keeps_the_legacy_settings_provider_when_nothing_is_bound(
        stub, keychain):
    booted = server_harness.Booted(
        llm=chat_client(stub.base_url + "/v1", "", "mock"),
        keychain=KeychainSecrets(keychain), connection_check=_instant_check)
    try:
        booted.server.llm_endpoint = stub.base_url + "/v1"
        booted.server.settings.set("research_provider_url", stub.base_url + "/research")
        booted.server.settings.set("research_provider_key", "settings-research-key")
        auth = booted.exchange()

        status, _h, body = _run_presentation(booted, auth, use_research="1")
        payload = json.loads(body)
        assert payload["status"] == "awaiting-review", payload
        fetches = stub.research_posts()
        assert len(fetches) == 1
        assert fetches[0]["path"] == "/research"  # the settings row's URL
        assert fetches[0]["auth"] == "Bearer settings-research-key"
    finally:
        booted.close()


# -- deleting a connection that serves jobs -------------------------------------


def test_the_first_delete_of_a_bound_connection_answers_409_naming_the_jobs(
        env, auth, keychain):
    connection = _save(env, auth, "Work gateway", "https://llm.corp.example/v1", KEY_A)
    assert _bind(env, auth, "assistant", connection["id"])[0] == 200
    assert _bind(env, auth, "memory", connection["id"])[0] == 200

    status, _h, body = env.post_json(
        f"/api/connections/{connection['id']}/delete", {}, auth)
    assert status == 409
    payload = json.loads(body)
    assert payload["boundJobs"] == ["assistant", "memory"]
    assert "assistant" in payload["error"]
    assert "memory" in payload["error"]
    # named, not deleted: the connection and its key are still in place
    labels = [c["label"] for c in json.loads(
        env.request("GET", "/api/connections", auth)[2])["connections"]]
    assert labels == ["Work gateway"]
    assert keychain.secrets != {}

    status, _h, body = env.post_json(
        f"/api/connections/{connection['id']}/delete", {"confirm": True}, auth)
    assert status == 200
    assert json.loads(body) == {"ok": True, "id": connection["id"]}
    assert keychain.secrets == {}  # the keychain entry went with it
    assert json.loads(
        env.request("GET", "/api/connections", auth)[2])["connections"] == []
    assert json.loads(env.request("GET", "/api/bindings", auth)[2])["bindings"] == []
    entries = json.loads(env.request("GET", "/audit/tail", auth)[2])["entries"]
    row = next(e for e in entries if e["action"] == "keys.delete")
    assert "unbound" in row["detail"]
    assert "assistant" in row["detail"] and "memory" in row["detail"]


def test_a_no_js_delete_post_gets_the_warning_page_and_the_confirmed_post_deletes(
        env, auth, keychain):
    connection = _save(env, auth, "Work gateway", "https://llm.corp.example/v1", KEY_A)
    assert _bind(env, auth, "presentations", connection["id"])[0] == 200

    status, _h, body = _post_form(
        env, auth, f"/api/connections/{connection['id']}/delete", {})
    assert status == 200
    page = body.decode("utf-8")
    assert "is bound to the" in page and "presentations" in page
    assert f"action='/api/connections/{connection['id']}/delete'" in page
    assert "name='confirm'" in page
    # The whole consequence paragraph, pinned verbatim (spec 019 #258):
    # a refactor that reflows the source fragments and drops one join
    # space prints run-on words ("job.Deleting", "thosebindings") and
    # fails here, so the one page that must read as carefully reviewed
    # cannot regress by that class alone.
    assert (
        "<p><b>Work gateway</b> is bound to the <b>presentations</b> job."
        " Deleting it removes the connection, its keychain entry and those"
        " bindings; the jobs fall back to the default binding, the single"
        " remaining connection, or the environment, and a job with none of"
        " those answers with a named unbound error instead of a silent"
        " one.</p>"
    ) in page
    for run_on in ("job.Deleting", "thosebindings", "singleremaining",
                   "thoseanswers"):
        assert run_on not in page, run_on
    # The confirm reads as destructive; Keep it stays the quiet secondary.
    assert ("<button class='btn btn-danger' type='submit'>"
            "Delete Work gateway and unbind presentations</button>") in page
    assert "<a class='btn btn-secondary' href='/settings'>Keep it</a>" in page
    labels = [c["label"] for c in json.loads(
        env.request("GET", "/api/connections", auth)[2])["connections"]]
    assert labels == ["Work gateway"]  # the warning answered, nothing landed

    # The named-jobs sentence keeps its pluralization with two jobs
    # bound (job_key order names them).
    assert _bind(env, auth, "memory", connection["id"])[0] == 200
    status, _h, body = _post_form(
        env, auth, f"/api/connections/{connection['id']}/delete", {})
    assert status == 200
    plural_page = body.decode("utf-8")
    assert (
        "<b>Work gateway</b> is bound to the <b>memory, presentations</b>"
        " jobs. Deleting it removes"
    ) in plural_page
    for run_on in ("job.Deleting", "thosebindings", "singleremaining",
                   "thoseanswers"):
        assert run_on not in plural_page, run_on

    status, headers, _b = _post_form(
        env, auth, f"/api/connections/{connection['id']}/delete",
        {"confirm": "1"})
    assert status == 303
    # The redirect anchors to the connections card.
    assert headers["Location"] == "/settings#connections"
    assert keychain.secrets == {}
    assert json.loads(env.request("GET", "/api/bindings", auth)[2])["bindings"] == []


# -- the bindings endpoint's own contract ----------------------------------------


def test_the_bindings_endpoint_round_trips_a_bind_and_refuses_with_names(
        env, auth):
    connection = _save(env, auth, "Work gateway", "https://llm.corp.example/v1", KEY_A)

    status, _h, body = _bind(env, auth, "assistant", connection["id"],
                             "assistant-model")
    assert status == 200
    payload = json.loads(body)
    assert payload["job"] == "assistant"
    assert payload["connectionId"] == connection["id"]
    assert payload["model"] == "assistant-model"
    assert payload["updatedAt"] > 0
    listed = json.loads(env.request("GET", "/api/bindings", auth)[2])
    assert listed["jobs"] == list(JOBS)
    assert [b["job"] for b in listed["bindings"]] == ["assistant"]
    assert listed["bindings"][0]["connectionId"] == connection["id"]

    status, _h, body = env.post_json("/api/bindings", {
        "job": "assistant", "connectionId": connection["id"], "modell": "x",
    }, auth)
    assert status == 400
    error = json.loads(body)["error"]
    assert "modell" in error
    for accepted in ("job", "connectionId", "model"):
        assert accepted in error

    status, _h, body = env.post_json("/api/bindings", {
        "job": "scheduling", "connectionId": connection["id"]}, auth)
    assert status == 400
    error = json.loads(body)["error"]
    assert "scheduling" in error
    for job in JOBS:
        assert job in error

    status, _h, body = env.post_json("/api/bindings", {
        "job": "assistant", "connectionId": "gone"}, auth)
    assert status == 404
    assert "gone" in json.loads(body)["error"]


def test_an_empty_connection_id_unbinds_the_job(env, auth):
    connection = _save(env, auth, "Work gateway", "https://llm.corp.example/v1", KEY_A)
    assert _bind(env, auth, "assistant", connection["id"], "assistant-model")[0] == 200

    status, _h, body = env.post_json(
        "/api/bindings", {"job": "assistant", "connectionId": ""}, auth)
    assert status == 200
    assert json.loads(body) == {"job": "assistant", "connectionId": "", "model": ""}
    listed = json.loads(env.request("GET", "/api/bindings", auth)[2])
    assert listed["bindings"] == []


# -- the Settings page reads the bindings back ------------------------------------


def test_the_settings_page_renders_the_jobs_section_with_seven_pickers(
        env, auth):
    first = _save(env, auth, "Work gateway", "https://llm.corp.example/v1", KEY_A)
    _save(env, auth, "Desk ollama", "http://localhost:11434/v1",
          api_key="", provider="ollama")
    assert _bind(env, auth, "assistant", first["id"], "assistant-model")[0] == 200

    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "id='jobs'" in page
    assert page.count("name='job'") == 7  # one picker per job, no more
    for job in JOBS:
        assert f"value='{job}'" in page
    for label in JOB_LABELS.values():
        assert label in page
    # The page never says job, binding or bound (spec 022): a place either
    # answers through a chosen AI or like everything else.
    assert "Same as everything else" in page
    assert "Answers through <b>Work gateway</b>" in page
    assert "value='assistant-model'" in page
    assert page.count("Answers like everything else.") == 6  # the six without a choice
    for banned in ("Not bound", "Unbound", "BOUND", " is bound", "unbinding"):
        assert banned not in page, banned
    # The model label is short and the cached-lists-or-typed fact is the
    # disclosure's, stated once (spec 019 #259). Counted inside the card,
    # because the connection form carries a Model field of its own.
    jobs_start = page.index("id='jobs'")
    jobs_card = page[jobs_start:page.index("</section>", jobs_start)]
    assert jobs_card.count(">Model</label>") == 7
    assert page.count("picked from the cached lists or typed") == 1
