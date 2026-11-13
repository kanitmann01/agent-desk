"""The peer HTTP client (ticket #67): pair, read, download.

A thin http.client wrapper for the other desk's peer surface. Every
failure is a named refusal with a cause: an unreachable desk says so
instead of hanging, a wrong code carries the server's error name, and a
malformed answer is never parsed into a success.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.peers.client import PeerClient, PeerClientError  # noqa: E402


class _StubHandler(BaseHTTPRequestHandler):
    """Records what arrived and answers from a scripted queue."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence
        pass

    def _answer(self):
        self.server.requests.append(
            {"method": self.command, "path": self.path,
             "authorization": self.headers.get("Authorization"),
             "body": self.rfile.read(int(self.headers.get("Content-Length", 0)))
             if self.command == "POST" else b""})
        status, payload = self.server.script.pop(0)
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _answer
    do_POST = _answer


@pytest.fixture()
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    server.requests = []
    server.script = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def _base(server) -> str:
    return f"127.0.0.1:{server.server_address[1]}"


def test_pair_posts_the_code_and_my_identity(stub):
    stub.script = [(200, {"ok": True, "peer_id": "desk-a", "name": "Desk A"})]
    out = PeerClient().pair(
        _base(stub), code="ABCD2345", my_peer_id="desk-b", my_name="Desk B",
        my_host="127.0.0.1", my_port=8802)
    assert out["ok"] is True
    assert out["peer_id"] == "desk-a"
    request = stub.requests[0]
    assert request["method"] == "POST"
    assert request["path"] == "/peer/pair"
    body = json.loads(request["body"])
    assert body == {"code": "ABCD2345", "peer_id": "desk-b",
                    "name": "Desk B", "host": "127.0.0.1", "port": 8802}


def test_wrong_code_carries_the_servers_named_refusal(stub):
    stub.script = [(403, {"error": "pairing:unknown-code",
                          "message": "That pairing code does not exist."})]
    with pytest.raises(PeerClientError) as excinfo:
        PeerClient().pair(_base(stub), code="ZZZZ9999", my_peer_id="b",
                          my_name="B", my_host="127.0.0.1", my_port=1)
    assert excinfo.value.code == "pairing:unknown-code"
    assert "does not exist" in str(excinfo.value)


def test_info_sends_the_bearer_token_and_parses_plugins(stub):
    stub.script = [(200, {"ok": True, "peer_id": "desk-a", "name": "Desk A",
                          "plugins": [{"id": "sales-delta-widget",
                                       "version": "1.2.0",
                                       "sha256": "ab" * 32}]})]
    out = PeerClient().info(_base(stub), token="channel-token")
    assert out["ok"] is True
    assert out["plugins"][0]["id"] == "sales-delta-widget"
    request = stub.requests[0]
    assert request["path"] == "/peer/info"
    assert request["authorization"] == "Bearer channel-token"


def test_manifest_and_bundle_fetch(stub):
    stub.script = [
        (200, {"id": "sales-delta-widget", "version": "1.2.0"}),
        (200, b"PK\x03\x04bundle-bytes"),
    ]
    client = PeerClient()
    manifest = client.manifest(_base(stub), token="t", plugin_id="sales-delta-widget")
    assert manifest["id"] == "sales-delta-widget"
    bundle = client.bundle(_base(stub), token="t", plugin_id="sales-delta-widget")
    assert bundle == b"PK\x03\x04bundle-bytes"
    paths = [r["path"] for r in stub.requests]
    assert paths == ["/peer/plugins/sales-delta-widget/manifest",
                     "/peer/plugins/sales-delta-widget/bundle"]


def test_unreachable_peer_is_a_named_refusal_with_cause():
    # a port with nothing listening on it
    import socket

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(PeerClientError) as excinfo:
        PeerClient(timeout=2).info(f"127.0.0.1:{dead_port}", token="t")
    assert excinfo.value.code == "peer:unreachable"
    assert str(excinfo.value)


def test_malformed_answer_is_never_a_success(stub):
    stub.script = [(200, b"this is not json")]
    with pytest.raises(PeerClientError) as excinfo:
        PeerClient().info(_base(stub), token="t")
    assert excinfo.value.code == "peer:bad-response"


def test_bad_token_is_the_servers_named_refusal(stub):
    stub.script = [(403, {"error": "peer:token-required",
                          "message": "A paired peer token is required."})]
    with pytest.raises(PeerClientError) as excinfo:
        PeerClient().info(_base(stub), token="")
    assert excinfo.value.code == "peer:token-required"


def test_extract_bundle_round_trips_files(tmp_path):
    import io
    import zipfile

    from agentdesk.peers.client import extract_bundle

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("nested/widget.ui.json", "{}")
    target = tmp_path / "staged"
    target.mkdir()
    extract_bundle(buffer.getvalue(), target)
    assert (target / "manifest.json").read_text(encoding="utf-8") == "{}"
    assert (target / "nested" / "widget.ui.json").is_file()


def test_extract_bundle_refuses_entries_that_escape(tmp_path):
    import io
    import zipfile

    from agentdesk.peers.client import extract_bundle

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.txt", "no")
    target = tmp_path / "staged"
    target.mkdir()
    with pytest.raises(PeerClientError) as excinfo:
        extract_bundle(buffer.getvalue(), target)
    assert excinfo.value.code == "peer:bad-bundle"
    assert not (tmp_path / "escape.txt").exists()
