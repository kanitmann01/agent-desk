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
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

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
from agentdesk.capabilities import GATES, CapabilitiesCache, GateRunners, default_gate_runners
from agentdesk.consents import ConsentStore
from agentdesk.excel.watcher import ExcelWatch, default_adapters
from agentdesk.inbox import service as inbox_service
from agentdesk.inbox.core import (
    KIND_MAIL_FOLLOW_UP,
    KIND_UPDATE_CONSENT,
    STATUS_WAITING,
    UnknownCard,
)
from agentdesk.inbox.snooze import SNOOZE_CHOICES, snooze_until
from agentdesk.inbox.store import InboxStore
from agentdesk.mail.core import reply_recipients, reply_subject, write_reply
from agentdesk.mail.store import MailStore
from agentdesk.mail.watcher import (
    STATE_ERROR,
    STATE_UNCONFIGURED,
    STATE_WATCHING,
    MailWatch,
)
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
from agentdesk.memory.core import UnknownFact
from agentdesk.memory.service import build_facts_block
from agentdesk.memory.store import MemoryStore
from agentdesk.plugins.runtime import PluginError, PluginRuntime
from agentdesk.registry import source as registry_source
from agentdesk.registry.index import RegistryIndexError
from agentdesk.registry.install import RegistryError
from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.service import Consolidator
from agentdesk.repetition.skills import SkillError, SkillStore
from agentdesk.server.activity_view import DECISIONS, render_activity_page
from agentdesk.server import pages
from agentdesk.server.auth import SessionStore, session_id_from_cookie
from agentdesk.server.capabilities_view import render_capabilities_page
from agentdesk.server.commitments import (
    render_commitments_unavailable,
    render_commitments_widget,
)
from agentdesk.server.inbox_view import render_inbox_page
from agentdesk.server.mail_view import render_mail_page
from agentdesk.server.memory_view import render_memory_page
from agentdesk.server.plugins_view import render_plugins_page
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
# 'unsafe-inline' because the server-rendered pages compose small style
# ATTRIBUTES (a margin above a heading, a spacing line), which
# 'unsafe-inline' in style-src governs. Style attributes cannot execute
# code; scripts still can, so script-src stays 'self' and no inline
# <script> block ships anywhere: the SPA loads only its own hashed
# bundles from /static/spa/, and styles itself through the stylesheet
# and the CSSOM (which the CSP does not govern), never inline styles.
# font-src is 'self' for the same reason scripts and styles are: the
# SPA's two typefaces (Plus Jakarta Sans and IBM Plex Mono, SIL OFL
# 1.1) are .woff2 files inside the committed bundle, served from
# /static/spa/assets/. Without the directive, font loads fall back to
# default-src 'none' and the bundled fonts are blocked. Self only: no
# font host, no data: URLs, so the page still fetches nothing from
# another origin.
SECURITY_HEADERS = (
    ("Content-Security-Policy",
     "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
     "font-src 'self'; img-src 'self' data:; connect-src 'self'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)

MAX_BODY_BYTES = 1024 * 1024

# A body over MAX_BODY_BYTES is refused but still drained, so a keep-alive
# connection survives the refusal; this is the hard bound on that draining.
# Beyond it the server answers and closes instead of reading unboundedly:
# keeping a localhost connection is never worth reading gigabytes.
MAX_DRAIN_BYTES = 8 * MAX_BODY_BYTES


def body_drain_plan(length: int) -> str:
    """What to do with a request body of this declared length: 'skip'
    (nothing declared), 'stash' it for the route, 'discard' it (over the
    stash limit but within the hard cap), or 'close' (beyond the cap;
    the answer goes out with Connection: close)."""
    if length <= 0:
        return "skip"
    if length <= MAX_BODY_BYTES:
        return "stash"
    if length <= MAX_DRAIN_BYTES:
        return "discard"
    return "close"

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


def form_body_fields(raw: bytes) -> dict | None:
    """Form-urlencoded bytes as the dict the JSON handlers read: each
    field mapped to its first value. The fallback for bodies that declare
    the form content type (the no-JS screens), never a speculative parse
    of anything else."""
    try:
        fields = parse_qs(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return None
    return {name: values[0] for name, values in fields.items() if values}


def plain_preview(text: str, limit: int = 140) -> str:
    """A one-line plain-text preview of a draft for the audit log: the
    donor approvals module's plainText. Tags and entities out, whitespace
    collapsed, capped, so the log never carries markup."""
    stripped = re.sub(r"<[^>]*>", " ", text)
    stripped = re.sub(r"&[a-zA-Z]+;", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()[:limit]


def _flag(body: dict, *names: str) -> bool:
    """A checkbox-style flag from either a JSON body (true) or a form
    post ("1", "true", "on"): the same choice, two wire shapes."""
    for name in names:
        value = body.get(name)
        if value is True or (isinstance(value, str)
                             and value.strip().lower() in ("1", "true", "on")):
            return True
    return False


def _memory_id_from_path(path: str, suffix: str) -> int | None:
    """The fact id in /memory/<id>/edit (or /delete), or None when the
    address names no fact."""
    raw = path[len("/memory/"):-len(suffix)]
    return int(raw) if raw.isascii() and raw.isdigit() else None


def _fact_json(fact) -> dict:
    """A fact as the API answers it."""
    return {
        "id": fact.id,
        "text": fact.text,
        "source": fact.source,
        "createdTs": fact.created_ts,
    }


def _plugin_audit_detail(action: str, result: dict) -> str:
    """What each plugin lifecycle row says, from the action's own result."""
    result = result if isinstance(result, dict) else {}
    if action == "update":
        if result.get("applied"):
            return f"applied v{result.get('version', '')}"
        return "held for consent: adds " + "; ".join(result.get("added_scopes", []))
    if action == "consent":
        return f"applied v{result.get('version', '')}"
    if action == "rollback":
        return f"rolled back to {result.get('rolled_back_to', '')}"
    if action in ("enable", "disable"):
        return f"state: {result.get('state', action)}"
    if action == "uninstall":
        return "program files deleted, data preserved"
    if action == "purge-data":
        return "data folder deleted after confirmation"
    if action == "retest":
        return f"data source: {result.get('status', '')}"
    return ""


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
        consents: ConsentStore | None = None,
        memory_store: MemoryStore | None = None,
        capabilities_cache: CapabilitiesCache | None = None,
        gate_runners: GateRunners | None = None,
        mail: MailWatch | None = None,
        mail_store: MailStore | None = None,
        outbox_dir=None,
        registry_root=None,
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
        self.memory = memory_store
        # The capabilities cache may be absent (its store could not open);
        # the runner set defaults to the real probe bundle. Building that
        # set probes nothing: gates run only when a re-test POST calls one.
        self.capabilities_cache = capabilities_cache
        self.gate_runners = gate_runners if gate_runners is not None else _default_gate_runners()
        # Process-lifetime consent allows: (plugin, scope) pairs accepted
        # "for this plugin". A fresh set unless injected; restart forgets.
        self.consents = consents if consents is not None else ConsentStore()
        # The mail watcher exists only when mail is enabled (the toggle
        # defaults to off, so a default boot has no watcher at all); the
        # handled-thread store and the outbox folder exist regardless.
        self.mail = mail
        # The registry checkout the plugins page browses. None resolves
        # per request (settings > environment > this app's own checkout);
        # an empty string forces the honest unavailable state, which is
        # what the hermetic test boots pass so no suite read or install
        # ever reaches a real checkout by accident.
        self.registry_root = registry_root
        self.mail_store = mail_store
        self.outbox_dir = Path(outbox_dir) if outbox_dir is not None else _default_outbox_dir()
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
                    "checkedAt": c.get("checked_at", ""),
                    "payload": c.get("payload"),
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
        self._close_with_response = False
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
        """Origin/Host guard, then session auth. Sends the answer itself.

        Both refusals end the connection: the gate runs before the body
        is drained, and an unread body on a kept-alive connection is
        exactly what the drain exists to prevent."""
        verdict = check_request(
            self.headers.get("Host"),
            self.headers.get("Origin"),
            self.server.port,  # type: ignore[attr-defined]
        )
        if not verdict.allowed:
            self._refuse_and_close(403, "Blocked", "This request did not come from the dashboard's own address.")
            return False
        if not self._authenticated():
            self._refuse_and_close(
                401, "Session required",
                "Open Agent Desk from its shortcut to get a fresh link.",
            )
            return False
        return True

    def _refuse_and_close(self, status: int, title: str, message: str) -> None:
        """Answer a refusal with Connection: close. The body is read up
        to the stash limit first, because closing over an unread buffer
        sends RST on Windows and can eat the very response being sent; a
        larger body is not worth reading for a request that already
        failed the gate."""
        length = self._declared_length()
        if 0 < length <= MAX_BODY_BYTES:
            self.rfile.read(length)
        self._close_with_response = True
        self.close_connection = True
        self._send_error_page(status, title, message)

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
                pages.render_walkthrough(str(hint), explicit_path=explicit or "",
                                        version=agentdesk.__version__,
                                        inbox_count=self._inbox_waiting_count()).encode("utf-8"),
                "text/html; charset=utf-8",
            )
        elif path == "/assistant":
            self._send_assistant_page()
        elif path == "/inbox":
            self._send_inbox_page()
        elif path == "/activity":
            self._send_activity_page()
        elif path == "/memory":
            self._send_memory_page()
        elif path == "/mail":
            self._send_mail_page()
        elif path == "/capabilities":
            self._send_capabilities_page()
        elif path == "/plugins":
            _, _sep, query = self.path.partition("?")
            notice = parse_qs(query).get("notice", [""])[0] if query else ""
            self._send_plugins_page(notice=notice)
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
        elif path == "/api/registry":
            self._send_json(200, self._registry_listing_for_request())
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
            # Through the bridge so the write lands under its lock, like
            # every other use of the shared connection.
            calendar.set_explicit_path(chosen)
            calendar.retest()
            self._maybe_briefs()
            self._send_json(200, calendar.status())
        elif path == "/sources/calendar-bridge/upload":
            if calendar is None:
                self._send_json(503, {"error": "the calendar bridge is not available"})
                return
            raw = getattr(self, "_raw_body", b"")
            declared = getattr(self, "_content_length", 0)
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
            calendar.set_explicit_path(str(target))
            calendar.retest()
            self._maybe_briefs()
            self._send_json(200, calendar.status())
        elif path == "/sources/calendar-bridge/reset":
            if calendar is None:
                self._send_json(503, {"error": "the calendar bridge is not available"})
                return
            calendar.clear_explicit_path()
            calendar.retest()
            self._maybe_briefs()
            self._send_json(200, calendar.status())
        elif path == "/research":
            question = self._ask_question_from_body()
            if not question:
                self._send_json(400, {"error": "expected {\"question\": \"...\"}"})
                return
            self._log_activity("research", question)
            self._send_json(200, self._run_llm_turn(
                question, summary_mode=True).to_json())
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
                    draft=str(body.get("draft", "")),
                )
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._evaluate_inbox(self.server.inbox)  # type: ignore[attr-defined]
            self._send_json(201, self.server.inbox.get(card.id).to_json(self.server.inbox.now_ts()))  # type: ignore[attr-defined]
        elif path.startswith("/inbox/cards/") and path.endswith("/accept"):
            self._inbox_decide(path[len("/inbox/cards/"):-len("/accept")], "accept")
        elif path.startswith("/inbox/cards/") and path.endswith("/dismiss"):
            self._inbox_decide(path[len("/inbox/cards/"):-len("/dismiss")], "dismiss")
        elif path.startswith("/inbox/cards/") and path.endswith("/edit"):
            self._inbox_edit(path[len("/inbox/cards/"):-len("/edit")])
        elif path.startswith("/inbox/cards/") and path.endswith("/snooze"):
            self._inbox_snooze(path[len("/inbox/cards/"):-len("/snooze")])
        elif path.startswith("/inbox/cards/") and path.endswith("/more-info"):
            self._inbox_more_info(path[len("/inbox/cards/"):-len("/more-info")])
        elif path.startswith("/inbox/dismissed/") and path.endswith("/restore"):
            self._inbox_restore(path[len("/inbox/dismissed/"):-len("/restore")])
        elif path == "/memory/add":
            self._memory_add()
        elif path.startswith("/memory/") and path.endswith("/edit"):
            self._memory_edit(_memory_id_from_path(path, "/edit"))
        elif path.startswith("/memory/") and path.endswith("/delete"):
            self._memory_delete(_memory_id_from_path(path, "/delete"))
        elif path == "/memory/recall":
            self._memory_recall()
        elif path.startswith("/capabilities/") and path.endswith("/retest"):
            self._capabilities_retest(path[len("/capabilities/"):-len("/retest")])
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
        elif path == "/settings/mail/folder":
            self._mail_folder_save()
        elif path == "/settings/registry/path":
            self._registry_path_save()
        elif path == "/api/registry/install":
            self._registry_install()
        elif path == "/plugins/registry-install":
            self._registry_install()
        elif path.startswith("/plugins/") and path.count("/") == 3:
            self._plugins_page_action(path)
        elif path == "/mail/retest":
            self._mail_retest()
        elif path.startswith("/mail/") and path.endswith("/draft"):
            if not self._source_allowed("mail_enabled"):
                self._send_json(409, {"error": "Mail digest is off in settings.", "reconnect": "/settings"})
                return
            self._mail_draft(unquote(path[len("/mail/"):-len("/draft")]))
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
        body = self._read_json_body()
        question = (body or {}).get("question")
        return question.strip() if isinstance(question, str) and question.strip() else None

    def _answers_from_form(self, body: dict, questions: list,
                           earlier: dict | None = None) -> dict | None:
        """A form post's fields as an answers dict, or None when the body
        is not one question form's shape. Each form carries the question's
        index in a hidden field and the chosen option in the answer field;
        earlier answers win over defaults, this form's choice wins over
        both, so answering the forms one at a time keeps every choice."""
        choice = body.get("answer")
        if not isinstance(choice, str) or not choice.strip():
            return None
        index_text = str(body.get("question", ""))
        if not index_text.isascii() or not index_text.isdigit():
            return None
        index = int(index_text)
        if index >= len(questions):
            return None
        answers = {q["id"]: q.get("default", "") for q in questions}
        answers.update(earlier or {})
        answers[questions[index]["id"]] = choice.strip()
        return answers

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
            facts_block=self._facts_block(question) if not summary_mode else "",
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

    def _facts_block(self, question: str) -> str:
        """The bounded recalled-facts block for the assistant prompt,
        ranked against the user's question. Recall only: this path never
        creates a fact; the bounds live in memory/service."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return ""
        return build_facts_block(memory.recall(question))

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

    def _declared_length(self) -> int:
        """The Content-Length header as an int, 0 when absent or malformed.
        The one place the header is parsed; everything else reads this."""
        try:
            return int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return 0

    def _drain_body(self) -> bytes:
        """Read and stash the request body; the route decides what it means.

        An over-limit body is still read and discarded (up to the hard
        cap in body_drain_plan) so a keep-alive connection survives the
        refusal; beyond the cap the connection is closed with the answer
        instead of draining, because no connection is worth reading
        unboundedly many bytes for."""
        length = self._declared_length()
        if length <= 0:
            return b""
        # Stashed beside the body so routes read the parsed value rather
        # than re-parsing the header.
        self._content_length = length
        plan = body_drain_plan(length)
        if plan == "close":
            self._close_with_response = True
            self.close_connection = True
            return b""
        if plan == "discard":
            self.rfile.read(length)
            return b""
        return self.rfile.read(length)  # stash

    def _read_json_body(self) -> dict | None:
        raw = getattr(self, "_raw_body", b"")
        if not raw:
            return None
        if self._is_form_submit():
            return form_body_fields(raw)
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
        page = render_assistant_page(turns, agentdesk.__version__,
                                     inbox_count=self._inbox_waiting_count())
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
            mail_folder=server.settings.get("mail_folder") if server.settings is not None else "",
            registry_status=self._registry_status_for_settings(),
            inbox_count=self._inbox_waiting_count(),
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _registry_status_for_settings(self) -> dict:
        """The listing shape plus the saved path, for the settings form."""
        listing = dict(self._registry_listing_for_request())
        settings = self.server.settings  # type: ignore[attr-defined]
        listing["saved_path"] = (settings.get(registry_source.SETTINGS_KEY)
                                 if settings is not None else "") or ""
        return listing

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
        if key not in ("excel_enabled", "calendar_enabled", "endpoint_enabled", "quiet_hours", "daily_cap", "mail_enabled"):
            self._send_json(400, {"error": "unknown setting"})
            return
        value = server.settings.toggle(key)
        self._apply_source_toggles(key, value)
        self._send_json(200, {"key": key, "value": value})

    def _apply_source_toggles(self, key: str, value) -> None:
        """Toggling a source off stops its ingestion immediately; on it
        resumes watching with one poll right now, like at startup. Mail
        is stricter: off at boot means no watcher exists, so toggling on
        constructs the default one first (and wires its audit hook)."""
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
        if key == "mail_enabled":
            if value and server.mail is None:
                if server.inbox is not None and server.mail_store is not None:
                    settings = server.settings
                    if settings is not None:
                        server.mail = _default_mail_watch(
                            settings, server.inbox, server.mail_store)
                        _wire_mail_audit(server)
            if server.mail is not None:
                if value:
                    server.mail.start_polling()
                    threading.Thread(
                        target=_poll_mail_once, args=(server.mail,), daemon=True
                    ).start()
                else:
                    server.mail.stop_polling()

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
        page = render_touches(observed, agentdesk.__version__, datetime.now(),
                              inbox_count=self._inbox_waiting_count())
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
        self._evaluate_inbox(inbox)
        # The store's own clock, like every payload: cards never age by
        # two different clocks.
        now_ts = inbox.now_ts()
        page = render_inbox_page(inbox.waiting(), inbox.dismissed(), agentdesk.__version__, now_ts)
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _inbox_waiting_count(self) -> int:
        """The rail's inbox pill count, the same number every surface
        shows: waiting cards, evaluated, on the store's own clock."""
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            return 0
        self._maybe_briefs()
        self._evaluate_inbox(inbox)
        return len(inbox.waiting())

    def _send_inbox_count(self) -> None:
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        self._maybe_briefs()
        self._evaluate_inbox(inbox)
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
        body = self._read_json_body() or {}
        try:
            current = inbox.get(card_id)
        except UnknownCard as exc:
            self._send_json(404, {"error": str(exc)})
            return
        # Decide-once: only a waiting card can be decided. A second
        # accept used to be a harmless second stamp; mail made it
        # user-visible (a duplicate .eml in the outbox), so every kind
        # is guarded now. A replayed JSON decision answers 409 with the
        # card's current state; a replayed form post redirects back to
        # the inbox, which is what a double-click means.
        if current.status != STATUS_WAITING:
            if self._is_form_submit():
                self._send_redirect("/inbox")
                return
            self._send_json(409, {
                "error": "that card was already decided",
                "card": current.to_json(inbox.now_ts()),
            })
            return
        # The mail draft's effect lands before the acceptance is
        # recorded: if the outbox write fails, the card stays waiting
        # and the user can retry, rather than an accepted card having
        # written nothing.
        if decision == "accept" and isinstance(current.meta.get("mailDraft"), dict):
            if not self._write_mail_reply(current):
                return
        try:
            card = inbox.accept(card_id) if decision == "accept" else inbox.dismiss(card_id)
        except UnknownCard as exc:
            self._send_json(404, {"error": str(exc)})
            return
        if card.kind == "skill_proposal":
            self._on_skill_proposal_decided(card, decision)
        if card.kind == KIND_UPDATE_CONSENT:
            self._on_update_consent_decided(card, decision, body)
        if card.kind == KIND_MAIL_FOLLOW_UP:
            self._on_mail_follow_up_decided(card)
        if decision == "accept":
            self._on_fact_carried(card)
        self._audit(
            "inbox.approved" if decision == "accept" else "inbox.denied",
            target=card.id, detail=card.title,
        )
        self._inbox_action_response(card.to_json(inbox.now_ts()))

    def _inbox_edit(self, card_id: str) -> None:
        """Update the card's draft; the decision vocabulary calls it
        edited. An identical draft is a no-op, like the donor's edit."""
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        body = self._read_json_body() or {}
        draft = body.get("draft")
        if not isinstance(draft, str):
            self._send_json(400, {"error": 'expected {"draft": "..."}'})
            return
        try:
            card = inbox.get(card_id)
            if card.draft != draft:
                card = inbox.edit_draft(card_id, draft)
                self._audit("inbox.edited", target=card.id,
                            detail=plain_preview(draft) or "Edited the draft")
        except UnknownCard as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._inbox_action_response(card.to_json(inbox.now_ts()))

    def _inbox_snooze(self, card_id: str) -> None:
        """Hide the card for one hour or until the next morning. The
        store's own clock judges the return time, like every payload."""
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        body = self._read_json_body() or {}
        choice = body.get("choice")
        if choice not in SNOOZE_CHOICES:
            self._send_json(400, {"error": "expected a snooze choice: 1h or tomorrow"})
            return
        until = snooze_until(datetime.fromtimestamp(inbox.now_ts()).astimezone(),
                             str(choice))
        try:
            card = inbox.snooze(card_id, until)
        except UnknownCard as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._audit("inbox.snoozed", target=card.id,
                    detail="until " + datetime.fromtimestamp(until).strftime("%Y-%m-%d %H:%M"))
        self._inbox_action_response(card.to_json(inbox.now_ts()))

    def _inbox_more_info(self, card_id: str) -> None:
        """Attach the user's instruction; the card stays waiting for the
        decision, and a running snooze ends so it is visible again."""
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        body = self._read_json_body() or {}
        instruction = body.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            self._send_json(400, {"error": 'expected {"instruction": "..."}'})
            return
        instruction = instruction.strip()
        try:
            card = inbox.more_info(card_id, instruction)
        except UnknownCard as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._audit("inbox.more-info", target=card.id, detail=instruction[:200])
        self._inbox_action_response(card.to_json(inbox.now_ts()))

    def _inbox_action_response(self, payload: dict) -> None:
        """A no-JS form post lands back on the inbox; JSON gets JSON."""
        if self._is_form_submit():
            self._send_redirect("/inbox")
            return
        self._send_json(200, payload)

    def _send_activity_page(self) -> None:
        """The decision log: inbox decisions from the audit store, newest
        first. Non-decision rows stay in the CSV export, not here; the
        decision filter runs in the store so background polls cannot push
        a decision past the page's window."""
        entries = (
            audit_store.decision_entries(self.server.audit_conn, tuple(DECISIONS))  # type: ignore[attr-defined]
            if self.server.audit_conn is not None else []  # type: ignore[attr-defined]
        )
        page = render_activity_page(entries, agentdesk.__version__,
                                    inbox_count=self._inbox_waiting_count())
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    # -- memory: the page and its actions (ticket #42) --------------------

    def _send_memory_page(
        self,
        recall: list | None = None,
        query: str = "",
    ) -> None:
        """The memory page; with a recall preview when a query came in."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        page = render_memory_page(
            memory.all(), agentdesk.__version__, recall=recall, query=query,
            inbox_count=self._inbox_waiting_count(),
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _memory_add(self) -> None:
        """The page's one explicit creation path. The assistant and
        research paths may recall, never create."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        body = self._read_json_body() or {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            self._send_json(400, {"error": 'expected {"text": "..."}'})
            return
        fact = memory.add(text.strip(), source="page")
        self._memory_response(_fact_json(fact), status=201)

    def _memory_edit(self, fact_id: int | None) -> None:
        if fact_id is None:
            self._send_error_page(404, "Nothing here", "No fact lives at this address.")
            return
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        body = self._read_json_body() or {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            self._send_json(400, {"error": 'expected {"text": "..."}'})
            return
        try:
            fact = memory.edit(fact_id, text.strip())
        except UnknownFact as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._memory_response(_fact_json(fact))

    def _memory_delete(self, fact_id: int | None) -> None:
        if fact_id is None:
            self._send_error_page(404, "Nothing here", "No fact lives at this address.")
            return
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        try:
            memory.delete(fact_id)
        except UnknownFact as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._memory_response({"deleted": fact_id})

    def _memory_recall(self) -> None:
        """The preview: render the page with the ranked answers, best
        first, so the manager sees exactly what the assistant would ride."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        body = self._read_json_body() or {}
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            self._send_json(400, {"error": 'expected {"query": "..."}'})
            return
        query = query.strip()
        self._send_memory_page(recall=memory.recall(query), query=query)

    def _memory_response(self, payload: dict, status: int = 200) -> None:
        """A no-JS form post lands back on the memory page; JSON gets JSON."""
        if self._is_form_submit():
            self._send_redirect("/memory")
            return
        self._send_json(status, payload)

    # -- capabilities: the cached page and the one probing path (ticket #43)

    def _send_capabilities_page(self) -> None:
        """The capabilities page from the cache and the live table only.

        GET never probes the environment: gate cards render the cached
        results (or the never-tested state), and probing belongs to the
        explicit re-test POST. The cards age by the cache's own clock, so
        a stored result never reads fresher than it is."""
        cache = self.server.capabilities_cache
        if cache is None:
            self._send_json(503, {"error": "the capabilities cache is not available"})
            return
        excel = self.server.excel  # type: ignore[attr-defined]
        calendar = self.server.calendar  # type: ignore[attr-defined]
        page = render_capabilities_page(
            {key: cache.cached(key) for key, _number, _title in GATES},
            live_sources(self.server),
            excel.status() if excel is not None else None,
            calendar.status() if calendar is not None else None,
            self._endpoint_status(),
            agentdesk.__version__,
            now_ts=cache.clock(),
            mail=self._mail_capabilities(),
            inbox_count=self._inbox_waiting_count(),
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _mail_capabilities(self) -> dict | None:
        """The mail card's data: off, unconfigured, watching or error,
        read from the toggle and the watch in one place. None when the
        toggle does not exist (no settings store), so the card only
        appears when there is something honest to say."""
        server = self.server  # type: ignore[attr-defined]
        settings = server.settings
        if settings is None:
            return None
        if not self._source_allowed("mail_enabled"):
            return {
                "word": "off",
                "detail": "Mail digest is off in settings. Nothing is read.",
                "cause": "",
            }
        mail = server.mail
        if mail is None:
            return {
                "word": "unconfigured",
                "detail": "The mail watcher is not available on this machine.",
                "cause": "",
            }
        status = mail.status()
        state = status.get("state", "")
        folder = status.get("folder")
        cause = str(status.get("cause", ""))
        # The words are the watcher's own exported states, never
        # re-spelled literals (the capabilities page's house rule).
        if state == STATE_ERROR:
            return {"word": "error", "detail": cause or "The folder could not be read.", "cause": cause}
        if state == STATE_UNCONFIGURED or not folder:
            return {"word": "unconfigured", "detail": "No mail folder chosen yet.", "cause": ""}
        return {
            "word": "watching",
            "detail": f"Watches {folder}. Headers only; bodies are never read.",
            "cause": "",
        }

    def _capabilities_retest(self, gate_key: str) -> None:
        """The one probing path: run exactly one gate with the server's
        runner set and re-cache the answer. An unknown gate address is a
        404 before any runner is touched."""
        server = self.server  # type: ignore[attr-defined]
        cache = server.capabilities_cache
        if cache is None:
            self._send_json(503, {"error": "the capabilities cache is not available"})
            return
        runner = (server.gate_runners or {}).get(gate_key)
        if runner is None:
            self._send_error_page(404, "Nothing here", "No gate lives at this address.")
            return
        cached = cache.save_result(runner())
        if self._is_form_submit():
            self._send_redirect("/capabilities")
            return
        self._send_json(200, cached.to_json())

    def _on_fact_carried(self, card) -> None:
        """An accepted card may carry a fact in its meta ("fact": "...").
        The only non-page creation path. The fact's source names the
        card, and the audit row names that source, never the text."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return
        text = card.meta.get("fact")
        if not isinstance(text, str) or not text.strip():
            return
        fact = memory.add(text.strip(), source=f"inbox card {card.id}")
        self._audit("memory.fact", target=str(fact.id), detail=fact.source)

    # -- mail: the page, the watcher controls, the reply drafts -----------

    def _send_mail_page(self) -> None:
        """The mail page. Off (or unconstructed) is an honest state with
        an enable pointer, never a blank screen."""
        server = self.server  # type: ignore[attr-defined]
        mail = server.mail
        off_reason = ""
        if not self._source_allowed("mail_enabled"):
            off_reason = ("Mail digest is off. It stays off until you turn it on "
                          "in settings; nothing has been read.")
        elif mail is None:
            off_reason = ("The mail watcher is not available on this machine "
                          "(its store could not open).")
        view = mail.view() if (mail is not None and not off_reason) else None
        page = render_mail_page(agentdesk.__version__, view, off_reason=off_reason,
                                inbox_count=self._inbox_waiting_count())
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _mail_retest(self) -> None:
        """One poll right now: read the folder, file the deltas, evaluate."""
        server = self.server  # type: ignore[attr-defined]
        mail = server.mail
        if mail is None or not self._source_allowed("mail_enabled"):
            self._send_json(409, {"error": "Mail digest is off in settings.",
                                  "reconnect": "/settings"})
            return
        status = mail.retest()
        if server.inbox is not None:
            self._evaluate_inbox(server.inbox)
        if self._is_form_submit():
            self._send_redirect("/mail")
            return
        self._send_json(200, status)

    def _mail_draft(self, message_id: str) -> None:
        """The reply draft flow's opening move: a card from the message's
        headers (recipients, subject) wrapping the text the user typed.
        No message content goes into the card: the draft body is the
        user's own words, by construction and by rule."""
        server = self.server  # type: ignore[attr-defined]
        mail = server.mail
        if mail is None:
            self._send_json(503, {"error": "the mail watcher is not available"})
            return
        if server.inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        body = self._read_json_body() or {}
        text = body.get("body")
        if not isinstance(text, str) or not text.strip():
            self._send_json(400, {"error": 'expected {"body": "..."}: the reply text you want to send'})
            return
        message = next((m for m in mail.view()["messages"] if m.id == message_id), None)
        if message is None:
            self._send_json(404, {"error": f"no message {message_id} in the mail folder"})
            return
        try:
            recipients = reply_recipients(message, self_address=mail.self_address)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        subject = reply_subject(message.thread or message.subject)
        card = server.inbox.add(
            kind="suggestion",
            origin=("Your reply draft for this thread. Accepting writes the "
                    ".eml to the local outbox folder; sending it stays yours."),
            title=f"Reply draft: {subject}",
            body=f"To: {recipients}",
            action_label="Write to outbox",
            draft=text.strip(),
            meta={"mailDraft": {
                "messageId": message.id,
                "to": recipients,
                "subject": subject,
                "thread": message.thread,
            }},
        )
        self._audit("mail.draft", target=message.id, detail=f"To: {recipients}")
        self._evaluate_inbox(server.inbox)
        if self._is_form_submit():
            self._send_redirect("/mail")
            return
        self._send_json(201, card.to_json(server.inbox.now_ts()))

    def _write_mail_reply(self, card) -> bool:
        """Acceptance's effect, done first: write the threaded .eml into
        the outbox. False means the write failed and the response is
        already sent; the card stays waiting for a retry. A line break
        in the reply metadata (possible through the generic cards
        route, which stores meta as given) is the write_reply header
        injection guard speaking: refused with a 400, nothing written,
        the card untouched."""
        draft_info = card.meta.get("mailDraft")
        try:
            path = write_reply(
                self.server.outbox_dir,  # type: ignore[attr-defined]
                original_id=str(draft_info.get("messageId", "")),
                to=str(draft_info.get("to", "")),
                subject=str(draft_info.get("subject", "")),
                body=card.draft,
            )
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return False
        except OSError as exc:
            LOG.exception("outbox write failed")
            self._send_json(500, {"error": f"the reply file could not be written: {exc}"})
            return False
        # The audit row names the file, never the reply text.
        self._audit("mail.sent", target=path.name, detail=str(path))
        return True

    def _on_mail_follow_up_decided(self, card) -> None:
        """Either decision on a follow-up card ends the nagging: the
        thread is marked handled and no later poll re-mints its card."""
        server = self.server  # type: ignore[attr-defined]
        mail_store = server.mail_store
        if mail_store is None:
            return
        thread = card.meta.get("thread")
        if isinstance(thread, str) and thread:
            mail_store.mark_handled(thread)

    def _mail_folder_save(self) -> None:
        """The settings page's mail folder field. An empty value clears
        the choice; the watcher re-reads the folder right away."""
        server = self.server  # type: ignore[attr-defined]
        settings = server.settings
        if settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        body = self._read_json_body() or {}
        folder = body.get("folder")
        if not isinstance(folder, str):
            self._send_json(400, {"error": 'expected {"folder": "..."}'})
            return
        settings.set("mail_folder", folder.strip())
        if server.mail is not None and folder.strip():
            server.mail.retest()
        if self._is_form_submit():
            self._send_redirect("/settings")
            return
        self._send_json(200, {"key": "mail_folder", "value": folder.strip()})

    def _on_update_consent_decided(self, card, decision: str, body: dict) -> None:
        """Accepting applies the held update; the "for this plugin"
        choice also records the (plugin, scope) allow so an identical
        re-ask never re-prompts. A widened scope is a different key and
        always re-asks."""
        server = self.server  # type: ignore[attr-defined]
        plugins = server.plugins
        if plugins is None:
            return
        plugin_id = str(card.meta.get("pluginId", ""))
        if not plugin_id:
            return
        if decision == "accept":
            if _flag(body, "forPlugin", "for_plugin"):
                server.consents.allow(plugin_id, str(card.meta.get("scope", "")))
            try:
                applied = plugins.consent(plugin_id)
            except PluginError as exc:
                # The held update may already be gone (uninstalled, or
                # consented through the plugin screen): the card's
                # decision stands; nothing is silently re-held.
                LOG.warning("update consent apply failed: %s", exc)
                return
            # Every successful apply writes the lifecycle row, whichever
            # path applied it, so the touches badge cannot lie by flow.
            self._audit("plugin.consent", target=plugin_id,
                        detail=_plugin_audit_detail("consent", applied))

    def _evaluate_inbox(self, inbox: InboxStore) -> None:
        """One evaluation with the audit hook: a snooze that returns is
        logged as pending, never a silent reappearance."""

        def on_return(card) -> None:
            self._audit("inbox.pending", target=card.id,
                        detail=f"{card.title} snooze returned")

        inbox_service.evaluate(inbox, _local_now(), on_snooze_return=on_return,
                               **self._budget_values())

    def _audit(self, action: str, target: str = "", detail: str = "") -> None:
        """The one inbox/plugin path into the append-only audit store."""
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(self.server.audit_conn, action,
                               target=target, detail=detail)

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
            result = plugins.install(body["zip_path"], source=body.get("source", "zip"))
            self._audit("plugin.install", target=str(result.get("id", "")),
                        detail=f"v{result.get('version', '')} pilot install")
            self._send_json(200, result)
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
        result = actions[action]()
        if (action == "update" and isinstance(result, dict)
                and result.get("status") == "pending-consent"):
            result = self._hold_update_for_consent(plugins, plugin_id, result)
        self._audit(f"plugin.{action}", target=plugin_id,
                    detail=_plugin_audit_detail(action, result))
        self._send_json(200, result)

    def _hold_update_for_consent(self, plugins: PluginRuntime, plugin_id: str,
                                 result: dict) -> dict:
        """A widened update holds in the runtime; the user meets it as an
        update_consent card. The consents check sits right here, where
        the card would be created: an allow recorded for exactly this
        (plugin, scope) pair answers the re-ask without prompting, and a
        widened further scope (a different key) still creates the card."""
        server = self.server  # type: ignore[attr-defined]
        scope = "; ".join(result.get("added_scopes", []))
        try:
            version = str(plugins.pending_diff(plugin_id).get("version", ""))
        except PluginError:
            version = ""
        if server.consents.allowed(plugin_id, scope):
            applied = plugins.consent(plugin_id)
            self._audit("plugin.consent", target=plugin_id,
                        detail=_plugin_audit_detail("consent", applied))
            self._audit("inbox.approved", target=plugin_id,
                        detail=f"{plugin_id} update pre-approved for this plugin")
            return {"applied": True, "version": applied.get("version"),
                    "auto_consented": True}
        inbox = server.inbox
        if inbox is not None:
            card = inbox.add(
                kind=KIND_UPDATE_CONSENT,
                origin=(f"The update widens what {plugin_id} may do; it "
                        "holds until you decide."),
                title=f"{plugin_id} {version} asks for more access",
                body=f"New access: {scope}",
                action_label="Allow update",
                meta={"pluginId": plugin_id, "scope": scope, "version": version},
            )
            self._audit("inbox.pending", target=card.id,
                        detail=f"{plugin_id} update waiting: adds {scope}"[:200])
            self._evaluate_inbox(inbox)
        return result

    def _plugin_widget(self, card: dict) -> Widget:
        """One installed plugin's dashboard card: pilot badge, amber state.

        The amber treatment matches the built-in widgets, and every
        plugin-controlled string is escaped here: the shell renders widget
        bodies as authored HTML, so this is the boundary. A bound
        ui-schema payload (metrics the host computed) draws the fresh
        body; without one the card falls back to the version line."""
        status = FRESH if card.get("freshness") == "fresh" else ATTENTION
        plugin_id = html.escape(str(card["id"]))
        cause = html.escape(str(card.get("cause") or "data source has not run"))
        file_name = html.escape(str(card.get("file") or "the data source"))
        version = html.escape(str(card["version"]))
        payload = card.get("payload") or {}
        elements = payload.get("elements") if isinstance(payload, dict) else None
        if status == FRESH and elements:
            parts = []
            for element in elements:
                if not isinstance(element, dict):
                    continue
                if element.get("kind") == "metric":
                    parts.append('<p class="w-big">'
                                 + html.escape(str(element.get("value", "")))
                                 + "</p>")
                    label = str(element.get("label", "")).strip()
                    if label:
                        parts.append('<p class="w-note">'
                                     + html.escape(label) + "</p>")
                elif element.get("kind") == "text":
                    parts.append('<p class="w-note">'
                                 + html.escape(str(element.get("text", "")))
                                 + "</p>")
            body = "".join(parts) or (
                '<p class="w-big">' + version + '</p><p class="w-note">'
                "reading " + file_name + "</p>")
            extra = ""
        elif status == FRESH:
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
                "payload": plugins.widget_payload(record["id"]),
                "pending_diff": record.get("pending_diff"),
            })
        return out

    # -- the plugins page and its registry bridge --------------------------

    def _registry_root_for_request(self) -> tuple[object, str]:
        """(root, origin): which registry checkout this request browses.

        An injected root wins (a Path pins it, an empty string forces
        the unavailable state); otherwise settings, then the
        environment, then this app's own checkout, in that order.
        """
        override = getattr(self.server, "registry_root", None)  # type: ignore[attr-defined]
        if isinstance(override, str) and not override.strip():
            return None, "none"
        if override:
            return Path(override), "pinned"
        return registry_source.resolve_registry_root(self.server.settings)  # type: ignore[attr-defined]

    def _registry_listing_for_request(self) -> dict:
        root, origin = self._registry_root_for_request()
        listing = registry_source.registry_listing(root)
        listing["origin"] = origin
        if listing.get("ok"):
            self._audit("registry.read", target="registry",
                        detail=f"{len(listing.get('plugins', []))} plugins from {origin}")
        return listing

    def _send_plugins_page(self, notice: str = "") -> None:
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        records = plugins.list_records() if plugins is not None else []
        listing = self._registry_listing_for_request()
        page = render_plugins_page(
            records, listing, str(listing.get("origin", "none")),
            agentdesk.__version__, notice=notice,
            inbox_count=self._inbox_waiting_count())
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _plugins_page_action(self, path: str) -> None:
        """One lifecycle action posted from the plugins page's own forms.

        The same runtime methods the JSON API drives, answered with a
        redirect back to the page; a refusal rides back as the notice
        line instead of a raw error page, because the form came from a
        human clicking a button.
        """
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            self._send_error_page(503, "Plugins unavailable",
                                  "No plugin runtime is configured.")
            return
        parts = [part for part in path.split("/") if part]
        plugin_id, action = unquote(parts[1]), parts[2]
        body = self._read_json_body() or {}
        actions = {
            "enable": lambda: plugins.enable(plugin_id),
            "disable": lambda: plugins.disable(plugin_id),
            "rollback": lambda: plugins.rollback(plugin_id),
            "uninstall": lambda: plugins.uninstall(plugin_id),
            "retest": lambda: plugins.retest(plugin_id),
            "consent": lambda: plugins.consent(plugin_id),
            "purge-data": lambda: plugins.purge_data(
                plugin_id, body.get("confirmation")),
        }
        if action not in actions:
            self._send_error_page(404, "Nothing here",
                                  "No action lives at this address.")
            return
        try:
            actions[action]()
        except PluginError as exc:
            self._send_redirect(f"/plugins?notice={quote(str(exc))}")
            return
        self._audit(f"plugin.{action}", target=plugin_id,
                    detail=f"page action {action}")
        self._send_redirect("/plugins")

    def _registry_install(self) -> None:
        """Install one pinned release from the registry checkout.

        The registry machinery owns verification (pin resolution, tag
        extraction, tree digest, the shared validator); the runtime owns
        the versioned install, pilot badge and consent flow. Forms get a
        redirect with the outcome as the notice line; JSON callers get
        the record.
        """
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            self._registry_install_refused("plugins:unavailable",
                                           "no plugin runtime is configured")
            return
        body = self._read_json_body() or {}
        plugin_id = str(body.get("id", "")).strip()
        version = str(body.get("version", "")).strip() or None
        if not plugin_id:
            self._registry_install_refused("bad-request",
                                           'expected {"id": "...", "version": "..."}',
                                           status=400)
            return
        root, _origin = self._registry_root_for_request()
        if root is None:
            self._registry_install_refused(
                "registry:not-configured",
                "No plugin registry is configured. Set one in Settings.")
            return
        try:
            with tempfile.TemporaryDirectory(prefix="agentdesk-registry-") as tmp:
                staged = registry_source.stage_registry_install(
                    root, plugin_id, version=version,
                    sha256=body.get("sha256"), staging_dir=Path(tmp))
                result = plugins.install(staged["dir"], source="registry")
        except (RegistryError, RegistryIndexError) as exc:
            self._registry_install_refused(
                getattr(exc, "code", "install:refused"), str(exc))
            return
        except PluginError as exc:
            self._registry_install_refused(exc.code, str(exc), exc.status)
            return
        self._audit("plugin.install", target=plugin_id,
                    detail=f"registry v{result.get('version', '')} pinned install")
        if self._is_form_submit():
            self._send_redirect(f"/plugins?notice={quote(
                'Installed ' + plugin_id + ' v' + str(result.get('version', '')) + '.')}")
            return
        self._send_json(200, result)

    def _registry_install_refused(self, code: str, message: str,
                                  status: int = 409) -> None:
        if self._is_form_submit():
            self._send_redirect(f"/plugins?notice={quote(message)}")
            return
        self._send_json(status, {"error": code, "message": message})

    def _registry_path_save(self) -> None:
        """Save or clear the registry checkout path (the settings form)."""
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        body = self._read_json_body() or {}
        chosen = str(body.get("path", "")).strip()
        if chosen and not (Path(chosen) / "index.json").is_file():
            self._send_redirect(
                "/plugins?notice=" + quote(
                    "That folder has no registry index (index.json). "
                    "Nothing was saved."))
            return
        settings.set(registry_source.SETTINGS_KEY, chosen)
        self._audit("settings.registry", target="registry_path",
                    detail="cleared" if not chosen else "updated")
        self._send_redirect("/plugins")

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
        answers = body.get("answers")
        if answers is None and self._is_form_submit():
            answers = self._answers_from_form(body, session.questions,
                                              session.answers)
        if not answers:
            answers = {
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
        if getattr(self, "_close_with_response", False):
            # The request leaves the connection unusable (its body was
            # beyond the drain cap, or refused before the drain): the
            # answer names the close (send_header also flips
            # close_connection).
            self.send_header("Connection", "close")


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
    consents: ConsentStore | None = None,
    memory_store: MemoryStore | None = None,
    capabilities_cache: CapabilitiesCache | None = None,
    gate_runners: GateRunners | None = None,
    mail: MailWatch | None = None,
    mail_store: MailStore | None = None,
    outbox_dir=None,
    registry_root=None,
) -> AgentDeskServer:
    """Bind the app to the loopback and nothing else.

    A non-loopback host is a hard error, not a warning: the skeleton must
    be incapable of listening on 0.0.0.0 even by misconfiguration. When no
    port is given, the preferred port is tried once and an ephemeral port
    is the fallback, so the auth URL always names the port that actually
    opened. The excel watch, the calendar bridge and the audit store
    default to real ones over the user data directory; tests pass their
    own. The mail watcher is constructed only when the (default-off)
    toggle is on: off means the watcher does not exist.
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
    if plugins is None:
        plugins = _default_plugins()
    if wizard_store is None:
        wizard_store = _default_wizard_store()
    if memory_store is None:
        memory_store = _default_memory_store()
    if capabilities_cache is None:
        capabilities_cache = _default_capabilities_cache()
    if gate_runners is None:
        gate_runners = _default_gate_runners()
    if mail_store is None:
        mail_store = _default_mail_store()
    if mail is None and inbox_store is not None and mail_store is not None \
            and bool(settings_store.get("mail_enabled")):
        mail = _default_mail_watch(settings_store, inbox_store, mail_store)

    def construct(bind_port: int) -> AgentDeskServer:
        return AgentDeskServer(
            (resolved, bind_port),
            sessions=sessions,
            excel=excel,
            pick_workbook=pick_workbook,
            calendar=calendar,
            llm=llm,
            audit_conn=audit_conn,
            llm_endpoint=llm_endpoint,
            llm_model=llm_model,
            inbox_store=inbox_store,
            activity_log=activity_log,
            skill_store=skill_store,
            settings_store=settings_store,
            plugins=plugins,
            pick_calendar=pick_calendar,
            wizard_store=wizard_store,
            consents=consents,
            memory_store=memory_store,
            capabilities_cache=capabilities_cache,
            gate_runners=gate_runners,
            mail=mail,
            mail_store=mail_store,
            outbox_dir=outbox_dir,
            registry_root=registry_root,
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
    if server.mail is not None:
        server.mail.audit_hook = hook
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


def _wire_mail_audit(server: AgentDeskServer) -> None:
    """The mail watcher's audit hook, for watches constructed after boot
    (the mail toggle turning on mid-session). Read-only polls say so;
    there is nothing here that could log message content."""
    if server.audit_conn is None or server.mail is None:
        return
    conn = server.audit_conn
    server.mail.audit_hook = lambda action, target, status="ok": audit_store.record(
        conn, action, target=target, status=status)


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


def _default_memory_store() -> MemoryStore | None:
    """Facts over the persistent store (they outlive a restart by
    design), or None when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "memory.sqlite3", check_same_thread=False)
        return MemoryStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("memory store unavailable")
        return None


def _default_outbox_dir() -> Path:
    """Where accepted reply drafts land as .eml files: a folder beside
    the other data, AGENTDESK_DATA moves it like everything else."""
    return default_data_dir() / "outbox"


def _default_mail_store() -> MailStore | None:
    """Handled-thread markers over the persistent store, or None when it
    cannot open. Messages are never stored: the folder is the source."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "mail.sqlite3", check_same_thread=False)
        return MailStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("mail store unavailable")
        return None


def _default_mail_watch(settings_store, inbox_store, mail_store) -> MailWatch | None:
    """The real mail watcher: settings decide the folder on every poll,
    so a folder saved in the app applies without a restart."""
    try:
        return MailWatch(
            inbox=inbox_store,
            store=mail_store,
            folder_provider=lambda: settings_store.get("mail_folder"),
        )
    except (OSError, sqlite3.Error):
        LOG.exception("mail watcher unavailable")
        return None


def _default_capabilities_cache() -> CapabilitiesCache | None:
    """Cached gate results over the persistent store, or None when it
    cannot open. A missing cache degrades the page to never-tested
    cards, never to a fabricated answer."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "capabilities.sqlite3", check_same_thread=False)
        return CapabilitiesCache(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("capabilities cache unavailable")
        return None


def _default_gate_runners() -> GateRunners:
    """The real probe bundle over a workdir beside the other data.

    Building the set probes nothing (plain closures over the adapters),
    so carrying it from startup costs nothing and page renders stay
    side-effect free; the gates run only when a re-test POST calls one."""
    return default_gate_runners(default_data_dir() / "probe-run")


def _default_plugins() -> PluginRuntime | None:
    """The plugin runtime over the user data directory, or None when it
    cannot open. Installed plugins, their data and the ${workspace} root
    each get their own folder under the same data dir the stores use, so
    the delete-folder uninstall story stays true."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        return PluginRuntime(
            plugins_dir=data_dir / "plugins",
            data_dir=data_dir / "plugin-data",
            workspace_dir=data_dir / "workspace",
        )
    except OSError:
        LOG.exception("plugin runtime unavailable")
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
    mail = server.mail
    if mail is not None and allowed("mail_enabled"):
        mail.start_polling()
        threading.Thread(target=_poll_mail_once, args=(mail,), daemon=True).start()
    plugins = server.plugins
    if plugins is not None:
        # Attached plugin data sources resume their hourly loops; each
        # already polled once at attach, so no immediate poll is needed.
        plugins.start_widget_polls()


def _poll_mail_once(watch: MailWatch) -> None:
    """One immediate read so the first inbox look already sees the digest."""
    try:
        watch.poll()
    except Exception:  # noqa: BLE001 - startup must not crash on a poll
        LOG.exception("mail startup poll failed")


def _poll_calendar_once(bridge) -> None:
    """One immediate read so the first page load already knows the day."""
    try:
        bridge.poll()
    except Exception:  # noqa: BLE001 - startup must not crash on a poll
        LOG.exception("calendar startup poll failed")
