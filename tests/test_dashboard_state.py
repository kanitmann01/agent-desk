"""Both dashboard surfaces agree, and reading them stays a pure read.

One state decides settings, source modes, research and plugin cards for the
server-rendered fallback and GET /api/dashboard. These tests walk each honest
mode through the real HTTP seam and compare the JSON payload with the article
the fallback page draws. The last tests pin the read/spend split: GETs never
spend a pilot view, the explicit view report does.
"""

import json
import sqlite3
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.calendar.watcher import Adapters as CalendarAdapters
from agentdesk.calendar.watcher import CalendarBridge
from agentdesk.excel.watcher import Adapters as ExcelAdapters
from agentdesk.excel.watcher import ExcelWatch
from agentdesk.excel.xlsx import parse_workbook_bytes
from agentdesk.server import dashboard_state
from excel_fixtures import base_workbook, make_xlsx
from plugins_fixtures import valid_zip

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

# The bridge's breakdown is a stubbed model call in this suite.
STUB_LLM = lambda prompt: '{"subtasks": ["Read the agenda"], "followups": []}'  # noqa: E731

CHANGED_ROWS = [
    ["Product line", "Units", "Revenue"],
    ["Atlas ERP modules", 44.0, 176000.0],
]


class FixedClock:
    """A clock the test moves, so the 24 h delta window is deterministic."""

    def __init__(self) -> None:
        self.now = NOW.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_calendar(calendar_file: Path | None) -> CalendarBridge:
    """A bridge that reads the file this test writes, through real adapters."""
    def read_calendar():
        if calendar_file is not None and calendar_file.is_file():
            return str(calendar_file), calendar_file.read_bytes()
        return None

    adapters = CalendarAdapters(read_calendar=read_calendar,
                                clock=lambda: NOW.timestamp())
    return CalendarBridge(sqlite3.connect(":memory:", check_same_thread=False),
                          adapters, llm=STUB_LLM)


class WidgetScan(HTMLParser):
    """Collect each rendered article.widget: id, freshness, title and text."""

    def __init__(self) -> None:
        super().__init__()
        self.widgets: list[dict] = []
        self._widget: dict | None = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "article" and "widget" in classes:
            self._widget = {
                "id": attributes.get("data-widget-id"),
                "status": attributes.get("data-freshness-status"),
                "title": "",
                "text": [],
            }
            return
        if self._widget is not None and tag == "h2":
            self._in_title = True

    def handle_endtag(self, tag):
        if self._widget is None:
            return
        if tag == "h2":
            self._in_title = False
        if tag == "article":
            self._widget["text"] = " ".join(" ".join(self._widget["text"]).split())
            self._widget["title"] = " ".join(self._widget["title"].split())
            self.widgets.append(self._widget)
            self._widget = None

    def handle_data(self, data):
        if self._widget is None:
            return
        if self._in_title:
            self._widget["title"] += data
        self._widget["text"].append(data)


def scan_page(page_html: str) -> list[dict]:
    """Every rendered widget on one fallback page, in document order."""
    scan = WidgetScan()
    scan.feed(page_html)
    scan.close()
    return scan.widgets


def widget_by_id(page_html: str, widget_id: str) -> dict:
    """The one rendered widget carrying this id, or a readable failure."""
    found = [w for w in scan_page(page_html) if w["id"] == widget_id]
    assert len(found) == 1, f"expected one {widget_id!r} widget, found {found}"
    return found[0]


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


def get_payload(booted, auth) -> dict:
    """GET /api/dashboard, exactly as the SPA reads it."""
    status, headers, body = booted.request("GET", "/api/dashboard", auth)
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    return json.loads(body)


def get_page(booted, auth) -> str:
    """GET /, the server-rendered fallback (conftest keeps the SPA absent)."""
    status, headers, body = booted.request("GET", "/", auth)
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    return body.decode("utf-8")


def install_plugin(booted, auth, tmp_path: Path) -> None:
    """Install the sales fixture plugin over the API, as the desk does."""
    status, _h, out = booted.post_json(
        "/api/plugins/install",
        {"zip_path": str(valid_zip(tmp_path / "plugin.zip")), "source": "zip"},
        auth)
    assert status == 200, out


def pilot_views(booted) -> dict:
    """The stored pilot_views_left per installed plugin."""
    state = booted.server.plugins._read()
    return {plugin_id: entry["pilot_views_left"]
            for plugin_id, entry in state["plugins"].items()}


def test_sales_modes_agree_between_payload_and_rendered_page(booted, auth):
    # Unconfigured: the watch exists, nothing has been registered.
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    assert payload["sales"]["mode"] == "unconfigured"
    card = widget_by_id(page, "sales-24h")
    assert card["status"] == "attention"
    assert "No workbook is connected yet" in card["text"]

    # No watch at all is the same honest mode, with the same card.
    booted.server.excel.stop_polling()
    booted.server.excel = None
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    assert payload["sales"]["mode"] == "unconfigured"
    card = widget_by_id(page, "sales-24h")
    assert card["status"] == "attention"
    assert "No workbook is connected yet" in card["text"]

    # The settings toggle is the one cause of the disabled mode.
    status, _h, _b = booted.post_json("/settings/toggle", {"key": "excel_enabled"}, auth)
    assert status == 200
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    assert payload["flags"]["excelEnabled"] is False
    assert payload["sales"]["mode"] == "disabled"
    card = widget_by_id(page, "sales-24h")
    assert card["status"] == "attention"
    assert "Sales watching is turned off in settings." in card["text"]


def test_sales_live_mode_agrees_with_rendered_card(tmp_path):
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
        payload = get_payload(booted, auth)
        page = get_page(booted, auth)
        assert payload["sales"]["mode"] == "live"
        assert payload["sales"]["status"]["state"] == "first"
        card = widget_by_id(page, "sales-24h")
        assert card["status"] == "fresh"
        assert "First snapshot taken" in card["text"]

        # A changed file one poll later keeps mode and card fresh together.
        workbook.write_bytes(make_xlsx(CHANGED_ROWS))
        clock.advance(24 * 3600)
        booted.post_json("/sources/excel-watch/retest", {}, auth)
        payload = get_payload(booted, auth)
        page = get_page(booted, auth)
        assert payload["sales"]["mode"] == "live"
        assert payload["sales"]["status"]["state"] == "healthy"
        card = widget_by_id(page, "sales-24h")
        assert card["status"] == "fresh"
        assert "Rows changed, 24 h" in card["text"]
    finally:
        watch.stop_polling()
        booted.close()


def test_commitments_modes_agree_between_payload_and_rendered_page(booted, auth):
    # Live but empty: the bridge is running and has no file yet.
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    assert payload["commitments"]["mode"] == "live"
    assert payload["commitments"]["status"]["state"] == "empty"
    card = widget_by_id(page, "key-commitment")
    assert card["status"] == "attention"
    assert "No calendar data yet" in card["text"]

    # The settings toggle is the one cause of the disabled mode.
    status, _h, _b = booted.post_json(
        "/settings/toggle", {"key": "calendar_enabled"}, auth)
    assert status == 200
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    assert payload["commitments"]["mode"] == "disabled"
    assert payload["commitments"]["status"] is None
    card = widget_by_id(page, "key-commitment")
    assert card["status"] == "attention"
    assert "Calendar reading is turned off in settings." in card["text"]

    # Re-enabled, and then the bridge itself is missing.
    booted.post_json("/settings/toggle", {"key": "calendar_enabled"}, auth)
    booted.server.calendar.stop_polling()
    booted.server.calendar = None
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    assert payload["commitments"]["mode"] == "unavailable"
    assert payload["commitments"]["status"] is None
    card = widget_by_id(page, "key-commitment")
    assert card["status"] == "attention"
    assert "calendar bridge is not running" in card["text"]


def test_commitments_healthy_card_agrees_with_payload(tmp_path):
    watched = tmp_path / "calendar_sync.json"
    booted = server_harness.Booted(calendar=make_calendar(watched))
    try:
        auth = booted.exchange()
        watched.write_text(json.dumps(CALENDAR_DOC), encoding="utf-8")
        status, _h, _b = booted.post_json(
            "/sources/calendar-bridge/retest", {}, auth)
        assert status == 200
        payload = get_payload(booted, auth)
        page = get_page(booted, auth)
        assert payload["commitments"]["mode"] == "live"
        assert payload["commitments"]["status"]["state"] == "healthy"
        card = widget_by_id(page, "key-commitment")
        assert card["status"] == "fresh"
        assert "Q4 pipeline review" in card["text"]
    finally:
        booted.server.calendar.stop_polling()
        booted.close()


def test_research_enabled_and_disabled_agree_between_surfaces(booted, auth):
    # Enabled: the ask surface is drawn and the payload says so.
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    assert payload["research"] == {"enabled": True, "lastAnsweredTs": None}
    card = widget_by_id(page, "research")
    assert card["status"] == "fresh"
    assert 'id="research-question"' in page

    # Disabled: the honest paused card on the page, the flag in the payload,
    # and no ask form offered anywhere on that surface.
    status, _h, _b = booted.post_json(
        "/settings/toggle", {"key": "endpoint_enabled"}, auth)
    assert status == 200
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    assert payload["flags"]["endpointEnabled"] is False
    assert payload["research"]["enabled"] is False
    card = widget_by_id(page, "research")
    assert card["status"] == "attention"
    assert "Research is turned off in settings." in card["text"]
    assert "Turn it back on" in card["text"]
    assert 'id="research-question"' not in page


def test_each_surface_reads_the_audit_once(booted, auth, monkeypatch):
    calls = {"count": 0}
    real = audit_store.last_ok_ts

    def counted(conn, action):
        calls["count"] += 1
        return real(conn, action)

    monkeypatch.setattr(dashboard_state.audit_store, "last_ok_ts", counted)
    get_page(booted, auth)
    assert calls["count"] == 1
    calls["count"] = 0
    get_payload(booted, auth)
    assert calls["count"] == 1


def test_plugin_cards_agree_between_payload_and_rendered_articles(
        booted, auth, tmp_path):
    install_plugin(booted, auth, tmp_path)
    payload = get_payload(booted, auth)
    page = get_page(booted, auth)
    cards = payload["plugins"]["cards"]
    assert [card["id"] for card in cards] == ["sales-delta-widget"]
    rendered = [w for w in scan_page(page) if str(w["id"]).startswith("plugin-")]
    assert [w["id"] for w in rendered] == [f"plugin-{card['id']}" for card in cards]
    assert [w["title"] for w in rendered] == [card["title"] for card in cards]
    expected = "fresh" if cards[0]["freshness"] == "fresh" else "attention"
    assert rendered[0]["status"] == expected


def test_gets_are_pure_and_the_view_report_spends(booted, auth, tmp_path):
    install_plugin(booted, auth, tmp_path)
    # The PRD's binding count: five runs carry the pilot badge (017-02 2h).
    assert pilot_views(booted) == {"sales-delta-widget": 5}

    # Both GET surfaces only read: the pilot count must not move.
    status, _h, _b = booted.request("GET", "/", auth)
    assert status == 200
    payload = get_payload(booted, auth)
    assert len(payload["plugins"]["cards"]) == 1
    assert pilot_views(booted) == {"sales-delta-widget": 5}

    # The explicit report spends one view per enabled plugin, then stops.
    for expected in (4, 3, 2, 1, 0):
        status, _h, body = booted.post_json("/api/dashboard/view", {}, auth)
        assert status == 200
        assert json.loads(body) == {"spent": 1}
        assert pilot_views(booted) == {"sales-delta-widget": expected}

    # Exhausted: a view still renders, but spends nothing and writes nothing.
    status, _h, body = booted.post_json("/api/dashboard/view", {}, auth)
    assert status == 200
    assert json.loads(body) == {"spent": 0}
    assert pilot_views(booted) == {"sales-delta-widget": 0}
