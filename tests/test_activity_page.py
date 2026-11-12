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


def test_activity_page_lists_decisions_newest_first(env, auth):
    _add_and_decide(env, auth)
    status, _h, body = env.request("GET", "/activity", auth)
    assert status == 200
    page = body.decode("utf-8")
    for word in ("approved", "denied", "edited", "snoozed", "more-info"):
        assert word in page
    # Newest first, asserted on the table-row markup (the intro
    # paragraph names the words too, so bare words would be vacuous):
    # the dismissal (last action) precedes the edit (first action).
    assert page.index("<b>denied</b>") < page.index("<b>edited</b>")
    assert "add the margin column" in page


def test_activity_page_leaves_non_decisions_to_the_audit_export(env, auth):
    audit_store.record(env.server.audit_conn, "llm.research",
                       target="https://llm.example", detail="a question")
    _add_and_decide(env, auth)
    page = env.request("GET", "/activity", auth)[2].decode("utf-8")
    assert "llm.research" not in page
    assert "a question" not in page
    csv = env.request("GET", "/audit/export.csv", auth)[2].decode("utf-8")
    assert "llm.research" in csv  # the export still carries everything


def test_activity_page_keeps_decisions_past_the_audit_noise(env, auth):
    # The audit tail's default window is 100 rows; the background polls
    # (hourly excel, half-hourly calendar) fill that in a couple of days.
    # A page that claims every decision must filter in the store, not
    # after an arbitrary limit.
    audit_store.record(env.server.audit_conn, "inbox.denied",
                       target="old-card", detail="a decision from before the noise")
    for i in range(100):
        audit_store.record(env.server.audit_conn, "excel.poll",
                           detail=f"poll {i}")
    page = env.request("GET", "/activity", auth)[2].decode("utf-8")
    assert "<b>denied</b>" in page
    assert "a decision from before the noise" in page


def test_activity_page_empty_state_names_what_will_appear(env, auth):
    page = env.request("GET", "/activity", auth)[2].decode("utf-8")
    assert "No decisions yet" in page
    assert "newest first" in page


def test_settings_page_links_the_activity_page(env, auth):
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert 'href="/activity"' in page


def test_pending_word_appears_when_a_snooze_returns(env, auth):
    status, _h, body = env.post_json("/inbox/cards", {
        "kind": "brief", "origin": "origin", "title": "Morning brief",
        "body": "body"}, auth)
    card = json.loads(body)
    # A snooze in the past is due immediately: the next read returns it
    # and logs the return as pending.
    env.server.inbox.snooze(card["id"], env.server.inbox.now_ts() - 10)
    env.request("GET", "/widgets/inbox", auth)
    page = env.request("GET", "/activity", auth)[2].decode("utf-8")
    assert "pending" in page
    assert "snooze returned" in page


# -- what-this-touches honesty ------------------------------------------

def test_vocabulary_names_every_inbox_and_plugin_action_with_statements():
    actions = {action for action, _kind, _statement in VOCABULARY}
    for action in (
        "inbox.approved", "inbox.denied", "inbox.edited", "inbox.snoozed",
        "inbox.more-info", "inbox.pending",
        "plugin.install", "plugin.update", "plugin.consent", "plugin.enable",
        "plugin.disable", "plugin.uninstall", "plugin.rollback",
        "plugin.retest", "plugin.purge-data",
    ):
        assert action in actions
    for _action, _kind, statement in VOCABULARY:
        assert statement.strip()  # every row says what it means


def test_touches_page_shows_the_new_vocabulary(env, auth):
    page = env.request("GET", "/what-this-touches", auth)[2].decode("utf-8")
    assert "inbox.approved" in page
    assert "plugin.install" in page
    # Honest state: nothing has happened yet on this boot.
    assert "not observed yet" in page
