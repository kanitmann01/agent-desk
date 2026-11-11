"""The hardened localhost HTTP server for the dashboard.

One threading server, loopback only, every request passing the same gate:
Origin/Host validation, then session auth, then routing. GETs serve the
shell, health and static assets; POSTs drive state changes (workbook
picker, registration, re-test). There is no second entry path; the
WebSocket upgrades of later tickets must call the same check_request and
session validation before handshake.
"""

import html
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import agentdesk
from agentdesk.assistant import audit as audit_store
from agentdesk.briefs import generate_briefs
from agentdesk.assistant import threadlog
from agentdesk.assistant.context import build_context
from agentdesk.assistant.loop import assistant_reply, research
from agentdesk.calendar import store as calendar_store
from agentdesk.calendar.core import (
    CalendarUnreadable,
    parse_calendar_document,
)
from agentdesk.calendar.watcher import (
    STATE_EMPTY,
    CalendarBridge,
    default_calendar_candidates,
    default_read_calendar,
)
from agentdesk.excel.watcher import ExcelWatch, default_adapters
from agentdesk.inbox import service as inbox_service
from agentdesk.inbox.core import UnknownCard
from agentdesk.inbox.store import InboxStore
from agentdesk.llm import (
    DEFAULT_MODEL,
    LlmUnavailable,
    REQUEST_TIMEOUT_S,
    chat,
    chat_client,
    effective_llm_config,
    env_chat,
    env_config,
    settings_chat,
)
from agentdesk.plugins.runtime import PluginError, PluginRuntime
from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.service import Consolidator
from agentdesk.repetition.skills import SkillError, SkillStore
from agentdesk.server import pages
from agentdesk.server.auth import SessionStore, session_id_from_cookie
from agentdesk.server.commitments import (
    render_commitments_unavailable,
    render_commitments_widget,
)
from agentdesk.server.inbox_view import render_inbox_page
from agentdesk.server.research import render_assistant_page, render_research_widget
from agentdesk.server.settings_view import mask_llm_key, render_settings_page
from agentdesk.server.wizard_view import (
    approval_summary,
    preview_lines,
    render_wizard_page,
)
from agentdesk.wizard.core import WizardCompiler, WizardError, WizardStore
from agentdesk.server.touches import render_touches
from agentdesk.server.core import (
    ATTENTION,
    FRESH,
    PREFERRED_PORT,
    SRC_CALENDAR,
    SRC_EXCEL,
    SRC_RESEARCH,
    SOURCE_IDS,
    STATUS_CONNECTED,
    STATUS_NOT_CONNECTED,
    Freshness,
    SourceStatus,
)
from agentdesk.server.demo import Widget
from agentdesk.server.guard import check_request
from agentdesk.server.health import health_payload
from agentdesk.server.sales import (
    render_sales_disabled,
    render_sales_unconfigured,
    render_sales_widget,
)
from agentdesk.settings import SettingsStore, ensure_schema as ensure_settings_schema

LOG = logging.getLogger("agentdesk.server")

# Strict CSP: everything self-hosted, no inline script. This is a product
# commitment from the first commit, not decoration: plugins will never be
# allowed to loosen it. One measured exception: style-src also allows
# 'unsafe-inline' because the SPA's animation library (motion, the
# framer-motion package) animates by writing style ATTRIBUTES on
# elements, which 'unsafe-inline' in style-src governs. Style attributes
# cannot execute code; scripts still can, so script-src stays 'self' and
# no inline <script> block ships anywhere: the SPA loads only its own
# hashed bundles from /static/spa/. The server-rendered pages are
# unaffected (they never used inline styles either).
# font-src is 'self' for the same reason scripts and styles are: the
# SPA's two typefaces (Inter and Space Grotesk, SIL OFL 1.1) are .woff2
# files inside the committed bundle, served from /static/spa/assets/.
# Without the directive, font loads fall back to default-src 'none' and
# the bundled fonts are blocked. Self only: no font host, no data: URLs,
# so the page still fetches nothing from another origin.
SECURITY_HEADERS = (
    ("Content-Security-Policy",
     "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
     "font-src 'self'; img-src 'self' data:; connect-src 'self'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)

MAX_BODY_BYTES = 1024 * 1024

# The committed SPA build, emitted by frontend/ (npm run build) directly
# into this folder and committed, so the double-click launcher serves it
# with zero node involvement. When index.html is missing (a source
# checkout without a build), "/" falls back to the server-rendered
# dashboard; tests re-point this path to simulate either case.
SPA_DIR = Path(__file__).resolve().parent / "static" / "spa"

_SPA_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def spa_index_path() -> Path:
    """The SPA shell, read through the module global so tests can re-point it."""
    return SPA_DIR / "index.html"


def _greeting(now: datetime) -> str:
    if now.hour < 12:
        return "Good morning"
    if now.hour < 18:
        return "Good afternoon"
    return "Good evening"


def _local_now() -> datetime:
    return datetime.now().astimezone()


def default_data_dir() -> Path:
    """Where the watch keeps its snapshots. Provisional for v1: a folder
    in the user profile, gone with delete-folder uninstall. AGENTDESK_DATA
    moves it, and the what-this-touches page states the same place."""
    override = os.environ.get("AGENTDESK_DATA")
    if override:
        return Path(override)
    return Path(Path.home(), ".agent-desk")


# The file dialogs run in a child interpreter, not in this process.
# Tk must own the main thread on macOS, and the server's request threads
# are workers; a fresh process sidesteps the threading rules on both
# platforms. The child prints the chosen path, or an empty line when the
# dialog is cancelled or Tk is unusable, so the parent only parses stdout.
# The dialog is parented to the hidden root and the root is lifted and
# focused first: on Windows a parentless dialog can open invisibly
# behind the browser, which reads to the user as "the button is broken".
_PICKER_SNIPPET_TEMPLATE = """\
import sys

try:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # keep the dialog in front on Windows
    root.lift()                        # out from behind the browser window
    root.focus_force()
    chosen = filedialog.askopenfilename(
        parent=root,
        title={title!r},
        filetypes={filetypes!r},
    )
    root.destroy()
except Exception:
    chosen = ""
print(chosen)
"""

WORKBOOK_PICK_SNIPPET = _PICKER_SNIPPET_TEMPLATE.format(
    title="Choose the sales workbook",
    filetypes=[
        ("Excel workbooks", "*.xlsx *.xlsm *.xlsb"),
        ("All files", "*.*"),
    ],
)

CALENDAR_PICK_SNIPPET = _PICKER_SNIPPET_TEMPLATE.format(
    title="Choose the calendar file",
    filetypes=[
        ("Calendar JSON", "*.json"),
        ("All files", "*.*"),
    ],
)


def _tk_pick_file(snippet: str) -> str | None:
    """One child process per dialog call; the parent never imports Tk.

    Any failure, including a cancelled dialog (empty output), answers
    None: the UI treats it as cancelled rather than breaking the flow.
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:  # noqa: BLE001 - a broken dialog must not break the app
        LOG.exception("file picker failed")
        return None
    chosen = (completed.stdout or "").strip()
    return chosen or None


def tk_pick_workbook() -> str | None:
    """The native workbook dialog, one child process per call."""
    return _tk_pick_file(WORKBOOK_PICK_SNIPPET)


def tk_pick_calendar() -> str | None:
    """The native calendar-file dialog, same mechanism as the workbook."""
    return _tk_pick_file(CALENDAR_PICK_SNIPPET)


# The stdlib xlsx reader opens zip-based workbooks only. .xls, .xlsb and
# .csv look like workbooks to a manager but cannot be read; naming the
# supported types up front beats an amber card after registration.
WORKBOOK_SUFFIXES = (".xlsx", ".xlsm")


def probe_readable(candidate: Path) -> bool:
    """One open of the file: the honest check that it can be read here
    (a workbook held open by another program fails this on Windows)."""
    try:
        with candidate.open("rb"):
            pass
    except OSError:
        return False
    return True


def workbook_path_problem(path_text: str) -> str:
    """'' when the path is watchable; otherwise the human cause."""
    candidate = Path(path_text)
    if not candidate.exists():
        return f"That path does not exist: {path_text}"
    if not candidate.is_file():
        return f"That path is a folder, not a workbook: {path_text}"
    if candidate.suffix.lower() not in WORKBOOK_SUFFIXES:
        return (
            "Only .xlsx and .xlsm workbooks can be read here; the reader "
            f"cannot open .xls, .xlsb or .csv files: {path_text}"
        )
    if not probe_readable(candidate):
        return (
            "The workbook could not be opened (it may be locked by another "
            f"program): {path_text}"
        )
    return ""


def calendar_document_problem(data: bytes) -> str:
    """'' when the bytes parse as a calendar document; otherwise the cause."""
    try:
        parse_calendar_document(json.loads(data))
    except (CalendarUnreadable, ValueError) as exc:
        return f"That file is not a calendar document: {exc}"
    return ""


def calendar_path_problem(path_text: str) -> str:
    """'' when the path names a readable calendar file; else the cause.

    Checked before the choice is stored: an explicit path that cannot be
    read today would only move the failure to every later poll."""
    candidate = Path(path_text)
    if not candidate.exists():
        return f"That path does not exist: {path_text}"
    if not candidate.is_file():
        return f"That path is a folder, not a file: {path_text}"
    try:
        data = candidate.read_bytes()
    except OSError:
        return f"The file could not be read (it may be locked by another program): {path_text}"
    return calendar_document_problem(data)


class AgentDeskServer(ThreadingHTTPServer):
    """The app server: sessions, source table, and the excel watch."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        sessions: SessionStore,
        excel: ExcelWatch | None = None,
        pick_workbook=None,
        calendar: CalendarBridge | None = None,
        llm=None,
        audit_conn=None,
        llm_endpoint: str | None = None,
        llm_model: str | None = None,
        inbox_store: InboxStore | None = None,
        activity_log: ActivityLog | None = None,
        skill_store: SkillStore | None = None,
        settings_store: SettingsStore | None = None,
        plugins: PluginRuntime | None = None,
        pick_calendar=None,
        wizard_store: WizardStore | None = None,
    ) -> None:
        self.sessions = sessions
        self.excel = excel
        self.pick_workbook = pick_workbook
        self.pick_calendar = pick_calendar
        self.calendar = calendar
        self.llm = llm if llm is not None else env_chat()
        self.audit_conn = audit_conn
        env_endpoint, _key, env_model = env_config()
        self.llm_endpoint = llm_endpoint if llm_endpoint is not None else env_endpoint
        self.llm_model = llm_model if llm_model is not None else env_model
        self.inbox = inbox_store
        self.activity_log = activity_log
        self.skills = skill_store
        self.settings = settings_store
        self.plugins = plugins
        self.wizard_store = wizard_store
        self.consolidator = (
            Consolidator(activity_log, inbox_store, skill_store, activity_log.clock)
            if activity_log is not None and inbox_store is not None and skill_store is not None
            else None
        )
        self.started_monotonic = time.monotonic()
        super().__init__(address, DashboardHandler)

    @property
    def port(self) -> int:
        return self.server_address[1]


def live_sources(server: AgentDeskServer) -> list[SourceStatus]:
    """The source table computed at request time, from the real watches.

    Health must not repeat what a constructor once guessed: excel is
    connected when a workbook is registered, calendar when the bridge has
    produced a non-empty state, endpoint when the corporate base URL is
    set. Both /health and the dashboard's source line read this table.
    """

    def state(connected: bool) -> str:
        return STATUS_CONNECTED if connected else STATUS_NOT_CONNECTED

    excel = server.excel
    excel_path = excel.registered_path if excel is not None else None
    calendar = server.calendar
    calendar_state = calendar.status().get("state") if calendar is not None else None
    calendar_ok = calendar_state not in (None, STATE_EMPTY)
    # An endpoint saved in the settings page counts the same as one from
    # the environment: either is a real configuration.
    settings_base = server.settings.get("llm_base") if server.settings is not None else ""
    endpoint_ok = bool(settings_base) or bool(server.llm_endpoint)
    workbook = ""
    if excel_path:
        workbook = str(excel_path).replace("\\", "/").rsplit("/", 1)[-1]
    return [
        SourceStatus(
            SRC_EXCEL,
            state(excel_path is not None),
            f"Watches {workbook}." if excel_path else "No workbook connected yet.",
        ),
        SourceStatus(
            SRC_CALENDAR,
            state(calendar_ok),
            "Reading the OneDrive calendar sync." if calendar_ok else "No calendar data yet.",
        ),
        SourceStatus(
            SRC_RESEARCH,
            state(endpoint_ok),
            "Company endpoint configured." if endpoint_ok else "No company endpoint configured.",
        ),
    ]


def dashboard_payload(server: AgentDeskServer) -> dict:
    """Everything the dashboard shows, as data: one JSON payload for the
    SPA shell (and any later client). The same source-state branches the
    server-rendered cards apply live here as modes, so there is exactly
    one place where dashboard state is decided; the renderers and the SPA
    both follow it. Plugin cards are data (the same widget_cards() call
    the rendered dashboard makes, so a dashboard view still spends one
    pilot view), never server HTML.
    """
    settings = server.settings

    def allowed(key: str) -> bool:
        return settings is None or bool(settings.get(key))

    excel = server.excel
    sales_status = excel.status() if excel is not None else None
    if not allowed("excel_enabled"):
        sales_mode = "disabled"
    elif sales_status is not None and sales_status.get("configured"):
        sales_mode = "live"
    else:
        sales_mode = "unconfigured"

    calendar = server.calendar
    if not allowed("calendar_enabled"):
        commitments_mode, commitments_status = "disabled", None
    elif calendar is None:
        commitments_mode, commitments_status = "unavailable", None
    else:
        commitments_mode, commitments_status = "live", calendar.status()

    # The writer records the action as "llm.research" (assistant/loop.py);
    # querying anything else makes the stamp never show the last answer.
    audit_conn = server.audit_conn
    last_answer = (
        audit_store.last_ok_ts(audit_conn, "llm.research") if audit_conn is not None else None
    )

    skills = server.skills.active() if server.skills is not None else []  # type: ignore[attr-defined]
    plugin_cards = server.plugins.widget_cards() if server.plugins is not None else []
    sources = live_sources(server)
    inbox = server.inbox  # type: ignore[attr-defined]
    return {
        "version": agentdesk.__version__,
        "flags": {
            "excelEnabled": allowed("excel_enabled"),
            "calendarEnabled": allowed("calendar_enabled"),
            "endpointEnabled": allowed("endpoint_enabled"),
        },
        "sources": {
            "connected": sum(1 for s in sources if s.status == STATUS_CONNECTED),
            "total": len(SOURCE_IDS),
            "items": [
                {"id": s.id, "status": s.status, "detail": s.detail} for s in sources
            ],
        },
        "sales": {
            "enabled": allowed("excel_enabled"),
            "mode": sales_mode,
            "status": sales_status,
        },
        "commitments": {
            "enabled": allowed("calendar_enabled"),
            "mode": commitments_mode,
            "status": commitments_status,
        },
        "research": {
            "enabled": allowed("endpoint_enabled"),
            "lastAnsweredTs": last_answer,
        },
        "inbox": {"waiting": len(inbox.waiting()) if inbox is not None else 0},
        "skills": [
            {"id": s["id"], "name": s["name"], "description": s["description"]}
            for s in skills
        ],
        "plugins": {
            "cards": [
                {
                    "id": c["id"],
                    "title": c["title"],
                    "version": c["version"],
                    "pilot": c["pilot"],
                    "state": c["state"],
                    "freshness": c["freshness"],
                    "cause": c["cause"],
                }
                for c in plugin_cards
            ],
        },
    }


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
        method = "GET"
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
            self._send_index_or_dashboard()
        elif path == "/health":
            self._send_health()
        elif path == "/widgets/sales-24h":
            self._send_sales_status()
        elif path == "/widgets/commitments":
            self._send_commitments_status()
        elif path == "/walkthrough/calendar":
            calendar = self.server.calendar  # type: ignore[attr-defined]
            explicit = calendar.explicit_path() if calendar is not None else None
            hint = default_calendar_hint(explicit)
            self._send_bytes(
                200,
                pages.render_walkthrough(str(hint), explicit_path=explicit or "").encode("utf-8"),
                "text/html; charset=utf-8",
            )
        elif path == "/assistant":
            self._send_assistant_page()
        elif path == "/inbox":
            self._send_inbox_page()
        elif path == "/widgets/inbox":
            self._send_inbox_count()
        elif path == "/settings":
            self._send_settings_page()
        elif path.startswith("/skills/") and path.endswith("/skill.md"):
            self._send_skill_markdown(int(path[len("/skills/"):-len("/skill.md")].strip("/")))
        elif path == "/audit/tail":
            self._send_audit_tail()
        elif path == "/widgets/settings":
            self._send_settings_values()
        elif path.startswith("/wizard"):
            self._route_wizard(method, path)
            return
        elif path == "/api/plugins":
            self._send_json(200, {"plugins": self.server_plugins_widget_records()})
        elif path == "/api/dashboard":
            self._send_json(200, dashboard_payload(self.server))
        elif path.startswith("/api/plugins/"):
            self._send_json(200, self._plugin_record_or_404(path[len("/api/plugins/"):]))
        elif path == "/audit/export.csv":
            self._send_audit_csv()
        elif path == "/what-this-touches":
            self._send_touches_page()
        elif path == "/static/app.css":
            self._send_bytes(200, pages.STYLES.encode("utf-8"), "text/css; charset=utf-8")
        elif path == "/static/app.js":
            self._send_bytes(200, pages.APP_JS.encode("utf-8"), "text/javascript; charset=utf-8")
        elif path.startswith("/static/spa/"):
            self._send_spa_asset(path[len("/static/spa/"):])
        else:
            self._send_error_page(404, "Nothing here", "No page lives at this address.")

    # -- POST ------------------------------------------------------------

    def _route_post(self) -> None:
        if not self._gate():
            return
        method = "POST"
        path, _, _query = self.path.partition("?")
        # Drain the request body up front: an unread body on a keep-alive
        # connection would be parsed as the next request.
        self._raw_body = self._drain_body()
        excel = self.server.excel  # type: ignore[attr-defined]
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if path.startswith("/sources/excel-watch") and not self._source_allowed("excel_enabled"):
            self._send_json(409, {"error": "Sales watching is off in settings.", "reconnect": "/settings"})
            return
        if path.startswith("/sources/calendar-bridge") and not self._source_allowed("calendar_enabled"):
            self._send_json(409, {"error": "Calendar reading is off in settings.", "reconnect": "/settings"})
            return
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
            # Reject nonsense before registering: the manual-path fallback
            # lives on the card, so this error text is the feedback loop.
            problem = workbook_path_problem(body["path"].strip())
            if problem:
                self._send_json(400, {"error": problem})
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
            self._maybe_briefs()
            self._send_json(200, calendar.status())
        elif path == "/sources/calendar-bridge/pick":
            if calendar is None:
                self._send_json(503, {"error": "the calendar bridge is not available"})
                return
            self._send_json(200, {"path": self.server.pick_calendar()})  # type: ignore[attr-defined]
        elif path == "/sources/calendar-bridge/path":
            if calendar is None:
                self._send_json(503, {"error": "the calendar bridge is not available"})
                return
            body = self._read_json_body()
            if body is None or not isinstance(body.get("path"), str) or not body["path"].strip():
                self._send_json(400, {"error": "expected {\"path\": \"...\"}"})
                return
            chosen = body["path"].strip()
            problem = calendar_path_problem(chosen)
            if problem:
                self._send_json(400, {"error": problem})
                return
            # Stored before the poll so the choice survives restarts; the
            # poll right now is the card's feedback that it took effect.
            calendar_store.set_calendar_path(calendar.conn, chosen)
            calendar.retest()
            self._maybe_briefs()
            self._send_json(200, calendar.status())
        elif path == "/sources/calendar-bridge/upload":
            if calendar is None:
                self._send_json(503, {"error": "the calendar bridge is not available"})
                return
            raw = getattr(self, "_raw_body", b"")
            try:
                declared = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                declared = 0
            if declared > MAX_BODY_BYTES:
                self._send_json(400, {"error": "The calendar file is larger than 1 MB. Trim the export, or point at the file by path instead."})
                return
            if not raw.strip():
                self._send_json(400, {"error": "Send the calendar JSON as the request body."})
                return
            problem = calendar_document_problem(raw)
            if problem:
                self._send_json(400, {"error": problem})
                return
            target = default_data_dir() / "calendar_sync.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            calendar_store.set_calendar_path(calendar.conn, str(target))
            calendar.retest()
            self._maybe_briefs()
            self._send_json(200, calendar.status())
        elif path == "/sources/calendar-bridge/reset":
            if calendar is None:
                self._send_json(503, {"error": "the calendar bridge is not available"})
                return
            calendar_store.clear_calendar_path(calendar.conn)
            calendar.retest()
            self._maybe_briefs()
            self._send_json(200, calendar.status())
        elif path == "/research":
            body = self._read_json_body()
            question = (body or {}).get("question")
            if not isinstance(question, str) or not question.strip():
                self._send_json(400, {"error": "expected {\"question\": \"...\"}"})
                return
            self._log_activity("research", question.strip())
            self._send_json(200, self._run_llm_turn(
                question.strip(), summary_mode=True).to_json())
        elif path == "/inbox/cards":
            if self.server.inbox is None:  # type: ignore[attr-defined]
                self._send_json(503, {"error": "the inbox is not available"})
                return
            body = self._read_json_body() or {}
            try:
                card = self.server.inbox.add(  # type: ignore[attr-defined]
                    kind=str(body.get("kind", "suggestion")),
                    origin=str(body.get("origin", "")),
                    title=str(body.get("title", "")),
                    body=str(body.get("body", "")),
                    action_label=str(body.get("actionLabel", "")),
                    window_hours=body.get("windowHours"),
                    meta=body.get("meta") or {},
                )
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            inbox_service.evaluate(self.server.inbox, _local_now(), **self._budget_values())  # type: ignore[attr-defined]
            self._send_json(201, self.server.inbox.get(card.id).to_json(self.server.inbox.now_ts()))  # type: ignore[attr-defined]
        elif path.startswith("/inbox/cards/") and path.endswith("/accept"):
            self._inbox_decide(path[len("/inbox/cards/"):-len("/accept")], "accept")
        elif path.startswith("/inbox/cards/") and path.endswith("/dismiss"):
            self._inbox_decide(path[len("/inbox/cards/"):-len("/dismiss")], "dismiss")
        elif path.startswith("/inbox/dismissed/") and path.endswith("/restore"):
            self._inbox_restore(path[len("/inbox/dismissed/"):-len("/restore")])
        elif path == "/inbox/consolidate":
            if self.server.consolidator is None:  # type: ignore[attr-defined]
                self._send_json(503, {"error": "the repetition detector is not available"})
                return
            self._send_json(200, self.server.consolidator.consolidate())  # type: ignore[attr-defined]
        elif path.startswith("/skills/") and path.endswith("/run"):
            self._skill_run(int(path[len("/skills/"):-len("/run")].strip("/")))
        elif path.startswith("/skills/") and path.endswith("/undo"):
            self._skill_undo(int(path[len("/skills/"):-len("/undo")].strip("/")))
        elif path == "/settings/toggle":
            self._settings_toggle()
        elif path == "/settings/endpoint/save":
            self._endpoint_save()
        elif path == "/settings/endpoint/test":
            self._endpoint_test()
        elif path.startswith("/wizard"):
            self._route_wizard(method, path)
            return
        elif path.startswith("/api/plugins"):
            plugins = self.server.plugins  # type: ignore[attr-defined]
            if plugins is None:
                self._send_json(503, {"error": "plugins:unavailable",
                                      "message": "no plugin runtime is configured"})
                return
            try:
                self._dispatch_plugin_post(plugins, path, self._read_json_body() or {})
            except PluginError as exc:
                self._send_json(exc.status, {"error": exc.code, "message": str(exc)})
        elif path == "/assistant/ask":
            question = self._ask_question_from_body()
            if not question:
                self._send_json(400, {"error": "expected a question"})
                return
            self._log_activity("assistant", question)
            answer = self._run_llm_turn(question, summary_mode=False)
            if self.server.audit_conn is not None:  # type: ignore[attr-defined]
                threadlog.append(self.server.audit_conn, "user", question)  # type: ignore[attr-defined]
                text = answer.reply if answer.status == "ok" else f"[degraded] {answer.cause}"
                threadlog.append(self.server.audit_conn, "assistant", text)  # type: ignore[attr-defined]
            if self._is_form_submit():
                self.send_response(303)
                self.send_header("Location", "/assistant")
                self._common_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send_json(200, answer.to_json())
        else:
            self._send_error_page(404, "Nothing here", "No action lives at this address.")

    def _is_form_submit(self) -> bool:
        return "application/x-www-form-urlencoded" in (self.headers.get("Content-Type") or "")

    def _ask_question_from_body(self) -> str | None:
        raw = getattr(self, "_raw_body", b"")
        if not raw:
            return None
        if self._is_form_submit():
            from urllib.parse import parse_qs

            fields = parse_qs(raw.decode("utf-8"))
            values = fields.get("question", [])
            return values[0].strip() if values and values[0].strip() else None
        body = self._read_json_body()
        question = (body or {}).get("question")
        return question.strip() if isinstance(question, str) and question.strip() else None

    def _run_llm_turn(self, question: str, *, summary_mode: bool):
        server = self.server  # type: ignore[attr-defined]
        if not self._source_allowed("endpoint_enabled"):
            from agentdesk.assistant.loop import Answer, STATUS_DEGRADED

            return Answer(
                status=STATUS_DEGRADED,
                cause=(
                    "Company endpoint calls are turned off in settings, so "
                    "this surface is paused. Everything else keeps working."
                ),
            )
        context = build_context(
            server.excel.status() if server.excel is not None else None,
            server.calendar.status() if server.calendar is not None else None,
        )
        llm, endpoint, model = self._effective_llm()
        common = {
            "llm": llm,
            "audit_conn": server.audit_conn,
            "endpoint": endpoint,
            "model": model,
        }
        if summary_mode:
            return research(question, context, **common)
        return assistant_reply(question, context, **common)

    def _effective_llm(self) -> tuple:
        """The client this request uses, resolved per call: saved settings
        win over the startup-resolved endpoint, so an endpoint entered in
        the settings page applies without a restart. With nothing saved
        the startup client (env/config.env, or a test injection) is kept.
        """
        server = self.server  # type: ignore[attr-defined]
        settings = server.settings
        if settings is not None and settings.get("llm_base"):
            base, key, model = effective_llm_config(settings)
            return chat_client(base, key, model), base, model
        return server.llm, server.llm_endpoint, server.llm_model

    def _drain_body(self) -> bytes:
        """Read and stash the request body; the route decides what it means."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return b""
        if length <= 0 or length > MAX_BODY_BYTES:
            return b""
        return self.rfile.read(length)

    def _read_json_body(self) -> dict | None:
        raw = getattr(self, "_raw_body", b"")
        if not raw:
            return None
        try:
            parsed = json.loads(raw.decode("utf-8"))
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

    def _send_index_or_dashboard(self) -> None:
        """The SPA shell when the committed build exists; the
        server-rendered dashboard otherwise (a source checkout without a
        build). One address, whichever surface this checkout can serve.
        """
        index = spa_index_path()
        if index.is_file():
            self._send_bytes(200, index.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send_dashboard()

    def _send_spa_asset(self, relative: str) -> None:
        """One file from the committed SPA build. Everything is resolved
        against the build folder and refused outside it, however the path
        was spelled; the no-store stance applies to hashed assets too.
        """
        from urllib.parse import unquote

        root = SPA_DIR.resolve()
        candidate = (root / unquote(relative)).resolve()
        if candidate != root and not candidate.is_relative_to(root):
            self._send_error_page(404, "Nothing here", "No page lives at this address.")
            return
        if not candidate.is_file():
            self._send_error_page(404, "Nothing here", "No page lives at this address.")
            return
        mime = _SPA_MIME.get(candidate.suffix.lower(), "application/octet-stream")
        self._send_bytes(200, candidate.read_bytes(), mime)

    def _send_dashboard(self) -> None:
        now = datetime.now()
        widgets: list = []
        excel = self.server.excel  # type: ignore[attr-defined]
        sales_status = excel.status() if excel is not None else None
        if not self._source_allowed("excel_enabled"):
            widgets.append(render_sales_disabled(now))
        elif sales_status is not None and sales_status.get("configured"):
            widgets.append(render_sales_widget(sales_status))
        else:
            widgets.append(render_sales_unconfigured(now))
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if not self._source_allowed("calendar_enabled"):
            widgets.append(render_commitments_widget({"state": "disabled"}, now))
        elif calendar is not None:
            commitments = render_commitments_widget(calendar.status(), now)
            widgets.append(
                commitments if commitments is not None else render_commitments_unavailable(now)
            )
        else:
            widgets.append(render_commitments_unavailable(now))
        audit_conn = self.server.audit_conn  # type: ignore[attr-defined]
        # The writer records the action as "llm.research" (assistant/loop.py);
        # querying anything else makes the stamp never show the last answer.
        last_answer = audit_store.last_ok_ts(audit_conn, "llm.research") if audit_conn is not None else None
        widgets.append(render_research_widget(last_answer, now))
        connected = sum(1 for s in live_sources(self.server) if s.status == STATUS_CONNECTED)
        plugins = self.server.plugins  # type: ignore[attr-defined]
        if plugins is not None:
            widgets += [self._plugin_widget(card) for card in plugins.widget_cards()]
        inbox = self.server.inbox  # type: ignore[attr-defined]
        skills = self.server.skills.active() if self.server.skills is not None else []  # type: ignore[attr-defined]
        page = pages.render_dashboard(
            widgets,
            agentdesk.__version__,
            _greeting(now),
            now.strftime("%A, %d %B, %H:%M. "),
            inbox_count=len(inbox.waiting()) if inbox is not None else 0,
            skills=skills,
            connected_sources=connected,
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

    def _send_assistant_page(self) -> None:
        turns = []
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            turns = threadlog.turns(self.server.audit_conn)  # type: ignore[attr-defined]
        page = render_assistant_page(turns, agentdesk.__version__)
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_audit_tail(self) -> None:
        if self.server.audit_conn is None:  # type: ignore[attr-defined]
            self._send_json(503, {"error": "the audit store is not available"})
            return
        self._send_json(200, {"entries": audit_store.entries(self.server.audit_conn)})  # type: ignore[attr-defined]

    def _send_audit_csv(self) -> None:
        if self.server.audit_conn is None:  # type: ignore[attr-defined]
            self._send_json(503, {"error": "the audit store is not available"})
            return
        self._send_bytes(
            200,
            audit_store.csv_bytes(self.server.audit_conn),  # type: ignore[attr-defined]
            "text/csv; charset=utf-8",
        )

    def _log_activity(self, kind: str, text: str) -> None:
        """App-mediated asks only: this is the repetition detector's diet."""
        if self.server.activity_log is not None:  # type: ignore[attr-defined]
            self.server.activity_log.record(kind, text)  # type: ignore[attr-defined]

    def _send_settings_page(self) -> None:
        server = self.server  # type: ignore[attr-defined]
        entries = server.activity_log.entries() if server.activity_log is not None else []
        skills = server.skills.active() if server.skills is not None else []
        histories = {s["id"]: server.skills.history(s["id"]) for s in skills}
        page = render_settings_page(
            entries, skills, histories, agentdesk.__version__,
            settings_values=self._settings_public_values(),
            endpoint_status=self._endpoint_status(),
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _settings_public_values(self) -> dict:
        """Settings as they may leave the server: the key row is replaced
        by its masked state, here and in /widgets/settings alike."""
        settings = self.server.settings  # type: ignore[attr-defined]
        values = settings.all() if settings is not None else {}
        values["llm_key"] = mask_llm_key(values.get("llm_key", ""))
        return values

    def _endpoint_status(self) -> dict:
        """Configured or not, the form's current values, and the truth
        about the last call. A down endpoint shows degraded, never a
        false green; the key answers only in its masked state."""
        server = self.server  # type: ignore[attr-defined]
        settings = server.settings
        saved_base = settings.get("llm_base") if settings is not None else ""
        configured = bool(saved_base) or bool(server.llm_endpoint)
        last = "never"
        if server.audit_conn is not None:
            for entry in audit_store.entries(server.audit_conn, 20):
                if entry["action"].startswith("llm."):
                    last = entry["status"]
                    break
        saved_model = settings.get("llm_model") if settings is not None else ""
        key_state = mask_llm_key(settings.get("llm_key")) if settings is not None else ""
        return {
            "configured": configured,
            "last": last,
            "base": saved_base or server.llm_endpoint,
            "model": saved_model or server.llm_model,
            "keyState": key_state,
        }

    def _send_settings_values(self) -> None:
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        self._send_json(200, self._settings_public_values())

    def _endpoint_save(self) -> None:
        """Save (or clear, with empty strings) the three endpoint rows."""
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        body = self._read_json_body() or {}
        saved = {
            "llm_base": str(body.get("base", "")).strip(),
            "llm_key": str(body.get("key", "")).strip(),
            "llm_model": str(body.get("model", "")).strip(),
        }
        for key, value in saved.items():
            settings.set(key, value)
        self._send_json(200, {
            "ok": True,
            "base": saved["llm_base"],
            "model": saved["llm_model"],
            "keyState": mask_llm_key(saved["llm_key"]),
        })

    def _endpoint_test(self) -> None:
        """One minimal chat request against the SUBMITTED values, not the
        saved ones, so the connection can be checked before saving."""
        body = self._read_json_body() or {}
        base = str(body.get("base", "")).strip()
        if not base:
            self._send_json(200, {"ok": False, "cause": "Type a base URL first: there is nothing to test."})
            return
        key = str(body.get("key", "")).strip()
        model = str(body.get("model", "")).strip() or DEFAULT_MODEL
        try:
            chat(base, key, model, "ping", timeout=REQUEST_TIMEOUT_S, max_tokens=1)
        except LlmUnavailable as exc:
            self._send_json(200, {"ok": False, "cause": str(exc)})
            return
        self._send_json(200, {"ok": True})

    def _settings_toggle(self) -> None:
        server = self.server  # type: ignore[attr-defined]
        if server.settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        body = self._read_json_body() or {}
        key = body.get("key")
        if key not in ("excel_enabled", "calendar_enabled", "endpoint_enabled", "quiet_hours", "daily_cap"):
            self._send_json(400, {"error": "unknown setting"})
            return
        value = server.settings.toggle(key)
        self._apply_source_toggles(key, value)
        self._send_json(200, {"key": key, "value": value})

    def _apply_source_toggles(self, key: str, value) -> None:
        """Toggling a source off stops its ingestion immediately; on it
        resumes watching with one poll right now, like at startup."""
        server = self.server  # type: ignore[attr-defined]
        if key == "excel_enabled" and server.excel is not None:
            if value:
                server.excel.resume()
            else:
                server.excel.stop_polling()
        if key == "calendar_enabled" and server.calendar is not None:
            if value:
                server.calendar.start_polling()
                threading.Thread(
                    target=_poll_calendar_once, args=(server.calendar,), daemon=True
                ).start()
            else:
                server.calendar.stop_polling()

    def _source_allowed(self, key: str) -> bool:
        settings = self.server.settings  # type: ignore[attr-defined]
        return settings is None or bool(settings.get(key))

    def _budget_values(self) -> dict:
        """What the settings page shows is what the inbox enforces."""
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            return {}
        return {"quiet_hours": settings.get("quiet_hours"), "cap": settings.get("daily_cap")}

    def _skill_run(self, skill_id: int) -> None:
        server = self.server  # type: ignore[attr-defined]
        if server.skills is None:
            self._send_json(503, {"error": "skills are not available"})
            return
        if not self._source_allowed("endpoint_enabled"):
            self._send_json(200, {"status": "degraded", "cause": "Company endpoint calls are turned off in settings."})
            return
        skill = server.skills.get(skill_id)
        if skill is None or not skill["active"]:
            self._send_json(409, {"error": "that skill is not active"})
            return
        context = build_context(
            server.excel.status() if server.excel is not None else None,
            server.calendar.status() if server.calendar is not None else None,
        )
        llm, endpoint, model = self._effective_llm()
        answer = research(
            skill["prompt"], context, llm=llm, audit_conn=server.audit_conn,
            endpoint=endpoint, model=model,
        )
        self._send_json(200, answer.to_json())

    def _skill_undo(self, skill_id: int) -> None:
        server = self.server  # type: ignore[attr-defined]
        if server.skills is None:
            self._send_json(503, {"error": "skills are not available"})
            return
        try:
            self._send_json(200, server.skills.deactivate(skill_id))  # type: ignore[attr-defined]
        except SkillError as exc:
            self._send_json(404, {"error": str(exc)})

    def _send_skill_markdown(self, skill_id: int) -> None:
        server = self.server  # type: ignore[attr-defined]
        if server.skills is None:
            self._send_json(503, {"error": "skills are not available"})
            return
        try:
            markdown = server.skills.markdown(skill_id)  # type: ignore[attr-defined]
        except SkillError as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._send_bytes(200, markdown.encode("utf-8"), "text/plain; charset=utf-8")

    def _send_touches_page(self) -> None:
        observed: set[str] = set()
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            observed = audit_store.observed_actions(self.server.audit_conn)  # type: ignore[attr-defined]
        page = render_touches(observed, agentdesk.__version__, datetime.now())
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _maybe_briefs(self) -> None:
        """A calendar read may owe the inbox a brief or two."""
        server = self.server  # type: ignore[attr-defined]
        if server.calendar is not None and server.inbox is not None and server.activity_log is not None:
            try:
                generate_briefs(server.calendar, server.inbox, server.activity_log, server.inbox.clock)
            except Exception:  # noqa: BLE001 - briefs must never break the inbox
                LOG.exception("brief generation failed")

    def _send_inbox_page(self) -> None:
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        self._maybe_briefs()
        inbox_service.evaluate(inbox, _local_now(), **self._budget_values())
        now_ts = time.time()
        page = render_inbox_page(inbox.waiting(), inbox.dismissed(), agentdesk.__version__, now_ts)
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_inbox_count(self) -> None:
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        self._maybe_briefs()
        inbox_service.evaluate(inbox, _local_now(), **self._budget_values())
        waiting = inbox.waiting()
        self._send_json(200, {
            "waiting": len(waiting),
            "notified": sum(1 for c in waiting if c.notified_ts is not None),
            "dismissed": len(inbox.dismissed()),
        })

    def _inbox_decide(self, card_id: str, decision: str) -> None:
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        try:
            card = inbox.accept(card_id) if decision == "accept" else inbox.dismiss(card_id)
        except UnknownCard as exc:
            self._send_json(404, {"error": str(exc)})
            return
        if card.kind == "skill_proposal":
            self._on_skill_proposal_decided(card, decision)
        self._send_json(200, card.to_json(inbox.now_ts()))

    def _on_skill_proposal_decided(self, card, decision: str) -> None:
        """Accepting activates the skill; dismissing cools the pattern down."""
        server = self.server  # type: ignore[attr-defined]
        if server.skills is None or server.consolidator is None:
            return
        if decision == "accept":
            try:
                server.skills.activate(
                    name=card.meta.get("skillName", card.title),
                    description=f"{card.title}: {card.origin}"[:1024],
                    prompt=card.meta.get("prompt", card.title),
                )
            except SkillError as exc:
                LOG.warning("skill activation failed: %s", exc)
        else:
            pattern = card.meta.get("patternHash")
            if pattern:
                server.consolidator.dismiss_cooldown(pattern)

    def _inbox_restore(self, card_id: str) -> None:
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        try:
            card = inbox.restore(card_id)
        except UnknownCard as exc:
            # Either there is no such card or its 30 days are over; the
            # answer says which, and nothing is quietly dropped.
            if "30-day" in str(exc):
                self._send_json(410, {"error": str(exc)})
            else:
                self._send_json(404, {"error": str(exc)})
            return
        self._send_json(200, card.to_json(inbox.now_ts()))

    def _dispatch_plugin_post(self, plugins: PluginRuntime, path: str, body: dict) -> None:
        parts = [part for part in path.split("/") if part]
        if path == "/api/plugins/install":
            if not isinstance(body.get("zip_path"), str):
                self._send_json(400, {"error": "bad-request",
                                      "message": 'expected {"zip_path": "..."}'})
                return
            self._send_json(200, plugins.install(body["zip_path"], source=body.get("source", "zip")))
            return
        if len(parts) < 3:
            self._send_json(404, {"error": "not-found", "message": path})
            return
        plugin_id = parts[2]
        action = parts[3] if len(parts) > 3 else ""
        actions = {
            "update": lambda: plugins.update(plugin_id, body["zip_path"]),
            "consent": lambda: plugins.consent(plugin_id),
            "rollback": lambda: plugins.rollback(plugin_id),
            "enable": lambda: plugins.enable(plugin_id),
            "disable": lambda: plugins.disable(plugin_id),
            "uninstall": lambda: plugins.uninstall(plugin_id),
            "retest": lambda: plugins.retest(plugin_id),
            "purge-data": lambda: plugins.purge_data(plugin_id, body.get("confirmation")),
        }
        if action not in actions:
            self._send_json(404, {"error": "not-found", "message": path})
            return
        self._send_json(200, actions[action]())

    def _plugin_widget(self, card: dict) -> Widget:
        """One installed plugin's dashboard card: pilot badge, amber state.

        The amber treatment matches the built-in widgets, and every
        plugin-controlled string is escaped here: the shell renders widget
        bodies as authored HTML, so this is the boundary."""
        status = FRESH if card.get("freshness") == "fresh" else ATTENTION
        plugin_id = html.escape(str(card["id"]))
        cause = html.escape(str(card.get("cause") or "data source has not run"))
        file_name = html.escape(str(card.get("file") or "the data source"))
        version = html.escape(str(card["version"]))
        if status == FRESH:
            cause = f"reading {file_name}"
            body = '<p class="w-big">' + version + '</p><p class="w-note">' + cause + "</p>"
            extra = ""
        else:
            body = (
                '<div class="alert" id="plugin-amber-' + plugin_id + '">'
                "<p>" + cause + "</p>"
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
            id="plugin-" + plugin_id,
            title=html.escape(str(card["title"])),
            col="col-4",
            freshness=freshness,
            body_html=body,
            foot_html="plugin v" + version,
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

    def _route_wizard(self, method: str, path: str) -> None:
        """The wizard surface: describe, answer, build, preview, approve."""
        wizard = self.server.wizard_store  # type: ignore[attr-defined]
        if wizard is None:
            self._send_json(503, {"error": "the wizard is not available"})
            return
        parts = [part for part in path.split("/") if part]  # ["wizard", ...]
        if method == "POST" and path == "/wizard/start":
            body = self._read_json_body() or {}
            description = str(body.get("description", "")).strip()
            if not description:
                # The dashboard button lands here first: ask for the words
                # before a session exists. No-JS: a plain form.
                page = render_wizard_page(
                    {"id": "new", "state": "describing", "description": "",
                     "questions": [], "draft": {}, "ui_schema": None,
                     "sample_rows": []},
                    agentdesk.__version__,
                )
                self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")
                return
            session = wizard.create(description)
            self._advance_describe(session, description)
            self._send_json(201, wizard.get(session.id).to_json())
            return
        if len(parts) < 2:
            self._send_error_page(404, "Nothing here", "No wizard page lives at this address.")
            return
        session_id = parts[1]
        action = parts[2] if len(parts) > 2 else ""
        if method == "GET" and action == "":
            self._send_wizard_page(session_id)
            return
        if method == "POST" and action == "answer":
            self._wizard_answer(session_id)
            return
        if method == "POST" and action == "approve":
            self._wizard_approve(session_id)
            return
        if method == "POST" and action == "escalate":
            self._wizard_escalate(session_id, reason="The wizard cannot build this safely.")
            return
        self._send_error_page(404, "Nothing here", "No wizard action lives at this address.")

    def _advance_describe(self, session, description: str) -> None:
        """Ask the compiler for the multiple-choice questions."""
        compiler = self._wizard_compiler()
        if compiler is None:
            return
        try:
            session.questions = compiler.questions_for(description)
        except Exception:  # noqa: BLE001 - the defaults are the floor
            LOG.exception("wizard questions failed; using defaults")
            session.questions = WizardCompiler(None).questions_for(description)
        session.state = "questions"
        self.server.wizard_store.save(session)  # type: ignore[attr-defined]

    def _wizard_compiler(self):
        server = self.server  # type: ignore[attr-defined]
        if server.audit_conn is not None and server.llm is not None:
            conn = server.audit_conn
            endpoint, _key, model = env_config()
            inner = server.llm

            def audited_llm(prompt: str) -> str:
                try:
                    result = inner(prompt)
                except Exception as exc:  # noqa: BLE001 - audit then re-raise
                    audit_store.record(conn, "llm.wizard", target=endpoint,
                                       status="error", model=model,
                                       request_bytes=len(prompt.encode("utf-8")),
                                       detail=str(exc)[:200])
                    raise
                audit_store.record(conn, "llm.wizard", target=endpoint,
                                   status="ok", model=model,
                                   request_bytes=len(prompt.encode("utf-8")))
                return result

            return WizardCompiler(audited_llm)
        return WizardCompiler(None)

    def _wizard_answer(self, session_id: str) -> None:
        """Answers in, then build with capped self-repair. Redirects to the
        page so a plain form works without JavaScript."""
        wizard = self.server.wizard_store  # type: ignore[attr-defined]
        if session_id == "new":
            # The describe screen before any session exists: the words make
            # the session.
            description = str((self._read_json_body() or {}).get("description", "")).strip()
            if not description:
                self._send_redirect("/wizard/start")
                return
            session = wizard.create(description)
            self._advance_describe(session, description)
            self._send_redirect(f"/wizard/{session.id}")
            return
        session = wizard.get(session_id)
        body = self._read_json_body() or {}
        if "description" in body and body.get("description", "").strip():
            description = str(body["description"]).strip()
            session.description = description
            self._advance_describe(session, description)
            self._send_redirect(f"/wizard/{session_id}")
            return
        answers = body.get("answers") or {
            q["id"]: q.get("default", "") for q in session.questions
        }
        session.answers = answers
        compiler = self._wizard_compiler()
        if compiler is None:
            self._send_json(503, {"error": "the wizard is not available"})
            return
        try:
            draft = compiler.build(session, answers)
        except WizardError as exc:
            self._escalate(session, exc)
            self._send_redirect(f"/wizard/{session_id}")
            return
        session.draft = draft
        session.state = "preview"
        wizard.save(session)
        self._send_redirect(f"/wizard/{session_id}")

    def _wizard_approve(self, session_id: str) -> None:
        """The one consolidated approval: zip the validated draft and hand
        it to the plugin runtime, which validates again and installs in
        pilot mode."""
        wizard = self.server.wizard_store  # type: ignore[attr-defined]
        session = wizard.get(session_id)
        plugins = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            self._send_json(503, {"error": "plugins:unavailable",
                                  "message": "no plugin runtime is configured"})
            return
        if session.state != "preview" or not session.draft:
            self._send_json(409, {"error": "wizard:not-in-preview"})
            return
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp) / session.draft["manifest"]["id"]
            plugin_dir.mkdir()
            (plugin_dir / "manifest.json").write_text(
                json.dumps(session.draft["manifest"], indent=2), encoding="utf-8")
            (plugin_dir / "widget.ui.json").write_text(
                json.dumps(session.draft["ui_schema"], indent=2), encoding="utf-8")
            zip_path = Path(tmp) / "wizard-plugin.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                for file in plugin_dir.rglob("*"):
                    zf.write(file, file.relative_to(plugin_dir).as_posix())
            result = plugins.install(zip_path, source="wizard")
        session.state = "approved"
        session.draft = {**session.draft, "installed": result}
        wizard.save(session)
        summary = approval_summary(session.draft["manifest"])
        self._send_json(200, {"status": "installed", "pilot": True,
                              "summary": summary, "install": result})

    def _wizard_escalate(self, session_id: str, reason: str) -> None:
        wizard = self.server.wizard_store  # type: ignore[attr-defined]
        session = wizard.get(session_id)
        self._escalate(session, WizardError("wizard:escalated", reason, 422))
        self._send_redirect(f"/wizard/{session_id}")

    def _escalate(self, session, exc: WizardError) -> None:
        """The honest dead-end: a feature-request card in the inbox, the
        user's every word preserved on both card and session."""
        session.state = "escalated"
        session.feature_request = exc.feature_request or {
            "description": session.description,
            "answers": session.answers,
            "reason": str(exc),
            "kind": "feature_request",
        }
        self.server.wizard_store.save(session)  # type: ignore[attr-defined]
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is not None:
            inbox.add(
                kind="feature_request",
                origin="The plugin wizard could not build this safely.",
                title="Feature request exported to the owner queue",
                body=(
                    f"Your words, preserved: {session.description}\n"
                    f"Reason: {session.feature_request.get('reason', '')}"
                ),
                meta={"wizardSession": session.id,
                      "featureRequest": session.feature_request},
            )

    def _send_wizard_page(self, session_id: str) -> None:
        wizard = self.server.wizard_store  # type: ignore[attr-defined]
        try:
            session = wizard.get(session_id)
        except WizardError as exc:
            self._send_error_page(404, "Nothing here", str(exc))
            return
        payload = session.to_json()
        draft = session.draft or {}
        # The view's draft is the manifest (its approval summary reads
        # permissions); the ui schema and sample rows ride top-level.
        payload["draft"] = draft.get("manifest", {}) if isinstance(draft, dict) else {}
        payload["ui_schema"] = (draft.get("ui_schema")
                                if isinstance(draft, dict) else None)
        sample = [
            {"Product line": "Atlas ERP", "Change": "+4.2%"},
            {"Product line": "Care plans", "Change": "+1.6%"},
            {"Product line": "Field services", "Change": "-2.8%"},
        ]
        payload["sample_rows"] = sample
        payload["approval"] = approval_summary(payload["draft"]) if payload["draft"] else {}
        page = render_wizard_page(payload, agentdesk.__version__)
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self._common_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_health(self) -> None:
        payload = health_payload(
            agentdesk.__version__,
            live_sources(self.server),  # type: ignore[attr-defined]
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
    excel: ExcelWatch | None = None,
    pick_workbook=None,
    calendar: CalendarBridge | None = None,
    llm=None,
    audit_conn=None,
    llm_endpoint: str | None = None,
    llm_model: str | None = None,
    inbox_store: InboxStore | None = None,
    activity_log: ActivityLog | None = None,
    skill_store: SkillStore | None = None,
    settings_store: SettingsStore | None = None,
    plugins: PluginRuntime | None = None,
    pick_calendar=None,
    wizard_store: WizardStore | None = None,
) -> AgentDeskServer:
    """Bind the app to the loopback and nothing else.

    A non-loopback host is a hard error, not a warning: the skeleton must
    be incapable of listening on 0.0.0.0 even by misconfiguration. When no
    port is given, the preferred port is tried once and an ephemeral port
    is the fallback, so the auth URL always names the port that actually
    opened. The excel watch, the calendar bridge and the audit store
    default to real ones over the user data directory; tests pass their
    own.
    """
    resolved = "127.0.0.1" if host == "localhost" else host
    if resolved != "127.0.0.1":
        raise ValueError(f"refusing to bind non-loopback host: {host!r}")
    sessions = SessionStore()
    if excel is None:
        excel = _default_excel_watch()
    # Settings first: the default calendar bridge wires its breakdown
    # client to them, so saved endpoints apply without a restart.
    if settings_store is None:
        settings_store = _default_settings_store()
    if calendar is None:
        calendar = _default_calendar_bridge(settings_store)
    if audit_conn is None:
        audit_conn = _default_audit_conn()
    if inbox_store is None:
        inbox_store = _default_inbox_store()
    if activity_log is None or skill_store is None:
        repetition = _default_repetition_stores()
        if activity_log is None:
            activity_log = repetition[0]
        if skill_store is None:
            skill_store = repetition[1]
    if pick_workbook is None:
        pick_workbook = tk_pick_workbook
    if pick_calendar is None:
        pick_calendar = tk_pick_calendar
    if settings_store is None:
        settings_store = _default_settings_store()
    if wizard_store is None:
        wizard_store = _default_wizard_store()

    def construct(bind_port: int) -> AgentDeskServer:
        return AgentDeskServer(
            (resolved, bind_port), sessions, excel, pick_workbook,
            calendar, llm, audit_conn, llm_endpoint, llm_model, inbox_store,
            activity_log, skill_store, settings_store, plugins, pick_calendar, wizard_store,
        )

    if port is None:
        try:
            server = construct(PREFERRED_PORT)
        except OSError:
            server = construct(0)
    else:
        server = construct(port)
    _wire_audit(server)
    return server


def _wire_audit(server: AgentDeskServer) -> None:
    """Give the watches and the model wrapper the audit hook.

    Applied to injected watches too: whatever object serves the requests
    at runtime reports into the one append-only store. The breakdown
    target is resolved per call with the same settings-over-env order
    the inner client uses, so the audit row names what was really hit.
    """
    if server.audit_conn is None:
        return
    conn = server.audit_conn

    def hook(action: str, target: str, status: str = "ok") -> None:
        audit_store.record(conn, action, target=target, status=status)

    if server.excel is not None:
        server.excel.audit_hook = hook
    if server.calendar is not None:
        server.calendar.audit_hook = hook
        inner_llm = server.calendar.llm

        def audited_llm(prompt: str) -> str:
            endpoint, _key, model = effective_llm_config(server.settings)
            try:
                result = inner_llm(prompt)
            except Exception as exc:  # noqa: BLE001 - audit then re-raise
                audit_store.record(conn, "llm.breakdown", target=endpoint,
                                   status="error", model=model,
                                   request_bytes=len(prompt.encode("utf-8")),
                                   detail=str(exc)[:200])
                raise
            audit_store.record(conn, "llm.breakdown", target=endpoint,
                               status="ok", model=model,
                               request_bytes=len(prompt.encode("utf-8")))
            return result

        server.calendar.llm = audited_llm


def _default_audit_conn():
    """The local audit store, or None when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "audit.sqlite3", check_same_thread=False)
        audit_store.ensure_schema(conn)
        return conn
    except (OSError, sqlite3.Error):
        LOG.exception("audit store unavailable")
        return None


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


def _default_inbox_store() -> InboxStore | None:
    """The inbox over the persistent store, or None when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "inbox.sqlite3", check_same_thread=False)
        return InboxStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("inbox unavailable")
        return None


def _default_wizard_store() -> WizardStore | None:
    """Wizard sessions over the persistent store, or None when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "wizard.sqlite3", check_same_thread=False)
        return WizardStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("wizard store unavailable")
        return None


def _default_repetition_stores() -> tuple[ActivityLog | None, SkillStore | None]:
    """The activity log and skill store over one file, or Nones."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "repetition.sqlite3", check_same_thread=False)
        return ActivityLog(conn, time.time), SkillStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("repetition stores unavailable")
        return None, None


def _default_settings_store() -> SettingsStore | None:
    """Settings over the persistent store, or None when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "settings.sqlite3", check_same_thread=False)
        ensure_settings_schema(conn)
        return SettingsStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("settings unavailable")
        return None


def default_calendar_hint(explicit: str | None = None) -> Path:
    """The calendar path the walkthrough shows as 'the app watches this'.

    An explicitly chosen path is shown as is: that is the file the reader
    uses. Otherwise the reader accepts several shapes (plain OneDrive, the
    'OneDrive - Company' glob, macOS CloudStorage); the hint shows the
    first one that exists on this machine, falling back to the first
    default, so it never names a path the reader would ignore.
    """
    if explicit:
        return Path(explicit)
    candidates = default_calendar_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _default_calendar_bridge(settings_store=None) -> CalendarBridge | None:
    """A real bridge over the persistent store, or None when it cannot open.

    The breakdown client resolves settings over env on every call, so an
    endpoint saved in the app is used by new breakdowns without a restart;
    with nothing configured it degrades to the generic breakdown.
    """
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "calendar-bridge.sqlite3", check_same_thread=False)
        bridge = CalendarBridge(conn)
        if settings_store is not None:
            bridge.llm = settings_chat(settings_store)
        return bridge
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
        # flush: launchers redirect this to a log file, where a buffered
        # print would hide the one-time start link until the process ends
        print(f"Agent Desk is running: {url}", flush=True)
    start_background_polls(server)
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start_background_polls(server: AgentDeskServer) -> None:
    """Both watches poll once, right now, on daemon threads.

    The recurring loops keep their own schedules (calendar every half
    hour, excel hourly); this only removes the empty first half hour on
    the commitments card and brings the registered workbook back after a
    restart. A source turned off in settings is not touched at all.
    """

    def allowed(key: str) -> bool:
        settings = server.settings
        return settings is None or bool(settings.get(key))

    excel = server.excel
    if excel is not None and allowed("excel_enabled"):
        excel.resume()
    calendar = server.calendar
    if calendar is not None and allowed("calendar_enabled"):
        calendar.start_polling()  # passive file watch, keeps itself fresh
        threading.Thread(target=_poll_calendar_once, args=(calendar,), daemon=True).start()


def _poll_calendar_once(bridge) -> None:
    """One immediate read so the first page load already knows the day."""
    try:
        bridge.poll()
    except Exception:  # noqa: BLE001 - startup must not crash on a poll
        LOG.exception("calendar startup poll failed")
