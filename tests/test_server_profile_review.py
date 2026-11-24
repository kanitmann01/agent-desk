"""The profile-review step against the real server and a stub endpoint
(ticket 09).

Ten asks, one review pass, and the stub endpoint's one grounded add
becomes a learned line: visible on Settings with its "Learned from
activity on <date>" provenance and the third switch, listed on the
Activity page with Undo, removable through the #198 route, and that
removal undone from the ledger route. The stated preferences file is
byte-identical through all of it, and the llm.profile audit rows hold
the model and the size, never the words.
"""

import hashlib
import json
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
from agentdesk.server import app as server_app

LINE = "Owns the Halvorsen Freight and Kestrel Foods accounts."
ASK = "summarise the Halvorsen Freight order history"


class OpsEndpoint:
    """A loopback chat-completions stub that answers every call with
    one canned ops JSON and records what it was sent."""

    def __init__(self, reply: str) -> None:
        outer = self
        self.requests: list[dict] = []
        self.reply = reply

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - the stdlib's spelling
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append(body)
                data = json.dumps({
                    "choices": [{"message": {"role": "assistant",
                                             "content": outer.reply}}],
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # noqa: A003 - stay quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "preferences.json").write_text(
        '{"version": 3, "focusTopics": ["Acme"], "replies": {}}',
        encoding="utf-8")
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _ten_asks(env):
    for _ in range(10):
        env.server.activity_log.record("research", ASK)


def _grounded_reply(env) -> str:
    # Cite the real window ids the desk just recorded.
    ids = [row["id"] for row in env.server.activity_log.entries()][-2:]
    return json.dumps({"ops": [
        {"op": "add", "text": LINE, "from": ids},
    ]})


def test_ten_asks_and_a_pass_learn_one_line(env, auth):
    _ten_asks(env)
    stub = OpsEndpoint(_grounded_reply(env))
    try:
        env.server.settings.set("llm_base", stub.base_url)
        env.server.settings.set("llm_model", "stub-model")
        outcome = server_app.review_profile(
            env.server, env.server.ledger, env.server.settings,
            audit_conn=env.server.audit_conn)
        assert outcome == {"applied": 1, "dropped": 0}
        # One call, and what left the machine: the grounding rule, the
        # asks cut at 300 characters, never the stores.
        assert len(stub.requests) == 1
        prompt = stub.requests[0]["messages"][0]["content"]
        assert "Never infer the user's traits" in prompt
        assert ASK in prompt
        assert '"learned": []' in prompt
        entry = env.server.learned_profile.document()["entries"][0]
        assert entry["text"] == LINE
        assert entry["learnedFrom"] == {"activity": [9, 10]}
    finally:
        stub.close()

    # Settings shows the line, its provenance and the third switch.
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert LINE in page
    assert "Learned from activity on" in page
    assert "data-setting='learn_profile'" in page
    assert "Learn lines about you from your recent asks" in page

    # The Activity page lists the change with an Undo button.
    activity = env.request("GET", "/settings/activity", auth)[2] \
        .decode("utf-8")
    assert "Learned a line about you" in activity
    assert "/api/ledger/undo" in activity

    # The endpoint audit rows hold the model and the size only.
    rows = env.server.audit_conn.execute(
        "SELECT action, status, model, request_bytes, detail, target"
        " FROM audit WHERE action IN ('llm.profile', 'profile.learned')"
        " ORDER BY id").fetchall()
    assert [row[0] for row in rows] == ["llm.profile", "profile.learned"]
    assert rows[0][1] == "ok" and rows[0][2] == "stub-model"
    assert rows[0][3] > 0 and LINE not in (rows[0][4] or "")

    # The removal route from #198 takes the learned line back.
    entry_id = env.server.learned_profile.document()["entries"][0]["id"]
    status, _h, body = env.post_json("/api/profile/learned/remove",
                                     {"id": entry_id}, auth)
    assert status == 200
    assert json.loads(body)["removed"] is True
    assert env.server.learned_profile.document()["entries"] == []

    # And Undo of the removal puts it back (the Activity page's route).
    removed_entry = json.loads(body)["entry"]
    status, _h, body = env.post_json("/api/ledger/undo",
                                     {"id": removed_entry}, auth)
    assert status == 200
    assert env.server.learned_profile.document()["entries"][0]["text"] == LINE


def test_a_hub_connection_serves_the_review_through_its_own_endpoint(env):
    """A fresh install has no llm_base row any more: the connections hub
    is the only endpoint the user configures. The review must use that
    resolved connection, with its own base URL, key and label, instead
    of replacing it with the settings client and failing as unconfigured.
    """
    _ten_asks(env)
    stub = OpsEndpoint(_grounded_reply(env))
    try:
        env.server.settings.set("llm_base", "")
        # The row records its key the way every real save does: the
        # masked hint is what tells the hub the row can serve.
        connection = env.server.keys.add(
            "Hub only", "custom", stub.base_url, masked_key="sk-...3456",
            is_default=True)
        assert env.server.keychain.store(connection.id, "sk-hub-only-123456")
        env.server.keys.bind("memory", connection.id, "hub-model")
        outcome = server_app.review_profile(
            env.server, env.server.ledger, env.server.settings,
            audit_conn=env.server.audit_conn)
    finally:
        stub.close()
    assert outcome == {"applied": 1, "dropped": 0}
    assert len(stub.requests) == 1
    row = env.server.audit_conn.execute(
        "SELECT status, model, target FROM audit"
        " WHERE action = 'llm.profile' ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("ok", "hub-model", "Hub only")


def test_the_third_switch_turns_the_review_off_and_on(env, auth):
    """The Settings switch is the user's off switch (spec 016 section
    6.5): the page renders it with data-setting='learn_profile', and the
    generic toggle post must reach it. It did not: the route's allowlist
    named learn_topics but not learn_profile, so the switch answered
    "unknown setting" and the third control on the page was dead. Off
    takes the step's gate down with no pass to wait for; on puts it
    back."""
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "data-setting='learn_profile'" in page
    # The step's gate needs a base URL as well as the switch, so the
    # switch is measured with one configured: it must turn the one thing
    # the user controls off and on without waiting for a pass.
    env.server.settings.set("llm_base", "http://127.0.0.1:9/v1")
    assert server_app._profile_review_enabled(env.server.settings) is True
    status, _h, body = env.post_json("/settings/toggle",
                                     {"key": "learn_profile"}, auth)
    assert status == 200
    assert json.loads(body) == {"key": "learn_profile", "value": False}
    assert env.server.settings.get("learn_profile") is False
    assert server_app._profile_review_enabled(env.server.settings) is False
    widgets = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert widgets["learn_profile"] is False
    status, _h, body = env.post_json("/settings/toggle",
                                     {"key": "learn_profile"}, auth)
    assert status == 200
    assert json.loads(body) == {"key": "learn_profile", "value": True}
    assert server_app._profile_review_enabled(env.server.settings) is True


def test_preferences_stay_byte_identical_through_it_all(env, auth):
    stated = server_app.default_data_dir() / "preferences.json"
    before = hashlib.sha256(stated.read_bytes()).hexdigest()
    _ten_asks(env)
    stub = OpsEndpoint(_grounded_reply(env))
    try:
        env.server.settings.set("llm_base", stub.base_url)
        assert server_app.review_profile(
            env.server, env.server.ledger, env.server.settings,
            audit_conn=env.server.audit_conn)["applied"] == 1
    finally:
        stub.close()
    entry_id = env.server.learned_profile.document()["entries"][0]["id"]
    env.post_json("/api/profile/learned/remove", {"id": entry_id}, auth)
    after = hashlib.sha256(stated.read_bytes()).hexdigest()
    assert after == before
