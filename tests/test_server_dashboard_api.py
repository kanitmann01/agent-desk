"""GET /api/dashboard contract tests: one payload, every dashboard state.

The SPA shell renders entirely from this payload, so each test walks a
real source state through the same HTTP seam the browser uses and asserts
the exact shape it will read. Same rules as the rendered dashboard: no
invented values, the branches the server renderers apply appear here as
modes, and plugin cards are data only.
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
from agentdesk.excel.watcher import Adapters as ExcelAdapters
from agentdesk.excel.watcher import ExcelWatch
from agentdesk.excel.xlsx import parse_workbook_bytes
from agentdesk.plugins.runtime import PluginRuntime
from plugins_fixtures import valid_zip
from excel_fixtures import base_workbook, make_xlsx

# The changed fixture rows, one row added and one removed after 24 h.
CHANGED_ROWS = [
    ["Product line", "Units", "Revenue"],
    ["Atlas ERP modules", 44.0, 176000.0],
    ["Field services", 12.0, 58000.0],
    ["Care plans", 7.0, 22500.0],
]

NOW = datetime(2026, 11, 11, 9, 0, 0).astimezone()

CALENDAR_DOC = {
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
    '{"subtasks": ["Read the agenda"], "followups": []}'
)


class FixedClock:
    def __init__(self) -> None:
        self.now = NOW.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_calendar(calendar_file: Path | None) -> CalendarBridge:
    def read_calendar():
        if calendar_file is not None and calendar_file.is_file():
            return str(calendar_file), calendar_file.read_bytes()
        return None

    adapters = CalendarAdapters(read_calendar=read_calendar, clock=lambda: NOW.timestamp())
    return CalendarBridge(sqlite3.connect(":memory:", check_same_thread=False),
                          adapters, llm=STUB_LLM)


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture()
def auth(booted):
    return booted.exchange()


def get_dashboard(booted, auth):
    status, _headers, body = booted.request("GET", "/api/dashboard", auth)
    assert status == 200
    assert _headers["Content-Type"].startswith("application/json")
    return json.loads(body)


def test_dashboard_api_requires_a_session(booted):
    status, _h, _b = booted.request("GET", "/api/dashboard", booted.host_header())
    assert status == 401


def test_first_run_payload_has_every_section_in_the_honest_states(booted, auth):
    payload = get_dashboard(booted, auth)
    # The whole contract: nothing missing, nothing extra.
    assert sorted(payload) == [
        "commitments", "flags", "inbox", "plugins", "research",
        "sales", "skills", "sources", "version",
    ]
    assert payload["version"]
    assert payload["flags"] == {
        "excelEnabled": True, "calendarEnabled": True, "endpointEnabled": True,
    }
    assert payload["sources"]["connected"] == 0
    assert payload["sources"]["total"] == 3
    assert {s["id"] for s in payload["sources"]["items"]} == {
        "excel-watch", "calendar-bridge", "research-endpoint",
    }
    # Sales: the watch exists but nothing is registered: unconfigured, and
    # the raw status keeps its excel.status() shape.
    assert payload["sales"]["enabled"] is True
    assert payload["sales"]["mode"] == "unconfigured"
    assert payload["sales"]["status"]["configured"] is False
    assert payload["sales"]["status"]["state"] == "not_configured"
    # Commitments: a bridge finding no file is the empty state, live.
    assert payload["commitments"]["mode"] == "live"
    assert payload["commitments"]["status"]["state"] == "empty"
    # Research: never answered, so the stamp has nothing to show.
    assert payload["research"]["enabled"] is True
    assert payload["research"]["lastAnsweredTs"] is None
    assert payload["inbox"]["waiting"] == 0
    assert payload["skills"] == []
    assert payload["plugins"]["cards"] == []


def test_payload_counts_connected_sources_when_one_exists(booted, auth):
    booted.server.llm_endpoint = "https://llm.corp.example"  # configured only
    payload = get_dashboard(booted, auth)
    assert payload["sources"]["connected"] == 1
    research_item = next(s for s in payload["sources"]["items"]
                         if s["id"] == "research-endpoint")
    assert research_item["status"] == "connected"


def test_sales_mode_is_live_with_delta_after_registration(tmp_path):
    workbook = tmp_path / "Q4-sales.xlsx"
    workbook.write_bytes(base_workbook())
    clock = FixedClock()
    adapters = ExcelAdapters(
        copy_shadow=lambda p: Path(p),
        parse_workbook=lambda p: parse_workbook_bytes(Path(p).read_bytes()),
        clock=clock,
    )
    watch = ExcelWatch(sqlite3.connect(":memory:", check_same_thread=False), adapters)
    booted = server_harness.Booted(excel=watch)
    try:
        auth = booted.exchange()
        status, _h, _b = booted.post_json(
            "/sources/excel-watch", {"path": str(workbook)}, auth)
        assert status == 200
        # First snapshot is the baseline; a changed file one poll later
        # moves the card to healthy with a real delta, as on the machine.
        payload = get_dashboard(booted, auth)
        assert payload["sales"]["mode"] == "live"
        assert payload["sales"]["status"]["state"] == "first"
        workbook.write_bytes(make_xlsx(CHANGED_ROWS))
        clock.advance(24 * 3600)
        booted.post_json("/sources/excel-watch/retest", {}, auth)
        payload = get_dashboard(booted, auth)
        sales = payload["sales"]["status"]
        assert sales["state"] == "healthy"
        assert sales["delta"] is not None
        assert isinstance(sales["delta"]["added"], list)
        assert isinstance(sales["last_ok_ts"], float)
    finally:
        watch.stop_polling()
        booted.close()


def test_sales_mode_turns_disabled_with_the_setting(booted, auth):
    status, _h, _b = booted.post_json("/settings/toggle", {"key": "excel_enabled"}, auth)
    assert status == 200
    payload = get_dashboard(booted, auth)
    assert payload["flags"]["excelEnabled"] is False
    assert payload["sales"]["enabled"] is False
    assert payload["sales"]["mode"] == "disabled"


def test_commitments_states_across_the_bridge(env_setup):
    booted, watched, auth = env_setup
    # Empty: no file yet.
    payload = get_dashboard(booted, auth)
    assert payload["commitments"]["mode"] == "live"
    assert payload["commitments"]["status"]["state"] == "empty"

    # Healthy: the file lands and one re-test reads it.
    watched.write_text(json.dumps(CALENDAR_DOC), encoding="utf-8")
    status, _h, _b = booted.post_json("/sources/calendar-bridge/retest", {}, auth)
    assert status == 200
    payload = get_dashboard(booted, auth)
    commitments = payload["commitments"]["status"]
    assert commitments["state"] == "healthy"
    assert commitments["keyEvent"]["id"] == "evt-1"
    assert commitments["keyEvent"]["subject"] == "Q4 pipeline review"
    assert commitments["breakdown"]["subtasks"] == ["Read the agenda"]
    assert commitments["generatedAt"]
    assert commitments["checks"] == {}


def test_commitments_stale_state_carries_the_cause(env_setup):
    booted, watched, auth = env_setup
    # Age the file past the stale window, the way the existing calendar
    # tests do: generatedAt and the event itself, 12 hours back.
    old_doc = json.loads(json.dumps(CALENDAR_DOC))
    old_doc["generatedAt"] = (NOW - timedelta(hours=12)).isoformat()
    old_doc["events"][0]["start"] = (NOW - timedelta(hours=12)).isoformat()
    old_doc["events"][0]["end"] = (NOW - timedelta(hours=11)).isoformat()
    watched.write_text(json.dumps(old_doc), encoding="utf-8")
    booted.post_json("/sources/calendar-bridge/retest", {}, auth)
    payload = get_dashboard(booted, auth)
    commitments = payload["commitments"]["status"]
    assert commitments["state"] == "stale"
    assert commitments["cause"]


def test_commitments_disabled_with_the_setting(booted, auth):
    booted.post_json("/settings/toggle", {"key": "calendar_enabled"}, auth)
    payload = get_dashboard(booted, auth)
    assert payload["commitments"]["enabled"] is False
    assert payload["commitments"]["mode"] == "disabled"
    assert payload["commitments"]["status"] is None


def test_commitments_unavailable_when_the_bridge_is_none(booted, auth):
    # The UI path under test is the attribute being None after a failed
    # store open, exactly as the rendered unavailable card reads it.
    booted.server.calendar.stop_polling()
    booted.server.calendar = None
    payload = get_dashboard(booted, auth)
    assert payload["commitments"]["mode"] == "unavailable"
    assert payload["commitments"]["status"] is None


def test_research_last_answered_ts_follows_a_real_answer(booted, auth):
    booted.server.llm = lambda prompt: json.dumps({"summary": "s", "sources": []})
    status, _h, _b = booted.post_json("/research", {"question": "q"}, auth)
    assert status == 200
    payload = get_dashboard(booted, auth)
    assert isinstance(payload["research"]["lastAnsweredTs"], float)


def test_inbox_waiting_count_comes_from_the_store(booted, auth):
    status, _h, _b = booted.post_json("/inbox/cards", {
        "kind": "suggestion", "origin": "test", "title": "T",
        "body": "B",
    }, auth)
    assert status == 201
    payload = get_dashboard(booted, auth)
    assert payload["inbox"]["waiting"] == 1


def test_skills_list_active_skills_as_data(booted):
    booted.server.skills.activate(name="Morning numbers", description="d", prompt="p")
    auth = booted.exchange()
    payload = get_dashboard(booted, auth)
    assert len(payload["skills"]) == 1
    skill = payload["skills"][0]
    assert skill["name"] == "morning-numbers"  # the store slugs the name
    assert "prompt" not in skill  # the dashboard needs the name, not the ask


def test_plugin_cards_are_data_not_html(booted, auth, tmp_path):
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now="2026-11-11T16:00:00",
    )
    booted.server.plugins = runtime
    zip_path = valid_zip(tmp_path / "plugin.zip")
    status, _h, out = booted.post_json(
        "/api/plugins/install", {"zip_path": str(zip_path), "source": "zip"}, auth)
    assert status == 200, out
    payload = get_dashboard(booted, auth)
    cards = payload["plugins"]["cards"]
    assert len(cards) == 1
    card = cards[0]
    assert card["id"] == "sales-delta-widget"
    assert card["title"] == "Sales 24h Delta"
    assert card["version"] == "1.2.0"
    assert card["pilot"] is True
    assert card["freshness"] in ("fresh", "attention")
    assert isinstance(card["cause"], str)
    assert "<" not in json.dumps(cards)  # never server HTML inside the JSON


@pytest.fixture()
def env_setup(tmp_path):
    watched = tmp_path / "calendar_sync.json"
    booted = server_harness.Booted(calendar=make_calendar(watched))
    try:
        yield booted, watched, booted.exchange()
    finally:
        booted.server.calendar.stop_polling()
        booted.close()
