"""Wizard seam tests: describe, build, preview, approve, escalate.

The acceptance criteria are API tests; the compiler's unit tests live in
test_wizard_core.py. Here the wizard runs through the real server with a
stub corporate endpoint, and installs go through the real plugin runtime.
"""

import json
import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.inbox.store import InboxStore
from agentdesk.plugins.runtime import PluginRuntime

CANONICAL = "Watch this workbook and show me the latest figure"
NOW = datetime(2026, 11, 11, 9, 0, 0).astimezone()
# The prompt marker the autofill fake branches on, so the copy and the fill
# can answer differently without depending on prompt ordering.
AUTOFILL_MARKER = "Fill in the four choices"


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now


def make_runtime(tmp_path):
    return PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now="2026-11-11T09:00:00",
    )


def good_llm(prompt: str) -> str:
    """A corporate endpoint that answers the wizard's JSON asks sanely.

    It fills a workbook tile and writes its copy; it never decides a source,
    a permission, or an activation event.
    """
    if AUTOFILL_MARKER in prompt:
        return json.dumps({
            "source": "An Excel workbook",
            "detail": "",
            "show": "The latest figure",
            "look": "A big number",
            "update": "When I open the desk",
            "reasons": {"source": "It reads the workbook you keep your numbers in."},
        })
    return json.dumps({
        "title": "Sales, last 24 hours",
        "description": "The latest figure in the watched workbook.",
    })


def two_field_llm(prompt: str) -> str:
    """An endpoint that fills only the source, leaving the rest to the walk."""
    if AUTOFILL_MARKER in prompt:
        return json.dumps({"source": "An Excel workbook"})
    return good_llm(prompt)


WORKBOOK_ANSWERS = {
    "source": "An Excel workbook",
    "show": "The latest figure",
    "look": "A big number",
    "update": "When I open the desk",
}


def answer_all(booted, session_id, headers):
    """Answer the remaining questions on a session with one JSON post.

    The questions are computed from the answers, so this drives the walk the
    way a manager does: every open choice answered, in one call.
    """
    return booted.post_json(f"/wizard/{session_id}/answer",
                            {"answers": WORKBOOK_ANSWERS}, headers)


@pytest.fixture()
def env(tmp_path):
    clock = FakeClock(NOW)
    from agentdesk.wizard.core import WizardStore

    booted = server_harness.Booted(
        plugins=make_runtime(tmp_path),
        inbox_store=InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
        wizard_store=WizardStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
        llm=good_llm,
    )
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def test_wizard_requires_a_session(env):
    status, _h, _b = env.post_json("/wizard/start", {"description": CANONICAL},
                                   env.host_header())
    assert status == 401


def test_get_wizard_requires_a_session(env):
    # The start form lives behind the same gate as every other page.
    status, _h, _b = env.request("GET", "/wizard", env.host_header())
    assert status == 401


def test_get_wizard_renders_the_describe_start_form(env, auth):
    """GET /wizard is the entry, not a 404: a POST-less visitor can start
    describing, on the same describing screen the dashboard button uses."""
    status, _h, body = env.request("GET", "/wizard", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "Describe a plugin" in page
    assert "<textarea" in page
    assert 'action="/wizard/new/answer"' in page
    # The focused shell, not the dashboard chrome.
    assert 'class="rail"' not in page


def test_get_wizardx_is_still_a_404(env, auth):
    # The route dispatches on the /wizard prefix; only the exact segment
    # may render the start form, a lookalike name is no page.
    status, _h, _b = env.request("GET", "/wizardx", auth)
    assert status == 404


def test_describe_returns_capped_questions_with_defaults(env, auth):
    status, _h, body = env.post_json("/wizard/start", {"description": CANONICAL}, auth)
    payload = json.loads(body)
    assert status == 201
    assert payload["state"] == "questions"
    assert 0 < len(payload["questions"]) <= 5
    for question in payload["questions"]:
        assert question["options"]
        assert question["default"] in question["options"]


def test_build_validates_through_the_gate_before_preview(env, auth, tmp_path):
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    status, _h, _b = answer_all(env, started["id"], auth)
    assert status == 303
    session = env.server.wizard_store.get(started["id"])
    assert session.draft is not None
    # The gate: the draft directory passes the shared validator as-is.
    import tempfile

    from agentdesk.validator.core import validate_plugin

    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp) / "draft"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text(
            json.dumps(session.draft["manifest"], indent=2), encoding="utf-8")
        (plugin_dir / "widget.ui.json").write_text(
            json.dumps(session.draft["ui_schema"], indent=2), encoding="utf-8")
        verdict = validate_plugin(plugin_dir)
        assert verdict.ok, verdict.failures


def test_one_answer_does_not_build_anything(env, auth):
    """Answering a single question re-renders the walk. The old behaviour
    filled every other answer from defaults and installed a workbook."""
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    status, _h, _b = env.post_json(f"/wizard/{started['id']}/answer",
                                   {"answers": {"source": "My mail"}}, auth)

    assert status == 303
    session = env.server.wizard_store.get(started["id"])
    assert session.state == "questions"
    assert session.draft is None
    assert [q["id"] for q in session.questions] == ["source", "show", "update"]
    assert env.server.plugins.list_records() == []


def test_preview_renders_without_installing(env, auth):
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    answer_all(env, started["id"], auth)
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    assert "Filled in from your description" in page
    assert env.server.plugins.list_records() == []


def post_form(booted, path, fields, headers):
    """A browser-shaped POST: form-urlencoded fields, no JavaScript."""
    data = urlencode(fields).encode("utf-8")
    merged = {"Content-Type": "application/x-www-form-urlencoded"}
    merged.update(headers)
    return booted.request("POST", path, merged, data)


def test_describe_form_post_creates_the_session(env, auth):
    status, headers, _b = post_form(env, "/wizard/new/answer",
                                    {"description": CANONICAL}, auth)
    assert status == 303
    assert headers["Location"].startswith("/wizard/wiz-")


def test_answer_form_post_records_the_choice(env, auth):
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    status, _h, _b = post_form(env, f"/wizard/{started['id']}/answer",
                               {"question": "0", "answer": "My calendar"}, auth)
    assert status == 303
    session = env.server.wizard_store.get(started["id"])
    # One answer is not a finished walk: the source is recorded and the
    # questions narrow to that source.
    assert session.state == "questions"
    assert session.answers["source"] == "My calendar"
    assert session.answers["source"] != "An Excel workbook"


def test_reanswering_keeps_the_earlier_custom_answers(env, auth):
    """One form per question, answered one at a time: going back to a later
    form must not throw away the first form's choice."""
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    post_form(env, f"/wizard/{started['id']}/answer",
              {"question": "0", "answer": "My mail"}, auth)
    session = env.server.wizard_store.get(started["id"])
    show_index = next(i for i, q in enumerate(session.questions) if q["id"] == "show")
    status, _h, _b = post_form(env, f"/wizard/{started['id']}/answer",
                               {"question": str(show_index),
                                "answer": "One status line"}, auth)
    assert status == 303
    session = env.server.wizard_store.get(started["id"])
    # The untouched update question keeps its default, as a checked radio:
    # the page never shows an unanswered question as blank.
    assert session.answers == {"source": "My mail", "show": "One status line",
                               "update": "When I open the desk"}


def test_form_answer_with_a_malformed_index_keeps_the_walk_open(tmp_path, monkeypatch):
    """A question field that is digits-shaped but not an int (a Unicode
    superscript) is not a form answer: nothing is recorded and no 500."""
    for name in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY", "AGENTDESK_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    clock = FakeClock(NOW)
    from agentdesk.wizard.core import WizardStore

    booted = server_harness.Booted(
        plugins=make_runtime(tmp_path),
        wizard_store=WizardStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
        inbox_store=InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
    )
    try:
        auth = booted.exchange()
        started = json.loads(booted.post_json("/wizard/start",
                                              {"description": CANONICAL}, auth)[2])
        status, _h, _b = post_form(booted, f"/wizard/{started['id']}/answer",
                                   {"question": "\u00b2", "answer": "My mail"}, auth)
        assert status == 303
        session = booted.server.wizard_store.get(started["id"])
        assert session.state == "questions"
        assert session.answers == {}
        assert booted.server.plugins.list_records() == []
    finally:
        booted.close()


def test_the_no_code_form_flow_installs_through_the_default_runtime(tmp_path, monkeypatch):
    """The flagship flow in production shape: no injected runtime, so
    create_server builds the default one; every step a plain form post."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    from agentdesk.wizard.core import WizardStore

    booted = server_harness.Booted(
        plugins=None,
        wizard_store=WizardStore(
            sqlite3.connect(":memory:", check_same_thread=False), FakeClock(NOW)),
        llm=good_llm,
    )
    try:
        auth = booted.exchange()
        _s, headers, _b = post_form(booted, "/wizard/new/answer",
                                    {"description": CANONICAL}, auth)
        sid = headers["Location"].rsplit("/", 1)[-1]
        status, _h, _b = booted.post_json(f"/wizard/{sid}/answer",
                                          {"answers": WORKBOOK_ANSWERS}, auth)
        assert status == 303
        status, _h, _b = post_form(booted, f"/wizard/{sid}/approve", {}, auth)
        assert status == 303
        records = booted.server.plugins.list_records()
        assert [r["state"] for r in records] == ["enabled"]
        assert (tmp_path / "plugins").is_dir()
    finally:
        booted.close()


def test_approve_installs_in_pilot_mode_with_consolidated_summary(env, auth):
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    answer_all(env, started["id"], auth)
    status, _h, body = env.post_json(f"/wizard/{started['id']}/approve", {}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "installed"
    assert payload["pilot"] is True
    summary = payload["summary"]
    assert summary["does"]
    # The workbook build names the setup handoff, not a fabricated glob (T2).
    assert summary["reads"] == ["a workbook you pick in setup"]
    assert any("no code" in line.lower() for line in summary["never"])
    assert summary["remove"]
    records = env.server.plugins.list_records()
    assert len(records) == 1
    assert records[0]["state"] == "enabled"
    assert records[0]["pilot_views_left"] > 0  # pilot mode


def test_approve_json_post_keeps_the_install_document(env, auth):
    """Scripted installs keep today's 200 JSON contract in shape (T1):
    status, pilot, summary, install. The form-post redirect changes
    nothing for a client that asked for JSON."""
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    answer_all(env, started["id"], auth)
    status, headers, body = env.post_json(f"/wizard/{started['id']}/approve", {}, auth)
    payload = json.loads(body)
    assert status == 200
    assert "application/json" in headers["Content-Type"]
    assert set(payload) == {"status", "pilot", "summary", "install"}
    assert payload["status"] == "installed"
    assert payload["pilot"] is True
    install = payload["install"]
    assert install["ok"] is True
    assert install["pilot"] is True
    assert install["id"]
    assert install["version"]


def test_approve_form_post_redirects_to_the_approved_screen(env, auth):
    """The reproduced bug (T1): a plain form post to approve answered
    200 JSON and parked the browser on the raw response document. Now
    the form post redirects to the session page, which renders the
    approved screen: what was installed, the pilot line, the summary,
    and no raw JSON anywhere."""
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    answer_all(env, started["id"], auth)
    status, headers, body = post_form(env, f"/wizard/{started['id']}/approve", {}, auth)
    assert status == 303
    assert headers["Location"] == f"/wizard/{started['id']}"
    assert b'"status"' not in body  # no response document on the form post
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    records = env.server.plugins.list_records()
    assert len(records) == 1  # installed exactly once
    assert records[0]["id"] in page
    assert records[0]["active_version"] in page
    assert "in pilot mode" in page  # the pilot line
    assert "What it does" in page  # the does/reads/never summary
    assert "Delete it from the Plugins surface" in page  # the removal hint
    assert "marketplace" in page  # the call to action names its surface
    assert '"status"' not in page  # no raw JSON anywhere on the page


def test_second_approve_form_post_refuses_and_never_installs_twice(env, auth):
    """Approve stays idempotent-refusing (T1): a second form post cannot
    install again. The form client lands back on the session page, which
    shows the state the session is honestly in; the JSON client keeps
    the existing 409 refusal."""
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    answer_all(env, started["id"], auth)
    post_form(env, f"/wizard/{started['id']}/approve", {}, auth)
    status, headers, body = post_form(env, f"/wizard/{started['id']}/approve", {}, auth)
    assert status == 303
    assert headers["Location"] == f"/wizard/{started['id']}"
    assert b'"error"' not in body  # a form post never gets the raw refusal
    assert len(env.server.plugins.list_records()) == 1
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    assert "Added" in page  # the approved screen, not a raw JSON page
    status, _h, body = env.post_json(f"/wizard/{started['id']}/approve", {}, auth)
    assert status == 409
    assert json.loads(body)["error"] == "wizard:not-in-preview"
    assert len(env.server.plugins.list_records()) == 1


def test_unknown_session_actions_answer_the_stores_404(env, auth):
    """A stale or wrong session id is a client error: every wizard action
    surfaces the store's own not-found, never the generic restart page.
    The form client gets the honest error page, the JSON client the
    store's named error (spec 017, 7b)."""
    status, _h, body = post_form(env, "/wizard/wiz-missing/approve", {}, auth)
    assert status == 404
    page = body.decode("utf-8")
    assert "Nothing here" in page
    assert "no wizard session wiz-missing" in page
    status, _h, body = env.post_json("/wizard/wiz-missing/approve", {}, auth)
    assert status == 404
    payload = json.loads(body)
    assert payload["error"] == "wizard:unknown"
    assert payload["message"] == "no wizard session wiz-missing"
    # The other two actions answer the same store error, not a 500.
    assert env.post_json("/wizard/wiz-missing/answer", {}, auth)[0] == 404
    assert env.post_json("/wizard/wiz-missing/escalate", {}, auth)[0] == 404


def test_wizard_completes_with_no_endpoint_configured(tmp_path, monkeypatch):
    """The deterministic path is a first-class path (#62): with no
    endpoint configured anywhere, start asks the standard questions, the
    page names why, and answer/approve still install."""
    for name in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY", "AGENTDESK_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    from agentdesk.wizard.core import DEFAULT_QUESTIONS, WizardStore

    clock = FakeClock(NOW)
    booted = server_harness.Booted(
        plugins=make_runtime(tmp_path),
        wizard_store=WizardStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
        inbox_store=InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
    )
    try:
        auth = booted.exchange()
        started = json.loads(booted.post_json("/wizard/start",
                                              {"description": CANONICAL}, auth)[2])
        assert [q["id"] for q in started["questions"]] == ["source"]
        # The walk invites an AI connection in place of the old error alert.
        page = booted.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
        assert "Add an AI connection" in page
        assert "/settings#connections" in page
        assert booted.post_json(f"/wizard/{started['id']}/answer",
                                {"answers": WORKBOOK_ANSWERS}, auth)[0] == 303
        status, _h, body = booted.request("POST", f"/wizard/{started['id']}/approve",
                                          auth, b"")
        assert status == 200
        assert json.loads(body)["status"] == "installed"
        assert [r["state"] for r in booted.server.plugins.list_records()] == ["enabled"]
    finally:
        booted.close()


def test_the_full_no_js_walk_ends_on_an_approved_page(tmp_path, monkeypatch):
    """The reproduced walk (T1), end to end with no JavaScript anywhere:
    start, describe, answer, approve. Every form post answers with a
    page or a redirect, so the walk never parks on a raw JSON document."""
    for name in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY", "AGENTDESK_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    clock = FakeClock(NOW)
    from agentdesk.wizard.core import WizardStore

    booted = server_harness.Booted(
        plugins=make_runtime(tmp_path),
        wizard_store=WizardStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
        inbox_store=InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
    )
    try:
        auth = booted.exchange()
        # The Plugins page's button: an empty start asks for the words, on
        # a page, not a document.
        status, headers, body = post_form(booted, "/wizard/start", {}, auth)
        assert status == 200
        assert "text/html" in headers["Content-Type"]
        assert 'action="/wizard/new/answer"' in body.decode("utf-8")
        # The words make the session; the questions screen renders.
        status, headers, _b = post_form(booted, "/wizard/new/answer",
                                        {"description": CANONICAL}, auth)
        assert status == 303
        sid = headers["Location"].rsplit("/", 1)[-1]
        page = booted.request("GET", f"/wizard/{sid}", auth)[2].decode("utf-8")
        assert "What should this tile watch?" in page  # the source question
        # Answer the whole path, then the preview with its approve form.
        status, _h, _b = booted.post_json(f"/wizard/{sid}/answer",
                                          {"answers": WORKBOOK_ANSWERS}, auth)
        assert status == 303
        page = booted.request("GET", f"/wizard/{sid}", auth)[2].decode("utf-8")
        assert f'action="/wizard/{sid}/approve"' in page
        # Add widget: the form post redirects; no document parks anywhere.
        status, headers, body = post_form(booted, f"/wizard/{sid}/approve", {}, auth)
        assert status == 303
        assert headers["Location"] == f"/wizard/{sid}"
        assert b"{" not in body
        page = booted.request("GET", f"/wizard/{sid}", auth)[2].decode("utf-8")
        assert "Added" in page
        records = booted.server.plugins.list_records()
        assert [r["state"] for r in records] == ["enabled"]
        # The workbook build reads no glob (T2): the approval summary
        # names the setup handoff, and the call to action is the manage
        # surface where that setup lives.
        assert "a workbook you pick in setup" in page
        assert "reports/*.xlsx" not in page
        assert "Set up its data" in page
    finally:
        booted.close()


def test_a_workbook_install_lands_in_setup_with_its_dashboard_card(tmp_path, monkeypatch):
    """T2: the config-backed workbook build installs into the setup
    state (no file was ever granted), and the dashboard renders its
    wireframe card keyed by the plugin id, the same card the bundled
    tracker shows before its first instance exists."""
    for name in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY", "AGENTDESK_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    clock = FakeClock(NOW)
    from agentdesk.wizard.core import WizardStore

    booted = server_harness.Booted(
        plugins=make_runtime(tmp_path),
        wizard_store=WizardStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
        inbox_store=InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
    )
    try:
        auth = booted.exchange()
        started = json.loads(booted.post_json("/wizard/start",
                                              {"description": CANONICAL}, auth)[2])
        assert booted.post_json(f"/wizard/{started['id']}/answer",
                                {"answers": WORKBOOK_ANSWERS}, auth)[0] == 303
        status, _h, _b = post_form(booted, f"/wizard/{started['id']}/approve", {}, auth)
        assert status == 303
        records = booted.server.plugins.list_records()
        assert [r["state"] for r in records] == ["enabled"]
        assert records[0]["pilot_views_left"] > 0  # pilot mode, as always
        plugin_id = records[0]["id"]
        assert plugin_id.startswith("wizard-")
        status, _h, body = booted.request("GET", "/api/dashboard", auth)
        assert status == 200
        cards = json.loads(body)["plugins"]["cards"]
        card = next(item for item in cards if item["id"] == plugin_id)
        assert card["freshness"] == "setup"
        assert card["payload"]["setup"]["pluginId"] == plugin_id
        assert card["payload"]["setup"]["step"] == "source"
        assert card["payload"]["elements"] == []
    finally:
        booted.close()


def test_wizard_with_an_endpoint_does_not_claim_it_is_missing(env, auth):
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    assert "Add an AI connection" not in page


def test_the_fill_is_reported_and_every_field_can_be_changed(env, auth):
    """The one autofill state ticket 08 covers at the API level: the
    description filled the fields in, the session says so, and the answers
    it produced are the vocabulary's labels."""
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])

    assert started["autofilled"] is True
    assert started["answers"] == WORKBOOK_ANSWERS
    # Nothing is left to ask, so the walk lands straight on the preview.
    session = env.server.wizard_store.get(started["id"])
    assert session.questions == [] or all(
        question["id"] in session.answers for question in session.questions)
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    assert "Filled in from your description" in page


def test_a_partial_fill_leaves_the_rest_asking(env, auth):
    """An endpoint that fills only one field leaves the others open: the
    fill is never completed with a default behind the manager's back."""
    env.server.llm = two_field_llm
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])

    assert started["answers"] == {"source": "An Excel workbook"}
    assert [q["id"] for q in started["questions"]] == ["source", "show", "update"]


def test_wizard_names_the_cause_when_the_saved_base_is_malformed(tmp_path, monkeypatch):
    """A malformed saved base makes every consult raise, so the
    questions are the standard ones: the note must say so instead of
    implying endpoint-shaped questions that never arrive (#62 review)."""
    for name in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY", "AGENTDESK_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    from agentdesk.wizard.core import DEFAULT_QUESTIONS, WizardStore

    clock = FakeClock(NOW)
    booted = server_harness.Booted(
        plugins=make_runtime(tmp_path),
        wizard_store=WizardStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
        inbox_store=InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
    )
    try:
        # The unreachable shape a bad save (or an older one) leaves in
        # the store: a base that can never answer.
        booted.server.settings.set("llm_base", "llm.corp.example/v1")
        auth = booted.exchange()
        started = json.loads(booted.post_json("/wizard/start",
                                              {"description": CANONICAL}, auth)[2])
        assert [q["id"] for q in started["questions"]] == ["source"]
        assert started["autofilled"] is False
        page = booted.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
        assert "Add an AI connection" in page
    finally:
        booted.close()


def test_form_body_fields_maps_each_field_to_its_first_value():
    from agentdesk.server.app import form_body_fields

    fields = form_body_fields(b"question=0&answer=hourly&answer=daily&blank=")
    assert fields == {"question": "0", "answer": "hourly"}


def test_form_body_fields_refuses_undecodable_bytes():
    from agentdesk.server.app import form_body_fields

    assert form_body_fields(b"\xff\xfe=x") is None


def test_unbuildable_escalates_and_preserves_the_words(env, auth):
    def hostile(prompt):
        return good_llm(prompt)

    env.server.llm = hostile
    words = "Run a script every morning that sends the report to my boss"
    started = json.loads(env.post_json("/wizard/start", {"description": words}, auth)[2])
    status, _h, _b = env.post_json(f"/wizard/{started['id']}/answer",
                                   {"answers": WORKBOOK_ANSWERS}, auth)
    assert status == 303
    inbox = json.loads(env.request("GET", "/widgets/inbox", auth)[2])
    assert inbox["waiting"] >= 1  # the feature-request card
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    assert words in page  # the user's full input, shown back
    assert env.server.plugins.list_records() == []  # no partial install


def test_repair_cap_is_capped_and_observable_then_escalates(env, auth, monkeypatch):
    """The repair budget still bounds a draft that will not validate. The
    composer is what makes it broken here, since a model can no longer
    choose the manifest at all."""
    from agentdesk import wizard as wizard_pkg

    def always_broken_compose(self, **_kwargs):
        return ({"schemaVersion": 1, "id": "wizard-broken", "name": "Broken",
                 "version": "not-semver", "publisher": "agent-desk-wizard",
                 "class": "declarative",
                 "engines": {"dashboardHost": ">=1.0.0 <2.0.0"},
                 "license": "MIT",
                 "permissions": {"filesystem": {"read": [], "write": ["${pluginData}"]},
                                 "network": {"allow": []}, "llm": {"allow": False},
                                 "shell": "none"},
                 "activationEvents": ["onWidget:broken"],
                 "contributes": {"widgets": [{
                     "id": "broken", "size": "2x1",
                     "dataSource": {"type": "excel-watch"},
                     "render": {"type": "bogus-render"}}]}},
                {"type": "card", "title": "Broken", "elements": []})

    monkeypatch.setattr(wizard_pkg.WizardCompiler, "_compose", always_broken_compose)
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    status, _h, _b = env.post_json(f"/wizard/{started['id']}/answer",
                                   {"answers": WORKBOOK_ANSWERS}, auth)
    assert status == 303
    session = env.server.wizard_store.get(started["id"])
    assert session.attempts <= 3  # capped
    assert session.attempts >= 1  # observable: the counter really moved
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    assert "cannot" in page.lower()  # the honest dead-end renders
    assert env.server.plugins.list_records() == []  # no broken install


def test_escalate_endpoint_exports_the_feature_request(env, auth):
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    status, _h, _b = env.post_json(f"/wizard/{started['id']}/escalate", {}, auth)
    assert status == 303
    inbox = json.loads(env.request("GET", "/widgets/inbox", auth)[2])
    assert inbox["waiting"] >= 1


def test_the_describe_door_opens_the_describe_page(env, auth):
    # The wizard's door is the "Describe a plugin in plain English" button
    # on the Plugins page (spec 022): a plain form post with no fields. The
    # home screen no longer carries it.
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert "/wizard/start" not in page
    assert 'disabled title="The plugin wizard' not in page
    # The empty start lands on the describe screen: a textarea whose
    # answer creates the session.
    status, _h, body = env.post_json("/wizard/start", {"description": ""}, auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "<textarea" in page
    assert 'action="/wizard/new/answer"' in page
    # Typing the words there creates the real session.
    status, _h, _b = env.post_json("/wizard/new/answer", {"description": CANONICAL}, auth)
    assert status == 303
