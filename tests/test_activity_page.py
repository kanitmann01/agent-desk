"""The activity page: the decision log, newest first (ticket #41).

The donor approvals module's activity page, on this app's audit store:
inbox decisions (approved, denied, edited, snoozed, more-info, pending)
rendered newest first, in the server-rendered design language, and the
settings page links it. Also covers the what-this-touches honesty for
the new vocabulary and the plugin lifecycle rows.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.assistant.audit import VOCABULARY


@pytest.fixture()
def env():
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _add_and_decide(env, auth):
    """Two cards whose decisions produce one row per vocabulary word."""
    cards = []
    for title in ("First card", "Second card"):
        status, _h, body = env.post_json("/inbox/cards", {
            "kind": "suggestion", "origin": "origin line", "title": title,
            "body": "body", "actionLabel": "Accept"}, auth)
        assert status == 201
        cards.append(json.loads(body))
    first, second = cards
    env.post_json(f"/inbox/cards/{first['id']}/edit", {"draft": "the draft"}, auth)
    env.post_json(f"/inbox/cards/{first['id']}/snooze", {"choice": "1h"}, auth)
    env.post_json(f"/inbox/cards/{first['id']}/more-info",
                  {"instruction": "add the margin column"}, auth)
    env.post_json(f"/inbox/cards/{first['id']}/accept", {}, auth)
    env.post_json(f"/inbox/cards/{second['id']}/dismiss", {}, auth)
    return first, second


def test_the_activity_page_is_one_trail_under_settings(env, auth):
    status, headers, body = env.request("GET", "/activity", auth)
    assert status == 302
    assert headers["Location"] == "/settings/activity"
    _add_and_decide(env, auth)
    status, _h, body = env.request("GET", "/settings/activity", auth)
    assert status == 200
    page = body.decode("utf-8")
    for word in ("approved", "denied", "edited", "snoozed", "more-info"):
        assert word in page
    # Newest first, asserted on the table-row markup (the intro
    # paragraph names the words too, so bare words would be vacuous):
    # the dismissal (last action) precedes the edit (first action).
    assert page.index("<b>denied</b>") < page.index("<b>edited</b>")
    assert "add the margin column" in page


def test_the_trail_carries_non_decisions_too(env, auth):
    # The old page sent model calls to the CSV export; that split hid the
    # desk's own record from the screen. One trail shows the row and the
    # action code, and the export still carries it byte for byte.
    audit_store.record(env.server.audit_conn, "llm.research",
                       target="https://llm.example", detail="a question")
    _add_and_decide(env, auth)
    page = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "Model call" in page
    assert "llm.research" in page
    assert "a question" in page
    csv = env.request("GET", "/audit/export.csv", auth)[2].decode("utf-8")
    assert "llm.research" in csv


def test_the_questions_you_asked_sit_on_the_same_screen(env, auth):
    env.server.activity_log.record("research", "what changed in the margin?")
    page = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "Questions you asked" in page
    assert "what changed in the margin?" in page


def test_the_trail_keeps_older_rows_inside_its_window(env, auth):
    # The trail asks the store for 300 rows; the background polls (hourly
    # excel, half-hourly calendar) would fill a 100-row window in days.
    audit_store.record(env.server.audit_conn, "inbox.denied",
                       target="old-card", detail="a decision from before the noise")
    for i in range(100):
        audit_store.record(env.server.audit_conn, "excel.poll",
                           detail=f"poll {i}")
    page = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "<b>denied</b>" in page
    assert "a decision from before the noise" in page
    assert "101 entries" in page


def test_the_summary_counts_the_decision_family_once(env, auth):
    # inbox.* and demo.* both speak as Decision. The summary groups them;
    # it must not print the same label twice with split counts.
    audit_store.record(env.server.audit_conn, "inbox.denied",
                       target="old-card", detail="one")
    audit_store.record(env.server.audit_conn, "demo.cleared",
                       target="demo.cleared", detail="two")
    page = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "2 decision" in page
    # A target that only echoes the action code is not worth a column.
    assert "two demo.cleared" not in page


def test_the_trail_empty_state_names_what_will_appear(env, auth):
    page = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "Nothing recorded yet" in page
    assert "newest first" in page


def test_settings_page_links_the_activity_page(env, auth):
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert 'href="/settings/activity"' in page
    assert "Open the activity trail" in page


def test_pending_word_appears_when_a_snooze_returns(env, auth):
    status, _h, body = env.post_json("/inbox/cards", {
        "kind": "brief", "origin": "origin", "title": "Morning brief",
        "body": "body"}, auth)
    card = json.loads(body)
    # A snooze in the past is due immediately: the next read returns it
    # and logs the return as pending.
    env.server.inbox.snooze(card["id"], env.server.inbox.now_ts() - 10)
    env.request("GET", "/widgets/inbox", auth)
    page = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "pending" in page
    assert "snooze returned" in page


def test_the_kind_filter_shows_one_family(env, auth):
    audit_store.record(env.server.audit_conn, "llm.research",
                       target="https://llm.example", detail="a question")
    audit_store.record(env.server.audit_conn, "inbox.denied",
                       target="old-card", detail="a decision")
    page = env.request("GET", "/settings/activity?kind=Model%20call", auth)[2].decode("utf-8")
    assert "llm.research" in page
    assert "<b>denied</b>" not in page
    assert "1 model call entries" in page
    assert "Questions you asked" not in page
    assert "href='/settings/activity'" in page


def test_an_unknown_kind_falls_back_to_the_whole_trail(env, auth):
    audit_store.record(env.server.audit_conn, "inbox.denied",
                       target="old-card", detail="a decision")
    page = env.request("GET", "/settings/activity?kind=Nonsense", auth)[2].decode("utf-8")
    assert "<b>denied</b>" in page
    assert "1 entries" in page
