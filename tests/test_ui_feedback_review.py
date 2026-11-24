"""The independent review's server fixes for the feedback round (spec 027).

S1 through S10 in the review: the status line's role and length, the dead
Check every control, the busy timer that outlives its fetch, the duplicate
submit that reaches the form listener, the form that cannot recover, the
tests that passed for the wrong reason, the plugin table without a
scroller, the rail labels without a title, the dashboard's network fact and
the reload that ignores a non-ok status.

These drive the real HTTP seam, the way a browser would, and read the
served script and stylesheet for what pytest cannot execute.
"""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.server import pages


class CaptureLlm:
    """The stub endpoint every model-backed form here talks to."""

    def __init__(self, reply: str = "A plain answer.") -> None:
        """Hold the one reply every call returns."""
        self.prompts: list[str] = []
        self.reply = reply

    def __call__(self, prompt: str) -> str:
        """Record the prompt and answer with the canned reply."""
        self.prompts.append(prompt)
        return self.reply


@pytest.fixture()
def booted():
    """One booted desk with every store and watcher faked in memory."""
    server = server_harness.Booted(llm=CaptureLlm())
    try:
        yield server
    finally:
        server.close()


def _get(booted, path):
    """Fetch one page through the real HTTP seam, requiring 200."""
    headers = booted.exchange()
    status, _headers, body = booted.request("GET", path, headers)
    assert status == 200, (status, path)
    return body.decode("utf-8")


def _post_form(booted, path, fields):
    """A browser-shaped POST: form-urlencoded fields, no JavaScript."""
    body = urlencode(fields).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
    }
    headers.update(booted.exchange())
    return booted.request("POST", path, headers, body)


def _js_block(source, marker):
    """The body of one top-level function, from its marker to its close."""
    start = source.index(marker)
    end = source.index("\n}\n", start) + len("\n}\n")
    return source[start:end]


# -- S1: the status line's role is chosen, never taken from the URL ------


def test_a_crafted_notice_kind_cannot_inject_markup(booted):
    kind = '"><img src=x onerror=alert(1)>'
    page = _get(booted, "/inbox?notice=hello&notice_kind=" + quote(kind))
    assert "<img" not in page
    assert "onerror" not in page
    assert '<p class="page-status" role="status">hello</p>' in page


def test_a_notice_longer_than_the_cap_is_cut(booted):
    wall = "Z" * 800
    page = _get(booted, "/inbox?notice=" + quote(wall))
    assert page.count("Z") == 300


def test_an_alert_notice_keeps_the_alert_role(booted):
    page = _get(booted, "/inbox?notice=Nope&notice_kind=alert")
    assert '<p class="page-status" role="alert">Nope</p>' in page


def test_an_unknown_notice_kind_is_a_plain_status(booted):
    page = _get(booted, "/inbox?notice=Fine&notice_kind=sword")
    assert '<p class="page-status" role="status">Fine</p>' in page


# -- S2: every data-setting control is a form that posts ------------------


class _SettingScan(HTMLParser):
    """Flag every element carrying data-setting that no form wraps."""

    def __init__(self) -> None:
        """Start outside every form with no offenders."""
        super().__init__()
        self.depth = 0
        self.offenders: list[str] = []

    def handle_starttag(self, tag, attrs):
        """Track form nesting and record a bare data-setting element."""
        if tag == "form":
            self.depth += 1
        if any(name == "data-setting" for name, _value in attrs) and self.depth == 0:
            self.offenders.append(tag)

    def handle_endtag(self, tag):
        """Leave one form when its close tag arrives."""
        if tag == "form" and self.depth:
            self.depth -= 1


SETTING_PAGES = (
    "/settings", "/inbox", "/assistant", "/agents", "/memory", "/mail",
    "/capabilities", "/peers",
)


def test_no_data_setting_control_sits_outside_a_form(booted):
    for path in SETTING_PAGES:
        scan = _SettingScan()
        scan.feed(_get(booted, path))
        assert scan.offenders == [], path


def test_the_check_every_control_is_its_own_form(booted):
    page = _get(booted, "/settings")
    form = next(
        found for found in re.findall(r"<form[^>]*>.*?</form>", page, flags=re.S)
        if "agent_loop_minutes" in found and "data-setting" in found)
    assert "action='/settings/toggle'" in form or 'action="/settings/toggle"' in form
    assert "name='key' value='agent_loop_minutes'" in form or (
        'name="key" value="agent_loop_minutes"' in form)
    assert "type='submit'" in form or 'type="submit"' in form


def test_the_check_every_control_changes_the_setting_without_script(booted):
    page = _get(booted, "/settings")
    form = next(
        found for found in re.findall(r"<form[^>]*>.*?</form>", page, flags=re.S)
        if "agent_loop_minutes" in found and "data-setting" in found)
    fields = dict(re.findall(
        r"<input[^>]*name=['\"]([^'\"]+)['\"][^>]*value=['\"]([^'\"]*)['\"]",
        form))
    assert fields.get("key") == "agent_loop_minutes"
    assert booted.server.settings.get("agent_loop_minutes") == 60
    status, headers, _body = _post_form(booted, "/settings/toggle", fields)
    assert status == 303
    assert headers["Location"] == "/settings#agent"
    assert booted.server.settings.get("agent_loop_minutes") == 30


# -- S3: the busy timer dies with the wait it belongs to ------------------


def test_the_busy_timer_is_cleared_when_the_control_rests():
    source = pages.APP_JS
    begin = _js_block(source, "function beginControl(btn) {")
    assert "btn._busyTimer = window.setTimeout" in begin
    rest = _js_block(source, "function setButtonBusy(btn, on, label) {")
    assert "if (!on && btn._busyTimer)" in rest
    assert "window.clearTimeout(btn._busyTimer)" in rest
    assert "btn._busyTimer = null" in rest
    assert "return function cancel()" not in source


# -- S4: a duplicate submit never reaches the form's own listener ---------


def test_a_duplicate_submit_is_stopped_before_the_form_listener():
    guard = _js_block(pages.APP_JS, "function onSubmit(event) {")
    duplicate = guard[guard.index("data-busy-form') === '1'"):]
    assert "event.preventDefault();" in duplicate
    assert ("event.stopPropagation();" in duplicate
            or "event.stopImmediatePropagation();" in duplicate)


# -- S5: a form that never answers unlocks itself after three minutes -----


def test_a_stuck_form_unlocks_after_the_watchdog_limit():
    source = pages.APP_JS
    assert "BUSY_WATCHDOG_MS = 180000" in source
    watch = source[source.index("form._busyWatchdog = window.setTimeout"):]
    watch = watch[:watch.index("}, BUSY_WATCHDOG_MS);")]
    assert "document.visibilityState === 'visible'" in watch
    assert "unlockStuckForm(form)" in watch
    unlock = _js_block(source, "function unlockStuckForm(form) {")
    assert "cancelFormBusy(form)" in unlock
    assert "removeWaitPlaceholder(" in unlock
    assert "taking too long" in unlock
    assert "still running" in unlock
    rest = _js_block(source, "function cancelFormBusy(form) {")
    assert "clearTimeout(form._busyWatchdog)" in rest
    assert "form._busyWatchdog = null" in rest
    assert "removeEventListener('visibilitychange'" in rest


# -- S10: a non-ok JSON answer is a failure whatever its body says --------


def test_every_reload_is_decided_by_the_response_status():
    source = pages.APP_JS
    apply = _js_block(source, "var apply = function (url, body, btn) {")
    assert "shouldReloadAfterPost(res.ok)" in apply
    assert "causeOf(res)" in apply
    connect = _js_block(source, "var connect = function (path) {")
    assert "shouldReloadAfterPost(res.ok)" in connect
    upload = source[source.index("reader.onload = function () {"):]
    upload = upload[:upload.index("reader.readAsText(file);")]
    assert "shouldReloadAfterPost(res.ok)" in upload
    assert "causeOf(res)" in upload
    # Every reload is now behind one decision: the four sites.
    assert source.count("location.reload()") == 4
    for marker in ("var apply = function (url, body, btn) {",
                   "var connect = function (path) {",
                   "reader.onload = function () {"):
        block = source[source.index(marker):]
        block = block[:block.index("location.reload()")]
        assert "res.ok" in block, marker


def test_the_served_script_carries_the_status_guard(booted):
    headers = booted.exchange()
    status, _headers, body = booted.request("GET", "/static/app.js", headers)
    assert status == 200
    source = body.decode("utf-8")
    assert "function causeOf(res)" in source
    assert "!shouldReloadAfterPost(res.ok)" in source


# -- S9: the dashboard payload names whether the desk can read the web ---


def _dashboard_payload(booted):
    headers = booted.exchange()
    status, _headers, body = booted.request("GET", "/api/dashboard", headers)
    assert status == 200
    return json.loads(body)


def test_the_dashboard_payload_reports_no_network_in_production(booted):
    payload = _dashboard_payload(booted)
    assert payload["deskNetwork"] is False


def test_a_runner_with_a_transport_reports_network_available(booted):
    from agentdesk.plugins.execute import PluginWidgetRunner

    runtime = booted.server.plugins
    runtime.runner = PluginWidgetRunner(
        runtime.workspace_dir, http_transport=object())
    assert _dashboard_payload(booted)["deskNetwork"] is True


# -- S8: a truncated rail label still offers its full text ---------------


def test_every_rail_label_carries_its_full_text_as_a_title(booted):
    page = _get(booted, "/settings")
    start = page.index('<nav class="rail"')
    rail = page[start:page.index("</nav>", start) + len("</nav>")]
    entries = re.findall(r"<a\b([^>]*)>(.*?)</a>", rail, flags=re.S)
    assert entries
    for attrs, inner in entries:
        label = re.search(r'<span class="rail-label">([^<]+)</span>', inner)
        assert label is not None, inner
        assert re.search(
            r'\btitle="' + re.escape(label.group(1)) + r'"', attrs), attrs
    toggle = re.search(r"<button\b[^>]*class=['\"]rail-toggle['\"][^>]*>", rail)
    assert toggle is not None
    assert 'title="Collapse navigation"' in toggle.group(0)
    source = pages.APP_JS
    assert "btn.setAttribute('title'" in source
    assert "Expand navigation" in source
    assert "Collapse navigation" in source


# -- S6: every redirect names its outcome in the notice query ------------


def _notice(location):
    """The decoded notice value a redirect carries, if any."""
    query = location.partition("?")[2].partition("#")[0]
    return parse_qs(query).get("notice", [""])[0]


def _notice_kind(location):
    """The decoded notice_kind value a redirect carries, if any."""
    query = location.partition("?")[2].partition("#")[0]
    return parse_qs(query).get("notice_kind", [""])[0]


def test_the_assistant_redirect_names_the_outcome(booted):
    status, headers, _body = _post_form(
        booted, "/assistant/ask", {"question": "what changed?"})
    assert status == 303
    assert _notice(headers["Location"]) == "Your answer is below."
    assert _notice_kind(headers["Location"]) in ("", "status")


def test_the_agents_redirect_names_the_outcome(booted):
    status, headers, _body = _post_form(
        booted, "/agents/run",
        {"agent": "worksheet-brief", "brief": "the Q3 review"})
    assert status == 303
    notice = _notice(headers["Location"])
    assert notice.startswith("Ran Worksheet brief.")
    assert "Its receipt is at the top of the run history." in notice


def test_the_memory_add_redirect_names_the_outcome(booted):
    status, headers, _body = _post_form(
        booted, "/memory/add", {"text": "revenue is 220"})
    assert status == 303
    assert _notice(headers["Location"]) == "The fact is saved."


def test_the_memory_forget_all_redirect_names_the_outcome(booted):
    booted.server.memory.add("revenue is 220", source="page")
    booted.server.memory.add("the Berlin office has 40 people", source="page")
    status, headers, _body = _post_form(
        booted, "/memory/forget-all", {"confirm": "yes"})
    assert status == 303
    assert _notice(headers["Location"]) == "Forgot 2 facts."


def test_the_capabilities_redirect_names_the_outcome(booted):
    status, headers, _body = _post_form(
        booted, "/capabilities/exec-user-space/retest", {})
    assert status == 303
    assert _notice(headers["Location"]).startswith("Gate re-tested: ")


def test_the_mail_folder_redirect_names_the_outcome(booted):
    status, headers, _body = _post_form(
        booted, "/settings/mail/folder", {"folder": "C:/mail-fixtures"})
    assert status == 303
    assert _notice(headers["Location"]) == "The mail folder is saved."


def test_the_endpoint_save_redirect_names_the_outcome(booted):
    status, headers, _body = _post_form(
        booted, "/settings/endpoint/save", {"presentationTimeout": "60"})
    assert status == 303
    assert _notice(headers["Location"]) == "The presentation timeout is saved."


def test_the_inbox_accept_redirect_names_the_outcome(booted):
    card = booted.server.inbox.add(
        kind="suggestion", origin="a test", title="A test card",
        body="", action_label="Do it")
    status, headers, _body = _post_form(
        booted, f"/inbox/cards/{card.id}/accept", {})
    assert status == 303
    assert _notice(headers["Location"]) == "The card was accepted."


@pytest.mark.parametrize("return_to", (
    "https://evil.example",
    "//evil.example/x",
    "javascript:alert(1)",
    "http://127.0.0.1:1/settings",
))
def test_an_external_return_to_falls_back_to_the_safe_settings_page(
        booted, return_to):
    status, headers, _body = _post_form(
        booted, "/settings/toggle",
        {"key": "mail_enabled", "return_to": return_to})
    assert status == 303
    assert headers["Location"] == "/settings"
    page = _get(booted, "/settings")
    form = next(
        found for found in re.findall(r"<form[^>]*>.*?</form>", page, flags=re.S)
        if "agent_loop_minutes" in found and "data-setting" in found)
    fields = dict(re.findall(
        r"<input[^>]*name=['\"]([^'\"]+)['\"][^>]*value=['\"]([^'\"]*)['\"]",
        form))
    assert fields.get("key") == "agent_loop_minutes"
    assert booted.server.settings.get("agent_loop_minutes") == 60
    status, headers, _body = _post_form(booted, "/settings/toggle", fields)
    assert status == 303
    assert headers["Location"] == "/settings#agent"
    assert booted.server.settings.get("agent_loop_minutes") == 30
