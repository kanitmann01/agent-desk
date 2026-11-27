"""Feedback on every wait, on the server-rendered pages (spec 027).

The rules are F1 to F7 in docs/design-language.md and the advisor's three
pieces (S1, S2, S3). The pages keep their normal navigation, so a wait is
carried by the outgoing page: the pressed submit button shows it on
itself, a model-backed form also writes a same-shape placeholder into the
region that will receive the result, and the page that arrives says the
outcome in a status line. Every page works with the script off.

These tests read the rendered HTML through the real HTTP seam, the way a
browser would, and the served script and stylesheet for the one delegated
listener, the placeholder and the busy pieces that pytest cannot execute.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.server import pages, peers_view, wizard_view

# Every page this ticket owns, with the rail label the shell carries.
PAGES = [
    "/inbox",
    "/assistant",
    "/agents",
    "/memory",
    "/mail",
    "/capabilities",
    "/peers",
    "/settings",
    "/settings/activity",
    "/walkthrough/calendar",
    "/what-this-touches",
    "/wizard",
]


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
    """Fetch one page through the real HTTP seam, requiring 200.

    A fragment is a browser-side destination and is never sent on the
    wire, so it is stripped here the way a browser would.
    """
    headers = booted.exchange()
    status, _headers, body = booted.request("GET", path.split("#", 1)[0], headers)
    assert status == 200, (status, path)
    return body.decode("utf-8")


def _attr(markup, name, value):
    """Whether one attribute carries one value, in either quote style."""
    return re.search(
        name + r"=[\"']" + re.escape(value) + r"[\"']", markup) is not None


def _post_form(booted, path, fields, follow=False):
    """A browser-shaped POST: form-urlencoded fields, no JavaScript."""
    body = urlencode(fields).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
    }
    headers.update(booted.exchange())
    status, out, page = booted.request("POST", path, headers, body)
    if follow:
        assert status in (200, 303), (status, page[:300])
        if status == 303:
            location = out["Location"]
            status, _out, page = booted.request("GET", location, headers)
            assert status == 200, (status, location)
        return status, out, page.decode("utf-8")
    return status, out, page


def _form(page, action):
    """The first form posting to one action, as its own markup block."""
    match = re.search(
        r"<form[^>]*action=[\"']" + re.escape(action) + r"[\"'][^>]*>.*?</form>",
        page,
        flags=re.S,
    )
    assert match is not None, action
    return match.group(0)


# -- the shell: skip link, main, focus and the one script ------------------


@pytest.mark.parametrize("path", PAGES)
def test_every_page_opens_with_a_skip_link_to_main(booted, path):
    page = _get(booted, path)
    body = page.split("<body>", 1)[1].lstrip()
    assert body.startswith('<a class="skip-link" href="#main">'), path
    assert 'id="main"' in page, path


@pytest.mark.parametrize("path", PAGES)
def test_every_page_serves_the_one_page_script(booted, path):
    page = _get(booted, path)
    assert '<script src="/static/app.js"></script>' in page, path


def test_the_script_has_one_delegated_capture_listener_and_a_back_restore():
    source = pages.APP_JS
    # S1: one listener at capture phase, no per-form listener.
    assert "document.addEventListener('submit', onSubmit, true)" in source
    # The double-submit guard and the busy markers.
    for marker in ("data-busy-form", "aria-busy", "aria-disabled",
                   "btn-label-busy", "btn-stack"):
        assert marker in source, marker
    # A back-navigation restores every button and drops the placeholder.
    assert "window.addEventListener('pageshow', restoreAfterBack)" in source
    assert "data-wait-ph" in source
    # F1: nothing shows under 100 milliseconds.
    assert "BUSY_DELAY_MS = 100" in source
    # F4: the ten second line.
    assert "TAKING_LONGER_MS = 10000" in source
    assert "taking longer than usual" in source


def test_the_script_reloads_only_after_a_success_for_every_fetch_handler():
    source = pages.APP_JS

    def decision(ok):
        """The pure reload decision the script embeds, mirrored here."""
        return ok is True

    assert "function shouldReloadAfterPost(ok) {" in source
    assert "return ok === true;" in source
    assert decision(True) and not decision(False) and not decision(None)
    # The seven former unconditional reloads now funnel through the two
    # helpers that ask the decision first: the re-tests, accept, dismiss,
    # restore, the settings toggle and the skill undo.
    assert source.count("shouldReloadAfterPost(") >= 3
    for helper in ("function finishFetch(", "function inboxDecision(",
                   "document.querySelectorAll('[data-setting]')"):
        block = source[source.index(helper):]
        block = block[:block.index("\n}")]
        assert "shouldReloadAfterPost(res.ok)" in block, helper


def test_the_sheet_carries_the_busy_dot_the_label_stack_and_the_shapes():
    css = pages.STYLES
    assert ".btn-stack{" in css
    assert ".btn-label-busy{" in css
    assert "animation:busy-dot" in css
    assert "@keyframes busy-dot" in css
    assert ".wait-ph{" in css
    for shape in ("answer", "list", "card", "panel", "widget"):
        assert f".wait-ph.{shape}" in css, shape
    # The card sketch: a figure, five bars and two text lines, all dashed.
    for part in ("wait-figure", "wait-chart", "wait-bar", "wait-text"):
        assert f".wait-ph.widget .{part}" in css, part
    assert ".wait-ph.widget .wait-bar:nth-child(5)" in css
    # The motion freezes when reduced motion is asked for.
    reduced = css.split("@media (prefers-reduced-motion:reduce)", 1)[1]
    assert "busy-dot" in reduced and "animation:none" in reduced


def test_the_widget_sketch_keeps_the_older_shapes_rows():
    source = pages.APP_JS
    assert "function placeholderRows(shape)" in source
    assert "if (shape === 'answer') return 3;" in source
    assert "if (shape === 'list') return 4;" in source
    assert "if (shape === 'card') return 2;" in source
    assert "if (shape === 'widget') {" in source
    assert "wait-figure" in source
    assert "wait-chart" in source
    assert "wait-bar" in source
    assert "wait-text wait-text-a" in source
    assert "wait-text wait-text-b" in source
    assert "wire.setAttribute('aria-hidden', 'true')" in source


# -- S2: every model-backed form names a region that exists --------------


def test_the_assistant_ask_form_names_the_thread_region(booted):
    page = _get(booted, "/assistant")
    form = _form(page, "/assistant/ask")
    assert _attr(form, "data-wait", "#assistant-thread")
    assert _attr(form, "data-wait-label", "Asking your AI...")
    assert _attr(form, "data-wait-shape", "answer")
    assert _attr(page, "id", "assistant-thread")


def test_the_agents_forms_wait_on_the_run_history(booted):
    page = _get(booted, "/agents")
    forms = re.findall(
        r"<form[^>]*action=[\"']/agents/run[\"'][^>]*>.*?</form>", page, flags=re.S)
    assert forms
    for form in forms:
        assert _attr(form, "data-wait", "#agents-history")
        assert "data-wait-label=" in form
    assert _attr(page, "id", "agents-history")
    presentation = next(f for f in forms if 'value="presentation"' in f)
    assert _attr(presentation, "data-wait-shape", "card")
    assert "This takes about a minute" in presentation


def test_the_memory_model_forms_wait_where_their_results_land(booted):
    fact = booted.server.memory.add("Priya Shah owns the Acme renewal.", source="page")
    assert fact is not None
    page = _get(booted, "/memory")
    reflect = _form(page, "/memory/reflect")
    assert _attr(reflect, "data-wait", "#observations")
    assert _attr(page, "id", "observations")
    recall = _form(page, "/memory/recall")
    assert _attr(recall, "data-wait", "#recall-result")
    assert _attr(page, "id", "recall-result")
    forget = _form(page, "/memory/forget-all")
    assert _attr(forget, "data-wait", "#forget-wait")
    assert _attr(page, "id", "forget-wait")
    encrypt_page = _get(booted, "/memory/encrypt")
    encrypt = _form(encrypt_page, "/memory/encrypt")
    assert _attr(encrypt, "data-wait", "#memory-maintenance")
    assert _attr(encrypt_page, "id", "memory-maintenance")


def test_the_capabilities_retest_waits_on_its_gate_card(booted):
    page = _get(booted, "/capabilities")
    forms = re.findall(
        r"<form[^>]*action=[\"']/capabilities/([^\"']+)/retest[\"'][^>]*>.*?</form>",
        page, flags=re.S)
    assert forms
    shapes = re.findall(r"data-wait-shape=[\"']card[\"']", page)
    assert len(shapes) >= len(forms)
    for key in re.findall(r"id=[\"']gate-([^\"']+)[\"']", page):
        assert _attr(page, "data-wait", f"#gate-{key}")


def test_the_settings_model_forms_wait_on_their_cards(booted):
    page = _get(booted, "/settings")
    save = _form(page, "/api/connections")
    assert _attr(save, "data-wait", "#connections-wait")
    assert _attr(page, "id", "connections-wait")
    update = _form(page, "/api/update/check")
    assert _attr(update, "data-wait", "#updates")
    assert _attr(page, "id", "updates")


def test_the_peer_forms_wait_on_the_peers_result(booted):
    page = _get(booted, "/peers")
    pair = _form(page, "/peers/pair")
    assert _attr(pair, "data-wait", "#peers-result")
    assert _attr(page, "id", "peers-result")
    # The install, update and refresh forms only render with a paired
    # desk; the view is the same surface, rendered with that state.
    catalog = {
        "ok": True,
        "desk": {"name": "This desk", "peer_id": "peer-a"},
        "pairingCode": None,
        "discovered": [],
        "paired": [{
            "peer_id": "peer-b", "name": "Other desk",
            "base_url": "127.0.0.1:9999", "state": {"ok": True},
            "plugins": [
                {"id": "a-widget", "version": "2", "installed_here": True,
                 "installed_version": "1", "update_available": True},
                {"id": "b-widget", "version": "1", "installed_here": False},
            ],
        }],
    }
    rendered = peers_view.render_peers_page(catalog, "0.0.1")
    for action in ("/peers/refresh", "/peers/install", "/peers/update"):
        form = _form(rendered, action)
        assert _attr(form, "data-wait", "#peers-result"), action
    assert _attr(rendered, "id", "peers-result")


def test_the_wizard_model_steps_wait_on_its_progress(booted):
    page = _get(booted, "/wizard")
    describe = next(
        f for f in re.findall(r"<form[^>]*>.*?</form>", page, flags=re.S)
        if 'name="description"' in f)
    assert _attr(describe, "data-wait", "#wizard-progress")
    assert _attr(describe, "data-wait-shape", wizard_view.CARD_WAIT_SHAPE)
    assert _attr(describe, "data-wait-label", wizard_view.CARD_WAIT_LABEL)
    assert _attr(page, "id", "wizard-progress")
    headers = booted.exchange()
    status, _h, body = booted.post_json(
        "/wizard/start", {"description": "Show the sales delta every morning."},
        headers)
    assert status == 201, body
    session_id = json.loads(body)["id"]
    answered = _get(booted, f"/wizard/{session_id}")
    answer_form = next(
        f for f in re.findall(r"<form[^>]*>.*?</form>", answered, flags=re.S)
        if "answer" in f and "question" in f and "description" not in f)
    assert _attr(answer_form, "data-wait", "#wizard-progress")
    # The source question only opens the next question, so it keeps the
    # plain panel and the old label.
    assert _attr(answer_form, "data-wait-shape", "panel")
    assert _attr(answer_form, "data-wait-label", wizard_view.QUESTION_WAIT_LABEL)
    assert _attr(answered, "id", "wizard-progress")


def test_a_wizard_answer_that_builds_the_card_draws_the_widget_sketch():
    from agentdesk.wizard.core import questions_for_answers

    answers = {
        "source": "An Excel workbook",
        "show": "The rows behind it",
        "look": "A table",
    }
    page = wizard_view._questions_html({
        "id": "wiz-demo",
        "answers": answers,
        "questions": questions_for_answers(answers),
    })
    forms = re.findall(r"<form[^>]*>.*?</form>", page, flags=re.S)
    update = next(f for f in forms if "When should it update?" in f)
    assert _attr(update, "data-wait-shape", wizard_view.CARD_WAIT_SHAPE)
    assert _attr(update, "data-wait-label", wizard_view.CARD_WAIT_LABEL)
    show = next(f for f in forms if "What should the tile show?" in f)
    assert _attr(show, "data-wait-shape", "panel")
    assert _attr(show, "data-wait-label", wizard_view.QUESTION_WAIT_LABEL)


# -- F5: the result page says the outcome and holds the heading ----------


def test_the_assistant_result_page_has_a_status_line_and_a_focusable_heading(booted):
    status, out, page = _post_form(
        booted, "/assistant/ask", {"question": "what changed?"}, follow=True)
    assert status == 200
    # The sentence itself, in the one line status_line renders: the shell
    # always carries a hidden role="status" note, so matching the role
    # alone would pass with the notice deleted.
    assert ('<p class="page-status" role="status">Your answer is below.</p>'
            in page)
    assert "<h1>" in page or "<h1 " in page
    assert "heading.setAttribute('tabindex', '-1')" in pages.APP_JS
    assert "heading.focus()" in pages.APP_JS


def test_the_agents_result_page_has_a_status_line_and_a_focusable_heading(booted):
    status, out, page = _post_form(
        booted, "/agents/run",
        {"agent": "worksheet-brief", "brief": "the Q3 review"}, follow=True)
    assert status == 200
    assert ('<p class="page-status" role="status">Ran Worksheet brief. '
            "Its receipt is at the top of the run history.</p>") in page
    assert "<h1>" in page or "<h1 " in page


def test_the_memory_result_page_has_a_status_line_and_a_focusable_heading(booted):
    booted.server.memory.add("Priya Shah owns the Acme renewal.", source="page")
    status, out, page = _post_form(
        booted, "/memory/recall", {"query": "Acme renewal"}, follow=True)
    assert status == 200
    # The notice element itself, not the maintenance button's words.
    assert re.search(
        r'<p class="page-status"(?: id="memory-notice")? role="status">'
        r"Here is what the assistant would recall, best match first\.</p>",
        page,
    ), page
    assert "<h1>" in page or "<h1 " in page


# -- F5: dead ends keep the typed words and name the cause ---------------


def test_a_blank_fact_re_renders_the_memory_form_with_the_cause(booted):
    status, _headers, body = _post_form(booted, "/memory/add", {"text": "  "})
    assert status == 200, status
    page = body.decode("utf-8")
    assert "text/html" in _headers.get("Content-Type", "")
    assert "Type a fact first" in page
    assert 'action="/memory/add"' in page
    assert not page.lstrip().startswith("{")


def test_a_blank_agent_brief_re_renders_the_form_with_the_typed_agent(booted):
    status, _headers, body = _post_form(
        booted, "/agents/run",
        {"agent": "worksheet-brief", "brief": "   "})
    assert status == 200, status
    page = body.decode("utf-8")
    assert "Type a brief first" in page
    assert 'value="worksheet-brief"' in page
    assert not page.lstrip().startswith("{")


def test_an_invalid_timeout_keeps_the_typed_value_and_names_the_cause(booted):
    status, headers, _body = _post_form(
        booted, "/settings/endpoint/save", {"presentationTimeout": "999"})
    assert status == 303, status
    assert "presentation_timeout=999" in headers["Location"]
    page = _get(booted, headers["Location"])
    assert 'value=\'999\'' in page or 'value="999"' in page
    assert "from 5 to 300" in page


def test_a_peer_pairing_refusal_keeps_the_typed_address_and_code(booted):
    status, headers, _body = _post_form(
        booted, "/peers/pair",
        {"address": "not-an-address", "code": "ABCD2345"})
    assert status == 303, status
    page = _get(booted, headers["Location"])
    assert 'value="not-an-address"' in page
    assert 'value="ABCD2345"' in page
    assert "not a host:port address" in page


def test_the_escalated_wizard_page_keeps_the_answers():
    page = wizard_view.render_wizard_page({
        "id": "wiz-1",
        "state": "escalated",
        "description": "Show the sales delta every morning.",
        "answers": {"source": "An Excel workbook", "show": "One status line"},
        "cannot": "This needs a code path the wizard cannot write.",
    }, "0.0.1")
    assert "You chose" in page
    assert "An Excel workbook" in page
    assert "One status line" in page


# -- the toggles work with the script off --------------------------------


def test_every_settings_toggle_is_its_own_form(booted):
    page = _get(booted, "/settings")
    forms = re.findall(
        r"<form[^>]*action=[\"']/settings/toggle[\"'][^>]*>.*?</form>",
        page, flags=re.S)
    keys = {re.search(r"name=[\"']key[\"'] value=[\"']([^\"']+)", form).group(1)
            for form in forms}
    for key in ("sample_data", "mail_enabled", "memory_auto_approve",
                "autonomy", "skills_auto_create"):
        assert key in keys, key
    for form in forms:
        assert 'type="submit"' in form or 'type=\'submit\'' in form
    # The inbox empty state's offer is the same route and stays a form.
    inbox = _get(booted, "/inbox")
    assert _attr(inbox, "action", "/settings/toggle")
    assert _attr(inbox, "value", "sample_data")


def test_the_toggle_form_posts_back_to_its_section_without_script(booted):
    page = _get(booted, "/settings")
    form = next(
        f for f in re.findall(
            r"<form[^>]*action=[\"']/settings/toggle[\"'][^>]*>.*?</form>",
            page, flags=re.S)
        if "memory_auto_approve" in f)
    assert "return_to" in form
    status, headers, _body = _post_form(
        booted, "/settings/toggle",
        {"key": "memory_auto_approve", "return_to": "/settings#memory"})
    assert status == 303, status
    assert headers["Location"] == "/settings#memory"
    assert booted.server.settings.get("memory_auto_approve") is not None


def test_a_settings_toggle_flip_still_works_without_script(booted, monkeypatch,
                                                           tmp_path):
    # Toggling mail on constructs the default watcher and polls it once,
    # so the same two pins the settings module's feeder toggles carry
    # keep that poll away from any real folder and real data folder.
    monkeypatch.delenv("AGENTDESK_MAIL_FOLDER", raising=False)
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    before = booted.server.settings.get("mail_enabled")
    status, headers, _body = _post_form(
        booted, "/settings/toggle",
        {"key": "mail_enabled", "return_to": "/settings#tools"})
    assert status == 303
    assert headers["Location"] == "/settings#tools"
    assert booted.server.settings.get("mail_enabled") != before
