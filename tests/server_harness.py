"""Shared harness for server tests: boot the real thing on a real port.

The HTTP API is the primary seam, so these tests drive the actual server
over actual sockets: no fakes between the test and the wire. Everything a
test asserts lives on the Booted object; close() must be called (use the
booted fixture) so no listener outlives a test.
"""

import http.client
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sqlite3
import time

from agentdesk.agents.store import AgentRunStore
from agentdesk.assistant import audit as audit_store
from agentdesk.assistant.research_store import ResearchStore
from agentdesk.calendar.watcher import Adapters as CalendarAdapters
from agentdesk.calendar.watcher import CalendarBridge
from agentdesk.capabilities import GATES, CapabilitiesCache
from agentdesk.consents import ConsentStore
from agentdesk.excel.watcher import Adapters as ExcelAdapters
from agentdesk.excel.watcher import ExcelWatch
from agentdesk.inbox.store import InboxStore
from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain
from agentdesk.keys.store import KeysStore
from agentdesk.layout import LayoutStore
from agentdesk.ledger.store import Ledger
from agentdesk.mail.store import MailStore
from agentdesk.memory.store import MemoryStore
from agentdesk.peers.store import PeerStore
from agentdesk.plugins.runtime import PluginRuntime
from agentdesk.probe.core import UNKNOWN, GateResult
from agentdesk.repetition.activity import ActivityLog
from agentdesk.repetition.skills import SkillStore
from agentdesk.server import app as server_app
from agentdesk.settings import SettingsStore
from agentdesk.wizard.core import WizardStore


def _inert_audit():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    audit_store.ensure_schema(conn)
    return conn


def _inert_activity():
    return ActivityLog(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_skills():
    return SkillStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_settings():
    return SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_inbox():
    return InboxStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_memory():
    return MemoryStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_layout():
    return LayoutStore(sqlite3.connect(":memory:", check_same_thread=False))


def _inert_wizard_store():
    return WizardStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_mail_store():
    return MailStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_research_store():
    """The research answer store joins the inert in-memory defaults:
    without this, a boot with no injection falls through to
    create_server's _default_research_store(), which writes the real
    ~/.agent-desk/research.sqlite3."""
    return ResearchStore(sqlite3.connect(":memory:", check_same_thread=False))


def _inert_agents_store():
    """The agent runs store joins the inert in-memory defaults:
    without this, a boot with no injection falls through to
    create_server's _default_agents_store(), which writes the real
    ~/.agent-desk/agents.sqlite3."""
    return AgentRunStore(sqlite3.connect(":memory:", check_same_thread=False))

def _inert_ledger():
    """The action ledger joins the inert in-memory defaults: without this, a
    boot with no injection falls through to create_server's _default_ledger(),
    which writes the real ~/.agent-desk/ledger.sqlite3."""
    return Ledger(":memory:")


def _inert_peer_store():
    return PeerStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_keys_store():
    """The connections store joins the inert in-memory defaults: without
    this, a boot with no injection falls through to create_server's
    _default_keys_store(), which writes the real ~/.agent-desk/keys.sqlite3."""
    return KeysStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_keychain():
    """The keychain joins the inert defaults as the in-memory fake, so no
    boot in the suite touches a real OS keychain (spec 018)."""
    return KeychainSecrets(MemoryKeychain())


def _inert_capabilities_cache():
    return CapabilitiesCache(sqlite3.connect(":memory:", check_same_thread=False), time.time)


def _inert_gate_runners() -> dict:
    """Honest placeholders, not fakes of a pass: a re-test under the
    default harness records UNKNOWN and says no probe ran. Tests that
    exercise a gate inject the real gate function over fakes, like the
    probe tests do, so nothing here ever touches the environment."""
    def runner_for(key: str, number: int, title: str):
        def run() -> GateResult:
            return GateResult(
                key=key, number=number, title=title, status=UNKNOWN,
                evidence=("injected test runner: no probe ran",),
                note="the test harness's placeholder runner",
            )
        return run

    return {key: runner_for(key, number, title) for key, number, title in GATES}


def _inert_excel() -> ExcelWatch:
    """A watch that never polls: tests inject their own when they care."""
    adapters = ExcelAdapters(
        copy_shadow=lambda p: Path(p),
        parse_workbook=lambda p: [],
        clock=time.time,
    )
    return ExcelWatch(sqlite3.connect(":memory:", check_same_thread=False), adapters)


def _inert_calendar() -> CalendarBridge:
    """A bridge that finds no file: the designed empty state."""
    adapters = CalendarAdapters(read_calendar=lambda: None, clock=time.time)
    return CalendarBridge(sqlite3.connect(":memory:", check_same_thread=False), adapters)


def _inert_plugins(root: Path) -> PluginRuntime:
    """A runtime rooted in the boot's own temp folder: create_server now
    builds a real one under the user data directory when none is given,
    so the default here keeps the suite off the real disk. Tests that
    care inject their own."""
    return PluginRuntime(
        plugins_dir=root / "plugins",
        data_dir=root / "plugin-data",
        workspace_dir=root / "workspace",
        now="2026-11-11T16:00:00",
    )


class Booted:
    """A running AgentDeskServer plus small helpers for raw requests.

    Keyword arguments pass straight through to create_server, so tests can
    inject their own excel watch, calendar bridge and picker adapter.
    Without them the server gets inert in-memory watches, so tests never
    touch the real user data directory.
    """

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("excel", _inert_excel())
        kwargs.setdefault("calendar", _inert_calendar())
        kwargs.setdefault("audit_conn", _inert_audit())
        kwargs.setdefault("activity_log", _inert_activity())
        kwargs.setdefault("skill_store", _inert_skills())
        kwargs.setdefault("settings_store", _inert_settings())
        kwargs.setdefault("inbox_store", _inert_inbox())
        kwargs.setdefault("memory_store", _inert_memory())
        # The layout store joins the inert in-memory defaults, so no boot
        # in the suite touches the real ~/.agent-desk/layout.sqlite3.
        kwargs.setdefault("layout_store", _inert_layout())
        # The wizard sessions join the inert in-memory defaults: without
        # this, a boot with no injection falls through to create_server's
        # _default_wizard_store(), which writes the real
        # ~/.agent-desk/wizard.sqlite3. Tests that care inject their own.
        kwargs.setdefault("wizard_store", _inert_wizard_store())
        # The capabilities cache joins the inert in-memory defaults, and
        # the runner set is the placeholder set: no boot in the suite can
        # probe the real environment, even by accident.
        kwargs.setdefault("capabilities_cache", _inert_capabilities_cache())
        kwargs.setdefault("gate_runners", _inert_gate_runners())
        # The mail handled-thread store joins the inert in-memory
        # defaults. The mail watcher itself is never booted here: the
        # toggle defaults to off and create_server constructs a watcher
        # only when it is on, so no boot in the suite polls a folder.
        # Outbox writes (only from tests that accept a reply draft
        # explicitly) land in a tmp folder owned by this boot.
        kwargs.setdefault("mail_store", _inert_mail_store())
        kwargs.setdefault("research_store", _inert_research_store())
        # The agent runs store joins the inert in-memory defaults, so no
        # boot in the suite touches the real ~/.agent-desk/agents.sqlite3.
        kwargs.setdefault("agents_store", _inert_agents_store())
        # The ledger joins the inert defaults for the same reason: a boot
        # with no injection must never create the real ledger.sqlite3.
        kwargs.setdefault("ledger", _inert_ledger())

        # The peer store joins the inert in-memory defaults: without
        # this, a boot with no injection falls through to
        # create_server's _default_peer_store(), which writes the real
        # ~/.agent-desk/peers.sqlite3. Discovery is never started by a
        # boot (only the peers page starts it), so no boot in the suite
        # sends a UDP packet unless its test asks for the peers page.
        kwargs.setdefault("peer_store", _inert_peer_store())
        # The connections store and the keychain join the inert defaults:
        # no boot in the suite creates the real keys.sqlite3 or touches a
        # real OS keychain; tests that care inject their own inspectable
        # fake keychain.
        kwargs.setdefault("keys_store", _inert_keys_store())
        kwargs.setdefault("keychain", _inert_keychain())
        if "outbox_dir" not in kwargs:
            self._outbox_root = tempfile.TemporaryDirectory(prefix="agentdesk-outbox-")
            outbox = Path(self._outbox_root.name) / "outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            kwargs["outbox_dir"] = outbox
        # The consent allows are in-memory and process-lifetime by design;
        # a fresh store per boot is the inert default.
        kwargs.setdefault("consents", ConsentStore())
        # The inert plugin runtime lives in a temp folder owned by this
        # boot and removed in close(), mirroring the in-memory stores.
        # Built only when no runtime was given, so injected ones spare
        # the temp dir entirely.
        if "plugins" not in kwargs:
            self._plugins_root = tempfile.TemporaryDirectory(
                prefix="agentdesk-plugins-")
            kwargs["plugins"] = _inert_plugins(Path(self._plugins_root.name))
        # The registry browsing joins the inert defaults: an empty root
        # is the honest unavailable state, so no boot in the suite reads
        # or installs from a real registry checkout by accident. Tests
        # that care inject their own fixture root.
        kwargs.setdefault("registry_root", "")
        # Same spirit as the inert watches: unless a test says otherwise,
        # no endpoint is configured, so tests never depend on this
        # machine's real AGENTDESK_LLM_BASE.
        kwargs.setdefault("llm_endpoint", "")
        # Template packs the user installs live under AGENTDESK_TEMPLATES.
        # A boot that does not set it gets an empty temp dir, so the suite
        # never lists whatever happens to sit in the real home directory.
        self._decks_root = tempfile.TemporaryDirectory(prefix="agentdesk-decks-")
        self._prev_templates = os.environ.get("AGENTDESK_TEMPLATES")
        if self._prev_templates is None:
            self._templates_root = tempfile.TemporaryDirectory(prefix="agentdesk-templates-")
            os.environ["AGENTDESK_TEMPLATES"] = self._templates_root.name
        self.server = server_app.create_server(port=0, **kwargs)
        self.server.presentation_dir = Path(self._decks_root.name)
        # Memory captures run inline under test, so a request's capture
        # has landed by the time its response is read.
        self.server.memory_capture_runner = lambda job: job()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.port

    def host_header(self) -> dict[str, str]:
        return {"Host": f"127.0.0.1:{self.port}"}

    def request(self, method: str, path: str, headers: dict[str, str] | None = None, body: bytes | None = None):
        """One real HTTP request; returns (status, headers, body)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def post_json(self, path: str, payload: dict | None = None, headers: dict[str, str] | None = None):
        """One real authenticated-shape POST with a JSON body."""
        data = json.dumps(payload or {}).encode("utf-8")
        merged = {"Content-Type": "application/json", "Content-Length": str(len(data))}
        merged.update(headers or {})
        return self.request("POST", path, headers=merged, body=data)

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
        root = getattr(self, "_plugins_root", None)
        if root is not None:
            root.cleanup()
        outbox_root = getattr(self, "_outbox_root", None)
        if outbox_root is not None:
            outbox_root.cleanup()
        decks_root = getattr(self, "_decks_root", None)
        if decks_root is not None:
            decks_root.cleanup()
        templates_root = getattr(self, "_templates_root", None)
        if templates_root is not None:
            templates_root.cleanup()
        if getattr(self, "_prev_templates", None) is None:
            os.environ.pop("AGENTDESK_TEMPLATES", None)
        elif self._prev_templates is not None:
            os.environ["AGENTDESK_TEMPLATES"] = self._prev_templates
