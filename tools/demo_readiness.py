"""Demo readiness: the first ten minutes, walked by a machine (spec 022).

Boots the REAL app in-process on an ephemeral port over a fresh temporary
data folder, with a file-backed stand-in keychain (so a second boot can
read a saved key back) and the local mock model endpoint, then drives it
over HTTP exactly as a browser would: the bootstrap token exchange, the
pages a new user opens, the form a key is saved through, one assistant
turn, a restart, a learned fact, forgetting everything, and the two real
sources. Every check prints one PASS or FAIL line that names what it
expected and what it found; the run ends with `METRIC ready=<passes>` and
exits non-zero when any check failed.

    python tools/demo_readiness.py

Stdlib only, loopback only. Hermetic: it never reads or writes the real
`~/.agent-desk`, never touches the real keychain, and never reaches the
network. The mock's words are canned; the plumbing they ride is the real
one, so a pass means the product does the thing, not that the model is
clever.

The checks are frozen by spec 022: a check may be reworded, never
removed, and a new one is a new number.

Fresh desk (nothing configured yet)
  R01  honest: no sample data, workbook and calendar not connected, and
       the setup object offers sample data while nothing real is on
  R02  the AI source reads not connected
  R03  the setup object lists three steps in order: ai, workbook,
       calendar, each with a title, a reason and an address, none done
  R04  Settings: the key form comes before every on/off switch
  R05  Settings: at most four on/off switches precede the Advanced section
  R06  Settings: never says "none bound"
  R07  Assistant without an AI links to Settings with "Add your AI key",
       and names no job and no environment variable
  R08  asking without an AI is not a server error and the answer the
       post itself returned says why
  R09  Memory: an explanation block of 200+ characters, in plain words
  R10  learning is switched on for a fresh folder
  R11  the rail: every link answers 200, at most eight, none to Peers,
       Activity or Capabilities
  R12  IT-only surfaces: the computer check is linked only from Advanced,
       and no page links to Peers or the marketplace's Publishers, Studio,
       Admin or Trust center

Adding the AI (the form a browser posts)
  R13  a key saved with a model is accepted and the listing carries it
  R14  the desk now reports the AI connected and the ai step done
  R15  Settings agrees: no "not set", no "not configured", the model shown
  R16  the model the connection chose is the model every call sent
  R17  the assistant answers
  R18  a second boot over the same folder still reports connected and
       still answers (the key came back from the keychain)

Memory
  R19  after one turn that states a durable fact, Memory lists it and
       recall carries it
  R20  Memory offers "Forget everything" once a fact exists; after it,
       Memory is empty and recall no longer carries the fact
  R21  the audit export records memory.forget_all

Real sources (files copied outside the sample folder)
  R22  a real workbook completes the workbook step
  R23  a real calendar completes the calendar step, so every step is done

The desk acting by itself (spec 023, tickets 023-3; the numbers 24 and
25 are reserved for the sibling slices, never reassigned)
  R26  a fresh desk acts by itself within 120 seconds of first boot
  R27  the dashboard payload carries what changed (the agent loop's
       stamp), and it advances when the desk acts
  R28  the names the desk says are names the desk holds (the engine's
       reading, and any connect line on a card)
  R29  every action in the engine's first pass has a ledger entry with
       an undo kind, and Undo works on one of them
"""

from __future__ import annotations

import gc
import http.cookiejar
import importlib.util
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

MOCK_KEY = "sk-ready-0001"
MOCK_MODEL = "mock-chat"
MOCK_ANSWER = "The mock endpoint answers a plain prompt with this sentence."
REMEMBERED = "The Acme renewal is due December 15"
STEPS = ("ai", "workbook", "calendar")
# The pages a person can open from the rail; "/" and "/plugins" are the
# client-rendered shell, which plain HTTP cannot read.
RAIL_PAGES = (
    "/inbox", "/assistant", "/agents", "/memory", "/mail", "/settings",
    "/walkthrough/calendar", "/what-this-touches",
)
IT_ONLY_HREFS = (
    "/peers", "/marketplace/admin", "/marketplace/trust",
    "/marketplace/publishers", "/marketplace/studio",
)
RAIL_BANNED_HREFS = ("/peers", "/activity", "/capabilities")
# R24 and R25 belong to the sibling slices (spec 023, tickets 023-1 and
# 023-2); a new check is a new number, so the walk's numbers jump there
# on purpose.
CHECK_COUNT = 27
CHECK_NUMBERS = tuple(range(1, 24)) + (26, 27, 28, 29)
# Every AGENTDESK_* variable the product reads: pinned empty so the walk
# sees a machine with nothing configured.
PINNED_EMPTY = (
    "AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY", "AGENTDESK_LLM_MODEL",
    "AGENTDESK_CALENDAR_FILE", "AGENTDESK_MAIL_FOLDER", "AGENTDESK_REGISTRY",
    "AGENTDESK_MARKETPLACE_ADMIN", "AGENTDESK_TEMPLATES",
)


class ReadinessError(Exception):
    """One step of the walk could not be performed at all."""


def _load_mock():
    """The mock endpoint module, by path (tools is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "agentdesk_mock_endpoint", ROOT / "tools" / "mock_endpoint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FileKeychain:
    """The keyring module's three methods over a JSON file.

    A stand-in for the OS keychain that a second boot can read back, so
    "the key survived a restart" can be checked without ever touching the
    real one.
    """

    def __init__(self, path: Path) -> None:
        """Load whatever an earlier boot stored, or start empty."""
        self.path = Path(path)
        try:
            self.secrets: dict[str, str] = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.secrets = {}

    def _save(self) -> None:
        """Persist the dict; the whole point is surviving a restart."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.secrets), encoding="utf-8")

    def get_password(self, service: str, username: str):
        """The stored secret for the pair, or None when there is none."""
        return self.secrets.get(f"{service}|{username}")

    def set_password(self, service: str, username: str, secret: str) -> None:
        """Store the secret under the pair, replacing any earlier one."""
        self.secrets[f"{service}|{username}"] = secret
        self._save()

    def delete_password(self, service: str, username: str) -> None:
        """Remove the pair's secret; a missing one is a plain no-op."""
        self.secrets.pop(f"{service}|{username}", None)
        self._save()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop at the 3xx so a form post's redirect can be asserted."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Decline the redirect; the caller asserts on the status itself."""
        return None


class Desk:
    """One real server over one data folder, plus a browser-shaped client."""

    def __init__(self, data_dir: Path, keychain_file: Path, announce_port: int):
        """Boot the real app on an ephemeral port over this data folder.

        AGENTDESK_DATA is set process-wide for the boot (the server resolves
        its folder from it) and restored by the walk when it finishes. The
        client carries one cookie jar: an opener that follows redirects the
        way a browser does, and one that stops at the first.
        """
        from agentdesk.keys.secrets import KeychainSecrets
        from agentdesk.server import app as server_app

        os.environ["AGENTDESK_DATA"] = str(data_dir)
        self.server = server_app.create_server(
            port=0, announce_port=announce_port,
            keychain=KeychainSecrets(backend=FileKeychain(keychain_file)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        # The launcher's serve() starts the background polls (the
        # supervised loop included) once bound; the walk mirrors that,
        # so the desk can act by itself the way a real start does.
        server_app.start_background_polls(self.server)
        self.base = f"http://127.0.0.1:{self.server.port}"
        self._jar = http.cookiejar.CookieJar()
        self.follow = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))
        self.direct = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar), _NoRedirect())

    def login(self) -> None:
        """Redeem the bootstrap token the way the launcher's browser does."""
        token = self.server.sessions.bootstrap_token()
        status, _headers, _body = self.get(f"/auth/{token}")
        if status != 200:
            raise ReadinessError(f"the start link answered {status}")

    def _open(self, opener, request, timeout: int = 60):
        """Run one request; an HTTP error status is a result, not a raise."""
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read()

    def get(self, path: str):
        """GET a path with the redirect-following opener."""
        return self._open(self.follow, urllib.request.Request(self.base + path))

    def get_json(self, path: str) -> dict:
        """GET a path that must answer 200 JSON; the decoded body."""
        status, _headers, body = self.get(path)
        if status != 200:
            raise ReadinessError(f"GET {path} answered {status}: {body[:200]!r}")
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as exc:
            raise ReadinessError(f"GET {path} did not answer JSON: {exc}") from exc

    def post_json(self, path: str, payload: dict):
        """POST JSON the way the page scripts do; redirects are followed."""
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method="POST",
            headers={"Content-Type": "application/json"})
        return self._open(self.follow, request)

    def post_form(self, path: str, fields: dict):
        """POST a plain form and stop at its first answer (a 303 usually)."""
        data = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        return self._open(self.direct, request)

    def post_body(self, path: str, body: bytes, content_type: str):
        """POST a raw document (the calendar upload's shape)."""
        request = urllib.request.Request(
            self.base + path, data=body, method="POST",
            headers={"Content-Type": content_type})
        return self._open(self.follow, request)

    def post_engine_tool(self, tool: str, args: dict):
        """POST one tool call to the desk's own engine route with its token.

        The boot-minted token rides the Authorization header, exactly as
        the engine's own calls do; redirects are not followed so a
        refusal is read as a refusal.
        """
        data = json.dumps({"tool": tool, "args": args}).encode("utf-8")
        request = urllib.request.Request(
            self.base + "/api/engine/tools", data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.server.engine_token})
        return self._open(self.direct, request)

    def close(self) -> None:
        """Stop the server, its watchers, its stores and its thread.

        Teardown must never mask a check, so every step is best-effort.
        The stores are closed explicitly because Windows will not delete a
        file a connection still holds, and the walk removes its folder.
        """
        try:
            # The workbook and calendar polls outlive the request that
            # started them; stop both so nothing polls a deleted folder.
            for name in ("excel", "calendar"):
                watcher = getattr(self.server, name, None)
                if watcher is not None:
                    watcher.stop_polling()
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            _close_stores(self.server)
        except Exception:  # noqa: BLE001 - teardown noise is not a finding
            pass


def _close_stores(server) -> None:
    """Close every SQLite connection the server holds, directly or on a store.

    A closed connection is harmless to close again; anything that is not a
    connection is left alone.
    """
    for value in list(vars(server).values()):
        holders = (value, getattr(value, "conn", None))
        for holder in holders:
            if isinstance(holder, sqlite3.Connection):
                try:
                    holder.close()
                except sqlite3.Error:
                    pass


def _remove(folder: Path) -> bool:
    """Delete the walk's folder, retrying while a late thread lets go.

    Returns whether the folder is gone; a folder that stays is reported
    by the caller rather than hidden.
    """
    for _attempt in range(5):
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            return True
        gc.collect()
        time.sleep(0.4)
    return not folder.exists()


class _Elements(HTMLParser):
    """Every element of a page with its attributes and its whole text.

    One tolerant pass: an element's text is everything inside it, script
    and style bodies are skipped, and unclosed markup closes at the end.
    """

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}
    _SKIP = ("script", "style")

    def __init__(self, html: str) -> None:
        """Parse the page into `elements`, innermost first."""
        super().__init__(convert_charrefs=True)
        self.elements: list[dict] = []
        self._open: list[dict] = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        """Open an element, or record a void one at once."""
        element = {"tag": tag, "attrs": dict(attrs), "text": []}
        if tag in self._VOID:
            self.elements.append({**element, "text": ""})
        else:
            self._open.append(element)

    def handle_endtag(self, tag):
        """Close the nearest open element with this tag and its children."""
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index]["tag"] == tag:
                self._close_from(index)
                return

    def handle_data(self, data):
        """Append text to every open element outside script and style."""
        if any(element["tag"] in self._SKIP for element in self._open):
            return
        for element in self._open:
            element["text"].append(data)

    def _close_from(self, start: int) -> None:
        """Record the open elements from `start` as finished, innermost first."""
        for element in reversed(self._open[start:]):
            self.elements.append({**element, "text": _squash(element["text"])})
        del self._open[start:]

    def close(self):
        """Finish the parse, recording whatever markup left open."""
        super().close()
        if self._open:
            self._close_from(0)


def _squash(parts) -> str:
    """The element's text on one line with single spaces."""
    return " ".join("".join(parts).split())


def parse(html: str) -> list[dict]:
    """The page's elements: tag, attrs and whole text, innermost first."""
    return _Elements(html).elements


def element_text(html: str, element_id: str) -> str:
    """The whole text of the element with this id, or '' when absent."""
    for element in parse(html):
        if element["attrs"].get("id") == element_id:
            return element["text"]
    return ""


def switch_state(html: str, key: str) -> str:
    """The On/Off word of the settings switch for `key`, or '' when absent."""
    for element in parse(html):
        if (element["tag"] == "button"
                and element["attrs"].get("data-setting") == key):
            return element["text"].strip()
    return ""


def page_text(html: str) -> str:
    """Everything a reader would hear: the text of the body element."""
    for element in parse(html):
        if element["tag"] == "body":
            return element["text"]
    return _squash(re.sub(r"<[^>]+>", " ", html))


def rail_links(html: str) -> list[str]:
    """The hrefs of the main rail, in order (an empty list when absent)."""
    match = re.search(r'<nav[^>]*aria-label="Main"[^>]*>(.*?)</nav>', html, re.S)
    if match is None:
        return []
    return re.findall(r'<a\s[^>]*href="([^"]*)"', match.group(1))


def link_text_for(html: str, href: str) -> list[str]:
    """The visible text of every link to exactly this href."""
    return [element["text"] for element in parse(html)
            if element["tag"] == "a" and element["attrs"].get("href") == href]


class Report:
    """The check lines, printed as they are decided and counted at the end."""

    def __init__(self) -> None:
        """Start with nothing decided."""
        self.passed = 0

    def check(self, number: int, name: str, ok: bool, detail: str = "") -> None:
        """Print and count one check; a false `ok` is a FAIL with the detail."""
        line = (f"PASS R{number:02d} {name}" if ok
                else f"FAIL R{number:02d} {name}: {detail}")
        if ok:
            self.passed += 1
        # One write, not print's several: the mock endpoint logs from its
        # own request threads, and a whole line cannot interleave with it.
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def run(self, number: int, name: str, probe) -> None:
        """Decide one check from `probe`, which returns (ok, detail).

        A probe that raises is a FAIL naming the error: the walk goes on,
        because a later check may still say something worth hearing.
        """
        try:
            ok, detail = probe()
        except Exception as exc:  # noqa: BLE001 - a crash is a failed check
            ok, detail = False, f"the check could not run ({type(exc).__name__}: {exc})"
        self.check(number, name, ok, detail)


def _steps(dashboard: dict) -> list[dict]:
    """The setup object's steps, or an empty list when there is no object."""
    setup = dashboard.get("setup")
    return list(setup.get("steps") or []) if isinstance(setup, dict) else []


def _source(dashboard: dict, source_id: str) -> dict:
    """One dashboard source's status row, or an empty dict when absent."""
    for item in (dashboard.get("sources") or {}).get("items") or []:
        if item.get("id") == source_id:
            return item
    return {}


def _wait_until(probe, seconds: float = 10.0):
    """Poll `probe` until it returns truthy; its last answer otherwise."""
    deadline = time.monotonic() + seconds
    answer = probe()
    while not answer and time.monotonic() < deadline:
        time.sleep(0.25)
        answer = probe()
    return answer


def _fresh_desk(desk: Desk, report: Report) -> None:
    """R01 to R12: what a new user meets before anything is configured."""
    dashboard = desk.get_json("/api/dashboard")
    setup = dashboard.get("setup")
    report.run(1, "fresh desk is honest", lambda: (
        dashboard.get("sample") is False
        and _source(dashboard, "excel-watch").get("status") == "not_connected"
        and _source(dashboard, "calendar-bridge").get("status") == "not_connected"
        and isinstance(setup, dict) and isinstance(setup.get("sample"), bool)
        and setup.get("sampleOffer") is True,
        f"sample={dashboard.get('sample')!r}, "
        f"workbook={_source(dashboard, 'excel-watch').get('status')!r}, "
        f"calendar={_source(dashboard, 'calendar-bridge').get('status')!r}, "
        f"setup.sampleOffer={(setup or {}).get('sampleOffer') if isinstance(setup, dict) else 'no setup object'}"))
    report.run(2, "the AI reads not connected", lambda: (
        _source(dashboard, "research-endpoint").get("status") == "not_connected",
        f"research-endpoint status={_source(dashboard, 'research-endpoint').get('status')!r}"))

    def three_steps():
        """The setup steps in order, each complete, none done."""
        steps = _steps(dashboard)
        ids = [step.get("id") for step in steps]
        complete = all(
            step.get("title") and step.get("reason") and step.get("href")
            and step.get("done") is False for step in steps)
        return ids == list(STEPS) and complete, f"steps={ids}"
    report.run(3, "three setup steps exist", three_steps)

    # Attribute quotes are normalised to double quotes before the string
    # searches below: the page quotes attributes with single quotes, and a
    # check must read what an attribute says, not how it is quoted.
    settings_html = desk.get("/settings")[2].decode("utf-8").replace("'", '"')
    report.run(4, "Settings opens on the AI", lambda: (
        _before(settings_html)('id="connection-form"', "data-setting="),
        "an on/off switch comes before the key form"))

    def everyday_is_short():
        """At most four switches before the Advanced section."""
        advanced = settings_html.find('id="settings-advanced"')
        if advanced == -1:
            return False, (f"no Advanced section marker; the page has "
                           f"{settings_html.count('data-setting=')} switches in all")
        count = settings_html[:advanced].count('data-setting=')
        return count <= 4, f"{count} switches before Advanced (allowed: 4)"
    report.run(5, "everyday sections are short", everyday_is_short)
    report.run(6, "Settings never says none bound", lambda: (
        "none bound" not in settings_html.lower(),
        "the words 'none bound' appear"))

    assistant_html = desk.get("/assistant")[2].decode("utf-8")
    report.run(7, "assistant without an AI says what to do", lambda: (
        any("add your ai key" in text.lower()
            for text in link_text_for(assistant_html, "/settings#ai"))
        and "unbound" not in page_text(assistant_html).lower()
        and "AGENTDESK_" not in page_text(assistant_html),
        "no link to /settings#ai saying 'Add your AI key', or the page names a job or an environment variable"))

    def asking_is_honest():
        """Asking with no AI is answered, not a server error, and the
        answer the POST itself returned says why (tightened 2026-11-23:
        the page fetched before the post always carries the offer, so it
        proved nothing)."""
        status, _headers, body = desk.post_json(
            "/assistant/ask", {"question": "What changed since yesterday?"})
        said = body.decode("utf-8", "replace").lower()
        return status < 500 and "ai key" in said, f"POST /assistant/ask answered {status}"
    report.run(8, "asking without an AI is honest", asking_is_honest)

    memory_html = desk.get("/memory")[2].decode("utf-8")
    explanation = len(element_text(memory_html, "how-memory-works"))
    # Reworded on 2026-11-23, never removed: the page offers "Forget
    # everything" only once there is a fact to forget (no control that can
    # do nothing), so the form is checked by R20, after a fact exists.
    report.run(9, "memory explains itself", lambda: (
        explanation >= 200,
        f"explanation has {explanation} characters (needed: 200)"))
    report.run(10, "learning is on by default", lambda: (
        switch_state(settings_html, "memory_auto_approve").lower() == "on",
        f"the Learn automatically switch reads {switch_state(settings_html, 'memory_auto_approve')!r}"))

    def rail_is_whole():
        """Every rail link answers, there are few, none to an IT surface."""
        links = rail_links(desk.get("/inbox")[2].decode("utf-8"))
        if not 0 < len(links) <= 8:
            return False, f"{len(links)} rail links: {links}"
        banned = [link for link in links if link in RAIL_BANNED_HREFS]
        if banned:
            return False, f"rail links to {banned}"
        broken = [link for link in links if desk.get(link)[0] != 200]
        return not broken, f"rail links that do not answer 200: {broken}"
    report.run(11, "the rail is short and whole", rail_is_whole)

    def it_only_surfaces_are_not_offered():
        """The computer check sits in Advanced; nothing links the rest."""
        advanced = settings_html.find('id="settings-advanced"')
        computer = settings_html.find('href="/capabilities"')
        if advanced == -1 or (computer != -1 and computer < advanced):
            return False, "the computer check is linked outside the Advanced section"
        for page in RAIL_PAGES:
            html = desk.get(page)[2].decode("utf-8")
            found = [href for href in IT_ONLY_HREFS if f'href="{href}"' in html]
            if found:
                return False, f"{page} links to {found}"
        return True, ""
    report.run(12, "IT-only surfaces are not offered", it_only_surfaces_are_not_offered)


def _before(html: str):
    """A comparator over positions in one page, absent counting as last."""
    length = len(html) + 1

    def position(needle: str) -> int:
        """The needle's position, or one past the end when absent."""
        return html.find(needle) if needle in html else length

    def before(first: str, second: str) -> bool:
        """Whether the first needle appears before the second."""
        return position(first) < position(second)
    return before


def _add_the_ai(desk: Desk, mock, mock_port: int, report: Report) -> None:
    """R13 to R17: save one key, then watch every surface agree."""
    base = f"http://127.0.0.1:{mock_port}/v1"
    fields = {"provider": "custom", "label": "Readiness check",
              "baseUrl": base, "apiKey": MOCK_KEY, "model": MOCK_MODEL}

    def saved_with_model():
        """The form is accepted and the listing carries the model."""
        status, headers, body = desk.post_form("/api/connections", fields)
        if status != 303:
            return False, f"POST /api/connections answered {status}: {body[:160]!r}"
        saved = [connection for connection in
                 desk.get_json("/api/connections").get("connections", [])
                 if connection.get("label") == fields["label"]]
        if not saved:
            # A refused save also answers 303: a redirect carrying the notice.
            return False, f"the save was refused (redirect to {headers.get('Location')})"
        return saved[0].get("model") == MOCK_MODEL, (
            f"the saved connection carries model {saved[0].get('model')!r}")
    report.run(13, "a key is saved with its model", saved_with_model)

    def desk_agrees():
        """The dashboard reports the AI connected and the step done."""
        dashboard = desk.get_json("/api/dashboard")
        done = [step.get("done") for step in _steps(dashboard) if step.get("id") == "ai"]
        return (_source(dashboard, "research-endpoint").get("status") == "connected"
                and done == [True],
                f"research-endpoint status={_source(dashboard, 'research-endpoint').get('status')!r}, "
                f"ai step done={done!r}")
    report.run(14, "the desk reports the AI connected", desk_agrees)

    def settings_agree():
        """The Your AI section shows the model and never says not set."""
        text = element_text(desk.get("/settings")[2].decode("utf-8"), "ai").lower()
        return (("not set" not in text and "not configured" not in text
                 and MOCK_MODEL in text),
                "the Your AI section says not set or not configured, or does not show the model")
    report.run(15, "Settings agrees", settings_agree)

    def asks_and_answers():
        """One assistant turn; its JSON answer when the call went through."""
        return desk.post_json("/assistant/ask", {"question": "What is on my calendar today?"})

    def chosen_model_is_used():
        """Every request carried the chosen model, never the old default."""
        answer = json.loads(asks_and_answers()[2].decode("utf-8"))
        seen = list(mock.SEEN_MODELS)
        return ((answer.get("status") == "ok" and bool(seen) and seen[-1] == MOCK_MODEL
                 and "gpt-4o-mini" not in seen),
                f"the mock was sent {seen}")
    report.run(16, "the chosen model is the model used", chosen_model_is_used)
    report.run(17, "the assistant answers", lambda: (
        MOCK_ANSWER in json.loads(asks_and_answers()[2].decode("utf-8")).get("reply", ""),
        "the assistant did not answer with the mock's sentence"))


def _survives_restart(desk: Desk, report: Report) -> None:
    """R18: a second boot over the same folder reads the key back."""
    def still_connected():
        """Connected after the restart, and still answering."""
        dashboard = desk.get_json("/api/dashboard")
        answer = json.loads(desk.post_json(
            "/assistant/ask", {"question": "Still there?"})[2].decode("utf-8"))
        return ((_source(dashboard, "research-endpoint").get("status") == "connected"
                 and answer.get("status") == "ok"),
                f"status={_source(dashboard, 'research-endpoint').get('status')!r}, "
                f"answer={answer.get('status')!r}")
    report.run(18, "the AI survives a restart", still_connected)


def _learns(desk: Desk, report: Report) -> None:
    """R19: one turn states a fact; Memory lists it and recall carries it."""
    def recall_page():
        """The Memory page rendered for a recall of the fact's subject."""
        _status, _headers, body = desk.post_json("/memory/recall", {"query": "Acme renewal"})
        return body.decode("utf-8")

    def learned():
        """The fact is stored by itself and recall finds it."""
        status, _headers, _body = desk.post_json(
            "/assistant/ask", {"question": f"Remember this: {REMEMBERED}"})
        listed = _wait_until(lambda: REMEMBERED in page_text(
            desk.get("/memory")[2].decode("utf-8")))
        recalled = _wait_until(lambda: REMEMBERED in recall_page())
        return (status == 200 and bool(listed) and bool(recalled),
                f"ask answered {status}; listed on the Memory page: {bool(listed)}; recalled: {bool(recalled)}")
    report.run(19, "learning happens by itself", learned)


def _forgets(desk: Desk, report: Report) -> None:
    """R20 and R21: the page offers the form; forget everything; nothing is left."""
    def nothing_left():
        """The form is offered, the two posts a person makes, then an empty Memory."""
        offered = 'action="/memory/forget-all"' in desk.get("/memory")[2].decode("utf-8")
        first = desk.post_form("/memory/forget-all", {})
        if first[0] == 200:
            second = desk.post_form("/memory/forget-all", {"confirm": "yes"})
        else:
            second = first
        memory = page_text(desk.get("/memory")[2].decode("utf-8"))
        _status, _headers, body = desk.post_json("/memory/recall", {"query": "Acme renewal"})
        return ((offered and second[0] in (200, 303) and REMEMBERED not in memory
                 and REMEMBERED not in body.decode("utf-8")
                 and re.search(r"\b0 facts\b", memory) is not None),
                f"forget-all form {'offered' if offered else 'absent'}; "
                f"posts answered {first[0]} then {second[0]}; the fact is "
                f"{'still' if REMEMBERED in memory else 'no longer'} on the Memory page")
    report.run(20, "forget everything works", nothing_left)
    report.run(21, "forgetting is recorded", lambda: (
        "memory.forget_all" in desk.get("/audit/export.csv")[2].decode("utf-8"),
        "the audit export has no memory.forget_all row"))


def _real_sources(desk: Desk, folder: Path, data_dir: Path, report: Report) -> None:
    """R22 and R23: a workbook and a calendar from outside the sample folder."""
    real = folder / "real"
    real.mkdir()
    desk.post_json("/settings/toggle", {"key": "sample_data"})
    sample = data_dir / "sample"
    made = _wait_until(lambda: (sample / "sample-sales.xlsx").exists()
                       and (sample / "sample-calendar.json").exists())
    if not made:
        report.check(22, "a real workbook completes its step", False, "the sample fixtures were never written")
        report.check(23, "all three steps complete", False, "the sample fixtures were never written")
        return
    shutil.copy(sample / "sample-sales.xlsx", real / "pipeline.xlsx")
    shutil.copy(sample / "sample-calendar.json", real / "calendar.json")
    desk.post_json("/settings/toggle", {"key": "sample_data"})

    def step_done(step_id: str) -> bool:
        """Whether the dashboard now reports this setup step done."""
        return any(step.get("id") == step_id and step.get("done") is True
                   for step in _steps(desk.get_json("/api/dashboard")))

    def workbook_step():
        """Register the copy and wait for the step to be done."""
        status, _headers, body = desk.post_json(
            "/sources/excel-watch", {"path": str(real / "pipeline.xlsx")})
        done = _wait_until(lambda: step_done("workbook"))
        return status == 200 and done, f"register answered {status}: {body[:120]!r}; step done: {done}"
    report.run(22, "a real workbook completes its step", workbook_step)

    def calendar_step():
        """Upload the copy and wait for every step to be done."""
        status, _headers, body = desk.post_body(
            "/sources/calendar-bridge/upload",
            (real / "calendar.json").read_bytes(), "application/json")
        every = _wait_until(lambda: all(step_done(step) for step in STEPS))
        return status == 200 and every, f"upload answered {status}: {body[:120]!r}; all done: {every}"
    report.run(23, "all three steps complete", calendar_step)


def _free_udp_port() -> int:
    """A loopback UDP port that is free right now (probed, not reserved)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# -- the desk acting by itself (spec 023, R26 to R29) -----------------------


def _loop_stamp(desk: Desk) -> dict:
    """The dashboard's agent loop stamp, or an empty dict."""
    stamp = desk.get_json("/api/dashboard").get("agentLoop")
    return stamp if isinstance(stamp, dict) else {}


def _collect_first_boot_activity(desk: Desk) -> tuple[bool, str]:
    """R26's evidence: what the desk did by itself, within 120 seconds.

    The supervised loop's startup desk check is the desk's own first
    act; the walk waits for its stamp on the dashboard and its row in
    the audit export, both things a person can look at.
    """
    deadline = time.monotonic() + 120.0
    stamp: dict = {}
    while time.monotonic() < deadline:
        stamp = _loop_stamp(desk)
        if isinstance(stamp.get("lastRunTs"), (int, float)):
            break
        time.sleep(0.5)
    if not isinstance(stamp.get("lastRunTs"), (int, float)):
        return False, "no agent loop stamp appeared on the dashboard in 120 seconds"
    export = desk.get("/audit/export.csv")[2].decode("utf-8")
    if "agentloop.pass" not in export:
        return False, ("the dashboard carries the stamp but the audit export "
                       "has no agentloop.pass row")
    return True, f"the desk ran its first pass by itself (stamp {stamp.get('lastRunTs')})"


def _run_now(desk: Desk, seconds: float = 30.0) -> tuple[bool, int]:
    """Click Run now until the loop accepts it, waiting out a running pass.

    The answer is the final status: 200 means a pass was started, any
    other status is a refusal the caller reports.
    """
    deadline = time.monotonic() + seconds
    status = 0
    while time.monotonic() < deadline:
        status, _headers, _body = desk.post_json("/api/agent-loop/run", {})
        if status == 200:
            return True, status
        if status != 409:
            return False, status
        time.sleep(0.25)
    return False, status


def _stamp_advanced(desk: Desk, before) -> bool:
    """Whether the dashboard's stamp now carries a run newer than before."""
    value = _loop_stamp(desk).get("lastRunTs")
    if not isinstance(value, (int, float)):
        return False
    if isinstance(before, (int, float)):
        return value != before
    return True


def _stamp_carries_what_changed(desk: Desk) -> tuple[bool, str]:
    """R27: the payload carries the loop's stamp, and it advances when the desk acts.

    The poll hook's HTTP contract: a screen that re-fetches can see the
    desk's own activity change in the payload it already reads. The
    stamp need not exist before the click: the first full pass after a
    restart writes it, so the check waits for None to become a number
    or for a number to advance.
    """
    before = _loop_stamp(desk).get("lastRunTs")
    accepted, status = _run_now(desk)
    if not accepted:
        return False, f"Run now answered {status}; stamp stayed {before!r}"
    advanced = _wait_until(lambda: _stamp_advanced(desk, before), seconds=30.0)
    after = _loop_stamp(desk).get("lastRunTs")
    return bool(advanced), f"Run now answered 200; stamp {before!r} -> {after!r}"


def _connect_lines_name_held(desk: Desk, held: set[str]) -> tuple[bool, str]:
    """Whether any connect line on the dashboard names only held names.

    The invariant behind R28: a card may say "Also in your desk" only
    about a name the desk holds. A desk with no cards (and no such
    line) has nothing claimed and passes honestly.
    """
    cards = ((desk.get_json("/api/dashboard").get("plugins") or {})
             .get("cards") or [])
    held_lower = {name.lower() for name in held}
    for card in cards:
        payload = card.get("payload") if isinstance(card, dict) else None
        insight = payload.get("insight") if isinstance(payload, dict) else None
        if not isinstance(insight, dict):
            continue
        blocks = insight.get("blocks") or []
        lines = [str(insight.get("note") or "")]
        lines += [str(block.get("text") or "") for block in blocks
                  if isinstance(block, dict)]
        for line in lines:
            if not line.startswith("Also in your desk:"):
                continue
            for clause in line.split(":", 1)[1].split(";"):
                name = clause.split(",")[0].strip().rstrip(".").lower()
                if name and name not in held_lower:
                    return False, f"a card names {name!r}, which the desk does not hold"
    return True, (f"{len(cards)} card(s), none claims an unheld name"
                  if cards else "no card claims a connection")


def _auto_approve_on(desk: Desk) -> tuple[bool, str]:
    """Turn automatic saving on through the page's own switch, unless it is on."""
    def auto_approve() -> bool:
        """Whether the desk currently saves learned facts automatically."""
        capture = desk.get_json("/api/memory/loop").get("capture") or {}
        return bool(capture.get("autoApprove"))

    if auto_approve():
        return True, "already on"
    status, _headers, _body = desk.post_json(
        "/settings/toggle", {"key": "memory_auto_approve"})
    now = auto_approve()
    return (status == 200 and now,
            f"toggle answered {status}; autoApprove {now!r}")


def _engine_held_names(desk: Desk) -> tuple[int, list[str]]:
    """The desk_names tool's memory names and the status it answered."""
    status, _headers, body = desk.post_engine_tool("desk_names", {})
    if status != 200:
        return status, []
    names = json.loads(body.decode("utf-8")).get("names") or {}
    return status, [str(row.get("name") or "") for row in names.get("memory") or []]


def _names_are_held(desk: Desk) -> tuple[bool, str]:
    """R28: the engine's reading carries exactly the names the desk holds.

    The seed is an organisation the desk's own entity miner types as
    org, because the engine's reading is the dashboard's org and person
    names. The reading is polled, so a store that finishes its write a
    moment after the response is not read as a missing name.
    """
    approve_ok, approve_detail = _auto_approve_on(desk)
    if not approve_ok:
        return False, f"automatic saving could not be turned on: {approve_detail}"
    seeded = desk.post_json("/memory/add", {
        "text": "The Halvorsen Freight Group renewal is settled for this quarter."})
    if seeded[0] not in (200, 201):
        return False, f"saving the named fact answered {seeded[0]}: {seeded[2][:120]!r}"

    def name_held() -> bool:
        """Whether the desk_names tool now reads the seeded organisation."""
        status, held = _engine_held_names(desk)
        return status == 200 and "Halvorsen Freight Group" in held

    appeared = _wait_until(name_held, seconds=15.0)
    status, held = _engine_held_names(desk)
    if status != 200:
        return False, f"the desk_names tool answered {status}"
    if not appeared:
        return False, (f"the desk's own reading misses the saved name after "
                       f"15 seconds: {held!r}")
    if "Quiebro Nova" in held:
        return False, "the desk's reading names something it does not hold"
    lines_ok, lines_detail = _connect_lines_name_held(desk, set(held))
    return lines_ok, f"the reading holds {held}; {lines_detail}"


def _fact_listed(desk: Desk, fact: str) -> bool:
    """Whether the Memory page or recall shows this exact saved fact."""
    if fact in page_text(desk.get("/memory")[2].decode("utf-8")):
        return True
    status, _headers, body = desk.post_json(
        "/memory/recall", {"query": "Acme renewal"})
    return status == 200 and fact in body.decode("utf-8")


def _pass_pays_the_toll(desk: Desk) -> tuple[bool, str]:
    """R29: the pass's every entry carries an undo kind, and Undo works on one.

    The walk saves a dated fact first. The save path runs the same
    recommendation builder the pass's recommend step runs, so the card's
    entry can land during the save; the window starts before the seed so
    that action and anything the pass adds are both counted. Then Run
    now, wait for the stamp, and undo the newest through Activity.
    """
    due = datetime.now().date() + timedelta(days=10)
    fact = f"The Acme renewal is due {due.strftime('%B')} {due.day}"
    started = time.time()
    saved = desk.post_json("/memory/add", {"text": fact})
    if saved[0] not in (200, 201):
        return False, f"saving the dated fact answered {saved[0]}: {saved[2][:120]!r}"
    listed = _wait_until(lambda: _fact_listed(desk, fact), seconds=15.0)
    if not listed:
        return False, "the seeded dated fact never appeared in memory"
    before = _loop_stamp(desk).get("lastRunTs")
    accepted, status = _run_now(desk)
    if not accepted:
        return False, f"Run now answered {status} after the seeded fact was saved"
    finished = _wait_until(lambda: _stamp_advanced(desk, before), seconds=30.0)
    entries = desk.get_json("/api/ledger?limit=50").get("entries") or []
    window = [row for row in entries if row.get("ts", 0) >= started]
    if not finished or not window:
        why = "did not finish" if not finished else "recorded no ledger entry"
        return False, f"the seed and pass {why} in their window ({len(entries)} recent entries)"
    held_back = [row["id"] for row in window if not row.get("undoable")]
    if held_back:
        return False, f"{len(held_back)} entry(ies) in the pass window lack an undo kind"
    target = window[0]
    undo = desk.post_json("/api/ledger/undo", {"id": target["id"]})
    if undo[0] != 200:
        return False, f"undoing {target['action']} answered {undo[0]}: {undo[2][:120]!r}"
    after = {row["id"]: row for row in
             desk.get_json("/api/ledger?limit=50").get("entries") or []}
    undone = after.get(target["id"]) or {}
    if not undone.get("undoneBy"):
        return False, f"the undone entry {target['id']} does not say who undid it"
    return True, (f"the pass's {len(window)} entry(ies) all carry an undo kind; "
                  f"undo of {target['action']} worked")


def _the_desk_acting(desk: Desk, report: Report, first_boot: tuple[bool, str]) -> None:
    """R26 to R29: what the desk does by itself, all of it visible and undoable."""
    report.run(26, "a fresh desk acts by itself", lambda: first_boot)
    report.run(27, "the dashboard carries what changed",
               lambda: _stamp_carries_what_changed(desk))
    report.run(28, "names the desk says are held", lambda: _names_are_held(desk))
    report.run(29, "the engine's first pass pays the ledger toll",
               lambda: _pass_pays_the_toll(desk))


def walk() -> Report:
    """Boot everything the walk needs, run R01 to R23 and R26 to R29, and tear it down.

    The environment is pinned for the walk and restored after it: the data
    folder variable the server resolves, and every other AGENTDESK_*
    variable the product reads. The mock and both servers are stopped in
    the finally block, so a failed check never leaks a thread or a port.
    R26's evidence is collected on the first boot (a fresh desk's own
    first act) and its verdict prints with the others, in order.
    """
    mock = _load_mock()
    mock_server = ThreadingHTTPServer(("127.0.0.1", 0), mock.MockEndpointHandler)
    mock_port = mock_server.server_address[1]
    mock.SEEN_MODELS.clear()
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    saved = {name: os.environ.get(name) for name in ("AGENTDESK_DATA",) + PINNED_EMPTY}
    folder = Path(tempfile.mkdtemp(prefix="agentdesk-ready-"))
    report = Report()
    try:
        for name in PINNED_EMPTY:
            os.environ[name] = ""
        data_dir = folder / "data"
        data_dir.mkdir()
        keychain = folder / "ready-keychain.json"
        desk = Desk(data_dir, keychain, _free_udp_port())
        try:
            desk.login()
            _fresh_desk(desk, report)
            _add_the_ai(desk, mock, mock_port, report)
            first_boot = _collect_first_boot_activity(desk)
        finally:
            desk.close()
        desk = Desk(data_dir, keychain, _free_udp_port())
        try:
            desk.login()
            _survives_restart(desk, report)
            _learns(desk, report)
            _forgets(desk, report)
            _real_sources(desk, folder, data_dir, report)
            _the_desk_acting(desk, report, first_boot)
        finally:
            desk.close()
    finally:
        mock_server.shutdown()
        mock_server.server_close()
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if not _remove(folder):
            print(f"NOTE the temporary folder could not be removed: {folder}", flush=True)
    return report


def main() -> int:
    """Run the walk, print the metric, and exit 0 only when all passed."""
    report = walk()
    print(f"METRIC ready={report.passed}", flush=True)
    return 0 if report.passed == CHECK_COUNT else 1


if __name__ == "__main__":
    sys.exit(main())
