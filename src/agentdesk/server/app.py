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
from agentdesk.assistant import audit as audit_store
from agentdesk.briefs import generate_briefs
from agentdesk.assistant import threadlog
from agentdesk.assistant.context import build_context
from agentdesk.assistant.loop import assistant_reply, research
from agentdesk.calendar.watcher import CalendarBridge, default_read_calendar
from agentdesk.excel import store as excel_store
from agentdesk.excel.watcher import ExcelWatch, default_adapters
from agentdesk.inbox import service as inbox_service
from agentdesk.inbox.core import UnknownCard
from agentdesk.inbox.store import InboxStore
from agentdesk.llm import env_chat, env_config
from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.service import Consolidator
from agentdesk.repetition.skills import SkillError, SkillStore
from agentdesk.server import pages
from agentdesk.server.auth import SessionStore, session_id_from_cookie
from agentdesk.server.commitments import render_commitments_widget
from agentdesk.server.inbox_view import render_inbox_page
from agentdesk.server.research import render_assistant_page, render_research_widget
from agentdesk.server.settings_view import render_settings_page
from agentdesk.server.touches import render_touches
from agentdesk.server.core import (
    PREFERRED_PORT,
    SourceStatus,
    default_sources,
)
from agentdesk.server.demo import demo_widgets
from agentdesk.server.guard import check_request
from agentdesk.server.health import health_payload
from agentdesk.server.sales import render_sales_disabled, render_sales_widget
from agentdesk.settings import SettingsStore, ensure_schema as ensure_settings_schema

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
        llm=None,
        audit_conn=None,
        llm_endpoint: str | None = None,
        llm_model: str | None = None,
        inbox_store: InboxStore | None = None,
        activity_log: ActivityLog | None = None,
        skill_store: SkillStore | None = None,
        settings_store: SettingsStore | None = None,
    ) -> None:
        self.sessions = sessions
        self.sources = sources if sources is not None else default_sources()
        self.excel = excel
        self.pick_workbook = pick_workbook
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
        elif path == "/audit/export.csv":
            self._send_audit_csv()
        elif path == "/what-this-touches":
            self._send_touches_page()
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
        # Drain the request body up front: an unread body on a keep-alive
        # connection would be parsed as the next request.
        self._raw_body = self._drain_body()
        path, _, _query = self.path.partition("?")
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
        common = {
            "llm": server.llm,
            "audit_conn": server.audit_conn,
            "endpoint": server.llm_endpoint,
            "model": server.llm_model,
        }
        if summary_mode:
            return research(question, context, **common)
        return assistant_reply(question, context, **common)

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

    def _send_dashboard(self) -> None:
        now = datetime.now()
        demo = {w.id: w for w in demo_widgets()}
        widgets: list = []
        excel = self.server.excel  # type: ignore[attr-defined]
        sales_status = excel.status() if excel is not None else None
        if not self._source_allowed("excel_enabled"):
            widgets.append(render_sales_disabled(now))
        elif sales_status is not None and sales_status.get("configured"):
            widgets.append(render_sales_widget(sales_status))
        else:
            widgets.append(demo["sales-24h"])
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if not self._source_allowed("calendar_enabled"):
            widgets.append(render_commitments_widget({"state": "disabled"}, now))
        elif calendar is not None:
            commitments = render_commitments_widget(calendar.status(), now)
            widgets.append(commitments if commitments is not None else demo["key-commitment"])
        else:
            widgets.append(demo["key-commitment"])
        audit_conn = self.server.audit_conn  # type: ignore[attr-defined]
        # The writer records the action as "llm.research" (assistant/loop.py);
        # querying anything else makes the stamp never show the last answer.
        last_answer = audit_store.last_ok_ts(audit_conn, "llm.research") if audit_conn is not None else None
        widgets.append(render_research_widget(last_answer, now))
        widgets.append(demo["region-mix"])
        inbox = self.server.inbox  # type: ignore[attr-defined]
        skills = self.server.skills.active() if self.server.skills is not None else []  # type: ignore[attr-defined]
        page = pages.render_dashboard(
            widgets,
            agentdesk.__version__,
            _greeting(now),
            now.strftime("%A, %d %B, %H:%M. "),
            inbox_count=len(inbox.waiting()) if inbox is not None else 0,
            skills=skills,
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
        values = server.settings.all() if server.settings is not None else {}
        page = render_settings_page(
            entries, skills, histories, agentdesk.__version__,
            settings_values=values, endpoint_status=self._endpoint_status(),
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _endpoint_status(self) -> dict:
        """The read-only indicator: configured or not, and the truth about
        the last call. A down endpoint shows degraded, never a false green."""
        server = self.server  # type: ignore[attr-defined]
        configured = bool(server.llm_endpoint)
        last = "never"
        if server.audit_conn is not None:
            for entry in audit_store.entries(server.audit_conn, 20):
                if entry["action"].startswith("llm."):
                    last = entry["status"]
                    break
        return {"configured": configured, "last": last}

    def _send_settings_values(self) -> None:
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        self._send_json(200, settings.all())

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
        answer = research(
            skill["prompt"], context, llm=server.llm, audit_conn=server.audit_conn,
            endpoint=server.llm_endpoint, model=server.llm_model,
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
        llm=None,
        audit_conn=None,
        llm_endpoint: str | None = None,
        llm_model: str | None = None,
        inbox_store: InboxStore | None = None,
        activity_log: ActivityLog | None = None,
        skill_store: SkillStore | None = None,
        settings_store: SettingsStore | None = None,
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
    if calendar is None:
        calendar = _default_calendar_bridge()
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
    if settings_store is None:
        settings_store = _default_settings_store()

    def construct(bind_port: int) -> AgentDeskServer:
        return AgentDeskServer(
            (resolved, bind_port), sessions, sources, excel, pick_workbook,
            calendar, llm, audit_conn, llm_endpoint, llm_model, inbox_store,
            activity_log, skill_store, settings_store,
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
    at runtime reports into the one append-only store.
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
        endpoint, _key, model = env_config()
        inner_llm = server.calendar.llm

        def audited_llm(prompt: str) -> str:
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
