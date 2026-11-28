"""Health endpoint tests through the real HTTP seam.

Health is authenticated like everything else (the ground rule is that the
server authenticates every request) and the source table is computed at
request time: an unconfigured boot says not_connected, and a source the
server can actually see shows connected.
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

import nexuusbot
import server_harness
from nexuusbot.calendar.watcher import Adapters as CalendarAdapters
from nexuusbot.calendar.watcher import CalendarBridge
from nexuusbot.excel.watcher import Adapters as ExcelAdapters
from nexuusbot.excel.watcher import ExcelWatch
from nexuusbot.excel.xlsx import parse_workbook_bytes
from excel_fixtures import base_workbook

NOW = datetime.now().astimezone()


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def test_health_requires_a_session(booted):
    status, _headers, _body = booted.request("GET", "/health", booted.host_header())
    assert status == 401


def test_health_reports_app_version_sources_and_uptime(booted):
    headers = booted.exchange()
    status, resp_headers, body = booted.request("GET", "/health", headers)
    assert status == 200
    assert resp_headers["Content-Type"].startswith("application/json")
    payload = json.loads(body)
    assert payload["app"] == "agent-desk"
    assert payload["version"] == nexuusbot.__version__
    assert payload["uptime_seconds"] >= 0


def test_health_source_table_is_honest_when_nothing_is_configured(booted):
    headers = booted.exchange()
    _status, _resp_headers, body = booted.request("GET", "/health", headers)
    payload = json.loads(body)
    sources = {s["id"]: s for s in payload["sources"]}
    assert set(sources) == {"excel-watch", "calendar-bridge", "research-endpoint"}
    for source in sources.values():
        assert source["status"] == "not_connected"
        assert source["detail"]


def test_configured_sources_show_connected(tmp_path):
    workbook = tmp_path / "Q4-sales.xlsx"
    workbook.write_bytes(base_workbook())
    watch = ExcelWatch(
        sqlite3.connect(":memory:", check_same_thread=False),
        ExcelAdapters(
            copy_shadow=lambda p: Path(p),
            parse_workbook=lambda p: parse_workbook_bytes(Path(p).read_bytes()),
            clock=time.time,
        ),
    )
    watch.register(str(workbook))

    calendar_file = tmp_path / "calendar_sync.json"
    calendar_file.write_text(json.dumps({"generatedAt": NOW.isoformat(), "events": []}), encoding="utf-8")
    bridge = CalendarBridge(
        sqlite3.connect(":memory:", check_same_thread=False),
        CalendarAdapters(
            read_calendar=lambda: (str(calendar_file), calendar_file.read_bytes()),
            clock=time.time,
        ),
        llm=lambda prompt: '{"subtasks": [], "followups": []}',
    )
    bridge.poll()

    booted = server_harness.Booted(
        excel=watch,
        calendar=bridge,
        llm_endpoint="http://127.0.0.1:9",  # configured is enough; nothing calls it
    )
    try:
        headers = booted.exchange()
        payload = json.loads(booted.request("GET", "/health", headers)[2])
        sources = {s["id"]: s for s in payload["sources"]}
        assert all(s["status"] == "connected" and s["detail"] for s in sources.values())
        assert "Q4-sales.xlsx" in sources["excel-watch"]["detail"]
    finally:
        watch.stop_polling()
        booted.close()


def test_a_registered_workbook_flips_only_the_excel_entry(tmp_path):
    workbook = tmp_path / "Q4-sales.xlsx"
    workbook.write_bytes(base_workbook())
    watch = ExcelWatch(
        sqlite3.connect(":memory:", check_same_thread=False),
        ExcelAdapters(
            copy_shadow=lambda p: Path(p),
            parse_workbook=lambda p: parse_workbook_bytes(Path(p).read_bytes()),
            clock=time.time,
        ),
    )
    watch.register(str(workbook))
    booted = server_harness.Booted(excel=watch)
    try:
        headers = booted.exchange()
        payload = json.loads(booted.request("GET", "/health", headers)[2])
        sources = {s["id"]: s for s in payload["sources"]}
        assert sources["excel-watch"]["status"] == "connected"
        assert sources["calendar-bridge"]["status"] == "not_connected"
        assert sources["research-endpoint"]["status"] == "not_connected"
    finally:
        watch.stop_polling()
        booted.close()
