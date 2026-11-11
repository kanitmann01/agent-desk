"""The hardened localhost HTTP server for the dashboard.

One threading server, loopback only, every request passing the same gate:
Origin/Host validation, then session auth, then routing. GETs serve the
shell, health and static assets; POSTs drive state changes (workbook
picker, registration, re-test). There is no second entry path; the
WebSocket upgrades of later tickets must call the same check_request and
session validation before handshake.
"""

import json
import logging
import os
import sqlite3
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import agentdesk
from agentdesk.calendar.watcher import CalendarBridge, default_read_calendar
from agentdesk.excel import store as excel_store
from agentdesk.excel.watcher import ExcelWatch, default_adapters
from agentdesk.server import pages
from agentdesk.server.auth import SessionStore, session_id_from_cookie
from agentdesk.server.commitments import render_commitments_widget
from agentdesk.server.core import (
    PREFERRED_PORT,
    SourceStatus,
    default_sources,
)
from agentdesk.server.demo import demo_widgets
from agentdesk.server.guard import check_request
from agentdesk.server.health import health_payload
from agentdesk.server.sales import render_sales_widget

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

MAX_BODY_BYTES = 1024 * 1024


def _greeting(now: datetime) -> str:
    if now.hour < 12:
        return "Good morning"
    if now.hour < 18:
        return "Good afternoon"
    return "Good evening"


def default_data_dir() -> Path:
    """Where the watch keeps its snapshots. Provisional for v1: a folder
    in the user profile, gone with delete-folder uninstall."""
    return Path(Path.home(), ".agent-desk")


def tk_pick_workbook() -> str | None:
    """The native file dialog, one fresh Tk root per call.

    Runs in the calling (worker) thread with its own root, which Windows
    tolerates for a one-shot dialog. Any failure answers None: the UI
    treats it as cancelled rather than breaking the flow.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            chosen = filedialog.askopenfilename(
                title="Choose the sales workbook",
                filetypes=[("Excel workbooks", "*.xlsx"), ("All files", "*.*")],
            )
        finally:
            root.destroy()
        return chosen or None
    except Exception:  # noqa: BLE001 - a broken dialog must not break the app
        LOG.exception("workbook picker failed")
        return None


class AgentDeskServer(ThreadingHTTPServer):
    """The app server: sessions, source table, and the excel watch."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        sessions: SessionStore,
        sources: list[SourceStatus] | None = None,
        excel: ExcelWatch | None = None,
        pick_workbook=None,
        calendar: CalendarBridge | None = None,
    ) -> None:
        self.sessions = sessions
        self.sources = sources if sources is not None else default_sources()
        self.excel = excel
        self.pick_workbook = pick_workbook
        self.calendar = calendar
        self.started_monotonic = time.monotonic()
        super().__init__(address, DashboardHandler)

    @property
    def port(self) -> int:
        return self.server_address[1]


class DashboardHandler(BaseHTTPRequestHandler):
    """GET for the shell, health and statics; POST for state changes."""

    protocol_version = "HTTP/1.1"
    server_version = f"AgentDesk/{agentdesk.__version__}"
    sys_version = ""  # never advertise the interpreter behind the app

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        LOG.debug("http %s", format % args)

    # -- entry points: no exception may drop a connection silently -------

    def do_GET(self) -> None:  # noqa: N802 (http.server contract)
        self._responded = False
        try:
            self._route_get()
        except Exception:  # noqa: BLE001 - the UI is the log, not a traceback
            LOG.exception("GET failed")
            self._fail_safe(500, "Something broke", "The dashboard hit an error handling that. Nothing was changed.")

    def do_POST(self) -> None:  # noqa: N802 (http.server contract)
        self._responded = False
        try:
            self._route_post()
        except Exception:  # noqa: BLE001
            LOG.exception("POST failed")
            self._fail_safe(500, "Something broke", "That action did not go through. Try again; if it repeats, restart the app.")

    def _fail_safe(self, status: int, title: str, message: str) -> None:
        if not self._responded:
            self._send_error_page(status, title, message)

    # -- the gate every request passes ----------------------------------

    def _gate(self) -> bool:
        """Origin/Host guard, then session auth. Sends the answer itself."""
        verdict = check_request(
            self.headers.get("Host"),
            self.headers.get("Origin"),
            self.server.port,  # type: ignore[attr-defined]
        )
        if not verdict.allowed:
            self._send_error_page(403, "Blocked", "This request did not come from the dashboard's own address.")
            return False
        if not self._authenticated():
            self._send_error_page(
                401, "Session required",
                "Open Agent Desk from its shortcut to get a fresh link.",
            )
            return False
        return True

    # -- GET -------------------------------------------------------------

    def _route_get(self) -> None:
        path, _, _query = self.path.partition("?")
        if path.startswith("/auth/"):
            # The one route a session does not exist for yet: guard runs,
            # auth does not.
            verdict = check_request(
                self.headers.get("Host"),
                self.headers.get("Origin"),
                self.server.port,  # type: ignore[attr-defined]
            )
            if not verdict.allowed:
                self._send_error_page(403, "Blocked", "This request did not come from the dashboard's own address.")
                return
            self._handle_auth(path[len("/auth/"):])
            return
        if not self._gate():
            return
        if path == "/":
            self._send_dashboard()
        elif path == "/health":
            self._send_health()
        elif path == "/widgets/sales-24h":
            self._send_sales_status()
        elif path == "/widgets/commitments":
            self._send_commitments_status()
        elif path == "/walkthrough/calendar":
            self._send_bytes(
                200,
                pages.render_walkthrough(str(default_calendar_hint())).encode("utf-8"),
                "text/html; charset=utf-8",
            )
        elif path == "/static/app.css":
            self._send_bytes(200, pages.STYLES.encode("utf-8"), "text/css; charset=utf-8")
        elif path == "/static/app.js":
            self._send_bytes(200, pages.APP_JS.encode("utf-8"), "text/javascript; charset=utf-8")
        else:
            self._send_error_page(404, "Nothing here", "No page lives at this address.")

    # -- POST ------------------------------------------------------------

    def _route_post(self) -> None:
        if not self._gate():
            return
        path, _, _query = self.path.partition("?")
        excel = self.server.excel  # type: ignore[attr-defined]
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if path == "/sources/excel-watch/pick":
            if excel is None:
                self._send_json(503, {"error": "the excel watch is not available"})
                return
            self._send_json(200, {"path": self.server.pick_workbook()})  # type: ignore[attr-defined]
        elif path == "/sources/excel-watch":
            if excel is None:
                self._send_json(503, {"error": "the excel watch is not available"})
                return
            body = self._read_json_body()
            if body is None or not isinstance(body.get("path"), str) or not body["path"].strip():
                self._send_json(400, {"error": "expected {\"path\": \"...\"}"})
                return
            excel.register(body["path"].strip())
            excel.start_polling()
            self._send_json(200, excel.status())
        elif path == "/sources/excel-watch/retest":
            if excel is None:
                self._send_json(503, {"error": "the excel watch is not available"})
                return
            excel.retest()
            self._send_json(200, excel.status())
        elif path == "/widgets/commitments/check":
            if calendar is None:
                self._send_json(503, {"error": "the calendar bridge is not available"})
                return
            body = self._read_json_body()
            if body is None or not isinstance(body.get("eventId"), str):
                self._send_json(400, {"error": "expected {\"eventId\": \"...\", \"idx\": n, \"checked\": bool}"})
                return
            calendar.toggle_check(
                body["eventId"], int(body.get("idx", 0)), bool(body.get("checked"))
            )
            self._send_json(200, {"ok": True})
        elif path == "/sources/calendar-bridge/retest":
            if calendar is None:
                self._send_json(503, {"error": "the calendar bridge is not available"})
                return
            calendar.retest()
            self._send_json(200, calendar.status())
        else:
            self._send_error_page(404, "Nothing here", "No action lives at this address.")

    def _read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    # -- helpers ----------------------------------------------------------

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
        demo = {w.id: w for w in demo_widgets()}
        widgets: list = []
        excel = self.server.excel  # type: ignore[attr-defined]
        sales_status = excel.status() if excel is not None else None
        if sales_status is not None and sales_status.get("configured"):
            widgets.append(render_sales_widget(sales_status))
        else:
            widgets.append(demo["sales-24h"])
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if calendar is not None:
            commitments = render_commitments_widget(calendar.status(), now)
            widgets.append(commitments if commitments is not None else demo["key-commitment"])
        else:
            widgets.append(demo["key-commitment"])
        widgets.append(demo["research"])
        widgets.append(demo["region-mix"])
        page = pages.render_dashboard(
            widgets,
            agentdesk.__version__,
            _greeting(now),
            now.strftime("%A, %d %B, %H:%M. "),
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_sales_status(self) -> None:
        excel = self.server.excel  # type: ignore[attr-defined]
        if excel is None:
            self._send_json(503, {"error": "the excel watch is not available"})
            return
        self._send_json(200, excel.status())

    def _send_commitments_status(self) -> None:
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if calendar is None:
            self._send_json(503, {"error": "the calendar bridge is not available"})
            return
        self._send_json(200, calendar.status())

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

    def _send_json(self, status: int, payload: dict) -> None:
        self._send_bytes(
            status,
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
        self._responded = True
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
    excel: ExcelWatch | None = None,
    pick_workbook=None,
    calendar: CalendarBridge | None = None,
) -> AgentDeskServer:
    """Bind the app to the loopback and nothing else.

    A non-loopback host is a hard error, not a warning: the skeleton must
    be incapable of listening on 0.0.0.0 even by misconfiguration. When no
    port is given, the preferred port is tried once and an ephemeral port
    is the fallback, so the auth URL always names the port that actually
    opened. The excel watch and the calendar bridge default to real ones
    over the user data directory; tests pass their own.
    """
    resolved = "127.0.0.1" if host == "localhost" else host
    if resolved != "127.0.0.1":
        raise ValueError(f"refusing to bind non-loopback host: {host!r}")
    sessions = SessionStore()
    if excel is None:
        excel = _default_excel_watch()
    if calendar is None:
        calendar = _default_calendar_bridge()
    if pick_workbook is None:
        pick_workbook = tk_pick_workbook
    if port is None:
        try:
            return AgentDeskServer((resolved, PREFERRED_PORT), sessions, sources, excel, pick_workbook, calendar)
        except OSError:
            return AgentDeskServer((resolved, 0), sessions, sources, excel, pick_workbook, calendar)
    return AgentDeskServer((resolved, port), sessions, sources, excel, pick_workbook, calendar)


def _default_excel_watch() -> ExcelWatch | None:
    """A real watch over the persistent store, or None when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "excel-watch.sqlite3", check_same_thread=False)
        return ExcelWatch(conn, default_adapters())
    except (OSError, sqlite3.Error):
        LOG.exception("excel watch unavailable")
        return None


def default_calendar_hint() -> Path:
    """The calendar path the walkthrough shows as 'the app watches this'."""
    env_path = os.environ.get("AGENTDESK_CALENDAR_FILE")
    if env_path:
        return Path(env_path)
    return Path(Path.home(), "OneDrive", "agent-desk", "calendar_sync.json")


def _default_calendar_bridge() -> CalendarBridge | None:
    """A real bridge over the persistent store, or None when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "calendar-bridge.sqlite3", check_same_thread=False)
        return CalendarBridge(conn)
    except (OSError, sqlite3.Error):
        LOG.exception("calendar bridge unavailable")
        return None


def auth_url(server: AgentDeskServer) -> str:
    """The URL the start command opens in the default browser."""
    return f"http://127.0.0.1:{server.port}{server.sessions.auth_path()}"


def serve(server: AgentDeskServer, open_browser: bool = True) -> None:
    """Serve until interrupted, opening the dashboard once bound."""
    import sys

    url = auth_url(server)
    if sys.stdout is not None:  # pythonw runs without a console stream
        print(f"Agent Desk is running: {url}")
    if server.calendar is not None:
        server.calendar.start_polling()  # passive file watch, keeps itself fresh
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
