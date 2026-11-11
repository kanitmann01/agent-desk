"""Shared harness for server tests: boot the real thing on a real port.

The HTTP API is the primary seam, so these tests drive the actual server
over actual sockets: no fakes between the test and the wire. Everything a
test asserts lives on the Booted object; close() must be called (use the
booted fixture) so no listener outlives a test.
"""

import http.client
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.server import app as server_app


class Booted:
    """A running AgentDeskServer plus small helpers for raw requests."""

    def __init__(self) -> None:
        self.server = server_app.create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.port

    def host_header(self) -> dict[str, str]:
        return {"Host": f"127.0.0.1:{self.port}"}

    def request(self, method: str, path: str, headers: dict[str, str] | None = None):
        """One real HTTP request; returns (status, headers, body)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def exchange(self) -> dict[str, str]:
        """Walk the bootstrap exchange; returns headers for authed requests."""
        status, headers, _ = self.request("GET", f"/auth/{self.token()}", self.host_header())
        assert status == 303, f"expected 303 from auth exchange, got {status}"
        cookie = headers["Set-Cookie"].split(";")[0]
        return {"Cookie": cookie, "Host": f"127.0.0.1:{self.port}"}

    def token(self) -> str:
        return self.server.sessions.bootstrap_token()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
