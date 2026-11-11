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
from agentdesk.plugins.runtime import PluginError
from agentdesk.server import pages
from agentdesk.server.auth import SessionStore, session_id_from_cookie
from agentdesk.server.core import (
    ATTENTION,
    FRESH,
    PREFERRED_PORT,
    Freshness,
    SourceStatus,
    default_sources,
)
from agentdesk.server.demo import Widget, demo_widgets
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
        plugins: "PluginRuntime | None" = None,
    ) -> None:
        self.sessions = sessions
        self.sources = sources if sources is not None else default_sources()
        self.plugins = plugins
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
        elif path == "/api/plugins":
            self._send_json(200, {"plugins": self.server_plugins_widget_records()})
        elif path.startswith("/api/plugins/"):
            plugin_id = path[len("/api/plugins/"):]
            self._send_json(200, self._plugin_record_or_404(plugin_id))
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

    def do_POST(self) -> None:  # noqa: N802 (http.server contract)
        path, _, _query = self.path.partition("?")
        verdict = check_request(
            self.headers.get("Host"),
            self.headers.get("Origin"),
            self.server.port,  # type: ignore[attr-defined]
        )
        if not verdict.allowed:
            self._send_error_page(403, "Blocked", "This request did not come from the dashboard's own address.")
            return
        if not self._authenticated():
            self._send_error_page(
                401, "Session required",
                "Open Agent Desk from its shortcut to get a fresh link.",
            )
            return
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            self._send_json(404, {"error": "plugins:unavailable",
                                  "message": "no plugin runtime is configured"})
            return
        if not path.startswith("/api/plugins"):
            self._send_json(404, {"error": "not-found", "message": path})
            return
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json(400, {"error": "bad-json", "message": str(exc)})
            return
        try:
            self._dispatch_plugin_post(plugins, path, body)
        except PluginError as exc:
            self._send_json(exc.status, {"error": exc.code, "message": str(exc)})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        document = json.loads(raw.decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError("body must be a JSON object")
        return document

    def _dispatch_plugin_post(self, plugins: PluginRuntime, path: str, body: dict) -> None:
        parts = [p for p in path.split("/") if p]  # ["api", "plugins", ...]
        if path == "/api/plugins/install":
            self._send_json(200, plugins.install(
                body["zip_path"], source=body.get("source", "zip")))
            return
        if len(parts) < 3:
            self._send_json(404, {"error": "not-found", "message": path})
            return
        plugin_id = parts[2]
        action = parts[3] if len(parts) > 3 else ""
        if action == "update":
            self._send_json(200, plugins.update(plugin_id, body["zip_path"]))
        elif action == "consent":
            self._send_json(200, plugins.consent(plugin_id))
        elif action == "rollback":
            self._send_json(200, plugins.rollback(plugin_id))
        elif action == "enable":
            self._send_json(200, plugins.enable(plugin_id))
        elif action == "disable":
            self._send_json(200, plugins.disable(plugin_id))
        elif action == "uninstall":
            self._send_json(200, plugins.uninstall(plugin_id))
        elif action == "retest":
            self._send_json(200, plugins.retest(plugin_id))
        elif action == "purge-data":
            self._send_json(200, plugins.purge_data(
                plugin_id, body.get("confirmation")))
        else:
            self._send_json(404, {"error": "not-found", "message": path})

    def _send_json(self, status: int, payload: dict) -> None:
        self._send_bytes(status, json.dumps(payload, indent=2).encode("utf-8"),
                         "application/json; charset=utf-8")

    def _send_dashboard(self) -> None:
        now = datetime.now()
        date_line = now.strftime("%A, %d %B, %H:%M. ")
        widgets = list(demo_widgets())
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if plugins is not None:
            widgets += [self._plugin_widget(card) for card in plugins.widget_cards()]
        page = pages.render_dashboard(
            widgets,
            agentdesk.__version__,
            _greeting(now),
            date_line,
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _plugin_widget(self, card: dict) -> Widget:
        """One installed plugin's dashboard card: pilot badge, amber state.

        The amber treatment matches the built-in widgets: the amber class
        for the surface, an alert block carrying the cause, and the
        Re-test affordance in the stamp."""
        status = FRESH if card.get("freshness") == "fresh" else ATTENTION
        cause = card.get("cause") or "data source has not run"
        if status == FRESH:
            cause = f"reading {card.get('file') or 'the data source'}"
            body = f'<p class="w-big">{card["version"]}</p><p class="w-note">{cause}</p>'
            extra = ""
        else:
            body = (
                f'<div class="alert" id="plugin-amber-{card["id"]}">'
                f"<p>{cause}</p>"
                "<p>Re-test runs the plugin's data source again; the nightly "
                "probe does the same for every plugin.</p></div>"
            )
            extra = "amber"
        freshness = Freshness(
            status=status,
            stamp="Re-test available" if status == ATTENTION else "live",
            updated_iso=str(card.get("checked_at", "")),
        )
        return Widget(
            id=f"plugin-{card['id']}",
            title=card["title"],
            col="col-4",
            freshness=freshness,
            body_html=body,
            foot_html=f"plugin v{card['version']}",
            extra_classes=extra,
            badge="PILOT" if card.get("pilot") else "",
        )

    def _plugin_record_or_404(self, plugin_id: str) -> dict:
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            return {"error": "plugins:unavailable"}
        try:
            record = plugins.record(plugin_id)
        except PluginError as exc:
            return {"error": exc.code, "message": str(exc)}
        if record.get("pending_update"):
            record["pending_diff"] = {
                "version": record["pending_update"]["version"],
                "added_scopes": record["pending_update"]["added_scopes"],
            }
        return record

    def server_plugins_widget_records(self) -> list[dict]:
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            return []
        out = []
        for record in plugins.list_records():
            record = dict(record)
            if record.get("pending_update"):
                record["pending_diff"] = {
                    "version": record["pending_update"]["version"],
                    "added_scopes": record["pending_update"]["added_scopes"],
                }
            out.append({
                "id": record["id"],
                "name": record.get("name", record["id"]),
                "state": record["state"],
                "active_version": record.get("active_version"),
                "pilot": record.get("pilot_views_left", 0) > 0
                and record.get("state") == "enabled",
                "data_source": record.get("data_source"),
                "pending_diff": record.get("pending_diff"),
            })
        return out

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
    plugins: "PluginRuntime | None" = None,
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
            return AgentDeskServer((resolved, PREFERRED_PORT), sessions, sources,
                                   plugins)
        except OSError:
            return AgentDeskServer((resolved, 0), sessions, sources, plugins)
    return AgentDeskServer((resolved, port), sessions, sources, plugins)


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
