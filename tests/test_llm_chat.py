"""The endpoint adapter's failure vocabulary (ticket #62).

Every cause the surfaces show is born here: a real loopback server
answers each failure shape (a redirect, a login page, a 401, a wrong
JSON body) over a real socket, so the classification is tested against
what urllib actually raises, and the transport causes that cannot be
produced hermetically (DNS, TLS) are tested against the classifier
directly. No redirect is ever followed: a 3xx is an answer to report,
not a hop to chase.
"""

import json
import socket
import ssl
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

from agentdesk.llm import LlmUnavailable, auth_headers, chat, transport_cause, uses_azure_api_key


class GarbageEndpoint:
    """One raw socket that answers bytes which are not HTTP (TLS
    handshake bytes): the shape a https base pointed at a plain http
    listener, or a broken middlebox, produces. http.client raises
    BadStatusLine, which is the invariant to classify, not crash on."""

    PAYLOAD = b"\x16\x03\x01\x00\x0a\x01\x00\x00\x06\x00\x00"

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.base_url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _addr = self.sock.accept()
        try:
            conn.recv(1024)
            conn.sendall(self.PAYLOAD)
        finally:
            conn.close()

    def close(self):
        self.sock.close()


class ScriptedEndpoint:
    """A minimal loopback endpoint scripted per test: one status,
    content type, body and header set for every request, recorded.
    http.server only, the same shape as the research stub, so every
    failure shape is answered by a real socket."""

    def __init__(self, status=200, content_type="application/json",
                 body=b"{}", extra_headers=None, delay=0.0) -> None:
        outer = self
        self.requests: list[dict] = []
        self.status = status
        self.content_type = content_type
        self.body = body
        self.extra_headers = extra_headers or {}
        self.delay = delay

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                outer.requests.append(
                    {"path": self.path, "body": self.rfile.read(length)}
                )
                if outer.delay:
                    time.sleep(outer.delay)
                self.send_response(outer.status)
                self.send_header("Content-Type", outer.content_type)
                self.send_header("Content-Length", str(len(outer.body)))
                for name, value in outer.extra_headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def chat_answer(base: str, **kwargs) -> str:
    """chat() or the raised cause, so each case is one assert pair."""
    try:
        return chat(base, "test-key", "test-model", "ping", **kwargs)
    except LlmUnavailable as exc:
        return str(exc)


def chat_cause(base: str, **kwargs) -> str:
    with pytest.raises(LlmUnavailable) as raised:
        chat(base, "test-key", "test-model", "ping", **kwargs)
    return str(raised.value)


def valid_body(content: str = "pong") -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def test_a_valid_answer_returns_the_message_content():
    stub = ScriptedEndpoint(body=valid_body("pong"))
    try:
        assert chat(stub.base_url, "k", "m", "ping") == "pong"
        assert stub.requests[0]["path"] == "/chat/completions"
    finally:
        stub.close()


def test_a_redirect_is_never_followed_and_is_named_as_a_login_page():
    stub = ScriptedEndpoint(status=302, body=b"",
                            extra_headers={"Location": "/sso/login"})
    try:
        cause = chat_cause(stub.base_url)
        assert "redirect" in cause
        assert "not an API" in cause
        # One request only: the redirect was reported, not chased.
        assert len(stub.requests) == 1
    finally:
        stub.close()


def test_an_html_login_page_is_named_as_a_web_page():
    stub = ScriptedEndpoint(content_type="text/html",
                            body=b"<html><body>Sign in to continue</body></html>")
    try:
        cause = chat_cause(stub.base_url)
        assert "web page" in cause
        assert "portal" in cause
    finally:
        stub.close()


def test_an_html_body_is_detected_even_when_the_content_type_lies():
    stub = ScriptedEndpoint(content_type="application/json",
                            body=b"<html>Sign in</html>")
    try:
        assert "web page" in chat_cause(stub.base_url)
    finally:
        stub.close()


def test_a_401_or_403_means_the_key_was_rejected():
    for code in (401, 403):
        stub = ScriptedEndpoint(status=code, body=b'{"error": "bad key"}')
        try:
            cause = chat_cause(stub.base_url)
            assert "rejected the API key" in cause
            assert str(code) in cause
        finally:
            stub.close()


def test_a_404_means_the_path_is_not_an_api_base():
    stub = ScriptedEndpoint(status=404, body=b"not found")
    try:
        cause = chat_cause(stub.base_url)
        assert "404" in cause
        assert "API base" in cause
    finally:
        stub.close()


def test_a_5xx_is_named_as_the_endpoint_side():
    stub = ScriptedEndpoint(status=503, body=b"")
    try:
        cause = chat_cause(stub.base_url)
        assert "503" in cause
        assert "endpoint" in cause
    finally:
        stub.close()


def test_a_200_with_the_wrong_json_shape_is_named():
    stub = ScriptedEndpoint(body=b'{"ok": true}')
    try:
        cause = chat_cause(stub.base_url)
        assert "not an OpenAI chat reply" in cause
        assert "/v1" in cause
    finally:
        stub.close()


def test_a_refused_connection_names_the_address():
    # A closed port on the loopback: nothing is listening there.
    assert "refused" in chat_cause("http://127.0.0.1:9/v1")


def test_a_silent_endpoint_is_a_timeout():
    stub = ScriptedEndpoint(delay=1.5, body=valid_body())
    try:
        cause = chat_cause(stub.base_url, timeout=0.25)
        assert "did not answer within" in cause
        assert "0.25" in cause
    finally:
        stub.close()


def test_a_base_without_a_scheme_or_host_is_refused_before_any_call():
    assert "must start with http" in chat_cause("llm.corp.example/v1")
    assert "missing its host" in chat_cause("https://")
    assert "must start with http" in chat_cause("ftp://llm.corp.example/v1")


def test_no_base_is_still_the_documented_unconfigured_cause():
    assert "no corporate endpoint configured" in chat_cause("")


def test_dns_failure_names_the_host(monkeypatch):
    def no_such_host(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", no_such_host)
    cause = chat_cause("http://llm.nowhere.example/v1")
    assert "could not resolve" in cause
    assert "llm.nowhere.example" in cause


def test_transport_causes_for_failures_a_stub_cannot_produce():
    dns = transport_cause(socket.gaierror("no address"), host="llm.x.example")
    assert "could not resolve" in dns and "llm.x.example" in dns
    tls = transport_cause(ssl.SSLError("certificate verify failed"))
    assert "secure connection" in tls and "TLS" in tls
    timed_out = transport_cause(socket.timeout(), host="llm.x.example", timeout=10)
    assert "did not answer within" in timed_out and "10" in timed_out
    unknown = transport_cause(OSError("strange"), host="h")
    assert "endpoint" in unknown and "strange" in unknown


def test_a_malformed_ipv6_literal_is_refused_not_crashed():
    # A bracket that never closes used to raise ValueError out of
    # urlsplit and escape as a 500; it is a named refusal instead.
    assert "must start with http" in chat_cause("https://[::1/v1")


def test_a_non_http_answer_is_classified_not_crashed():
    """A TLS answer on an http base makes http.client raise
    BadStatusLine; every failure stays an LlmUnavailable with a cause
    (the pinned invariant the surfaces rely on)."""
    stub = GarbageEndpoint()
    try:
        cause = chat_cause(stub.base_url)
        assert "endpoint" in cause
        assert "did not answer" in cause
    finally:
        stub.close()


def test_causes_never_echo_url_credentials():
    # user:pass@ riding in the base URL must not leak into causes. The
    # failure class is whatever the resolver says; the pinned part is
    # that the host is named without the credentials.
    cause = chat_cause("http://user:secret@127.0.0.1:9/v1")
    assert "127.0.0.1:9" in cause
    assert "secret" not in cause
    assert "user" not in cause


def test_uses_azure_api_key_matches_foundry_and_azure_hosts():
    assert uses_azure_api_key("https://my-resource.openai.azure.com/openai/v1")
    assert uses_azure_api_key("https://my-resource.services.ai.azure.com/openai/v1")
    assert uses_azure_api_key("https://my-resource.cognitiveservices.azure.com/openai/v1")
    assert uses_azure_api_key("https://my-gateway.azure-api.net/openai/v1")
    assert uses_azure_api_key("https://openai.azure.com/openai/v1")  # apex
    assert uses_azure_api_key("https://MY-RESOURCE.OPENAI.AZURE.COM/openai/v1")  # case
    assert uses_azure_api_key("https://my-resource.openai.azure.com:443/openai/v1")  # port


def test_uses_azure_api_key_rejects_non_azure_and_empty():
    assert not uses_azure_api_key("https://api.openai.com/v1")
    assert not uses_azure_api_key("https://llm.corp.example/v1")
    assert not uses_azure_api_key("https://api.anthropic.com/v1")
    assert not uses_azure_api_key("")
    assert not uses_azure_api_key("not-a-url")


def test_auth_headers_send_api_key_for_azure_and_bearer_otherwise():
    azure = auth_headers("https://x.openai.azure.com/openai/v1", "secret")
    assert azure["Content-Type"] == "application/json"
    assert azure["api-key"] == "secret"
    assert "Authorization" not in azure

    other = auth_headers("https://api.openai.com/v1", "secret")
    assert other["Content-Type"] == "application/json"
    assert other["Authorization"] == "Bearer secret"
    assert "api-key" not in other
