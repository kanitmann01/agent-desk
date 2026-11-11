"""Startup poll tests: the dashboard is real from the first page load.

serve() wires both watches to poll once on daemon threads, so a restart
with a registered workbook shows the real sales state and a synced
calendar file shows today's commitment without anyone clicking Re-test.
"""

import json
import sqlite3
import sys
import time
from datetime import datetime
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
from agentdesk.server import app as server_app
from agentdesk.settings import SettingsStore
from excel_fixtures import base_workbook

NOW = datetime.now().astimezone()

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

STUB_LLM = lambda prompt: '{"subtasks": ["Read the agenda"], "followups": []}'  # noqa: E731


def wait_until(predicate, timeout_s: float = 5.0) -> bool:
    """Poll a condition on the real threads; daemon polls land when they land."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def real_excel_adapters() -> ExcelAdapters:
    return ExcelAdapters(
        copy_shadow=lambda p: Path(p),  # no lock in tests: parse the file directly
        parse_workbook=lambda p: parse_workbook_bytes(Path(p).read_bytes()),
        clock=time.time,
    )


@pytest.fixture()
def workbook(tmp_path):
    path = tmp_path / "Q4-sales.xlsx"
    path.write_bytes(base_workbook())
    return path


@pytest.fixture()
def calendar_file(tmp_path):
    path = tmp_path / "calendar_sync.json"
    path.write_text(json.dumps(FIXTURE_DOC), encoding="utf-8")
    return path


def make_bridge(db_path: Path, calendar_file: Path) -> CalendarBridge:
    def read_calendar():
        return str(calendar_file), calendar_file.read_bytes()

    adapters = CalendarAdapters(read_calendar=read_calendar, clock=time.time)
    return CalendarBridge(sqlite3.connect(db_path, check_same_thread=False), adapters, llm=STUB_LLM)


def test_registered_workbook_is_watched_again_after_a_restart(workbook, tmp_path):
    # First run: the manager picked the workbook; the path lands in the store.
    db_path = tmp_path / "excel-watch.sqlite3"
    first = ExcelWatch(sqlite3.connect(db_path, check_same_thread=False), real_excel_adapters())
    first.register(str(workbook))
    first.stop_polling()

    # Restart: a brand new watch over the same store, memory empty.
    booted = server_harness.Booted(
        excel=ExcelWatch(sqlite3.connect(db_path, check_same_thread=False), real_excel_adapters())
    )
    try:
        assert booted.server.excel.registered_path is None
        server_app.start_background_polls(booted.server)
        assert wait_until(lambda: booted.server.excel.status()["configured"])
        headers = booted.exchange()
        _status, _h, body = booted.request("GET", "/", headers)
        page = body.decode("utf-8")
        assert "First snapshot taken" in page  # real state, no demo numbers
        assert "+&nbsp;&euro;14,320" not in page
    finally:
        booted.server.excel.stop_polling()
        booted.close()


def test_excel_disabled_in_settings_is_not_restored(workbook, tmp_path):
    db_path = tmp_path / "excel-watch.sqlite3"
    first = ExcelWatch(sqlite3.connect(db_path, check_same_thread=False), real_excel_adapters())
    first.register(str(workbook))
    first.stop_polling()

    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    settings.set("excel_enabled", False)
    booted = server_harness.Booted(
        excel=ExcelWatch(sqlite3.connect(db_path, check_same_thread=False), real_excel_adapters()),
        settings_store=settings,
    )
    try:
        server_app.start_background_polls(booted.server)
        time.sleep(0.05)  # a resumed watch would have restored by now
        assert booted.server.excel.registered_path is None
        headers = booted.exchange()
        page = booted.request("GET", "/", headers)[2].decode("utf-8")
        assert "Sales watching is turned off in settings." in page
    finally:
        booted.server.excel.stop_polling()
        booted.close()


def test_calendar_file_populates_the_card_without_clicking(calendar_file, tmp_path):
    booted = server_harness.Booted(calendar=make_bridge(tmp_path / "cal.sqlite3", calendar_file))
    try:
        server_app.start_background_polls(booted.server)
        assert wait_until(lambda: booted.server.calendar.status()["state"] == "healthy")
        headers = booted.exchange()
        page = booted.request("GET", "/", headers)[2].decode("utf-8")
        assert "Q4 pipeline review" in page  # today's commitment, first load
    finally:
        booted.server.calendar.stop_polling()
        booted.close()


def test_calendar_disabled_in_settings_is_not_polled(calendar_file, tmp_path):
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    settings.set("calendar_enabled", False)
    booted = server_harness.Booted(
        calendar=make_bridge(tmp_path / "cal.sqlite3", calendar_file),
        settings_store=settings,
    )
    try:
        server_app.start_background_polls(booted.server)
        time.sleep(0.05)  # a poll would have flipped the state by now
        assert booted.server.calendar.status()["state"] == "empty"
        headers = booted.exchange()
        page = booted.request("GET", "/", headers)[2].decode("utf-8")
        assert "Calendar reading is turned off in settings." in page
    finally:
        booted.server.calendar.stop_polling()
        booted.close()


def test_serve_runs_the_startup_polls(monkeypatch):
    calls = []
    monkeypatch.setattr(server_app, "start_background_polls", calls.append)

    class FakeSessions:
        @staticmethod
        def auth_path():
            return "/auth/test"

    class FakeServer:
        port = 8765
        sessions = FakeSessions()

        def serve_forever(self):
            raise KeyboardInterrupt  # the test only proves the wiring

        def server_close(self):
            pass

    server_app.serve(FakeServer(), open_browser=False)
    assert len(calls) == 1
    assert isinstance(calls[0], FakeServer)
