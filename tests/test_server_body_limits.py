"""Request body limits through the real HTTP seam.

A body over the 1 MB stash limit is still read and discarded, up to a
hard cap, so a keep-alive connection survives the refusal: the next
request on the same connection is answered. Beyond the cap the server
answers and closes the connection rather than reading unboundedly; the
bounds decision itself is a pure helper with unit tests here.
"""
import http.client
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.server.app import MAX_BODY_BYTES, MAX_DRAIN_BYTES, body_drain_plan


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def post_on(conn, path, headers, data):
    merged = dict(headers)
    merged["Content-Type"] = "application/json"
    conn.request("POST", path, body=data, headers=merged)
    response = conn.getresponse()
    return response.status, dict(response.getheaders()), response.read()


def test_body_drain_plan_picks_skip_stash_discard_and_close():
    assert body_drain_plan(-1) == "skip"
    assert body_drain_plan(0) == "skip"
    assert body_drain_plan(1) == "stash"
    assert body_drain_plan(MAX_BODY_BYTES) == "stash"
    assert body_drain_plan(MAX_BODY_BYTES + 1) == "discard"
    assert body_drain_plan(MAX_DRAIN_BYTES) == "discard"
    assert body_drain_plan(MAX_DRAIN_BYTES + 1) == "close"


def test_gate_failure_closes_the_connection_with_the_body_unread(booted):
    """The gate answers before the drain runs, so its refusals must close
    the connection: an unread body on a kept-alive connection is exactly
    what the drain exists to prevent."""
    conn = http.client.HTTPConnection("127.0.0.1", booted.port, timeout=5)
    try:
        conn.request("POST", "/research", body=b'{"question": "hi"}',
                     headers={"Host": f"127.0.0.1:{booted.port}"})
        response = conn.getresponse()
        response.read()
        assert response.status == 401
        assert response.getheader("Connection", "").lower() == "close"
        # http.client dropped the socket because the server ended it.
        assert response.will_close and conn.sock is None
    finally:
        conn.close()


def test_oversized_body_is_drained_and_keep_alive_survives(booted):
    headers = booted.exchange()
    conn = http.client.HTTPConnection("127.0.0.1", booted.port, timeout=5)
    try:
        data = b"x" * (MAX_BODY_BYTES + 2048)
        status, _h, _b = post_on(conn, "/research", headers, data)
        assert status == 400  # the refusal, with the body consumed
        conn.request("GET", "/health", headers=headers)
        response = conn.getresponse()
        assert response.status == 200  # same connection, still usable
        response.read()
    finally:
        conn.close()


def test_calendar_upload_reject_leaves_the_connection_usable(booted):
    headers = booted.exchange()
    conn = http.client.HTTPConnection("127.0.0.1", booted.port, timeout=5)
    try:
        data = b"x" * (MAX_BODY_BYTES + 2048)
        status, _h, body = post_on(
            conn, "/sources/calendar-bridge/upload", headers, data)
        assert status == 400
        assert b"larger than 1 MB" in body
        conn.request("GET", "/health", headers=headers)
        response = conn.getresponse()
        assert response.status == 200
        response.read()
    finally:
        conn.close()


def test_beyond_the_cap_the_answer_closes_the_connection(booted):
    headers = booted.exchange()
    request = (
        "POST /research HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{booted.port}\r\n"
        f"Cookie: {headers['Cookie']}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {MAX_DRAIN_BYTES + 1}\r\n"
        "\r\n"
    ).encode("utf-8") + b"partial"
    with socket.create_connection(("127.0.0.1", booted.port), timeout=5) as sock:
        sock.sendall(request)
        # Read exactly one full answer (headers plus the Content-Length
        # body), never relying on how the close reaches us: FIN or RST.
        reply = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                reply += chunk
                head, sep, body = reply.partition(b"\r\n\r\n")
                if sep:
                    length = next(
                        int(line.split(b":", 1)[1])
                        for line in head.split(b"\r\n")
                        if line.lower().startswith(b"content-length:"))
                    if len(body) >= length:
                        break  # the whole answer is captured
        except ConnectionResetError:
            pass  # Windows may reset once everything has arrived
    head, _, _body = reply.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 400")
    assert b"connection: close" in head.lower()
