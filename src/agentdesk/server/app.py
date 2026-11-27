"""The hardened localhost HTTP server for the dashboard.

One threading server, loopback only, every request passing the same gate:
Origin/Host validation, then session auth, then routing. GETs serve the
shell, health and static assets; POSTs drive state changes (workbook
picker, registration, re-test). There is no second entry path; the
WebSocket upgrades of later tickets must call the same check_request and
session validation before handshake.
"""

import html
import http.client
import json
import logging
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import parse_qs, quote, unquote

import agentdesk
from agentdesk.agents.registry import ROSTER, find_agent
from agentdesk.agents.runner import (
    BRIEF_MAX_CHARS,
    FEEDBACK_MAX_CHARS,
    ENDPOINT_OFF_CAUSE,
    STATUS_OK as AGENT_STATUS_OK,
    endpoint_off_run,
    feedback_transcript,
    run_agent,
)
from agentdesk.agents.store import AgentRunStore
from agentdesk.assistant import audit as audit_store
from agentdesk.briefs import generate_briefs
from agentdesk.assistant import threadlog
from agentdesk.assistant.context import build_context
from agentdesk.assistant.loop import STATUS_OK, assistant_reply, research
from agentdesk.assistant.research_store import ResearchStore
from agentdesk.calendar.core import (
    CalendarUnreadable,
    parse_calendar_document,
)
from agentdesk.calendar.watcher import (
    STATE_EMPTY,
    CalendarBridge,
    default_calendar_candidates,
)
from agentdesk.capabilities import GATES, CapabilitiesCache, GateRunners, default_gate_runners
from agentdesk.consents import ConsentStore
from agentdesk.excel.watcher import ExcelWatch, default_adapters
from agentdesk.inbox import service as inbox_service
from agentdesk.inbox.core import (
    KIND_MAIL_FOLLOW_UP,
    KIND_MEMORY_DRAFT,
    KIND_UPDATE_CONSENT,
    STATUS_WAITING,
    UnknownCard,
)
# Aliased: agentdesk.assistant.context.build_context already owns this
# name in this module, and it is the one the model turn calls.
from agentdesk.insight.context import build_context as build_insight_context
from agentdesk.insight.preferences import PreferenceStore, PreferencesError, changed
from agentdesk.insight.press import draft_reply, press_from_form, press_to_fields
from agentdesk.insight.reading import press_label
from agentdesk.insight.service import attach_cards
from agentdesk.insight.types import InsightError
from agentdesk.inbox.snooze import SNOOZE_CHOICES, snooze_until
from agentdesk.inbox.store import InboxStore
from agentdesk.keys import health
from agentdesk.keys.migrate import MIGRATED_CONNECTION_IDS, migrate_legacy_settings
from agentdesk.keys.presets import PRESETS, preset_for
from agentdesk.keys.resolve import (
    DEFAULT_JOB,
    JOBS,
    JOB_LABELS,
    JobUnbound,
    Resolution,
    resolve_job,
)
from agentdesk.keys.secrets import KeychainSecrets
from agentdesk.keys.store import (
    Connection,
    JobBinding,
    KeysStore,
    UnknownConnection,
    mask_key,
)
from agentdesk.layout import (
    BUILTIN_KEYS as BUILTIN_LAYOUT_KEYS,
    LayoutError,
    LayoutStore,
    parse_layout,
    resolved_layout,
)
from agentdesk.feeder.platform import current_platform, default_collectors
from agentdesk.feeder.runner import OutlookFeeder
from agentdesk.ledger import Ledger, LedgerError, may_act
from agentdesk.ledger import undo as ledger_undo
from agentdesk.engine import (
    ConnectionSpec,
    MAX_ACTIONS_PER_TURN,
    TurnResult,
    available as engine_available,
    redact as engine_redact,
    run_turn as engine_run_turn,
    tool_by_name as engine_tool_by_name,
)
from agentdesk.mail.core import reply_recipients, reply_subject, write_reply
from agentdesk.mail.store import MailStore
from agentdesk.mail.watcher import (
    STATE_ERROR,
    STATE_UNCONFIGURED,
    MailWatch,
)
from agentdesk.locking import store_lock
from agentdesk.llm import (
    LlmUnavailable,
    NO_ENDPOINT_CAUSE,
    REQUEST_TIMEOUT_S,
    base_url_problem,
    chat,
    chat_client,
    effective_llm_config,
    env_chat,
    env_config,
    settings_chat,
)
from agentdesk.presentations.artifact import deck_artifact
from agentdesk.presentations.packs import load_packs
from agentdesk.presentations.tools import (
    ToolError,
    resolve_in_root,
    run_tool,
    tool_catalog,
)
from agentdesk.presentations.research import (
    FETCH_TIMEOUT_S,
    RESULT_LIMIT,
    as_sources,
    fetch_sources,
)
from agentdesk.presentations.pipeline import (
    call_model,
    fill_cause,
    gather,
    parse_plan,
    plan_prompt,
    receipt_lines,
    run_fill,
    timeout_seconds,
)
from agentdesk.memory.crypto import MemoryEncryptedError
from agentdesk.memory.embed import (
    settings_embedder,
)
from agentdesk.memory.extract import (
    FACT_KINDS,
)
from agentdesk.memory.service import build_facts_block
from agentdesk.memory.store import MemoryStore, key_file_path, read_key_file
from agentdesk.memory import loop as memory_loop
from agentdesk.memory import profile_review
from agentdesk.memory.profile import (
    MAX_TOPICS,
    LearnedProfileStore,
    merged_topics,
)
from agentdesk.plugins.config import MAX_UPLOAD_BYTES
from agentdesk.plugins.execute import PluginWidgetRunner
from agentdesk.plugins.html import element_html
from agentdesk.plugins.runtime import PluginError, PluginRuntime
from agentdesk.registry import source as registry_source
from agentdesk.registry.index import RegistryIndexError
from agentdesk.registry.install import RegistryError
from agentdesk.registry.publish import publish_to_registry
from agentdesk.repetition import curator as skill_curator
from agentdesk.repetition import refine as skill_refine
from agentdesk.peers.discovery import (
    PREFERRED_ANNOUNCE_PORT,
    DiscoveryService,
)
from agentdesk.peers.store import PeerStore
from agentdesk.registry.install import RegistryError
from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.cluster import cluster_requests, pattern_hash
from agentdesk.repetition.service import Consolidator, PROPOSAL_THRESHOLD
from agentdesk.recommend.builder import RecommendationBuilder
from agentdesk.repetition.skills import SkillError, SkillStore
from agentdesk.server.audit_view import render_audit_page
from agentdesk.server.agents_view import render_agents_page
from agentdesk.server import pages
from agentdesk.server import routes
from agentdesk.server.auth import SessionStore, session_id_from_cookie
from agentdesk.server.capabilities_view import render_capabilities_page
from agentdesk.server.commitments import (
    render_commitments_unavailable,
    render_commitments_widget,
)
from agentdesk.server.dashboard_state import build_dashboard_state
from agentdesk.server.inbox_view import render_inbox_page
from agentdesk.server.mail_view import render_mail_page
from agentdesk.server.research import (
    render_assistant_page,
    render_research_disabled,
    render_research_widget,
)
from agentdesk.server.settings_view import (
    joined_job_labels,
    mask_llm_key,
    render_connection_delete_warning,
    render_settings_page,
)
from agentdesk.server.wizard_view import (
    approval_summary,
    render_wizard_page,
)
from agentdesk.wizard.core import (
    WizardCompiler,
    WizardError,
    WizardStore,
    merge_answers,
    normalize_answers,
    questions_for_answers,
    resolve_choice,
)
from agentdesk.server.touches import render_touches
from agentdesk.server.core import (
    ATTENTION,
    SPA_DIR,
    FRESH,
    PREFERRED_PORT,
    SRC_CALENDAR,
    SRC_EXCEL,
    SRC_RESEARCH,
    STATUS_CONNECTED,
    STATUS_NOT_CONNECTED,
    STATUS_SAMPLE,
    Freshness,
    SourceStatus,
    _active_version_dir,
    plain_preview,
)
from agentdesk.agentloop import AgentLoop, LoopContext, Step, register_step
from agentdesk.agentloop.loop import (
    STEP_ORDER_CURATOR,
    STEP_ORDER_ENGINE,
    STEP_ORDER_LEARN_TOPICS,
    STEP_ORDER_PROFILE_REVIEW,
    STEP_ORDER_RANK,
    STEP_ORDER_RECOMMEND,
    STEP_ORDER_SKILLS,
    STEP_ORDER_UPDATE,
    _curator_enabled,
    _run_curator,
    _run_skills,
    _skills_enabled,
)
from agentdesk.recommend.rank import rank_enabled, rank_step
from agentdesk.server.demo import Widget
from agentdesk.server import demo_data
from agentdesk.server.guard import GuardVerdict, check_request
from agentdesk.server.memory_api import MemoryApiMixin
from agentdesk.server.peers_api import PeersApiMixin
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

# The skill feedback queue (spec 016 section 6.6): each skillfb:<id> latch
# holds at most 5 items, each 1000 characters or fewer.
SKILL_FEEDBACK_MAX_ITEMS = 5
SKILL_FEEDBACK_MAX_CHARS = 1000

# The setup upload carries the file's bytes, so it drains under its own
# cap; every other POST keeps the bound above.
_PLUGIN_UPLOAD_PATH = re.compile(r"^/api/plugins/[^/]+/instances/[^/]+/upload/")

# A setup refusal that is not a plain 400: a dialog that cannot open is
# the server's problem, and an oversized body is its own status.
_SETUP_ERROR_STATUS = {"config:picker-unavailable": 503, "config:too-large": 413}

# The wizard's describing screen before any session exists: the shape
# render_wizard_page renders for GET /wizard and for a wordless POST to
# /wizard/start (the dashboard button) alike.
WIZARD_DESCRIBING_PAYLOAD = {
    "id": "new",
    "state": "describing",
    "description": "",
    "questions": [],
    "draft": {},
    "ui_schema": None,
    "sample_rows": [],
}

# A body over MAX_BODY_BYTES is refused but still drained, so a keep-alive
# connection survives the refusal; this is the hard bound on that draining.
# Beyond it the server answers and closes instead of reading unboundedly:
# keeping a localhost connection is never worth reading gigabytes.
MAX_DRAIN_BYTES = 8 * MAX_BODY_BYTES

def body_drain_plan(length: int, limit: int = MAX_BODY_BYTES) -> str:
    """What to do with a request body of this declared length: 'skip'
    (nothing declared), 'stash' it for the route, 'discard' it (over the
    stash limit but within the hard cap), or 'close' (beyond the cap;
    the answer goes out with Connection: close). The limit is where the
    stash stops; the hard cap below does not move with it."""
    if length <= 0:
        return "skip"
    if length <= limit:
        return "stash"
    if length <= MAX_DRAIN_BYTES:
        return "discard"
    return "close"

# The committed SPA build, emitted by frontend/ (npm run build) directly
# into this folder and committed, so the double-click launcher serves it
# with zero node involvement. When index.html is missing (a source
# checkout without a build), "/" falls back to the server-rendered
# dashboard; tests re-point this path to simulate either case.
_MARKETPLACE_SINGLE = {"search", "installed", "publishers", "studio", "admin",
                      "trust"}
_MARKETPLACE_SECOND = {"category", "plugin", "pack", "publisher", "manage"}

def _known_marketplace_path(path: str) -> bool:
    """Mirror the SPA parser so a typo gets an honest 404, not a 200."""
    clean = path.split("?", 1)[0].rstrip("/") or "/"
    if clean == "/marketplace":
        return True
    if not clean.startswith("/marketplace/"):
        return False
    rest = [part for part in clean[len("/marketplace/"):].split("/") if part]
    if len(rest) == 1:
        return rest[0] in _MARKETPLACE_SINGLE
    if len(rest) == 2:
        head, second = rest
        if head in _MARKETPLACE_SECOND:
            return bool(second)
        return False
    return len(rest) == 3 and rest[0] == "plugin" and bool(rest[1]) \
        and rest[2] == "manage"

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
    """The time-of-day greeting for a timestamp.

    The boundaries are the timestamp's own hours: before 12 is morning, before 18
    afternoon, otherwise evening.
    """
    if now.hour < 12:
        return "Good morning"
    if now.hour < 18:
        return "Good afternoon"
    return "Good evening"

def _setup_decisions(state) -> list[dict]:
    """The setup rows the Decisions card shows before any recommendation.

    These are the same four checks the SPA makes, in the same order and words:
    the desk cannot recommend anything until it has a workbook, a calendar and
    a working endpoint, and it says which of those is missing rather than
    showing an empty card. Once all four pass the card is genuinely empty.
    """
    rows = []
    trackers = {
        str(card.get("id"))
        for card in state.plugin_cards
        if str(card.get("id", "")).startswith("excel-report")
    }
    sales = state.sales.status or {}
    if (
        not trackers
        and state.sales.mode != "disabled"
        and (state.sales.mode == "unconfigured" or not sales.get("configured"))
    ):
        rows.append(
            {
                "title": "Connect a workbook",
                "why": "The pipeline figure and the moves come from it.",
                "href": "/settings#sources",
                "actionLabel": "Open settings",
            }
        )
    calendar = state.commitments.status or {}
    if (
        state.commitments.mode != "live"
        or calendar.get("state") == "empty"
        or state.commitments.status is None
    ):
        rows.append(
            {
                "title": "Connect your calendar",
                "why": "The digest reads today's meetings from it.",
                "href": "/walkthrough/calendar",
                "actionLabel": "Connect",
            }
        )
    if state.research.enabled and state.research.last_answered_ts is None:
        rows.append(
            {
                "title": "Ask your first question",
                "why": "Answers come from your AI and are logged.",
                "href": "/assistant",
                "actionLabel": "Ask",
            }
        )
    if not state.research.enabled:
        rows.append(
            {
                "title": "Turn research back on",
                "why": "Answers come from your AI, and it is turned off in settings.",
                "href": "/settings#endpoint",
                "actionLabel": "Open settings",
            }
        )
    return rows

def _local_now() -> datetime:
    """The current time as a timezone-aware datetime in the machine's local zone."""
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
# platforms. The child prints exactly one JSON line - picked, cancelled,
# or unavailable - so the parent can tell a dialog that could not open
# from one the user closed; an empty line could only ever say both.
# The dialog is parented to the hidden root and the root is lifted and
# focused first: on Windows a parentless dialog can open invisibly
# behind the browser, which reads to the user as "the button is broken".
_PICKER_SNIPPET_TEMPLATE = """\
import json

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
    answer = {{"status": "picked", "path": chosen}} if chosen else {{"status": "cancelled"}}
except Exception as exc:
    answer = {{"status": "unavailable", "reason": type(exc).__name__}}
print(json.dumps(answer))
try:
    root.destroy()
except Exception:
    pass
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

# The instance setup dialog: every format the instance store can stage,
# so a tracker is never limited to a workbook the export tool did not make.
PLUGIN_FILE_PICK_SNIPPET = _PICKER_SNIPPET_TEMPLATE.format(
    title="Choose a workbook or JSON export",
    filetypes=[
        ("Data files", "*.xlsx *.xlsm *.csv *.json"),
        ("All files", "*.*"),
    ],
)

# The one sentence a dialog that cannot open is answered with, wherever
# it surfaces: the parser, the refuse-on-spawn path and the setup route.
_PICKER_UNAVAILABLE = (
    "The file dialog could not open on this computer. "
    "Type the file's path, or upload the file instead."
)

def _picker_outcome(stdout: str) -> str | None:
    """Which of the picker child's three answers arrived on stdout.

    A picked path is returned, a cancelled dialog answers None, and
    anything else - the unavailable document, a traceback, an unknown
    status, no output at all - raises config:picker-unavailable. Only a
    document the child actually printed as cancelled can mean the user
    closed the dialog; a child that died before it could report must not
    be answered as that person's own decision.
    """
    from ..plugins.config import ConfigError

    lines = [line.strip() for line in (stdout or "").splitlines() if line.strip()]
    if not lines:
        raise ConfigError("config:picker-unavailable", _PICKER_UNAVAILABLE)
    try:
        document = json.loads(lines[-1])
    except ValueError:
        raise ConfigError("config:picker-unavailable", _PICKER_UNAVAILABLE) from None
    if not isinstance(document, dict):
        raise ConfigError("config:picker-unavailable", _PICKER_UNAVAILABLE)
    status = document.get("status")
    if status == "picked":
        chosen = document.get("path")
        if isinstance(chosen, str) and chosen:
            return chosen
    elif status == "cancelled":
        return None
    raise ConfigError("config:picker-unavailable", _PICKER_UNAVAILABLE)

def _tk_pick_file(snippet: str) -> str | None:
    """One child process per dialog call; the parent never imports Tk.

    A picked path is returned and a cancelled dialog answers None. A
    dialog that could not open raises config:picker-unavailable, and a
    child that could not even start does the same after the log line, so
    the caller decides whether to report it or keep a "no path" answer.
    """
    from ..plugins.config import ConfigError

    try:
        completed = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:  # noqa: BLE001 - a broken dialog must not break the app
        LOG.exception("file picker failed")
        raise ConfigError("config:picker-unavailable", _PICKER_UNAVAILABLE) from None
    return _picker_outcome(completed.stdout or "")

def tk_pick_workbook() -> str | None:
    """The native workbook dialog, one child process per call."""
    from ..plugins.config import ConfigError

    try:
        return _tk_pick_file(WORKBOOK_PICK_SNIPPET)
    except ConfigError:
        return None

def tk_pick_calendar() -> str | None:
    """The native calendar-file dialog, same mechanism as the workbook."""
    from ..plugins.config import ConfigError

    try:
        return _tk_pick_file(CALENDAR_PICK_SNIPPET)
    except ConfigError:
        return None

def tk_pick_plugin_file() -> str | None:
    """The instance setup dialog: a workbook, a CSV, or a JSON export."""
    return _tk_pick_file(PLUGIN_FILE_PICK_SNIPPET)

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

def _skill_id_from_path(rest: str) -> int | None:
    """The skill id a /skills/<id>/... address names (the table hands the
    middle over), or None when it names no skill."""
    raw = rest.strip("/")
    return int(raw) if raw.isascii() and raw.isdigit() else None

def _alias_instance_id(name: str) -> str:
    """The instance id an alias's named instance resolves to. Mirrors the
    runtime's derivation, so the manage view lists exactly the instance
    the install materialized."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip().lower()).strip("-")
    return cleaned or "instance"

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
        pick_plugin_file=None,
        calendar: CalendarBridge | None = None,
        llm=None,
        audit_conn=None,
        ledger: Ledger | None = None,
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
        learned_profile: LearnedProfileStore | None = None,
        layout_store: LayoutStore | None = None,
        capabilities_cache: CapabilitiesCache | None = None,
        gate_runners: GateRunners | None = None,
        mail: MailWatch | None = None,
        mail_store: MailStore | None = None,
        research_store: ResearchStore | None = None,
        agents_store: AgentRunStore | None = None,
        outbox_dir=None,
        registry_root=None,
        peer_store: PeerStore | None = None,
        keys_store: KeysStore | None = None,
        keychain=None,
        connection_check=None,
        extractor=None,
        reflector=None,
        announce_port: int | None = None,
        skills_snapshots_dir: Path | str | None = None,
        engine_runner=None,
    ) -> None:
        """Bind the ports the handler set shares, then start listening on address.

        An omitted argument usually disables a feature rather than selecting a real
        fallback (no calendar bridge, no mail watcher, no layout store, no peer store),
        which is why so many attributes are allowed to stay None. llm is the exception:
        None builds the environment client and raises llm_defaulted_to_env so callers
        that only want nicer copy can take their deterministic path instead.
        Constructing the gate runners probes nothing, discovery stays unstarted until
        the peers surface is opened, and an empty registry_root forces the honest
        unavailable state.
        """
        self.sessions = sessions
        # The engine boundary's token (spec 023): minted once per boot,
        # held by this process, and accepted only by the loopback tools
        # route. It never rides a page or a log.
        self.engine_token = secrets.token_urlsafe(32)
        # The engine runner (spec 023, ticket 023-3): the injected seam
        # tests use instead of the real side-car. None means the engine
        # step asks the boundary, which answers with the side-car when
        # its pinned venv is installed and with the fixed loop otherwise.
        self.engine = engine_runner
        self.excel = excel
        self.pick_workbook = pick_workbook
        self.pick_plugin_file = (
            pick_plugin_file if pick_plugin_file is not None else pick_workbook
        )
        self.pick_calendar = pick_calendar
        self.calendar = calendar
        self.llm = llm if llm is not None else env_chat()
        # Whether llm is the env-default client rather than an injected
        # one: with no endpoint anywhere, callers that only want nicer
        # copy (the wizard) take their deterministic path instead of
        # consulting a client that can only raise.
        self.llm_defaulted_to_env = llm is None
        # The client construction built, remembered so the resolution hub
        # (spec 018 #233) can tell a startup env default from a client a
        # caller swapped in later: a replaced llm is an injected llm, and
        # an injected client is never silently replaced by the hub.
        self._startup_llm = self.llm
        self.audit_conn = audit_conn
        self.ledger = ledger
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
        # The learned profile (spec 016 section 6.5): what the desk can
        # honestly say it learned. None means the store could not open,
        # and nothing is learned or served until it can.
        self.learned_profile = learned_profile
        # The extractor port (ticket #91): None means the retain route
        # builds an EndpointExtractor from the effective llm client per
        # call; a test (or a future caller) injects its own.
        self.extractor = extractor
        # The reflector port (ticket #93): the same seam one port over.
        # None means the reflect route builds an EndpointReflector from
        # the effective llm client per call; a test injects its own.
        self.reflector = reflector
        # The dashboard card arrangement (order, hidden, titles); None
        # when its store could not open, in which case reads resolve the
        # canonical default and saves refuse.
        self.layout = layout_store
        # The capabilities cache may be absent (its store could not open);
        # the runner set defaults to the real probe bundle. Building that
        # set probes nothing: gates run only when a re-test POST calls one.
        self.capabilities_cache = capabilities_cache
        self.gate_runners = (
            gate_runners if gate_runners is not None
            else _default_gate_runners(settings_store)
        )
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
        # The peer-to-peer surface (issue #67). The store may be absent
        # (its sqlite could not open): the peers page then says so, and
        # every peer endpoint refuses with a named reason. Discovery is
        # deliberately NOT started here: a default boot announces
        # nothing until the first visit to the peers surface.
        self.peer_store = peer_store
        # The named model connections (spec 018): the store may be absent
        # (its sqlite could not open), in which case the connections
        # routes and the settings section say so and refuse. The keychain
        # wrapper is injectable like every store; None builds the real
        # keyring-backed one, tests pass the in-memory fake.
        self.keys = keys_store
        self.keychain = keychain if keychain is not None else KeychainSecrets()
        # The save-time key prober (spec 018 story 3): the free
        # model-list GET a save with a key performs. Injectable so a
        # hermetic boot answers instantly; the explicit Test, refresh
        # and deeper-check routes use the real health module, so they
        # are exercised against loopback stubs instead.
        self.connection_check = (
            connection_check if connection_check is not None else health.check_models
        )
        self.announce_port = announce_port
        # Where the curator's snapshots land; None resolves to
        # <data>/skills-snapshots at step time (tests inject their own).
        self.skills_snapshots_dir = (
            Path(skills_snapshots_dir) if skills_snapshots_dir is not None else None
        )
        self.peer_discovery: DiscoveryService | None = None
        self._peer_discovery_lock = threading.Lock()
        self.mail_store = mail_store
        # The latest sourced research answer (#64): written by the
        # research panel's own turns, read by plugin cards. None means
        # the store could not open, and the research card says so.
        self.research_store = research_store
        # The agent runs store (spec 012): every task run lands here
        # with its receipt. None means the store could not open, and
        # the agents page says so while the roster still renders.
        self.agents = agents_store
        self.outbox_dir = Path(outbox_dir) if outbox_dir is not None else _default_outbox_dir()

        def _record_skill_created(skill: dict) -> None:
            """The ledger entry for a skill the desk made by itself, plus
            its audit row (spec 016 section 6.6). The before capture is
            the not-active state the undo restores."""
            before = json.dumps({
                "id": skill["id"], "name": skill["name"],
                "description": skill.get("description", ""),
                "prompt": skill.get("prompt", ""),
                "active": False, "created_by": skill.get("created_by", "agent"),
            }, sort_keys=True, ensure_ascii=False).encode("utf-8")
            entry = self.ledger.record(
                actor="agent",
                action="skill.created",
                subject=f"skill:{skill['id']}",
                why=(f"Made the skill {skill['name']} by itself after the same"
                     " ask kept coming back."),
                undo_kind="skill-version",
                before=before,
                detail={"skill": skill["name"], "version": skill.get("version", 1)},
            )
            if self.audit_conn is not None:
                audit_store.record(
                    self.audit_conn, "skill.created", target=skill["name"],
                    detail=f"skill {skill['id']}; ledger {entry.id}")

        self.consolidator = (
            Consolidator(
                activity_log, inbox_store, skill_store, activity_log.clock,
                create_directly=lambda: (
                    settings_store is not None
                    and may_act(settings_store, "skill.create")
                    and bool(settings_store.get("skills_auto_create"))
                ),
                on_created=_record_skill_created,
            )
            if activity_log is not None and inbox_store is not None and skill_store is not None
            else None
        )
        # The memory loop (memory/loop.py): captures run off the request
        # thread, one at a time; removals are held for undo in process
        # memory only. A test swaps the runner for an inline call.
        self.memory_undo = memory_loop.UndoBuffer(time.time)
        self.memory_capture_lock = threading.Lock()
        self.memory_capture_runner = _background_runner
        self.memory_last_capture: dict | None = None
        # The removal previews just shown (their observation text), so the
        # removal writes what the user read; and the model pass's flag.
        self.memory_previews = memory_loop.PreviewCache(time.time)
        self.memory_observe_pending = False
        if excel is not None:
            excel.change_hook = lambda workbook, header, delta: _workbook_changed(
                self, workbook, header, delta)
        self.memory_observe_after = 0.0
        # Tests inject a summarizer port; None builds the endpoint one.
        self.summarizer = None
        # The recommendation builder (spec 016 §6.3): turns deadlines in saved
        # facts into waiting inbox cards. None only when a store it reads is absent.
        self.recommender = (
            RecommendationBuilder(
                inbox=inbox_store,
                memory=memory_store,
                calendar=calendar,
                settings=settings_store,
                ledger=ledger,
                clock=getattr(inbox_store, "clock", time.time),
            )
            if inbox_store is not None
            and memory_store is not None
            and settings_store is not None
            and ledger is not None
            else None
        )
        self.started_monotonic = time.monotonic()
        super().__init__(address, DashboardHandler)

    @property
    def port(self) -> int:
        """The port the socket actually bound.

        It differs from the address passed to the constructor when port 0 asked the OS
        to pick one.
        """
        return self.server_address[1]

    def ensure_peer_discovery(self) -> DiscoveryService | None:
        """Start discovery on first use, once, under a lock.

        The quieter honest default (pinned by test): nothing is
        announced until a human opens the peers surface, and from then
        on the desk keeps announcing until shutdown.
        """
        if self.peer_store is None:
            return None
        if self.peer_discovery is None:
            with self._peer_discovery_lock:
                if self.peer_discovery is None:
                    desk = self.peer_store.desk()
                    service = DiscoveryService(
                        peer_id=desk["peer_id"], name=desk["name"],
                        http_port=self.port,
                        announce_port=self.announce_port
                        or PREFERRED_ANNOUNCE_PORT)
                    service.start()
                    self.peer_discovery = service
        return self.peer_discovery

    def server_close(self) -> None:
        """Stop announcing before the sockets close, so a test process
        never leaves a UDP listener behind on Windows."""
        loop = getattr(self, "agent_loop", None)
        if loop is not None:
            # The loop's threads write to the ledger and the audit store, so
            # they stop before either store closes (spec 016 section 6.2).
            loop.stop(timeout=2)
        discovery = getattr(self, "peer_discovery", None)
        if discovery is not None:
            discovery.stop()
        if self.ledger is not None:
            self.ledger.close()
        super().server_close()

def live_sources(server: AgentDeskServer) -> list[SourceStatus]:
    """The source table computed at request time, from the real watches.

    Health must not repeat what a constructor once guessed: excel is
    connected when a workbook is registered, calendar when the bridge has
    produced a non-empty state, the AI when the resolution hub can serve a
    call. Both /health and the dashboard's source line read this table.

    A source wired to the labelled sample set is reported as "sample", never
    as connected (spec 022): the sample switch keeps the cards alive while
    nothing real is attached, and the source line must not call that live.
    """

    def state(connected: bool, sample: bool = False) -> str:
        """The status word for one source: not connected, sample or connected.

        Both /health and the dashboard read the same words from this function.
        """
        if not connected:
            return STATUS_NOT_CONNECTED
        return STATUS_SAMPLE if sample else STATUS_CONNECTED

    excel = server.excel
    excel_path = excel.registered_path if excel is not None else None
    workbook_sample = excel_path is not None and demo_data.under_sample_folder(excel_path, None)
    calendar = server.calendar
    calendar_status = calendar.status() if calendar is not None else {}
    calendar_state = calendar_status.get("state")
    calendar_ok = calendar_state not in (None, STATE_EMPTY)
    calendar_path = calendar_status.get("path")
    calendar_sample = calendar_ok and bool(calendar_path) and demo_data.under_sample_folder(
        calendar_path, None)
    # The AI is connected when the per-job resolution hub can serve a
    # call: a saved connection, or the legacy rows and environment behind
    # it. The startup client stays as the last leg so this is never less
    # true than before (a boot may inject one directly). Nothing else may
    # decide this (spec 022): the desk used to read the pre-018 rows alone
    # and tell a user with a saved key that the endpoint was not set.
    endpoint_ok = (_server_resolution(server, "assistant") is not None
                   or bool(server.llm_endpoint))
    workbook = ""
    if excel_path:
        workbook = str(excel_path).replace("\\", "/").rsplit("/", 1)[-1]
    return [
        SourceStatus(
            SRC_EXCEL,
            state(excel_path is not None, workbook_sample),
            f"Sample data, not your file: {workbook}." if workbook_sample
            else f"Watches {workbook}." if excel_path else "No workbook connected yet.",
        ),
        SourceStatus(
            SRC_CALENDAR,
            state(calendar_ok, calendar_sample),
            "Sample calendar, not your calendar." if calendar_sample
            else "Reading the OneDrive calendar sync." if calendar_ok else "No calendar data yet.",
        ),
        SourceStatus(
            SRC_RESEARCH,
            state(endpoint_ok),
            "AI connected." if endpoint_ok else "No AI key saved yet.",
        ),
    ]

def _plugin_element_html(element: dict) -> str:
    """One payload element as authored HTML, drawn by the plugin renderer.

    The dashboard's no-JS card and the SPA draw the same ten element kinds;
    the markup is owned by agentdesk.plugins.html so the two surfaces cannot
    grow separate vocabularies. Text arrives already escaped from there.
    """
    return element_html(element)

def _receipt_line(payload: dict) -> str:
    """The reading's resolved lines under its card, as quiet paragraphs.

    The payload carries the lines already resolved and ordered
    (agentdesk.insight.reading owns the phrases), so this only draws them:
    escaping is the single job left, and the SPA prints the very same block
    texts. A payload with no blocks, or one whose blocks hold no text, draws
    nothing rather than an empty line.
    """
    insight = payload.get("insight")
    blocks = insight.get("blocks") if isinstance(insight, dict) else None
    if not isinstance(blocks, list):
        return ""
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if text:
            # The apostrophe in "this card's rows" is copy, so only the
            # ampersand-and-angle shapes are escaped; a note's own text still
            # cannot smuggle markup onto the page.
            lines.append('<p class="w-note">' + html.escape(text, quote=False) + "</p>")
    return "".join(lines)

def _plugin_retest_can_change(cause: str) -> bool:
    """True when a re-test could change an attention card's cause.

    A structural cause does not change by reading again: a build without an
    HTTP transport can never fetch a page, a manifest that contributes no
    widget has no source to run, a manifest that names no file reads
    nothing, and a tampered tree needs a reinstall. A re-test on those
    would be a button that cannot work, so the card offers removal instead.
    """
    if "installed files changed" in cause:
        return False
    return cause not in (
        "This desk cannot read web pages yet.",
        "This plugin adds no card to your dashboard.",
        "data source has no file",
    )


def _press_form(card: dict, press: object) -> str:
    """A card's press as a real control: a plain form, no script.

    The hidden fields are press_to_fields' spelling of the request, so what
    the page posts re-parses into exactly the press the card carried. The
    card's identity rides along so the answer can name the card that was
    pressed.
    """
    if not isinstance(press, dict):
        return ""
    label = str(press.get("label") or "").strip()
    kind = str(press.get("kind") or "").strip()
    if not label or not kind:
        return ""
    hidden = press_to_fields(press)
    for name, value in (
        ("pluginId", card.get("pluginId") or card.get("id")),
        ("instanceId", card.get("instanceId")),
    ):
        if isinstance(value, str) and value.strip():
            hidden[name] = value
    fields = "".join(
        '<input type="hidden" name="' + name + '" value="' + html.escape(value) + '">'
        for name, value in hidden.items()
    )
    return (
        '<form method="post" action="/insight/press" class="cardform">'
        + fields
        + '<button class="btn btn-secondary" type="submit">' + html.escape(label) + "</button>"
        + "</form>"
    )

def with_insight(server: AgentDeskServer, cards: list[dict]) -> list[dict]:
    """Attach the coupled reading to cards as the dashboard state is built.

    build_dashboard_state calls this once, so a reading is never JSON-only:
    the same sentence arrives through the API payload and through the
    authored HTML.
    """
    attach_cards(
        cards,
        build_insight_context(server, PreferenceStore(default_data_dir()).read()),
    )
    return cards

def enabled_plugin_ids(server: AgentDeskServer) -> list[str]:
    """The plugin ids whose cards exist right now, in listing order.

    Only enabled plugins render a card (the same filter widget_cards
    applies), so those are the layout's plugin universe. This call is
    read-only: it never spends a pilot view.
    """
    plugins = server.plugins
    if plugins is None:
        return []
    if hasattr(plugins, "layout_keys"):
        return plugins.layout_keys()
    return [
        entry["id"] for entry in plugins.list_records()
        if entry.get("state") == "enabled"
    ]

def dashboard_payload(server: AgentDeskServer) -> dict:
    """Everything the dashboard shows, as data: one JSON payload for the
    SPA shell (and any later client).

    The payload is one projection of build_dashboard_state, the same state
    the server-rendered cards are built from, so the two surfaces cannot
    disagree about a source's mode, research availability or the layout.
    Plugin cards are data, never server HTML, and building the state is a
    pure read: a GET never spends a plugin's pilot view.
    """
    return build_dashboard_state(server).payload()

def update_payload(server: AgentDeskServer) -> dict:
    """The update state plus the two switches, for the page and the API."""
    from agentdesk.update import summary

    settings = getattr(server, "settings", None)
    channel = ""
    if settings is not None:
        value = settings.get("update_channel")
        channel = value.strip() if isinstance(value, str) else ""
    payload = summary(default_data_dir())
    payload["autoUpdate"] = (
        bool(settings.get("auto_update")) if settings is not None else False)
    payload["channelSet"] = bool(channel)
    return payload

def desk_check_context(server: AgentDeskServer) -> "DeskContext":
    """The desk check's view of this server: live collaborators, read only.

    The catalog is left unset. The retired-plugin check loads the shipped
    catalog itself, so a file that will not open is one crashed check and
    an empty file retires nothing. The ledger is whatever this build has.
    """
    from agentdesk.deskcheck import DeskContext

    return DeskContext(
        settings=server.settings,
        inbox=server.inbox,
        excel=server.excel,
        calendar=server.calendar,
        plugins=server.plugins,
        catalog_ids=None,
        data_dir=default_data_dir(),
        ledger=getattr(server, "ledger", None),
        clock=time.time,
    )

def desk_check_result(server: AgentDeskServer, should_fix: bool = False) -> "CheckResult":
    """One run of every desk check; with should_fix, confident fixes may run."""
    from agentdesk.deskcheck import run_checks

    return run_checks(desk_check_context(server), should_fix=should_fix)

def desk_check_api_payload(server: AgentDeskServer) -> dict:
    """GET /api/desk-check's JSON body: one read-only run of every check."""
    from agentdesk.deskcheck import finding_to_api

    result = desk_check_result(server)
    return {
        "ranTs": time.time(),
        "findings": [finding_to_api(finding) for finding in result.findings],
        "failed": dict(result.failed),
    }

def _detached_handler(server: "AgentDeskServer") -> "DashboardHandler":
    """A handler with no request, for work that starts outside one (the
    workbook watch's poll thread). Only the helpers that read
    `self.server` may be called on it: the memory capture path."""
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.server = server
    return handler


def _refresh_plugins_on(server: "AgentDeskServer", topic: str) -> list:
    """Refresh the change-driven plugin tiles whose topic just fired.

    One place for every event that reports itself, so a new event source is
    one call rather than a copy of the wiring. It never raises: a failing
    refresh must not break the watch or poll that fired it.
    """
    plugins = getattr(server, "plugins", None)
    if plugins is None:
        return []
    try:
        return plugins.runner.refresh_on_event(topic)
    except Exception:  # noqa: BLE001 - an event must never break its source
        LOG.exception("plugin refresh failed for topic %s", topic)
        return []


def _tick_plugin_refresh(server: "AgentDeskServer") -> list:
    """Refresh the plugin tiles whose next update is due.

    Scheduled tiles refresh when their cron's minute has come. Change tiles
    for piped sources (calendar, mail, research) and for files are re-read
    here too, and the runner stores the result only when it differs from what
    the card already shows, so an unchanged poll leaves the tile and its
    as-of time exactly as they were. The workbook is the one source with its
    own change signal, wired to its watch's hook instead.

    Called once a minute by ``start_plugin_refresh_tick``.
    """
    plugins = getattr(server, "plugins", None)
    if plugins is None:
        return []
    refreshed: list = []
    for step in (plugins.runner.refresh_due,
                 plugins.runner.refresh_files_and_pipelines):
        try:
            refreshed += step()
        except Exception:  # noqa: BLE001 - the tick must survive one bad plugin
            LOG.exception("plugin refresh step failed")
    return refreshed

def _workbook_changed(server: "AgentDeskServer", workbook: str, header: list, delta) -> None:
    """The memory loop's workbook channel: rows that changed since the
    watch's 24-hour reference become facts written from the cells, staged
    for review (or saved, in automatic mode) like any captured fact.
    Already stored, waiting or rejected facts are not proposed again."""
    if server.memory is None or server.settings is None:
        return
    if not bool(server.settings.get("excel_enabled")):
        return
    # A workbook tile set to "when it changes" follows its own watch's signal.
    _refresh_plugins_on(server, "workbook")
    candidates = memory_loop.workbook_candidates(header, delta.added, delta.removed)
    if not candidates:
        return
    _detached_handler(server)._capture_memory(
        "workbook", memory_loop.workbook_excerpt(workbook, candidates), "",
        candidates=candidates,
    )

@dataclass(frozen=True)
class StoreMissing:
    """A typed answer for an optional store that is not configured.

    The result-returning sibling of `_require_store` for callers that
    answer in more than one shape: what "missing" means is decided once,
    in `_store_missing`, and each surface renders from this outcome. The
    JSON shape is the status and error payload those callers always sent,
    byte-identical; the form shape is the wave's failure notice, which
    says what failed and what to try next, in place near the action
    (docs/design-language.md F5 and F7), so a form post never meets raw
    JSON.
    """

    status: int
    sentence: str
    notice: str

    def as_json(self) -> tuple[int, dict]:
        """The JSON-API shape: the status and the error payload as sent before."""
        return self.status, {"error": self.sentence}


class DashboardHandler(MemoryApiMixin, PeersApiMixin, BaseHTTPRequestHandler):
    """GET for the shell, health and statics; POST for state changes."""

    protocol_version = "HTTP/1.1"
    server_version = f"AgentDesk/{agentdesk.__version__}"
    sys_version = ""  # never advertise the interpreter behind the app

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Send http.server's per-request line to the debug log instead of stderr.

        The signature follows BaseHTTPRequestHandler: format is a %-style template and
        args its operands.
        """
        LOG.debug("http %s", format % args)

    # -- entry points: no exception may drop a connection silently -------

    def do_GET(self) -> None:  # noqa: N802 (http.server contract)
        """Dispatch one GET, answering 500 rather than dropping the connection on an
        unexpected error.

        _responded is reset before routing so _fail_safe can tell whether the client
        already has an answer.
        """
        self._responded = False
        try:
            self._route_get()
        except Exception:  # noqa: BLE001 - the UI is the log, not a traceback
            LOG.exception("GET failed")
            self._fail_safe(500, "Something broke", "The dashboard hit an error handling that. Nothing was changed.")

    def do_POST(self) -> None:  # noqa: N802 (http.server contract)
        """Dispatch one POST, answering 500 rather than dropping the connection on an
        unexpected error.

        _responded and _close_with_response are reset before routing, so a handler that
        already answered is never answered twice.
        """
        self._responded = False
        self._close_with_response = False
        try:
            self._route_post()
        except Exception:  # noqa: BLE001
            LOG.exception("POST failed")
            self._fail_safe(500, "Something broke", "That action did not go through. Try again; if it repeats, restart the app.")

    def _fail_safe(self, status: int, title: str, message: str) -> None:
        """Send the 500 page only when nothing has been written yet.

        Writing a second response over a completed one raises inside http.server, so
        this is the difference between a page and a traceback.
        """
        if not self._responded:
            self._send_error_page(status, title, message)

    # -- the gate every request passes ----------------------------------

    def _gate(self) -> bool:
        """Origin/Host guard, then session auth. Sends the answer itself.

        Both refusals end the connection: the gate runs before the body
        is drained, and an unread body on a kept-alive connection is
        exactly what the drain exists to prevent."""
        verdict = self._guard_verdict()
        if not verdict.allowed:
            title, message = self._guard_refusal_copy(verdict)
            self._refuse_and_close(403, title, message)
            return False
        if not self._authenticated():
            self._refuse_and_close(
                401, "Session required",
                "Open Agent Desk from its shortcut to get a fresh link.",
            )
            return False
        return True

    def _extra_allowed_hosts(self) -> frozenset[str]:
        """The host[:port] entries the user sanctioned in Settings,
        lowercased; empty (the default) keeps the guard loopback-only.
        Resolved per request so a saved value applies without a restart."""
        settings = self.server.settings  # type: ignore[attr-defined]
        raw = settings.get("extra_allowed_hosts") if settings is not None else ""
        return frozenset(
            part.lower() for part in re.split(r"[,\s]+", str(raw)) if part.strip()
        )

    def _guard_verdict(self) -> GuardVerdict:
        """The guard's answer for this request, with the sanctioned extra
        hosts resolved here (the guard itself stays a pure function)."""
        return check_request(
            self.headers.get("Host"),
            self.headers.get("Origin"),
            self.server.port,  # type: ignore[attr-defined]
            extra_hosts=self._extra_allowed_hosts(),
        )

    def _guard_refusal_copy(self, verdict: GuardVerdict) -> tuple[str, str]:
        """(title, message) for a refused Host or Origin: plain words
        naming the addresses that work, the extra ones the user
        sanctioned, and the address that was used instead."""
        port = self.server.port  # type: ignore[attr-defined]
        extras = sorted(self._extra_allowed_hosts())
        extra_line = (
            " These addresses also work: "
            + ", ".join(f"http://{host}" for host in extras) + "."
            if extras else ""
        )
        opened = f" You opened it at {verdict.rejected}." if verdict.rejected else ""
        message = (
            "This app runs on your machine and is opened at "
            f"http://127.0.0.1:{port} or http://localhost:{port}."
            f"{extra_line}{opened}"
        )
        return "Wrong address", message

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
        """Dispatch one GET by the route table, after the peer exception, the auth
        exception and the session gate.

        /peer/ and /auth/ are settled first because neither can require what the gate
        requires: a peer request carries a token rather than a cookie, and /auth/ exists
        to create the session every other path needs. Past the gate, routes.GET_ROUTES is
        authoritative in its order; an unknown /marketplace/ path still gets the shell
        but with a 404 status, so a typo stays honest to clients while the SPA renders.
        """
        path, _, _query = self.path.partition("?")
        if path.startswith("/peer/"):
            # The peer surface: the guard with its token rule, never a
            # browser session (another desk cannot hold a cookie).
            self._route_peer_get(path)
            return
        if path.startswith("/auth/"):
            # The one route a session does not exist for yet: guard runs,
            # auth does not.
            verdict = self._guard_verdict()
            if not verdict.allowed:
                self._send_error_page(403, *self._guard_refusal_copy(verdict))
                return
            self._handle_auth(path[len("/auth/"):])
            return
        if not self._gate():
            return
        self._dispatch("GET", path, "No page lives at this address.")

    # -- POST ------------------------------------------------------------

    def _route_post(self) -> None:
        """Dispatch one POST by the route table, after draining the body.

        The body is drained before dispatch even for paths that ignore it, because an
        unread body on a keep-alive connection would be parsed as the next request; the
        peer branch drains before its own guard for that same reason. Source endpoints
        consult their settings toggle first and answer 409 with a reconnect path, a
        collaborator that was never built answers 503, and the assistant turn separates
        the two clients: a form submit gets a 303 back to the page, a fetch gets the
        answer as JSON. Past those guards, routes.POST_ROUTES is authoritative in its
        order.
        """
        path, _, _query = self.path.partition("?")
        if path.startswith("/peer/"):
            # Peer POSTs exist for pairing only; the surface is
            # otherwise read-only. The body is drained before anything
            # answers, so a keep-alive connection survives.
            self._raw_body = self._drain_body()
            self._route_peer_post(path)
            return
        if path == "/api/engine/tools":
            # The engine surface (spec 023): the guard with the boot
            # token, never a browser session (the engine holds a token,
            # not a cookie), and loopback only. The body is drained
            # first, like the peer branch, so keep-alive survives.
            self._raw_body = self._drain_body()
            self._route_engine_post()
            return
        if not self._gate():
            return
        # Drain the request body up front: an unread body on a keep-alive
        # connection would be parsed as the next request. A setup upload
        # stashes up to its own cap instead of the 1 MiB JSON bound.
        limit = MAX_UPLOAD_BYTES if _PLUGIN_UPLOAD_PATH.match(path) else MAX_BODY_BYTES
        self._raw_body = self._drain_body(limit)
        if path.startswith("/sources/excel-watch") and not self._source_allowed("excel_enabled"):
            self._send_json(409, {"error": "Sales watching is off in settings.", "reconnect": "/settings"})
            return
        if path.startswith("/sources/calendar-bridge") and not self._source_allowed("calendar_enabled"):
            self._send_json(409, {"error": "Calendar reading is off in settings.", "reconnect": "/settings"})
            return
        self._dispatch("POST", path, "No action lives at this address.")

    def _dispatch(self, method: str, path: str, missing_message: str) -> None:
        """Answer one gated request from the route table.

        path arrives without its query string, which the caller has already stripped;
        missing_message is the 404 body's sentence for this method (the two clients word
        it differently). A route with arg="rest" receives the matched remainder, every
        other handler keeps its no-argument signature.
        """
        found = routes.match(method, path)
        if found is None:
            self._send_error_page(404, "Nothing here", missing_message)
            return
        handler = getattr(self, found.route.handler)
        if found.route.arg == "rest":
            handler(found.argument)
        else:
            handler()

    # -- route handlers the table calls -----------------------------------

    def _send_walkthrough_calendar(self) -> None:
        """Serve the walkthrough page, hinting the calendar it should open.

        A boot pinned to no calendar has no hint. The page still names the
        plain path it will use once reading is turned on, and says plainly
        that reading is off on this desk.
        """
        calendar = self.server.calendar  # type: ignore[attr-defined]
        explicit = calendar.explicit_path() if calendar is not None else None
        hint = default_calendar_hint(explicit)
        calendar_off = hint is None
        if hint is None:
            hint = Path.home() / "OneDrive" / "agent-desk" / "calendar_sync.json"
        self._send_bytes(
            200,
            pages.render_walkthrough(str(hint), explicit_path=explicit or "",
                                    version=agentdesk.__version__,
                                    inbox_count=self._inbox_waiting_count(),
                                    calendar_off=calendar_off).encode("utf-8"),
            "text/html; charset=utf-8",
        )

    def _send_activity_redirect(self) -> None:
        """Send the old /activity address to its Settings home.

        The decision log became the activity trail inside Settings; the old address
        keeps answering for bookmarks and links.
        """
        self._send_redirect_302("/settings/activity")

    def _send_plugins_redirect(self) -> None:
        """Send the legacy /plugins address to the installed marketplace surface.

        One release of continuity: the legacy address names the new installed surface
        with a permanent-enough 302. The SPA route owns everything past this point.
        A notice query rides along: the lifecycle actions below redirect back to
        /plugins?notice=..., and the sentence must survive into the page the user
        lands on, not die in this hop.
        """
        _, _sep, query = self.path.partition("?")
        notice = parse_qs(query).get("notice", [""])[0] if query else ""
        target = "/marketplace/installed"
        if notice:
            target += "?notice=" + quote(notice)
        self._send_redirect_302(target)

    def _send_peers_page_request(self) -> None:
        """Serve the peers page, carrying its notice and kept pair fields."""
        _, _sep, query = self.path.partition("?")
        fields = parse_qs(query) if query else {}
        self._send_peers_page(
            notice=fields.get("notice", [""])[0],
            pair_address=fields.get("address", [""])[0],
            pair_code=fields.get("code", [""])[0],
        )

    def _send_skill_markdown_rest(self, rest: str) -> None:
        """Serve the generated markdown for the skill id in the path.

        The table hands over the text between /skills/ and /skill.md; a
        malformed id is a 404 page, not a crash.
        """
        skill_id = _skill_id_from_path(rest)
        if skill_id is None:
            self._send_error_page(404, "Nothing here",
                                  "No skill lives at this address.")
            return
        self._send_skill_markdown(skill_id)

    def _wizard_request(self) -> None:
        """Hand a /wizard path to the wizard router, with its query string removed.

        The prefix deliberately includes lookalikes such as /wizardx: the wizard router
        answers its own 404 for a path it does not know, which is the honest response.
        """
        path, _, _query = self.path.partition("?")
        self._route_wizard(self.command, path)

    def _marketplace_api_get(self) -> None:
        """Hand a marketplace API GET to the marketplace router.

        The marketplace router performs its own error envelopes; the session and Origin
        gates above have already run.
        """
        from ..marketplace.api import handle_get

        handle_get(self)

    def _marketplace_api_post(self) -> None:
        """Hand a marketplace API POST to the marketplace router."""
        from ..marketplace.api import handle_post

        handle_post(self)

    def _send_wizard_availability(self) -> None:
        """Say whether the description can fill the wizard's choices in.

        The page asks this once, on mount, to decide between the fill dialog
        and the plain question walk. It is a read-only probe: it resolves the
        AI connection the wizard would use and makes no model call.
        """
        compiler = self._wizard_compiler()
        self._send_json(200, {"autofill": compiler is not None and compiler.llm is not None})

    def _send_plugins_api_list(self) -> None:
        """Serve the plugin records the widgets and the marketplace page read."""
        self._send_json(200, {"plugins": self.server_plugins_widget_records()})
    def _send_registry_listing(self) -> None:
        """Serve the registry listing visible to this request."""
        self._send_json(200, self._registry_listing_for_request())

    def _send_peers_api(self) -> None:
        """Serve the peer catalog as JSON."""
        self._send_json(200, self._peers_catalog())

    def _send_dashboard_api(self) -> None:
        """Serve the dashboard payload as JSON.

        The GET is also the supervisor's heartbeat: a loop thread that died
        mid-target is respawned here, one thread, never a second beside the
        first (spec 016 section 6.2).
        """
        loop = getattr(self.server, "agent_loop", None)  # type: ignore[attr-defined]
        if loop is not None:
            loop.restart_if_dead()
        self._send_json(200, dashboard_payload(self.server))

    def _send_ledger_api(self) -> None:
        """Serve the action ledger newest first: what the desk changed by
        itself, why, and whether each change can still be undone.

        limit is the one query parameter; it is clamped to what Activity
        shows so a client cannot ask for an unbounded read.
        """
        server = self.server  # type: ignore[attr-defined]
        limit = 50
        _, _sep, query = self.path.partition("?")
        raw_limit = parse_qs(query).get("limit", [""])[0] if query else ""
        if raw_limit.isdigit():
            limit = max(1, min(200, int(raw_limit)))
        ledger = getattr(server, "ledger", None)
        entries = ledger.entries(limit=limit) if ledger is not None else []
        self._send_json(200, {"entries": [
            {
                "id": entry.id,
                "ts": entry.ts,
                "actor": entry.actor,
                "action": entry.action,
                "subject": entry.subject,
                "why": entry.why,
                "undoable": entry.undoable,
                "undoneBy": entry.undone_by,
                "undoes": entry.undoes,
            }
            for entry in entries
        ]})

    def _send_desk_check_api(self) -> None:
        """Serve one read-only run of every desk check as JSON."""
        self._send_json(200, desk_check_api_payload(self.server))

    def _desk_check_fix(self) -> None:
        """Run one finding's automatic fix, exactly as its Fix it button does.

        The finding is looked up from a fresh read-only run, so a stale id
        cannot run an old fix, and only an automatic, confident finding is
        fixable here. The answer is the same JSON the button's page needs:
        whether it is fixed, which ledger entry records it, and the cause
        when it is not.
        """
        server = self.server  # type: ignore[attr-defined]
        body = self._read_json_body() or {}
        finding_id = body.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            self._send_json(400, {"error": 'expected {"id": "<finding id>"}'})
            return
        from agentdesk.deskcheck import FIX_AUTO, apply_fix, run_checks

        ctx = desk_check_context(server)
        finding = next(
            (item for item in run_checks(ctx).findings if item.id == finding_id),
            None,
        )
        if finding is None:
            payload = {"fixed": False, "entry": None,
                       "cause": "That finding is not there any more."}
        elif finding.fix != FIX_AUTO or not finding.confident:
            payload = {"fixed": False, "entry": None,
                       "cause": "That finding is not one the desk can fix by itself."}
        else:
            outcome = apply_fix(ctx, finding)
            payload = {"fixed": outcome.fixed, "entry": outcome.entry_id,
                       "cause": outcome.cause}
            self._audit(
                "deskcheck.fixed" if outcome.fixed else "deskcheck.fix-failed",
                target=finding_id,
                detail=(outcome.entry_id or outcome.cause or ""),
            )
        if self._is_form_submit():
            if payload.get("fixed"):
                notice = "The finding was fixed."
                kind_word = "status"
            else:
                notice = (f"That finding was not fixed: {payload.get('cause') or 'nothing changed'}")
                kind_word = "alert"
            self._send_notice_redirect("/settings#desk-check", notice, kind_word)
            return
        self._send_json(200, payload)

    # -- the engine surface: one token-gated, loopback-only tools route ----

    def _engine_bearer_token(self) -> str:
        """The engine token from the one transport it accepts: a Bearer header.

        There is no query-string form by design (tokens must not land in
        logs), the same rule the peer surface keeps.
        """
        header = self.headers.get("Authorization") or ""
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return ""

    def _route_engine_post(self) -> None:
        """Serve one engine tool call: the loopback guard, the token, the tool.

        The plain Host/Origin check runs with no sanctioned extra hosts,
        so the route is loopback-only however wide the settings allow
        other surfaces. The token is this boot's own, compared with a
        constant-time equal; the session gate deliberately does not run,
        because the engine holds a token rather than a browser cookie.
        """
        verdict = check_request(
            self.headers.get("Host"), self.headers.get("Origin"),
            self.server.port)  # type: ignore[attr-defined]
        if not verdict.allowed:
            self._send_json(403, {
                "error": "engine:blocked",
                "message": ("The engine tools answer on this desk's loopback "
                            "address only: " + verdict.reason)})
            return
        token = self._engine_bearer_token()
        expected = getattr(self.server, "engine_token", "")  # type: ignore[attr-defined]
        if not expected or not token:
            self._send_json(403, {
                "error": "engine:token-required",
                "message": ("This surface is the desk engine's: send this "
                            "boot's token as an Authorization: Bearer header.")})
            return
        # A token that is not ASCII cannot equal a token this boot minted;
        # encode first so compare_digest answers False instead of raising.
        try:
            matches = secrets.compare_digest(token.encode("utf-8"),
                                             expected.encode("utf-8"))
        except (TypeError, UnicodeEncodeError):
            matches = False
        if not matches:
            self._send_json(403, {
                "error": "engine:token-unknown",
                "message": "That token is not this boot's engine token."})
            return
        self._engine_tool_run()

    def _engine_tool_run(self) -> None:
        """Dispatch one token-valid tool call through the desk's vocabulary.

        A name the vocabulary does not carry is a 400, never a guess; a
        body that is not the expected object is the same refusal. Every
        handler answers (status, payload) and the audit row is written
        after it with the outcome status, so a refused or failed call is
        as visible as an accepted one. Every write runs its `may_act`
        gate and lands its ledger entry with an undo kind, or nothing
        changes and the refusal names why.
        """
        body = self._read_json_body()
        if not isinstance(body, dict):
            self._audit("engine.tool", target="(body)", status="error",
                        detail="malformed body: expected an object")
            self._send_json(400, {"error": 'expected {"tool": "<name>", "args": {...}}'})
            return
        name = body.get("tool")
        spec = engine_tool_by_name(name)
        if spec is None:
            self._audit("engine.tool", target=str(name)[:80], status="error",
                        detail="unknown tool")
            self._send_json(400, {
                "error": "engine:tool-unknown",
                "message": "That tool is not one the desk's engine may call."})
            return
        args = body.get("args")
        if not isinstance(args, dict):
            args = {}
        handlers = {
            "desk_names": self._engine_tool_desk_names,
            "add_card": self._engine_tool_add_card,
            "propose_fact": self._engine_tool_propose_fact,
            "desk_probes": self._engine_tool_desk_probes,
        }
        try:
            status, payload = handlers[spec.name](args)
        except Exception:  # noqa: BLE001 - one failed call is a 500, not a dead route
            LOG.exception("engine tool %s failed", spec.name)
            status, payload = 500, {
                "error": "The desk could not answer that tool call."}
        self._audit("engine.tool", target=spec.name,
                    status="ok" if 200 <= status < 300 else "error",
                    detail=("read-only" if spec.read_only else "write")
                    + ("" if 200 <= status < 300 else
                       "; " + str(payload.get("error") or "")[:160]))
        self._send_json(status, payload)
    def _engine_tool_desk_names(self, args: dict) -> tuple[int, dict]:
        """The dashboard's names, read-only: what the desk holds right now."""
        return 200, {"tool": "desk_names",
                     "names": engine_names_payload(self.server)}  # type: ignore[attr-defined]

    def _engine_tool_desk_probes(self, args: dict) -> tuple[int, dict]:
        """One read-only run of the desk check's probes, as JSON."""
        return 200, {"tool": "desk_probes",
                     "probes": desk_check_api_payload(self.server)}  # type: ignore[attr-defined]

    def _engine_tool_add_card(self, args: dict) -> tuple[int, dict]:
        """Add one suggestion card through the existing recommendation builder.

        The builder records the ledger entry with the card-added undo
        kind. The ledger and the inbox are required before anything is
        added: a suggestion that cannot be recorded or shown is not a
        write this route makes. Without autonomy the desk refuses before
        anything changes.
        """
        server = self.server  # type: ignore[attr-defined]
        if server.recommender is None or server.inbox is None:
            return self._store_missing("recommendation builder").as_json()
        if server.ledger is None:
            return self._store_missing(
                "ledger", status=409,
                sentence="The ledger is not available, so no suggestion was "
                         "added.").as_json()
        refusal = self._engine_write_refusal("engine.card", "cards")
        if refusal is not None:
            return refusal
        title = str(args.get("title") or "").strip()
        body = str(args.get("body") or "").strip()
        if not title or not body:
            return 400, {"error": "the add_card call needs a title and a body"}
        try:
            made = server.recommender.add_engine_card(
                title=title, body=body, why=str(args.get("why") or "").strip())
        except Exception:  # noqa: BLE001 - the builder rolled its card back
            LOG.exception("engine add_card could not record its entry")
            return 500, {"error": ("The desk could not record that suggestion, "
                                   "so nothing was added.")}
        if made is None:
            return 409, {
                "error": ("The desk is not adding suggestions right now, or that "
                          "one is already waiting or was already made.")}
        card, entry = made
        return 201, {"tool": "add_card", "cardId": card.id,
                     "entryId": entry.id}

    def _engine_tool_propose_fact(self, args: dict) -> tuple[int, dict]:
        """Propose one memory fact through capture's normal review path.

        Review mode stages the same memory draft card a capture makes
        (the entry's undo dismisses it; the excerpt is created on
        approval, so a rejected or undone proposal leaves nothing
        behind); automatic mode stores the fact through the one write
        every fact takes, with the auto-saved entry's fact undo. The
        ledger is required before anything is written. A fact the desk
        already holds, a capture switch that is off, or autonomy that is
        off is a refusal with nothing written.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None:
            return self._store_missing("memory store").as_json()
        if server.ledger is None:
            return self._store_missing(
                "ledger", status=409,
                sentence="The ledger is not available, so no fact was "
                         "proposed.").as_json()
        if memory.locked_cause is not None:
            return 423, {"status": "locked", "error": memory.locked_cause}
        settings = memory_loop.capture_settings(server.settings)
        if not settings.enabled:
            return 409, {
                "error": "Memory capture is off in settings, so nothing was proposed."}
        refusal = self._engine_write_refusal("engine.memory", "memory proposals")
        if refusal is not None:
            return refusal
        if not settings.auto_approve and server.inbox is None:
            return self._store_missing("inbox").as_json()
        text = str(args.get("text") or "").strip()
        if not text:
            return 400, {"error": "the propose_fact call needs the fact text"}
        if self._fact_already_held(text):
            return 409, {
                "error": "The desk already holds that fact, so nothing was proposed."}
        try:
            if settings.auto_approve:
                entry_id = self._engine_fact_store(memory, text)
            else:
                entry_id = self._engine_fact_stage(memory, text)
        except Exception:  # noqa: BLE001 - each helper rolled its write back
            LOG.exception("engine propose_fact could not record its entry")
            return 500, {"error": ("The desk could not record that fact, so "
                                   "nothing was proposed.")}
        self._audit("memory.capture", target="engine", detail="1 proposal")
        return 201, {"tool": "propose_fact", "entryId": entry_id}

    def _engine_write_refusal(self, action: str, noun: str) -> tuple[int, dict] | None:
        """The write gate: may_act as today, with a plain refusal otherwise.

        The engine's writes ride the same autonomy rule as every other
        thing the desk does by itself; the refusal names what stayed
        untouched. None means the write may run.
        """
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None or not may_act(settings, action):
            return self._store_missing(
                "settings", status=409,
                sentence=(f"Autonomy is off in settings, so the desk's engine "
                          f"cannot make {noun}.")).as_json()
        return None

    def _fact_already_held(self, text: str) -> bool:
        """Whether this exact fact is stored, waiting or was already rejected.

        The same shape capture's dedupe keeps: a proposal the desk has
        seen before is refused rather than asked about twice.
        """
        server = self.server  # type: ignore[attr-defined]
        memory, inbox = server.memory, server.inbox
        key = memory_loop.normalize_fact_text(text)
        if memory is not None:
            for fact in memory.all():
                if memory_loop.normalize_fact_text(fact.text) == key:
                    return True
        if inbox is not None:
            for card in [*inbox.waiting(include_snoozed=True), *inbox.dismissed()]:
                if card.kind == KIND_MEMORY_DRAFT and card.draft.strip() \
                        and memory_loop.normalize_fact_text(card.draft) == key:
                    return True
        return False

    def _engine_fact_store(self, memory, text: str) -> str:
        """Store the proposed fact at once (review off) and record its entry.

        The write is store_fact, the one write every fact takes, with
        the engine channel named in the source; the ledger entry is the
        auto-saved shape whose undo deletes exactly this fact. A record
        that fails removes the fact before the refusal answers: a write
        without its ledger entry is not a write this desk keeps.
        """
        server = self.server  # type: ignore[attr-defined]
        outcome = memory_loop.store_fact(
            memory, text, source=f"{memory_loop.AUTO_SOURCE_PREFIX}engine",
            entities=memory_loop.names_in(text))
        ledger = getattr(server, "ledger", None)
        try:
            entry = ledger.record(
                actor="agent-desk",
                action="memory.auto-saved",
                subject=f"memory:{outcome.fact.id}",
                why="Saved a fact the desk proposed, without asking.",
                undo_kind="memory-fact",
                before=json.dumps({"id": int(outcome.fact.id)}).encode("utf-8"),
                detail={"factId": int(outcome.fact.id), "channel": "engine"},
            )
        except Exception:
            memory.remove_facts([outcome.fact.id])
            raise
        self._schedule_observation_pass()
        return entry.id

    def _engine_fact_stage(self, memory, text: str) -> str:
        """Stage the proposed fact as the review card capture makes.

        The card is the memory draft kind the approval flow already
        writes, with the desk named as where it came from; the ledger
        entry's card-added undo dismisses the card, so the proposal
        itself is undoable while it waits. The source excerpt is carried
        as text on the card and created when the fact is approved, so a
        rejected or undone proposal leaves no excerpt behind. A record
        that fails removes the card before the refusal answers.
        """
        server = self.server  # type: ignore[attr-defined]
        names = memory_loop.names_in(text)
        card = server.inbox.add(
            kind=KIND_MEMORY_DRAFT,
            origin=("The desk learned this while working on its own and saved it "
                    "here for your review. Approving adds it to memory; rejecting "
                    "leaves nothing behind."),
            title="The desk suggests a fact" + (
                f": {', '.join(name for name, _type in names)}" if names else ""),
            body="The desk found this while working by itself.",
            action_label="Save to memory",
            draft=text,
            meta={"memoryFact": {
                "kind": "world",
                "occurrence_ts": None,
                "entities": [[name, entity_type] for name, entity_type in names],
                "source_excerpt": f"The desk proposed: {text}",
                "channel": "engine",
                "method": "desk",
            }},
        )
        ledger = getattr(server, "ledger", None)
        try:
            entry = ledger.record(
                actor="agent-desk",
                action="memory.proposed",
                subject=f"memory-draft/{card.id}",
                why="The desk proposed a fact and left it for your review.",
                undo_kind="card-added",
                before=json.dumps(card.to_json(server.inbox.now_ts()),
                                  ensure_ascii=False).encode("utf-8"),
                detail={"cardId": card.id, "channel": "engine"},
            )
        except Exception:
            server.inbox.delete(card.id)
            raise
        return entry.id

    def _send_update_api(self) -> None:
        """Serve the update state, whether the share is set, and the banner."""
        self._send_json(200, update_payload(self.server))  # type: ignore[attr-defined]

    def _update_check(self) -> None:
        """Read the share now, staging only when Install updates is on."""
        server = self.server  # type: ignore[attr-defined]
        from agentdesk.update import run_update, summary

        result = run_update(server)
        if self._is_form_submit():
            body = self._read_json_body() or {}
            self._send_notice_redirect(
                self._form_return_to(body, "/settings#updates"),
                "The update share was checked; the card above shows what "
                "it found.")
            return
        payload = update_payload(server)
        payload.update({key: value for key, value in result.items() if key not in payload})
        self._send_json(200, payload)

    def _update_channel_save(self) -> None:
        """Save the share path, refusing relative paths and parent hops."""
        from pathlib import PureWindowsPath

        body = self._read_json_body() or {}
        raw = body.get("path")
        if not isinstance(raw, str):
            self._send_json(400, {"error": 'expected {"path": "<folder>"}'})
            return
        path = raw.strip()
        if path:
            pure = PureWindowsPath(path)
            absolute = (path.startswith("\\") or path.startswith("//")
                        or pure.is_absolute() or os.path.isabs(path))
            if not absolute or ".." in pure.parts:
                self._send_json(400, {"error": "expected an absolute folder path without .."})
                return
        settings = self.server.settings  # type: ignore[attr-defined]
        settings.set("update_channel", path)
        if self._is_form_submit():
            self._send_notice_redirect(
                self._form_return_to(body, "/settings#updates"),
                "The update share is saved.")
            return
        self._send_json(200, {"saved": True, "path": path})

    def _send_agent_loop_api(self) -> None:
        """Serve the agent loop's status payload (spec 016 sections 6.2 and 7)."""
        loop = self._require_store(getattr(self.server, "agent_loop", None), "agent loop")
        if loop is None:
            return
        self._send_json(200, loop.status())

    def _agent_loop_run(self) -> None:
        """Start one full pass now, on the loop's own claim.

        The answer is immediate: {"started": true}, or 409 when a pass is
        already running. A plain form post (the settings page's Run now
        button) goes back to the agent section instead.
        """
        loop = self._require_store(getattr(self.server, "agent_loop", None), "agent loop")
        if loop is None:
            return
        started = loop.run_now()
        if self._is_form_submit():
            body = self._read_json_body() or {}
            target = self._form_return_to(body, "/settings#agent")
            if started:
                self._send_notice_redirect(
                    target,
                    "One pass started; its steps appear under Agent shortly.")
            else:
                self._send_redirect(target)
            return
        if not started:
            self._send_json(409, {"error": "A pass is already running."})
            return
        self._send_json(200, {"started": True})

    def _send_preferences_values(self) -> None:
        """Serve the stored insight preferences."""
        self._send_json(200, PreferenceStore(default_data_dir()).read())

    def _send_layout_api(self) -> None:
        """Serve the full layout, hidden cards included.

        That is the recoverable truth behind the payload's visible-only listing.
        """
        self._send_json(200, {
            "cards": resolved_layout(
                self.server.layout,  # type: ignore[attr-defined]
                enabled_plugin_ids(self.server)),
        })

    def _plugin_setup_get_request(self) -> None:
        """Read the plugin setup view a path under /api/plugins/ names with instances."""
        path, _, _query = self.path.partition("?")
        self._plugin_setup_get(path)

    def _plugin_record_get(self, rest: str) -> None:
        """Serve one plugin record envelope, or its not-found body."""
        self._send_json(200, self._plugin_record_or_404(rest))

    def _send_styles_asset(self) -> None:
        """Serve the dashboard stylesheet."""
        self._send_bytes(200, pages.STYLES.encode("utf-8"), "text/css; charset=utf-8")

    def _send_app_js_asset(self) -> None:
        """Serve the dashboard client script."""
        self._send_bytes(200, pages.APP_JS.encode("utf-8"), "text/javascript; charset=utf-8")

    def _send_theme_boot_asset(self) -> None:
        """Serve the script that applies the saved theme before paint."""
        self._send_bytes(200, pages.THEME_BOOT_JS.encode("utf-8"), "text/javascript; charset=utf-8")

    def _send_marketplace_shell_request(self) -> None:
        """Serve the SPA shell for a marketplace deep link.

        Deep links are the SPA's routes, so the server hands the shell to every known
        marketplace GET after the session gate. An unknown marketplace path gets the
        same shell with a 404 status, so a typo is honest to clients and crawlers; /api
        paths still answer 404 elsewhere and never the shell. A notice query arrives
        from the plugin lifecycle actions' redirect chain; the shell renders it
        server-side, so the sentence is on the page with JavaScript off too.
        """
        path, _, query = self.path.partition("?")
        notice = parse_qs(query).get("notice", [""])[0] if query else ""
        self._send_marketplace_shell(200 if _known_marketplace_path(path) else 404,
                                     notice=notice)

    def _preferences_write(self) -> None:
        """Store the posted insight preferences, reporting a rejection as JSON."""
        try:
            self._send_json(200, PreferenceStore(default_data_dir()).write(self._read_json_body()))
        except PreferencesError as exc:
            self._send_json(exc.status, {"error": exc.message, "code": exc.code})

    def _insight_draft(self) -> None:
        """Draft the press reply for the posted insight body."""
        body = self._read_json_body()
        kind = str((body or {}).get("kind") or "")
        try:
            answer = draft_reply(
                self.server,
                body,
                preferences=PreferenceStore(default_data_dir()).read(),
                complete=self._insight_complete(),
            )
        except InsightError as exc:
            # The no-JS twin audits both outcomes as insight.press; the
            # JSON door writes the same rows, a refusal as an error.
            self._audit("insight.press", target=kind or "press",
                        detail=exc.code, status="error")
            self._send_json(exc.status, {"error": exc.message, "code": exc.code})
            return
        thread = answer.get("thread") if isinstance(answer.get("thread"), dict) else None
        staged = str(answer.get("cardId") or "") if answer.get("staged") else ""
        # The audit names the thread and the source, never the words: a
        # draft is the user's to send, so the log records the act alone.
        self._audit(
            "insight.press",
            target=str(thread.get("id")) if thread is not None else (kind or "press"),
            detail=kind + ":" + str(answer.get("source") or "none")
            + (": staged " + staged if staged else ""),
        )
        self._send_json(200, answer)

    def _excel_watch_pick(self) -> None:
        """Open the workbook picker and return the chosen path."""
        excel = self._require_store(self.server.excel, "excel watch")
        if excel is None:
            return
        self._send_json(200, {"path": self.server.pick_workbook()})  # type: ignore[attr-defined]

    def _excel_watch_register(self) -> None:
        """Validate and register the workbook path the card submitted."""
        excel = self._require_store(self.server.excel, "excel watch")
        if excel is None:
            return
        body = self._read_json_body()
        if body is None or not isinstance(body.get("path"), str) or not body["path"].strip():
            self._send_json(400, {"error": "expected {\"path\": \"...\"}"})
            return
        # Reject nonsense before registering: the picker is the only
        # connect path, so this error text is the feedback loop.
        problem = workbook_path_problem(body["path"].strip())
        if problem:
            self._send_json(400, {"error": problem})
            return
        excel.register(body["path"].strip())
        excel.start_polling()
        self._send_json(200, excel.status())

    def _excel_watch_retest(self) -> None:
        """Re-test the registered workbook and return the watch status."""
        excel = self._require_store(self.server.excel, "excel watch")
        if excel is None:
            return
        excel.retest()
        self._send_json(200, excel.status())

    def _commitment_check(self) -> None:
        """Toggle one commitment checkbox on the calendar bridge."""
        calendar = self._require_store(self.server.calendar, "calendar bridge")
        if calendar is None:
            return
        body = self._read_json_body()
        if body is None or not isinstance(body.get("eventId"), str):
            self._send_json(400, {"error": "expected {\"eventId\": \"...\", \"idx\": n, \"checked\": bool}"})
            return
        calendar.toggle_check(
            body["eventId"], int(body.get("idx", 0)), bool(body.get("checked"))
        )
        self._send_json(200, {"ok": True})

    def _calendar_bridge_retest(self) -> None:
        """Re-test the calendar bridge and return its status."""
        calendar = self._require_store(self.server.calendar, "calendar bridge")
        if calendar is None:
            return
        calendar.retest()
        self._maybe_briefs()
        self._send_json(200, calendar.status())

    def _calendar_bridge_pick(self) -> None:
        """Open the calendar picker and return the chosen path."""
        calendar = self._require_store(self.server.calendar, "calendar bridge")
        if calendar is None:
            return
        self._send_json(200, {"path": self.server.pick_calendar()})  # type: ignore[attr-defined]

    def _calendar_bridge_path(self) -> None:
        """Store the explicit calendar path the card submitted, then re-poll."""
        calendar = self._require_store(self.server.calendar, "calendar bridge")
        if calendar is None:
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

    def _calendar_bridge_upload(self) -> None:
        """Store the uploaded calendar document and point the bridge at it."""
        calendar = self._require_store(self.server.calendar, "calendar bridge")
        if calendar is None:
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

    def _calendar_bridge_reset(self) -> None:
        """Clear the explicit calendar path, re-poll and return the status."""
        calendar = self._require_store(self.server.calendar, "calendar bridge")
        if calendar is None:
            return
        calendar.clear_explicit_path()
        calendar.retest()
        self._maybe_briefs()
        self._send_json(200, calendar.status())

    def _research_ask(self) -> None:
        """Run one sourced research turn and store its transcript in memory."""
        question = self._ask_question_from_body()
        if not question:
            self._send_json(400, {"error": "expected {\"question\": \"...\"}"})
            return
        self._log_activity("research", question)
        answer = self._run_llm_turn(question, summary_mode=True)
        summary = getattr(answer, "summary", "") if answer.status == "ok" else ""
        self._capture_memory(
            "research",
            f"Research question: {question}" + (f"\nSourced summary: {summary}" if summary else ""),
            question,
            use_model=answer.status == "ok",
        )
        self._send_json(200, answer.to_json())

    def _inbox_card_add(self) -> None:
        """Add one inbox card from the posted body and return it."""
        if self._require_store(self.server.inbox, "inbox") is None:  # type: ignore[attr-defined]
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

    def _inbox_accept(self, card_id: str) -> None:
        """Accept the inbox card named in the path."""
        self._inbox_decide(card_id, "accept")

    def _inbox_dismiss(self, card_id: str) -> None:
        """Dismiss the inbox card named in the path."""
        self._inbox_decide(card_id, "dismiss")

    def _memory_edit_rest(self, rest: str) -> None:
        """Edit the fact whose id the path names between /memory/ and /edit."""
        self._memory_edit(_memory_id_from_path("/memory/" + rest + "/edit", "/edit"))

    def _memory_delete_rest(self, rest: str) -> None:
        """Delete the fact whose id the path names between /memory/ and /delete."""
        self._memory_delete(_memory_id_from_path("/memory/" + rest + "/delete", "/delete"))

    def _memory_remove_preview(self) -> None:
        """Preview which memory entries the posted removal would delete."""
        self._memory_remove(preview=True)

    def _memory_remove_apply(self) -> None:
        """Delete the memory entries the posted body names."""
        self._memory_remove(preview=False)

    def _inbox_consolidate(self) -> None:
        """Run the repetition detector and return its consolidated cards."""
        if self._require_store(self.server.consolidator, "repetition detector") is None:  # type: ignore[attr-defined]
            return
        self._send_json(200, self.server.consolidator.consolidate())  # type: ignore[attr-defined]

    def _skill_run_rest(self, rest: str) -> None:
        """Run the repetition skill whose id the path names."""
        skill_id = _skill_id_from_path(rest)
        if skill_id is None:
            self._send_error_page(404, "Nothing here",
                                  "No skill lives at this address.")
            return
        self._skill_run(skill_id)

    def _skill_undo_rest(self, rest: str) -> None:
        """Undo the last run of the repetition skill whose id the path names."""
        skill_id = _skill_id_from_path(rest)
        if skill_id is None:
            self._send_error_page(404, "Nothing here",
                                  "No skill lives at this address.")
            return
        self._skill_undo(skill_id)

    def _plugins_page_action_request(self) -> None:
        """Hand a two-segment /plugins/<id>/<action> POST to the plugins page.

        The pattern row replaces the original slash-count test, which accepted exactly
        this shape and nothing deeper.
        """
        path, _, _query = self.path.partition("?")
        self._plugins_page_action(path)

    def _mail_draft_rest(self, rest: str) -> None:
        """Draft a reply for the mail message named in the path."""
        if not self._source_allowed("mail_enabled"):
            self._send_json(409, {"error": "Mail digest is off in settings.", "reconnect": "/settings"})
            return
        self._mail_draft(unquote(rest))

    def _plugin_api_post(self) -> None:
        """Hand a plugin runtime POST to the plugin dispatcher."""
        path, _, _query = self.path.partition("?")
        plugins = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            self._send_json(503, {"error": "plugins:unavailable",
                                  "message": "no plugin runtime is configured"})
            return
        try:
            self._dispatch_plugin_post(plugins, path, self._read_json_body() or {})
        except PluginError as exc:
            self._send_json(exc.status, {"error": exc.code, "message": str(exc)})

    def _assistant_ask(self) -> None:
        """Answer one assistant question, as JSON or a form redirect."""
        question = self._ask_question_from_body()
        if not question:
            if self._is_form_submit():
                typed = str((self._read_json_body() or {}).get("question", ""))
                self._send_assistant_page(
                    notice="Type a question first: the box was empty, so nothing was sent.",
                    notice_kind="alert", question=typed,
                )
                return
            self._send_json(400, {"error": "expected a question"})
            return
        self._log_activity("assistant", question)
        answer = self._run_llm_turn(question, summary_mode=False)
        reply = answer.reply if answer.status == "ok" else ""
        self._capture_memory(
            "assistant",
            f"You: {question}" + (f"\nAssistant: {reply}" if reply else ""),
            question,
            use_model=answer.status == "ok",
        )
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            threadlog.append(self.server.audit_conn, "user", question)  # type: ignore[attr-defined]
            text = answer.reply if answer.status == "ok" else f"[degraded] {answer.cause}"
            threadlog.append(self.server.audit_conn, "assistant", text)  # type: ignore[attr-defined]
        if self._is_form_submit():
            if answer.status == "ok":
                self._send_notice_redirect("/assistant", "Your answer is below.")
            else:
                self._send_notice_redirect(
                    "/assistant",
                    f"The AI could not answer: {answer.cause} Your "
                    "question is kept in the conversation below; try "
                    "again when the endpoint is back.",
                    "alert")
            return
        self._send_json(200, answer.to_json())

    def _is_form_submit(self) -> bool:
        """Whether this POST came from a plain HTML form rather than fetch.

        The test is the urlencoded media type appearing in Content-Type; the branches
        that choose between a redirect and JSON consult it.
        """
        return "application/x-www-form-urlencoded" in (self.headers.get("Content-Type") or "")

    def _respond_form_or_json(self, page: str, payload: dict,
                              status: int = 200) -> None:
        """The one form-versus-JSON answer.

        A plain HTML form post (no JavaScript) gets the 303 back to the
        page it came from, a refusal riding the query as a ?notice=
        sentence; a fetch client gets the JSON payload at `status`. The
        no-JS half is an accessibility commitment, never cut.
        """
        if self._is_form_submit():
            self._send_redirect(page)
            return
        self._send_json(status, payload)

    def _ask_question_from_body(self) -> str | None:
        """The trimmed question field of the JSON body, or None.

        None covers a missing body as well as a blank or non-string question, which
        callers turn into a 400 naming the shape they wanted.
        """
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
        """Answer one question, degraded rather than broken when the endpoint is off.

        A disabled endpoint setting short-circuits to a degraded answer carrying the
        explanation and makes no call at all. Otherwise the context is built from the
        live Excel and calendar status, with recalled facts attached to assistant turns
        and left out of research turns. The research variant also saves a successful
        summary for the plugin card that reads it later; a failed attempt is not stored,
        because the store holds what research concluded, never what it tried.
        """
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
        llm, endpoint, model = self._effective_llm("assistant")
        common = {
            "llm": llm,
            "audit_conn": server.audit_conn,
            "endpoint": endpoint,
            "model": model,
        }
        if summary_mode:
            answer = research(question, context, **common)
            # The panel's sourced answers persist (#64): a plugin's
            # research card reads the latest one later, without any
            # endpoint call of its own. Failures are not stored; the
            # store is what research concluded, never what it tried to.
            if answer.status == STATUS_OK and server.research_store is not None:
                server.research_store.save(answer.summary, answer.sources)
                # A research tile set to "when it changes" follows the save.
                _refresh_plugins_on(server, "research")
            return answer
        return assistant_reply(question, context, **common)

    def _facts_block(self, question: str) -> str:
        """The bounded recalled-facts block for the assistant prompt,
        ranked against the user's question. Recall only: this path never
        creates a fact; the bounds live in memory/service. A locked
        memory store (ticket #94), or one that cannot be read just now
        (a transient lock), contributes no block: the assistant keeps
        answering, the bank is never read in plaintext. The semantic
        half is derived per turn like every memory action (the review's
        finding 5): the assistant's recall gains the vector leg on the
        same terms as the memory page's, not only after some memory
        route happens to run first."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return ""
        self._configure_memory_embeddings()
        try:
            return build_facts_block(memory.recall(question))
        except Exception:  # noqa: BLE001 - recall must never take the answer down
            LOG.warning("the memory store could not be read just now;"
                        " the answer proceeds without recalled facts")
            return ""

    def _job_resolution(self, job: str) -> Resolution | None:
        """The pure resolution for one job, or None when nothing serves it.

        The keys store may be absent (its sqlite could not open), which is
        exactly an empty store's answer: no connections, no bindings, only
        the environment leg and the named unbound error remain.
        """
        server = self.server  # type: ignore[attr-defined]
        return _server_resolution(server, job)

    def _effective_llm(self, job: str = DEFAULT_JOB) -> tuple:
        """The resolution hub (spec 018 #233): the client, the serving
        name and the model for one job's next call.

        Every model call-site in the desk asks here, passing its job. The
        order is the spec's, resolved per call: the job's binding, the
        default binding, the single enabled connection, then the
        environment with the saved settings rows over it (config.env
        rides that leg; saved wins over env, the documented precedence).
        A saved connection serves through its own base URL, its keychain
        key and its gateway headers, stamps the row's last_used_at, and
        answers to its label, so every llm.* audit row names it. An
        unbound job gets a client that raises LlmUnavailable naming the
        job, unless a client was injected at construction: an injected
        client is never silently replaced.
        """
        server = self.server  # type: ignore[attr-defined]
        return _job_llm_parts(server, job)

    def _declared_length(self) -> int:
        """The Content-Length header as an int, 0 when absent or malformed.
        The one place the header is parsed; everything else reads this."""
        try:
            return int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return 0

    def _drain_body(self, limit: int = MAX_BODY_BYTES) -> bytes:
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
        plan = body_drain_plan(length, limit)
        if plan == "close":
            self._close_with_response = True
            self.close_connection = True
            return b""
        if plan == "discard":
            self.rfile.read(length)
            return b""
        return self.rfile.read(length)  # stash

    def _read_json_body(self) -> dict | None:
        """The request body as a dict, or None when nothing usable arrived.

        A form-encoded post is decoded as its fields; anything else is parsed as JSON,
        and an empty, undecodable, unparsable or non-object body yields None so each
        caller can answer 400 with the shape it expected.
        """
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
        """Whether the request carries a session cookie the store still accepts.

        Only the cookie is consulted here; the Host and Origin guard is enforced
        separately by the gate.
        """
        store: SessionStore = self.server.sessions  # type: ignore[attr-defined]
        return store.validate(session_id_from_cookie(self.headers.get("Cookie")))

    def _handle_auth(self, token: str) -> None:
        """Redeem a start-link token for a session cookie.

        A token the store will not exchange gets the 403 page; a good one sets the
        cookie and redirects 303 to the dashboard, so the token does not stay in the
        address bar.
        """
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
        """Render the dashboard: one widget per source, in the page's fixed order.

        Each source resolves to exactly one card however it is doing, so a source that
        is off, unconfigured, unavailable or live still takes its slot and the layout
        never shifts. Every mode comes from build_dashboard_state, the same state the
        JSON payload projects, and plugin cards ride along already carrying their
        insight reading. Rendering is a pure read, so a page view never spends a
        plugin's pilot view.
        """
        state = build_dashboard_state(self.server)
        now = state.now
        widgets: list = []
        if state.sales.mode == "disabled":
            widgets.append(render_sales_disabled(now))
        elif state.sales.mode == "live" and state.sales.status is not None:
            widgets.append(render_sales_widget(state.sales.status))
        else:
            widgets.append(render_sales_unconfigured(now))
        if state.commitments.mode == "disabled":
            widgets.append(render_commitments_widget({"state": "disabled"}, now))
        elif state.commitments.mode == "live" and state.commitments.status is not None:
            commitments = render_commitments_widget(state.commitments.status, now)
            widgets.append(
                commitments if commitments is not None else render_commitments_unavailable(now)
            )
        else:
            widgets.append(render_commitments_unavailable(now))
        if state.research.enabled:
            widgets.append(render_research_widget(state.research.last_answered_ts, now))
        else:
            widgets.append(render_research_disabled(now))
        widgets += [self._plugin_widget(card) for card in state.plugin_cards]
        widgets.append(
            pages.render_decisions_widget(
                list(state.recommendations), now, _setup_decisions(state)
            )
        )
        page = pages.render_dashboard(
            widgets,
            state.version,
            _greeting(now),
            now.strftime("%A, %d %B, %H:%M. "),
            inbox_count=state.inbox_waiting,
            skills=list(state.skills),
            connected_sources=state.sources_connected,
            banner=(state.update or {}).get("banner") or "",
            sample=state.sample,
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_sales_status(self) -> None:
        """The sales widget's status as JSON, straight from the Excel watcher.

        503 when no watcher exists: the widget's shape belongs to the watcher, and
        inventing an empty one here would look like a connected source with no data.
        """
        excel = self._require_store(self.server.excel, "excel watch")
        if excel is None:
            return
        self._send_json(200, excel.status())

    def _send_commitments_status(self) -> None:
        """The commitments widget's status as JSON, from the calendar bridge.

        503 when no bridge exists, since an unbuilt collaborator is not the same thing
        as a source that happens to be empty.
        """
        calendar = self._require_store(self.server.calendar, "calendar bridge")
        if calendar is None:
            return
        self._send_json(200, calendar.status())

    def _send_assistant_page(self, notice: str = "", notice_kind: str = "status",
                             question: str = "") -> None:
        """Render the assistant page from the stored conversation.

        The audit store holds every kind of action, so the turns come from the thread
        log's own reader rather than from the raw table; without a store the page opens
        empty instead of failing. A form post's outcome rides the query as `notice`
        (and `notice_kind` for a failure), and a refusal's typed question rides
        `question`, so the page says what happened and keeps the words.
        """
        query = parse_qs(self.path.partition("?")[2])
        notice = notice or query.get("notice", [""])[0]
        notice_kind = query.get("notice_kind", [notice_kind])[0]
        question = question or query.get("question", [""])[0]
        turns = []
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            turns = threadlog.turns(self.server.audit_conn)  # type: ignore[attr-defined]
        page = render_assistant_page(
            turns, agentdesk.__version__, inbox_count=self._inbox_waiting_count(),
            ai_connected=_server_resolution(self.server, "assistant") is not None,
            notice=notice, notice_kind=notice_kind, question=question)
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_agents_page(self, notice: str = "", notice_kind: str = "status",
                          typed_agent: str = "", typed_brief: str = "") -> None:
        """Render the agents page: the roster with a run form per agent,
        and the run history with each run's receipt.

        The history reads the store's newest-first rows; a store that
        could not open renders the roster with the honest absent-history
        note rather than an empty history that would claim no run ever
        happened. A form post's outcome rides the query as `notice`, and
        a refusal keeps the typed brief through `agent` and `brief`.
        """
        query = parse_qs(self.path.partition("?")[2])
        notice = notice or query.get("notice", [""])[0]
        notice_kind = query.get("notice_kind", [notice_kind])[0]
        typed_agent = typed_agent or query.get("agent", [""])[0]
        typed_brief = typed_brief or query.get("brief", [""])[0]
        server = self.server  # type: ignore[attr-defined]
        runs = (
            server.agents.recent() if server.agents is not None else []
        )
        ready, sentence = self._presentation_endpoint()
        research_url = ""
        if server.settings is not None:
            research_url = server.settings.get("research_provider_url") or ""
        resolved = self._job_resolution("research-web")
        connection_serves = resolved is not None and resolved.connection is not None
        research_ready = (
            bool(research_url)
            or getattr(server, "research_fetch", None) is not None
            or connection_serves
        )
        page = render_agents_page(
            ROSTER, runs, agentdesk.__version__,
            inbox_count=self._inbox_waiting_count(),
            history_available=server.agents is not None,
            packs=self._presentation_packs(),
            endpoint_ready=ready,
            endpoint_sentence="" if ready else sentence,
            research_ready=research_ready,
            research_sentence="" if research_ready else "Web research needs a provider URL in settings.",
            notice=notice, notice_kind=notice_kind,
            typed_agent=typed_agent, typed_brief=typed_brief,
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _agents_run(self) -> None:
        """Run one agent over one brief and record the run honestly.

        The named refusals come first (unknown agent, blank or oversize
        brief), so nothing reaches memory or the endpoint that the
        roster would not own. A run is then recall, one prompt, one
        call: the endpoint switched off short-circuits with the standing
        cause and recalls nothing (no prompt was built), every other
        failure is the runner's degraded outcome with the pinned cause.
        A form submit lands back on the page; JSON returns the run.
        """
        server = self.server  # type: ignore[attr-defined]
        body = self._read_json_body()
        agent_id = body.get("agent") if body is not None else None
        if agent_id == "presentation":
            self._presentation_run(body or {})
            return
        brief = body.get("brief") if body is not None else None
        kind = find_agent(agent_id) if isinstance(agent_id, str) else None
        typed_brief = brief if isinstance(brief, str) else ""
        if kind is None:
            if self._is_form_submit():
                self._send_agents_page(
                    notice="That agent is not on the roster; the page lists the "
                           "agents this desk can run.",
                    notice_kind="alert", typed_agent=str(agent_id or ""),
                    typed_brief=typed_brief)
                return
            self._send_json(
                400,
                {"error": "unknown agent id; the /agents page lists the agents"
                          " this desk can run"},
            )
            return
        if not isinstance(brief, str) or not brief.strip():
            if self._is_form_submit():
                self._send_agents_page(
                    notice="Type a brief first: the box was empty, so nothing was run.",
                    notice_kind="alert", typed_agent=kind.id,
                    typed_brief=typed_brief)
                return
            self._send_json(
                400,
                {"error": "expected {\"agent\": \"worksheet-brief\","
                          " \"brief\": \"a short task brief\"}"},
            )
            return
        brief = brief.strip()
        if len(brief) > BRIEF_MAX_CHARS:
            if self._is_form_submit():
                self._send_agents_page(
                    notice=f"The brief is longer than {BRIEF_MAX_CHARS} "
                           "characters; shorten it.",
                    notice_kind="alert", typed_agent=kind.id,
                    typed_brief=typed_brief[:BRIEF_MAX_CHARS])
                return
            self._send_json(
                400,
                {"error": f"the brief is longer than {BRIEF_MAX_CHARS}"
                          " characters; shorten it"},
            )
            return
        if server.agents is None:
            self._send_store_missing(
                self._store_missing(
                    "agents store",
                    notice=("The run history is not available right now, so the "
                            "brief was not run.")),
                render=lambda notice: self._send_agents_page(
                    notice=notice, notice_kind="alert", typed_agent=kind.id,
                    typed_brief=typed_brief))
            return
        if not self._source_allowed("endpoint_enabled"):
            result = endpoint_off_run()
        else:
            result = run_agent(
                kind, brief, self._effective_llm("agents")[0],
                ranked_facts=self._agent_fact_ranks(kind, brief),
                excel_status=(
                    server.excel.status() if server.excel is not None else None
                ),
            )
        run_id = server.agents.record(
            kind.id, brief, result.status, cause=result.cause,
            reply=result.reply, artifact=result.artifact, facts=result.facts,
        )
        if result.facts:
            count = len(result.facts)
            used = f"used {count} recalled fact" + ("" if count == 1 else "s")
        else:
            used = "used nothing"
        self._audit(
            "agents.run", target=kind.id,
            status="ok" if result.status == AGENT_STATUS_OK else "error",
            detail=f"status {result.status}; {used}",
        )
        payload = {
            "id": run_id,
            "agent": kind.id,
            "status": result.status,
            "cause": result.cause,
            "reply": result.reply,
            "artifact": result.artifact,
            "facts": result.facts,
        }
        if self._is_form_submit():
            if result.status == AGENT_STATUS_OK:
                notice = (f"Ran {kind.name}. Its receipt is at the top of "
                          "the run history.")
                kind_word = "status"
            else:
                notice = (f"Ran {kind.name}, but it came back degraded: "
                          f"{result.cause} Its row is at the top of the run "
                          "history.")
                kind_word = "alert"
            self._send_notice_redirect("/agents", notice, kind_word)
            return
        self._send_json(200, payload)

    def _presentation_packs(self) -> list:
        """Shipped packs plus anything installed under the user templates dir."""
        return load_packs()

    def _presentation_endpoint(self) -> tuple[bool, str]:
        """Whether a presentation may run, and the sentence when it may not.

        The switch uses the pinned endpoint-off sentence. Configuration is
        the hub's answer now (spec 018): a job binding, a default binding,
        a single saved connection, the saved settings rows or the startup
        endpoint each count; only a fully unbound presentations job uses
        the unconfigured sentence.
        """
        server = self.server  # type: ignore[attr-defined]
        settings = server.settings
        enabled = True if settings is None else bool(settings.get("endpoint_enabled"))
        configured = (
            self._job_resolution("presentations") is not None
            or (bool(settings.get("llm_base")) if settings is not None else False)
            or bool(getattr(server, "llm_endpoint", ""))
        )
        if not enabled:
            return False, ENDPOINT_OFF_CAUSE
        if not configured:
            return False, NO_ENDPOINT_CAUSE
        return True, ""

    def _presentation_run(self, body: dict) -> None:
        """Record the template, variant and recipe, and write the deck.

        A run with the endpoint off or unconfigured is the named degraded
        row and no file. A run that names a pack the loader does not have
        is a 400, and nothing is stored.
        """
        server = self.server  # type: ignore[attr-defined]
        brief = body.get("brief")
        typed_brief = brief if isinstance(brief, str) else ""
        if not isinstance(brief, str) or not brief.strip():
            if self._is_form_submit():
                self._send_agents_page(
                    notice="Type a topic first: the box was empty, so no deck was built.",
                    notice_kind="alert", typed_agent="presentation",
                    typed_brief=typed_brief)
                return
            self._send_json(
                400,
                {"error": "expected {\"agent\": \"presentation\","
                          " \"brief\": \"a short task brief\"}"},
            )
            return
        brief = brief.strip()
        if len(brief) > BRIEF_MAX_CHARS:
            if self._is_form_submit():
                self._send_agents_page(
                    notice=f"The topic is longer than {BRIEF_MAX_CHARS} "
                           "characters; shorten it.",
                    notice_kind="alert", typed_agent="presentation",
                    typed_brief=typed_brief[:BRIEF_MAX_CHARS])
                return
            self._send_json(
                400,
                {"error": f"the brief is longer than {BRIEF_MAX_CHARS}"
                          " characters; shorten it"},
            )
            return
        if server.agents is None:
            self._send_store_missing(
                self._store_missing(
                    "agents store",
                    notice=("The run history is not available right now, so no "
                            "deck was built.")),
                render=lambda notice: self._send_agents_page(
                    notice=notice, notice_kind="alert", typed_agent="presentation",
                    typed_brief=typed_brief))
            return
        ready, sentence = self._presentation_endpoint()
        if not ready:
            run_id = server.agents.record(
                "presentation", brief, "degraded", cause=sentence,
            )
            self._audit("agents.run", target="presentation", status="error",
                        detail=f"status degraded; {sentence}")
            self._finish_agent_run(run_id, "presentation", "degraded", sentence, "", None, [])
            return
        template = body.get("template")
        variant = body.get("variant") or "dark"
        recipe = body.get("recipe")
        packs = {pack.id: pack for pack in self._presentation_packs()}
        pack = packs.get(template) if isinstance(template, str) else None
        recipe_ok = False
        if pack is not None and isinstance(recipe, str):
            recipe_ok = any(path.endswith(f"/{recipe}.json") or path == f"{recipe}.json"
                            for path in pack.recipes)
        if pack is None or variant not in pack.variants or not recipe_ok:
            self._send_json(
                400,
                {"error": "choose a template, a variant and a recipe from the"
                          " /agents page"},
            )
            return
        recipe_doc = pack.recipe(recipe)
        shell_path = pack.shell_path(variant)
        if recipe_doc is None or shell_path is None:
            self._send_json(
                400,
                {"error": "that template has no shell for the chosen variant"},
            )
            return
        enabled = self._presentation_sources(body)
        sources = gather(
            self._agent_fact_ranks_plain(brief) if "memory" in enabled else [],
            self._excel_status() if "excel-report" in enabled else None,
            self._page_watch() if "competitor-watch" in enabled else None,
            enabled,
        )
        timeout = timeout_seconds(
            server.settings.get("presentation_timeout_s") if server.settings is not None else "30"
        )
        llm = self._effective_llm("presentations")[0]
        delivered = None
        cause = ""
        try:
            parsed = parse_plan(call_model(llm, plan_prompt(brief, recipe_doc), timeout), recipe_doc)
            if not parsed:
                raise ValueError("malformed plan")
            deck_title, planned = parsed
            if str(body.get("use_research", "")).lower() in ("1", "true", "on"):
                self._pause_for_research(
                    server, brief, pack, variant, recipe, planned, sources, timeout, deck_title,
                )
                return
            delivered, cause = run_fill(
                pack, variant, recipe_doc, planned, sources, brief, deck_title,
                llm, timeout, self._presentation_dir(),
                runner=getattr(server, "presentation_runner", None),
            )
        except (OSError, ValueError, LlmUnavailable) as exc:
            cause = fill_cause(exc)
        if delivered is None:
            run_id = server.agents.record("presentation", brief, "degraded", cause=cause)
            self._audit("agents.run", target="presentation", status="error",
                        detail=f"status degraded; {cause}")
            self._finish_agent_run(run_id, "presentation", "degraded", cause, "", None, [])
            return
        fit_notes = delivered["fit"]
        rendered = delivered["rendered"]
        prefix = delivered["folder"]
        artifact = deck_artifact(
            pack, variant, recipe, phase="written", folder=prefix, rendered=rendered,
            sources=receipt_lines(sources), fit=fit_notes,
        )
        facts = [
            {"id": row["id"], "text": row["text"]}
            for row in sources if row["kind"] == "memory"
        ]
        run_id = server.agents.record(
            "presentation", brief, "ok", artifact=artifact, facts=facts,
        )
        used = ", ".join(f"{row['kind']}:{row['id']}" for row in sources) or "none"
        self._audit(
            "agents.run", target="presentation", status="ok",
            detail=(f"status ok; template {pack.id}@{pack.version}; "
                    f"variant {variant}; recipe {recipe}; sources {used}; "
                    f"renderer {rendered['renderer']}"),
        )
        self._finish_agent_run(run_id, "presentation", "ok", "", "", artifact, facts)

    def _pause_for_research(self, server, brief, pack, variant, recipe, planned, sources, timeout,
                            deck_title: str = "") -> None:
        """Store the gathered web sources and wait. The request is not held.

        The provider rides the research-web job's resolution (spec 018):
        a bound connection serves with its own base URL and key, and only
        with no connection does the legacy research-provider settings row
        keep serving (its migration is ticket #234).
        """
        fetch = getattr(server, "research_fetch", None)
        url = ""
        key = ""
        resolved = self._job_resolution("research-web")
        if resolved is not None and resolved.connection is not None:
            url = resolved.connection.base_url
            key = server.keychain.fetch(resolved.connection.id) or ""
            try:
                server.keys.record_use(resolved.connection.id)
            except Exception:  # noqa: BLE001 - the stamp never fails the fetch
                LOG.debug("could not stamp last_used_at", exc_info=True)
        elif server.settings is not None:
            url = server.settings.get("research_provider_url") or ""
            key = server.settings.get("research_provider_key") or ""
        titles = [section["title"] for section in planned]
        if fetch is None and not url:
            cause = "Web research needs a provider URL in settings."
            run_id = server.agents.record("presentation", brief, "degraded", cause=cause)
            self._audit("agents.run", target="presentation", status="error",
                        detail=f"status degraded; research unconfigured")
            self._finish_agent_run(run_id, "presentation", "degraded", cause, "", None, [])
            return
        base = deck_artifact(
            pack, variant, recipe, plan=planned, title=deck_title,
            deskSources=sources, timeout=timeout,
        )
        try:
            if fetch is not None:
                rows = list(fetch(brief, titles))[:RESULT_LIMIT]
            else:
                rows = fetch_sources(url, key, brief, titles, timeout=FETCH_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - a failed gather is a named state
            cause = f"Web research failed: {exc}"
            artifact = {**base, "phase": "research-failed", "webSources": []}
            run_id = server.agents.record(
                "presentation", brief, "degraded", cause=cause, artifact=artifact,
            )
            self._audit("agents.run", target="presentation", status="error",
                        detail="status degraded; research failed")
            self._finish_agent_run(run_id, "presentation", "degraded", cause, "", artifact, [])
            return
        web = as_sources(rows, len(sources) + 1)
        artifact = {**base, "phase": "awaiting-review", "webSources": web, "research": True}
        run_id = server.agents.record(
            "presentation", brief, "awaiting-review", artifact=artifact,
        )
        self._audit(
            "agents.run", target="presentation", status="ok",
            detail=(f"status awaiting-review; template {pack.id}@{pack.version}; "
                    f"recipe {recipe}; research on; sources {len(web)}"),
        )
        self._finish_agent_run(run_id, "presentation", "awaiting-review", "", "", artifact, [])

    def _agents_sources(self, rest: str) -> None:
        """Confirm a paused research run and build the deck from the kept sources."""
        server = self.server  # type: ignore[attr-defined]
        try:
            run_id = int(str(rest).strip("/"))
        except ValueError:
            run_id = -1
        run = server.agents.get(run_id) if server.agents is not None and run_id > 0 else None
        artifact = run.get("artifact") if run else None
        phase = artifact.get("phase") if isinstance(artifact, dict) else ""
        if phase == "written":
            self._finish_agent_run(run_id, "presentation", "ok", "", "", artifact, [])
            return
        if phase not in ("awaiting-review", "research-failed"):
            self._send_json(404, {"error": "that run is not waiting on sources"})
            return
        inflight = getattr(server, "presentation_filling", None)
        if inflight is None:
            inflight = set()
            server.presentation_filling = inflight
        if run_id in inflight:
            self._send_json(409, {"error": "that run is already being built"})
            return
        raw = getattr(self, "_raw_body", b"") or b""
        if self._is_form_submit():
            fields = parse_qs(raw.decode("utf-8", "replace"))
            keep = fields.get("keep", [])
            carry_on = (fields.get("continue") or [""])[0]
        else:
            body = self._read_json_body() or {}
            keep = body.get("keep") or []
            if isinstance(keep, str):
                keep = [keep]
            carry_on = str(body.get("continue") or "")
        desk = artifact.get("deskSources") or []
        web = artifact.get("webSources") or []
        if carry_on == "cancel":
            cause = "Cancelled before the deck was built."
            server.agents.update_outcome(run_id, "degraded", artifact, cause)
            self._audit("agents.run", target="presentation", status="error",
                        detail="status degraded; research cancelled")
            self._finish_agent_run(run_id, "presentation", "degraded", cause, "", artifact, [])
            return
        if carry_on == "desk" or phase == "research-failed":
            chosen = []
        else:
            wanted = {str(item) for item in keep}
            chosen = [source for source in web if str(source.get("id")) in wanted]
        inflight.add(run_id)
        try:
            self._fill_paused(run_id, run, artifact, desk + chosen, chosen)
        finally:
            inflight.discard(run_id)

    def _fill_paused(self, run_id, run, artifact, sources, chosen) -> None:
        """Fill and write a paused run. Deselected web sources are not passed in."""
        server = self.server  # type: ignore[attr-defined]
        brief = run.get("brief") or ""
        recipe_name = artifact.get("recipe")
        pack = next((item for item in self._presentation_packs()
                     if item.id == artifact.get("templateId")), None)
        recipe_doc = pack.recipe(recipe_name) if pack is not None else None
        shell_path = pack.shell_path(artifact.get("variant")) if pack is not None else None
        if recipe_doc is None or shell_path is None:
            self._send_json(400, {"error": "the template for that run is no longer installed"})
            return
        timeout = timeout_seconds(artifact.get("timeout") or 30)
        llm = self._effective_llm("assistant")[0]
        try:
            delivered, cause = run_fill(
                pack, artifact.get("variant"), recipe_doc, artifact.get("plan") or [],
                sources, brief, str(artifact.get("title") or ""),
                llm, timeout, self._presentation_dir(),
                runner=getattr(server, "presentation_runner", None),
            )
        except (OSError, ValueError, LlmUnavailable) as exc:
            # The fresh run's ladder catches its whole pipeline, folder
            # creation included; the resume must answer the same way, or a
            # write failure here degrades into the generic 500 instead of
            # an honest run row.
            delivered, cause = None, fill_cause(exc)
        if delivered is None:
            server.agents.update_outcome(run_id, "degraded", None, cause)
            self._finish_agent_run(run_id, "presentation", "degraded", cause, "", None, [])
            return
        rendered = delivered["rendered"]
        prefix = delivered["folder"]
        # The paused card's research fields ride along; its plan and the
        # unkept web sources do not.
        carried = {key: artifact[key] for key in ("title", "deskSources", "timeout")
                   if key in artifact}
        updated = deck_artifact(
            pack, artifact.get("variant"), recipe_name,
            phase="written", folder=prefix, rendered=rendered,
            **carried, sources=receipt_lines(sources), research=True,
            kept=[source.get("id") for source in chosen], fit=delivered["fit"],
        )
        server.agents.update_outcome(run_id, "ok", updated, "")
        kept = ", ".join(str(source.get("id")) for source in chosen) or "none"
        self._audit(
            "agents.run", target="presentation", status="ok",
            detail=(f"status ok; template {pack.id}@{pack.version}; recipe {recipe_name}; "
                    f"research on; kept {kept}"),
        )
        self._finish_agent_run(run_id, "presentation", "ok", "", "", updated, updated["sources"])

    def _finish_agent_run(self, run_id, agent_id, status, cause, reply, artifact, facts) -> None:
        """JSON for a fetch, or a redirect back to the page for a form.

        A form lands on the run history with the outcome in the page's
        status line; a degraded run says its cause there too.
        """
        if self._is_form_submit():
            if status == "ok":
                notice = "Your deck is at the top of the run history."
                kind_word = "status"
            else:
                notice = (f"The run came back degraded: {cause} Its row is at "
                          "the top of the run history.")
                kind_word = "alert"
            self._send_notice_redirect("/agents", notice, kind_word)
            return
        self._send_json(200, {
            "id": run_id,
            "agent": agent_id,
            "status": status,
            "cause": cause,
            "reply": reply,
            "artifact": artifact,
            "facts": facts,
        })

    def _presentation_sources(self, body: dict) -> set[str]:
        """Which desk reads this run keeps.

        A JSON body leaves a missing key on, and turns one off with 0,
        false, or off. A form post includes sources_form, and an
        unchecked box is simply absent, so a missing key is off.
        """
        wanted = {"memory", "excel-report", "competitor-watch"}
        flags = {
            "use_memory": "memory",
            "use_workbook": "excel-report",
            "use_watch": "competitor-watch",
        }
        form = str(body.get("sources_form") or "") == "1"
        for key, source in flags.items():
            if key not in body:
                if form:
                    wanted.discard(source)
                continue
            if str(body[key]).lower() in ("0", "false", "off", ""):
                wanted.discard(source)
        return wanted

    def _agent_fact_ranks_plain(self, brief: str) -> list:
        """Memory facts for a presentation, as {id, text} rows. A store
        that cannot be read just now contributes nothing: the run keeps
        going, like every agents recall."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return []
        self._configure_memory_embeddings()
        try:
            ranked = memory.recall(f"Presentation {brief}")
        except Exception:  # noqa: BLE001 - recall must never take the run down
            LOG.warning("the memory store could not be read just now;"
                        " the run proceeds without recalled facts")
            return []
        return [{"id": fact.id, "text": fact.text} for _score, fact in ranked[:5]]

    def _excel_status(self) -> dict | None:
        """The watched workbook's status, or None when there is no watch."""
        excel = self.server.excel  # type: ignore[attr-defined]
        if excel is None:
            return None
        try:
            return excel.status()
        except Exception:  # noqa: BLE001 - a watch that cannot answer is not read
            return None

    def _page_watch(self) -> dict | None:
        """The latest Page watch snapshot.

        A test may inject `server.page_watch`. Otherwise the snapshot is
        the competitor-watch plugin's http-state.json, the file that
        source writes after a fetch. The newest entry wins.
        """
        server = self.server  # type: ignore[attr-defined]
        supplied = getattr(server, "page_watch", None)
        if isinstance(supplied, dict):
            return supplied
        plugins = getattr(server, "plugins", None)
        root = getattr(plugins, "data_dir", None)
        if root is None:
            return None
        path = Path(root) / "competitor-watch" / "http-state.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(state, dict):
            return None
        best = None
        best_at = ""
        best_url = ""
        for url, entry in state.items():
            if not isinstance(entry, dict):
                continue
            at = str(entry.get("fetchedAt") or entry.get("checkedAt") or "")
            if best is None or at >= best_at:
                best = entry
                best_at = at
                best_url = str(url)
        if best is None:
            return None
        value = best.get("text")
        if not value:
            stored = best.get("value")
            value = "" if stored is None else str(stored)
        text = f"{best_url}: {value}".strip(": ").strip() if best_url else str(value)
        if not text:
            return None
        return {"text": text, "at": best_at}

    def _presentation_dir(self):
        """Where this process writes decks. Tests point it at a temp dir."""
        server = self.server  # type: ignore[attr-defined]
        path = getattr(server, "presentation_dir", None)
        if path is None:
            path = default_data_dir() / "presentation-runs"
            server.presentation_dir = path
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _presentation_tool_urls(self, result: dict) -> dict:
        """Give every file a download address the caller can open next."""
        for key, url_key in (("file", "url"), ("pdf", "pdfUrl")):
            value = result.get(key)
            if isinstance(value, str) and value:
                result[url_key] = "/presentations/files/" + quote(value)
        images = result.get("images")
        if isinstance(images, list) and images:
            result["imageUrls"] = [
                "/presentations/files/" + quote(str(image)) for image in images
            ]
        return result

    def _send_presentation_tools(self) -> None:
        """List the deck tools the shipped and installed packs declare."""
        try:
            tools = tool_catalog(self._presentation_packs())
        except (OSError, ValueError) as exc:
            LOG.warning("presentation tool catalog failed: %s", exc)
            self._send_json(500, {"error": "The deck tools could not be listed."})
            return
        self._send_json(200, {"tools": tools})

    def _presentation_tool_run(self) -> None:
        """Run one declared deck tool. The plugin declares, the host executes."""
        body = self._read_json_body()
        if not isinstance(body, dict):
            self._send_json(400, {"error": "Send a JSON object with a tool name."})
            return
        name = body.get("tool")
        if not isinstance(name, str) or not name.strip():
            self._send_json(400, {"error": "The tool field names the deck tool to run."})
            return
        payload = {key: value for key, value in body.items() if key != "tool"}
        try:
            result = run_tool(
                name.strip(), payload, self._presentation_dir(),
                packs=self._presentation_packs(),
                runner=getattr(self.server, "presentation_runner", None),
            )
        except ToolError as exc:
            self._send_json(exc.status, {"error": exc.message})
            return
        except (OSError, ValueError) as exc:
            LOG.warning("presentation tool %s failed: %s", name, exc)
            self._send_json(500, {"error": "The deck tool failed while writing its files."})
            return
        except Exception:  # noqa: BLE001 - a tool caller gets JSON, not a 500 page
            LOG.exception("presentation tool %s failed", name)
            self._send_json(500, {"error": "The deck tool failed."})
            return
        self._audit("presentation.tool", target=name.strip(),
                    detail=(f"plugin {result['plugin']}; "
                            f"{result.get('file') or result.get('bytes') or ''}"))
        self._send_json(200, self._presentation_tool_urls(result))

    def _presentation_file(self, rest: str) -> None:
        """A deck, PDF or preview the tool wrote, and nothing outside that root."""
        raw = unquote((rest or "").strip("/"))
        try:
            path = resolve_in_root(self._presentation_dir(), raw,
                                   suffixes=(".pptx", ".pdf", ".png"))
        except ToolError as exc:
            self._send_json(exc.status, {"error": exc.message})
            return
        suffix = path.suffix.lower()
        content_type = {
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".pdf": "application/pdf",
            ".png": "image/png",
        }[suffix]
        headers = {"Content-Disposition": f'attachment; filename="{path.name}"'}
        self._audit("presentation.file", target=raw, detail=suffix)
        self._send_bytes(200, path.read_bytes(), content_type, headers)

    def _agents_download(self, rest: str) -> None:
        """The .pptx one run wrote, and nothing else.

        The stored name is a relative path under the presentation
        directory. A name that climbs out of that directory is a 404,
        the same answer as a run that never wrote a file.
        """
        server = self.server  # type: ignore[attr-defined]
        run_id_text = (rest or "").strip("/")
        try:
            run_id = int(run_id_text)
        except ValueError:
            run_id = -1
        run = server.agents.get(run_id) if server.agents is not None and run_id > 0 else None
        artifact = run.get("artifact") if run else None
        part = (parse_qs(self.path.partition("?")[2]).get("part") or ["pptx"])[0] or "pptx"
        rel = None
        if isinstance(artifact, dict):
            if part == "pdf":
                rel = artifact.get("pdf")
            elif part == "pptx":
                rel = artifact.get("file")
            else:
                rel = next((image for image in artifact.get("images") or []
                            if str(image).endswith("/" + part)), None)
        root = self._presentation_dir().resolve()
        path = (root / rel).resolve() if isinstance(rel, str) and rel and ".." not in rel.split("/") else None
        if path is None or root not in path.parents or not path.is_file():
            self._send_json(404, {"error": "this run has no deck to download"})
            return
        kind = part if part in ("pptx", "pdf") else "png"
        self._audit(
            "agents.download", target=str(run.get("agentId", "")),
            detail=f"run {run_id}; {kind}",
        )
        if part == "pdf":
            content_type = "application/pdf"
            filename = "deck.pdf"
        elif part == "pptx":
            content_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            filename = "deck.pptx"
        else:
            content_type = "image/png"
            filename = part if part.endswith(".png") else "slide.png"
        self._send_bytes(
            200, path.read_bytes(), content_type,
            {"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def _agents_template_thumb(self, rest: str) -> None:
        """One pack preview, and only a preview the pack itself names."""
        pack_id, _, filename = (rest or "").partition("/")
        if not filename.endswith(".png") or "/" in filename or not pack_id:
            self._send_json(404, {"error": "no such preview"})
            return
        variant = filename[:-4]
        pack = next((item for item in self._presentation_packs() if item.id == pack_id), None)
        path = pack.thumb_path(variant) if pack is not None else None
        if path is None:
            self._send_json(404, {"error": "no such preview"})
            return
        self._send_bytes(200, path.read_bytes(), "image/png")

    def _agents_feedback(self, run_id_text: str) -> None:
        """Record how one run landed and offer it to the memory loop.

        The named refusals come first (blank or oversize feedback), then
        the unknown run, so nothing is stored or captured that the page
        would not own. The text lands on the run row with its own
        timestamp, one audit row names the run and the length (never the
        words), and the run's transcript is offered to capture on the
        agents channel with the feedback as the user's own words. A form
        submit lands back on the page; JSON returns the record.
        """
        server = self.server  # type: ignore[attr-defined]
        body = self._read_json_body()
        feedback = body.get("feedback") if body is not None else None
        if not isinstance(feedback, str) or not feedback.strip():
            self._send_json(
                400,
                {"error": "the feedback is blank; say a few words about how"
                          " the run landed"},
            )
            return
        feedback = feedback.strip()
        if len(feedback) > FEEDBACK_MAX_CHARS:
            self._send_json(
                400,
                {"error": f"the feedback is longer than {FEEDBACK_MAX_CHARS}"
                          " characters; shorten it"},
            )
            return
        if self._require_store(server.agents, "agents store") is None:
            return
        try:
            run_id = int(str(run_id_text).strip())
        except ValueError:
            run_id = -1
        run = server.agents.get(run_id) if run_id > 0 else None
        if run is None:
            self._send_json(
                404,
                {"error": "no run with that id; the /agents page lists the"
                          " runs this desk has recorded"},
            )
            return
        server.agents.set_feedback(run_id, feedback)
        agent = find_agent(run.get("agentId", ""))
        agent_name = agent.name if agent is not None else run.get("agentId", "")
        self._audit(
            "agents.feedback", target=str(run.get("agentId", "")),
            detail=f"run {run_id}; {len(feedback)} characters",
        )
        self._capture_memory(
            "agents",
            feedback_transcript(agent_name, run, feedback),
            feedback,
            use_model=True,
        )
        stored = server.agents.get(run_id)
        self._respond_form_or_json("/agents", {
            "id": run_id,
            "agent": run.get("agentId", ""),
            "feedback": feedback,
            "feedbackTs": stored["feedbackTs"] if stored else None,
        })

    def _agent_fact_ranks(self, kind, brief: str) -> list:
        """The ranked recall for one agent run: the agent's name joined
        to the brief is the query, the same hybrid recall and embedding
        derivation the assistant's turns use. A locked memory store, or
        one that cannot be read just now (a transient lock),
        contributes nothing: the run keeps going, the bank is never read
        in plaintext."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return []
        self._configure_memory_embeddings()
        try:
            return memory.recall(f"{kind.name} {brief}")
        except Exception:  # noqa: BLE001 - recall must never take the run down
            LOG.warning("the memory store could not be read just now;"
                        " the run proceeds without recalled facts")
            return []

    def _send_audit_tail(self) -> None:
        """The newest audit entries as JSON, for the settings page's live tail.

        503 without a store: the tail is the store's data, and an empty list would claim
        there was nothing to record.
        """
        if self._require_store(self.server.audit_conn, "audit store") is None:  # type: ignore[attr-defined]
            return
        self._send_json(200, {"entries": audit_store.entries(self.server.audit_conn)})  # type: ignore[attr-defined]

    def _send_audit_csv(self) -> None:
        """The whole audit trail as a CSV download.

        The bytes are the store's own export rather than a re-rendering of its rows, so
        the file carries exactly what the store holds; the content type tells a browser
        to download it.
        """
        if self._require_store(self.server.audit_conn, "audit store") is None:  # type: ignore[attr-defined]
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

    def _preference_notice(self) -> str:
        """The store's own words after a save, or its confirmation.

        The save route answers with a 303 carrying the outcome in the
        query, so the page shows what the store decided rather than
        re-deciding it here.
        """
        query = parse_qs(self.path.partition("?")[2])
        refusal = query.get("preferences_error", [""])[0]
        if refusal:
            return refusal
        if "preferences_saved" in query:
            return "Saved. The card below reads back what the store now holds."
        return ""

    def _desk_check_for_page(self, server) -> dict | None:
        """The desk check for the settings page, or nothing if it cannot run.

        The page has to render either way. A failure here is the empty
        section, not a 500.
        """
        try:
            return desk_check_api_payload(server)
        except Exception:
            return {
                "ranTs": time.time(),
                "findings": [{
                    "title": "The desk check could not finish",
                    "cause": "Something went wrong running the check, so this page has no findings.",
                }],
                "failed": {},
            }

    def _send_settings_page(self) -> None:
        """Render the settings page: sources, skills, endpoint, mail, registry, audit.

        Every store is optional, so each block falls back to the empty form the page
        renders when nothing opened. The audit block reads the newest 60 entries plus a
        total count, because the page shows a sample and the true size side by side.
        """
        server = self.server  # type: ignore[attr-defined]
        entries = server.activity_log.entries() if server.activity_log is not None else []
        skills = server.skills.all_skills() if server.skills is not None else []
        histories = {s["id"]: server.skills.history(s["id"]) for s in skills}
        audit_entries = (
            audit_store.entries(server.audit_conn, 60)
            if server.audit_conn is not None else []
        )
        audit_total = (
            audit_store.count(server.audit_conn)
            if server.audit_conn is not None else 0
        )
        connections = (
            [_connection_payload(c) for c in server.keys.all()]
            if server.keys is not None else None
        )
        bindings = (
            [_binding_payload(b) for b in server.keys.bindings()]
            if server.keys is not None else None
        )
        editing_id = parse_qs(self.path.partition("?")[2]).get("connection", [""])[0]
        editing = next((c for c in (connections or []) if c["id"] == editing_id), None)
        learned = (
            server.learned_profile.document()
            if server.learned_profile is not None else None
        )
        page = render_settings_page(
            entries, skills, histories, agentdesk.__version__,
            settings_values=self._settings_public_values(),
            endpoint_status=self._endpoint_status(),
            learned=learned,
            mail_folder=server.settings.get("mail_folder") if server.settings is not None else "",
            mail_self_address=(server.settings.get("mail_self_address")
                               if server.settings is not None else ""),
            mail_fetch=(server.mail.status().get("fetch")
                        if server.mail is not None else None),
            registry_status=self._registry_status_for_settings(),
            extra_hosts=(server.settings.get("extra_allowed_hosts")
                         if server.settings is not None else ""),
            server_port=server.port,
            inbox_count=self._inbox_waiting_count(),
            audit_entries=audit_entries,
            audit_total=audit_total,
            preference_notice=self._preference_notice(),
            desk_check=self._desk_check_for_page(server),
            connections=connections,
            editing_connection=editing,
            bindings=bindings,
            keychain_available=bool(server.keychain.available()),
            connections_notice=self._connections_notice(),
            agent_loop=(server.agent_loop.status()
                        if getattr(server, "agent_loop", None) is not None else None),
            update=update_payload(server),
            curator_last_run=(server.skills.curator_state_value("last_run_at")
                              if server.skills is not None else None),
            ai=_ai_summary(server),
            excel_status=(server.excel.status() if server.excel is not None else None),
            calendar_status=(server.calendar.status() if server.calendar is not None
                             else None),
            notice=parse_qs(self.path.partition("?")[2]).get("notice", [""])[0],
            notice_kind=parse_qs(self.path.partition("?")[2]).get(
                "notice_kind", ["status"])[0],
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _connections_notice(self) -> str:
        """A connection save's refusal, or the store's unavailability."""
        if self.server.keys is None:  # type: ignore[attr-defined]
            return "The connections store is not available, so connections cannot be saved here."
        return parse_qs(self.path.partition("?")[2]).get("connections_error", [""])[0]

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
        values["research_provider_key"] = mask_llm_key(values.get("research_provider_key", ""))
        return values

    def _endpoint_status(self) -> dict:
        """Configured or not, and the truth about the last call. A down
        endpoint shows degraded, never a false green. The form values
        retired to the connections surface (spec 018 #234); the legacy
        rows themselves stay in the store, read-only."""
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
        timeout = settings.get("presentation_timeout_s") if settings is not None else "30"
        # A refused timeout comes back in the query so the form shows the
        # typed value beside its cause instead of the last saved one.
        typed = parse_qs(self.path.partition("?")[2]).get("presentation_timeout", [""])[0]
        return {
            "configured": configured,
            "last": last,
            "presentationTimeout": typed or timeout or "30",
        }

    def _send_settings_values(self) -> None:
        """The public settings values as JSON, for the page's widgets.

        503 without a store; the values are the public subset the page is allowed to
        see, never the raw store, so the widget route cannot become a second read
        surface.
        """
        settings = self._require_store(self.server.settings, "settings store")
        if settings is None:
            return
        self._send_json(200, self._settings_public_values())

    def _endpoint_save(self) -> None:
        """Save the one field the endpoint route still carries: the
        presentation timeout.

        The base, key, model and research fields retired to the
        connections surface (spec 018 #234), and the legacy settings
        rows are read-only fallback now, so every other field name is
        refused with the accepted names: a silent ok with dropped values
        is how a typo loses data."""
        settings = self._require_store(self.server.settings, "settings store")
        if settings is None:
            return
        body = self._read_json_body() or {}
        unknown = sorted(
            name for name in body if name != "presentationTimeout"
        )
        if unknown:
            self._send_json(400, {"error": (
                "unknown endpoint field(s): " + ", ".join(unknown)
                + "; accepted fields are presentationTimeout"
            )})
            return
        if "presentationTimeout" in body:
            timeout_raw = str(body.get("presentationTimeout") or "").strip()
            try:
                seconds = float(timeout_raw)
            except ValueError:
                seconds = 0
            if seconds < 5 or seconds > 300:
                refusal = {"error": "presentation timeout must be a number of seconds from 5 to 300"}
                if self._is_form_submit():
                    self._send_redirect(
                        "/settings?connections_error=" + quote(refusal["error"])
                        + "&presentation_timeout=" + quote(timeout_raw)
                        + "#endpoint")
                    return
                self._send_json(400, refusal)
                return
            settings.set("presentation_timeout_s", timeout_raw)
        if self._is_form_submit():
            self._send_notice_redirect(
                "/settings#endpoint", "The presentation timeout is saved.")
            return
        self._send_json(200, {
            "ok": True,
            "presentationTimeout": settings.get("presentation_timeout_s"),
        })

    # -- named connections (spec 018) -------------------------------------

    def _send_connections_json(self) -> None:
        """GET /api/connections: every connection, masked hints only.

        The keychain's availability rides along so a client never learns it
        from a failed save; 503 without a store, the honest unavailable
        state every store route uses.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        self._send_json(200, {
            "connections": [_connection_payload(c) for c in server.keys.all()],
            "keychainAvailable": server.keychain.available(),
        })

    def _connections_refusal(self, message: str, status: int = 400) -> None:
        """Answer a connection refusal: JSON, or the settings page carrying it.

        A no-JS form post lands back on the Settings page with the server's
        own words in the query, the preferences save's pattern, so a refusal
        is never a dead JSON end for a browser form.
        """
        if self._is_form_submit():
            self._send_redirect("/settings?connections_error="
                                + quote(message) + "#connections")
            return
        self._send_json(status, {"error": message})

    def _connection_create(self) -> None:
        """POST /api/connections: save one named connection.

        The key goes to the keychain alone; the row and every answer after
        this one carry the masked hint. A key that cannot land in the
        keychain refuses the whole save: a connection whose secret silently
        went nowhere is a trap. The refusal really leaves nothing behind:
        the row is deleted, and the default star the refused row's insert
        had already taken from the previous default is given back, so the
        user's starred connection keeps its star.

        The model is the one every call on this connection sends (spec
        022). A save that arrives without one takes the preset's default
        model, as a blank base URL takes the preset's address: the form
        starts with that model, and a browser without script that switched
        provider still saves a model that provider accepts.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        body = self._read_json_body() or {}
        values, error = _connection_input(body, CONNECTION_CREATE_FIELDS,
                                          allow_empty_label=True)
        if error:
            self._connections_refusal(error)
            return
        preset = values["provider"]
        base = values["baseUrl"] or preset.base_url
        if not base:
            self._connections_refusal("This AI needs its address. Open More options"
                                      " and fill in Address.")
            return
        # The form makes a name optional: an empty one takes the provider's.
        label = values["label"] or _default_connection_label(server.keys, preset)
        if not values["apiKey"] and not preset.key_optional:
            where = f" Get a key at {preset.console_url}." if preset.console_url else ""
            self._connections_refusal(
                f"the {preset.name} preset needs an API key.{where}")
            return
        if values["apiKey"] and not server.keychain.available():
            self._connections_refusal(NO_KEYCHAIN_NOTICE)
            return
        previous_default = next(
            (c for c in server.keys.all() if c.is_default), None)
        try:
            connection = server.keys.add(
                label=label, provider=preset.id, base_url=base,
                masked_key=mask_key(values["apiKey"]) if values["apiKey"] else "",
                headers=values["headers"], is_default=values["isDefault"],
                model=values["model"] or preset.default_model)
        except ValueError as exc:
            self._connections_refusal(str(exc), status=409)
            return
        if values["apiKey"] and not server.keychain.store(connection.id,
                                                          values["apiKey"]):
            server.keys.delete(connection.id)  # never keep a row whose secret went nowhere
            if previous_default is not None:
                # The insert cleared the previous default's star before the
                # keychain refused; restoring it is what makes "nothing
                # was saved" true.
                server.keys.set_default(previous_default.id)
            self._connections_refusal("the keychain refused the key; nothing was saved")
            return
        if values["apiKey"] and not preset.local:
            # Story 3: the save itself checks the key with the free
            # model-list GET; a failed check never refuses the save.
            connection = _check_after_save(server, connection, values["apiKey"])
        self._audit("keys.create", target=connection.id,
                    detail=f"{connection.label} ({preset.name})")
        if self._is_form_submit():
            self._send_notice_redirect(
                "/settings#connections", "Saved. The connection is live.")
            return
        self._send_json(201, _connection_payload(connection))

    def _connection_update(self, connection_id: str) -> None:
        """POST /api/connections/<id>/update: edit one connection.

        An empty key field keeps the stored key (the one edit semantic
        everywhere); keyClear removes it; a typed key replaces it. A row
        that cannot be written puts the previous secret back, so the
        keychain and the database never disagree about what is stored.
        A keychain that refuses the clear's delete is named in the
        answer (a notice for JSON, the connections notice for a form
        post): the row says no key, so the user must hear that the
        keychain still holds the secret.

        The model is saved as the request gives it (spec 022): a name
        replaces the saved one and a blank one means none chosen. A JSON
        request that does not mention it leaves the saved model alone; a
        form always posts the field, so there a blank is the user clearing it.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        try:
            existing = server.keys.get(connection_id)
        except UnknownConnection:
            self._send_json(404, {"error": f"no connection {connection_id}"})
            return
        body = self._read_json_body() or {}
        values, error = _connection_input(body, CONNECTION_UPDATE_FIELDS)
        if error:
            self._connections_refusal(error)
            return
        preset = values["provider"]
        base = values["baseUrl"] or existing.base_url
        if not base:
            self._connections_refusal("a custom connection needs a base URL")
            return
        api_key = values["apiKey"]
        if api_key and not server.keychain.available():
            self._connections_refusal(NO_KEYCHAIN_NOTICE)
            return
        previous_secret = server.keychain.fetch(existing.id) if api_key else None
        if api_key and not server.keychain.store(existing.id, api_key):
            self._connections_refusal("the keychain refused the key; nothing changed")
            return
        model = values["model"]
        if model is None and self._is_form_submit():
            # The form always posts its model field, so one missing from a
            # form post was blank: the user clearing it is saved as cleared.
            model = ""
        try:
            connection = server.keys.update(
                existing.id, label=values["label"], provider=preset.id,
                base_url=base,
                masked_key=mask_key(api_key) if api_key else existing.masked_key,
                headers=values["headers"], model=model)
        except ValueError as exc:
            if api_key:
                if previous_secret is None:
                    server.keychain.forget(existing.id)
                else:
                    server.keychain.store(existing.id, previous_secret)
            self._connections_refusal(str(exc), status=409)
            return
        clear_notice = ""
        if _flag(body, "keyClear") and not api_key:
            if not server.keychain.forget(existing.id) \
                    and server.keychain.fetch(existing.id) is not None:
                # forget answers False both for "there was none" and for a
                # refusal; the re-fetch is what tells the two apart, so a
                # refused delete is surfaced and an empty keychain is not.
                clear_notice = (
                    "the connection no longer names a key, but this"
                    " machine's keychain refused to drop it and still"
                    " holds the key")
            connection = server.keys.clear_key(existing.id)
        if values["isDefault"]:
            connection = server.keys.set_default(existing.id)
        if api_key and not preset.local:
            # A typed key is checked like a fresh save; an empty key
            # field keeps the stored key and checks nothing.
            connection = _check_after_save(server, connection, api_key)
        self._audit("keys.update", target=existing.id,
                    detail=f"{connection.label} ({preset.name})")
        if self._is_form_submit():
            if clear_notice:
                self._send_redirect(
                    "/settings?connections_error=" + quote(clear_notice)
                    + "#connections")
            else:
                self._send_notice_redirect(
                    "/settings#connections", "Saved. The connection is live.")
            return
        payload = _connection_payload(connection)
        if clear_notice:
            payload["notice"] = clear_notice
        self._send_json(200, payload)

    def _connection_delete(self, connection_id: str) -> None:
        """POST /api/connections/<id>/delete: the row, its secret and its
        bindings go together, but not before what the connection answers
        is named (spec 018 story 10): a first post about a connection
        that serves answers the warning naming those in plain words (a
        no-JS confirmation page for a form post, a 409 carrying them for
        JSON), and only a confirmed post deletes.

        A migrated connection (spec 018 #234) is the one exception: its
        keychain entry survives the delete, because the legacy settings
        rows stay in place and the next boot's migration step puts the
        connection back with its key: that delete is the recovery path,
        and both confirmations say so."""
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        try:
            connection = server.keys.get(connection_id)
        except UnknownConnection:
            self._send_json(404, {"error": f"no connection {connection_id}"})
            return
        migrated = connection.id in MIGRATED_CONNECTION_IDS
        jobs = server.keys.bound_jobs(connection.id)
        confirmed = _flag(self._read_json_body() or {}, "confirm")
        if jobs and not confirmed:
            names = joined_job_labels(jobs)
            if migrated:
                sentence = (
                    f"{connection.label} answers {names}. It came from an"
                    " older version of the app: deleting it removes the"
                    " connection, but its key stays in this computer's"
                    " keychain and the connection comes back the next time"
                    " the app starts, so nothing needs retyping")
            else:
                sentence = (
                    f"{connection.label} answers {names}. Deleting it"
                    " removes its key from this computer, and those stop"
                    " answering until you save another key")
            if self._is_form_submit():
                page = render_connection_delete_warning(
                    _connection_payload(connection), jobs, agentdesk.__version__,
                    migrated=migrated)
                self._send_bytes(200, page.encode("utf-8"),
                                 "text/html; charset=utf-8")
                return
            self._send_json(409, {"error": sentence, "boundJobs": jobs})
            return
        if not migrated:
            server.keychain.forget(connection.id)
        server.keys.delete(connection.id)  # the bindings cascade inside
        detail = connection.label + (f"; unbound {', '.join(jobs)}" if jobs else "")
        if migrated:
            detail += "; the keychain entry stayed (it comes back on restart)"
        self._audit("keys.delete", target=connection.id, detail=detail)
        if self._is_form_submit():
            self._send_notice_redirect(
                "/settings#connections", "The connection was deleted.")
            return
        self._send_json(200, {"ok": True, "id": connection.id})

    def _connection_test(self, connection_id: str) -> None:
        """POST /api/connections/<id>/test: the free model-list GET.

        The check happens server-side only, with the connection's own key
        from the keychain, and it is never a chat completion: the listing
        alone answers whether the key works. The outcome lands in status,
        last_checked_at and last_error per the spec's mapping, a
        discovered listing refreshes the models cache, and a keys.test
        audit row records the check with no secret material. A form post
        lands back on Settings, where the badge re-renders from the row.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        try:
            connection = server.keys.get(connection_id)
        except UnknownConnection:
            self._send_json(404, {"error": f"no connection {connection_id}"})
            return
        result = health.check_models(
            connection.base_url,
            server.keychain.fetch(connection.id) or "",
            extra_headers=connection.headers,
        )
        connection = _apply_health(server.keys, connection, result)
        self._audit("keys.test", target=connection.id,
                    status="error" if result.outcome == health.OUTCOME_ERROR else "ok",
                    detail=f"{connection.label}: {result.cause or result.outcome}")
        if self._is_form_submit():
            if result.outcome == health.OUTCOME_ERROR:
                notice = (f"The check failed: {result.cause or result.outcome}. "
                          "The badge above names the cause.")
                kind_word = "alert"
            else:
                notice = "The check passed. The badge above is fresh."
                kind_word = "status"
            self._send_notice_redirect(
                "/settings#connections", notice, kind_word)
            return
        self._send_json(200, _connection_payload(connection))

    def _connection_deep_check(self, connection_id: str) -> None:
        """POST /api/connections/<id>/check: the explicit deeper check.

        One max_tokens=1 chat completion with the model typed by hand,
        the only chat the keys surface ever sends, and only because the
        button was pressed: save and Test never complete one. This is
        the one way a key gets verified on an endpoint without a model
        listing (the Anthropic compatibility case), and its outcome
        stamps the row exactly like the free check's.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        try:
            connection = server.keys.get(connection_id)
        except UnknownConnection:
            self._send_json(404, {"error": f"no connection {connection_id}"})
            return
        body = self._read_json_body() or {}
        model = str(body.get("model", "") or "").strip()
        if not model:
            self._connections_refusal("the deeper check needs a model name to complete")
            return
        result = health.deep_check(
            connection.base_url,
            server.keychain.fetch(connection.id) or "",
            model,
            extra_headers=connection.headers,
        )
        connection = _apply_health(server.keys, connection, result)
        self._audit("keys.test", target=connection.id,
                    status="error" if result.outcome == health.OUTCOME_ERROR else "ok",
                    detail=f"{connection.label}: deeper check"
                           f" ({result.cause or result.outcome})")
        if self._is_form_submit():
            if result.outcome == health.OUTCOME_ERROR:
                notice = (f"The deeper check failed: {result.cause or result.outcome}. "
                          "The badge above names the cause.")
                kind_word = "alert"
            else:
                notice = "The deeper check passed: one token came back."
                kind_word = "status"
            self._send_notice_redirect(
                "/settings#connections", notice, kind_word)
            return
        self._send_json(200, _connection_payload(connection))

    def _connection_models(self, connection_id: str) -> None:
        """GET /api/connections/<id>/models: the cached model list with
        its fetched-at time; ?refresh re-fetches server-side first.

        The upstream GET happens here and in the Test route only, never
        in the browser; a connection whose endpoint offers no listing
        answers its empty cache rather than an error, because typing the
        model by hand is always the allowed path.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        try:
            connection = server.keys.get(connection_id)
        except UnknownConnection:
            self._send_json(404, {"error": f"no connection {connection_id}"})
            return
        refresh = str(
            parse_qs(self.path.partition("?")[2]).get("refresh", [""])[0]
        ).lower() in ("1", "true", "yes", "on")
        if refresh:
            result = health.check_models(
                connection.base_url,
                server.keychain.fetch(connection.id) or "",
                extra_headers=connection.headers,
            )
            connection = _apply_health(server.keys, connection, result)
        self._send_json(200, {
            "id": connection.id,
            "models": connection.models,
            "fetchedAt": connection.models_fetched_at,
            "status": connection.status,
            "lastError": connection.last_error,
        })

    # -- job bindings (spec 018 #233) --------------------------------------

    def _send_bindings_json(self) -> None:
        """GET /api/bindings: every job binding. 503 without a store, the
        honest unavailable state every keys route uses."""
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        self._send_json(200, {
            "bindings": [_binding_payload(b) for b in server.keys.bindings()],
            "jobs": list(JOBS),
        })

    def _binding_write(self) -> None:
        """POST /api/bindings: point one job at one connection and model.

        The endpoint-save pattern throughout: unknown fields are a 400
        naming the typos and the accepted names, a job outside the seven
        is a 400 naming them, an unknown connection is a 404, and an
        empty connectionId unbinds the job (the picker's Not bound
        choice). A form post lands back on Settings; JSON gets the
        binding back.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.keys, "connections store") is None:
            return
        body = self._read_json_body() or {}
        unknown = sorted(name for name in body if name not in BINDING_FIELDS)
        if unknown:
            self._connections_refusal(
                "unknown binding field(s): " + ", ".join(unknown)
                + "; accepted fields are " + ", ".join(BINDING_FIELDS))
            return
        job = str(body.get("job", "") or "").strip()
        if job not in JOBS:
            self._connections_refusal(
                "unknown job: " + (job or "(none)")
                + "; jobs are " + ", ".join(JOBS))
            return
        connection_id = str(body.get("connectionId", "") or "").strip()
        model = str(body.get("model", "") or "").strip()
        if not connection_id:
            removed = server.keys.unbind(job)
            self._audit(
                "keys.update", target=job,
                detail=(f"unbound the {job} job" if removed
                        else f"the {job} job was already unbound"),
            )
            if self._is_form_submit():
                self._send_redirect("/settings#connections")
                return
            self._send_json(200, {"job": job, "connectionId": "", "model": model})
            return
        try:
            connection = server.keys.get(connection_id)
        except UnknownConnection:
            self._send_json(404, {"error": f"no connection {connection_id}"})
            return
        binding = server.keys.bind(job, connection_id, model)
        self._audit(
            "keys.update", target=connection_id,
            detail=f"bound the {job} job to {connection.label}"
                   + (f" (model {model})" if model else ""),
        )
        if self._is_form_submit():
            self._send_redirect("/settings#connections")
            return
        self._send_json(200, _binding_payload(binding))

    def _settings_toggle(self) -> None:
        """Flip one named switch and let the change take effect before answering.

        Only the listed keys are accepted, so a typo is a 400 rather than a new setting
        nobody reads. What the flip then means depends on the key: sample data seeds or
        clears its fixtures, the semantic and memory-loop switches are re-read on the
        next action, and every remaining key stops or starts its watcher. A form submit
        goes back to the inbox, the one page that posts this without JavaScript.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.settings, "settings store") is None:
            return
        body = self._read_json_body() or {}
        key = body.get("key")
        if key not in ("excel_enabled", "calendar_enabled", "endpoint_enabled", "quiet_hours", "daily_cap", "mail_enabled", "mail_feeder", "sample_data", "semantic_memory", "autonomy", "suggest_headers_only", "plugin_instance_cap", "agent_loop_minutes",
                       "memory_capture", "memory_auto_approve", "memory_capture_assistant",
                       "memory_capture_research", "memory_capture_workbook",
                       "memory_capture_agents", "learn_topics", "learn_profile",
                       "recommendations",
                       "recommend_deadlines", "recommend_meetings",
                       "recommend_horizon_days", "recommend_model_rank",
                       "recommend_threshold", "auto_update", "auto_update_plugins",
                       "skills_auto_create", "skills_auto_refine", "skills_curator"):
            self._send_json(400, {"error": "unknown setting"})
            return
        value = server.settings.toggle(key)
        if key == "sample_data":
            # The demo switch is not a data source: no watcher stops or
            # starts, so it never joins _apply_source_toggles.
            self._apply_sample_data(value)
        elif key == "semantic_memory":
            # The semantic switch (ticket #95) owns no watcher either:
            # the next memory action re-derives the store's semantic
            # half from this value and the probe's cached answer.
            pass
        elif key.startswith("recommend"):
            # The recommendation switches are read by the builder on every
            # refresh. Turning the feature back on runs the pass the next
            # memory write would otherwise have to wait for.
            if key == "recommendations":
                self._after_memory_change()
        elif key == "mail_feeder":
            # Alerts land in the mail folder, so the feed needs the mail
            # watch that reads it: turning alerts on turns the digest on
            # as part of the same action.
            value = self._apply_mail_feeder(value)
        elif key in ("autonomy", "suggest_headers_only", "plugin_instance_cap",
                     "agent_loop_minutes", "auto_update",
                     "auto_update_plugins", "learn_topics", "learn_profile",
                     "skills_auto_create", "skills_auto_refine",
                     "skills_curator") or key.startswith("memory_"):
            # The memory loop reads its switches on every capture, the
            # autonomy switch is read by ledger.may_act before each action,
            # the agent loop re-reads its interval on every wake, the
            # learn-topics and profile-review steps read their switches at
            # every pass, and the skills switches are read by the
            # consolidator and the loop's skills and curator steps on every
            # pass.
            pass
        else:
            self._apply_source_toggles(key, value)
        # A no-JS post lands back on the page it came from: settings
        # pages name themselves with return_to, and the inbox empty
        # state's offer (the only other form poster) defaults to /inbox.
        if self._is_form_submit():
            self._send_redirect(self._form_return_to(body, "/inbox"))
            return
        self._send_json(200, {"key": key, "value": value})

    def _apply_sample_data(self, value) -> None:
        """On seeds the labelled sample set into the real stores; off
        removes exactly what the Sample markers identify. Both turns
        write their audit row, so the decision log says what happened
        and the activity page shows it.

        Turning the switch on also wires the sources at the sample files
        (that is what makes the pipeline and moves cards fill), and off
        detaches only wiring that points into the sample folder. That
        wiring is recorded in the ledger first, so Activity can undo it;
        a wiring change the ledger cannot record is put back.
        """
        server = self.server  # type: ignore[attr-defined]
        if not value:
            wiring = demo_data.unwire_sample_sources(server)
            if wiring is not None:
                self._record_sample_wiring(wiring, value)
        result = (
            demo_data.seed(server.inbox, default_data_dir()) if value
            else demo_data.clear(server.inbox, default_data_dir())
        )
        # The Memory page graph's labelled sample memories ride the same
        # switch; a locked store is left alone.
        memories = (
            demo_data.seed_memory(server.memory) if value
            else demo_data.clear_memory(server.memory)
        )
        if memories:
            verb = "seeded" if value else "removed"
            result = dict(result, detail=f"{result['detail']} Memory: {verb} {memories} sample facts.")
        if value:
            wiring = demo_data.wire_sample_sources(server)
            if wiring is not None:
                self._record_sample_wiring(wiring, value)
        self._audit("demo.seeded" if value else "demo.cleared",
                    target="sample_data", detail=result["detail"])
        self._after_memory_change()

    def _record_sample_wiring(self, wiring: dict, value: bool) -> None:
        """Record one sample-wiring change in the ledger, or put it back.

        The entry carries the paths that were registered before the change,
        which is exactly what Undo needs. Without a ledger the desk cannot
        promise Undo, so the wiring is put back instead of left unrecorded.
        """
        server = self.server  # type: ignore[attr-defined]
        ledger = getattr(server, "ledger", None)
        if ledger is None:
            self._restore_sample_wiring(wiring, value)
            return
        why = (
            "Sample data was turned on, so the desk pointed the workbook and calendar "
            "at the sample files."
            if value else
            "Sample data was turned off, so the desk detached the sample workbook and calendar."
        )
        try:
            entry = ledger.record(
                actor="agent",
                action="deskcheck.fixed",
                subject="sample-data-wiring",
                why=why,
                undo_kind="wiring",
                before=json.dumps(wiring, sort_keys=True).encode("utf-8"),
                detail={"finding": "sample-not-wired", "switch": "sample_data"},
            )
        except Exception:  # noqa: BLE001 - nothing may stay without Undo
            self._restore_sample_wiring(wiring, value)
            return
        self._audit("deskcheck.fixed", target="sample-data-wiring",
                    detail=entry.id)

    def _restore_sample_wiring(self, wiring: dict, value: bool) -> None:
        """Put the wiring back to the captured paths after a failed record."""
        server = self.server  # type: ignore[attr-defined]
        if value:
            demo_data.unwire_sample_sources(server)
        else:
            demo_data.restore_sample_wiring(server, wiring)

    def _layout_save(self) -> None:
        """Save the full desired dashboard layout (issue #66).

        The body is the complete card list in the desired order; the
        array order is the card order, and unmentioned rows are dropped.
        Keys outside the current card universe (builtins plus installed
        plugins) are refused with the named layout errors, so a stale
        plugin id cannot be stored forever and a typo cannot invent a
        card.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.layout, "layout store") is None:
            return
        body = self._read_json_body() or {}
        known = set(BUILTIN_LAYOUT_KEYS) | set(enabled_plugin_ids(server))
        try:
            cards = parse_layout(body.get("cards"), known)
        except LayoutError as exc:
            payload = {"error": exc.code, "message": str(exc)}
            if exc.key is not None:
                payload["key"] = exc.key
            self._send_json(400, payload)
            return
        server.layout.replace(cards)
        self._send_json(200, {
            "cards": resolved_layout(server.layout, enabled_plugin_ids(server)),
        })

    def _dashboard_view_report(self) -> None:
        """Record that the page showed one dashboard, spending pilot views.

        Reading the dashboard used to spend pilot views inside the GET; the
        state builder made the read pure, so the page reports the view here
        once after a successful load. The spend rules live in the runtime,
        which keeps them identical to the cards the read emitted.
        """
        plugins = self.server.plugins  # type: ignore[attr-defined]
        spent = plugins.record_dashboard_view() if plugins is not None else 0
        self._send_json(200, {"spent": spent})

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
                    # The first poll runs inside the response, not on a
                    # stray thread: the folder read is local and quick, a
                    # toggle that returns before its watch has run leaves
                    # every reader guessing, and the folder-save handler
                    # already polls synchronously. _poll_mail_once keeps
                    # its guard, so a failing read logs instead of
                    # failing the toggle.
                    _poll_mail_once(server.mail)
                else:
                    server.mail.stop_polling()
            # The plugin runner's mail-digest binding follows the watcher
            # the toggle owns (#64): off pauses the digest, so no plugin
            # card reads the folder either.
            if server.plugins is not None:
                server.plugins.runner.mail = server.mail if value else None

    def _apply_mail_feeder(self, value) -> bool:
        """Apply the Outlook alert switch, turning the mail digest on with it.

        Alerts land in the mail folder, so an alert feed without its
        watcher would never be polled. Turning alerts on therefore sets
        mail_enabled too, constructs and starts the watcher exactly as
        the mail toggle does, polls once, and only then wires the feeder;
        the effective switch value is returned. A watcher that cannot be
        constructed answers with the switch back off, never on with
        nothing to run it.
        """
        server = self.server  # type: ignore[attr-defined]
        settings = server.settings
        if value and settings is not None:
            mail_on = bool(settings.get("mail_enabled"))
            if not mail_on:
                settings.set("mail_enabled", True)
            # Construct and start the watch only when mail was off or no
            # watcher exists, exactly the mail_enabled branch.
            if not mail_on or server.mail is None:
                self._apply_source_toggles("mail_enabled", True)
            if server.mail is None:
                settings.set("mail_feeder", False)
                return False
        if server.mail is not None and settings is not None:
            feeder = _default_outlook_feeder(settings) if value else None
            server.mail.feeder = feeder.run_once if feeder is not None else None
        return value

    def _source_allowed(self, key: str) -> bool:
        """Whether a settings-keyed source is switched on, a missing store counting as on.

        Read per request rather than cached, so flipping a switch takes effect on the
        next page load.
        """
        settings = self.server.settings  # type: ignore[attr-defined]
        return settings is None or bool(settings.get(key))

    def _budget_values(self) -> dict:
        """What the settings page shows is what the inbox enforces."""
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            return {}
        return {"quiet_hours": settings.get("quiet_hours"), "cap": settings.get("daily_cap")}

    def _skill_run(self, skill_id: int) -> None:
        """Run one active skill as a sourced research prompt.

        503 without a skills store. An endpoint switched off answers 200 with a degraded
        status, because that is a settings choice rather than a failed request, while an
        unknown or inactive skill is a 409. The body is the answer's own JSON, so a
        degraded turn still explains itself.

        The skill is the assistant's saved ask, so its run recalls facts
        ranked against the skill's own prompt on the same terms the
        assistant turn does: the bounded block rides through the shared
        _facts_block helper, and a locked bank contributes nothing rather
        than breaking the run.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.skills, "skills store") is None:
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
            facts_block=self._facts_block(skill["prompt"]),
        )
        llm, endpoint, model = self._effective_llm("agents")
        answer = research(
            skill["prompt"], context, llm=llm, audit_conn=server.audit_conn,
            endpoint=endpoint, model=model,
        )
        # The run counts as use (spec 016 section 6.6): the curator's
        # staleness clock reads it, and a used stale skill reactivates.
        server.skills.record_use(skill_id)
        self._send_json(200, answer.to_json())

    def _skill_undo(self, skill_id: int) -> None:
        """Deactivate a skill, this surface's only undo.

        Undo is a declined proposal: the pattern starts its dismiss cooldown
        before the skill deactivates, so the next consolidation run does not
        re-propose the identical ask. Undoing a desk-made skill also queues
        "The user undid the last run of this skill." as feedback, so the
        next refinement pass learns from it (spec 016 section 6.6). A
        SkillError means the store cannot name that skill and answers 404;
        on success the body is the store's own record of the deactivation.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.skills, "skills store") is None:
            return
        try:
            skill = server.skills.get(skill_id)  # type: ignore[attr-defined]
            if skill is None:
                self._send_json(404, {"error": f"no skill {skill_id}"})
                return
            if server.consolidator is not None:
                server.consolidator.dismiss_cooldown(pattern_hash(skill["prompt"]))
            result = server.skills.deactivate(skill_id)  # type: ignore[attr-defined]
            if skill.get("created_by") == "agent" and server.ledger is not None:
                enqueue_skill_feedback(
                    server.ledger, skill_id,
                    "The user undid the last run of this skill.")
            self._send_json(200, result)
        except SkillError as exc:
            self._send_json(404, {"error": str(exc)})

    def _skill_pin_rest(self, rest: str) -> None:
        """Pin (or release) the skill the path names, per the posted flag.

        A pinned skill is exempt from the curator and from refine. The
        answer is {"pinned": bool}; a no-JS form post goes back to the
        settings page's Skills section.
        """
        skill_id = _skill_id_from_path(rest)
        if skill_id is None:
            self._send_error_page(404, "Nothing here",
                                  "No skill lives at this address.")
            return
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.skills, "skills store") is None:
            return
        body = self._read_json_body() or {}
        raw = body.get("pinned")
        if raw is True or (isinstance(raw, str) and raw.strip().lower() in ("1", "true", "on")):
            pinned = True
        elif raw is False or (isinstance(raw, str) and raw.strip().lower() in ("0", "false", "off")):
            pinned = False
        else:
            self._send_json(400, {"error": "expected pinned true or false"})
            return
        try:
            result = server.skills.pin(skill_id, pinned)  # type: ignore[attr-defined]
        except SkillError as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._respond_form_or_json(self._form_return_to(body, "/settings#skills"),
                                   {"pinned": result["pinned"]})

    def _skill_feedback_rest(self, rest: str) -> None:
        """Queue the posted feedback for the desk-made skill the path names.

        409 when the skill is not agent-made or is pinned: those never
        reach a model. The text is capped at 1000 characters; the queue
        latch holds the rest until the skills loop step drains it.
        """
        skill_id = _skill_id_from_path(rest)
        if skill_id is None:
            self._send_error_page(404, "Nothing here",
                                  "No skill lives at this address.")
            return
        server = self.server  # type: ignore[attr-defined]
        skills = self._require_store(server.skills, "skills store")
        if skills is None:
            return
        if self._require_store(server.ledger, "ledger") is None:
            return
        skill = skills.get(skill_id)  # type: ignore[attr-defined]
        if skill is None:
            self._send_json(404, {"error": f"no skill {skill_id}"})
            return
        if skill.get("created_by") != "agent":
            self._send_json(409, {"error": "only skills the desk made take feedback"})
            return
        if skill.get("pinned"):
            self._send_json(409, {"error": "a pinned skill is not refined"})
            return
        body = self._read_json_body() or {}
        text = body.get("text") if isinstance(body.get("text"), str) else None
        if text is None or not text.strip():
            self._send_json(400, {"error": "expected feedback text"})
            return
        if len(text) > SKILL_FEEDBACK_MAX_CHARS:
            self._send_json(400, {"error": "feedback is capped at 1000 characters"})
            return
        enqueue_skill_feedback(server.ledger, skill_id, text)
        self._respond_form_or_json(self._form_return_to(body, "/settings#skills"),
                                   {"queued": True}, status=200)

    def _send_skill_markdown(self, skill_id: int) -> None:
        """One skill's prompt as plain markdown, for copying out of the app.

        404 when the store cannot name it. text/plain is deliberate: a browser then
        shows the text instead of rendering it as a page.
        """
        server = self.server  # type: ignore[attr-defined]
        if self._require_store(server.skills, "skills store") is None:
            return
        try:
            markdown = server.skills.markdown(skill_id)  # type: ignore[attr-defined]
        except SkillError as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._send_bytes(200, markdown.encode("utf-8"), "text/plain; charset=utf-8")

    def _send_touches_page(self) -> None:
        """Render the what-this-touches page from the actions the audit store has seen.

        An unopened store yields an empty observation set, so the page still explains
        what the app can touch without claiming it has not touched anything.
        """
        observed: set[str] = set()
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            observed = audit_store.observed_actions(self.server.audit_conn)  # type: ignore[attr-defined]
        page = render_touches(observed, agentdesk.__version__, datetime.now(),
                              inbox_count=self._inbox_waiting_count())
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _maybe_briefs(self) -> None:
        """A calendar read may owe the inbox a brief or two, and any read
        is when the repetition detector catches up on the asks logged so
        far: the same catch-up-on-read pattern as the briefs themselves,
        one guarded call, no scheduler."""
        server = self.server  # type: ignore[attr-defined]
        if server.calendar is not None and server.inbox is not None and server.activity_log is not None:
            try:
                generate_briefs(server.calendar, server.inbox, server.activity_log, server.inbox.clock)
            except Exception:  # noqa: BLE001 - briefs must never break the inbox
                LOG.exception("brief generation failed")
        if server.consolidator is not None:
            try:
                server.consolidator.consolidate()
            except Exception:  # noqa: BLE001 - consolidation must never break a read
                LOG.exception("consolidation failed")

    def _send_inbox_page(self) -> None:
        """Render the inbox: waiting cards, dismissed ones and the sample-data switch.

        Two passes run first, briefs then the evaluator, so a card whose window opened
        while the page was away is already waiting. The clock is the store's own, like
        every payload, so a card never ages by two different clocks.
        """
        inbox = self._require_store(self.server.inbox, "inbox")
        if inbox is None:
            return
        self._maybe_briefs()
        self._evaluate_inbox(inbox)
        # The store's own clock, like every payload: cards never age by
        # two different clocks.
        now_ts = inbox.now_ts()
        settings = self.server.settings  # type: ignore[attr-defined]
        sample_on = bool(settings.get("sample_data")) if settings is not None else False
        query = parse_qs(self.path.partition("?")[2])
        page = render_inbox_page(inbox.waiting(), inbox.dismissed(),
                                 agentdesk.__version__, now_ts,
                                 sample_data_on=sample_on,
                                 notice=query.get("notice", [""])[0],
                                 notice_kind=query.get("notice_kind", ["status"])[0])
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
        """The three counts the badge needs: waiting, notified and dismissed.

        The brief and evaluator passes run first, for the same reason the page runs
        them; notified counts waiting cards that have been announced, so the badge does
        not double-count a card that already asked for attention.
        """
        inbox = self._require_store(self.server.inbox, "inbox")
        if inbox is None:
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
        """Accept or dismiss one card, at most once.

        A card that is no longer waiting is refused: JSON gets a 409 carrying the card's
        current state, while a replayed form post redirects to the inbox, which is what
        a double-click means. A mail draft's file is written before the acceptance is
        recorded, so a failed write leaves the card waiting for a retry instead of an
        accepted card that wrote nothing. Acceptance then runs the card's kind-specific
        follow-up and the fact-carried hook, and both decisions are audited under
        inbox.approved or inbox.denied.
        """
        inbox = self._require_store(self.server.inbox, "inbox")
        if inbox is None:
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
            self._respond_form_or_json("/inbox", {
                "error": "that card was already decided",
                "card": current.to_json(inbox.now_ts()),
            }, 409)
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
        if isinstance(card.meta.get("ask"), str):
            self._on_ask_card_decided(card, decision)
        if decision == "accept":
            self._on_fact_carried(card)
        if card.kind == KIND_MEMORY_DRAFT:
            self._after_memory_change()
        self._audit(
            "inbox.approved" if decision == "accept" else "inbox.denied",
            target=card.id, detail=card.title,
        )
        if self._is_form_submit():
            if decision == "accept":
                notice = "The card was accepted."
            else:
                notice = ("The card moved to Dismissed at the bottom of the "
                          "inbox. Restore it there for 30 days.")
            self._send_notice_redirect("/inbox", notice)
            return
        self._send_json(200, card.to_json(inbox.now_ts()))

    def _on_ask_card_decided(self, card, decision: str) -> None:
        """Carry out the one ask-first question the desk check asks.

        The retired-plugins card is the only path that calls uninstall from
        a check finding, and it only runs when the user accepts the card:
        every listed plugin is uninstalled with its data folder kept, one
        audit row per plugin. Dismissing it latches the question so a later
        check run does not ask again for the same ids.
        """
        if card.meta.get("ask") != "retired-plugins":
            return
        server = self.server  # type: ignore[attr-defined]
        ids = [item for item in card.meta.get("ids") or [] if isinstance(item, str)]
        if decision != "accept":
            ledger = getattr(server, "ledger", None)
            if ledger is not None:
                from agentdesk.deskcheck.checks import retired_ask_latch_key

                ledger.latch(retired_ask_latch_key(ids), "dismissed")
            return
        plugins = server.plugins
        if plugins is None:
            return
        for plugin_id in ids:
            try:
                result = plugins.uninstall(plugin_id)
            except Exception as exc:  # noqa: BLE001 - one row per plugin
                self._audit("plugin.uninstall", target=plugin_id,
                            status="error", detail=str(exc)[:200])
                continue
            self._audit("plugin.uninstall", target=plugin_id,
                        detail=_plugin_audit_detail("uninstall", result))

    def _inbox_edit(self, card_id: str) -> None:
        """Update the card's draft; the decision vocabulary calls it
        edited. An identical draft is a no-op, like the donor's edit."""
        inbox = self._require_store(self.server.inbox, "inbox")
        if inbox is None:
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
        self._respond_form_or_json("/inbox", card.to_json(inbox.now_ts()))

    def _inbox_snooze(self, card_id: str) -> None:
        """Hide the card for one hour or until the next morning. The
        store's own clock judges the return time, like every payload."""
        inbox = self._require_store(self.server.inbox, "inbox")
        if inbox is None:
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
        self._respond_form_or_json("/inbox", card.to_json(inbox.now_ts()))

    def _inbox_more_info(self, card_id: str) -> None:
        """Attach the user's instruction; the card stays waiting for the
        decision, and a running snooze ends so it is visible again."""
        inbox = self._require_store(self.server.inbox, "inbox")
        if inbox is None:
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
        self._respond_form_or_json("/inbox", card.to_json(inbox.now_ts()))

    def _send_audit_page(self) -> None:
        """The one activity trail inside Settings: every audit row,
        newest first, plus the questions typed into research and the
        assistant. The page's window is larger than the store's default
        because it is the screen behind the CSV export."""
        entries = (
            audit_store.entries(self.server.audit_conn, 300)  # type: ignore[attr-defined]
            if self.server.audit_conn is not None else []  # type: ignore[attr-defined]
        )
        questions = (
            self.server.activity_log.entries()  # type: ignore[attr-defined]
            if self.server.activity_log is not None else []  # type: ignore[attr-defined]
        )
        _, _sep, query = self.path.partition("?")
        parsed = parse_qs(query) if query else {}
        kind = parsed.get("kind", [""])[0]
        notice = parsed.get("notice", [""])[0]
        ledger = getattr(self.server, "ledger", None)  # type: ignore[attr-defined]
        ledger_entries = ledger.entries(limit=50) if ledger is not None else []
        page = render_audit_page(entries, questions, agentdesk.__version__,
                                 inbox_count=self._inbox_waiting_count(),
                                 kind=kind or None,
                                 ledger_entries=ledger_entries,
                                 notice=notice)
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _ledger_undo(self) -> None:
        """Undo one recorded change (the Activity page's Undo button).

        A missing entry is a 404; every refusal to undo (already undone, no
        undo kind, or the current state could not be captured) is a 409 with
        the plain sentence to show. The undo is itself recorded and undoable.
        A form post goes back to the page it came from, JSON gets the ids.
        """
        server = self.server  # type: ignore[attr-defined]
        ledger = getattr(server, "ledger", None)
        if ledger is None:
            self._ledger_undo_error(503, "The ledger is not available, so nothing was changed.")
            return
        body = self._read_json_body() or {}
        entry_id = body.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            self._ledger_undo_error(400, "Name the change to undo.")
            return
        try:
            recorded = ledger_undo.undo(server, ledger, entry_id)
        except LookupError as exc:
            self._ledger_undo_error(404, str(exc))
            return
        except LedgerError as exc:
            self._ledger_undo_error(409, str(exc))
            return
        self._audit("ledger.undo", target=entry_id,
                    detail=f"undo entry {recorded.id}")
        self._respond_form_or_json(self._form_return_to(body, "/settings/activity"),
                                   {"undone": entry_id, "entry": recorded.id})

    def _ledger_undo_error(self, status: int, sentence: str) -> None:
        """A failed undo: the sentence rides back as the page's notice."""
        self._respond_form_or_json(f"/settings/activity?notice={quote(sentence)}",
                                   {"error": sentence}, status)

    # -- capabilities: the cached page and the one probing path (ticket #43)

    def _send_capabilities_page(self) -> None:
        """The capabilities page from the cache and the live table only.

        GET never probes the environment: gate cards render the cached
        results (or the never-tested state), and probing belongs to the
        explicit re-test POST. The cards age by the cache's own clock, so
        a stored result never reads fresher than it is."""
        query = parse_qs(self.path.partition("?")[2])
        cache = self.server.capabilities_cache
        if cache is None:
            # Without the cache the page itself cannot render: API callers
            # get the raw JSON refusal as before, and a form post (which
            # cannot be answered with this page) still never meets raw JSON.
            self._send_store_missing(self._store_missing("capabilities cache"))
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
            notice=query.get("notice", [""])[0],
            notice_kind=query.get("notice_kind", ["status"])[0],
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
        cache = self._require_store(server.capabilities_cache, "capabilities cache")
        if cache is None:
            return
        runner = (server.gate_runners or {}).get(gate_key)
        if runner is None:
            self._send_error_page(404, "Nothing here", "No gate lives at this address.")
            return
        cached = cache.save_result(runner())
        if self._is_form_submit():
            self._send_notice_redirect(
                "/capabilities",
                f"Gate re-tested: {cached.result.title} is "
                f"{cached.result.status}.")
            return
        self._send_json(200, cached.to_json())

    def _on_fact_carried(self, card) -> None:
        """An accepted card may carry a fact. Two shapes: the memory
        draft cards' structured meta ("memoryFact": the edited draft is
        the text, with its kind, gated occurrence, source and entities,
        ticket #91), and the legacy string meta ("fact": "..."), which
        behaves exactly as before. The only non-page creation path. The
        fact's source names the card, and the audit row names that
        source, never the text. Ticket #95: the semantic half derives
        per action, so an accepted fact embeds at write when active."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return
        self._configure_memory_embeddings()
        memory_fact = card.meta.get("memoryFact")
        if isinstance(memory_fact, dict):
            self._carry_memory_fact(card, memory_fact)
            return
        memory_observation = card.meta.get("memoryObservation")
        if isinstance(memory_observation, dict):
            self._carry_memory_observation(card, memory_observation)
            return
        text = card.meta.get("fact")
        if not isinstance(text, str) or not text.strip():
            return
        fact = memory_loop.store_fact(memory, text.strip(), source=f"inbox card {card.id}").fact
        self._audit("memory.fact", target=str(fact.id), detail=fact.source)

    def _carry_memory_fact(self, card, memory_fact: dict) -> None:
        """Write the accepted memory draft: one fact from the edited
        draft text with its kind, occurrence and source, then the
        mention edges. Anything malformed in the meta (it can arrive
        through the generic cards route too) drops that piece rather
        than failing the acceptance."""
        text = card.draft.strip()
        if not text:
            return
        memory = self.server.memory  # type: ignore[attr-defined]
        kind = memory_fact.get("kind")
        if kind not in FACT_KINDS:
            return
        occurrence_ts = memory_fact.get("occurrence_ts")
        if occurrence_ts is not None and not isinstance(occurrence_ts, (int, float)):
            occurrence_ts = None
        source_id = memory_fact.get("source_id")
        if not isinstance(source_id, int) or isinstance(source_id, bool):
            source_id = None
        if source_id is None:
            # A staged proposal carries its excerpt as text and creates the
            # source here, on approval: a rejected or undone proposal must
            # leave no excerpt behind.
            excerpt = memory_fact.get("source_excerpt")
            if isinstance(excerpt, str) and excerpt.strip():
                source_id = memory.add_source(
                    excerpt.strip(), speaker="The desk", context="engine")
        entities = []
        for pair in memory_fact.get("entities") or []:
            if (
                isinstance(pair, (list, tuple))
                and len(pair) == 2
                and isinstance(pair[0], str)
                and isinstance(pair[1], str)
            ):
                entities.append((pair[0], pair[1]))
        try:
            outcome = memory_loop.store_fact(
                memory, text, source=f"inbox card {card.id}", kind=kind,
                occurrence_ts=occurrence_ts, source_id=source_id, entities=entities,
            )
        except ValueError:
            LOG.warning("memory card %s carried an invalid entity type; the fact stays unlinked", card.id)
            outcome = memory_loop.store_fact(
                memory, text, source=f"inbox card {card.id}", kind=kind,
                occurrence_ts=occurrence_ts, source_id=source_id,
            )
        fact = outcome.fact
        self._audit("memory.fact", target=str(fact.id), detail=fact.source)
        self._schedule_observation_pass()

    def _carry_memory_observation(self, card, observation_meta: dict) -> None:
        """Write the accepted reflection (ticket #93): one observation
        from the edited draft text with its confidence, its citations
        and the scope the run ran in. The store prunes the scope rows
        the run did not keep, using the card's creation moment as the
        run reference (see MemoryStore.save_observation), so a re-
        reflect's acceptance updates the matching observation and
        drops the unkept ones exactly like the donor. Anything
        malformed in the meta (it can arrive through the generic cards
        route too) drops the piece rather than failing the
        acceptance, like the fact shape beside it. Dismissal never
        reaches here and writes nothing."""
        text = card.draft.strip()
        if not text:
            return
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return
        scope = observation_meta.get("scope_key")
        confidence = observation_meta.get("confidence")
        fact_ids = [
            value
            for value in observation_meta.get("source_fact_ids") or []
            if isinstance(value, int) and not isinstance(value, bool)
        ]
        if (
            not isinstance(scope, str)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
        ):
            LOG.warning(
                "memory card %s carried an unusable observation meta;"
                " nothing was written", card.id,
            )
            return
        try:
            saved = memory.save_observation(
                scope, text, float(confidence), fact_ids,
                now=memory.clock(), run_ts=card.created_ts,
            )
        except ValueError as exc:
            LOG.warning(
                "memory card %s carried an observation that cannot be"
                " stored (%s); nothing was written", card.id, exc,
            )
            return
        self._audit(
            "memory.observation", target=str(saved.observation.id),
            detail=f"inbox card {card.id}",
        )

    # -- mail: the page, the watcher controls, the reply drafts -----------

    def _send_mail_page(self, notice: str = "", notice_kind: str = "status",
                        drafts: dict | None = None) -> None:
        """The mail page. Off (or unconstructed) is an honest state with
        an enable pointer, never a blank screen.

        A form post's outcome rides the query as `notice`; a refused
        draft's typed words ride `drafts` keyed by the message id.
        """
        query = parse_qs(self.path.partition("?")[2])
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
        page = render_mail_page(
            agentdesk.__version__, view, off_reason=off_reason,
            inbox_count=self._inbox_waiting_count(),
            notice=notice or query.get("notice", [""])[0],
            notice_kind=query.get("notice_kind", [notice_kind])[0],
            drafts=drafts)
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
            self._send_notice_redirect("/mail", "The folder was read again.")
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
            self._send_store_missing(
                self._store_missing(
                    "mail watcher",
                    notice=("The mail watcher is not available on this machine, "
                            "so no draft was made.")),
                render=lambda notice: self._send_mail_page(
                    notice=notice, notice_kind="alert"))
            return
        if server.inbox is None:
            self._send_store_missing(
                self._store_missing(
                    "inbox",
                    notice=("The inbox is not available right now, so the draft "
                            "was not made. Try again once it is back.")),
                render=lambda notice: self._send_mail_page(
                    notice=notice, notice_kind="alert"))
            return
        body = self._read_json_body() or {}
        text = body.get("body")
        if not isinstance(text, str) or not text.strip():
            if self._is_form_submit():
                self._send_mail_page(
                    notice="Type the reply first: the box was empty, so no "
                           "draft was made.",
                    notice_kind="alert",
                    drafts={message_id: text if isinstance(text, str) else ""})
                return
            self._send_json(400, {"error": 'expected {"body": "..."}: the reply text you want to send'})
            return
        message = next((m for m in mail.view()["messages"] if m.id == message_id), None)
        if message is None:
            if self._is_form_submit():
                self._send_mail_page(
                    notice=f"No message {message_id} is in the mail folder any "
                           "more, so no draft was made.",
                    notice_kind="alert", drafts={message_id: text})
                return
            self._send_json(404, {"error": f"no message {message_id} in the mail folder"})
            return
        try:
            recipients = reply_recipients(message, self_address=mail.self_address)
        except ValueError as exc:
            if self._is_form_submit():
                self._send_mail_page(
                    notice=f"The reply could not be addressed: {exc} Your words "
                           "are kept below.",
                    notice_kind="alert", drafts={message_id: text})
                return
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
            self._send_notice_redirect(
                "/mail",
                "The reply draft is in your inbox for review; accepting "
                "it writes the file to your local outbox.")
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
        mail = self.server.mail  # type: ignore[attr-defined]
        try:
            path = write_reply(
                self.server.outbox_dir,  # type: ignore[attr-defined]
                original_id=str(draft_info.get("messageId", "")),
                to=str(draft_info.get("to", "")),
                subject=str(draft_info.get("subject", "")),
                body=card.draft,
                self_address=mail.self_address if mail is not None else "",
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
        settings = self._require_store(server.settings, "settings store")
        if settings is None:
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
            self._send_notice_redirect("/settings#tools", "The mail folder is saved.")
            return
        self._send_json(200, {"key": "mail_folder", "value": folder.strip()})

    def _mail_fetch_now(self) -> None:
        """Run one Outlook alert pass now, the Settings card's button.

        The pass writes headers only into the mail folder; it reads no
        body and calls no model. A desk with the feed off has nothing to
        run, which is an honest answer rather than an error page. The
        card's form names the tools section as its return_to, and a post
        without one (a fetch client, an empty body) lands on the sources
        card itself, the anchor inside that same section.
        """
        server = self.server  # type: ignore[attr-defined]
        body = self._read_json_body() or {}
        target = self._form_return_to(body, "/settings#sources")
        if server.mail is None or server.mail.feeder is None:
            self._respond_form_or_json(
                target,
                {"ran": False, "error": "Outlook alerts are off."},
            )
            return
        fetch = server.mail.fetch_now()
        self._respond_form_or_json(target, {"ran": True, "fetch": fetch})

    def _mail_address_save(self) -> None:
        """The settings page's mail address field, next to the folder.

        The address is what mail self-detection compares against the From
        header; an empty value turns self-detection off honestly (no
        follow-up cards that cannot know which threads were answered).
        A saved address is retried against the folder right away."""
        server = self.server  # type: ignore[attr-defined]
        settings = self._require_store(server.settings, "settings store")
        if settings is None:
            return
        body = self._read_json_body() or {}
        address = body.get("address")
        if not isinstance(address, str):
            self._send_json(400, {"error": 'expected {"address": "..."}'})
            return
        if "\r" in address or "\n" in address:
            self._send_json(400, {"error": "the address cannot contain a line break"})
            return
        settings.set("mail_self_address", address.strip())
        if server.mail is not None and address.strip():
            server.mail.retest()
        if self._is_form_submit():
            self._send_notice_redirect("/settings#tools", "Your mail address is saved.")
            return
        self._send_json(200, {"key": "mail_self_address", "value": address.strip()})

    def _preferences_save(self) -> None:
        """The settings form for what the desk knows about this person.

        A form post arrives as strings while the store wants a list of
        topics and a whole number of minutes, so this route converts
        before the store validates; nothing is clamped or guessed. An
        emptied field means "none": no topics, zero preparation minutes.
        """
        body = self._read_json_body() or {}
        form = self._is_form_submit()
        patch: dict = {}
        for key in ("chart", "replyTone", "replyLength", "insightDensity"):
            if key in body:
                patch[key] = str(body[key]).strip()
        if form or "focusTopics" in body:
            raw_topics = str(body.get("focusTopics", ""))
            patch["focusTopics"] = [
                line.strip() for line in raw_topics.splitlines() if line.strip()
            ]
        if form or "prepMinutes" in body:
            typed = str(body.get("prepMinutes", "")).strip()
            if not typed:
                patch["prepMinutes"] = 0
            else:
                try:
                    patch["prepMinutes"] = int(typed)
                except ValueError:
                    self._send_redirect(
                        "/settings?preferences_error=" + quote(
                            "Preparation minutes must be a whole number from 0 to 120."))
                    return
        try:
            document = PreferenceStore(default_data_dir()).write(patch)
        except PreferencesError as exc:
            self._respond_form_or_json(
                "/settings?preferences_error=" + quote(exc.message),
                {"error": exc.message, "code": exc.code}, exc.status)
            return
        self._audit("settings.preferences", target="preferences",
                    detail=",".join(changed(document)) or "none")
        self._respond_form_or_json("/settings?preferences_saved=1", document)

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
            """Audit a snooze whose window has come back.

            The evaluator calls this for each returning card, so the trail shows a
            return as pending instead of the card reappearing with no history.
            """
            self._audit("inbox.pending", target=card.id,
                        detail=f"{card.title} snooze returned")

        inbox_service.evaluate(inbox, _local_now(), on_snooze_return=on_return,
                               **self._budget_values())

    def _after_memory_change(self) -> None:
        """Keep recommendations caught up after a memory write.

        The builder adds waiting cards for deadlines that just became known and
        withdraws cards whose fact was just removed or replaced, then the inbox
        spends its notification budget on whatever is new: quiet hours and the
        daily cap therefore apply to recommendations exactly as to every card.
        """
        recommender = getattr(self.server, "recommender", None)  # type: ignore[attr-defined]
        added = 0
        if recommender is not None:
            added = int(recommender.refresh().get("added") or 0)
        if added and self.server.inbox is not None:  # type: ignore[attr-defined]
            self._evaluate_inbox(self.server.inbox)  # type: ignore[attr-defined]

    def _audit(self, action: str, target: str = "", detail: str = "",
               status: str = "ok") -> None:
        """The one inbox/plugin path into the append-only audit store."""
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(self.server.audit_conn, action,
                               target=target, status=status, detail=detail)

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
        """Put a dismissed card back in the waiting list.

        The store reports "no such card" and "past its 30-day window" through the same
        exception, so the answer distinguishes them: 404 for a card that never existed,
        410 for one that is gone for good. A restore is audited like every other
        decision, so a card cannot reappear with no history.
        """
        inbox = self._require_store(self.server.inbox, "inbox")
        if inbox is None:
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
        # A restore is a decision like the others: it is recorded, so a
        # card never reappears silently (the pending rule's sibling).
        self._audit("inbox.restored", target=card.id, detail=card.title)
        self._send_json(200, card.to_json(inbox.now_ts()))

    def _plugin_setup_get(self, path: str) -> None:
        """Serve the two plugin-setup views that answer GET: the instance list and one
        preview.

        The path is read as segments rather than matched whole, because the same prefix
        carries a four-segment listing and a six-segment preview. A PluginError answers
        with its own status and code, any other failure goes through the setup envelope
        so it still names itself, and a path matching neither shape is a 404 quoting it.
        """
        plugins = self._require_store(self.server.plugins, "plugin runtime")
        if plugins is None:
            return
        parts = [part for part in path.split("/") if part]
        try:
            # api plugins <id> instances   (the manage view's instance list)
            if len(parts) == 4 and parts[3] == "instances":
                self._send_json(200, self._instance_listing(plugins, parts[2]))
                return
            from ..plugins.setup_flow import preview
            # api plugins <id> instances <iid> preview
            if len(parts) >= 6 and parts[5] == "preview":
                query = self.path.partition("?")[2]
                params = {}
                if query:
                    from urllib.parse import parse_qs
                    params = {key: values[0] for key, values in parse_qs(query).items()}
                result = preview(
                    plugins, self._instance_cap(), parts[4],
                    sheet=params.get("sheet"),
                    header_row=int(params.get("headerRow") or 1),
                    range_text=params.get("range"),
                    plugin_id=parts[2],
                )
                self._send_json(200, result)
                return
        except PluginError as exc:
            self._send_json(exc.status, {"error": exc.code, "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - the setup envelope names the cause
            self._setup_error(exc)
            return
        self._send_json(404, {"error": "not-found", "message": path})

    def _instance_listing(self, plugins: PluginRuntime, plugin_id: str) -> dict:
        """The manage view's instance list for one plugin id.

        A config-backed plugin answers its own instance documents. An
        alias answers the one named instance of its target, and names the
        target as the setup plugin, so the SPA drives the target's
        endpoints instead of opening a second config surface for the
        alias. A plain plugin answers configBacked false and no instances.
        """
        from ..plugins.setup_flow import store_for
        record = plugins.record(plugin_id)  # PluginError(404) when unknown
        manifest = {}
        if record.get("versions"):
            manifest_path = _active_version_dir(record) / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        alias_of = str(config.get("aliasOf")) if config.get("aliasOf") else None
        config_backed = alias_of is not None or "workbook" in (config.get("kinds") or [])
        store = store_for(plugins, self._instance_cap())
        if alias_of:
            target_record = plugins.record(alias_of)
            instance_id = _alias_instance_id(
                str(config.get("instanceName") or plugin_id or "instance"))
            documents = [item for item in store.list(alias_of)
                         if item.get("instanceId") == instance_id]
            setup_id = alias_of
            setup_name = str(target_record.get("name") or alias_of)
        elif config_backed:
            documents = store.list(plugin_id)
            setup_id = plugin_id
            setup_name = str(record.get("name") or plugin_id)
        else:
            documents = []
            setup_id = plugin_id
            setup_name = str(record.get("name") or plugin_id)
        return {
            "pluginId": plugin_id,
            "configBacked": config_backed,
            "aliasOf": alias_of,
            "setupPluginId": setup_id,
            "setupPluginName": setup_name,
            "instances": documents,
        }

    def _plugin_setup_post(self, plugins: PluginRuntime, path: str, body: dict) -> None:
        """Run one plugin setup step and answer with its result.

        The segment count selects the step: four segments create an instance from the
        posted name, which is slugged down to an id, while a longer path names one and
        then its action: pick, stage, suggest, evaluate, confirm or outside. Suggest
        and evaluate let a request override the saved headers-only and completion
        settings, since the flow's next question is usually the answer. A ConfigError
        answers 400 with its own code, anything else through the setup envelope, and an
        unknown action is a 404 quoting the path.
        """
        from ..plugins.config import ConfigError
        from ..plugins.setup_flow import (
            accept_outside, confirm, ensure_instance, evaluate, pick, stage, store_for, suggest,
            upload,
        )
        parts = [part for part in path.split("/") if part]
        # api plugins <id> instances [iid] [action]
        if len(parts) < 4 or parts[3] != "instances":
            self._send_json(404, {"error": "not-found", "message": path})
            return
        cap = self._instance_cap()
        plugin_id = parts[2]
        try:
            if len(parts) == 4:
                name = str(body.get("name") or "").strip()
                if not name:
                    self._send_json(400, {"error": "Name the instance."})
                    return
                instance_id = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-") or "instance"
                saved = ensure_instance(
                    store_for(plugins, cap), instance_id, name,
                    good="down" if body.get("good") == "down" else "up",
                    plugin_id=plugin_id,
                )
                self._send_json(200, {"instance": saved})
                return
            instance_id = parts[4]
            action = parts[5] if len(parts) > 5 else ""
            name = str(body.get("name") or instance_id)
            if action == "pick":
                self._send_json(200, pick(
                    plugins, cap, instance_id, name, self.server.pick_plugin_file,  # type: ignore[attr-defined]
                    plugin_id=plugin_id))
                return
            if action == "stage":
                self._send_json(200, stage(
                    plugins, cap, instance_id, name, str(body.get("path") or ""),
                    plugin_id=plugin_id))
                return
            if action == "upload" and len(parts) > 6:
                filename = unquote(parts[6])
                # The declared length is tested first: an over-cap body was
                # discarded by the drain, and only this header still says
                # what the browser meant to send.
                declared = getattr(self, "_content_length", 0)
                if declared > MAX_UPLOAD_BYTES:
                    raise ConfigError(
                        "config:too-large",
                        "The file is larger than 4 MB. Save a smaller copy, or type the file's path instead.",
                    )
                raw = getattr(self, "_raw_body", b"")
                self._send_json(200, upload(
                    plugins, cap, instance_id, name, raw, filename, plugin_id=plugin_id))
                return
            if action == "suggest":
                headers_only = self._headers_only()
                if "headersOnly" in body:
                    headers_only = bool(body.get("headersOnly"))
                complete = self._suggestion_complete()
                self._send_json(200, suggest(
                    plugins, cap, instance_id, headers_only=headers_only, complete=complete,
                    plugin_id=plugin_id))
                return
            if action == "evaluate":
                tracking = body.get("tracking") if isinstance(body.get("tracking"), dict) else body
                self._send_json(200, evaluate(
                    plugins, cap, instance_id, tracking,
                    complete=self._suggestion_complete(), plugin_id=plugin_id))
                return
            if action == "confirm":
                tracking = body.get("tracking") if isinstance(body.get("tracking"), dict) else body
                self._send_json(200, confirm(
                    plugins, cap, instance_id, tracking,
                    suggested=bool(body.get("suggested")),
                    header_row=body.get("headerRow"),
                    range_text=body.get("range"),
                    name=body.get("name"),
                    plugin_id=plugin_id))
                return
            if action == "outside":
                self._send_json(200, accept_outside(plugins, cap, instance_id, plugin_id=plugin_id))
                return
        except ConfigError as exc:
            self._send_json(_SETUP_ERROR_STATUS.get(exc.code, 400),
                            {"error": exc.code, "message": exc.message})
            return
        except Exception as exc:  # noqa: BLE001
            self._setup_error(exc)
            return
        self._send_json(404, {"error": "not-found", "message": path})

    def _instance_cap(self) -> int:
        """The plugin-instance cap the setup flow enforces.

        A missing store, or a stored value that is not an integer, yields 6: the cap
        guards an allocation, so it must be a number even when the settings file cannot
        supply one.
        """
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            return 6
        try:
            return int(settings.get("plugin_instance_cap"))
        except (KeyError, TypeError, ValueError):
            return 6

    def _headers_only(self) -> bool:
        """Whether header suggestions should skip reading data rows.

        A missing store or missing key reads as off, so the fuller suggestion is what a
        desk does before anyone chooses otherwise.
        """
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            return False
        try:
            return bool(settings.get("suggest_headers_only"))
        except KeyError:
            return False

    def _suggestion_complete(self):
        """The completion callable an endpoint-backed suggestion gets, or
        None.

        None means no client or no endpoint, which is how the setup flow
        is told to use its deterministic heuristics instead of waiting on
        a call that would fail. The client comes from the resolution hub
        (spec 018 #233): suggestions honor the insights job's saved
        connection like every other call-site, the old bypass that
        ignored saved settings is gone.
        """
        server = self.server  # type: ignore[attr-defined]
        injected = (
            not getattr(server, "llm_defaulted_to_env", False)
            or server.llm is not getattr(server, "_startup_llm", None)
        )
        if self._job_resolution(DEFAULT_JOB) is None and not server.llm_endpoint and not injected:
            return None

        def complete(prompt: str) -> str:
            """One prompt in, one answer out, in the shape the flow expects.

            It is a closure so the flow receives a plain callable and never the handler
            or the server. The tracker asks the default model, not the insights place.
            """
            client, _name, _model = self._effective_llm(DEFAULT_JOB)
            return client(prompt)
        return complete

    def _insight_press_page(self) -> None:
        """A pressed card's answer as a page: what would be sent, then the
        sentence or the draft, then the one stage form that may follow.

        A refusal keeps the page and repeats the sentence the JSON route
        would have sent, because a person who pressed a button asked a
        question and deserves the answer on the same screen.
        """
        # The form posts the pair's flat spelling; press_from_form reads it
        # back into the one request the route parses, so the no-JS surface
        # and the SPA press the same press.
        request = press_from_form(self._read_json_body() or {})
        kind = str(request.get("kind") or "")
        label = press_label(kind)
        try:
            answer = draft_reply(
                self.server,
                request,
                preferences=PreferenceStore(default_data_dir()).read(),
                complete=self._insight_complete(),
            )
        except InsightError as exc:
            # A refused press spent no call and staged no card, so it is
            # an error row, never a working one (agents.run sets the same
            # status for a degraded run).
            self._audit("insight.press", target=kind or "press", detail=exc.code,
                        status="error")
            page = pages.render_press_page(
                label, [], agentdesk.__version__, refusal=exc.message
            )
            self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        thread = answer.get("thread") if isinstance(answer.get("thread"), dict) else None
        staged = str(answer.get("cardId") or "") if answer.get("staged") else ""
        stage_html = ""
        if thread is not None and not staged and answer.get("text"):
            stage_html = self._press_stage_form(request, thread, str(answer["text"]))
        # The audit names the thread and the source, never the words: a
        # draft is the user's to send, so the log records the act alone.
        self._audit(
            "insight.press",
            target=str(thread.get("id")) if thread is not None else (kind or "press"),
            detail=kind + ":" + str(answer.get("source") or "none")
            + (": staged " + staged if staged else ""),
        )
        if staged:
            # The card exists now, so the inbox badge and any notification
            # follow it, exactly as a hand-typed reply draft does.
            self._evaluate_inbox(self.server.inbox)
        page = pages.render_press_page(
            label,
            [str(line) for line in answer.get("disclosure") or []],
            agentdesk.__version__,
            text=str(answer.get("text") or ""),
            source=str(answer.get("source") or ""),
            note=str(answer.get("note") or ""),
            stage_html=stage_html,
            staged_id=staged,
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    @staticmethod
    def _press_stage_form(request: dict, thread: dict, text: str) -> str:
        """The one form that may turn a draft into an inbox card.

        It posts the same press again with stage, so there is a single
        composer and a single route: what travels the second time is exactly
        what this page already showed, with the subject the resolved thread
        carried, because that is the thread the page just named back.
        """
        facts = dict(request.get("thread") or {})
        facts["subject"] = str(thread.get("subject") or "")
        hidden = press_to_fields({"kind": request.get("kind"), "thread": facts, "text": text})
        hidden["stage"] = "1"
        fields = "".join(
            '<input type="hidden" name="' + name + '" value="' + html.escape(value) + '">'
            for name, value in hidden.items()
        )
        return (
            '<form method="post" action="/insight/press" class="cardform">'
            + fields
            + '<button class="btn btn-primary" type="submit">Stage as a reply card</button>'
            + "</form>"
        )

    def _insight_complete(self):
        """The one model call a reading may offer, or None when this desk
        has nothing configured for the insights job or the user turned
        model calls off. A reading that gets None keeps its local
        elements and offers no press. The client comes from the
        resolution hub (spec 018 #233): readings honor the insights job's
        saved connection like every other call-site, fixing the known
        bypass where they ignored saved settings entirely."""
        server = self.server  # type: ignore[attr-defined]
        if not self._source_allowed("endpoint_enabled"):
            return None
        if self._job_resolution("insights") is None and not server.llm_endpoint:
            return None

        def complete(prompt: str) -> str:
            """One model call over whatever serves the insights job, raw.

            A failing endpoint raises: each caller decides its own
            fallback, so the same adapter serves drafts that fall back to
            the template and explanations that refuse.
            """
            client, _name, _model = self._effective_llm("insights")
            return client(prompt)

        return complete

    def _setup_error(self, exc: Exception) -> None:
        """Answer a failed setup step in the envelope the setup client reads.

        A ConfigError keeps its own code and message at 400; anything else becomes
        config:failed with the exception's text, so an unexpected failure names itself
        rather than arriving as a bare 500.
        """
        from ..plugins.config import ConfigError
        if isinstance(exc, ConfigError):
            self._send_json(_SETUP_ERROR_STATUS.get(exc.code, 400),
                            {"error": exc.code, "message": exc.message})
            return
        self._send_json(400, {"error": "config:failed", "message": str(exc)})

    def _dispatch_plugin_post(self, plugins: PluginRuntime, path: str, body: dict) -> None:
        """Deprecated: /api/plugins mutations are deleted in the 2026-Q4
        release; new clients use /api/marketplace/* (see marketplace/api.py)."""
        parts = [part for part in path.split("/") if part]
        if "/instances" in path:
            self._plugin_setup_post(plugins, path, body)
            return
        if path == "/api/plugins/install":
            if not isinstance(body.get("zip_path"), str):
                self._send_json(400, {"error": "bad-request",
                                      "message": 'expected {"zip_path": "..."}'})
                return
            result = plugins.install(body["zip_path"], source=body.get("source", "zip"))
            plugin_id = str(result.get("id", "")) if isinstance(result, dict) else ""
            held = (isinstance(result, dict)
                    and result.get("status") == "pending-consent")
            if held:
                # An install over an installed plugin holds for consent
                # exactly like an update; the user meets the same card.
                result = self._hold_update_for_consent(plugins, plugin_id, result)
                held = (isinstance(result, dict)
                        and result.get("status") == "pending-consent")
            self._audit(
                "plugin.install", target=plugin_id,
                detail=("held for consent: adds "
                        + "; ".join(result.get("added_scopes", [])) if held
                        else f"v{result.get('version', '')} pilot install"))
            self._send_json(200, result)
            return
        if len(parts) < 3:
            self._send_json(404, {"error": "not-found", "message": path})
            return
        plugin_id = parts[2]
        action = parts[3] if len(parts) > 3 else ""
        if action == "publish":
            # Registry-side, not a runtime lifecycle method: publish
            # resolves the registry root and writes into it.
            self._publish_plugin(plugins, plugin_id)
            return
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
        raw_cause = str(card.get("cause") or "data source has not run")
        cause = html.escape(raw_cause)
        retestable = status == ATTENTION and _plugin_retest_can_change(raw_cause)
        file_name = html.escape(str(card.get("file") or "the data source"))
        version = html.escape(str(card["version"]))
        payload = card.get("payload") or {}
        source = payload.get("source") if isinstance(payload, dict) else None
        # A stale read keeps its last good value, but it must not wear the live stamp.
        stale = (status == FRESH and isinstance(source, dict)
                 and source.get("state") == "stale")
        elements = payload.get("elements") if isinstance(payload, dict) else None
        if status == FRESH and elements:
            parts = [
                _plugin_element_html(element)
                for element in elements
                if isinstance(element, dict)
            ]
            body = "".join(parts) or (
                '<p class="w-big">' + version + '</p><p class="w-note">'
                "reading " + file_name + "</p>")
            extra = ""
        elif status == FRESH:
            cause = f"reading {file_name}"
            body = '<p class="w-big">' + version + '</p><p class="w-note">' + cause + "</p>"
            extra = ""
        else:
            if retestable:
                offer = (
                    "<p>Re-test runs the plugin's data source again; the nightly "
                    "probe does the same for every plugin.</p>"
                )
            else:
                offer = (
                    "<p>A re-test cannot change this. Remove the plugin on the "
                    "Plugins page if you do not need it.</p>"
                )
            body = (
                '<div class="alert" id="plugin-amber-' + plugin_id + '">'
                "<p>" + cause + "</p>" + offer + "</div>"
            )
            extra = "amber"
        if status == FRESH:
            # The reading's resolved lines and its press belong on the card, so
            # the rendered dashboard is never a poorer version of the API.
            insight = payload.get("insight")
            body += _receipt_line(payload)
            body += _press_form(card, insight.get("press") if isinstance(insight, dict) else None)
        stamp = "live"
        if stale:
            checked = str(card.get("checked_at") or "")
            try:
                hhmm = datetime.fromisoformat(checked).strftime("%H:%M")
            except ValueError:
                hhmm = ""
            stamp = f"Stale since {hhmm}" if hhmm else "Stale"
        freshness = Freshness(
            status=ATTENTION if stale else status,
            stamp=("Re-test available" if retestable
                   else "Needs attention" if status == ATTENTION else stamp),
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
        """Deprecated: /api/plugins/<id> is deleted in the 2026-Q4 release;
        the new detail route is /api/marketplace/plugin/<id>."""
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
        """The plugin records the SPA's plugin list consumes, one per installed plugin.

        Uninstalled records are dropped: with no active version there is no card for a
        view to render. A pending update is reduced to the version and the scopes it
        would add, which is exactly what an update would widen, and pilot marks a record
        that is enabled with pilot views left (the flag means a view can still be
        spent, so a disabled plugin never carries it).
        """
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            return []
        out = []
        for record in plugins.list_records():
            record = dict(record)
            if record.get("state") == "uninstalled":
                continue  # no active version, so there is no widget to render
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
        """Deprecated: /api/registry is deleted in the 2026-Q4 release; new
        clients read /api/marketplace/catalog."""
        root, origin = self._registry_root_for_request()
        listing = registry_source.registry_listing(root)
        listing["origin"] = origin
        if listing.get("ok"):
            self._audit("registry.read", target="registry",
                        detail=f"{len(listing.get('plugins', []))} plugins from {origin}")
        return listing

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
        if action == "publish":
            # Registry-side, not a runtime lifecycle method: publish
            # resolves the registry root and writes into it.
            self._publish_plugin(plugins, plugin_id)
            return
        body = self._read_json_body() or {}
        if action in ("share", "unshare"):
            self._plugins_share(plugins, plugin_id, action == "share")
            return
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
            self._send_notice_redirect("/plugins", str(exc))
            return
        self._audit(f"plugin.{action}", target=plugin_id,
                    detail=f"page action {action}")
        self._send_redirect("/plugins")

    def _plugins_share(self, plugins: PluginRuntime, plugin_id: str,
                       shared: bool) -> None:
        """The Share toggle: mark an installed plugin as publishable to
        paired desks (or stop sharing it). Nothing is served until a
        peer actually asks, and only then the plugin's own files."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._send_error_page(503, "Peers unavailable",
                                  "The peer store is not available, so "
                                  "sharing cannot be changed.")
            return
        try:
            record = plugins.record(plugin_id)
        except PluginError as exc:
            self._send_notice_redirect("/plugins", str(exc))
            return
        if record.get("state") == "uninstalled" or not record.get("versions"):
            self._send_notice_redirect(
                "/plugins",
                f"Only an installed plugin can be shared; "
                f"{plugin_id} has no installed files.")
            return
        store.set_shared(plugin_id, shared)
        self._audit("peer.share", target=plugin_id,
                    detail="shared with paired desks" if shared
                    else "sharing stopped")
        verb = "shared with paired desks" if shared else "no longer shared"
        self._send_notice_redirect("/plugins", f"{plugin_id} is now {verb}.")

    def _registry_install(self) -> None:
        """Install one pinned release from the registry checkout.

        The registry machinery owns verification (pin resolution, tag
        extraction, tree digest, the shared validator); the runtime owns
        the versioned install, pilot badge and consent flow. Forms get a
        redirect with the outcome as the notice line; JSON callers get
        the record. Deprecated: both legacy addresses this handler serves
        (/api/registry/install, /plugins/registry-install) are deleted in
        the 2026-Q4 release; new clients POST /api/marketplace/install.
        """
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            self._registry_refused("plugins:unavailable",
                                           "no plugin runtime is configured")
            return
        body = self._read_json_body() or {}
        plugin_id = str(body.get("id", "")).strip()
        version = str(body.get("version", "")).strip() or None
        if not plugin_id:
            self._registry_refused("bad-request",
                                           'expected {"id": "...", "version": "..."}',
                                           status=400)
            return
        root, _origin = self._registry_root_for_request()
        if root is None:
            self._registry_refused(
                "registry:not-configured",
                "No plugin registry is configured. Set one in Settings.")
            return
        # An id@version that is already the active install is an honest
        # "already", not a second success (the double-click case): the
        # state would not change, so neither may the notice. A request
        # for a DIFFERENT version still proceeds: that is a legitimate
        # install or rollback to it.
        try:
            record = plugins.record(plugin_id)
        except PluginError:
            record = None
        if record is not None:
            active = str(record.get("active_version", ""))
            if active and (version is None or version == active):
                self._audit("plugin.install", target=plugin_id,
                            detail=f"already installed v{active}; nothing changed")
                self._respond_form_or_json(f"/plugins?notice={quote(
                    'Already installed ' + plugin_id + ' v' + active + '.')}",
                    {"ok": True, "already": True, "version": active})
                return
        try:
            with tempfile.TemporaryDirectory(prefix="agentdesk-registry-") as tmp:
                staged = registry_source.stage_registry_install(
                    root, plugin_id, version=version,
                    sha256=body.get("sha256"), staging_dir=Path(tmp))
                result = plugins.install(staged["dir"], source="registry")
        except (RegistryError, RegistryIndexError) as exc:
            self._registry_refused(
                getattr(exc, "code", "install:refused"), str(exc))
            return
        except PluginError as exc:
            self._registry_refused(exc.code, str(exc), exc.status)
            return
        if (isinstance(result, dict)
                and result.get("status") == "pending-consent"):
            # An install over an installed plugin holds for consent
            # exactly like an update; the user meets the same card.
            result = self._hold_update_for_consent(plugins, plugin_id, result)
        self._audit(
            "plugin.install", target=plugin_id,
            detail=("registry install held for consent: adds "
                    + "; ".join(result.get("added_scopes", []))
                    if isinstance(result, dict)
                    and result.get("status") == "pending-consent"
                    else f"registry v{result.get('version', '')} pinned install"))
        if self._is_form_submit():
            if isinstance(result, dict) and result.get("status") == "pending-consent":
                self._send_notice_redirect(
                    "/plugins",
                    plugin_id + "'s new release is waiting for your decision; "
                    "it adds: " + '; '.join(result.get('added_scopes', [])) + '.')
                return
            self._send_notice_redirect(
                "/plugins",
                'Installed ' + plugin_id + ' v' + str(result.get('version', '')) + '.')
            return
        self._send_json(200, result)

    def _registry_refused(self, code: str, message: str,
                          status: int = 409) -> None:
        """A refused registry install or publish, in one shape.

        A form post goes back to the plugins page with the message as a notice, because
        a browser form has nowhere else to put it; a fetch gets the code and message as
        JSON, at 409 unless the caller names another status.
        """
        self._respond_form_or_json(f"/plugins?notice={quote(message)}",
                                   {"error": code, "message": message}, status)

    def _publish_plugin(self, plugins: PluginRuntime, plugin_id: str) -> None:
        """Publish one installed plugin to the resolved registry (#63).

        The registry machinery owns the write (shared validator first,
        tree copy, digest pin, index append); the runtime only says
        which version directory is active. Forms get a redirect with
        the outcome as the notice line; JSON callers get the record.
        """
        try:
            record = plugins.record(plugin_id)
            if record.get("state") == "uninstalled" or not record.get("versions"):
                raise PluginError(
                    "publish:uninstalled",
                    f"{plugin_id} has no installed version to publish", 409)
            version = str(record.get("active_version", ""))
            source_dir = plugins.version_dir(plugin_id)
            root, origin = self._registry_root_for_request()
            if root is None:
                raise RegistryError(
                    "publish:no-registry",
                    "No plugin registry is configured, so there is nowhere "
                    "to publish to. The registry resolves in this order: "
                    "the registry_path saved in Settings, the "
                    "AGENTDESK_REGISTRY environment variable, then this "
                    "app's own checkout. Set one in Settings.")
            result = publish_to_registry(root, plugin_id, version=version,
                                         source_dir=source_dir)
        except PluginError as exc:
            self._registry_refused(exc.code, str(exc), exc.status)
            return
        except (RegistryError, RegistryIndexError) as exc:
            self._registry_refused(
                getattr(exc, "code", "publish:refused"), str(exc))
            return
        self._audit("registry.publish", target=plugin_id,
                    detail=f"local v{result.get('version', '')} to the "
                           f"{origin} registry")
        self._respond_form_or_json(f"/plugins?notice={quote(
            'Published ' + plugin_id + ' v'
            + str(result.get('version', '')) + ' to the registry.')}", result)

    def _registry_path_save(self) -> None:
        """Save or clear the registry checkout path (the settings form)."""
        settings = self._require_store(self.server.settings, "settings store")
        if settings is None:
            return
        body = self._read_json_body() or {}
        chosen = str(body.get("path", "")).strip()
        if chosen and not (Path(chosen) / "index.json").is_file():
            self._send_notice_redirect(
                "/plugins",
                "That folder has no registry index (index.json). "
                "Nothing was saved.")
            return
        settings.set(registry_source.SETTINGS_KEY, chosen)
        self._audit("settings.registry", target="registry_path",
                    detail="cleared" if not chosen else "updated")
        self._send_redirect("/plugins")

    def _extra_hosts_save(self) -> None:
        """The settings form for the guard's extra allowed hosts: the
        host[:port] entries admitted beyond loopback. Stored as typed
        (comma or space separated); the guard re-reads it on every
        request, so an empty save returns to loopback-only at once."""
        settings = self._require_store(self.server.settings, "settings store")
        if settings is None:
            return
        body = self._read_json_body() or {}
        if self._is_form_submit():
            # Form parsing drops an emptied field, so in a form post the
            # field's absence IS the empty value: clearing works with no
            # JavaScript and no second button.
            hosts = body.get("hosts", "")
        else:
            hosts = body.get("hosts")
            if not isinstance(hosts, str):
                self._send_json(400, {"error": 'expected {"hosts": "..."}'})
                return
        settings.set("extra_allowed_hosts", hosts.strip())
        self._audit("settings.hosts", target="extra_allowed_hosts",
                    detail="cleared" if not hosts.strip() else "updated")
        self._respond_form_or_json("/settings",
                                   {"key": "extra_allowed_hosts", "value": hosts.strip()})

    def _route_wizard(self, method: str, path: str) -> None:
        """The wizard surface: describe, answer, build, preview, approve."""
        wizard = self._require_store(self.server.wizard_store, "wizard")
        if wizard is None:
            return
        parts = [part for part in path.split("/") if part]  # ["wizard", ...]
        if method == "GET" and len(parts) < 2 and parts[0] == "wizard":
            # /wizard is the entry, not a 404: the describing screen a
            # POST-less visitor can start from, behind the same gate. The
            # exact single segment only: the router dispatches on the
            # prefix, so a lookalike (/wizardx) must keep its 404.
            page = render_wizard_page(WIZARD_DESCRIBING_PAYLOAD, agentdesk.__version__)
            self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if method == "POST" and path == "/wizard/start":
            body = self._read_json_body() or {}
            description = str(body.get("description", "")).strip()
            if not description:
                # The dashboard button lands here first: ask for the words
                # before a session exists. No-JS: a plain form.
                page = render_wizard_page(
                    {"id": "new", "state": "describing", "description": "",
                     "questions": [], "draft": {}, "ui_schema": None,
                     "sample_rows": [], "degradedNote": self._wizard_endpoint_note()},
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
        """Let the description fill the choices in, then ask what is left.

        With no AI connection nothing is filled and the source question opens
        the walk. With one, the autofill preselects what it can and the same
        walk shows the rest; a field it could not fill is simply still open.
        Either way the questions are the closed vocabulary's, never invented.
        """
        compiler = self._wizard_compiler()
        if compiler is None:
            compiler = WizardCompiler(None)
        filled: dict = {}
        reasons: dict = {}
        try:
            filled, reasons = compiler.autofill_with_reasons(description)
        except Exception:  # noqa: BLE001 - a failed fill leaves every field open
            LOG.exception("wizard autofill failed; asking every question")
            filled, reasons = {}, {}
        session.autofilled = bool(filled)
        session.reasons = reasons
        session.answers = merge_answers(session.answers, filled)
        session.questions = questions_for_answers(session.answers)
        session.state = "questions"
        self.server.wizard_store.save(session)  # type: ignore[attr-defined]

    def _wizard_compiler(self):
        """The compiler's endpoint client, audited, through the resolution
        hub on the default job (spec 018 #233): a bound connection, the
        saved settings rows, then the startup endpoint. None when nothing
        is configured anywhere, so the deterministic path runs on purpose
        instead of a client that raises on every call; the wizard never
        blocks on the llm."""
        server = self.server  # type: ignore[attr-defined]
        if server.audit_conn is None:
            return WizardCompiler(None)
        resolved = self._job_resolution(DEFAULT_JOB)
        if (resolved is None and getattr(server, "llm_defaulted_to_env", False)
                and not server.llm_endpoint):
            return WizardCompiler(None)
        inner, endpoint, model = self._effective_llm(DEFAULT_JOB)
        conn = server.audit_conn

        def audited_llm(prompt: str) -> str:
            """The wizard's prompt call, recorded as llm.wizard.

            Endpoint and model are those resolved when the compiler was built, so the
            row names the client that actually answered (a saved connection answers
            to its label, spec 018). A failure records the error text and re-raises,
            leaving the wizard's own error handling intact.
            """
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

    def _wizard_session_or_404(self, session_id: str):
        """The session an action names, or None with the store's own
        not-found sent: the honest 404 a stale link deserves, never the
        generic restart page. A form post gets the error page, a JSON
        client the store's named error."""
        try:
            return self.server.wizard_store.get(session_id)  # type: ignore[attr-defined]
        except WizardError as exc:
            if self._is_form_submit():
                self._send_error_page(exc.status, "Nothing here", str(exc))
            else:
                self._send_json(exc.status, {"error": exc.code, "message": str(exc)})
            return None

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
        session = self._wizard_session_or_404(session_id)
        if session is None:
            return
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
            if answers is None:
                # A form post carrying no usable answer is a no-op: it must
                # not build from whatever the session already held.
                self._send_redirect(f"/wizard/{session_id}")
                return
        if not answers:
            # A post with no answer at all is the manager opening the walk,
            # not answering it: the questions stay, unanswered.
            answers = dict(session.answers)
        answers = normalize_answers(answers)
        session.answers = answers
        # Only every question on the chosen path answered builds anything.
        # Anything short of that re-renders the walk with what is answered so
        # far, which is what keeps the workbook from being filled in behind
        # a manager who chose something else.
        session.questions = questions_for_answers(answers)
        if resolve_choice(answers) is None:
            wizard.save(session)
            self._send_redirect(f"/wizard/{session_id}")
            return
        compiler = self._require_store(self._wizard_compiler(), "wizard")
        if compiler is None:
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
        pilot mode. A form post (the no-JS browser) answers with a
        redirect back to the session page, which renders the approved
        screen; a JSON client keeps the 200 install document."""
        wizard = self.server.wizard_store  # type: ignore[attr-defined]
        session = self._wizard_session_or_404(session_id)
        if session is None:
            return
        plugins = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            if self._is_form_submit():
                self._send_error_page(503, "Plugins unavailable",
                                      "No plugin runtime is configured.")
            else:
                self._send_json(503, {"error": "plugins:unavailable",
                                      "message": "no plugin runtime is configured"})
            return
        if session.state != "preview" or not session.draft:
            # The refusal, honestly rendered: back to the page, which
            # shows the state the session is really in (the approved
            # screen after an approval, the preview and its button
            # otherwise). Nothing installs twice.
            self._respond_form_or_json(f"/wizard/{session_id}",
                                       {"error": "wizard:not-in-preview"}, 409)
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
        self._respond_form_or_json(f"/wizard/{session_id}", {
            "status": "installed", "pilot": True,
            "summary": summary, "install": result})

    def _wizard_escalate(self, session_id: str, reason: str) -> None:
        """End a wizard session as escalated and send the user back to its page.

        The session is loaded first, so the escalation is recorded against a real one;
        the redirect lands on the page that reads the new state.
        """
        session = self._wizard_session_or_404(session_id)
        if session is None:
            return
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
        """Render one wizard session.

        404 when the store cannot load it. The payload is the session's JSON with the
        draft reshaped for the view: the draft itself is the manifest, because the
        approval summary reads permissions from it, while the ui schema and a fixed
        sample ride top-level so the view can show a shape before real data exists. The
        installed record is passed through, since the approved screen's publish step
        needs the plugin id.
        """
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
        # The approved screen's publish step needs the install record
        # (the plugin id); the draft keeps it after approval.
        payload["installed"] = (draft.get("installed")
                                if isinstance(draft, dict) else None)
        payload["approval"] = approval_summary(payload["draft"]) if payload["draft"] else {}
        payload["degradedNote"] = self._wizard_endpoint_note()
        page = render_wizard_page(payload, agentdesk.__version__)
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _wizard_endpoint_note(self) -> str:
        """'' when an endpoint will shape the wizard's questions and
        copy, else the honest line that names the cause: the standard
        questions are the whole path until one is configured. Derived
        from the same compiler the build will use, so the note never
        claims an absence an injected endpoint fills. A malformed saved
        base is an absence too: every consult raises, so the questions
        are the standard ones whether or not a base string exists."""
        compiler = self._wizard_compiler()
        if compiler.llm is not None:
            settings = self.server.settings  # type: ignore[attr-defined]
            saved_base = settings.get("llm_base") if settings is not None else ""
            if not base_url_problem(saved_base):
                return ""
        return (
            "No AI is saved, so the wizard asks its "
            "standard questions and builds the same way. Add your AI key "
            "in Settings and it can tailor its questions to your ask."
        )

    def _send_marketplace_shell(self, status: int = 200, notice: str = "") -> None:
        """The SPA shell for a marketplace deep link, when the build exists.

        A notice (a plugin action's confirmation or named refusal riding its
        redirect chain) is rendered into the body server-side: the SPA mounts
        into #root and leaves the sibling alone, and without JavaScript the
        sentence is still on the page. The value is escaped, the slot is the
        alert markup the server pages already use.
        """
        index = spa_index_path()
        if index.is_file():
            page = index.read_text(encoding="utf-8")
            if notice and '<div id="root">' in page:
                banner = (
                    '<div class="alert" role="status" '
                    'style="padding:16px 20px"><p>'
                    + html.escape(notice)
                    + "</p></div>"
                )
                page = page.replace('<div id="root">', banner + '<div id="root">', 1)
            self._send_bytes(status, page.encode("utf-8"),
                             "text/html; charset=utf-8")
        else:
            self._send_error_page(
                404, "Marketplace unavailable",
                "The marketplace interface is not built in this checkout.")

    def _send_redirect_302(self, location: str) -> None:
        """Redirect with 302, for an address that has moved.

        _responded is set first, so a later failure in the same request will not try to
        answer over this one.
        """
        self._responded = True
        self.send_response(302)
        self.send_header("Location", location)
        self._common_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _form_return_to(self, body: dict, default: str) -> str:
        """The local page a no-JS form post came back to, or the default.

        Only /settings paths are honored: those are the pages that post a form
        here, and the allowlist keeps a crafted return_to from bouncing the
        browser to another origin (no open redirect).
        """
        target = body.get("return_to")
        if isinstance(target, str) and re.fullmatch(
            r"/settings(/[A-Za-z0-9_\-/]*)?(#[A-Za-z0-9_-]+)?", target,
        ):
            return target
        if isinstance(target, str):
            return "/settings"
        return default

    def _send_redirect(self, location: str) -> None:
        """Redirect with 303, for a form post that has been handled.

        303 is what makes the browser follow with a GET, so a reload repeats the page
        rather than the action. _responded is set first, so a later failure in the same
        request will not try to answer over this one.
        """
        self._responded = True
        self.send_response(303)
        self.send_header("Location", location)
        self._common_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_notice_redirect(self, target: str, notice: str,
                              kind: str = "status") -> None:
        """Redirect to `target` with an outcome notice in its query.

        The query goes before any fragment: `/settings#updates?notice=x`
        never sends the query at all, so the sentence is lost. The target's
        own query, if any, is kept, and its fragment is put back last.
        """
        base, hash_sep, fragment = target.partition("#")
        joiner = "&" if "?" in base else "?"
        query = "notice=" + quote(notice)
        if kind == "alert":
            query = "notice_kind=alert&" + query
        location = base + joiner + query
        if hash_sep:
            location += "#" + fragment
        self._send_redirect(location)

    def _send_health(self) -> None:
        """The health payload as indented JSON.

        Built from the live source table and the process start time, so each source's
        state and the uptime are read at request time rather than remembered from boot.
        """
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
        """Send one JSON body with the given status.

        Indented output is deliberate, because these endpoints are also read by eye; the
        content type carries the charset so a non-ASCII message survives the trip.
        """
        self._send_bytes(
            status,
            json.dumps(payload, indent=2).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _require_store(self, store, name: str):
        """The one refusal for an optional store that is not configured.

        Every handler used to write its own None check, and the sentences
        drifted ("skills are not available", "settings are not available").
        One helper keeps the status, the JSON shape and the wording in one
        place. Returns the store, or None once the 503 has gone out.
        """
        if store is None:
            self._send_json(503, {"error": f"the {name} is not available"})
            return None
        return store

    def _store_missing(self, name: str, *, status: int = 503, sentence: str = "",
                       notice: str = "") -> StoreMissing:
        """The one decision point for an optional store that is not there,
        for callers that answer in more than one shape (the engine tool
        helpers return refusal tuples; form handlers render a page).

        A refusal site asks here instead of building its own tuple or
        dict. The JSON sentence defaults to `_require_store`'s exact
        wording, so JSON callers keep the bytes they always sent; the
        form notice defaults to the same sentence capitalized, and a
        caller whose page copy says more (the wave's failure lines,
        which name what failed and the next step) passes `notice`.
        """
        sentence = sentence or f"the {name} is not available"
        return StoreMissing(status=status, sentence=sentence,
                            notice=notice or (sentence[0].upper() + sentence[1:]))

    def _send_store_missing(self, outcome: StoreMissing, render=None) -> None:
        """Answer a store-missing outcome in the caller's own shape.

        A form post renders the page it came from with the outcome's
        notice (never raw JSON on a form post; the page's typed-value
        handling keeps what the reader typed, F5), and every other
        caller gets the raw JSON payload, byte-identical to the answer
        those callers always got. `render` is the caller's one-argument
        page renderer for the form shape; without one the notice rides
        the plain error page, so a form post can still never meet raw
        JSON.
        """
        if self._is_form_submit():
            if render is None:
                self._send_error_page(outcome.status, "Not available",
                                      outcome.notice)
            else:
                render(outcome.notice)
            return
        status, payload = outcome.as_json()
        self._send_json(status, payload)

    def _send_error_page(self, status: int, title: str, message: str) -> None:
        """Send one HTML error page with the given status.

        The page carries a title and a message and nothing else, so a refusal can be
        specific without a traceback reaching the browser.
        """
        self._send_bytes(
            status,
            pages.render_error_page(title, message).encode("utf-8"),
            "text/html; charset=utf-8",
        )

    def _send_bytes(self, status: int, body: bytes, content_type: str,
                    headers: dict | None = None) -> None:
        """Send one response body and mark the request answered.

        Content-Length is the body's own length, and every response path (page, JSON,
        file, error) goes through here, so the security headers cannot be forgotten on
        one of them. extra headers precede the common set, which is where a caller adds
        one rather than where it overrides the defaults.
        """
        self._responded = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self._common_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _common_headers(self) -> None:
        """The headers every response carries.

        The security set comes first; the Connection close follows only when the request
        left the connection unusable: its body was past the drain cap, or refused
        before the drain. Naming it here is what actually closes, because http.server
        flips close_connection when it sees that header.
        """
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        if getattr(self, "_close_with_response", False):
            # The request leaves the connection unusable (its body was
            # beyond the drain cap, or refused before the drain): the
            # answer names the close (send_header also flips
            # close_connection).
            self.send_header("Connection", "close")

def _background_runner(job) -> None:
    """Run a memory capture off the request thread."""
    threading.Thread(target=job, name="memory-capture", daemon=True).start()

def create_server(
    host: str = "127.0.0.1",
    port: int | None = None,
    excel: ExcelWatch | None = None,
    pick_workbook=None,
    pick_plugin_file=None,
    calendar: CalendarBridge | None = None,
    llm=None,
    audit_conn=None,
    ledger: Ledger | None = None,
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
    learned_profile: LearnedProfileStore | None = None,
    layout_store: LayoutStore | None = None,
    capabilities_cache: CapabilitiesCache | None = None,
    gate_runners: GateRunners | None = None,
    mail: MailWatch | None = None,
    mail_store: MailStore | None = None,
    research_store: ResearchStore | None = None,
    agents_store: AgentRunStore | None = None,
    outbox_dir=None,
    registry_root=None,
    peer_store: PeerStore | None = None,
    keys_store: KeysStore | None = None,
    keychain=None,
    connection_check=None,
    extractor=None,
    reflector=None,
    announce_port: int | None = None,
    skills_snapshots_dir: Path | str | None = None,
    engine_runner=None,
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
    # Spec 016 section 6.5, checked before any store opens: whether this
    # data folder was already used before this boot. Opening the inbox or
    # memory database would create the very file this check looks for, so
    # it must run first; the write itself happens once the settings store
    # is open.
    folder_data_dir = default_data_dir()
    folder_was_used = (
        (folder_data_dir / "inbox.sqlite3").exists()
        or (folder_data_dir / "memory.sqlite3").exists()
    )
    sessions = SessionStore()
    if excel is None:
        excel = _default_excel_watch()
    # Settings first: the default calendar bridge wires its breakdown
    # client to them, so saved endpoints apply without a restart.
    if settings_store is None:
        settings_store = _default_settings_store()
        # The "learn automatically" row is written only to the settings
        # store this boot opened itself: an injected store belongs to its
        # caller, who decides what its keys hold.
        if settings_store is not None:
            _store_memory_auto_approve_default(settings_store, folder_was_used)
    if calendar is None:
        calendar = _default_calendar_bridge(settings_store)
    if audit_conn is None:
        audit_conn = _default_audit_conn()
    if ledger is None:
        ledger = _default_ledger()
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
    if pick_plugin_file is None:
        # Embedders and tests that inject one picker get that picker for
        # instance setup too; production widens the dialog to every format
        # the instance store can stage.
        pick_plugin_file = (
            tk_pick_plugin_file if pick_workbook is tk_pick_workbook else pick_workbook
        )
    if pick_calendar is None:
        pick_calendar = tk_pick_calendar
    if wizard_store is None:
        wizard_store = _default_wizard_store()
    if memory_store is None:
        memory_store = _default_memory_store()
    if learned_profile is None:
        learned_profile = LearnedProfileStore(
            default_data_dir() / "profile.learned.json")
    if layout_store is None:
        layout_store = _default_layout_store()
    if capabilities_cache is None:
        capabilities_cache = _default_capabilities_cache()
    if gate_runners is None:
        gate_runners = _default_gate_runners(settings_store)
    if mail_store is None:
        mail_store = _default_mail_store()
    if mail is None and inbox_store is not None and mail_store is not None \
            and bool(settings_store.get("mail_enabled")):
        mail = _default_mail_watch(settings_store, inbox_store, mail_store)
    if research_store is None:
        research_store = _default_research_store()
    if agents_store is None:
        agents_store = _default_agents_store()
    if plugins is None:
        # After the mail block on purpose: the default runner's
        # pipeline bindings read the very objects built above, so a
        # calendar-read, mail-digest or research-brief plugin binds the
        # same data the built-in cards show (#64). The settings toggle
        # rewires mail as it rebuilds the watcher.
        plugins = _default_plugins(
            calendar=calendar,
            mail=mail if bool(settings_store.get("mail_enabled")) else None,
            research=research_store,
        )

    if peer_store is None:
        peer_store = _default_peer_store()
    # The named connections (spec 018): the store gets its own sqlite
    # file in the data dir; the keychain wrapper defaults to the real
    # keyring client (an injectable fake in tests, a machine with no
    # backend answers available() False and stores no secret).
    if keys_store is None:
        keys_store = _default_keys_store()

    def construct(bind_port: int) -> AgentDeskServer:
        """Build the server bound to one port, everything else fixed.

        The enclosing factory calls this once for the preferred port and again with 0
        when that port is taken, so only the port may differ between the two attempts;
        all the stores were resolved before it, which is what makes the retry cheap.
        """
        return AgentDeskServer(
            (resolved, bind_port),
            sessions=sessions,
            excel=excel,
            pick_workbook=pick_workbook,
            pick_plugin_file=pick_plugin_file,
            calendar=calendar,
            llm=llm,
            audit_conn=audit_conn,
            ledger=ledger,
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
            learned_profile=learned_profile,
            layout_store=layout_store,
            capabilities_cache=capabilities_cache,
            gate_runners=gate_runners,
            mail=mail,
            mail_store=mail_store,
            research_store=research_store,
            agents_store=agents_store,
            outbox_dir=outbox_dir,
            registry_root=registry_root,
            peer_store=peer_store,
            keys_store=keys_store,
            keychain=keychain,
            connection_check=connection_check,
            extractor=extractor,
            reflector=reflector,
            announce_port=announce_port,
            skills_snapshots_dir=skills_snapshots_dir,
            engine_runner=engine_runner,
        )

    if port is None:
        try:
            server = construct(PREFERRED_PORT)
        except OSError:
            server = construct(0)
    else:
        server = construct(port)
    _wire_audit(server)
    _migrate_legacy_endpoints(server)
    # The first recommendation pass runs once the desk is fully wired: facts
    # saved by an earlier run become waiting cards before any page is read.
    if server.recommender is not None:
        try:
            server.recommender.refresh()
        except MemoryEncryptedError:
            # A locked memory bank cannot be read; the rest of the desk still
            # starts, and the memory page explains the missing key.
            pass
    # A version staged by an earlier run is checked in-process before this
    # boot serves anything. A failure points the launcher back and repairs a
    # store that no longer passes its integrity check (spec 016 section 6.8).
    try:
        from agentdesk.update import first_start

        started = first_start(default_data_dir())
        if started.get("lastResult") == "rolled-back" and server.audit_conn is not None:
            from agentdesk.assistant import audit_store

            audit_store.record(
                server.audit_conn, "update.rolled-back",
                target=str(started.get("current") or ""), status="error",
                detail=str(started.get("lastCause") or "")[:300],
            )
    except Exception:  # noqa: BLE001 - an update check never blocks the desk
        LOG.exception("first-start update check failed")
    # The supervised loop is built here and started in
    # start_background_polls, so it lives and dies with the server process
    # (spec 016 section 6.2). Its run claim lives in the data folder.
    server.agent_loop = AgentLoop(server, data_dir=default_data_dir())
    return server


# -- learned focus topics (spec 016 section 6.5, the learn-topics step) -----

# The same ask window Consolidator.consolidate reads: the last 500 asks
# through the app's own surfaces.
_LEARN_TOPICS_WINDOW = 500


def _store_memory_auto_approve_default(
    settings_store: SettingsStore, folder_was_used: bool) -> None:
    """Store the "learn automatically" value a folder does not have yet.

    A folder an earlier build already used keeps "ask me first" (spec 016
    section 6.5): it stores the explicit False. A folder born on this build
    stores the explicit True at the boot that creates it (spec 022): without
    that row its second start looked like an old folder, because by then the
    folder holds a database, and the desk switched learning off by itself.
    Only a missing row is ever written, so a value the user set survives. The
    read runs once at boot, before request threads exist, so the bare
    statement on the shared connection is safe.
    """
    row = settings_store.conn.execute(
        "SELECT value FROM settings WHERE key = 'memory_auto_approve'"
    ).fetchone()
    if row is None:
        settings_store.set("memory_auto_approve", not folder_was_used)


def _entity_names(memory) -> dict[str, str]:
    """Entity names (canonical and aliases) mapped to their canonical
    name, lowercase keys, for the whole-word matching the step does. A
    locked or unreadable bank learns nothing rather than failing a pass."""
    names: dict[str, str] = {}
    try:
        summaries = memory.entities()
    except Exception:  # noqa: BLE001 - a locked bank is a named skip, not a crash
        return names
    for summary in summaries:
        canonical = str(getattr(summary, "canonical_name", "") or "").strip()
        if not canonical:
            continue
        names[canonical.lower()] = canonical
        for alias in getattr(summary, "aliases", None) or []:
            alias_line = str(alias or "").strip()
            if alias_line and alias_line.lower() not in names:
                names[alias_line.lower()] = canonical
    return names


def _name_pattern(name: str) -> str:
    """The whole-word regex for one entity name: word boundaries that
    hold inside normalized lowercased text, so "Kestrel" never matches
    "Kestrelshire" and multi-word names match in order."""
    words = [re.escape(word) for word in name.lower().split()]
    return r"(?<![a-z0-9])" + r"[\s]+".join(words) + r"(?![a-z0-9])"


def _cluster_subject(texts: list[str], cluster: list[int],
                     names: dict[str, str]) -> str | None:
    """The memory entity named most often across one cluster's texts, or
    None when no entity is named: no topic is learned from free text."""
    counts: dict[str, int] = {}
    for index in cluster:
        lowered = texts[index].lower()
        for name, canonical in names.items():
            if re.search(_name_pattern(name), lowered):
                counts[canonical] = counts.get(canonical, 0) + 1
    if not counts:
        return None
    # The most-mentioned entity; ties break by name so a pass is stable.
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def learn_focus_topics(server, ledger, settings, audit_conn=None) -> dict:
    """One learn-topics pass: clusters of similar asks that name a memory
    entity become learned focus topics (spec 016 section 6.5).

    Every mutation goes through the same one helper shape: capture
    `raw()`, mutate, record `learned-profile` with the before and after
    bytes, so Undo restores the whole document. The latch written at
    learn time (`topic:<name>`) is what keeps a removed topic from ever
    coming back, and the stated preferences are only ever read.
    """
    store = getattr(server, "learned_profile", None)
    activity = getattr(server, "activity_log", None)
    memory = getattr(server, "memory", None)
    if store is None or activity is None or memory is None or ledger is None:
        return {"topics": 0}
    asks = [e for e in activity.entries(_LEARN_TOPICS_WINDOW)
            if e["kind"] in ("research", "assistant")]
    names = _entity_names(memory)
    if not asks or not names:
        return {"topics": 0}
    texts = [e["text"] for e in asks]
    stated = [str(t) for t in (PreferenceStore(default_data_dir()).read()
                               .get("focusTopics") or [])]
    stated_lower = {t.lower() for t in stated}
    learned = 0
    for cluster in cluster_requests(texts):
        if len(cluster) < PROPOSAL_THRESHOLD:
            continue
        subject = _cluster_subject(texts, cluster, names)
        if subject is None:
            continue
        if subject.lower() in stated_lower:
            continue
        if ledger.latch_value(f"topic:{subject.lower()}") is not None:
            continue
        learned_topics = store.document()["focusTopics"]
        if any(str(t.get("topic", "")).lower() == subject.lower()
               for t in learned_topics):
            continue
        if len(merged_topics(stated, learned_topics)) >= MAX_TOPICS:
            continue
        before = store.raw()
        if not store.add_topic(subject, len(cluster)):
            continue
        ledger.latch(f"topic:{subject.lower()}", "learned")
        try:
            ledger.record(
                actor="agent-desk",
                action="profile.learned",
                subject=f"learned profile:{subject}",
                why=f"Learned the focus topic {subject}: named in "
                    f"{len(cluster)} similar asks.",
                undo_kind="learned-profile",
                before=before,
                after=store.raw(),
                detail={"topic": subject, "asks": len(cluster)},
            )
        except LedgerError:
            # The topic stays learned and latched; only its Activity
            # entry is lost, and the pass continues (the same guard the
            # removal route gives its own record).
            LOG.exception("the learned-profile record for %s failed", subject)
        if audit_conn is not None:
            audit_store.record(audit_conn, "profile.learned", target=subject,
                               detail=f"Learned from {len(cluster)} asks")
        learned += 1
    return {"topics": learned}


def _learn_topics_enabled(settings) -> bool:
    """The learn-topics step runs when its switch is on; a desk without
    settings keeps everything it has already learned and learns no more."""
    if settings is None:
        return False
    try:
        return bool(settings.get("learn_topics"))
    except KeyError:
        return False


def _run_learn_topics(ctx: LoopContext) -> dict:
    """The pass wrapper: run the learning over the loop context's desk."""
    return learn_focus_topics(
        ctx.server, ctx.ledger, ctx.settings,
        audit_conn=getattr(ctx.server, "audit_conn", None))


# Ticket 08's step is registered with the other ticket steps near the end of
# this module, in the order spec 016 section 6.2 gives.


# -- profile review (spec 016 section 6.5, the profile-review step) ---------

# The latch that counts new activity rows between reviews: the id of the
# newest row the last review was prompted with. Entries are not latched
# the way topics are (a removed line can be relearned from a later,
# different window; the user's removal already happened), and the
# removal route keeps this latch alone.
PROFILE_LATCH = "profile:last_activity_id"


def _profile_review_client(server, settings, audit_conn=None):
    """The endpoint client for one review, audited as llm.profile, or
    None when no call may be made.

    The review is served from the hub's memory job (the evidence run's
    defect 7.2, resolved as its option 2): _job_llm_parts resolves the
    job binding, the default binding, a single saved connection, the
    legacy llm_base row or the startup endpoint, so the review is
    reachable on a fresh install and not only on a folder with pre-hub
    rows, and a saved connection answers to its label. The wrapper
    follows the audited_llm pattern (llm.wizard): the row names the
    serving endpoint or label, the model and the request's byte size,
    never the prompt or reply, and a failure records its cause and
    re-raises so the step fails loudly and leaves its latch alone."""
    if settings is None:
        return None
    try:
        if not bool(settings.get("endpoint_enabled")):
            return None
    except KeyError:
        return None
    try:
        client, serving, model = _job_llm_parts(server, "memory")
    except Exception:  # noqa: BLE001 - a broken hub reads as unconfigured
        LOG.exception("the profile review could not resolve its endpoint")
        return None
    if client is None or not serving:
        return None
    if audit_conn is None:
        return client
    conn = audit_conn

    def audited_llm(prompt: str) -> str:
        """One review call, recorded as llm.profile with the size only."""
        try:
            result = client(prompt)
        except Exception as exc:  # noqa: BLE001 - audit then re-raise
            audit_store.record(conn, "llm.profile", target=serving,
                               status="error", model=model,
                               request_bytes=len(prompt.encode("utf-8")),
                               detail=str(exc)[:200])
            raise
        audit_store.record(conn, "llm.profile", target=serving,
                           status="ok", model=model,
                           request_bytes=len(prompt.encode("utf-8")))
        return result

    return audited_llm


def review_profile(server, ledger, settings, audit_conn=None) -> dict:
    """One profile-review pass: the last 24 activity rows and the
    current learned lines go to the company endpoint once ten or more
    new rows have arrived (spec 016 section 6.5).

    The endpoint's reply is the least trusted text on the desk, so it
    only ever reaches the store through profile_review.apply, which
    drops every op that is not grounded in the window, fails the strict
    injection scan, or breaks the budget, and accepts no remove ops.
    The latch advances to the window's max id after a review call
    completes, even when nothing was applied or the reply was not JSON;
    a failed call or an unchanged input leaves it so the window is
    retried. The input hash is remembered after a completed call so an
    unchanged window and learned list never buy a second call. The
    stated preferences are not an input and not a target here.
    """
    store = getattr(server, "learned_profile", None)
    activity = getattr(server, "activity_log", None)
    if store is None or activity is None or ledger is None:
        return {"applied": 0}
    rows = activity.entries(profile_review.TAIL)
    if not rows:
        return {"applied": 0}
    max_id = max(int(row["id"]) for row in rows)
    stored = ledger.latch_value(PROFILE_LATCH)
    try:
        last_seen = int(stored or 0)
    except ValueError:
        last_seen = 0
    waiting = max_id - last_seen
    if waiting < profile_review.NUDGE:
        return {"applied": 0, "waiting": waiting}
    context = LoopContext(server=server, ledger=ledger, settings=settings,
                          now=datetime.now().astimezone())
    payload = profile_review.build_input(rows, store.document())
    client = _profile_review_client(server, settings, audit_conn)
    if client is None:
        # The step is gated off (endpoint_enabled off) or no endpoint can
        # serve the call, in the loop path, so this only happens on a
        # direct call; the window stays unconsumed, and the review still
        # happens once an endpoint is configured.
        return {"applied": 0, "waiting": waiting}
    if context.input_unchanged("profile-review", payload):
        return {"applied": 0, "skipped": "input unchanged"}
    prompt = f"{profile_review.PROMPT}\n{json.dumps(payload, ensure_ascii=False)}"
    reply = client(prompt)
    context.remember_input("profile-review", payload)

    def record(before: bytes, after: bytes, note: str) -> str | None:
        """One learned-profile ledger entry per applied op; Undo
        restores the whole document, the way the removal route's
        record does. A failed record never undoes the learning, and
        one profile.learned audit row rides with the entry (the id
        is named, never the line's text)."""
        try:
            entry = ledger.record(
                actor="agent-desk",
                action="profile.learned",
                subject="learned profile:review",
                why=note,
                undo_kind="learned-profile",
                before=before,
                after=after,
            )
        except LedgerError:
            LOG.exception("the learned-profile record for the review failed")
            return None
        if audit_conn is not None:
            audit_store.record(audit_conn, "profile.learned",
                               target=entry.id, detail="Learned from activity")
        return entry.id

    result = profile_review.apply(reply, store, record,
                                  allowed_ids={int(row["id"]) for row in rows})
    ledger.latch(PROFILE_LATCH, str(max_id))
    return {"applied": result.applied,
            "dropped": sum(result.dropped.values())}


def _profile_review_enabled(settings) -> bool:
    """The review runs when its switch is on and the endpoint switch is
    on (spec 016 section 6.5). The base-URL check is not made here: the
    step gate sees only the settings store, while the configured answer
    needs the server (connections hub, legacy row, startup endpoint),
    so _profile_review_client makes it and leaves the window
    unconsumed when no channel can serve the call."""
    if settings is None:
        return False
    try:
        return bool(settings.get("learn_profile")) \
            and bool(settings.get("endpoint_enabled"))
    except KeyError:
        return False


def _run_profile_review(ctx: LoopContext) -> dict:
    """The pass wrapper: review the loop context's desk."""
    return review_profile(ctx.server, ctx.ledger, ctx.settings,
                          audit_conn=getattr(ctx.server, "audit_conn", None))


# Ticket 09's step is registered with the other ticket steps near the end
# of this module, in the order spec 016 section 6.2 gives.


def _migrate_legacy_endpoints(server: AgentDeskServer) -> None:
    """Run the legacy-endpoint migration (spec 018 #234) once per boot.

    The step is idempotent by label (a live migrated connection means a
    no-op) and doubles as the recovery path after a delete. It is boot
    plumbing, not request handling: it runs before the first request can
    arrive, it never probes an endpoint, and any failure is logged and
    left behind rather than failing the boot.
    """
    try:
        migrate_legacy_settings(
            server.settings, server.keys, server.keychain,
            record=_migration_audit(server.audit_conn))
    except Exception:  # noqa: BLE001 - a migration problem never fails a boot
        LOG.exception("the legacy endpoint migration did not complete")


def _migration_audit(conn):
    """The audit callback for the migration's keys.create rows, or None
    without an audit store. No secret material ever rides the detail."""
    if conn is None:
        return None

    def record(action: str, target: str, detail: str) -> None:
        """Record one migration row in the shared audit store."""
        audit_store.record(conn, action, target=target, detail=detail)

    return record


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
        """Record one action from a watcher into the shared audit store.

        The store connection is captured by the enclosing wiring, so a watcher only
        names the action, the target and whether it worked.
        """
        audit_store.record(conn, action, target=target, status=status)

    if server.excel is not None:
        server.excel.audit_hook = hook
    if server.mail is not None:
        server.mail.audit_hook = hook
    if server.calendar is not None:
        server.calendar.audit_hook = hook
        inner_llm = server.calendar.llm

        def audited_llm(prompt: str) -> str:
            """Wrap the calendar's breakdown client so each call is recorded as
            llm.breakdown, through the resolution hub on the default job
            (spec 018 #233).

            A saved connection serving the default job answers with its own
            base URL and key and the row names its label; with no
            connection the bridge's own client keeps serving and the
            endpoint is resolved per call with the same settings-over-
            environment order that client uses, so the row names what was
            really hit either way. The failure path records the error text
            and re-raises, so the caller still sees the real exception.
            """
            resolved = _server_resolution(server, DEFAULT_JOB)
            model = ""
            if resolved is not None and resolved.connection is not None:
                connection = resolved.connection
                client = _connection_client(
                    server, connection,
                    server.keychain.fetch(connection.id) or "",
                    resolved.model)
                endpoint = connection.label
                model = resolved.model
            else:
                client = inner_llm
                endpoint, _key, model = effective_llm_config(server.settings)
            try:
                result = client(prompt)
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

def _default_ledger() -> Ledger | None:
    """The action ledger, or None when it cannot open.

    The ledger records what the desk changed by itself together with the
    before and after state, so the Activity page can undo it; a failure to
    open leaves the desk usable, just without the trail.
    """
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        return Ledger(data_dir / "ledger.sqlite3")
    except (OSError, sqlite3.Error):
        LOG.exception("ledger unavailable")
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
    design), or None when it cannot open. The key file rides along when
    it exists: a marker without it locks the store, and the memory page
    says exactly that (ticket #94). A corrupt key file is not a crash:
    the log carries the detail and the store locks with the cause that
    names the path."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "memory.sqlite3", check_same_thread=False)
        key_path = key_file_path(data_dir)
        key = None
        key_corrupt = False
        if key_path.exists():
            try:
                key = read_key_file(key_path)
            except ValueError:
                # Not a crash, and not "missing": the flag threads the
                # true cause into the store's locked banner.
                LOG.exception("memory.key exists but is not a valid key")
                key_corrupt = True
        return MemoryStore(conn, time.time, key=key, key_path=key_path,
                           key_corrupt=key_corrupt)
    except (OSError, sqlite3.Error):
        LOG.exception("memory store unavailable")
        return None

def _default_layout_store() -> LayoutStore | None:
    """The dashboard card arrangement over the persistent store, or None
    when it cannot open (reads then resolve the canonical default)."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "layout.sqlite3", check_same_thread=False)
        return LayoutStore(conn)
    except (OSError, sqlite3.Error):
        LOG.exception("layout store unavailable")
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

def _default_outlook_feeder(settings_store) -> OutlookFeeder:
    """The real Outlook alert feeder: the host's collectors, the same
    mail folder the watcher reads, and its own status and lock files
    beside the other data."""
    return OutlookFeeder(
        collectors=default_collectors(),
        folder_provider=lambda: settings_store.get("mail_folder"),
        status_path=default_data_dir() / "outlook-feeder.json",
        lock_path=default_data_dir() / "outlook-feeder.lock",
        clock=time.time,
        platform=current_platform(),
    )

def _read_feeder_status() -> dict | None:
    """The last persisted Outlook alert status, or None when there is none.

    The runner writes outlook-feeder.json on every pass; reading it at
    watcher construction keeps the Settings card honest across a
    restart. A missing, unreadable or malformed file is ignored: the
    card falls back to its Not run yet state rather than failing a boot.
    """
    path = default_data_dir() / "outlook-feeder.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None

def _default_mail_watch(settings_store, inbox_store, mail_store) -> MailWatch | None:
    """The real mail watcher: settings decide the folder and the user's
    own address on every poll, so either saved in the app applies
    without a restart. The Outlook alert feeder rides the same watcher
    and exists only when its own toggle is on; its last persisted status
    seeds the card so a restart does not read as Not run yet."""
    try:
        feeder = (
            _default_outlook_feeder(settings_store)
            if bool(settings_store.get("mail_feeder")) else None
        )
        return MailWatch(
            inbox=inbox_store,
            store=mail_store,
            folder_provider=lambda: settings_store.get("mail_folder"),
            self_address_provider=lambda: settings_store.get("mail_self_address"),
            feeder=feeder.run_once if feeder is not None else None,
            fetch_status=_read_feeder_status(),
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

def _default_gate_runners(settings_store=None) -> GateRunners:
    """The real probe bundle over a workdir beside the other data,
    plus the embeddings gate over the settings-backed client (#95).

    Building the set probes nothing (plain closures over the adapters
    and the settings rows), so carrying it from startup costs nothing
    and page renders stay side-effect free; the gates run only when a
    re-test POST calls one, and the embeddings gate makes exactly one
    request when it does."""
    return default_gate_runners(
        default_data_dir() / "probe-run",
        embeddings=lambda: settings_embedder(settings_store),
    )

def _default_plugins(calendar: CalendarBridge | None = None,
                     mail: MailWatch | None = None,
                     research: ResearchStore | None = None) -> PluginRuntime | None:
    """The plugin runtime over the user data directory, or None when it
    cannot open. Installed plugins, their data and the ${workspace} root
    each get their own folder under the same data dir the stores use, so
    the delete-folder uninstall story stays true. The runner carries the
    shared pipelines so the binding types (calendar-read, mail-digest,
    research-brief) read what the built-in cards read (#64)."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        runner = PluginWidgetRunner(data_dir / "workspace", calendar=calendar,
                                    mail=mail, research=research)
        return PluginRuntime(
            plugins_dir=data_dir / "plugins",
            data_dir=data_dir / "plugin-data",
            workspace_dir=data_dir / "workspace",
            runner=runner,
        )
    except OSError:
        LOG.exception("plugin runtime unavailable")
        return None

def _default_research_store() -> ResearchStore | None:
    """The latest sourced research answer over the persistent store, or
    None when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "research.sqlite3", check_same_thread=False)
        return ResearchStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("research store unavailable")
        return None

def _default_agents_store() -> AgentRunStore | None:
    """The agent runs over the persistent store (they outlive a restart
    by design: the history and its receipts are the record), or None
    when it cannot open."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "agents.sqlite3", check_same_thread=False)
        return AgentRunStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("agents store unavailable")
        return None

def _default_repetition_stores() -> tuple[ActivityLog | None, SkillStore | None]:
    """The activity log and skill store over one file, or Nones.

    Both stores share the connection, so they share its one lock: a
    request-thread skill write and a loop-thread consolidation, refine or
    curator pass serialize instead of interleaving on one implicit
    transaction.
    """
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "repetition.sqlite3", check_same_thread=False)
        # One connection, one lock (the agentdesk.locking rule): both
        # stores sit on this connection, so its lock is the connection's.
        lock = store_lock()
        return (ActivityLog(conn, time.time, lock=lock),
                SkillStore(conn, time.time, lock=lock))
    except (OSError, sqlite3.Error):
        LOG.exception("repetition stores unavailable")
        return None, None


# -- the skills and curator loop steps (spec 016 sections 5.5 and 6.6) -----


def enqueue_skill_feedback(ledger: Ledger, skill_id: int, text: str) -> None:
    """Append one feedback line to a skill's queue latch.

    The latch skillfb:<id> holds a JSON list capped at 5 items of 1000
    characters or fewer: the improve field's posts and the undo-of-a-run
    notice both land here, and the skills loop step drains it one
    endpoint call per skill.
    """
    text = (text or "").strip()[:SKILL_FEEDBACK_MAX_CHARS]
    if not text:
        return
    key = f"skillfb:{skill_id}"
    items: list[str] = []
    raw = ledger.latch_value(key)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                items = [item for item in parsed if isinstance(item, str)]
        except ValueError:
            items = []  # a damaged queue starts over rather than blocks
    items.append(text)
    ledger.latch(key, json.dumps(items[-SKILL_FEEDBACK_MAX_ITEMS:]))


def _record_skill_refined(server, skill: dict, old_prompt: str,
                          note: str) -> object:
    """The ledger entry for one applied refinement, plus its audit row.

    The before capture holds the prompt the refine replaced, which is
    exactly what the skill-version undo restores. A ledger that cannot
    record the change refuses it: the caller compensates.
    """
    before = json.dumps({
        "id": skill["id"], "name": skill["name"],
        "description": skill["description"], "prompt": old_prompt,
        "active": bool(skill["active"]), "created_by": skill.get("created_by", "agent"),
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")
    entry = server.ledger.record(
        actor="agent",
        action="skill.refined",
        subject=f"skill:{skill['id']}",
        why=(f"Improved the skill {skill['name']} from the queued feedback"
             " through the endpoint."),
        undo_kind="skill-version",
        before=before,
        detail={"skill": skill["name"], "note": note[:200]},
    )
    if server.audit_conn is not None:
        audit_store.record(server.audit_conn, "skill.refined",
                           target=skill["name"],
                           detail=f"skill {skill['id']}; ledger {entry.id}")
    return entry


def _drain_skill_feedback(ctx) -> dict:
    """One pass over the feedback queues: one endpoint call per queued
    skill, audited as llm.skill-refine with the request's size, never its
    text (spec 016 sections 6.6 and 6.7).

    A call that fails or cannot be parsed leaves the queue queued for a
    later pass; a definite answer (applied or refused by the store)
    clears it. Identical input is skipped by hash, the loop's own rule.
    """
    server = ctx.server
    skills = getattr(server, "skills", None)
    settings = getattr(server, "settings", None)
    if skills is None or ctx.ledger is None or settings is None:
        return {}
    if not settings.get("skills_auto_refine"):
        return {}
    if not settings.get("endpoint_enabled"):
        return {}  # endpoint off: nothing leaves the machine, queue stays
    llm = settings_chat(settings)
    base, _key, model = effective_llm_config(settings)
    refined = 0
    for skill in skills.agent_skills():
        if skill["pinned"]:
            continue
        key = f"skillfb:{skill['id']}"
        raw = ctx.ledger.latch_value(key)
        feedback: list[str] = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    feedback = [item for item in parsed if isinstance(item, str)]
            except ValueError:
                feedback = []
        if not feedback:
            continue
        payload = {"skill": skill["id"], "prompt": skill["prompt"],
                   "feedback": feedback}
        if ctx.input_unchanged("skills-refine", payload):
            continue
        prompt = skill_refine.build_input(skill, feedback)
        request_bytes = len(prompt.encode("utf-8"))
        try:
            new_prompt = skill_refine.parse_reply(llm(prompt))
        except Exception as exc:  # noqa: BLE001 - a failed call retries later
            _audit_llm_refine(server, base, model, request_bytes, str(exc)[:200])
            continue
        if new_prompt is None:
            _audit_llm_refine(server, base, model, request_bytes,
                              "the endpoint's reply was not strict JSON")
            continue
        old_prompt = skill["prompt"]
        try:
            skills.refine(skill["id"], new_prompt,
                          note=f"feedback: {feedback[0][:160]}")
        except SkillError as exc:
            _audit_llm_refine(server, base, model, request_bytes, str(exc)[:200])
            ctx.ledger.unlatch(key)  # a refusal is a definite answer
            continue
        try:
            _record_skill_refined(server, skill, old_prompt,
                                  note=f"feedback: {feedback[0][:160]}")
        except LedgerError:
            # The change cannot be recorded, so it does not stand: put the
            # earlier prompt back and keep the queue for a retry.
            skills.refine(skill["id"], old_prompt, note="refine undone: no ledger entry")
            LOG.warning("a refinement could not be recorded, so it was not applied")
            continue
        _audit_llm_refine(server, base, model, request_bytes, "")
        ctx.remember_input("skills-refine", payload)
        ctx.ledger.unlatch(key)
        refined += 1
    return {"refined": refined} if refined else {}


def _audit_llm_refine(server, base: str, model: str,
                       request_bytes: int, cause: str) -> None:
    """One llm.skill-refine audit row: the endpoint, the model and the
    request's size, never the prompt or the feedback text."""
    if server.audit_conn is not None:
        audit_store.record(
            server.audit_conn, "llm.skill-refine", target=base,
            status="error" if cause else "ok", model=model,
            request_bytes=request_bytes, detail=cause)


def skills_step_run(ctx) -> dict:
    """The `skills` loop step: consolidate, then drain the feedback queue.

    Consolidate runs every pass exactly as the read path runs it; whether
    it makes a card or a skill directly is the create_directly switch's
    answer at that moment (autonomy and skills_auto_create).
    """
    server = ctx.server
    counts: dict = {}
    consolidator = getattr(server, "consolidator", None)
    if consolidator is not None:
        outcome = consolidator.consolidate()
        if outcome.get("created"):
            counts["created"] = 1
        elif outcome.get("proposed"):
            counts["proposed"] = 1
    counts.update(_drain_skill_feedback(ctx))
    return counts


def curator_step_run(ctx) -> dict:
    """The `curator` loop step: the weekly pass over desk-made skills.

    Gated by the skills_curator switch (read here, per pass) and the
    curator's own interval. Each transition is one undoable ledger entry;
    the run is one skill.curated audit row carrying the counts.
    """
    server = ctx.server
    skills = getattr(server, "skills", None)
    ledger = getattr(server, "ledger", None)
    settings = getattr(server, "settings", None)
    if skills is None or ledger is None or settings is None:
        return {}
    if not skill_curator.due(skills, ctx.now):
        return {}

    def record(before: dict, detail: dict) -> str:
        """One undoable ledger entry per transition (undo_kind skill-state)."""
        entry = ledger.record(
            actor="agent",
            action="skill.curated",
            subject=f"skill:{before['id']}",
            why=(f"Moved the skill {detail.get('skill', '')} to"
                 f" {detail.get('to', '')} (the weekly curator)."),
            undo_kind="skill-state",
            before=json.dumps(before, sort_keys=True).encode("utf-8"),
            detail=detail,
        )
        return entry.id

    try:
        snapshots_dir = getattr(server, "skills_snapshots_dir", None) or (
            default_data_dir() / "skills-snapshots")
        counts = skill_curator.run_curator(
            skills, snapshots_dir, record, ctx.now.timestamp())
    except OSError as exc:
        if server.audit_conn is not None:
            audit_store.record(
                server.audit_conn, "skill.curated", status="error",
                detail=f"the snapshot failed, no skill was changed: {exc}"[:300])
        LOG.exception("the curator run aborted")
        return {"failed": 1}
    if server.audit_conn is not None:
        audit_store.record(
            server.audit_conn, "skill.curated",
            detail=json.dumps(counts, sort_keys=True))
    return counts


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

def _default_peer_store() -> PeerStore | None:
    """The peer store over the persistent store (peers.sqlite3 beside
    the other stores), or None when it cannot open. None means the
    peers page says the surface is unavailable and every peer endpoint
    refuses with a named reason; it never means silent no-auth."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "peers.sqlite3", check_same_thread=False)
        return PeerStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("peer store unavailable")
        return None


def _default_keys_store() -> KeysStore | None:
    """The connections store over its own sqlite file (keys.sqlite3),
    or None when it cannot open. None means the connections routes and
    the settings section say the surface is unavailable; it never means
    a half-working silent mode."""
    try:
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "keys.sqlite3", check_same_thread=False)
        return KeysStore(conn, time.time)
    except (OSError, sqlite3.Error):
        LOG.exception("keys store unavailable")
        return None


# -- the resolution hub (spec 018 #233) ------------------------------------


def _server_resolution(server, job: str) -> Resolution | None:
    """The pure resolver over one server's current rows, or None when the
    job is unbound. Shared by the handler hub and the call sites that
    need the raw parts (web research's provider, the embeddings client);
    the keys store being absent reads as an empty one."""
    connections = server.keys.all() if server.keys is not None else []
    bindings = server.keys.bindings() if server.keys is not None else []
    try:
        return resolve_job(job, connections=connections, bindings=bindings,
                           env=effective_llm_config(server.settings))
    except JobUnbound:
        return None


def _ai_summary(server) -> dict:
    """What Settings says about the AI: whether one answers, and which.

    The same resolution hub every model call uses answers for the assistant
    (spec 022: one truth for "is the AI connected"), with the startup
    client as the last leg exactly as the dashboard's source table reads
    it, so the two can never disagree. On the environment leg there is no
    saved connection to name.
    """
    resolution = _server_resolution(server, "assistant")
    if resolution is None:
        if not getattr(server, "llm_endpoint", None):
            return {"connected": False, "label": "", "model": ""}
        return {"connected": True, "label": "The AI set on this computer", "model": ""}
    connection = resolution.connection
    return {
        "connected": True,
        "label": connection.label if connection is not None else "The AI set on this computer",
        "model": resolution.model,
    }


def _connection_client(server, connection: Connection, api_key: str,
                       model: str):
    """One connection's serving client: its base URL, its key, its gateway
    headers, and last_used_at stamped by the live traffic it serves (the
    one write the call path makes, spec 018's live-traffic leg). The
    stamp is best-effort: a failed bookkeeping write must never fail the
    call it is bookkeeping for."""

    def complete(prompt: str, timeout: float = REQUEST_TIMEOUT_S) -> str:
        """One completion on the connection the hub resolved to."""
        try:
            return chat(connection.base_url, api_key, model, prompt,
                        timeout=timeout,
                        extra_headers=connection.headers or None)
        finally:
            try:
                server.keys.record_use(connection.id)
            except Exception:  # noqa: BLE001 - bookkeeping, never the call
                LOG.debug("could not stamp last_used_at for %s",
                          connection.id, exc_info=True)

    return complete


def _unbound_client(job: str):
    """The client an unbound job answers with: every call raises the
    adapter's own error type carrying the named unbound sentence, so each
    surface degrades in its own words exactly as it does for an
    unconfigured endpoint, and the job is named on the way out."""

    def complete(prompt: str, timeout: float = REQUEST_TIMEOUT_S) -> str:
        """Refuse, naming the job nothing is bound to."""
        raise LlmUnavailable(str(JobUnbound(job)))

    return complete


def _job_llm_parts(server, job: str) -> tuple:
    """(client, serving_name, model) for one job on one server: the whole
    hub in one place, so the request handler and the calendar's audited
    wrapper can never drift apart.

    A resolved connection serves with its own client and answers to its
    label. The environment leg keeps the pre-hub posture exactly: a
    settings-saved endpoint builds a fresh client per call, and with
    nothing saved the startup client (env/config.env, or a test's
    injection) keeps serving. An unbound job raises by name, again unless
    a client was injected: at construction, or later by assignment to
    server.llm (the injection seam several suites and callers use), which
    is why the startup client is remembered and compared by identity.
    """
    resolved = _server_resolution(server, job)
    if resolved is not None and resolved.connection is not None:
        connection = resolved.connection
        api_key = server.keychain.fetch(connection.id) or ""
        return (_connection_client(server, connection, api_key,
                                   resolved.model),
                connection.label, resolved.model)
    if resolved is not None:
        settings = server.settings
        if settings is not None and settings.get("llm_base"):
            return (chat_client(resolved.base_url, resolved.api_key,
                                resolved.model),
                    resolved.base_url, resolved.model)
        return server.llm, server.llm_endpoint, server.llm_model
    injected = (
        not getattr(server, "llm_defaulted_to_env", False)
        or server.llm is not getattr(server, "_startup_llm", None)
    )
    if injected:
        return server.llm, server.llm_endpoint, server.llm_model
    return _unbound_client(job), "", ""


# The connections API's field whitelist (the endpoint-save pattern: an
# unknown field name is a 400 naming the typos and the accepted names,
# never a silent ok with dropped values) and the no-keychain notice.
CONNECTION_CREATE_FIELDS = (
    "label", "provider", "baseUrl", "apiKey", "headers", "isDefault", "model",
)
CONNECTION_UPDATE_FIELDS = CONNECTION_CREATE_FIELDS + ("keyClear",)
# The job-binding write's whitelist, the same pattern one surface over.
BINDING_FIELDS = ("job", "connectionId", "model")
NO_KEYCHAIN_NOTICE = (
    "This machine has no keychain, so a key cannot be stored here. Save the"
    " connection without one (local presets need no key) or resolve keys"
    " through environment variables."
)


def _connection_payload(connection) -> dict:
    """The wire shape of one connection: the masked hint, never the key."""
    return {
        "id": connection.id,
        "label": connection.label,
        "provider": connection.provider,
        "baseUrl": connection.base_url,
        "model": connection.model,
        "maskedKey": connection.masked_key,
        "headers": connection.headers,
        "isDefault": connection.is_default,
        "enabled": connection.enabled,
        "status": connection.status,
        "lastError": connection.last_error,
        "lastCheckedAt": connection.last_checked_at,
        "lastUsedAt": connection.last_used_at,
        "models": connection.models,
        "modelsFetchedAt": connection.models_fetched_at,
        "createdAt": connection.created_at,
        "updatedAt": connection.updated_at,
    }


def _binding_payload(binding: JobBinding) -> dict:
    """The wire shape of one job binding: the job, the connection and the
    model, nothing else."""
    return {
        "job": binding.job_key,
        "connectionId": binding.connection_id,
        "model": binding.model_id,
        "updatedAt": binding.updated_at,
    }


def _apply_health(keys: KeysStore, connection: Connection,
                  result: health.ProbeResult) -> Connection:
    """Stamp one probe's outcome into the row and return it re-read.

    status moves only for the outcomes that know it (ok, ok-with-limit,
    error); transient and no-models keep the stored status, the spec's
    mapping, while the check time and the inline note always refresh. A
    successful listing refreshes the models cache with its fetched-at,
    so the Test button and the refresh route land in the same place.
    """
    status = {"ok": "ok", "limited": "ok", "error": "error"}.get(result.outcome)
    connection = keys.record_check(connection.id, status=status, note=result.cause)
    if result.outcome == health.OUTCOME_OK:
        connection = keys.set_models(connection.id, result.models)
    return connection


def _check_after_save(server, connection: Connection, api_key: str) -> Connection:
    """The free check that rides a save (spec 018 story 3): one
    model-list GET with the just-saved key, its outcome stamped into the
    row and carried by the save response, so a typo'd key is caught on
    the Settings page instead of at the first broken answer.

    Never a chat, and never a refusal: a rejected, unreachable or
    slow check leaves the save standing (the research pattern, a
    discovery failure must not block saving) and the badge tells the
    truth. Callers invoke this only when a key was typed and the preset
    is not a local one, so local presets and empty-key edits check
    nothing at all.
    """
    try:
        result = server.connection_check(
            connection.base_url, api_key, extra_headers=connection.headers)
        return _apply_health(server.keys, connection, result)
    except Exception:  # noqa: BLE001 - the check must never refuse a save
        LOG.warning("the save-time check failed for %s", connection.id,
                    exc_info=True)
        return connection


def _default_connection_label(store, preset) -> str:
    """The name a connection gets when the person typed none (spec 022).

    The form asks for a provider, a key and a model; a name is optional.
    It is the provider's own name, with a number once that name is taken,
    because names are how two keys for one provider are told apart.
    """
    taken = {connection.label for connection in store.all()}
    label = preset.name
    count = 2
    while label in taken:
        label = f"{preset.name} {count}"
        count += 1
    return label


def _connection_input(body: dict, accepted: tuple[str, ...],
                      allow_empty_label: bool = False) -> tuple[dict | None, str | None]:
    """Validate one connection POST body into field values, or name the refusal.

    The provider resolves to its preset object, a typed base URL is checked with
    the adapter's own base_url_problem, and headers arrive as a JSON dict or
    form "Name: Value" lines. baseUrl comes back empty when blank: the create
    path fills the preset default, the update path keeps the stored value. The
    model comes back trimmed, or None when the request does not mention it.
    A name is required on an update (the row already has one) and optional
    on a create, where an empty one is filled from the provider.
    """
    unknown = sorted(name for name in body if name not in accepted)
    if unknown:
        return None, ("unknown connection field(s): " + ", ".join(unknown)
                      + "; accepted fields are " + ", ".join(accepted))
    label = str(body.get("label", "") or "").strip()
    if not label and not allow_empty_label:
        return None, "a name is required"
    preset = preset_for(str(body.get("provider", "") or "").strip())
    if preset is None:
        return None, ("unknown provider preset: " + str(body.get("provider", ""))
                      + "; presets are " + ", ".join(p.id for p in PRESETS))
    base = str(body.get("baseUrl", "") or "").strip()
    if base:
        problem = base_url_problem(base)
        if problem:
            return None, problem
    headers, problem = _headers_from_input(body.get("headers"))
    if problem:
        return None, problem
    return {
        "label": label,
        "provider": preset,
        "baseUrl": base,
        "apiKey": str(body.get("apiKey", "") or "").strip(),
        "headers": headers,
        "isDefault": _flag(body, "isDefault"),
        # None when the request does not mention the model at all, which
        # the update path reads as "leave it" (the create path fills it).
        "model": (str(body["model"] or "").strip() if "model" in body else None),
    }, None


def _headers_from_input(value) -> tuple[dict | None, str | None]:
    """Extra headers from a JSON dict or one 'Name: Value' per form line."""
    if value is None or value == "":
        return {}, None
    if isinstance(value, dict):
        if any(not isinstance(name, str) or not isinstance(content, str) or not name.strip()
               for name, content in value.items()):
            return None, "headers must map each name to a text value"
        return {name.strip(): content.strip() for name, content in value.items()}, None
    if isinstance(value, str):
        headers: dict[str, str] = {}
        for line in value.splitlines():
            line = line.strip()
            if not line:
                continue
            name, sep, content = line.partition(":")
            if not sep or not name.strip() or not content.strip():
                return None, "each header line must be 'Name: Value'"
            headers[name.strip()] = content.strip()
        return headers, None
    return None, "headers must be name: value lines"


def default_calendar_hint(explicit: str | None = None) -> Path | None:
    """The calendar path the walkthrough shows as 'the app watches this'.

    An explicitly chosen path is shown as is: that is the file the reader
    uses. Otherwise the reader accepts several shapes (plain OneDrive, the
    'OneDrive - Company' glob, macOS CloudStorage); the hint shows the
    first one that exists on this machine, falling back to the first
    default, so it never names a path the reader would ignore.

    An empty AGENTDESK_CALENDAR_FILE pins the reader to no calendar and
    leaves no candidates at all. There is then no path to name, so the
    hint returns None and the walkthrough says calendar reading is off.
    """
    if explicit:
        return Path(explicit)
    candidates = default_calendar_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    if candidates:
        return candidates[0]
    return None

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
    """Both watches poll once, right now, on daemon threads, and the
    supervised agent loop opens its thread.

    The recurring loops keep their own schedules (calendar every half
    hour, excel hourly); this only removes the empty first half hour on
    the commitments card and brings the registered workbook back after a
    restart. A source turned off in settings is not touched at all. The
    agent loop thread always opens; at agent_loop_minutes 0 its startup
    check and its ticks simply do nothing.
    """

    def allowed(key: str) -> bool:
        """Whether a settings-keyed poll may run, a missing store counting as on.

        Read at each poll rather than captured once, so a switch flipped in the page
        takes effect without a restart.
        """
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
        start_plugin_refresh_tick(server)
    loop = getattr(server, "agent_loop", None)
    if loop is not None:
        loop.start()


def start_plugin_refresh_tick(server: AgentDeskServer,
                              interval_s: float = 60.0) -> threading.Thread | None:
    """Start the minute tick that refreshes scheduled and file-change tiles.

    One daemon thread for the process, started beside the other background
    polls. It never blocks a request: each wake asks the runner which tiles
    are due and returns. The thread is named so a shutdown or a test can see
    it, and a missing plugin runtime simply means no threads.
    """
    if getattr(server, "plugins", None) is None:
        return None

    def run() -> None:
        """Wake once a minute and refresh what the modes say is due."""
        while True:
            time.sleep(interval_s)
            _tick_plugin_refresh(server)

    thread = threading.Thread(target=run, name="plugin-refresh-tick", daemon=True)
    thread.start()
    server.plugin_refresh_tick = thread
    return thread

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


def _recommend_enabled(settings) -> bool:
    """The recommendation step runs only with the recommendations switch on."""
    return settings is not None and bool(settings.get("recommendations"))


def _run_recommend(ctx) -> dict:
    """Add or withdraw recommendation cards from the facts already saved."""
    recommender = getattr(ctx.server, "recommender", None)
    if recommender is None:
        return {"added": 0, "withdrawn": 0}
    return recommender.refresh()


# Tickets 05 and 06 register their steps with the orders spec 016 section
# 6.2 gives: a pass heals, recommends, then ranks. The declared order, not
# this file's position, decides when each runs.
register_step(Step(name="recommend", order=STEP_ORDER_RECOMMEND,
                   enabled=_recommend_enabled, run=_run_recommend))
register_step(Step(name="rank", order=STEP_ORDER_RANK,
                   enabled=rank_enabled, run=rank_step))

# Ticket 08's learned topics and ticket 09's profile review follow, then
# ticket 10's skills and curator steps. The bodies of the last two stay in
# agentloop/loop.py beside the desk check's until a later wave moves the
# step bodies together.
register_step(Step(name="learn-topics", order=STEP_ORDER_LEARN_TOPICS,
                   enabled=_learn_topics_enabled, run=_run_learn_topics))
register_step(Step(name="profile-review", order=STEP_ORDER_PROFILE_REVIEW,
                   enabled=_profile_review_enabled, run=_run_profile_review))
register_step(Step(name="skills", order=STEP_ORDER_SKILLS,
                   enabled=_skills_enabled, run=_run_skills))
register_step(Step(name="curator", order=STEP_ORDER_CURATOR,
                   enabled=_curator_enabled, run=_run_curator))


def _update_enabled(settings) -> bool:
    """The update step checks whenever a share is set, even with installs off."""
    if settings is None:
        return False
    channel = settings.get("update_channel")
    return bool(channel.strip()) if isinstance(channel, str) else False


def _run_update_step(ctx) -> dict:
    """One update check; it stages only when Install updates is on."""
    from agentdesk.update import run_update

    return run_update(ctx.server)


# Ticket 11 registers the update step with the last order: a pass heals,
# ranks, and then reads the share, which is the only step that can replace
# the program.
register_step(Step(name="update", order=STEP_ORDER_UPDATE,
                   enabled=_update_enabled, run=_run_update_step))


# -- the engine step (spec 023, ticket 023-3) -------------------------------
#
# The engine's own turn, appended last so a pass heals, recommends,
# ranks and updates before the engine acts on what all of that found.
# The step is enabled only when the side-car is installed: without it
# the pass is exactly today's, which is what makes the fallback the
# proof of the boundary rather than a second behaviour.

ENGINE_LOOPBACK_TIMEOUT_S = 30

# The context block's ceiling: the prompt rides argv (the CLI has no
# stdin prompt mode), so the desk's names payload is cut with a visible
# marker rather than allowed to grow without bound.
ENGINE_CONTEXT_MAX_CHARS = 12000
ENGINE_CONTEXT_CUT_MARKER = " [the context was cut at this length]"


def _engine_enabled(settings) -> bool:
    """The engine step always runs; the side-car's absence is its own answer.

    A present side-car acts; an absent one returns the honest fallback
    note and executes nothing, because the pass's fixed steps are the
    fallback. Keeping the row in every pass is what lets R29 say which
    of the two happened instead of counting a seed's own entry.
    """
    return True


def _run_engine(ctx) -> dict:
    """One engine turn for this pass: the boundary decides, the desk executes."""
    return engine_step_run(ctx)


register_step(Step(name="engine", order=STEP_ORDER_ENGINE,
                   enabled=_engine_enabled, run=_run_engine))


def _server_resolution_or_none(server, job: str):
    """The hub's resolution for one job, or None when it cannot be asked."""
    try:
        return _server_resolution(server, job)
    except Exception:  # noqa: BLE001 - an unbound job is a no-turn, not a crash
        return None


def _engine_connection(server) -> ConnectionSpec | None:
    """The saved connection a side-car turn runs against, via the hub.

    The same resolution the assistant's calls take (the job's binding,
    then the default, then the single serving connection, then the
    environment). The key comes from the keychain for a saved
    connection and stays only for this one call. A desk with no usable
    endpoint, or one whose connection serves without a key, answers
    None: the side-car grammar needs all three parts, and the fallback
    covers the desk instead.
    """
    resolved = _server_resolution_or_none(server, DEFAULT_JOB)
    if resolved is None or not resolved.base_url or not resolved.model:
        return None
    if resolved.connection is not None:
        api_key = server.keychain.fetch(resolved.connection.id) or ""
    else:
        api_key = resolved.api_key
    if not api_key:
        return None
    return ConnectionSpec(base_url=resolved.base_url, api_key=api_key,
                          model=resolved.model)


def engine_names_payload(server) -> dict:
    """The dashboard's names, read once for the engine: what the desk holds.

    Memory's org and person entities with their names and counts, the
    agenda's next meeting, and the watched workbook's rows summary. A
    locked bank, a missing store or an unreadable watch contributes its
    empty state, so the engine reads the desk as it is and invents
    nothing.
    """
    names: list[dict] = []
    memory = getattr(server, "memory", None)
    if memory is not None:
        try:
            for summary in memory.entities():
                if summary.type not in ("org", "person"):
                    continue
                names.append({
                    "name": summary.canonical_name,
                    "type": summary.type,
                    "facts": summary.fact_count,
                    "aliases": list(summary.aliases or ()),
                })
        except Exception:  # noqa: BLE001 - a locked bank reads as no names
            LOG.info("engine names: the memory bank could not be read", exc_info=True)
    agenda = None
    calendar = getattr(server, "calendar", None)
    if calendar is not None:
        try:
            view = calendar.day_view()
            upcoming = [row for row in (view.get("upcoming") or [])
                        if isinstance(row, dict)]
            if upcoming:
                agenda = {"title": str(upcoming[0].get("title") or "Busy"),
                          "time": str(upcoming[0].get("time") or "")}
        except Exception:  # noqa: BLE001 - an unreadable calendar reads as none
            LOG.info("engine names: the calendar could not be read", exc_info=True)
    workbook = None
    excel = getattr(server, "excel", None)
    if excel is not None:
        try:
            status = excel.status() or {}
            if status.get("configured"):
                workbook = {
                    "workbook": Path(str(status.get("path") or "")).name,
                    "rowsSeen": status.get("rowsSeen"),
                    "grid": status.get("grid") or {"columns": [], "rows": []},
                }
        except Exception:  # noqa: BLE001 - an unreadable watch reads as none
            LOG.info("engine names: the workbook watch could not be read", exc_info=True)
    return {"memory": names, "agenda": agenda, "workbook": workbook}


def engine_context_text(server) -> str:
    """The engine turn's context block: the names payload as compact JSON.

    Bounded before it can reach argv: a desk holding thousands of names
    must not build a command line near the OS limit. The cut is marked
    so the engine knows the context is partial rather than empty.
    """
    text = json.dumps(engine_names_payload(server), ensure_ascii=False)
    if len(text) > ENGINE_CONTEXT_MAX_CHARS:
        keep = ENGINE_CONTEXT_MAX_CHARS - len(ENGINE_CONTEXT_CUT_MARKER)
        return text[:keep] + ENGINE_CONTEXT_CUT_MARKER
    return text


def _engine_tools_post(server, payload: dict) -> tuple[int, dict]:
    """POST one tool call to this desk's own tools route over loopback.

    The boot-minted token rides the Authorization header; the proxy
    rules are emptied so the call can never leave the machine. The
    answer is the status and the parsed body (an empty dict when the
    body is not JSON).
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/api/engine/tools", data=data,
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {server.engine_token}",
                 "Host": f"127.0.0.1:{server.port}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=ENGINE_LOOPBACK_TIMEOUT_S) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = {}
    return status, body if isinstance(body, dict) else {}


def execute_engine_actions(server, actions) -> tuple[int, int]:
    """Run the turn's actions through the tools route; count acted and refused.

    Every action, reads included, goes over the loopback route, so the
    route is the one path the engine's hands take and its audit trail
    records each call. The turn's cap is applied here again: calls past
    it are refused, never executed. A call whose transport fails (a
    timeout, a closed connection, a malformed HTTP answer) is counted as
    refused and the next action still runs, so one dead socket cannot
    end the rest of the turn. A refused call names its reason in the
    server log; nothing is ever executed around the route.
    """
    acted = refused = 0
    for index, action in enumerate(actions):
        if index >= MAX_ACTIONS_PER_TURN:
            refused += 1
            LOG.warning("engine tool call %s refused: past the turn's limit of %s",
                        action.tool, MAX_ACTIONS_PER_TURN)
            continue
        try:
            status, body = _engine_tools_post(server, {
                "tool": action.tool, "args": dict(action.args), "why": action.why,
            })
        except (urllib.error.URLError, socket.timeout, TimeoutError,
                http.client.HTTPException, OSError) as exc:
            refused += 1
            LOG.warning("engine tool call %s could not reach the desk: %s",
                        action.tool, exc)
            continue
        if 200 <= status < 300:
            acted += 1
        else:
            refused += 1
            LOG.warning("engine tool call %s refused (%s): %s",
                        action.tool, status, body.get("error") or "")
    return acted, refused


def engine_step_run(ctx) -> dict:
    """One engine turn for a pass: run it through the boundary, act on it.

    An injected runner (the tests' fake) takes the turn; otherwise the
    boundary runs the side-car when it is installed. The fixed loop is
    never run from inside a pass: its own guard refuses that, and
    re-posting its ledger entries would execute the pass twice. When the
    side-car is absent the step says so and executes nothing, because
    the fixed steps in this same pass are the fallback. The answer
    carries the backend, the counts, the note and the turn's verdict;
    the loop records a failed row when the verdict is False, and the
    audit row is written in a finally so a transport failure still
    leaves a trace.
    """
    server = ctx.server
    runner = getattr(server, "engine", None)
    if runner is None and not engine_available():
        return {"backend": "fallback", "ok": True, "actions": 0, "acted": 0,
                "refused": 0,
                "note": ("The side-car is not installed; the pass's fixed "
                         "steps are the fallback.")}
    connection = _engine_connection(server)
    context_text = engine_context_text(server)
    if runner is not None:
        try:
            result = runner.run_turn(context_text, connection=connection)
        except Exception:  # noqa: BLE001 - an injected runner never stops the pass
            LOG.exception("the engine runner could not run its turn")
            result = TurnResult(
                backend="sidecar", ok=False,
                note="The engine turn could not run, so the pass did not act.")
    else:
        result = engine_run_turn(context_text, connection=connection, loop=None)
    key = getattr(connection, "api_key", "") or ""
    note = engine_redact(result.note, key)
    boundary_refusals = len(result.refusals)
    acted = refused = 0
    try:
        acted, refused = execute_engine_actions(server, result.actions)
    finally:
        refused += boundary_refusals
        audit_conn = getattr(server, "audit_conn", None)
        if audit_conn is not None:
            audit_store.record(
                audit_conn, "engine.pass", target=result.backend,
                status="ok" if result.ok else "error",
                detail=(f"{len(result.actions)} action(s), {acted} acted, "
                        f"{refused} refused"
                        + (f"; {note}" if note else "")))
    return {"backend": result.backend, "actions": len(result.actions),
            "acted": acted, "refused": refused, "note": note, "ok": result.ok}
