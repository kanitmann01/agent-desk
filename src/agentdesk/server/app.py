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
import zipfile
from dataclasses import replace
from io import BytesIO
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

import agentdesk
from agentdesk.agents.registry import ROSTER, find_agent
from agentdesk.agents.runner import (
    BRIEF_MAX_CHARS,
    FEEDBACK_MAX_CHARS,
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
from agentdesk.probe.core import PASS as GATE_PASS
from agentdesk.consents import ConsentStore
from agentdesk.excel.watcher import ExcelWatch, default_adapters
from agentdesk.inbox import service as inbox_service
from agentdesk.inbox.core import (
    KIND_MAIL_FOLLOW_UP,
    KIND_MEMORY_DRAFT,
    KIND_MEMORY_REFLECTION,
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
from agentdesk.layout import (
    BUILTIN_KEYS as BUILTIN_LAYOUT_KEYS,
    LayoutError,
    LayoutStore,
    parse_layout,
    resolved_layout,
)
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
    base_url_problem,
    chat,
    chat_client,
    effective_llm_config,
    env_chat,
    env_config,
    settings_chat,
)
from agentdesk.memory.core import UnknownEntity, UnknownFact, normalize_fact_text
from agentdesk.memory.crypto import MemoryEncryptedError
from agentdesk.memory.embed import (
    EmbedderUnavailable,
    EndpointEmbedder,
    effective_embeddings_model,
    settings_embedder,
)
from agentdesk.memory.extract import (
    EndpointExtractor,
    ExtractionFailed,
    ExtractorUnavailable,
    FACT_KINDS,
    facts_to_retain,
    occurrence_from_source,
)
from agentdesk.memory.reflect import (
    EndpointReflector,
    ReflectEmpty,
    ReflectFailed,
    ReflectorUnavailable,
    accept_observations,
    gather_facts,
    parse_scope_date,
    scope_key,
)
from agentdesk.memory.service import build_facts_block
from agentdesk.memory.store import MemoryStore, key_file_path, read_key_file
from agentdesk.memory import loop as memory_loop
from agentdesk.server.memory_loop_api import build_loop_state
from agentdesk.plugins.config import MAX_UPLOAD_BYTES
from agentdesk.plugins.execute import PluginWidgetRunner
from agentdesk.plugins.html import element_html
from agentdesk.plugins.runtime import PluginError, PluginRuntime
from agentdesk.registry import source as registry_source
from agentdesk.registry.index import RegistryIndexError
from agentdesk.registry.install import RegistryError
from agentdesk.registry.publish import publish_to_registry
from agentdesk.peers.client import PeerClient, PeerClientError, extract_bundle
from agentdesk.peers.discovery import (
    PREFERRED_ANNOUNCE_PORT,
    DiscoveryService,
)
from agentdesk.peers.store import PeerError, PeerStore, derive_token
from agentdesk.registry.install import RegistryError, tree_digest
from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.service import Consolidator
from agentdesk.repetition.skills import SkillError, SkillStore
from agentdesk.server.audit_view import render_audit_page
from agentdesk.server.activity_view import DECISIONS
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
from agentdesk.server.graph_view import parse_graph_query, render_graph_page
from agentdesk.server.inbox_view import render_inbox_page
from agentdesk.server.mail_view import render_mail_page
from agentdesk.server.memory_graph_api import build_memory_graph
from agentdesk.server.memory_view import EDIT_MERGE_NOTICE, render_memory_page
from agentdesk.server.plugins_view import render_plugins_page
from agentdesk.server.peers_view import render_peers_page
from agentdesk.server.research import (
    RETAIN_EXCERPT_MAX_CHARS,
    render_assistant_page,
    render_research_disabled,
    render_research_widget,
)
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
    STATUS_CONNECTED,
    STATUS_NOT_CONNECTED,
    Freshness,
    SourceStatus,
)
from agentdesk.server.demo import Widget
from agentdesk.server import demo_data
from agentdesk.server.guard import GuardVerdict, check_peer_request, check_request
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
SPA_DIR = Path(__file__).resolve().parent / "static" / "spa"

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


def memory_graph_island_built() -> bool:
    """True when the committed SPA build carries the memory graph island
    (a source checkout without a build keeps the static graph link)."""
    return (SPA_DIR / "assets" / "memory-graph.js").is_file()


def memory_loop_island_built() -> bool:
    """True when the committed SPA build carries the Memory page island
    (capture, review, knowledge, removal); without it /memory stays the
    server-rendered page."""
    return (SPA_DIR / "assets" / "memory-loop.js").is_file()


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


def _scope_text(value) -> str:
    """An optional reflect scope field (ticket #93): anything that is
    not a string, or is blank once trimmed, reads as absent."""
    if not isinstance(value, str):
        return ""
    return value.strip()


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


def _memory_entity_id(value) -> int | None:
    """A body's entity id, or None when it is not one (ticket #92's
    merge form posts ids)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


class _AuditedEmbedder:
    """The audit wrapper around the embeddings client (ticket #95): one
    ``llm.embeddings`` row per endpoint call, the same fields the
    assistant loop writes for every outbound model call (endpoint,
    model, input size, status), never the text itself. The store calls
    this object exactly like the raw client; injecting a raw client (a
    test does) stays silent by design, the caller's audit, not the
    port's."""

    def __init__(self, inner, base_url: str, audit_conn) -> None:
        """Wrap the client, naming the endpoint its audit rows will carry and the
        connection to write them to.

        An audit_conn of None turns the audit off for this instance and leaves the
        embedding path untouched.
        """
        self._inner = inner
        self._base_url = base_url
        self._audit_conn = audit_conn

    @property
    def model(self) -> str:
        """The wrapped client's model name, passed straight through.

        It is copied onto every audit row, so the log names the model that answered.
        """
        return self._inner.model

    @property
    def last_request_bytes(self) -> int:
        """The byte count of the wrapped client's last call, or 0 when it reports none.

        Read with getattr because the port does not require the attribute.
        """
        return int(getattr(self._inner, "last_request_bytes", 0) or 0)

    def embed(self, text: str):
        """Embed one text, auditing the attempt even when it fails.

        Success writes one row; either failure writes a row with the exception type or
        message cut to 200 characters and then re-raises, so every endpoint call leaves
        exactly one llm.embeddings row.
        """
        request_bytes = len(text.encode("utf-8"))
        try:
            vector = self._inner.embed(text)
        except EmbedderUnavailable as exc:
            self._record("error", request_bytes, str(exc)[:200])
            raise
        except Exception as exc:  # noqa: BLE001 - classified, then raised
            self._record("error", request_bytes, f"{type(exc).__name__}: {exc}"[:200])
            raise
        self._record("ok", request_bytes)
        return vector

    def _record(self, status: str, request_bytes: int, detail: str = "") -> None:
        """Write one llm.embeddings row, or nothing when no audit connection was injected.

        Only sizes and status are recorded; the text being embedded never reaches the
        log.
        """
        if self._audit_conn is None:
            return
        audit_store.record(
            self._audit_conn,
            "llm.embeddings",
            target=self._base_url,
            status=status,
            model=self.model,
            request_bytes=request_bytes,
            detail=detail,
        )


_PEER_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _peer_plugin_path(path: str) -> tuple[str | None, str]:
    """'/peer/plugins/<id>/<tail>' as (plugin_id, tail), with the id
    checked against the safe-name rule before it ever names a file; a
    path that is not that shape answers (None, '')."""
    prefix = "/peer/plugins/"
    if not path.startswith(prefix):
        return None, ""
    remainder = path[len(prefix):]
    plugin_id, sep, tail = remainder.partition("/")
    if not sep or not plugin_id or not _PEER_SAFE_NAME.match(plugin_id):
        return None, ""
    return plugin_id, tail


def _active_version_dir(record: dict) -> Path:
    """The directory of the version the user actually runs (the same
    rule the runtime applies: after rollback that is not the newest)."""
    active = record.get("active_version")
    for version in record.get("versions", []):
        if version["version"] == active:
            return Path(version["dir"])
    return Path(record["versions"][-1]["dir"])


def _alias_instance_id(name: str) -> str:
    """The instance id an alias's named instance resolves to. Mirrors the
    runtime's derivation, so the manage view lists exactly the instance
    the install materialized."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip().lower()).strip("-")
    return cleaned or "instance"


def _normalize_peer_address(address: str) -> str | None:
    """host:port with an optional http:// scheme stripped; None when the
    shape is wrong (a hostname without a port is refused: the peer
    surface always names its port)."""
    text = address.strip()
    for scheme in ("http://", "https://"):
        if text.startswith(scheme):
            text = text[len(scheme):]
    text = text.rstrip("/")
    host, sep, port_text = text.partition(":")
    if not sep or not host or not port_text.isascii() or not port_text.isdigit():
        return None
    port = int(port_text)
    if not (0 < port < 65536):
        return None
    return f"{host}:{port}"


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
        extractor=None,
        reflector=None,
        announce_port: int | None = None,
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
        self.announce_port = announce_port
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
        self.consolidator = (
            Consolidator(activity_log, inbox_store, skill_store, activity_log.clock)
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
        discovery = getattr(self, "peer_discovery", None)
        if discovery is not None:
            discovery.stop()
        super().server_close()


def live_sources(server: AgentDeskServer) -> list[SourceStatus]:
    """The source table computed at request time, from the real watches.

    Health must not repeat what a constructor once guessed: excel is
    connected when a workbook is registered, calendar when the bridge has
    produced a non-empty state, endpoint when the corporate base URL is
    set. Both /health and the dashboard's source line read this table.
    """

    def state(connected: bool) -> str:
        """The status word for one source, connected or not.

        Both /health and the dashboard read the same words from this function.
        """
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


def _detached_handler(server: "AgentDeskServer") -> "DashboardHandler":
    """A handler with no request, for work that starts outside one (the
    workbook watch's poll thread). Only the helpers that read
    `self.server` may be called on it: the memory capture path."""
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.server = server
    return handler


def _workbook_changed(server: "AgentDeskServer", workbook: str, header: list, delta) -> None:
    """The memory loop's workbook channel: rows that changed since the
    watch's 24-hour reference become facts written from the cells, staged
    for review (or saved, in automatic mode) like any captured fact.
    Already stored, waiting or rejected facts are not proposed again."""
    if server.memory is None or server.settings is None:
        return
    if not bool(server.settings.get("excel_enabled")):
        return
    candidates = memory_loop.workbook_candidates(header, delta.added, delta.removed)
    if not candidates:
        return
    _detached_handler(server)._capture_memory(
        "workbook", memory_loop.workbook_excerpt(workbook, candidates), "",
        candidates=candidates,
    )


class DashboardHandler(BaseHTTPRequestHandler):
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
                "Open Nexuus Bot from its shortcut to get a fresh link.",
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
        """Serve the walkthrough page, hinting the calendar it should open."""
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
        """
        self._send_redirect_302("/marketplace/installed")

    def _send_peers_page_request(self) -> None:
        """Serve the peers page, carrying its optional notice query field."""
        _, _sep, query = self.path.partition("?")
        notice = parse_qs(query).get("notice", [""])[0] if query else ""
        self._send_peers_page(notice=notice)

    def _send_skill_markdown_rest(self, rest: str) -> None:
        """Serve the generated markdown for the skill id in the path.

        The table hands over the text between /skills/ and /skill.md; a non-numeric id
        raises the ValueError the page always answered with.
        """
        self._send_skill_markdown(int(rest.strip("/")))

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
        """Serve the dashboard payload as JSON."""
        self._send_json(200, dashboard_payload(self.server))

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
        paths still answer 404 elsewhere and never the shell.
        """
        path, _, _query = self.path.partition("?")
        self._send_marketplace_shell(200 if _known_marketplace_path(path) else 404)

    def _preferences_write(self) -> None:
        """Store the posted insight preferences, reporting a rejection as JSON."""
        try:
            self._send_json(200, PreferenceStore(default_data_dir()).write(self._read_json_body()))
        except PreferencesError as exc:
            self._send_json(exc.status, {"error": exc.message, "code": exc.code})

    def _insight_draft(self) -> None:
        """Draft the press reply for the posted insight body."""
        try:
            answer = draft_reply(
                self.server,
                self._read_json_body(),
                preferences=PreferenceStore(default_data_dir()).read(),
                complete=self._insight_complete(),
            )
        except InsightError as exc:
            self._send_json(exc.status, {"error": exc.message, "code": exc.code})
            return
        self._send_json(200, answer)

    def _excel_watch_pick(self) -> None:
        """Open the workbook picker and return the chosen path."""
        excel = self.server.excel  # type: ignore[attr-defined]
        if excel is None:
            self._send_json(503, {"error": "the excel watch is not available"})
            return
        self._send_json(200, {"path": self.server.pick_workbook()})  # type: ignore[attr-defined]

    def _excel_watch_register(self) -> None:
        """Validate and register the workbook path the card submitted."""
        excel = self.server.excel  # type: ignore[attr-defined]
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

    def _excel_watch_retest(self) -> None:
        """Re-test the registered workbook and return the watch status."""
        excel = self.server.excel  # type: ignore[attr-defined]
        if excel is None:
            self._send_json(503, {"error": "the excel watch is not available"})
            return
        excel.retest()
        self._send_json(200, excel.status())

    def _commitment_check(self) -> None:
        """Toggle one commitment checkbox on the calendar bridge."""
        calendar = self.server.calendar  # type: ignore[attr-defined]
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

    def _calendar_bridge_retest(self) -> None:
        """Re-test the calendar bridge and return its status."""
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if calendar is None:
            self._send_json(503, {"error": "the calendar bridge is not available"})
            return
        calendar.retest()
        self._maybe_briefs()
        self._send_json(200, calendar.status())

    def _calendar_bridge_pick(self) -> None:
        """Open the calendar picker and return the chosen path."""
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if calendar is None:
            self._send_json(503, {"error": "the calendar bridge is not available"})
            return
        self._send_json(200, {"path": self.server.pick_calendar()})  # type: ignore[attr-defined]

    def _calendar_bridge_path(self) -> None:
        """Store the explicit calendar path the card submitted, then re-poll."""
        calendar = self.server.calendar  # type: ignore[attr-defined]
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

    def _calendar_bridge_upload(self) -> None:
        """Store the uploaded calendar document and point the bridge at it."""
        calendar = self.server.calendar  # type: ignore[attr-defined]
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

    def _calendar_bridge_reset(self) -> None:
        """Clear the explicit calendar path, re-poll and return the status."""
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if calendar is None:
            self._send_json(503, {"error": "the calendar bridge is not available"})
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
        if self.server.consolidator is None:  # type: ignore[attr-defined]
            self._send_json(503, {"error": "the repetition detector is not available"})
            return
        self._send_json(200, self.server.consolidator.consolidate())  # type: ignore[attr-defined]

    def _skill_run_rest(self, rest: str) -> None:
        """Run the repetition skill whose id the path names."""
        self._skill_run(int(rest.strip("/")))

    def _skill_undo_rest(self, rest: str) -> None:
        """Undo the last run of the repetition skill whose id the path names."""
        self._skill_undo(int(rest.strip("/")))

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
            self.send_response(303)
            self.send_header("Location", "/assistant")
            self._common_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send_json(200, answer.to_json())

    def _is_form_submit(self) -> bool:
        """Whether this POST came from a plain HTML form rather than fetch.

        The test is the urlencoded media type appearing in Content-Type; the branches
        that choose between a redirect and JSON consult it.
        """
        return "application/x-www-form-urlencoded" in (self.headers.get("Content-Type") or "")

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
        llm, endpoint, model = self._effective_llm()
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
            return answer
        return assistant_reply(question, context, **common)

    def _facts_block(self, question: str) -> str:
        """The bounded recalled-facts block for the assistant prompt,
        ranked against the user's question. Recall only: this path never
        creates a fact; the bounds live in memory/service. A locked
        memory store (ticket #94) contributes no block: the assistant
        keeps answering, the bank is never read in plaintext. The
        semantic half is derived per turn like every memory action (the
        review's finding 5): the assistant's recall gains the vector
        leg on the same terms as the memory page's, not only after some
        memory route happens to run first."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return ""
        self._configure_memory_embeddings()
        try:
            return build_facts_block(memory.recall(question))
        except MemoryEncryptedError:
            return ""

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
        page = pages.render_dashboard(
            widgets,
            state.version,
            _greeting(now),
            now.strftime("%A, %d %B, %H:%M. "),
            inbox_count=state.inbox_waiting,
            skills=list(state.skills),
            connected_sources=state.sources_connected,
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_sales_status(self) -> None:
        """The sales widget's status as JSON, straight from the Excel watcher.

        503 when no watcher exists: the widget's shape belongs to the watcher, and
        inventing an empty one here would look like a connected source with no data.
        """
        excel = self.server.excel  # type: ignore[attr-defined]
        if excel is None:
            self._send_json(503, {"error": "the excel watch is not available"})
            return
        self._send_json(200, excel.status())

    def _send_commitments_status(self) -> None:
        """The commitments widget's status as JSON, from the calendar bridge.

        503 when no bridge exists, since an unbuilt collaborator is not the same thing
        as a source that happens to be empty.
        """
        calendar = self.server.calendar  # type: ignore[attr-defined]
        if calendar is None:
            self._send_json(503, {"error": "the calendar bridge is not available"})
            return
        self._send_json(200, calendar.status())

    def _send_assistant_page(self) -> None:
        """Render the assistant page from the stored conversation.

        The audit store holds every kind of action, so the turns come from the thread
        log's own reader rather than from the raw table; without a store the page opens
        empty instead of failing.
        """
        turns = []
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            turns = threadlog.turns(self.server.audit_conn)  # type: ignore[attr-defined]
        page = render_assistant_page(turns, agentdesk.__version__,
                                     inbox_count=self._inbox_waiting_count())
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _send_agents_page(self) -> None:
        """Render the agents page: the roster with a run form per agent,
        and the run history with each run's receipt.

        The history reads the store's newest-first rows; a store that
        could not open renders the roster with the honest absent-history
        note rather than an empty history that would claim no run ever
        happened.
        """
        server = self.server  # type: ignore[attr-defined]
        runs = (
            server.agents.recent() if server.agents is not None else []
        )
        page = render_agents_page(
            ROSTER, runs, agentdesk.__version__,
            inbox_count=self._inbox_waiting_count(),
            history_available=server.agents is not None,
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
        brief = body.get("brief") if body is not None else None
        kind = find_agent(agent_id) if isinstance(agent_id, str) else None
        if kind is None:
            self._send_json(
                400,
                {"error": "unknown agent id; the /agents page lists the agents"
                          " this desk can run"},
            )
            return
        if not isinstance(brief, str) or not brief.strip():
            self._send_json(
                400,
                {"error": "expected {\"agent\": \"presentation\","
                          " \"brief\": \"a short task brief\"}"},
            )
            return
        brief = brief.strip()
        if len(brief) > BRIEF_MAX_CHARS:
            self._send_json(
                400,
                {"error": f"the brief is longer than {BRIEF_MAX_CHARS}"
                          " characters; shorten it"},
            )
            return
        if server.agents is None:
            self._send_json(503, {"error": "the agents store is not available"})
            return
        if not self._source_allowed("endpoint_enabled"):
            result = endpoint_off_run()
        else:
            result = run_agent(
                kind, brief, self._effective_llm()[0],
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
        if self._is_form_submit():
            self.send_response(303)
            self.send_header("Location", "/agents")
            self._common_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send_json(200, {
                "id": run_id,
                "agent": kind.id,
                "status": result.status,
                "cause": result.cause,
                "reply": result.reply,
                "artifact": result.artifact,
                "facts": result.facts,
            })

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
        if server.agents is None:
            self._send_json(503, {"error": "the agents store is not available"})
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
        if self._is_form_submit():
            self.send_response(303)
            self.send_header("Location", "/agents")
            self._common_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            stored = server.agents.get(run_id)
            self._send_json(200, {
                "id": run_id,
                "agent": run.get("agentId", ""),
                "feedback": feedback,
                "feedbackTs": stored["feedbackTs"] if stored else None,
            })

    def _agent_fact_ranks(self, kind, brief: str) -> list:
        """The ranked recall for one agent run: the agent's name joined
        to the brief is the query, the same hybrid recall and embedding
        derivation the assistant's turns use. A locked memory store
        contributes nothing: the run keeps going, the bank is never read
        in plaintext."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            return []
        self._configure_memory_embeddings()
        try:
            return memory.recall(f"{kind.name} {brief}")
        except MemoryEncryptedError:
            return []

    def _send_audit_tail(self) -> None:
        """The newest audit entries as JSON, for the settings page's live tail.

        503 without a store: the tail is the store's data, and an empty list would claim
        there was nothing to record.
        """
        if self.server.audit_conn is None:  # type: ignore[attr-defined]
            self._send_json(503, {"error": "the audit store is not available"})
            return
        self._send_json(200, {"entries": audit_store.entries(self.server.audit_conn)})  # type: ignore[attr-defined]

    def _send_audit_csv(self) -> None:
        """The whole audit trail as a CSV download.

        The bytes are the store's own export rather than a re-rendering of its rows, so
        the file carries exactly what the store holds; the content type tells a browser
        to download it.
        """
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

    def _send_settings_page(self) -> None:
        """Render the settings page: sources, skills, endpoint, mail, registry, audit.

        Every store is optional, so each block falls back to the empty form the page
        renders when nothing opened. The audit block reads the newest 60 entries plus a
        total count, because the page shows a sample and the true size side by side.
        """
        server = self.server  # type: ignore[attr-defined]
        entries = server.activity_log.entries() if server.activity_log is not None else []
        skills = server.skills.active() if server.skills is not None else []
        histories = {s["id"]: server.skills.history(s["id"]) for s in skills}
        audit_entries = (
            audit_store.entries(server.audit_conn, 60)
            if server.audit_conn is not None else []
        )
        audit_total = (
            audit_store.count(server.audit_conn)
            if server.audit_conn is not None else 0
        )
        page = render_settings_page(
            entries, skills, histories, agentdesk.__version__,
            settings_values=self._settings_public_values(),
            endpoint_status=self._endpoint_status(),
            mail_folder=server.settings.get("mail_folder") if server.settings is not None else "",
            registry_status=self._registry_status_for_settings(),
            extra_hosts=(server.settings.get("extra_allowed_hosts")
                         if server.settings is not None else ""),
            server_port=server.port,
            inbox_count=self._inbox_waiting_count(),
            audit_entries=audit_entries,
            audit_total=audit_total,
            preference_notice=self._preference_notice(),
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
        """The public settings values as JSON, for the page's widgets.

        503 without a store; the values are the public subset the page is allowed to
        see, never the raw store, so the widget route cannot become a second read
        surface.
        """
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        self._send_json(200, self._settings_public_values())

    def _endpoint_save(self) -> None:
        """Save (or clear, with empty strings) the three endpoint rows.

        Unknown field names are a 400 naming the accepted fields, and a
        base that is not a full http(s) address is refused: a silent ok
        is how a typo'd field name loses a key."""
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        body = self._read_json_body() or {}
        unknown = sorted(name for name in body if name not in ("base", "key", "model"))
        if unknown:
            self._send_json(400, {"error": (
                "unknown endpoint field(s): " + ", ".join(unknown)
                + "; accepted fields are base, key, model"
            )})
            return
        base = str(body.get("base", "")).strip()
        problem = base_url_problem(base)
        if problem:
            self._send_json(400, {"error": problem})
            return
        saved = {
            "llm_base": base,
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
        """Flip one named switch and let the change take effect before answering.

        Only the listed keys are accepted, so a typo is a 400 rather than a new setting
        nobody reads. What the flip then means depends on the key: sample data seeds or
        clears its fixtures, the semantic and memory-loop switches are re-read on the
        next action, and every remaining key stops or starts its watcher. A form submit
        goes back to the inbox — the one page that posts this without JavaScript.
        """
        server = self.server  # type: ignore[attr-defined]
        if server.settings is None:
            self._send_json(503, {"error": "settings are not available"})
            return
        body = self._read_json_body() or {}
        key = body.get("key")
        if key not in ("excel_enabled", "calendar_enabled", "endpoint_enabled", "quiet_hours", "daily_cap", "mail_enabled", "sample_data", "semantic_memory", "suggest_headers_only", "plugin_instance_cap",
                       "memory_capture", "memory_auto_approve", "memory_capture_assistant",
                       "memory_capture_research", "memory_capture_workbook",
                       "memory_capture_agents"):
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
        elif key in ("suggest_headers_only", "plugin_instance_cap") or key.startswith("memory_"):
            # The memory loop reads its switches on every capture.
            pass
        else:
            self._apply_source_toggles(key, value)
        # The one form poster is the inbox empty state's offer, so a
        # no-JS post lands back on the inbox it came from.
        if self._is_form_submit():
            self._send_redirect("/inbox")
            return
        self._send_json(200, {"key": key, "value": value})

    def _apply_sample_data(self, value) -> None:
        """On seeds the labelled sample set into the real stores; off
        removes exactly what the Sample markers identify. Both turns
        write their audit row, so the decision log says what happened
        and the activity page shows it."""
        server = self.server  # type: ignore[attr-defined]
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
        self._audit("demo.seeded" if value else "demo.cleared",
                    target="sample_data", detail=result["detail"])

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
        if server.layout is None:
            self._send_json(503, {"error": "the layout store is not available"})
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
            facts_block=self._facts_block(skill["prompt"]),
        )
        llm, endpoint, model = self._effective_llm()
        answer = research(
            skill["prompt"], context, llm=llm, audit_conn=server.audit_conn,
            endpoint=endpoint, model=model,
        )
        self._send_json(200, answer.to_json())

    def _skill_undo(self, skill_id: int) -> None:
        """Deactivate a skill — this surface's only undo.

        A SkillError means the store cannot name that skill and answers 404; on success
        the body is the store's own record of the deactivation.
        """
        server = self.server  # type: ignore[attr-defined]
        if server.skills is None:
            self._send_json(503, {"error": "skills are not available"})
            return
        try:
            self._send_json(200, server.skills.deactivate(skill_id))  # type: ignore[attr-defined]
        except SkillError as exc:
            self._send_json(404, {"error": str(exc)})

    def _send_skill_markdown(self, skill_id: int) -> None:
        """One skill's prompt as plain markdown, for copying out of the app.

        404 when the store cannot name it. text/plain is deliberate: a browser then
        shows the text instead of rendering it as a page.
        """
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
        """A calendar read may owe the inbox a brief or two."""
        server = self.server  # type: ignore[attr-defined]
        if server.calendar is not None and server.inbox is not None and server.activity_log is not None:
            try:
                generate_briefs(server.calendar, server.inbox, server.activity_log, server.inbox.clock)
            except Exception:  # noqa: BLE001 - briefs must never break the inbox
                LOG.exception("brief generation failed")

    def _send_inbox_page(self) -> None:
        """Render the inbox: waiting cards, dismissed ones and the sample-data switch.

        Two passes run first, briefs then the evaluator, so a card whose window opened
        while the page was away is already waiting. The clock is the store's own, like
        every payload, so a card never ages by two different clocks.
        """
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        self._maybe_briefs()
        self._evaluate_inbox(inbox)
        # The store's own clock, like every payload: cards never age by
        # two different clocks.
        now_ts = inbox.now_ts()
        settings = self.server.settings  # type: ignore[attr-defined]
        sample_on = bool(settings.get("sample_data")) if settings is not None else False
        page = render_inbox_page(inbox.waiting(), inbox.dismissed(),
                                 agentdesk.__version__, now_ts,
                                 sample_data_on=sample_on)
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
        """Accept or dismiss one card, at most once.

        A card that is no longer waiting is refused: JSON gets a 409 carrying the card's
        current state, while a replayed form post redirects to the inbox, which is what
        a double-click means. A mail draft's file is written before the acceptance is
        recorded, so a failed write leaves the card waiting for a retry instead of an
        accepted card that wrote nothing. Acceptance then runs the card's kind-specific
        follow-up and the fact-carried hook, and both decisions are audited under
        inbox.approved or inbox.denied.
        """
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
        kind = parse_qs(query).get("kind", [""])[0] if query else ""
        page = render_audit_page(entries, questions, agentdesk.__version__,
                                 inbox_count=self._inbox_waiting_count(),
                                 kind=kind or None)
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    # -- memory: the page and its actions (tickets #42, #94) --------------

    def _configure_memory_embeddings(self) -> None:
        """Derive the memory store's semantic half for this action
        (ticket #95): the semantic_memory toggle (default on), the
        embeddings probe's cached answer (a PASS only; the page's
        re-test is what produced it), and a saved endpoint to ask. Any
        miss leaves the store inert, so recall is the deterministic
        hybrid exactly as before this ticket. The embedder is wrapped
        in the audit rows every outbound call owes; the store is a
        long-lived object, so the derived pair is written back onto it
        per action rather than per boot."""
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None or memory.locked_cause is not None:
            return
        settings = server.settings
        active = True if settings is None else bool(settings.get("semantic_memory"))
        cache = server.capabilities_cache
        cached = cache.cached("embeddings") if cache is not None else None
        passed = cached is not None and cached.result.status == GATE_PASS
        base, key, _model = effective_llm_config(settings)
        embedder = None
        if active and passed and base:
            embedder = _AuditedEmbedder(
                EndpointEmbedder(base, key, effective_embeddings_model(settings)),
                base_url=base,
                audit_conn=server.audit_conn,
            )
        memory.embedder = embedder
        memory.embeddings_active = embedder is not None

    def _memory_available(self):
        """The store check every memory route rides: None means the
        response is already sent. A locked store (a marker without its
        key, a wrong key, a key on a populated plaintext bank) refuses
        with its specific plain-language cause, never silently reading
        or writing plaintext."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return None
        if memory.locked_cause is not None:
            self._send_json(503, {"error": memory.locked_cause})
            return None
        return memory

    def _send_memory_page(
        self,
        recall: list | None = None,
        query: str = "",
        encrypt: dict | None = None,
        sweep: list | None = None,
        notice: str | None = None,
    ) -> None:
        """The memory page; with a recall preview when a query came in,
        the encryption state alongside the facts, the entities with
        their merge form (ticket #92), the junk-sweep preview when
        asked, and the locked banner alone when the store is locked."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            page = render_memory_page(
                [], agentdesk.__version__, locked=memory.locked_cause,
                inbox_count=self._inbox_waiting_count(),
            )
        else:
            if encrypt is None:
                encrypt = {"already": True} if memory.is_sealed else {"link": True}
            page = render_memory_page(
                memory.all(), agentdesk.__version__, recall=recall, query=query,
                encrypt=encrypt, entities=memory.entities(), sweep=sweep,
                notice=notice, observations=memory.observations(),
                embeddings=memory.embedding_counts(),
                inbox_count=self._inbox_waiting_count(),
                graph_island=memory_graph_island_built(),
                loop_island=memory_loop_island_built(),
            )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _memory_add(self) -> None:
        """The page's typed-fact path. (The Assistant and Research create
        facts only through capture, which the memory settings govern and
        review gates by default.) Ticket #95: the
        semantic half is derived per action, so an active fact embeds
        at write and a failure stores the fact without a vector."""
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        body = self._read_json_body() or {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            self._send_json(400, {"error": 'expected {"text": "..."}'})
            return
        # Typed facts keep the user's words; the names they mention link
        # them to entities, so supersede and consolidation see them too.
        outcome = memory_loop.store_fact(
            memory, text.strip(), source="page", entities=memory_loop.names_in(text),
        )
        self._schedule_observation_pass()
        self._memory_response(_fact_json(outcome.fact), status=201)

    def _memory_edit(self, fact_id: int | None) -> None:
        """Rewrite one fact's text.

        404 for an id that names no fact and 400 for a body with no text. An edit whose
        new text matches another fact merges into it: a form post re-renders the page
        with the merge notice, while JSON returns the surviving fact with
        mergedIntoExisting set, so neither client has to guess which fact it now holds.
        """
        if fact_id is None:
            self._send_error_page(404, "Nothing here", "No fact lives at this address.")
            return
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        body = self._read_json_body() or {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            self._send_json(400, {"error": 'expected {"text": "..."}'})
            return
        try:
            result = memory.edit(fact_id, text.strip())
        except UnknownFact as exc:
            self._send_json(404, {"error": str(exc)})
            return
        # Ticket #92: an edit that landed on another fact's text merged
        # into it; a form post renders the page with the plain notice,
        # JSON carries the flag alongside the surviving fact.
        if result.merged_into and self._is_form_submit():
            self._send_memory_page(notice=EDIT_MERGE_NOTICE)
            return
        payload = _fact_json(result.fact)
        payload["mergedIntoExisting"] = result.merged_into
        self._memory_response(payload)

    def _memory_delete(self, fact_id: int | None) -> None:
        """Remove one fact, holding it for undo.

        The plan and the apply both receive the pending source ids, so a removal that
        keeps some sources keeps the same set at both stages. The removal is audited by
        count and followed by an observation pass; the answer names the deleted id.
        """
        if fact_id is None:
            self._send_error_page(404, "Nothing here", "No fact lives at this address.")
            return
        memory = self._memory_available()
        if memory is None:
            return
        try:
            plan = memory_loop.plan_removal(
                memory, "fact", fact_id, keep_source_ids=self._pending_source_ids())
        except memory_loop.UnknownTarget as exc:
            self._send_json(404, {"error": str(exc)})
            return
        memory_loop.apply_removal(memory, plan, keep_source_ids=self._pending_source_ids())
        self._audit("memory.remove", target=f"fact {fact_id}", detail="1 fact")
        self._schedule_observation_pass()
        self._memory_response({"deleted": fact_id})

    def _memory_sweep_page(self) -> None:
        """The sweep's dry run (ticket #92): the memory page with the
        candidates, each carrying its reason and a checkbox. A locked
        store renders the banner, like the main page does."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_memory_page()
            return
        self._send_memory_page(sweep=memory.sweep_candidates())

    def _memory_graph_page(self) -> None:
        """The memory graph page (ticket #96): the snapshot's static
        SVG in this app's page style. A locked store renders the
        memory page's banner, like the sweep's dry run does; the query
        string parses defensively (memory dates, a clamped limit), so
        the page renders whatever arrives."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_memory_page()
            return
        _path, _sep, query = self.path.partition("?")
        since, until, limit = parse_graph_query(query)
        snapshot = memory.graph_snapshot(since=since, until=until, limit=limit)
        page = render_graph_page(
            snapshot,
            agentdesk.__version__,
            since=since,
            until=until,
            inbox_count=self._inbox_waiting_count(),
            island_query=query if memory_graph_island_built() else None,
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _memory_graph_json(self) -> None:
        """The Memory page graph's data (GET /api/memory/graph): the
        store's real facts, observations, entities, retained excerpts
        and the actions that wrote them, with each node's provenance.
        Same window vocabulary as the static graph page; a locked store
        answers 423 with its cause and reads nothing."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"status": "unavailable",
                                  "error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_json(423, {"status": "locked", "error": memory.locked_cause})
            return
        self._configure_memory_embeddings()
        _path, _sep, query = self.path.partition("?")
        since, until, limit = parse_graph_query(query)
        payload = build_memory_graph(
            memory,
            inbox=self.server.inbox,  # type: ignore[attr-defined]
            since=since,
            until=until,
            limit=limit,
            semantic=bool(memory.embeddings_active),
        )
        self._send_json(200, payload)

    # -- the memory loop: capture, the page's state, removal and undo ------

    def _capture_memory(self, channel: str, excerpt: str, own_words: str,
                        use_model: bool = True, candidates=None) -> None:
        """Offer what just flowed through a channel to the memory loop.
        Runs off the request thread (one capture at a time) so a reply is
        never slowed by extraction; any failure is logged, never raised
        into the turn that triggered it. A turn the endpoint just failed
        (`use_model` false) goes straight to the rules instead of asking
        the same endpoint again."""
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None or memory.locked_cause is not None:
            return
        settings = memory_loop.capture_settings(server.settings)
        if not settings.captures(channel):
            return
        if candidates is not None:
            use_model = False  # the channel wrote its own candidates
        extractor, endpoint, model = self._capture_extractor() if use_model else (None, "", "")
        extract = extractor.extract if extractor is not None else None

        def job() -> None:
            """The capture itself, on the background runner's thread.

            The lock is what keeps captures to one at a time. A failure is logged and
            swallowed, because capture must never break the turn that triggered it. The
            llm.retain row is written only when an extractor ran, so a rules-only
            capture adds no model noise. The observation pass is scheduled after the
            lock is released, so the next pass waits on the lock rather than on this
            job.
            """
            with server.memory_capture_lock:
                try:
                    self._configure_memory_embeddings()
                    outcome = memory_loop.capture(
                        memory, server.inbox,
                        channel=channel, excerpt=excerpt[:RETAIN_EXCERPT_MAX_CHARS],
                        own_words=own_words, settings=settings, extract=extract,
                        stage_card=self._capture_card,
                        speaker="Workbook" if channel == "workbook" else "You",
                        candidates=candidates,
                    )
                except Exception:  # noqa: BLE001 - capture must never break a turn
                    LOG.exception("memory capture on %s failed", channel)
                    return
                if outcome is None:
                    return
                if extractor is not None:
                    self._model_audit(
                        "llm.retain", endpoint or "", model or "", self._port_bytes(extractor),
                        status="ok" if outcome.method == memory_loop.METHOD_MODEL else "error",
                        detail=outcome.cause,
                    )
                server.memory_last_capture = {
                    "channel": channel,
                    "channelLabel": memory_loop.CHANNEL_LABELS.get(channel, channel),
                    "method": outcome.method,
                    "cause": outcome.cause,
                    "found": outcome.found,
                    "skipped": outcome.skipped,
                    "staged": len(outcome.card_ids),
                    "stored": len(outcome.fact_ids),
                    "ts": time.time(),
                }
                if outcome.card_ids or outcome.fact_ids:
                    self._audit(
                        "memory.capture", target=channel,
                        detail=(f"{len(outcome.card_ids)} to review, "
                                f"{len(outcome.fact_ids)} saved, by {outcome.method}"),
                    )
                if outcome.card_ids and server.inbox is not None:
                    self._evaluate_inbox(server.inbox)
            if outcome is not None and outcome.fact_ids:
                self._schedule_observation_pass()

        server.memory_capture_runner(job)

    def _observation_summarizer(self) -> tuple:
        """(summarizer, endpoint, model) for the per-entity observations,
        or (None, "", "") when endpoint calls are off or none is
        configured: then the rules write them."""
        server = self.server  # type: ignore[attr-defined]
        if not self._source_allowed("endpoint_enabled"):
            return None, "", ""
        llm, endpoint, model = self._effective_llm()
        if server.summarizer is not None:
            return server.summarizer, endpoint or "", model or ""
        if endpoint or not server.llm_defaulted_to_env:
            return memory_loop.EndpointSummarizer(llm), endpoint or "", model or ""
        return None, "", ""

    def _observe_audit(self, summarizer, endpoint: str, model: str, written: int,
                       failure: str) -> None:
        """Record what an observation pass did: llm.observe with the count written.

        The detail always names the written count and appends the first 160 characters
        of the failure when there was one. A failed pass still writes a row, so a pass
        that wrote nothing cannot look like a pass that never ran.
        """
        self._model_audit(
            "llm.observe", endpoint or "", model or "", self._port_bytes(summarizer),
            status="error" if failure else "ok",
            detail=(f"{memory_loop.counted(written, 'observation')} written"
                    + (f"; {failure[:160]}" if failure else "")),
        )

    def _schedule_observation_pass(self) -> None:
        """After memory changes: let the endpoint rewrite the observations
        the rules just wrote (or any built from changed facts), off the
        request thread. Coalesced: one pending pass at a time; a change
        during a pass schedules the next one."""
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None or memory.locked_cause is not None:
            return
        summarizer, endpoint, model = self._observation_summarizer()
        if summarizer is None or server.memory_observe_pending:
            return
        server.memory_observe_pending = True

        def job() -> None:
            """One coalesced observation pass, on the background runner's thread.

            The pending flag is cleared first, so a change that arrives during the pass
            schedules the next one instead of being lost. A failure is logged and leaves
            the rules' text in place. The audit row is written only when the summarizer
            reports calls, so a pass that needed no endpoint call is not recorded as
            one.
            """
            server.memory_observe_pending = False
            with server.memory_capture_lock:
                try:
                    outcome = memory_loop.reconcile_observations(memory, summarize=summarizer)
                except Exception:  # noqa: BLE001 - a failed pass leaves the rules' text
                    LOG.exception("memory observation pass failed")
                    return
            if getattr(summarizer, "calls", 1):
                self._observe_audit(summarizer, endpoint, model,
                                    outcome.model_written, outcome.model_failure)

        server.memory_capture_runner(job)

    def _capture_card(self, candidate, source_id: int, channel: str, method: str):
        """The review card for one captured candidate: the same memory
        draft card the manual save makes, with the channel and the
        extraction method recorded so the page can say where it came
        from and how."""
        label = memory_loop.CHANNEL_LABELS.get(channel, channel)
        names = ", ".join(name for name, _type in candidate.entities)
        how = ("the company endpoint" if method == memory_loop.METHOD_MODEL
               else "the built-in rules (no endpoint answered)")
        return self.server.inbox.add(  # type: ignore[attr-defined]
            kind=KIND_MEMORY_DRAFT,
            origin=(f"Captured from your {label} activity by {how}. "
                    "Approving saves this fact to memory; rejecting leaves nothing behind."),
            title=f"Fact from {label}" + (f": {names}" if names else ""),
            body=f"Captured from {label}." + (f" Mentions {names}." if names else ""),
            action_label="Save to memory",
            draft=candidate.text,
            meta={"memoryFact": {
                "kind": candidate.kind,
                "occurrence_ts": candidate.occurrence_ts,
                "entities": [[name, entity_type] for name, entity_type in candidate.entities],
                "source_id": source_id,
                "channel": channel,
                "method": method,
            }},
        )

    def _pending_source_ids(self) -> set[int]:
        """Excerpts a waiting review card still points at: a removal
        leaves them in place so approving the card later still links."""
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            return set()
        ids: set[int] = set()
        for card in inbox.waiting(include_snoozed=True):
            meta = card.meta.get("memoryFact") if isinstance(card.meta, dict) else None
            if isinstance(meta, dict) and isinstance(meta.get("source_id"), int):
                ids.add(int(meta["source_id"]))
        return ids

    def _capture_extractor(self) -> tuple:
        """(extractor, endpoint, model) capture asks first, or (None, "",
        "") when endpoint calls are off or no endpoint is configured."""
        server = self.server  # type: ignore[attr-defined]
        if not self._source_allowed("endpoint_enabled"):
            return None, "", ""
        llm, endpoint, model = self._effective_llm()
        if server.extractor is not None:
            return server.extractor, endpoint or "", model or ""
        if endpoint or not server.llm_defaulted_to_env:
            return EndpointExtractor(llm), endpoint or "", model or ""
        return None, "", ""

    def _extractor_status(self) -> dict:
        """Which extraction method capture will use, with the reason, for the memory page.

        A disabled endpoint or none saved means the built-in rules, each with its own
        sentence; a configured endpoint means the model, naming it and warning that the
        rules take over when it does not answer.
        """
        if not self._source_allowed("endpoint_enabled"):
            return {"mode": memory_loop.METHOD_RULES,
                    "detail": "Endpoint calls are off in Settings, so capture uses the built-in rules on your own words."}
        extractor, _endpoint, model = self._capture_extractor()
        if extractor is not None:
            return {"mode": memory_loop.METHOD_MODEL,
                    "detail": f"Extracting with {model or 'the default model'}. If the endpoint does not answer, the built-in rules take over."}
        return {"mode": memory_loop.METHOD_RULES,
                "detail": "No endpoint is saved in Settings, so capture uses the built-in rules on your own words."}

    def _memory_loop_json(self) -> None:
        """The memory loop's state as JSON, and a chance to re-offer rule-built
        observations.

        423 when the store is locked, carrying the store's own cause. When any
        observation still carries the rules' mark — the bank predates the endpoint, or a
        pass ran while it was down — one pass is scheduled, at most once a minute while
        the page stays open, so looking at the page is what improves it.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None:
            self._send_json(503, {"status": "unavailable", "error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_json(423, {"status": "locked", "error": memory.locked_cause})
            return
        # Observations the rules wrote (the endpoint was down, or the bank
        # predates it) are offered to the endpoint again, at most once a
        # minute while the page is open.
        now = time.time()
        if now >= server.memory_observe_after and any(
            method == memory_loop.METHOD_RULES for method, _b in memory.observation_marks().values()
        ):
            server.memory_observe_after = now + 60.0
            self._schedule_observation_pass()
        settings = memory_loop.capture_settings(server.settings)
        self._send_json(200, build_loop_state(
            memory, server.inbox, settings.to_json(), self._extractor_status(),
            server.memory_last_capture, server.memory_undo.window_s,
        ))

    def _memory_target(self, body: dict) -> tuple[str, int] | None:
        """The (kind, id) a request names, or None when it names neither properly.

        The id must be a true int: a bool is refused even though Python would accept it
        as one, because a JSON true is not an id. A body without a target field falls
        back to the body itself, so a flat request means what a nested one means.
        """
        target = body.get("target") if isinstance(body.get("target"), dict) else body
        kind = target.get("type")
        raw = target.get("id")
        if kind not in memory_loop.TARGET_TYPES or isinstance(raw, bool) or not isinstance(raw, int):
            return None
        return kind, raw

    def _memory_remove(self, preview: bool) -> None:
        """Preview names everything a removal changes and writes nothing;
        the removal itself writes once, holds an undo for the window and
        records an audit row with counts, never memory text."""
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        body = self._read_json_body() or {}
        target = self._memory_target(body)
        if target is None:
            self._send_json(400, {"error": 'expected {"target": {"type": "fact|source|entity|observation", "id": <id>}}'})
            return
        kind, target_id = target
        if kind == "source" and not preview and server.inbox is not None:
            # Removing an excerpt also rejects the cards still waiting on it.
            for card in server.inbox.waiting(include_snoozed=True):
                meta = card.meta.get("memoryFact") if isinstance(card.meta, dict) else None
                if isinstance(meta, dict) and meta.get("source_id") == target_id:
                    server.inbox.dismiss(card.id)
        keep = self._pending_source_ids()
        # The preview asks the endpoint for the observations' new text (so
        # the dialog shows what they will read); the removal reuses it.
        summarizer, endpoint, model = self._observation_summarizer() if preview else (None, "", "")
        try:
            plan = memory_loop.plan_removal(
                memory, kind, target_id, keep_source_ids=keep,
                summarize=summarizer,
            )
        except (memory_loop.UnknownTarget, UnknownEntity, UnknownFact) as exc:
            self._send_json(404, {"error": str(exc)})
            return
        if summarizer is not None and getattr(summarizer, "calls", 0):
            self._observe_audit(summarizer, endpoint, model, sum(
                1 for _scope, summary in plan.after.values()
                if summary.method == memory_loop.METHOD_MODEL
            ), "")
        if preview:
            server.memory_previews.put(plan)
            self._send_json(200, {"status": "ok", "plan": plan.to_json(memory)})
            return
        self._configure_memory_embeddings()
        planned = server.memory_previews.take(kind, target_id)
        result = memory_loop.apply_removal(memory, plan, keep_source_ids=keep, planned=planned)
        self._schedule_observation_pass()
        token, expires = server.memory_undo.hold(result, plan.label)
        counts = (f"{memory_loop.counted(len(result.fact_ids), 'fact')}; observations:"
                  f" {len(result.observations_removed)} removed, {len(result.observations_updated)} rewritten,"
                  f" {len(result.observations_flagged)} flagged;"
                  f" {memory_loop.counted(len(result.entities_removed), 'entity', 'entities')} forgotten")
        self._audit("memory.remove", target=f"{kind} {target_id}", detail=counts)
        self._send_json(200, {
            "status": "ok",
            "removed": result.to_json(),
            "undo": {"token": token, "expiresTs": expires, "windowS": server.memory_undo.window_s},
        })

    def _memory_undo(self) -> None:
        """Undo a removal inside its window.

        The token is taken out of the buffer, so a second undo with the same token finds
        nothing and answers 410 with the window message. A ValueError means the data
        moved on since the preview and answers 409. A successful undo is audited and
        followed by an observation pass.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        body = self._read_json_body() or {}
        token = body.get("token")
        held = server.memory_undo.take(token) if isinstance(token, str) else None
        if held is None:
            self._send_json(410, {"error": "The undo window has passed, so that removal is final."})
            return
        try:
            memory_loop.undo_removal(memory, held)
        except ValueError as exc:
            self._send_json(409, {"error": str(exc)})
            return
        self._schedule_observation_pass()
        self._audit("memory.undo", target=memory_loop.counted(len(held.result.fact_ids), "fact"),
                    detail="removal undone within the window")
        self._send_json(200, {"status": "ok", "restored": held.result.to_json()})

    def _memory_keep(self, raw_id: str) -> None:
        """Keep both: a replaced fact rides recall again."""
        memory = self._memory_available()
        if memory is None:
            return
        if not raw_id.isdigit():
            self._send_json(404, {"error": "no fact at this address"})
            return
        try:
            memory.clear_superseded(int(raw_id))
        except UnknownFact as exc:
            self._send_json(404, {"error": str(exc)})
            return
        memory_loop.reconcile_observations(memory)
        self._schedule_observation_pass()
        self._audit("memory.keep", target=f"fact {raw_id}", detail="kept beside its replacement")
        self._send_json(200, {"status": "ok", "kept": int(raw_id)})

    def _memory_sweep(self) -> None:
        """Delete the checked candidates through the donor's removeFacts
        semantics (ticket #92): every id must be a current junk
        candidate and must exist, or the whole call is refused before
        anything is written. The audit row names counts, never fact
        text."""
        memory = self._memory_available()
        if memory is None:
            return
        body = self._read_json_body() or {}
        ids = self._sweep_ids_from_body(body)
        if not ids:
            self._memory_hygiene_error_response(
                400, 'expected {"ids": [...]} or the preview checkboxes'
            )
            return
        candidates = {c.fact.id: c.reason for c in memory.sweep_candidates()}
        for fact_id in ids:
            if fact_id in candidates:
                continue
            try:
                memory.get(fact_id)
            except UnknownFact:
                self._memory_hygiene_error_response(404, f"no fact {fact_id}")
                return
            self._memory_hygiene_error_response(
                400,
                "That fact is not a junk candidate; delete it from the "
                "fact list instead.",
            )
            return
        try:
            removed = memory.remove_facts(ids)
        except UnknownFact as exc:
            # A candidate vanished between the preview and this post.
            self._memory_hygiene_error_response(404, str(exc))
            return
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(
                self.server.audit_conn, "memory.sweep",
                target=f"{len(removed.fact_ids)} facts",
                detail=(f"swept {len(removed.observation_ids)} orphaned"
                        f" observations and {len(removed.entity_ids)} orphaned"
                        " entities"),
            )
        self._memory_response({
            "status": "ok",
            "deleted": len(removed.fact_ids),
            "removedFactIds": list(removed.fact_ids),
            "removedObservationIds": list(removed.observation_ids),
            "removedEntityIds": list(removed.entity_ids),
        })

    def _sweep_ids_from_body(self, body: dict) -> list[int]:
        """The checked candidate ids: a JSON id list, or one checkbox
        per candidate (the no-JS form's unique names). Anything that is
        not a fact id is a refused call, never a partial delete."""
        raw = body.get("ids")
        if isinstance(raw, list):
            ids: list[int] = []
            for value in raw:
                if isinstance(value, bool) or not isinstance(value, int):
                    return []
                ids.append(value)
            return sorted(set(ids))
        checked: set[int] = set()
        for name, value in body.items():
            if not name.startswith("sweep_") or not value:
                continue
            suffix = name[len("sweep_"):]
            if not suffix.isdigit():
                return []
            checked.add(int(suffix))
        return sorted(checked)

    def _memory_entities_merge(self) -> None:
        """The page's entity merge (ticket #92): union the aliases,
        relink every fact, one entity remains. The audit row names ids,
        never entity names."""
        memory = self._memory_available()
        if memory is None:
            return
        body = self._read_json_body() or {}
        survivor = _memory_entity_id(body.get("survivor"))
        removed = _memory_entity_id(body.get("removed"))
        if survivor is None or removed is None:
            self._memory_hygiene_error_response(
                400, 'expected {"survivor": <id>, "removed": <id>}'
            )
            return
        try:
            merged = memory.merge_entities(survivor, removed)
        except ValueError as exc:
            self._memory_hygiene_error_response(400, str(exc))
            return
        except UnknownEntity as exc:
            self._memory_hygiene_error_response(404, str(exc))
            return
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(
                self.server.audit_conn, "memory.merge",
                target=str(survivor),
                detail=f"merged entity {removed} into entity {survivor}",
            )
        self._memory_response({
            "status": "ok",
            "survivor": merged.id,
            "survivorName": merged.canonical_name,
            "aliases": list(merged.aliases),
            "type": merged.type,
            "merged": removed,
        })

    def _memory_hygiene_error_response(self, status: int, cause: str) -> None:
        """A refused hygiene action: the error page for a form post, the
        JSON cause for an API call."""
        if self._is_form_submit():
            self._send_error_page(status, "Memory hygiene", cause)
            return
        self._send_json(status, {"error": cause})

    def _memory_recall(self) -> None:
        """The preview: render the page with the ranked answers, best
        first, so the manager sees exactly what the assistant would
        ride. Ticket #95: the query embeds once when the semantic half
        is active; a failure simply leaves the deterministic legs."""
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        body = self._read_json_body() or {}
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            self._send_json(400, {"error": 'expected {"query": "..."}'})
            return
        query = query.strip()
        self._send_memory_page(recall=memory.recall(query), query=query)

    def _memory_encrypt_page(self) -> None:
        """The dry run: the memory page with the conversion form and the
        per-table counts of what would be sealed. An already-encrypted
        bank says so; a locked one renders the banner."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_memory_page()
            return
        if memory.is_sealed:
            self._send_memory_page(encrypt={"already": True})
            return
        self._send_memory_page(encrypt={"counts": memory.plain_field_counts()})

    def _memory_encrypt(self) -> None:
        """The one-action conversion, confirm-gated (ticket #94).

        The checkbox is the settings confirmation the spec asks for: no
        confirm field, no conversion. The key file is ensured before the
        transaction, the conversion is one transaction, and the audit
        row names the field count, never a key byte or a fact text."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._memory_error_response(503, memory.locked_cause)
            return
        if memory.is_sealed:
            self._memory_error_response(
                409, "The memory database is already encrypted."
            )
            return
        body = self._read_json_body() or {}
        if not body.get("confirm"):
            self._memory_error_response(
                400,
                "Tick the confirm checkbox: the conversion rewrites every "
                "stored text and cannot be undone without the key.",
            )
            return
        if memory.key_path is None:
            self._memory_error_response(
                503, "No key file location is configured for this memory store."
            )
            return
        try:
            result = memory.encrypt_all()
        except MemoryEncryptedError as exc:
            self._memory_error_response(409, str(exc))
            return
        except (OSError, ValueError) as exc:
            self._memory_error_response(
                503, f"The key file could not be written or read: {exc}"
            )
            return
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(
                self.server.audit_conn, "memory.encrypt",
                target=f"{result['fields']} fields",
                detail=("memory.sqlite3 encrypted at rest; the key stays"
                        " in memory.key"),
            )
        self._memory_response({"status": "ok", "fields": result["fields"]})

    def _memory_error_response(self, status: int, cause: str) -> None:
        """A refused memory action: the error page for a form post, the
        JSON cause for an API call."""
        if self._is_form_submit():
            self._send_error_page(status, "Memory encryption", cause)
            return
        self._send_json(status, {"error": cause})

    def _memory_response(self, payload: dict, status: int = 200) -> None:
        """A no-JS form post lands back on the memory page; JSON gets JSON."""
        if self._is_form_submit():
            self._send_redirect("/memory")
            return
        self._send_json(status, payload)

    # -- embeddings backfill (ticket #95) ----------------------------------

    def _memory_embeddings_backfill(self) -> None:
        """The memory page's backfill action (ticket #95, the donor's
        backfillEmbeddings): every fact missing a vector embeds
        oldest-first, one committed UPDATE per row, so a mid-run
        failure leaves the prior rows embedded and a retry finishes
        the job. The answer carries the counts either way (embedded N,
        remaining M) and, when the run stopped early, the endpoint's
        plain-language cause. The action's audit row names the counts,
        never a fact text; the individual endpoint calls ride the
        llm.embeddings rows the audited embedder writes."""
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        if not (memory.embeddings_active and memory.embedder is not None):
            self._memory_embeddings_error_response(
                409,
                "Semantic memory is not active: pass the embeddings probe"
                " on the capabilities page, keep semantic memory on in"
                " settings, and save an endpoint first.",
            )
            return
        try:
            result = memory.backfill_embeddings()
        except MemoryEncryptedError as exc:
            self._memory_embeddings_error_response(503, str(exc))
            return
        counts = f"{result['embedded']} embedded, {result['remaining']} remaining"
        cause = result.get("cause")
        if server.audit_conn is not None:
            audit_store.record(
                server.audit_conn, "memory.embeddings",
                target=counts,
                status="ok" if cause is None else "error",
                detail=cause or "",
            )
        notice = f"Embeddings backfill: {counts}."
        if cause is not None:
            notice = f"Embeddings backfill stopped early: {cause} Counts: {counts}"
            if self._is_form_submit():
                self._send_memory_page(notice=notice)
                return
            self._send_json(200, {
                "status": "error",
                "embedded": result["embedded"],
                "remaining": result["remaining"],
                "cause": cause,
            })
            return
        if self._is_form_submit():
            self._send_memory_page(notice=notice)
            return
        self._send_json(200, {
            "status": "ok",
            "embedded": result["embedded"],
            "remaining": result["remaining"],
            "cause": None,
        })

    def _memory_embeddings_error_response(self, status: int, cause: str) -> None:
        """A refused embeddings action: the error page for a form post,
        the JSON cause for an API call."""
        if self._is_form_submit():
            self._send_error_page(status, "Embeddings", cause)
            return
        self._send_json(status, {"error": cause})

    # -- retain: the chat surface's save-to-memory action (ticket #91) ----

    def _memory_retain(self) -> None:
        """Turn a conversation excerpt into inbox cards, one per
        surviving candidate fact, all sharing one source id.

        The donor writes extracted facts directly; here nothing is
        written until a card is accepted (spec decision 9), and both
        extractor failure classes leave the bank untouched with a
        plain-language error: JSON answers degraded like every LLM
        turn, a form post gets the error page. The endpoint gate and
        the llm.retain audit match every other model call. With no
        extractor injected at construction, an EndpointExtractor is
        built from the effective llm client per call.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        if server.inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        body = self._read_json_body() or {}
        excerpt = body.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip():
            self._send_json(400, {"error": 'expected {"excerpt": "..."}: the conversation you want to save'})
            return
        excerpt = excerpt.strip()[:RETAIN_EXCERPT_MAX_CHARS]
        if not self._source_allowed("endpoint_enabled"):
            self._retain_error_response(
                409,
                "Company endpoint calls are turned off in settings, so "
                "this surface is paused. Everything else keeps working.",
            )
            return
        _llm, endpoint, model = self._effective_llm()
        extractor = server.extractor
        if extractor is None:
            extractor = EndpointExtractor(_llm)
        try:
            candidates = extractor.extract(excerpt)
        except (ExtractorUnavailable, ExtractionFailed) as exc:
            self._model_audit("llm.retain", endpoint, model,
                              self._port_bytes(extractor),
                              status="error", detail=str(exc)[:200])
            self._retain_error_response(502, str(exc))
            return
        self._model_audit("llm.retain", endpoint, model,
                          self._port_bytes(extractor))
        kept = [
            replace(candidate, occurrence_ts=occurrence_from_source(excerpt, candidate.occurrence_ts))
            for candidate in facts_to_retain(candidates)
        ]
        if not kept:
            # Nothing survived the donor's filters: no source row, no
            # cards, no writes at all.
            self._retain_response({"status": "ok", "cards": [], "sourceId": None})
            return
        source_id = memory.add_source(excerpt)
        cards = [self._memory_draft_card(candidate, source_id) for candidate in kept]
        self._evaluate_inbox(server.inbox)
        self._retain_response({
            "status": "ok",
            "cards": [card.to_json(server.inbox.now_ts()) for card in cards],
            "sourceId": source_id,
        })

    def _port_bytes(self, port) -> int:
        """The bytes of the prompt that went out, when the port can say
        (the built-in ones record it; an injected one may not)."""
        return int(getattr(port, "last_request_bytes", 0) or 0)

    def _model_audit(self, action: str, endpoint: str, model: str,
                     request_bytes: int, status: str = "ok",
                     detail: str = "") -> None:
        """A model call's audit row (llm.retain, llm.reflect), the _ask
        pattern's fields."""
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(
                self.server.audit_conn, action, target=endpoint,
                status=status, model=model, request_bytes=request_bytes, detail=detail,
            )

    def _memory_draft_card(self, candidate, source_id: int):
        """One approval card per candidate: the editable draft is the
        fact text, the meta carries what acceptance writes."""
        names = ", ".join(name for name, _type in candidate.entities)
        mentioned = names if names else "nothing named"
        kind_word = "Experience" if candidate.kind == "experience" else "World"
        return self.server.inbox.add(  # type: ignore[attr-defined]
            kind=KIND_MEMORY_DRAFT,
            origin=("Extracted from a conversation you chose to save. "
                    "Accepting writes this fact to memory; dismissing "
                    "leaves nothing behind."),
            title=f"{kind_word} fact: {mentioned}",
            body=f"From the conversation you saved. Mentions {mentioned}.",
            action_label="Save to memory",
            draft=candidate.text,
            meta={"memoryFact": {
                "kind": candidate.kind,
                "occurrence_ts": candidate.occurrence_ts,
                "entities": [[name, entity_type] for name, entity_type in candidate.entities],
                "source_id": source_id,
            }},
        )

    def _retain_response(self, payload: dict) -> None:
        """A form post from the chat surface lands in the inbox, where
        the new cards wait; JSON gets JSON."""
        if self._is_form_submit():
            self._send_redirect("/inbox")
            return
        self._send_json(200, payload)

    def _retain_error_response(self, status: int, cause: str) -> None:
        """A failed retain says so in plain language and writes nothing:
        the error page for a form post, the degraded turn shape for JSON."""
        if self._is_form_submit():
            self._send_error_page(status, "Save to memory", cause)
            return
        self._send_json(200, {"status": "degraded", "cause": cause})

    # -- reflect: the memory page's derive-observations action (ticket #93)

    def _memory_reflect(self) -> None:
        """Gather the bank's facts, ask the reflector for observations,
        and stage one approval card per survivor. Nothing lands in the
        memory bank here (spec decision 24): acceptance writes the
        observation, with its citations, through the card's meta. The
        donor writes its accepted observations directly; here both
        reflector failure classes and every filtered-out draft leave
        the bank untouched with a plain-language notice, and the
        endpoint gate and the llm.reflect audit match every other
        model call. With no reflector injected at construction, an
        EndpointReflector is built from the effective llm client per
        call, exactly like the retain route's extractor. Ticket #95:
        when the semantic half is active, every draft also embeds (one
        audited call each, failures degrade) so the near-duplicate
        rule's cosine leg can join.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        if server.inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        body = self._read_json_body() or {}
        topic = _scope_text(body.get("topic"))
        entity = _scope_text(body.get("entity"))
        try:
            since = parse_scope_date(body.get("since"))
            until = parse_scope_date(body.get("until"))
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        if not self._source_allowed("endpoint_enabled"):
            self._reflect_error_response(
                409,
                "Company endpoint calls are turned off in settings, so "
                "this surface is paused. Everything else keeps working.",
            )
            return
        query = " ".join(part for part in (topic, entity) if part)
        try:
            gathered = gather_facts(
                query, memory.recall(query), memory.all(),
                since=since, until=until,
            )
        except ReflectEmpty as exc:
            # Refused before any model call, so nothing to audit.
            self._reflect_error_response(502, str(exc))
            return
        _llm, endpoint, model = self._effective_llm()
        reflector = server.reflector
        if reflector is None:
            reflector = EndpointReflector(_llm)
        try:
            drafts = reflector.reflect(topic or entity, gathered)
        except (ReflectFailed, ReflectorUnavailable) as exc:
            self._model_audit(
                "llm.reflect", endpoint, model, self._port_bytes(reflector),
                status="error", detail=str(exc)[:200],
            )
            self._reflect_error_response(502, str(exc))
            return
        self._model_audit(
            "llm.reflect", endpoint, model, self._port_bytes(reflector)
        )
        try:
            survivors = accept_observations(
                list(drafts), {fact.id for fact in gathered},
                single_entity=bool(entity), vectors=self._draft_vectors(memory, drafts),
            )
        except ReflectFailed as exc:
            # The call itself succeeded and is already audited; the
            # model's answers just did not survive the donor's filters.
            self._reflect_error_response(502, str(exc))
            return
        scope = scope_key(entity=entity, topic=topic, since=since, until=until)
        gathered_by_id = {fact.id: fact for fact in gathered}
        subject = topic or entity
        title = f"Observation: {subject}" if subject else "Observation"
        cards = [
            self._reflection_card(draft, title, scope, gathered_by_id)
            for draft in survivors
        ]
        self._evaluate_inbox(server.inbox)
        self._retain_response({
            "status": "ok",
            "cards": [card.to_json(server.inbox.now_ts()) for card in cards],
            "rejected": len(drafts) - len(survivors),
        })

    def _draft_vectors(self, memory, drafts) -> dict[str, list[float]]:
        """Each reflector draft's embedding, keyed by its normalized
        text (ticket #95, the donor's reflect: every draft embeds
        through the bank's one embedder, so the map is same-model by
        construction). A failed embed leaves that draft out, which the
        near-duplicate cosine leg reads as no vector, never an error.
        The calls ride the audited wrapper like every other endpoint
        call."""
        vectors: dict[str, list[float]] = {}
        if not (memory.embeddings_active and memory.embedder is not None):
            return vectors
        for draft in drafts:
            key = normalize_fact_text(draft.text)
            if not key or key in vectors:
                continue
            try:
                vectors[key] = list(memory.embedder.embed(draft.text))
            except Exception:  # noqa: BLE001 - the donor's vectorFor
                continue
        return vectors

    def _reflection_card(self, draft, title: str, scope: str,
                         gathered_by_id: dict):
        """One approval card per surviving observation: the editable
        draft is the observation text, the body names the cited facts,
        and the meta carries what acceptance writes (the scope the run
        ran in, the confidence to store, the citations)."""
        cited = [
            fact for fact in
            (gathered_by_id.get(fact_id) for fact_id in draft.fact_ids)
            if fact is not None
        ]
        listing = " | ".join(plain_preview(fact.text) for fact in cited)
        return self.server.inbox.add(  # type: ignore[attr-defined]
            kind=KIND_MEMORY_REFLECTION,
            origin=("Derived from the facts on your memory page. "
                    "Accepting writes this observation with its "
                    "citations; dismissing leaves nothing behind."),
            title=title,
            body=f"Derived from {len(cited)} gathered facts: {listing}",
            action_label="Save observation",
            draft=draft.text,
            meta={"memoryObservation": {
                "scope_key": scope,
                "confidence": draft.confidence,
                "source_fact_ids": list(draft.fact_ids),
            }},
        )

    def _reflect_error_response(self, status: int, cause: str) -> None:
        """A failed reflect says so in plain language and writes
        nothing: the error page for a form post, the degraded turn
        shape for JSON, like retain's."""
        if self._is_form_submit():
            self._send_error_page(status, "Reflect", cause)
            return
        self._send_json(200, {"status": "degraded", "cause": cause})

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
            if form:
                self._send_redirect(
                    "/settings?preferences_error=" + quote(exc.message))
                return
            self._send_json(exc.status, {"error": exc.message, "code": exc.code})
            return
        self._audit("settings.preferences", target="preferences",
                    detail=",".join(changed(document)) or "none")
        if form:
            self._send_redirect("/settings?preferences_saved=1")
            return
        self._send_json(200, document)

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
        plugins = self.server.plugins  # type: ignore[attr-defined]
        if plugins is None:
            self._send_json(503, {"error": "plugins are not available"})
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
        then its action — pick, stage, suggest, evaluate, confirm or outside. Suggest
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
        """The completion callable an endpoint-backed suggestion gets, or None.

        None means no client or no endpoint, which is how the setup flow is told to use
        its deterministic heuristics instead of waiting on a call that would fail.
        """
        server = self.server  # type: ignore[attr-defined]
        if server.llm is None or not server.llm_endpoint:
            return None

        def complete(prompt: str) -> str:
            """One prompt in, one answer out, in the shape the flow expects.

            It is a closure so the flow receives a plain callable and never the handler
            or the server.
            """
            return server.llm(prompt)
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
            self._audit("insight.press", target=kind or "press", detail=exc.code)
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
        has no endpoint or the user turned model calls off. A reading that
        gets None keeps its local elements and offers no press."""
        server = self.server  # type: ignore[attr-defined]
        if server.llm is None or not server.llm_endpoint:
            return None
        if not self._source_allowed("endpoint_enabled"):
            return None

        def complete(prompt: str) -> str:
            """One model call over the desk's endpoint, raw.

            A failing endpoint raises: each caller decides its own
            fallback, so the same adapter serves drafts that fall back to
            the template and explanations that refuse.
            """
            return server.llm(prompt)

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
        """Deprecated: /api/plugins mutations stay for one release; new clients
        use /api/marketplace/* (see marketplace/api.py)."""
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
            self._audit("plugin.install", target=str(result.get("id", "")),
                        detail=f"v{result.get('version', '')} pilot install")
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
        cause = html.escape(str(card.get("cause") or "data source has not run"))
        file_name = html.escape(str(card.get("file") or "the data source"))
        version = html.escape(str(card["version"]))
        payload = card.get("payload") or {}
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
            body = (
                '<div class="alert" id="plugin-amber-' + plugin_id + '">'
                "<p>" + cause + "</p>"
                "<p>Re-test runs the plugin's data source again; the nightly "
                "probe does the same for every plugin.</p></div>"
            )
            extra = "amber"
        if status == FRESH:
            # The reading's resolved lines and its press belong on the card, so
            # the rendered dashboard is never a poorer version of the API.
            insight = payload.get("insight")
            body += _receipt_line(payload)
            body += _press_form(card, insight.get("press") if isinstance(insight, dict) else None)
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
        """Deprecated: /api/plugins/<id> stays for one release; the new detail
        route is /api/marketplace/plugin/<id>."""
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
        that is enabled with pilot views left — the flag means a view can still be
        spent, so a disabled plugin never carries it.
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
        """Deprecated: /api/registry stays for one release; new clients read
        /api/marketplace/catalog."""
        root, origin = self._registry_root_for_request()
        listing = registry_source.registry_listing(root)
        listing["origin"] = origin
        if listing.get("ok"):
            self._audit("registry.read", target="registry",
                        detail=f"{len(listing.get('plugins', []))} plugins from {origin}")
        return listing

    def _send_plugins_page(self, notice: str = "") -> None:
        """Render the plugins page from the runtime's records and the registry listing.

        The listing's origin is passed as a word the page can branch on, and the peer
        counts come from the peer store when it opened. Without a plugin runtime the
        records are empty and the page still renders, which is the honest way to show a
        desk that has no plugin surface.
        """
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        records = plugins.list_records() if plugins is not None else []
        listing = self._registry_listing_for_request()
        peer_store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        page = render_plugins_page(
            records, listing, str(listing.get("origin", "none")),
            agentdesk.__version__, notice=notice,
            inbox_count=self._inbox_waiting_count(),
            shared_ids=peer_store.shared_ids() if peer_store is not None else set(),
            peers_paired=len(peer_store.peers()) if peer_store is not None else 0)
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
            self._send_redirect(f"/plugins?notice={quote(str(exc))}")
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
            self._send_redirect(f"/plugins?notice={quote(str(exc))}")
            return
        if record.get("state") == "uninstalled" or not record.get("versions"):
            self._send_redirect(
                "/plugins?notice=" + quote(
                    f"Only an installed plugin can be shared; "
                    f"{plugin_id} has no installed files."))
            return
        store.set_shared(plugin_id, shared)
        self._audit("peer.share", target=plugin_id,
                    detail="shared with paired desks" if shared
                    else "sharing stopped")
        verb = "shared with paired desks" if shared else "no longer shared"
        self._send_redirect(
            "/plugins?notice=" + quote(f"{plugin_id} is now {verb}."))

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
                if self._is_form_submit():
                    self._send_redirect(f"/plugins?notice={quote(
                        'Already installed ' + plugin_id + ' v' + active + '.')}")
                    return
                self._send_json(200, {"ok": True, "already": True, "version": active})
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
        """Report a refused registry install to whichever client asked.

        A form post goes back to the plugins page with the message as a notice, because
        a browser form has nowhere else to put it; a fetch gets the code and message as
        JSON, at 409 unless the caller names another status.
        """
        if self._is_form_submit():
            self._send_redirect(f"/plugins?notice={quote(message)}")
            return
        self._send_json(status, {"error": code, "message": message})

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
            self._publish_refused(exc.code, str(exc), exc.status)
            return
        except (RegistryError, RegistryIndexError) as exc:
            self._publish_refused(
                getattr(exc, "code", "publish:refused"), str(exc))
            return
        self._audit("registry.publish", target=plugin_id,
                    detail=f"local v{result.get('version', '')} to the "
                           f"{origin} registry")
        if self._is_form_submit():
            self._send_redirect(f"/plugins?notice={quote(
                'Published ' + plugin_id + ' v'
                + str(result.get('version', '')) + ' to the registry.')}")
            return
        self._send_json(200, result)

    def _publish_refused(self, code: str, message: str,
                         status: int = 409) -> None:
        """Report a refused publish, in the same shape as a refused install.

        A form post gets the notice redirect and a fetch gets code and message as JSON
        at 409, so the two refusal routes of the marketplace cannot drift into different
        contracts.
        """
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

    def _extra_hosts_save(self) -> None:
        """The settings form for the guard's extra allowed hosts: the
        host[:port] entries admitted beyond loopback. Stored as typed
        (comma or space separated); the guard re-reads it on every
        request, so an empty save returns to loopback-only at once."""
        settings = self.server.settings  # type: ignore[attr-defined]
        if settings is None:
            self._send_json(503, {"error": "settings are not available"})
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
        if self._is_form_submit():
            self._send_redirect("/settings")
            return
        self._send_json(200, {"key": "extra_allowed_hosts", "value": hosts.strip()})

    # -- the peer-to-peer surface (issue #67) ------------------------------

    def _peer_bearer_token(self) -> str:
        """The channel token from the one transport the peer surface
        accepts: an Authorization: Bearer header. There is no
        query-string form by design (tokens must not land in logs)."""
        header = self.headers.get("Authorization") or ""
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return ""

    def _route_peer_get(self, path: str) -> None:
        """Serve one peer GET, gated for a paired desk rather than a browser session.

        The guard weighs Host, Origin and the pairing token together, and a request
        failing it gets a peer:blocked 403 with the reason. The three read paths —
        /peer/info, a plugin's manifest and its bundle — each check the token again
        before answering, because the guard's token test is also what a desk without a
        token fails. Every read is audited as peer.read, so another desk's access shows
        up in this desk's trail.
        """
        token = self._peer_bearer_token()
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        token_ok = bool(store is not None and token
                        and store.token_valid(token))
        verdict = check_peer_request(
            self.headers.get("Host"), self.headers.get("Origin"),
            self.server.port, token_ok=token_ok)  # type: ignore[attr-defined]
        if not verdict.allowed:
            self._send_json(403, {
                "error": "peer:blocked",
                "message": ("This request did not come from a paired desk: "
                            + verdict.reason)})
            return
        if path == "/peer/info":
            if not self._peer_token_passed(token, token_ok):
                return
            self._audit("peer.read", target="info",
                        detail="a paired desk listed shared plugins")
            self._send_json(200, self._peer_info_payload())
            return
        plugin_id, tail = _peer_plugin_path(path)
        if plugin_id is not None and tail == "manifest":
            if not self._peer_token_passed(token, token_ok):
                return
            self._peer_serve_manifest(plugin_id)
            return
        if plugin_id is not None and tail == "bundle":
            if not self._peer_token_passed(token, token_ok):
                return
            self._peer_serve_bundle(plugin_id)
            return
        self._send_json(404, {"error": "peer:not-found",
                              "message": "No peer path lives at " + path})

    def _peer_token_passed(self, token: str, token_ok: bool) -> bool:
        """403 with the named reason when the token is missing or wrong."""
        if token_ok:
            return True
        if not token:
            self._send_json(403, {
                "error": "peer:token-required",
                "message": "This surface is for paired desks: send the "
                           "channel token as an Authorization: Bearer "
                           "header."})
        else:
            self._send_json(403, {
                "error": "peer:token-unknown",
                "message": "That channel token does not name a paired "
                           "desk here."})
        return False

    def _route_peer_post(self, path: str) -> None:
        """Handle the one peer POST that exists, pairing, and refuse everything else.

        Pairing has no token to present — its code is the gate — so it takes the plain
        Host and Origin guard. Any other peer POST is a 405 explaining that the surface
        reads and pairs and changes nothing else.
        """
        if path == "/peer/pair":
            # The pairing path has no token (its code is the gate), so
            # it takes the plain guard, unchanged.
            verdict = check_request(
                self.headers.get("Host"), self.headers.get("Origin"),
                self.server.port)  # type: ignore[attr-defined]
            if not verdict.allowed:
                self._send_json(403, {
                    "error": "peer:blocked",
                    "message": ("This request did not come from a paired "
                                "desk: " + verdict.reason)})
                return
            self._peer_pair()
            return
        self._send_json(405, {
            "error": "peer:read-only",
            "message": "The peer surface serves reads and one pairing "
                       "path; nothing else changes anything here."})

    def _peer_pair(self) -> None:
        """Another desk submits a pairing code plus its own identity."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._send_json(503, {"error": "peers:unavailable",
                                  "message": "The peer store is not "
                                             "available on this desk."})
            return
        body = self._read_json_body() or {}
        code = str(body.get("code", "")).strip()
        peer_id = str(body.get("peer_id", "")).strip()
        name = str(body.get("name", "")).strip()
        host = str(body.get("host", "")).strip()
        port = body.get("port")
        if not code or not peer_id or not name or not host \
                or not isinstance(port, int):
            self._send_json(400, {
                "error": "pairing:bad-request",
                "message": 'expected {"code", "peer_id", "name", "host",'
                           ' "port"}'})
            return
        try:
            store.exchange_pairing_code(
                code, peer_id=peer_id, name=name,
                base_url=f"{host}:{port}")
        except PeerError as exc:
            self._send_json(403, {"error": exc.code, "message": str(exc)})
            return
        desk = store.desk()
        self._audit("peer.paired", target=peer_id,
                    detail=f"{name} at {host}:{port} redeemed a pairing code")
        self._send_json(200, {"ok": True, "app": "agent-desk",
                              "peer_id": desk["peer_id"],
                              "name": desk["name"]})

    def _peer_shared_plugins(self) -> list[dict]:
        """The shared-plugin list computed live from the runtime: ids the
        user marked shared, installed, with the active version and its
        digest. A shared id that is no longer installed is honestly
        absent, not invented."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if store is None or plugins is None:
            return []
        out = []
        for plugin_id in sorted(store.shared_ids()):
            try:
                record = plugins.record(plugin_id)
            except PluginError:
                continue
            if record.get("state") == "uninstalled" or not record.get("versions"):
                continue
            out.append({
                "id": plugin_id,
                "name": str(record.get("name", plugin_id)),
                "version": str(record.get("active_version", "")),
                "sha256": str(record.get("sha256", "")),
            })
        return out

    def _peer_info_payload(self) -> dict:
        """What this desk tells a paired peer: its identity and the plugins it shares.

        A missing store still yields the same shape with an empty identity, so the
        guard, not the payload, is what refuses an unpaired reader.
        """
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        desk = store.desk() if store is not None else {"peer_id": "",
                                                       "name": ""}
        return {"ok": True, "app": "agent-desk",
                "peer_id": desk["peer_id"], "name": desk["name"],
                "plugins": self._peer_shared_plugins()}

    def _peer_plugin_record(self, plugin_id: str) -> dict | None:
        """The shared, installed record for one plugin id, or None."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if store is None or plugins is None:
            return None
        if plugin_id not in store.shared_ids():
            return None
        try:
            record = plugins.record(plugin_id)
        except PluginError:
            return None
        if record.get("state") == "uninstalled" or not record.get("versions"):
            return None
        return record

    def _peer_serve_manifest(self, plugin_id: str) -> None:
        """Serve one shared plugin's manifest.json.

        An unknown plugin and a manifest that cannot be read answer the same 404,
        because from the other desk both mean there is nothing to install; a successful
        read is audited as peer.read.
        """
        record = self._peer_plugin_record(plugin_id)
        if record is None:
            self._send_json(404, {"error": "peer:unknown-plugin",
                                  "message": f"{plugin_id} is not a shared "
                                             "plugin on this desk."})
            return
        manifest_path = _active_version_dir(record) / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._send_json(404, {"error": "peer:unknown-plugin",
                                  "message": f"{plugin_id}'s manifest could "
                                             "not be read."})
            return
        self._audit("peer.read", target=plugin_id, detail="manifest")
        self._send_json(200, manifest)

    def _peer_serve_bundle(self, plugin_id: str) -> None:
        """Zip one shared plugin's active version and serve it.

        The archive is built in memory from that version directory, with entry names
        relative to it, so the other desk can install exactly the files this desk holds.
        An unknown plugin is a 404 and the transfer is audited as peer.read.
        """
        record = self._peer_plugin_record(plugin_id)
        if record is None:
            self._send_json(404, {"error": "peer:unknown-plugin",
                                  "message": f"{plugin_id} is not a shared "
                                             "plugin on this desk."})
            return
        version_dir = _active_version_dir(record)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for file in sorted(version_dir.rglob("*")):
                if file.is_file():
                    archive.write(file,
                                  file.relative_to(version_dir).as_posix())
        self._audit("peer.read", target=plugin_id, detail="bundle")
        self._send_bytes(200, buffer.getvalue(), "application/zip")

    # -- the peers page and its flows ---------------------------------------

    def _send_peers_page(self, notice: str = "") -> None:
        """Render the peers page, starting discovery first if it never started.

        Discovery is lazy by design: a desk that never opens this page announces
        nothing, so the page rather than the constructor is where announcing begins.
        """
        self.server.ensure_peer_discovery()  # type: ignore[attr-defined]
        page = render_peers_page(
            self._peers_catalog(), agentdesk.__version__, notice=notice,
            inbox_count=self._inbox_waiting_count())
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _peers_catalog(self) -> dict:
        """Everything the peers page and /api/peers show, as data: this
        desk, its live pairing code, discovered desks, and paired peers
        with their shared plugins and the honest reachability state."""
        self.server.ensure_peer_discovery()  # type: ignore[attr-defined]
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            return {"ok": False, "error": "peers:unavailable",
                    "message": "The peer store is not available."}
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        code = store.active_pairing_code()
        discovery = self.server.peer_discovery  # type: ignore[attr-defined]
        subscriptions = {}
        for sub in store.subscriptions():
            subscriptions.setdefault(sub["peer_id"], []).append(sub)
        paired = []
        for peer in store.peers():
            peer_id = peer["peer_id"]
            plugin_rows = []
            for sub in subscriptions.get(peer_id, []):
                record = None
                if plugins is not None:
                    try:
                        record = plugins.record(sub["plugin_id"])
                    except PluginError:
                        record = None
                installed_here = bool(
                    record is not None
                    and record.get("state") != "uninstalled"
                    and record.get("versions"))
                installed_version = (str(record.get("active_version", ""))
                                     if installed_here else None)
                local_sha = (str(record.get("sha256", ""))
                             if installed_here else "")
                plugin_rows.append({
                    "id": sub["plugin_id"],
                    "version": sub["seen_version"],
                    "sha256": sub["seen_sha256"],
                    "installed_here": installed_here,
                    "installed_version": installed_version,
                    # update-available only when the publisher's version
                    # or digest truly differs from what runs here
                    "update_available": bool(
                        installed_here
                        and (installed_version != sub["seen_version"]
                             or local_sha != sub["seen_sha256"])),
                })
            paired.append({
                "peer_id": peer_id,
                "name": peer["name"],
                "base_url": peer["base_url"],
                "state": store.peer_state(peer_id),
                "plugins": plugin_rows,
            })
        return {
            "ok": True,
            "desk": store.desk(),
            "pairingCode": {"code": code["code"],
                            "expires_at": code["expires_at"]}
            if code else None,
            "discovered": discovery.discovered() if discovery else [],
            "discovery_running": bool(discovery and discovery.running()),
            "paired": paired,
        }

    def _peers_redirect(self, message: str) -> None:
        """Send the browser back to the peers page carrying a notice.

        Every peer action posted as a form answers this way, so a client without
        JavaScript sees the outcome as text on the page it came from.
        """
        self._send_redirect(f"/peers?notice={quote(message)}")

    def _peers_refuse(self, code: str, message: str,
                      status: int = 409) -> None:
        """The peers page's own refusals: forms get the notice line,
        JSON callers get the named error."""
        if self._is_form_submit():
            self._peers_redirect(message)
            return
        self._send_json(status, {"error": code, "message": message})

    def _peers_code_generate(self) -> None:
        """Mint a single-use pairing code and tell the user what it is.

        The store gives it a ten-minute life and one redemption; a form post redirects
        with the code in the notice, while a fetch gets the store's own JSON. Both are
        audited, because minting a code is the moment this desk offers another desk
        access.
        """
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        out = store.create_pairing_code()
        self._audit("peer.code", target="pairing-code",
                    detail="a single-use pairing code was generated")
        if self._is_form_submit():
            self._peers_redirect(
                f"Pairing code {out['code']}. Another desk can redeem it "
                "for the next ten minutes; it works once.")
            return
        self._send_json(200, out)

    def _peers_pair(self) -> None:
        """This desk types the other desk's code: submit it, then pin the
        peer identity and the shared channel token."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        body = self._read_json_body() or {}
        typed_address = str(body.get("address", "")).strip()
        code = str(body.get("code", "")).strip()
        if not typed_address or not code:
            self._peers_refuse(
                "peer:bad-request",
                "Type both the other desk's address (host:port) and its "
                "pairing code.", 400)
            return
        address = _normalize_peer_address(typed_address)
        if address is None:
            self._peers_refuse(
                "peer:bad-address",
                f"{typed_address!r} is not a host:port address.", 400)
            return
        desk = store.desk()
        try:
            answer = PeerClient().pair(
                address, code=code, my_peer_id=desk["peer_id"],
                my_name=desk["name"], my_host="127.0.0.1",
                my_port=self.server.port)  # type: ignore[attr-defined]
        except PeerClientError as exc:
            self._peers_refuse(exc.code, str(exc))
            return
        store.add_peer(peer_id=str(answer.get("peer_id", "")),
                       name=str(answer.get("name", "peer")),
                       base_url=address, token=derive_token(code))
        self._audit("peer.pair", target=str(answer.get("peer_id", "")),
                    detail=f"paired with {answer.get('name', '')} at {address}")
        # One honest refresh right away, so the page shows the peer's
        # shares (or the cause it could not be read).
        self._refresh_one_peer(str(answer.get("peer_id", "")))
        if self._is_form_submit():
            self._peers_redirect(
                f"Paired with {answer.get('name', 'the other desk')}.")
            return
        self._send_json(200, {"ok": True, "peer_id": answer.get("peer_id"),
                              "name": answer.get("name")})

    def _refresh_one_peer(self, peer_id: str) -> bool:
        """Fetch one peer's shared-plugin list into the subscription
        snapshot; record the honest outcome either way."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        peer = store.peer(peer_id) if store is not None else None
        if peer is None:
            return False
        token = store.channel_token(peer_id) if store is not None else None
        try:
            info = PeerClient().info(peer["base_url"], token=token or "")
        except PeerClientError as exc:
            store.record_peer_refresh(peer_id, ok=False, cause=str(exc))
            return False
        for plugin in info.get("plugins", []):
            if not isinstance(plugin, dict):
                continue
            store.record_seen(str(plugin.get("id", "")), peer_id,
                              str(plugin.get("version", "")),
                              str(plugin.get("sha256", "")))
        store.record_peer_refresh(peer_id, ok=True, cause="")
        return True

    def _peers_refresh(self) -> None:
        """Ask every paired desk for its current listing, then report how many answered.

        Each peer is refreshed on its own, so one unreachable desk does not stop the
        rest; the notice counts reached against total and, when any failed, points at
        the per-peer causes the page lists.
        """
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        reached = 0
        peers = store.peers()
        for peer in peers:
            if self._refresh_one_peer(peer["peer_id"]):
                reached += 1
        message = (f"Refreshed {reached} of {len(peers)} paired desks.")
        if reached < len(peers):
            message += " The unreachable ones list their cause below."
        self._peers_redirect(message)

    def _peers_install(self) -> None:
        """Install one shared plugin from a paired peer: download the
        bundle, recompute the tree digest against the publisher's, run
        the shared validator through the runtime, and record the peer
        as the source."""
        store, plugins, peer, plugin_id, names_ok = self._peers_flow_args()
        if not names_ok:
            return  # the refusal already went out
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        if peer is None:
            self._peers_refuse("peer:unknown-peer",
                               "No paired desk matches that request.")
            return
        if plugins is None:
            self._peers_refuse("plugins:unavailable",
                               "No plugin runtime is configured.")
            return
        if not plugin_id:
            self._peers_refuse("peer:bad-request",
                               "Which plugin, from which desk?", 400)
            return
        try:
            existing = plugins.record(plugin_id)
            already = bool(existing.get("versions")
                           and existing.get("state") != "uninstalled")
        except PluginError:
            already = False
        if already:
            self._peers_refuse(
                "peer:already-installed",
                f"{plugin_id} is already installed here; use Update to "
                "move to the peer's version.")
            return
        with tempfile.TemporaryDirectory(prefix="agentdesk-peer-") as tmp:
            staged = self._peer_stage(plugins, peer, plugin_id, Path(tmp))
            if staged is None:
                return  # the refusal already went out
            try:
                result = plugins.install(staged["dir"],
                                         source=f"peer:{peer['name']}")
            except PluginError as exc:
                self._audit("peer.install", target=plugin_id,
                            status="error",
                            detail=f"refused by the shared validator: "
                                   f"{exc.code}")
                self._peers_refuse(exc.code, str(exc), exc.status)
                return
        store.record_seen(plugin_id, peer["peer_id"], staged["version"],
                          staged["sha256"])
        store.set_installed(plugin_id, peer["peer_id"], result["version"])
        self._audit("peer.install", target=plugin_id,
                    detail=f"from {peer['name']} v{result['version']} "
                           f"digest {staged['sha256'][:12]} verified")
        if self._is_form_submit():
            self._peers_redirect(
                f"Installed {plugin_id} v{result['version']} from "
                f"{peer['name']}.")
            return
        self._send_json(200, result)

    def _peers_update(self) -> None:
        """One click to the publisher's newer version: same staging and
        verification, then the runtime's own update path (a widened
        permission set still holds for consent)."""
        store, plugins, peer, plugin_id, names_ok = self._peers_flow_args()
        if not names_ok:
            return  # the refusal already went out
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        if peer is None:
            self._peers_refuse("peer:unknown-peer",
                               "No paired desk matches that request.")
            return
        if plugins is None:
            self._peers_refuse("plugins:unavailable",
                               "No plugin runtime is configured.")
            return
        if not plugin_id:
            self._peers_refuse("peer:bad-request",
                               "Which plugin, from which desk?", 400)
            return
        with tempfile.TemporaryDirectory(prefix="agentdesk-peer-") as tmp:
            staged = self._peer_stage(plugins, peer, plugin_id, Path(tmp))
            if staged is None:
                return
            zip_path = Path(tmp) / f"{plugin_id}.zip"
            zip_path.write_bytes(staged["bundle"])
            try:
                result = plugins.update(plugin_id, zip_path)
            except PluginError as exc:
                self._audit("peer.update", target=plugin_id,
                            status="error",
                            detail=f"refused: {exc.code}")
                self._peers_refuse(exc.code, str(exc), exc.status)
                return
        if isinstance(result, dict) and result.get("status") == "pending-consent":
            result = self._hold_update_for_consent(plugins, plugin_id, result)
        if isinstance(result, dict) and result.get("applied"):
            store.record_seen(plugin_id, peer["peer_id"], staged["version"],
                              staged["sha256"])
            store.set_installed(plugin_id, peer["peer_id"],
                                str(result.get("version", "")))
        self._audit("peer.update", target=plugin_id,
                    detail=f"from {peer['name']} to v{staged['version']}")
        if self._is_form_submit():
            if isinstance(result, dict) and result.get("applied"):
                self._peers_redirect(
                    f"Updated {plugin_id} to v{result.get('version', '')} "
                    f"from {peer['name']}.")
            else:
                self._peers_redirect(
                    f"The update to {staged['version']} waits for your OK: "
                    "it asks for more access. Decide it on the inbox.")
            return
        self._send_json(200, result if isinstance(result, dict) else {})

    def _peers_flow_args(self):
        """(store, plugins, peer, plugin_id, names_ok) for the install
        and update flows. ids that are not safe names are refused here,
        before either can name a file (a planted ../id would otherwise
        escape the staging dir) or a store row."""
        body = self._read_json_body() or {}
        peer_id = str(body.get("peer_id", "")).strip()
        plugin_id = str(body.get("plugin_id", "")).strip()
        names_ok = self._peer_flow_names_ok(peer_id, plugin_id)
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        peer = store.peer(peer_id) if store is not None and names_ok else None
        return (store, self.server.plugins, peer, plugin_id, names_ok)  # type: ignore[attr-defined]

    def _peer_flow_names_ok(self, peer_id: str, plugin_id: str) -> bool:
        """Whether the peer and plugin ids of a flow are safe to place in a path.

        An unsafe name is refused with a 400 and a quoted, shortened excerpt rather than
        silently sanitised, so the answer tells the truth about what was rejected. An
        empty name passes: whether one is required is the next check's business, not
        this one's.
        """
        for name, what in ((peer_id, "peer id"), (plugin_id, "plugin id")):
            if name and not _PEER_SAFE_NAME.match(name):
                self._peers_refuse(
                    "peer:unsafe-name",
                    f"The {what} is not a safe name: {name[:40]!r}.", 400)
                return False
        return True

    def _peer_stage(self, plugins: PluginRuntime, peer: dict,
                    plugin_id: str, tmp: Path) -> dict | None:
        """Download, verify and stage one plugin from a peer. Returns the
        staged {dir, bundle, version, sha256}, or None after sending the
        named refusal."""
        token = self.server.peer_store.channel_token(peer["peer_id"])  # type: ignore[attr-defined]
        client = PeerClient()
        try:
            info = client.info(peer["base_url"], token=token or "")
            bundle = client.bundle(peer["base_url"], token=token or "",
                                   plugin_id=plugin_id)
        except PeerClientError as exc:
            self._peers_refuse(exc.code, str(exc))
            return None
        offered = next((p for p in info.get("plugins", [])
                        if isinstance(p, dict)
                        and str(p.get("id", "")) == plugin_id), None)
        if offered is None:
            self._peers_refuse(
                "peer:plugin-not-shared",
                f"{peer['name']} does not share {plugin_id}.")
            return None
        staged_dir = tmp / "plugin"
        staged_dir.mkdir()
        try:
            extract_bundle(bundle, staged_dir)
        except PeerClientError as exc:
            self._peers_refuse(exc.code, str(exc))
            return None
        digest = tree_digest(staged_dir)
        expected = str(offered.get("sha256", ""))
        if not expected:
            # No announced digest means nothing to verify against: a
            # refusal, never a silent skip that the audit row would
            # then call verified.
            self._audit("peer.install", target=plugin_id, status="error",
                        detail=f"{peer['name']} publishes no digest for "
                               f"{plugin_id}; refused")
            self._peers_refuse(
                "peer:digest-unknown",
                f"{peer['name']} publishes no digest for {plugin_id}, so "
                "this desk cannot verify the bundle against anything. "
                "Nothing was installed.")
            return None
        if digest != expected:
            self._audit("peer.install", target=plugin_id, status="error",
                        detail=f"bundle digest {digest[:12]} does not match "
                               f"the published {expected[:12]}; refused")
            self._peers_refuse(
                "peer:digest-mismatch",
                f"The bundle from {peer['name']} does not match the "
                f"digest it publishes ({digest[:12]} vs {expected[:12]}). "
                "Nothing was installed.")
            return None
        return {"dir": staged_dir, "bundle": bundle,
                "version": str(offered.get("version", "")),
                "sha256": digest}

    def _route_wizard(self, method: str, path: str) -> None:
        """The wizard surface: describe, answer, build, preview, approve."""
        wizard = self.server.wizard_store  # type: ignore[attr-defined]
        if wizard is None:
            self._send_json(503, {"error": "the wizard is not available"})
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
        """The compiler's endpoint client, audited: the settings-saved
        endpoint over the startup one. None when nothing is configured
        anywhere, so the deterministic path runs on purpose instead of a
        client that raises on every call; the wizard never blocks on
        the llm."""
        server = self.server  # type: ignore[attr-defined]
        if server.audit_conn is None:
            return WizardCompiler(None)
        settings = server.settings
        if settings is not None and settings.get("llm_base"):
            base, _key, model = effective_llm_config(settings)
            inner, endpoint = settings_chat(settings), base
        elif getattr(server, "llm_defaulted_to_env", False) and not server.llm_endpoint:
            return WizardCompiler(None)
        else:
            inner = server.llm
            endpoint, _key, model = env_config()
        conn = server.audit_conn

        def audited_llm(prompt: str) -> str:
            """The wizard's prompt call, recorded as llm.wizard.

            Endpoint and model are those resolved when the compiler was built, so the
            row names the client that actually answered. A failure records the error
            text and re-raises, leaving the wizard's own error handling intact.
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
        pilot mode. A form post (the no-JS browser) answers with a
        redirect back to the session page, which renders the approved
        screen; a JSON client keeps the 200 install document."""
        wizard = self.server.wizard_store  # type: ignore[attr-defined]
        session = wizard.get(session_id)
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
            if self._is_form_submit():
                # The refusal, honestly rendered: back to the page, which
                # shows the state the session is really in (the approved
                # screen after an approval, the preview and its button
                # otherwise). Nothing installs twice.
                self._send_redirect(f"/wizard/{session_id}")
                return
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
        if self._is_form_submit():
            self._send_redirect(f"/wizard/{session_id}")
            return
        self._send_json(200, {"status": "installed", "pilot": True,
                              "summary": summary, "install": result})

    def _wizard_escalate(self, session_id: str, reason: str) -> None:
        """End a wizard session as escalated and send the user back to its page.

        The session is loaded first, so the escalation is recorded against a real one;
        the redirect lands on the page that reads the new state.
        """
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
            "No corporate endpoint is configured: the wizard asks its "
            "standard questions and builds the same way. Add an endpoint "
            "in Settings for questions tailored to your ask."
        )

    def _send_marketplace_shell(self, status: int = 200) -> None:
        """The SPA shell for a marketplace deep link, when the build exists."""
        index = spa_index_path()
        if index.is_file():
            self._send_bytes(status, index.read_bytes(), "text/html; charset=utf-8")
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

    def _send_redirect(self, location: str) -> None:
        """Redirect with 303, for a form post that has been handled.

        303 is what makes the browser follow with a GET, so a reload repeats the page
        rather than the action.
        """
        self.send_response(303)
        self.send_header("Location", location)
        self._common_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

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

        Content-Length is the body's own length, and every response path — page, JSON,
        file, error — goes through here, so the security headers cannot be forgotten on
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
        left the connection unusable — its body was past the drain cap, or refused
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
    extractor=None,
    reflector=None,
    announce_port: int | None = None,
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
            extractor=extractor,
            reflector=reflector,
            announce_port=announce_port,
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
            llm.breakdown.

            The endpoint is resolved per call with the same settings-over-environment
            order the inner client uses, so the row names what was really hit. The
            failure path records the error text and re-raises, so the caller still sees
            the real exception.
            """
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
        if key_path.exists():
            try:
                key = read_key_file(key_path)
            except ValueError:
                LOG.exception("memory.key exists but is not a valid key")
        return MemoryStore(conn, time.time, key=key, key_path=key_path)
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
        print(f"Nexuus Bot is running: {url}", flush=True)
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
