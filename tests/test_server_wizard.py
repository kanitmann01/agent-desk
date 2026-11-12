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

CANONICAL = "Watch this workbook and show me the 24-hour change"
NOW = datetime(2026, 11, 11, 9, 0, 0).astimezone()


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
    """A corporate endpoint that answers the wizard's JSON asks sanely."""
    if "question" in prompt or "clarif" in prompt:
        return json.dumps({"questions": [
            {"id": "cadence", "question": "How often should it refresh?",
             "options": ["hourly", "every 15 minutes"], "default": "hourly"},
        ]})
    return json.dumps({
        "title": "Sales, last 24 hours",
        "description": "What changed in the watched workbook since yesterday.",
    })


def two_question_llm(prompt: str) -> str:
    """The same sane endpoint, but asking two questions."""
    if "question" in prompt or "clarif" in prompt:
        return json.dumps({"questions": [
            {"id": "cadence", "question": "How often should it refresh?",
             "options": ["hourly", "every 15 minutes"], "default": "hourly"},
            {"id": "source", "question": "Which file should it read?",
             "options": ["orders.xlsx", "returns.xlsx"], "default": "orders.xlsx"},
        ]})
    return good_llm(prompt)


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
    status, _h, _b = env.post_json(f"/wizard/{started['id']}/answer", {}, auth)
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


def test_preview_renders_without_installing(env, auth):
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    env.post_json(f"/wizard/{started['id']}/answer", {}, auth)
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    assert "Atlas ERP" in page  # the fixture sample rows render
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
                               {"question": "0", "answer": "every 15 minutes"}, auth)
    assert status == 303
    session = env.server.wizard_store.get(started["id"])
    assert session.state == "preview"
    assert session.answers["cadence"] == "every 15 minutes"


def test_reanswering_keeps_the_earlier_custom_answers(env, auth):
    """One form per question, answered one at a time: going back to the
    second form must not throw away the first form's choice."""
    env.server.llm = two_question_llm
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    post_form(env, f"/wizard/{started['id']}/answer",
              {"question": "0", "answer": "every 15 minutes"}, auth)
    status, _h, _b = post_form(env, f"/wizard/{started['id']}/answer",
                               {"question": "1", "answer": "returns.xlsx"}, auth)
    assert status == 303
    session = env.server.wizard_store.get(started["id"])
    assert session.answers == {"cadence": "every 15 minutes",
                               "source": "returns.xlsx"}


def test_form_answer_with_a_malformed_index_uses_the_defaults(env, auth):
    """A question field that is digits-shaped but not an int (a Unicode
    superscript) is not a form answer: defaults apply, no 500."""
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    status, _h, _b = post_form(env, f"/wizard/{started['id']}/answer",
                               {"question": "\u00b2", "answer": "hourly"}, auth)
    assert status == 303
    session = env.server.wizard_store.get(started["id"])
    assert session.state == "preview"
    assert session.answers == {"cadence": "hourly"}


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
        status, _h, _b = post_form(booted, f"/wizard/{sid}/answer",
                                   {"question": "0", "answer": "hourly"}, auth)
        assert status == 303
        status, _h, body = booted.request("POST", f"/wizard/{sid}/approve", auth, b"")
        assert status == 200
        assert json.loads(body)["status"] == "installed"
        records = booted.server.plugins.list_records()
        assert [r["state"] for r in records] == ["enabled"]
        assert (tmp_path / "plugins").is_dir()
    finally:
        booted.close()


def test_approve_installs_in_pilot_mode_with_consolidated_summary(env, auth):
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    env.post_json(f"/wizard/{started['id']}/answer", {}, auth)
    status, _h, body = env.post_json(f"/wizard/{started['id']}/approve", {}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "installed"
    assert payload["pilot"] is True
    summary = payload["summary"]
    assert summary["does"]
    assert summary["reads"]
    assert any("no code" in line.lower() for line in summary["never"])
    assert summary["remove"]
    records = env.server.plugins.list_records()
    assert len(records) == 1
    assert records[0]["state"] == "enabled"
    assert records[0]["pilot_views_left"] > 0  # pilot mode


def test_form_body_fields_maps_each_field_to_its_first_value():
    from agentdesk.server.app import form_body_fields

    fields = form_body_fields(b"question=0&answer=hourly&answer=daily&blank=")
    assert fields == {"question": "0", "answer": "hourly"}


def test_form_body_fields_refuses_undecodable_bytes():
    from agentdesk.server.app import form_body_fields

    assert form_body_fields(b"\xff\xfe=x") is None


def test_unbuildable_escalates_and_preserves_the_words(env, auth):
    def hostile(prompt):
        if "vocabulary" in prompt:
            return json.dumps({"buildable": False,
                               "reason": "this needs executable script logic"})
        return good_llm(prompt)

    env.server.llm = hostile
    words = "Run a script every morning that sends the report to my boss"
    started = json.loads(env.post_json("/wizard/start", {"description": words}, auth)[2])
    status, _h, _b = env.post_json(f"/wizard/{started['id']}/answer", {}, auth)
    assert status == 303
    inbox = json.loads(env.request("GET", "/widgets/inbox", auth)[2])
    assert inbox["waiting"] >= 1  # the feature-request card
    page = env.request("GET", f"/wizard/{started['id']}", auth)[2].decode("utf-8")
    assert words in page  # the user's full input, shown back
    assert env.server.plugins.list_records() == []  # no partial install


def test_repair_cap_is_capped_and_observable_then_escalates(env, auth):
    def always_broken(prompt):
        return json.dumps({
            "title": "Broken",
            "description": "broken",
            "manifest": {
                "schemaVersion": 1, "id": "broken-widget", "version": "not-semver",
                "publisher": "wizard", "class": "declarative", "license": "MIT",
                "permissions": {"filesystem": {"read": ["${workspace}/x.xlsx"]}},
                "contributes": {"widgets": [{"id": "w", "size": "2x1",
                                             "dataSource": {"type": "excel-watch"},
                                             "render": {"type": "bogus-render"}}]},
            },
        })

    env.server.llm = always_broken
    started = json.loads(env.post_json("/wizard/start", {"description": CANONICAL}, auth)[2])
    status, _h, _b = env.post_json(f"/wizard/{started['id']}/answer", {}, auth)
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


def test_add_plugin_button_opens_the_describe_page(env, auth):
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert "/wizard/start" in page
    assert 'disabled title="The plugin wizard' not in page
    # The empty start (the dashboard button) lands on the describe screen:
    # a textarea whose answer creates the session.
    status, _h, body = env.post_json("/wizard/start", {"description": ""}, auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "<textarea" in page
    assert 'action="/wizard/new/answer"' in page
    # Typing the words there creates the real session.
    status, _h, _b = env.post_json("/wizard/new/answer", {"description": CANONICAL}, auth)
    assert status == 303
