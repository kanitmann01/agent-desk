"""Auth and hardening tests through the real HTTP seam.

Every test here drives the actual server over an actual socket: the
acceptance criteria for the walking skeleton are written against the API,
not against internals.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.server.auth import SessionStore, session_id_from_cookie


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def test_request_without_session_cookie_is_rejected(booted):
    status, _headers, _body = booted.request("GET", "/", booted.host_header())
    assert status == 401


def test_token_bootstrap_yields_a_working_session_cookie(booted):
    headers = booted.exchange()
    status, _headers, _body = booted.request("GET", "/", headers)
    assert status == 200


def test_exchange_sets_the_hardened_cookie(booted):
    status, headers, _body = booted.request(
        "GET", f"/auth/{booted.token()}", booted.host_header()
    )
    assert status == 303
    cookie = headers["Set-Cookie"]
    assert cookie.startswith("agentdesk_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Path=/" in cookie


def test_exchange_redirects_to_the_dashboard(booted):
    status, headers, _body = booted.request(
        "GET", f"/auth/{booted.token()}", booted.host_header()
    )
    assert status == 303
    assert headers["Location"] == "/"


def test_wrong_bootstrap_token_is_rejected_without_a_cookie(booted):
    status, headers, _body = booted.request(
        "GET", "/auth/not-the-token", booted.host_header()
    )
    assert status == 403
    assert "Set-Cookie" not in headers


def test_invalid_cookie_value_is_rejected(booted):
    headers = booted.host_header() | {"Cookie": "agentdesk_session=forged"}
    status, _headers, _body = booted.request("GET", "/", headers)
    assert status == 401


def test_foreign_origin_is_rejected_even_with_a_valid_session(booted):
    headers = booted.exchange() | {"Origin": "https://evil.example"}
    status, _headers, _body = booted.request("GET", "/", headers)
    assert status == 403


def test_foreign_host_is_rejected_even_with_a_valid_session(booted):
    headers = booted.exchange() | {"Host": "evil.example:80"}
    status, _headers, _body = booted.request("GET", "/", headers)
    assert status == 403


def test_localhost_host_is_accepted(booted):
    headers = booted.exchange() | {"Host": f"localhost:{booted.port}"}
    status, _headers, _body = booted.request("GET", "/", headers)
    assert status == 200


def test_server_binds_loopback_only(booted):
    assert booted.server.server_address[0] == "127.0.0.1"


def test_non_loopback_bind_is_refused():
    from agentdesk.server import app

    with pytest.raises(ValueError):
        app.create_server(host="0.0.0.0")
    with pytest.raises(ValueError):
        app.create_server(host="192.168.1.10")


def test_expired_sessions_stop_validating():
    now = 1_000.0
    store = SessionStore(max_age=60, clock=lambda: now)
    sid = store.exchange(store.bootstrap_token())
    assert sid is not None
    assert store.validate(sid)
    now += 61
    assert not store.validate(sid)


def test_cookie_header_parsing_pulls_the_session_id():
    header = "other=1; agentdesk_session=abc123; extra=2"
    assert session_id_from_cookie(header) == "abc123"


def test_missing_or_empty_cookie_header_yields_no_session():
    assert session_id_from_cookie(None) is None
    assert session_id_from_cookie("other=1") is None
    assert session_id_from_cookie("agentdesk_session=") is None
