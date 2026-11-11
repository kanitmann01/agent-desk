"""Calendar bridge tests through the real HTTP seam.

The fixture calendar JSON is literally dropped into the watched folder
path; the endpoint, the page, the checkbox persistence across a restart
and the walkthrough are exercised the way the manager will meet them.
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.calendar.watcher import Adapters as CalendarAdapters
from agentdesk.calendar.watcher import CalendarBridge
from agentdesk.excel.watcher import ExcelWatch
from agentdesk.server import app as server_app

NOW = datetime(2026, 11, 11, 9, 0, 0).astimezone()

FIXTURE_DOC = {
    "generatedAt": NOW.isoformat(),
    "events": [
        {
            "id": "evt-1",
            "subject": "Q4 pipeline review",
            "start": NOW.replace(hour=14).isoformat(),
            "end": NOW.replace(hour=15).isoformat(),
            "location": "Room Beaufort",
            "attendees": 6,
        }
    ],
}

STUB_LLM = lambda prompt: (  # noqa: E731 - a fixture, not behavior
    '{"subtasks": ["Read the agenda", "Prep two questions", "Decide the ask"],'
    ' "followups": [{"text": "Send notes to Marco", "deadline": "16:00"}]}'
)


def make_bridge(db_path: Path, calendar_file: Path | None) -> CalendarBridge:
    def read_calendar():
        if calendar_file is not None and calendar_file.is_file():
            return str(calendar_file), calendar_file.read_bytes()
        return None

    adapters = CalendarAdapters(read_calendar=read_calendar, clock=lambda: NOW.timestamp())
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return CalendarBridge(conn, adapters, llm=STUB_LLM)


@pytest.fixture()
def watched(tmp_path):
    return tmp_path / "calendar_sync.json"


@pytest.fixture()
def env(watched, tmp_path):
    db = tmp_path / "calendar.sqlite3"
    booted = server_harness.Booted(calendar=make_bridge(db, watched))
    booted.db = db
    booted.watched = watched
    try:
        yield booted
    finally:
        booted.server.calendar.stop_polling()
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def test_endpoints_require_a_session(env):
    status, _h, _b = env.post_json("/sources/calendar-bridge/retest", {}, env.host_header())
    assert status == 401


def test_absent_file_renders_the_designed_empty_state(env, auth):
    env.post_json("/sources/calendar-bridge/retest", {}, auth)
    status, _h, body = env.request("GET", "/widgets/commitments", auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "empty"
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert "calendar_sync.json" in page  # names the object
    assert 'href="/walkthrough/calendar"' in page  # names the first action


def test_dropping_the_fixture_populates_within_one_poll(env, auth):
    env.post_json("/sources/calendar-bridge/retest", {}, auth)
    assert json.loads(env.request("GET", "/widgets/commitments", auth)[2])["state"] == "empty"

    env.watched.write_text(json.dumps(FIXTURE_DOC), encoding="utf-8")
    env.post_json("/sources/calendar-bridge/retest", {}, auth)
    payload = json.loads(env.request("GET", "/widgets/commitments", auth)[2])
    assert payload["state"] == "healthy"
    assert payload["keyEvent"]["subject"] == "Q4 pipeline review"
    assert payload["breakdown"]["subtasks"] == [
        "Read the agenda", "Prep two questions", "Decide the ask",
    ]
    assert payload["breakdown"]["followups"][0]["text"] == "Send notes to Marco"


def test_checkbox_set_via_the_api_persists_across_restart(env, watched):
    watched.write_text(json.dumps(FIXTURE_DOC), encoding="utf-8")
    first = server_harness.Booted(calendar=make_bridge(env.db, watched))
    try:
        headers = first.exchange()
        first.post_json("/sources/calendar-bridge/retest", {}, headers)
        status, _h, _b = first.post_json(
            "/widgets/commitments/check",
            {"eventId": "evt-1", "idx": 1, "checked": True},
            headers,
        )
        assert status == 200
    finally:
        first.server.calendar.stop_polling()
        first.close()

    second = server_harness.Booted(calendar=make_bridge(env.db, watched))
    try:
        headers = second.exchange()
        second.post_json("/sources/calendar-bridge/retest", {}, headers)
        payload = json.loads(second.request("GET", "/widgets/commitments", headers)[2])
        assert payload["checks"] == {"1": True}
    finally:
        second.server.calendar.stop_polling()
        second.close()


def test_stale_calendar_data_is_marked_stale_with_a_refresh_path(env, auth, watched):
    old = json.loads(json.dumps(FIXTURE_DOC))  # deep copy: FIXTURE_DOC is shared
    old["generatedAt"] = (NOW - timedelta(hours=12)).isoformat()
    old["events"][0]["start"] = (NOW - timedelta(hours=12)).isoformat()
    old["events"][0]["end"] = (NOW - timedelta(hours=11)).isoformat()
    watched.write_text(json.dumps(old), encoding="utf-8")
    env.post_json("/sources/calendar-bridge/retest", {}, auth)
    payload = json.loads(env.request("GET", "/widgets/commitments", auth)[2])
    assert payload["state"] == "stale"
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert "data-calendar-retest" in page  # the refresh path
    assert "/walkthrough/calendar" in page


def test_walkthrough_is_reachable_and_browser_only(env, auth):
    status, resp_headers, body = env.request("GET", "/walkthrough/calendar", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert resp_headers["Content-Type"].startswith("text/html")
    assert "make.powerautomate.com" in page
    assert "Get calendar view of events" in page
    assert "calendar_sync.json" in page
    assert "Check for calendar data now" in page
    assert "http://" not in page.replace("http://127.0.0.1", "")  # still offline-built


def test_first_detection_is_confirmed_once(env, auth, watched):
    watched.write_text(json.dumps(FIXTURE_DOC), encoding="utf-8")
    env.post_json("/sources/calendar-bridge/retest", {}, auth)
    payload = json.loads(env.request("GET", "/widgets/commitments", auth)[2])
    assert payload["firstDetected"] is not None
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert "Connected" in page


def post_raw(booted, auth, path: str, text: str):
    """One POST whose body is exactly the given text (the upload shape)."""
    data = text.encode("utf-8")
    headers = {**auth, "Content-Type": "application/json",
               "Content-Length": str(len(data))}
    return booted.request("POST", path, headers=headers, body=data)


def test_walkthrough_offers_the_source_controls_and_the_settings_link(env, auth):
    page = env.request("GET", "/walkthrough/calendar", auth)[2].decode("utf-8")
    assert "data-calendar-pick" in page
    assert "data-calendar-path" in page
    assert "data-calendar-upload" in page
    assert "data-calendar-reset" in page
    assert 'id="calendar-note" hidden' in page
    assert 'accept=".json' in page  # the file input filters JSON
    settings_page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert 'href="/walkthrough/calendar"' in settings_page
    assert "calendar source page" in settings_page


def test_path_set_round_trip_and_reset(env, auth, tmp_path):
    mine = tmp_path / "mine.json"
    mine.write_text(json.dumps(FIXTURE_DOC), encoding="utf-8")

    # Setting the path validates, stores, and polls immediately: the
    # answer is already the healthy state, no separate re-test needed.
    status, _h, body = env.post_json(
        "/sources/calendar-bridge/path", {"path": str(mine)}, auth
    )
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "healthy"
    assert payload["path"] == str(mine)
    assert json.loads(env.request("GET", "/widgets/commitments", auth)[2])["state"] == "healthy"

    # The walkthrough names the chosen file as the one being read.
    page = env.request("GET", "/walkthrough/calendar", auth)[2].decode("utf-8")
    assert str(mine) in page
    assert "automatic discovery is set aside" in page
    assert "Back to automatic discovery" in page

    # Reset clears the choice; the adapter finds nothing, so empty returns.
    status, _h, body = env.post_json("/sources/calendar-bridge/reset", {}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "empty"
    assert json.loads(env.request("GET", "/widgets/commitments", auth)[2])["state"] == "empty"
    page = env.request("GET", "/walkthrough/calendar", auth)[2].decode("utf-8")
    assert str(mine) not in page
    assert "Reset to automatic discovery" in page


def test_path_set_rejects_bad_choices_with_honest_causes(env, auth, tmp_path):
    ghost = tmp_path / "nope.json"
    status, _h, body = env.post_json(
        "/sources/calendar-bridge/path", {"path": str(ghost)}, auth
    )
    assert status == 400
    assert "does not exist" in json.loads(body)["error"]

    status, _h, body = env.post_json(
        "/sources/calendar-bridge/path", {"path": str(tmp_path)}, auth
    )
    assert status == 400
    assert "folder" in json.loads(body)["error"]

    junk = tmp_path / "junk.json"
    junk.write_text('{"not": "a calendar"}', encoding="utf-8")
    status, _h, body = env.post_json(
        "/sources/calendar-bridge/path", {"path": str(junk)}, auth
    )
    assert status == 400
    assert "not a calendar document" in json.loads(body)["error"]

    # Nothing was stored: the bridge is still on discovery.
    assert env.server.calendar.explicit_path() is None


def test_upload_validates_writes_and_takes_effect(env, auth, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AGENTDESK_DATA", str(data_dir))
    document = json.dumps(FIXTURE_DOC)

    status, _h, body = post_raw(env, auth, "/sources/calendar-bridge/upload", document)
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "healthy"
    written = data_dir / "calendar_sync.json"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == document
    assert payload["path"] == str(written)
    assert env.server.calendar.explicit_path() == str(written)


def test_upload_rejects_anything_that_is_not_a_calendar_document(env, auth):
    status, _h, body = post_raw(env, auth, "/sources/calendar-bridge/upload", "")
    assert status == 400
    assert "request body" in json.loads(body)["error"]

    status, _h, body = post_raw(env, auth, "/sources/calendar-bridge/upload", "not json at all")
    assert status == 400
    assert "not a calendar document" in json.loads(body)["error"]

    status, _h, body = post_raw(
        env, auth, "/sources/calendar-bridge/upload", '{"events": "nope"}'
    )
    assert status == 400
    assert "not a calendar document" in json.loads(body)["error"]
    assert env.server.calendar.explicit_path() is None


def test_picker_endpoint_and_snippet(env, auth):
    chosen = str(env.watched)

    def pick():
        return chosen

    old = env.server.pick_calendar
    env.server.pick_calendar = pick
    try:
        status, _h, body = env.post_json("/sources/calendar-bridge/pick", {}, auth)
        assert status == 200
        assert json.loads(body)["path"] == chosen
    finally:
        env.server.pick_calendar = old

    # The dialog filters JSON and is parented and raised like the
    # workbook picker, so it cannot open invisibly behind the browser.
    snippet = server_app.CALENDAR_PICK_SNIPPET
    assert "*.json" in snippet
    assert "Calendar JSON" in snippet
    assert "parent=root" in snippet
    assert "root.lift()" in snippet


def test_calendar_picker_child_parsing_matches_the_workbook(monkeypatch):
    class FakeProcess:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(cmd, **kwargs):
        return FakeProcess(stdout="C:/cal/calendar_sync.json\n")

    monkeypatch.setattr(server_app.subprocess, "run", fake_run)
    assert server_app.tk_pick_calendar() == "C:/cal/calendar_sync.json"

    monkeypatch.setattr(
        server_app.subprocess, "run", lambda cmd, **k: FakeProcess(stdout="\n")
    )
    assert server_app.tk_pick_calendar() is None
