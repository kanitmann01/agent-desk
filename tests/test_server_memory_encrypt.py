"""Memory encryption over HTTP (ticket #94): the encrypt form flow, the
locked banner and the audit row.

The seam tests drive the real server with a file-backed memory store:
the dry-run counts page, the confirm-gated conversion, the
already-encrypted no-op, the locked banner for a marker without its
key, and the memory.encrypt audit row. The key never crosses the wire
and never lands in any response.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.memory.crypto import load_key
from agentdesk.memory.store import MemoryStore, ensure_key_file, write_key_file


KEY = load_key(bytes(range(32)))


class CaptureLlm:
    """The stub adapter the server tests use: records every prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "A short answer."


def _plain_boot(tmp_path):
    """A plaintext file-backed store with the action's key path wired."""
    db = tmp_path / "memory.sqlite3"
    key_path = tmp_path / "memory.key"
    conn = sqlite3.connect(str(db), check_same_thread=False)
    store = MemoryStore(conn, time.time, key_path=key_path)
    booted = server_harness.Booted(memory_store=store)
    original_close = booted.close

    def close():
        original_close()
        conn.close()

    booted.close = close
    return booted, db, key_path


def _locked_boot(tmp_path):
    """A bank sealed in a previous life, reopened without its key."""
    db = tmp_path / "memory.sqlite3"
    key_path = tmp_path / "memory.key"
    first = sqlite3.connect(str(db), check_same_thread=False)
    seeded = MemoryStore(first, time.time, key=KEY)
    seeded.add("revenue is 220", source="page")
    first.close()
    conn = sqlite3.connect(str(db), check_same_thread=False)
    store = MemoryStore(conn, time.time, key_path=key_path)
    assert store.locked_cause is not None
    booted = server_harness.Booted(memory_store=store, llm=CaptureLlm())
    original_close = booted.close

    def close():
        original_close()
        conn.close()

    booted.close = close
    return booted, db, key_path


@pytest.fixture()
def plain_env(tmp_path):
    booted, db, key_path = _plain_boot(tmp_path)
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def locked_env(tmp_path):
    booted, _db, _key_path = _locked_boot(tmp_path)
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(plain_env):
    return plain_env.exchange()


@pytest.fixture()
def locked_auth(locked_env):
    return locked_env.exchange()


def _add_fact(env, auth, text):
    status, _h, _b = env.post_json("/memory/add", {"text": text}, auth)
    assert status == 201


def _form_post(env, auth, path, fields: dict):
    from urllib.parse import urlencode
    body = urlencode(fields).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
        **auth,
    }
    return env.request("POST", path, headers, body)


# -- the gate ---------------------------------------------------------------


def test_the_encrypt_routes_require_a_session(plain_env):
    host = plain_env.host_header()
    status, _h, _b = plain_env.request("GET", "/memory/encrypt", host)
    assert status == 401
    status, _h, _b = plain_env.request("POST", "/memory/encrypt", host)
    assert status == 401


# -- the dry-run page --------------------------------------------------------


def test_the_plain_memory_page_offers_the_encrypt_action(plain_env, auth):
    status, _h, body = plain_env.request("GET", "/memory", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "/memory/encrypt" in page


def test_the_encrypt_page_shows_the_dry_run_counts(plain_env, auth):
    _add_fact(plain_env, auth, "revenue is 220")
    _add_fact(plain_env, auth, "the meeting room is booked")
    plain_env.server.memory.add_source("we met Tuesday")
    plain_env.server.memory.resolve_and_link(1, [("Acme", "org")])
    plain_env.server.memory.conn.execute(
        "INSERT INTO observations (scope_key, text, confidence, created_ts, updated_ts)"
        " VALUES ('all', 'Money matters recur.', 0.9, 100.0, 100.0)"
    )
    plain_env.server.memory.conn.commit()
    status, _h, body = plain_env.request("GET", "/memory/encrypt", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "2 facts" in page
    assert "1 source" in page
    assert "1 entity" in page
    assert "1 observation" in page
    assert "name='confirm'" in page
    # Nothing converted yet: the facts still read as plaintext.
    assert "revenue is 220" in page


# -- the conversion -----------------------------------------------------------


def test_encrypt_without_the_confirm_checkbox_is_refused(plain_env, auth):
    _add_fact(plain_env, auth, "revenue is 220")
    status, _h, body = _form_post(plain_env, auth, "/memory/encrypt", {})
    assert status == 400
    assert b"confirm" in body
    row = plain_env.server.memory.conn.execute(
        "SELECT text FROM facts"
    ).fetchone()
    assert row[0] == "revenue is 220", "nothing converted"


def test_encrypt_with_confirm_converts_and_the_page_says_so(tmp_path):
    booted, db, key_path = _plain_boot(tmp_path)
    try:
        auth = booted.exchange()
        _add_fact(booted, auth, "revenue is 220")
        status, headers, _b = _form_post(booted, auth, "/memory/encrypt",
                                         {"confirm": "on"})
        assert status == 303
        assert headers["Location"] == "/memory"
        # The key file exists and the marker is set.
        assert key_path.exists()
        assert len(key_path.read_bytes()) == 32
        marker = booted.server.memory.conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'encryption'"
        ).fetchone()
        assert marker is not None
        # The page reads through decryption and says the bank is sealed.
        status, _h, body = booted.request("GET", "/memory", auth)
        page = body.decode("utf-8")
        assert status == 200
        assert "revenue is 220" in page
        assert "encrypted at rest" in page
        # The raw file carries no plaintext fact text.
        raw = db.read_bytes()
        assert b"revenue is 220" not in raw
        # The audit row names the field count, never the key bytes or a
        # fact text.
        rows = audit_store.entries(booted.server.audit_conn)
        row = next(e for e in rows if e["action"] == "memory.encrypt")
        row_json = json.dumps(row)
        key = key_path.read_bytes()
        assert key.decode("latin-1") not in row_json
        assert key.hex() not in row_json
        assert "revenue is 220" not in row_json
    finally:
        booted.close()


def test_the_encrypt_page_on_an_already_encrypted_bank_says_so(tmp_path):
    db = tmp_path / "memory.sqlite3"
    key_path = tmp_path / "memory.key"
    write_key_file(key_path)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    store = MemoryStore(conn, time.time, key=ensure_key_file(key_path))
    store.add("revenue is 220", source="page")
    booted = server_harness.Booted(memory_store=store)
    try:
        auth = booted.exchange()
        status, _h, body = booted.request("GET", "/memory/encrypt", auth)
        page = body.decode("utf-8")
        assert status == 200
        assert "already encrypted" in page
        assert 'name="confirm"' not in page
        # The POST is a no-op that says so too.
        status, _h, body = booted.post_json("/memory/encrypt", {}, auth)
        assert status == 409
        assert "already encrypted" in body.decode("utf-8")
    finally:
        booted.close()
        conn.close()


# -- the locked banner --------------------------------------------------------


def test_the_locked_memory_page_shows_the_banner_with_the_cause(locked_env,
                                                                 locked_auth):
    status, _h, body = locked_env.request("GET", "/memory", locked_auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "The memory database is encrypted" in page
    assert "the key file is missing" in page
    assert "memory.key" in page


def test_locked_memory_actions_refuse_with_the_cause(locked_env, locked_auth):
    status, _h, body = locked_env.post_json(
        "/memory/add", {"text": "nope"}, locked_auth
    )
    assert status == 503
    assert "key file is missing" in body.decode("utf-8")
    status, _h, body = locked_env.post_json(
        "/memory/recall", {"query": "x"}, locked_auth
    )
    assert status == 503


def test_the_assistant_still_answers_with_locked_memory(locked_env, locked_auth):
    status, _h, body = locked_env.post_json(
        "/assistant/ask", {"question": "anything"}, locked_auth
    )
    assert status == 200
    assert json.loads(body)["status"] == "ok"
    assert "Known facts" not in locked_env.server.llm.prompts[0]
