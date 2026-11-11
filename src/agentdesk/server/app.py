"""The hardened localhost HTTP server for the walking skeleton.

One threading server, loopback only, every request passing the same gate:
Origin/Host validation, then session auth, then routing. There is no
second entry path; the WebSocket upgrades of later tickets must call the
same check_request and session validation before handshake.
"""

import json
import logging
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agentdesk
from agentdesk.server import pages
from agentdesk.server.auth import SessionStore, session_id_from_cookie
from agentdesk.server.core import (
    PREFERRED_PORT,
    SourceStatus,
    default_sources,
)
from agentdesk.server.demo import demo_widgets
from agentdesk.server.guard import check_request
from agentdesk.server.health import health_payload

LOG = logging.getLogger("agentdesk.server")

# Strict CSP: everything self-hosted, nothing inline. This is a product
# commitment from the first commit, not decoration: plugins will never be
# allowed to loosen it.
SECURITY_HEADERS = (
    ("Content-Security-Policy",
     "default-src 'none'; style-src 'self'; script-src 'self'; "
     "img-src 'self' data:; connect-src 'self'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)


def _greeting(now: datetime) -> str:
    if now.hour < 12:
        return "Good morning"
    if now.hour < 18:
        return "Good afternoon"
    return "Good evening"


class AgentDeskServer(ThreadingHTTPServer):
    """The app server: carries the session store and the source table."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        sessions: SessionStore,
        sources: list[SourceStatus] | None = None,
    ) -> None:
        self.sessions = sessions
        self.sources = sources if sources is not None else default_sources()
        self.started_monotonic = time.monotonic()
        super().__init__(address, DashboardHandler)

    @property
    def port(self) -> int:
        return self.server_address[1]


class DashboardHandler(BaseHTTPRequestHandler):
    """GET-only routing for the skeleton: auth, dashboard, health, static."""

    protocol_version = "HTTP/1.1"
    server_version = f"AgentDesk/{agentdesk.__version__}"
    sys_version = ""  # never advertise the interpreter behind the app

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        LOG.debug("http %s", format % args)

    def do_GET(self) -> None:  # noqa: N802 (http.server contract)
        path, _, _query = self.path.partition("?")
        verdict = check_request(
            self.headers.get("Host"),
            self.headers.get("Origin"),
            self.server.port,  # type: ignore[attr-defined]
        )
        if not verdict.allowed:
            self._send_error_page(403, "Blocked", "This request did not come from the dashboard's own address.")
            return
        if path.startswith("/auth/"):
            self._handle_auth(path[len("/auth/"):])
            return
        if not self._authenticated():
            self._send_error_page(
                401, "Session required",
                "Open Agent Desk from its shortcut to get a fresh link.",
            )
            return
        if path == "/":
            self._send_dashboard()
        elif path == "/health":
            self._send_health()
        elif path == "/static/app.css":
            self._send_bytes(200, pages.STYLES.encode("utf-8"), "text/css; charset=utf-8")
        elif path == "/static/app.js":
            self._send_bytes(200, pages.APP_JS.encode("utf-8"), "text/javascript; charset=utf-8")
        else:
            self._send_error_page(404, "Nothing here", "No page lives at this address.")

    def _authenticated(self) -> bool:
        store: SessionStore = self.server.sessions  # type: ignore[attr-defined]
        return store.validate(session_id_from_cookie(self.headers.get("Cookie")))

    def _handle_auth(self, token: str) -> None:
        store: SessionStore = self.server.sessions  # type: ignore[attr-defined]
        sid = store.exchange(token)
        if sid is None:
            self._send_error_page(403, "Blocked", "That start link is not valid for this session.")
            return
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", store.cookie_header(sid))
        self._common_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_dashboard(self) -> None:
        now = datetime.now()
        date_line = now.strftime("%A, %d %B, %H:%M. ")
        page = pages.render_dashboard(
            demo_widgets(),
            agentdesk.__version__,
            _greeting(now),
            date_line,
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_health(self) -> None:
        payload = health_payload(
            agentdesk.__version__,
            self.server.sources,  # type: ignore[attr-defined]
            self.server.started_monotonic,  # type: ignore[attr-defined]
        )
        self._send_bytes(
            200,
            json.dumps(payload, indent=2).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send_error_page(self, status: int, title: str, message: str) -> None:
        self._send_bytes(
            status,
            pages.render_error_page(title, message).encode("utf-8"),
            "text/html; charset=utf-8",
        )

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self._common_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _common_headers(self) -> None:
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)


def create_server(
    host: str = "127.0.0.1",
    port: int | None = None,
    sources: list[SourceStatus] | None = None,
) -> AgentDeskServer:
    """Bind the app to the loopback and nothing else.

    A non-loopback host is a hard error, not a warning: the skeleton must
    be incapable of listening on 0.0.0.0 even by misconfiguration. When no
    port is given, the preferred port is tried once and an ephemeral port
    is the fallback, so the auth URL always names the port that actually
    opened.
    """
    resolved = "127.0.0.1" if host == "localhost" else host
    if resolved != "127.0.0.1":
        raise ValueError(f"refusing to bind non-loopback host: {host!r}")
    sessions = SessionStore()
    if port is None:
        try:
            return AgentDeskServer((resolved, PREFERRED_PORT), sessions, sources)
        except OSError:
            return AgentDeskServer((resolved, 0), sessions, sources)
    return AgentDeskServer((resolved, port), sessions, sources)


def auth_url(server: AgentDeskServer) -> str:
    """The URL the start command opens in the default browser."""
    return f"http://127.0.0.1:{server.port}{server.sessions.auth_path()}"


def serve(server: AgentDeskServer, open_browser: bool = True) -> None:
    """Serve until interrupted, opening the dashboard once bound."""
    import sys

    url = auth_url(server)
    if sys.stdout is not None:  # pythonw runs without a console stream
        print(f"Agent Desk is running: {url}")
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
