"""The full user walkthrough (ticket #69): one scripted demo, real servers.

Boots two REAL AgentDesk servers over fresh temp data dirs on ephemeral
ports (Desk A for the whole story, Desk B for the peer-to-peer part) and
drives them over real HTTP exactly as a user's browser would: the
bootstrap token exchange, every rail page, the sample-data switch and
every inbox card action, the strict endpoint save and the honest
Test-connection cause, the wizard's create-from-English with no
endpoint, publish to a temp registry, a pinned install of a shipped
plugin from this checkout, the workbook connection that turns an amber
card into bound values, pairing plus sharing plus the one-click peer
update, and dashboard customization. Each step prints one PASS/FAIL
line; any failure exits non-zero with every server it started stopped
in the finally block.

Run it on a clean checkout: python tools/demo_walkthrough.py
Stdlib only. Hermetic: it never touches the real ~/.agent-desk.
"""
import http.cookiejar
import http.server
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CANONICAL = "Watch this workbook and show me the 24-hour change"
BUILTINS = ["sales", "commitments", "research", "skills"]
SAMPLE_CARD_IDS = (
    "sample-update",
    "sample-brief",
    "sample-feature-request",
    "sample-update-consent",
)
# (path, the h1 the rail page must answer with)
RAIL_PAGES = (
    ("/", None),  # the SPA shell when the build is committed; h1 otherwise
    ("/inbox", "Inbox"),
    ("/assistant", "Assistant"),
    ("/activity", "Activity"),
    ("/memory", "Memory"),
    ("/mail", "Mail"),
    ("/capabilities", "Capabilities"),
    # The legacy plugins address now 302s to the marketplace's installed
    # surface (the SPA owns it), so like "/" it answers with the shell.
    ("/plugins", None),
    ("/peers", "Peers"),
    ("/settings", "Settings"),
)


class WalkthroughError(Exception):
    """One failed check, with the plain-language reason."""


def check(condition, message: str) -> None:
    """Raise WalkthroughError carrying the message unless the condition holds.

    The message becomes the reason on the step's FAIL line, so it should
    name both the expected value and the observed one.
    """
    if not condition:
        raise WalkthroughError(message)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stops at the 303 so the walkthrough can assert the redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Decline the redirect so the caller can assert on the 303 itself."""
        return None


class _LoginStubHandler(http.server.BaseHTTPRequestHandler):
    """Answers any request with an HTML login page: the connection
    check's worst real-world shape (an SSO front door, not an API)."""

    def _page(self) -> None:
        """Answer with the HTML page an SSO front door returns."""
        body = b"<html><body><h1>Sign in to continue</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server contract)
        """The model-list GET a connection Test makes sees the page too."""
        self._page()

    def do_POST(self) -> None:  # noqa: N802 (http.server contract)
        """Answer any POST with the page as well; the body is discarded.

        The request body is read and discarded: the stub cares about the shape
        of the answer, not the question.
        """
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self._page()

    def log_message(self, format, *args) -> None:  # noqa: A002
        """Discard the stub's request log line so step output stays readable."""
        pass


class LoginStub:
    def __init__(self) -> None:
        """Start the HTML-only stub on an ephemeral loopback port.

        base_url already carries the version suffix, so it can be saved as
        a connection's base URL exactly as a user would type a base.
        """
        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), _LoginStubHandler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop the stub server and wait up to five seconds for its thread."""
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _free_udp_port() -> int:
    """Return a loopback UDP port that is free right now.

    The socket is closed before the number is returned, so the port is
    probed rather than reserved: another process may take it before the
    announcement uses it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Desk:

    """One real server over its own temp data dir, plus the browser-
    shaped client (a cookie jar that follows redirects, and a no-redirect
    opener for asserting the 303s the forms answer with)."""

    def __init__(self, name: str, data_dir: Path, announce_port: int,
                 pick_workbook=None):
        """Boot one real server on an ephemeral port over a temp data dir.

        AGENTDESK_DATA is set process-wide so the server resolves this data
        dir, and it is not restored here: a second Desk overwrites it for the
        process. Both openers share one cookie jar, so follow chases redirects
        like a browser while direct stops at the first one. pick_workbook
        stands in for the native file dialog, which cannot open headless.
        """
        from agentdesk.server import app as server_app

        os.environ["AGENTDESK_DATA"] = str(data_dir)
        self.name = name
        self.data_dir = data_dir
        self.server = server_app.create_server(port=0, announce_port=announce_port,
                                               pick_workbook=pick_workbook)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.port}"
        # One jar for both openers: the no-redirect one still carries the
        # session cookie, exactly like a browser that merely declines to
        # follow one specific redirect.
        self._jar = http.cookiejar.CookieJar()
        self.follow = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))
        self.direct = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar), _NoRedirect())

    # -- the session bootstrap, exactly as the launcher drives it ------

    def exchange(self) -> None:
        """Drive the bootstrap token exchange and assert the 303 and the cookie.

        The same token is used twice: once through the no-redirect opener, to
        read the 303 and its Set-Cookie, and once through the following
        opener, which is the path a browser takes.
        """
        token = self.server.sessions.bootstrap_token()
        status, headers, _body = self.raw_get(f"/auth/{token}", {})
        check(status == 303, f"/auth/<token> answered {status}, expected 303")
        check(headers.get("Location") == "/", "the auth exchange must land on /")
        check("agentdesk_session=" in (headers.get("Set-Cookie") or ""),
              "the auth exchange must set the session cookie")
        # The same token again with the cookie-following opener: the
        # browser's actual path (the token stays valid for the lifetime).
        request = urllib.request.Request(f"{self.base}/auth/{token}")
        status, _headers, _body = self._open(self.follow, request)
        check(status == 200, "the followed exchange must land on /")

    # -- request helpers -----------------------------------------------

    def _open(self, opener, request, timeout: int = 60):
        """Run one request and return the status, headers and body.

        An HTTP error status is a result, not an exception, so a step can
        assert on a 4xx payload the same way it asserts on a 200.
        """
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read()

    def get(self, path: str):
        """GET a path with the redirect-following opener.

        Returns the status, headers and body; the session cookie rides along
        from the shared jar.
        """
        request = urllib.request.Request(self.base + path)
        return self._open(self.follow, request)

    def get_json(self, path: str) -> dict:
        """GET a path that must answer 200 JSON and return the decoded body.

        Raises WalkthroughError naming the path, the status and a prefix of the
        body when either half is wrong.
        """
        status, _headers, body = self.get(path)
        check(status == 200, f"GET {path} answered {status}: {body[:200]!r}")
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as exc:
            raise WalkthroughError(f"GET {path} did not answer JSON: {exc}") from exc

    def post_json(self, path: str, payload: dict):
        """POST a JSON payload and return the status, headers and body.

        A refusal comes back like any other answer, so the caller can assert on
        a 400 the way it asserts on a 200.
        """
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method="POST",
            headers={"Content-Type": "application/json"})
        return self._open(self.follow, request)

    def post_json_ok(self, path: str, payload: dict) -> dict:
        """POST a JSON payload that must answer 200 and return the decoded body.

        Raises WalkthroughError naming the path, the status and a prefix of the
        body on any other answer.
        """
        status, _headers, body = self.post_json(path, payload)
        check(status == 200, f"POST {path} answered {status}: {body[:300]!r}")
        return json.loads(body.decode("utf-8"))

    def post_form(self, path: str, fields: dict):
        """A browser-shaped form post; returns the 303 it stopped at."""
        data = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        status, headers, body = self._open(self.direct, request)
        check(status == 303,
              f"form POST {path} answered {status}, expected a 303 "
              f"(Location {headers.get('Location')}, body {body[:200]!r})")
        return headers.get("Location", "")

    def raw_get(self, path: str, headers: dict):
        """One raw GET (the peer endpoint's token-gated shape)."""
        request = urllib.request.Request(self.base + path, headers=headers)
        return self._open(self.direct, request)

    # -- teardown -------------------------------------------------------

    def close(self) -> None:
        """Stop the server and its thread, swallowing every teardown error.

        Teardown runs in a finally block, so a raise here would mask the check
        that actually failed.
        """
        try:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
        except Exception:  # noqa: BLE001 - teardown must never mask a failure
            pass


class Walkthrough:
    """Runs the named steps in order, one PASS/FAIL line each."""

    def __init__(self) -> None:
        """Start an empty run: no desks, no temp root, and the ids the steps share.

        a, b and root stay None until the boot steps fill them. The wizard and
        plugin ids are set by the step that installs them and read by every
        later peer step.
        """
        self.results: list[tuple[str, bool, str]] = []
        self.desks: list[Desk] = []
        self.a: Desk | None = None
        self.b: Desk | None = None
        self.root: Path | None = None
        self.wizard_id = ""
        self.excel_plugin = "excel-report"

    def run_step(self, name: str, fn) -> None:
        """Run one step and print and record its single PASS/FAIL line.

        Any exception is recorded as a failure and re-raised as a
        WalkthroughError afterwards, so the run stops at the first failing
        step. The elapsed time is monotonic and reported, never asserted.
        """
        started = time.monotonic()
        try:
            fn()
        except WalkthroughError as exc:
            self.results.append((name, False, str(exc)))
            print(f"FAIL  {name}: {exc}")
            raise
        except Exception as exc:  # noqa: BLE001 - any surprise is a failure
            self.results.append((name, False, f"{type(exc).__name__}: {exc}"))
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
            raise WalkthroughError(str(exc)) from exc
        seconds = time.monotonic() - started
        self.results.append((name, True, ""))
        print(f"PASS  {name}  ({seconds:.1f}s)")

    # -- the steps ------------------------------------------------------

    def step_boot(self) -> None:
        """Boot Desk A and check the fresh dashboard, layout order and empty inbox."""
        # The picker stands in for the native file dialog (it opens on
        # the server, so a headless script injects the choice): it hands
        # back the seeded sample workbook, the demo's stand-in for "the
        # user's real file".
        sample = self.root / "desk-a" / "sample" / "sample-sales.xlsx"
        desk = Desk("A", self.root / "desk-a", _free_udp_port(),
                    pick_workbook=lambda: str(sample))
        self.desks.append(desk)
        self.a = desk
        desk.exchange()
        payload = desk.get_json("/api/dashboard")
        for key in ("version", "flags", "sources", "sales", "commitments",
                    "research", "inbox", "skills", "layout", "plugins"):
            check(key in payload, f"the dashboard payload is missing {key!r}")
        keys = [card["key"] for card in payload["layout"]["cards"]]
        check(keys == BUILTINS,
              f"the default layout order is {keys}, expected {BUILTINS}")
        check(payload["plugins"]["cards"] == [],
              "a fresh desk must render no plugin cards")
        check(payload["inbox"]["waiting"] == 0,
              "a fresh desk must have an empty inbox")

    def step_rail(self) -> None:
        """Check every rail page answers 200 with the heading it must carry.

        The entries with no expected heading accept the SPA shell instead,
        because the committed build owns those surfaces.
        """
        desk = self.a
        for path, h1 in RAIL_PAGES:
            status, _headers, body = desk.get(path)
            check(status == 200, f"{path} answered {status}")
            text = body.decode("utf-8", "replace")
            if h1 is not None:
                check(f"<h1>{h1}</h1>" in text,
                      f"{path} must carry the heading <h1>{h1}</h1>")
            else:
                check('id="root"' in text or "<h1>" in text,
                      "/ must answer with the SPA shell or the rendered dashboard")

    def step_wizard_start_form(self) -> None:
        """Check /wizard serves the describe box and posts to /wizard/new/answer."""
        status, _headers, body = self.a.get("/wizard")
        check(status == 200, f"GET /wizard answered {status}")
        page = body.decode("utf-8")
        check("Describe a plugin" in page, "the wizard start form is missing")
        check("<textarea" in page, "the describe box is missing")
        check('action="/wizard/new/answer"' in page,
              "the start form must post to /wizard/new/answer")

    def step_sample_data_on(self) -> None:
        """Check the sample-data switch flips, seeds the labelled cards and the workbook.

        The switch must read as off on a fresh desk, stick after the toggle,
        and the sample workbook must exist on disk afterwards.
        """
        desk = self.a
        values = desk.get_json("/widgets/settings")
        check(values.get("sample_data") is False,
              "sample data must be off on a fresh desk")
        out = desk.post_json_ok("/settings/toggle", {"key": "sample_data"})
        check(out == {"key": "sample_data", "value": True},
              f"the toggle answered {out}")
        values = desk.get_json("/widgets/settings")
        check(values.get("sample_data") is True, "the switch did not stick")
        status, _headers, body = desk.get("/inbox")
        check(status == 200, f"GET /inbox answered {status}")
        page = body.decode("utf-8")
        check(page.count("tag-sample") >= len(SAMPLE_CARD_IDS),
              "the labelled sample cards did not render with their Sample tag")
        check("Sample data:" in page, "the sample origin lines are missing")
        check("Overnight sales update" in page, "the sample update card is missing")
        check("Before your sample meeting" in page, "the sample brief card is missing")
        workbook = desk.data_dir / "sample" / "sample-sales.xlsx"
        check(workbook.is_file(), "the sample workbook was not seeded")

    def step_inbox_actions(self) -> None:
        """Drive every inbox card action once and check the state each leaves.

        Accept clears the card, an edit keeps it waiting, snooze for an hour
        pins now plus 3600 inside a 200 s window, more-info ends the snooze,
        and a dismissed card restores to waiting.
        """
        desk = self.a
        # accept the update card
        out = desk.post_json_ok("/inbox/cards/sample-update/accept", {})
        check(out["status"] == "accepted", f"accept answered {out['status']}")
        # edit the brief's draft, still waiting
        out = desk.post_json_ok("/inbox/cards/sample-brief/edit",
                                {"draft": "Demo edit: attendees first"})
        check(out["draft"] == "Demo edit: attendees first", "the edit did not stick")
        check(out["status"] == "waiting", "an edited card must stay waiting")
        # snooze the feature request for an hour
        before = time.time()
        out = desk.post_json_ok("/inbox/cards/sample-feature-request/snooze",
                                {"choice": "1h"})
        snoozed_until = out["snoozedUntil"]
        check(before + 3500 < snoozed_until <= before + 3700,
              f"snooze 1h pinned {snoozed_until}, expected now+3600")
        counts = desk.get_json("/widgets/inbox")
        # brief + consent remain waiting (the update was accepted)
        check(counts["waiting"] == 2,
              f"after the snooze {counts['waiting']} cards wait, expected 2")
        # more-info attaches the instruction and ends the snooze
        out = desk.post_json_ok("/inbox/cards/sample-feature-request/more-info",
                                {"instruction": "name the wizard session"})
        check(out["meta"]["instruction"] == "name the wizard session",
              "the more-info instruction did not ride the card")
        check(out["snoozedUntil"] is None, "more-info must end the snooze")
        # dismiss the brief, then restore it from the shelf
        out = desk.post_json_ok("/inbox/cards/sample-brief/dismiss", {})
        check(out["status"] == "dismissed", "dismiss did not take")
        out = desk.post_json_ok("/inbox/dismissed/sample-brief/restore", {})
        check(out["status"] == "waiting", "restore did not bring the card back")

    def step_audit_and_activity(self) -> None:
        """Check the audit tail and the activity page name every action taken.

        The pending action is deliberately not expected: it belongs to the
        snooze return path, which needs the wall clock to reach it.
        """
        desk = self.a
        tail = desk.get_json("/audit/tail")
        actions = {entry["action"] for entry in tail["entries"]}
        # inbox.pending belongs to the snooze-RETURN path (an hour later on
        # the wall clock); a live walkthrough asserts the snooze itself.
        expected = {"inbox.approved", "inbox.edited", "inbox.snoozed",
                    "inbox.more-info", "inbox.denied",
                    "inbox.restored", "demo.seeded"}
        missing = expected - actions
        check(not missing, f"the audit log is missing {sorted(missing)}")
        targets = {entry["target"] for entry in tail["entries"]}
        check({"sample-update", "sample-brief", "sample-feature-request"} <= targets,
              "the audit rows must name the sample cards they acted on")
        status, _headers, body = desk.get("/activity")
        check(status == 200, f"GET /activity answered {status}")
        page = body.decode("utf-8")
        for word in ("approved", "edited", "snoozed", "more-info", "denied",
                     "restored", "sample on"):
            check(word in page, f"the activity page does not name {word!r}")

    def step_endpoint_strict_save(self) -> None:
        """Check the connections save refuses mistyped fields and stores nothing.

        The refusal must name both the rejected fields and the accepted ones,
        and a refused save must leave the connections list empty (the
        endpoint rows themselves retired to this surface, spec 018 #234).
        """
        desk = self.a
        status, _headers, body = desk.post_json("/api/connections", {
            "labell": "OpenAI personal",
            "provider": "openai",
            "apiKey": "typed-key",
        })
        check(status == 400, f"the wrong-field save answered {status}, expected 400")
        payload = json.loads(body.decode("utf-8"))
        check("labell" in payload["error"] and "apiKey" in payload["error"],
              "the refusal must name the mistyped fields")
        check("accepted fields are label, provider, baseUrl, apiKey" in payload["error"],
              "the refusal must name the accepted fields")
        check(desk.get_json("/api/connections")["connections"] == [],
              "a refused save must save nothing")

    def step_endpoint_test_cause(self) -> None:
        """Check a connection's Test names the login-page cause and saves nothing.

        The stub answers every request with an HTML sign-in page, the worst
        real-world shape an endpoint can take. The connection rides a local
        preset, so the step needs no key and touches no keychain; the
        row is deleted again before the step ends.
        """
        desk = self.a
        stub = LoginStub()
        try:
            out = desk.post_json_ok("/api/connections", {
                "label": "Stub box", "provider": "ollama",
                "baseUrl": stub.base_url})
            connection_id = out["id"]
            out = desk.post_json_ok(f"/api/connections/{connection_id}/test", {})
            check(out["status"] == "error",
                  "the HTML login page must not pass as an API")
            check("web page" in out["lastError"],
                  f"the cause must name the web page, got {out['lastError']!r}")
            values = desk.get_json("/widgets/settings")
            check(not values["llm_base"],
                  "Test must never save what was typed into the connection")
            status, _headers, _body = desk.post_json(
                f"/api/connections/{connection_id}/delete", {})
            check(status == 200, f"the cleanup delete answered {status}")
        finally:
            stub.close()

    def step_wizard_create(self) -> None:
        """Take the wizard from English to an installed, enabled pilot plugin.

        Every question is answered with its default, which is the
        deterministic no-endpoint path. The install must land as pilot, with an
        id carrying the wizard prefix.
        """
        desk = self.a
        status, _headers, body = desk.post_json("/wizard/start",
                                                {"description": CANONICAL})
        check(status == 201, f"/wizard/start answered {status}")
        session = json.loads(body.decode("utf-8"))
        check(session["state"] == "questions", f"the session is {session['state']}")
        questions = session["questions"]
        check(0 < len(questions) <= 5, f"{len(questions)} questions, expected 1..5")
        # answer with the defaults, the no-endpoint deterministic path
        location = None
        data = json.dumps({"answers": {q["id"]: q.get("default", "")
                                       for q in questions}}).encode("utf-8")
        request = urllib.request.Request(
            desk.base + f"/wizard/{session['id']}/answer", data=data,
            method="POST", headers={"Content-Type": "application/json"})
        status, headers, _body = desk._open(desk.direct, request)
        check(status == 303, f"the answer answered {status}, expected 303")
        location = headers.get("Location", "")
        check(location == f"/wizard/{session['id']}", f"redirected to {location}")
        status, _headers, body = desk.get(f"/wizard/{session['id']}")
        check(status == 200 and "Preview" in body.decode("utf-8"),
              "the preview screen did not render")
        # approve: the one consolidated yes
        out = desk.post_json_ok(f"/wizard/{session['id']}/approve", {})
        check(out["status"] == "installed", f"approve said {out['status']}")
        check(out["pilot"] is True, "a wizard install must be pilot")
        self.wizard_id = out["install"]["id"]
        check(self.wizard_id.startswith("wizard-"),
              f"the wizard plugin id is {self.wizard_id}")
        records = desk.get_json("/api/plugins")["plugins"]
        match = [r for r in records if r["id"] == self.wizard_id]
        check(len(match) == 1 and match[0]["state"] == "enabled",
              "the wizard plugin must be installed and enabled")

    def step_wizard_card_on_dashboard(self) -> None:
        """Check the wizard card reaches the dashboard as a pilot setup card.

        A workbook ask installs config-backed, so the honest freshness is setup
        with no elements bound, not an amber guess about a glob.
        """
        payload = self.a.get_json("/api/dashboard")
        cards = {c["id"]: c for c in payload["plugins"]["cards"]}
        check(self.wizard_id in cards,
              "the wizard plugin's card did not reach the dashboard")
        card = cards[self.wizard_id]
        check(card["pilot"] is True, "the wizard card must wear the pilot badge")
        check(card["version"] == "0.1.0", f"the card says v{card['version']}")
        # A workbook ask installs config-backed (T2): no file was ever
        # granted, so the honest state is the setup card, not an amber
        # guess about a glob nothing reads.
        check(card["freshness"] == "setup",
              f"a workbook build must land in the setup state, got {card['freshness']}")
        setup = card["payload"]["setup"]
        check(setup["pluginId"] == self.wizard_id,
              f"the setup payload names {setup.get('pluginId')!r}")
        check(setup["step"] == "source",
              f"the setup step is {setup.get('step')!r}, expected source")
        check(card["payload"]["elements"] == [],
              "the setup card must bind nothing before a workbook exists")

    def step_wizard_setup_data(self) -> None:
        """The finish line (T6): create the instance, open the workbook
        through the injected picker (the native dialog's stand-in),
        accept the outside-workspace path by name, confirm a row
        selection, and the card is fresh with exactly that row's value."""
        desk = self.a
        wid = self.wizard_id
        base = f"/api/plugins/{wid}/instances"
        out = desk.post_json_ok(base, {"name": "Sample tracker"})
        check(out["instance"]["instanceId"] == "sample-tracker",
              f"the create answered {out}")
        payload = desk.get_json("/api/dashboard")
        card = next(c for c in payload["plugins"]["cards"]
                    if c["id"] == f"{wid}~sample-tracker")
        check(card["freshness"] == "setup",
              f"the new instance's card is {card['freshness']}, expected setup")
        check(card["payload"]["setup"]["step"] == "source",
              "the new instance starts at the source step")

        out = desk.post_json_ok(f"{base}/sample-tracker/pick",
                                {"name": "Sample tracker"})
        preview = out["preview"]
        check(preview["headers"][:2] == ["Deal", "Region"],
              f"the preview headers are {preview['headers']!r}")
        check(preview["rows"][0][0] == "Harborlight Freight renewal",
              f"the preview's first row is {preview['rows'][0]!r}")

        tracking = {"labelColumn": "Deal", "valueColumn": "Amount",
                    "aggregate": "sum", "rows": [0]}
        status, _headers, body = desk.post_json(
            f"{base}/sample-tracker/confirm", {"tracking": tracking})
        check(status == 400, f"the first confirm answered {status}")
        refusal = json.loads(body.decode("utf-8"))
        check(refusal["error"] == "config:outside-workspace",
              f"the refusal is {refusal.get('error')!r}, expected config:outside-workspace")
        check(refusal["message"], "the refusal must carry its plain-language message")

        out = desk.post_json_ok(f"{base}/sample-tracker/outside", {})
        check(out.get("outsideAccepted") is True, f"the accept said {out}")
        out = desk.post_json_ok(f"{base}/sample-tracker/confirm",
                                {"tracking": tracking})
        check(out["instance"]["tracking"]["rows"] == [0],
              f"the confirm stored {out['instance']['tracking'].get('rows')!r}")

        payload = desk.get_json("/api/dashboard")
        card = next(c for c in payload["plugins"]["cards"]
                    if c["id"] == f"{wid}~sample-tracker")
        check(card["freshness"] == "fresh",
              f"the confirmed card is {card['freshness']}, expected fresh")
        metrics = {e["label"]: e["value"] for e in card["payload"]["elements"]
                   if e["kind"] == "metric"}
        # Row 1 only: 12000 + round(7919, -1); the other 99 rows are not
        # in the card, which is the whole point of the row selection.
        check(metrics.get("Value") == "19920",
              f"the tracked value is {metrics.get('Value')!r}, expected 19920")
        workbook = next(e for e in card["payload"]["elements"]
                        if e["kind"] == "text" and e.get("label") == "Workbook")
        check(workbook["text"] == "sample-sales.xlsx",
              f"the bound workbook is {workbook['text']!r}")

    def step_publish(self) -> None:
        """Publish the wizard plugin to a temp copy of this checkout's registry.

        The copy keeps the real registry untouched. Clearing the setting must
        bring the listing back to the checkout origin, which proves both the
        save and the clear took effect.
        """
        desk = self.a
        # a temp registry root: a copy of this checkout's registry
        registry_copy = self.root / "registry-copy"
        shutil.copytree(ROOT / "registry", registry_copy)
        location = desk.post_form("/settings/registry/path",
                                  {"path": str(registry_copy)})
        check(location == "/plugins", f"the registry path save landed at {location}")
        out = desk.post_json_ok(f"/api/plugins/{self.wizard_id}/publish", {})
        check(out["ok"] is True and out["source"] == "local",
              f"publish answered {out}")
        check(out["version"] == "0.1.0", f"published v{out['version']}")
        listing = desk.get_json("/api/registry")
        check(listing["ok"] is True and listing["origin"] == "setting",
              f"the listing said {listing.get('origin')}")
        entry = next((e for e in listing["plugins"] if e["id"] == self.wizard_id),
                     None)
        check(entry is not None, "the published plugin is not in the listing")
        check(entry["latest"] == "0.1.0", f"the listing says {entry['latest']}")
        check(entry["releases"][0]["source"] == "local",
              "the release must be pinned as a local digest release")
        # back to automatic resolution: this app's own checkout
        desk.post_form("/settings/registry/path", {"path": ""})
        listing = desk.get_json("/api/registry")
        check(listing["ok"] is True and listing["origin"] == "checkout",
              f"after clearing the setting the origin is {listing.get('origin')}")

    def step_registry_install(self) -> None:
        """Install the shipped excel-report plugin and check its setup card.

        No workbook has been granted yet, so both the record and the card must
        report setup with no cause.
        """
        desk = self.a
        out = desk.post_json_ok("/api/registry/install",
                                {"id": self.excel_plugin})
        check(out["ok"] is True, f"the install refused: {out}")
        check(out["version"] == "0.1.0", f"installed v{out['version']}")
        # The shipped tracker is config-backed: it installs into the
        # setup state (no file was granted), not an amber glob guess.
        record = desk.get_json(f"/api/plugins/{self.excel_plugin}")
        source = record["data_source"]
        check(source["status"] == "setup",
              f"no workbook picked yet: expected setup, got {source['status']}")
        check(source["cause"] == "",
              f"the setup state carries no cause, got {source['cause']!r}")
        payload = desk.get_json("/api/dashboard")
        card = next(c for c in payload["plugins"]["cards"]
                    if c["id"] == self.excel_plugin)
        check(card["freshness"] == "setup",
              f"the card must render setup, got {card['freshness']}")
        check(card["payload"]["setup"]["step"] == "source",
              "the tracker starts at the source step")

    def step_connect_workbook(self) -> None:
        """Connect the sample workbook to the sales card and to a tracker instance.

        The outside-workspace refusal comes first, then the acceptance, then
        the bind: the tracked first row alone must total 19920 and the card must
        name the workbook.
        """
        desk = self.a
        sample = desk.data_dir / "sample" / "sample-sales.xlsx"
        check(sample.is_file(), "the seeded sample workbook is gone")
        # the built-in sales card: register the sample workbook as the
        # watched source, exactly the settings-page connect action
        out = desk.post_json_ok("/sources/excel-watch", {"path": str(sample)})
        check(out.get("configured") is True, f"the source said {out}")
        payload = desk.get_json("/api/dashboard")
        check(payload["sales"]["mode"] == "live",
              f"the sales card is {payload['sales']['mode']}, expected live")
        # the plugin card: the same pick-and-confirm flow the wizard
        # plugin used, on the shipped tracker. The picker stands in for
        # the native dialog; the sample folder is outside the scoped
        # workspace, so the acceptance step runs for real.
        base = f"/api/plugins/{self.excel_plugin}/instances"
        out = desk.post_json_ok(base, {"name": "Workbook tracker"})
        check(out["instance"]["instanceId"] == "workbook-tracker",
              f"the create answered {out}")
        out = desk.post_json_ok(f"{base}/workbook-tracker/pick",
                                {"name": "Workbook tracker"})
        check(out["preview"]["headers"][:1] == ["Deal"],
              f"the preview headers are {out['preview']['headers']!r}")
        tracking = {"labelColumn": "Deal", "valueColumn": "Amount",
                    "aggregate": "sum", "rows": [0]}
        status, _headers, body = desk.post_json(
            f"{base}/workbook-tracker/confirm", {"tracking": tracking})
        check(status == 400, f"the first confirm answered {status}")
        refusal = json.loads(body.decode("utf-8"))
        check(refusal["error"] == "config:outside-workspace",
              f"the refusal is {refusal.get('error')!r}")
        desk.post_json_ok(f"{base}/workbook-tracker/outside", {})
        out = desk.post_json_ok(f"{base}/workbook-tracker/confirm",
                                {"tracking": tracking})
        check(out["instance"]["confirmedAt"], "the confirm did not stick")
        payload = desk.get_json("/api/dashboard")
        card = next(c for c in payload["plugins"]["cards"]
                    if c["id"] == f"{self.excel_plugin}~workbook-tracker")
        check(card["freshness"] == "fresh", "the card must be fresh now")
        elements = card["payload"]["elements"]
        by_label = {e.get("label"): e for e in elements if e["kind"] == "metric"}
        check(by_label.get("Value", {}).get("value") == "19920",
              f"the tracked value is {by_label.get('Value')}")
        workbook = next(e for e in elements
                        if e["kind"] == "text" and e.get("label") == "Workbook")
        check(workbook["text"] == "sample-sales.xlsx",
              f"the bound workbook is {workbook['text']!r}")

    def step_boot_desk_b(self) -> None:
        """Boot Desk B on its own data dir and check its peers page renders."""
        desk = Desk("B", self.root / "desk-b", _free_udp_port())
        self.desks.append(desk)
        self.b = desk
        desk.exchange()
        status, _headers, body = desk.get("/peers")
        check(status == 200 and "<h1>Peers</h1>" in body.decode("utf-8"),
              "Desk B's peers page did not render")

    def step_pair(self) -> None:
        """Share the wizard plugin from A, pair B with the code, and check B's catalog.

        B must list A as paired, see the shared plugin, and report it neither
        installed nor updatable before the install step runs.
        """
        a, b = self.a, self.b
        a.post_form("/plugins/%s/share" % self.wizard_id, {})
        shared = a.server.peer_store.shared_ids()
        check(self.wizard_id in shared, "the share toggle did not take on A")
        a.post_form("/peers/code", {})
        code = a.get_json("/api/peers")["pairingCode"]["code"]
        check(bool(code), "no pairing code was generated")
        location = b.post_form("/peers/pair",
                               {"address": f"127.0.0.1:{a.server.port}",
                                "code": code})
        check(location.startswith("/peers"),
              f"pairing landed at {location}")
        catalog = b.get_json("/api/peers")
        check(len(catalog["paired"]) == 1, "Desk B must list Desk A as paired")
        plugins = catalog["paired"][0]["plugins"]
        entry = next((p for p in plugins if p["id"] == self.wizard_id), None)
        check(entry is not None, "A's shared plugin is not listed on B")
        check(entry["installed_here"] is False, "B must not have it yet")
        check(entry["update_available"] is False, "no update can exist yet")

    def step_peer_install(self) -> None:
        """Install A's shared plugin on B and check B runs it from the peer.

        The lockfile source must carry the peer prefix, which is what
        distinguishes a peer install from a registry one.
        """
        a, b = self.a, self.b
        peer_id = a.server.peer_store.desk()["peer_id"]
        b.post_form("/peers/install",
                    {"peer_id": peer_id, "plugin_id": self.wizard_id})
        record = b.get_json(f"/api/plugins/{self.wizard_id}")
        check(record["active_version"] == "0.1.0",
              f"B runs v{record['active_version']}")
        check(str(record.get("source", "")).startswith("peer:"),
              f"B's lockfile source is {record.get('source')!r}")
        payload = b.get_json("/api/dashboard")
        cards = {c["id"] for c in payload["plugins"]["cards"]}
        check(self.wizard_id in cards, "the shared plugin's card does not render on B")

    def step_wrong_token(self) -> None:
        """Check /peer/info refuses a made-up bearer token by name.

        The refusal must be a 403 carrying the token-unknown code rather than a
        generic body.
        """
        a = self.a
        status, _headers, body = a.raw_get(
            "/peer/info", {"Host": f"127.0.0.1:{a.server.port}",
                           "Authorization": "Bearer not-a-real-token"})
        check(status == 403, f"the wrong token answered {status}, expected 403")
        payload = json.loads(body.decode("utf-8"))
        check(payload["error"] == "peer:token-unknown",
              f"the refusal is {payload.get('error')!r}, expected peer:token-unknown")

    def step_peer_update(self) -> None:
        """Bump A's plugin, refresh B, and check update-available plus one click.

        The bump is a rezip of the installed tree with only the manifest
        version changed, so the update flows through the same path a real
        release would.
        """
        a, b = self.a, self.b
        # A publishes 0.0.2 of the wizard plugin through the update flow
        record = a.get_json(f"/api/plugins/{self.wizard_id}")
        version_dir = Path(record["versions"][-1]["dir"])
        check(version_dir.is_dir(), f"the installed tree is gone: {version_dir}")
        manifest = json.loads((version_dir / "manifest.json").read_text("utf-8"))
        manifest["version"] = "0.0.2"
        bump = self.root / "wizard-0.0.2.zip"
        with zipfile.ZipFile(bump, "w") as archive:
            for path in sorted(version_dir.rglob("*")):
                if not path.is_file():
                    continue
                if path.name == "manifest.json":
                    continue
                archive.writestr(path.relative_to(version_dir).as_posix(),
                                 path.read_bytes())
            archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        out = a.post_json_ok(f"/api/plugins/{self.wizard_id}/update",
                             {"zip_path": str(bump)})
        check(out.get("version", out.get("active_version")) == "0.0.2"
              or out.get("ok") is True, f"the bump answered {out}")
        record = a.get_json(f"/api/plugins/{self.wizard_id}")
        check(record["active_version"] == "0.0.2",
              f"A runs v{record['active_version']}, expected 0.0.2")
        # still shared; B refreshes and sees the update
        b.post_form("/peers/refresh", {})
        catalog = b.get_json("/api/peers")
        entry = next(p for p in catalog["paired"][0]["plugins"]
                     if p["id"] == self.wizard_id)
        check(entry["version"] == "0.0.2",
              f"B sees the publisher at {entry['version']}")
        check(entry["update_available"] is True,
              "B must see update-available after the bump")
        peer_id = a.server.peer_store.desk()["peer_id"]
        b.post_form("/peers/update",
                    {"peer_id": peer_id, "plugin_id": self.wizard_id})
        record = b.get_json(f"/api/plugins/{self.wizard_id}")
        check(record["active_version"] == "0.0.2",
              f"the one-click update left B at v{record['active_version']}")

    def step_customize(self) -> None:
        """Save a layout with research first and sales hidden, then restore it.

        A hidden card must stay in the listed layout marked hidden, which is
        what Restore reads, while the dashboard payload omits it; restoring
        must return the exact key order.
        """
        desk = self.a
        listed = desk.get_json("/api/layout")["cards"]
        keys = [c["key"] for c in listed]
        # A config-backed plugin contributes one key per instance once
        # instances exist (its plugin id before that, the setup card's
        # home), so both trackers appear under their instance keys here.
        check(set(BUILTINS) <= set(keys)
              and f"{self.excel_plugin}~workbook-tracker" in keys
              and f"{self.wizard_id}~sample-tracker" in keys,
              f"the layout must list every card, got {keys}")
        # reorder (research first) and hide the sales card
        reordered = ([{"key": "research"}]
                     + [{"key": k} for k in keys if k not in ("research", "sales")]
                     + [{"key": "sales", "hidden": True}])
        out = desk.post_json_ok("/api/layout", {"cards": reordered})
        check([c["key"] for c in out["cards"]][0] == "research",
              "the save must answer with the new order")
        payload = desk.get_json("/api/dashboard")
        visible = [c["key"] for c in payload["layout"]["cards"]]
        check(visible[0] == "research", f"the dashboard order is {visible}")
        check("sales" not in visible, "the hidden card must not render")
        listed = desk.get_json("/api/layout")["cards"]
        hidden = {c["key"]: c["hidden"] for c in listed}
        check(hidden.get("sales") is True,
              "the hidden card must stay listed for Restore")
        # restore the default arrangement
        restored = [{"key": k, "hidden": False} for k in keys]
        desk.post_json_ok("/api/layout", {"cards": restored})
        payload = desk.get_json("/api/dashboard")
        visible = [c["key"] for c in payload["layout"]["cards"]]
        check(visible == keys, f"after restore the order is {visible}, expected {keys}")

    # -- the run ----------------------------------------------------------

    def main(self) -> int:
        """Run every step over one temp dir and return the process exit code.

        0 means every step passed; 1 means the first failure was printed and
        the remaining steps never ran. The temp dir is removed and the desks
        stopped even on failure, and AGENTDESK_DATA goes back to what the
        caller had.
        """
        original_data = os.environ.get("AGENTDESK_DATA")
        # Hermetic and unconfigured: no endpoint, no registry override,
        # no calendar file, and empty strings block ~/.agent-desk/config.env.
        for key in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY",
                    "AGENTDESK_LLM_MODEL", "AGENTDESK_REGISTRY",
                    "AGENTDESK_CALENDAR_FILE"):
            os.environ[key] = ""
        steps = (
            ("boot: token exchange and the dashboard payload", self.step_boot),
            ("rail: every page answers with its heading", self.step_rail),
            ("wizard: the start form answers on /wizard", self.step_wizard_start_form),
            ("sample data: the switch seeds labelled inbox cards",
             self.step_sample_data_on),
            ("inbox: accept, edit, snooze, more-info, dismiss, restore",
             self.step_inbox_actions),
            ("audit and activity name every action", self.step_audit_and_activity),
            ("endpoint honesty: strict save refuses wrong field names",
             self.step_endpoint_strict_save),
            ("endpoint honesty: Test connection names the login-page cause",
             self.step_endpoint_test_cause),
            ("wizard: create from English, no endpoint, approve, install",
             self.step_wizard_create),
            ("wizard plugin's card renders on the dashboard",
             self.step_wizard_card_on_dashboard),
            ("wizard: set up its data, pick, confirm rows, card fresh",
             self.step_wizard_setup_data),
            ("publish: the temp registry lists the wizard plugin",
             self.step_publish),
            ("registry: excel-report installs into the setup state",
             self.step_registry_install),
            ("connect the workbook: pick, confirm, bound values",
             self.step_connect_workbook),
            ("peers: Desk B boots and pairs by code", self.step_boot_desk_b),
            ("peers: share, list, install, card renders on B", self.step_pair),
            ("peers: install lands on B with the card rendered",
             self.step_peer_install),
            ("peers: a wrong token is refused by name", self.step_wrong_token),
            ("peers: bump to 0.0.2, update-available, one click",
             self.step_peer_update),
            ("customize: reorder and hide respect the payload, restore",
             self.step_customize),
        )
        print("Agent Desk demo walkthrough")
        print(f"checkout: {ROOT}")
        try:
            # ignore_cleanup_errors: the app's sqlite stores stay open for
            # the process lifetime; Windows then refuses the temp delete.
            # The checks are done long before that matters.
            with tempfile.TemporaryDirectory(
                    prefix="agentdesk-walkthrough-",
                    ignore_cleanup_errors=True) as tmp:
                self.root = Path(tmp)
                for name, fn in steps:
                    self.run_step(name, fn)
        except WalkthroughError:
            pass
        finally:
            for desk in self.desks:
                desk.close()
            if original_data is None:
                os.environ.pop("AGENTDESK_DATA", None)
            else:
                os.environ["AGENTDESK_DATA"] = original_data
        passed = sum(1 for _n, ok, _r in self.results if ok)
        total = len(self.results)
        print("-" * 72)
        for name, ok, reason in self.results:
            if not ok:
                print(f"first failure: {name}: {reason}")
        print(f"{passed}/{len(steps)} steps passed")
        if passed != len(steps):
            print("WALKTHROUGH FAILED")
            return 1
        print("WALKTHROUGH PASS")
        return 0


if __name__ == "__main__":
    sys.exit(Walkthrough().main())
