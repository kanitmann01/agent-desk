"""Turning Sample data on wires the sample files, and only the sample files.

The wiring is a ledger change, so Activity can undo it; turning the switch
off detaches only paths inside the sample folder and never a real source.
"""

import sqlite3
import time
from pathlib import Path

import pytest

import server_harness
from agentdesk.calendar.watcher import Adapters as CalendarAdapters
from agentdesk.calendar.watcher import CalendarBridge
from agentdesk.excel.watcher import Adapters as ExcelAdapters
from agentdesk.excel.watcher import ExcelWatch

NOW = 1700000000.0


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A server whose only stores are real watches over in-memory databases."""
    data_dir = tmp_path / "desk-data"
    monkeypatch.setenv("AGENTDESK_DATA", str(data_dir))
    excel = ExcelWatch(
        sqlite3.connect(":memory:", check_same_thread=False),
        ExcelAdapters(copy_shadow=lambda path: Path(path),
                      parse_workbook=lambda path: [], clock=time.time),
    )
    calendar = CalendarBridge(
        sqlite3.connect(":memory:", check_same_thread=False),
        CalendarAdapters(read_calendar=lambda: None, clock=time.time),
    )
    booted = server_harness.Booted(excel=excel, calendar=calendar)
    booted.data_dir = data_dir
    try:
        yield booted
    finally:
        booted.close()


def _toggle(env, auth):
    """Flip the Sample data switch, the way the settings page does."""
    status, _headers, _body = env.post_json("/settings/toggle", {"key": "sample_data"}, auth)
    assert status == 200


def _sample_workbook(env):
    return env.data_dir / "sample" / "sample-sales.xlsx"


def _sample_calendar(env):
    return env.data_dir / "sample" / "sample-calendar.json"


def test_sample_on_wires_pipeline_and_moves(env):
    """Sample data on attaches both sample files and fills the dashboard."""
    auth = env.exchange()
    _toggle(env, auth)
    assert env.server.excel.registered_path == str(_sample_workbook(env))
    assert env.server.calendar.explicit_path() == str(_sample_calendar(env))
    from agentdesk.server.dashboard_state import build_dashboard_state

    payload = build_dashboard_state(env.server).payload()
    assert payload["sales"]["mode"] == "live"
    assert payload["commitments"]["mode"] == "live"
    status, _headers, body = env.request("GET", "/api/desk-check", auth)
    assert status == 200
    import json

    ids = [finding["id"] for finding in json.loads(body)["findings"]]
    assert "sample-not-wired" not in ids
    assert "source-on-not-connected" not in ids


def test_sample_wiring_is_reported_as_sample_and_never_counted_live(env):
    """A sample source is showing something, and it is not live (spec 022).

    The home screen used to say "Live: 2 of 3 sources connected" while
    every card wore its SAMPLE DATA tag. The source table now answers
    "sample" for a wired sample file, so the live count, Desk health and
    the setup steps all agree that nothing real is attached.
    """
    import json

    auth = env.exchange()
    _toggle(env, auth)
    payload = json.loads(env.request("GET", "/api/dashboard", auth)[2])
    rows = {item["id"]: item for item in payload["sources"]["items"]}
    assert rows["excel-watch"]["status"] == "sample"
    assert "not your file" in rows["excel-watch"]["detail"]
    assert rows["calendar-bridge"]["status"] == "sample"
    assert payload["sources"]["connected"] == 0
    assert [step["done"] for step in payload["setup"]["steps"]] == [False, False, False]
    health = json.loads(env.request("GET", "/health", auth)[2])
    assert [row["status"] for row in health["sources"]] == ["sample", "sample", "not_connected"]

    # A real workbook takes the wiring back: it is live, and it is counted.
    real_workbook = env.data_dir / "real-workbook.xlsx"
    real_workbook.write_bytes(b"real workbook")
    env.server.excel.register(str(real_workbook))
    payload = json.loads(env.request("GET", "/api/dashboard", auth)[2])
    rows = {item["id"]: item for item in payload["sources"]["items"]}
    assert rows["excel-watch"]["status"] == "connected"
    assert payload["sources"]["connected"] == 1
    assert payload["setup"]["steps"][1]["done"] is True


def test_sample_off_detaches_only_the_sample_wiring(env):
    """Turning the switch off clears the sample wiring, not a real source."""
    auth = env.exchange()
    _toggle(env, auth)
    _toggle(env, auth)
    assert env.server.excel.registered_path is None
    assert env.server.calendar.explicit_path() is None


def test_sample_off_never_touches_real_source(env):
    """A real registered path survives a Sample on/off cycle unchanged."""
    real_workbook = env.data_dir / "real-workbook.xlsx"
    real_workbook.parent.mkdir(parents=True, exist_ok=True)
    real_workbook.write_bytes(b"real workbook")
    real_calendar = env.data_dir / "real-calendar.json"
    real_calendar.write_text('{"events": []}', encoding="utf-8")
    env.server.excel.register(str(real_workbook))
    env.server.calendar.set_explicit_path(str(real_calendar))
    auth = env.exchange()
    _toggle(env, auth)
    _toggle(env, auth)
    assert env.server.excel.registered_path == str(real_workbook)
    assert env.server.calendar.explicit_path() == str(real_calendar)


def test_undo_wiring_roundtrip(env):
    """Activity's Undo detaches the sample wiring, and undo of that reattaches."""
    auth = env.exchange()
    _toggle(env, auth)
    entry = next(item for item in env.server.ledger.entries(limit=5)
                 if item.subject == "sample-data-wiring")
    status, _headers, _body = env.post_json("/api/ledger/undo", {"id": entry.id}, auth)
    assert status == 200
    assert env.server.excel.registered_path is None
    assert env.server.calendar.explicit_path() is None
    newest = env.server.ledger.entries(limit=1)[0]
    status, _headers, _body = env.post_json("/api/ledger/undo", {"id": newest.id}, auth)
    assert status == 200
    assert env.server.excel.registered_path == str(_sample_workbook(env))
    assert env.server.calendar.explicit_path() == str(_sample_calendar(env))
