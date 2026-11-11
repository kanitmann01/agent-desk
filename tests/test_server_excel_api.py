"""Excel-watch tests through the real HTTP seam.

These walk the manager's actual flow without a browser: the picker
endpoint stands in for the native dialog, registration starts the watch,
and the widget endpoint plus the rendered dashboard carry the delta, the
amber states and the freshness contract.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.excel.core import WorkbookLocked
from agentdesk.excel.watcher import Adapters, ExcelWatch
from agentdesk.excel.xlsx import parse_workbook_bytes
from excel_fixtures import BASE_ROWS, base_workbook, make_xlsx

CHANGED_ROWS = [
    ["Product line", "Units", "Revenue"],
    ["Atlas ERP modules", 44.0, 176000.0],
    ["Field services", 12.0, 58000.0],
    ["Care plans", 7.0, 22500.0],
]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def workbook(tmp_path):
    """The real fixture file on disk, as the picker would hand it over."""
    path = tmp_path / "Q4-sales.xlsx"
    path.write_bytes(base_workbook())
    return path


@pytest.fixture()
def env(workbook, tmp_path):
    """Booted server with a real-parsing watch over the fixture file."""
    clock = FakeClock()
    adapters = Adapters(
        copy_shadow=lambda p: Path(p),  # no lock in tests: parse the file directly
        parse_workbook=lambda p: parse_workbook_bytes(Path(p).read_bytes()),
        clock=clock,
    )
    watch = ExcelWatch(sqlite3.connect(":memory:", check_same_thread=False), adapters)
    picks = {"path": str(workbook), "calls": 0}

    def pick():
        picks["calls"] += 1
        return picks["path"]

    booted = server_harness.Booted(excel=watch, pick_workbook=pick)
    booted.clock = clock
    booted.watch = watch
    booted.workbook = workbook
    booted.picks = picks
    try:
        yield booted
    finally:
        watch.stop_polling()
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def test_post_endpoints_require_a_session(env):
    status, _h, _b = env.post_json("/sources/excel-watch", {"path": "x"}, env.host_header())
    assert status == 401


def test_picker_endpoint_returns_the_chosen_path(env, auth):
    status, _h, body = env.post_json("/sources/excel-watch/pick", {}, auth)
    assert status == 200
    assert json.loads(body)["path"] == str(env.workbook)


def test_picker_cancellation_is_not_an_error(env, auth):
    env.picks["path"] = None
    status, _h, body = env.post_json("/sources/excel-watch/pick", {}, auth)
    assert status == 200
    assert json.loads(body)["path"] is None


def test_registration_takes_the_first_snapshot(env, auth):
    status, _h, body = env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["configured"] is True
    assert payload["state"] == "first"
    assert payload["delta"] is None


def test_registration_rejects_a_blank_path(env, auth):
    status, _h, body = env.post_json("/sources/excel-watch", {"path": "  "}, auth)
    assert status == 400


def test_known_delta_after_24h_on_the_changed_fixture(env, auth):
    env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    env.workbook.write_bytes(make_xlsx(CHANGED_ROWS))
    env.clock.advance(24 * 3600)
    status, _h, body = env.post_json("/sources/excel-watch/retest", {}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "healthy"
    added = payload["delta"]["added"]
    removed = payload["delta"]["removed"]
    assert added == [["Atlas ERP modules", 44.0, 176000.0]]
    assert removed == [["Atlas ERP modules", 41.0, 164000.0]]


def test_a_broken_widget_renders_an_error_page_not_a_dead_socket(env, auth):
    def boom():
        raise RuntimeError("injected failure")

    env.watch.status = boom
    status, _h, body = env.request("GET", "/", auth)
    assert status == 500
    assert b"Something broke" in body


def test_widget_endpoint_carries_the_same_payload(env, auth):
    env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    status, _h, body = env.request("GET", "/widgets/sales-24h", auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["configured"] is True
    assert payload["state"] == "first"


def test_exclusively_open_workbook_shows_amber_and_recovers(env, auth):
    env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    direct_copy = env.watch.adapters.copy_shadow

    def locked(path):
        raise WorkbookLocked("Q4-sales.xlsx is open in Excel right now")

    env.watch.adapters.copy_shadow = locked
    status, _h, body = env.post_json("/sources/excel-watch/retest", {}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "locked"
    assert "Excel" in payload["cause"]

    # The page carries the amber state: attention freshness and a Re-test.
    page_status, _h, page_body = env.request("GET", "/", auth)
    page = page_body.decode("utf-8")
    assert page_status == 200
    assert "open in Excel" in page
    assert "data-retest" in page

    # Releasing the file and re-testing recovers to healthy.
    env.clock.advance(24 * 3600)
    env.workbook.write_bytes(make_xlsx(CHANGED_ROWS))
    env.watch.adapters.copy_shadow = direct_copy
    status, _h, body = env.post_json("/sources/excel-watch/retest", {}, auth)
    payload = json.loads(body)
    assert payload["state"] == "healthy"
    assert payload["delta"]["added"] == [["Atlas ERP modules", 44.0, 176000.0]]


def test_stale_data_is_labeled_on_the_widget_endpoint(env, auth):
    env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    env.clock.advance(env.watch.stale_after_s + 1)
    _status, _h, body = env.request("GET", "/widgets/sales-24h", auth)
    assert json.loads(body)["state"] == "stale"


def test_dashboard_renders_the_live_widget_once_registered(env, auth):
    page_status, _h, page_body = env.request("GET", "/", auth)
    assert 'data-widget-id="sales-24h"' in page_body.decode("utf-8")
    assert b"Sample data until then." in page_body

    env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    _status, _h, page_body = env.request("GET", "/", auth)
    page = page_body.decode("utf-8")
    assert "First snapshot taken" in page  # honest: deltas start next poll
    assert "Sample data until a workbook is connected." not in page

    env.clock.advance(24 * 3600)
    env.workbook.write_bytes(make_xlsx(CHANGED_ROWS))
    env.post_json("/sources/excel-watch/retest", {}, auth)
    _status, _h, page_body = env.request("GET", "/", auth)
    assert "Rows changed, 24 h" in page_body.decode("utf-8")


def test_zero_row_one_row_and_huge_values_render(env, auth):
    env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    env.clock.advance(24 * 3600)
    env.workbook.write_bytes(make_xlsx([]))
    env.post_json("/sources/excel-watch/retest", {}, auth)
    status, _h, page_body = env.request("GET", "/", auth)
    page = page_body.decode("utf-8")
    assert status == 200
    # The zero-row poll reads as "everything was removed", rendered as rows.
    assert "4" in page and "Atlas ERP modules" in page

    env.clock.advance(24 * 3600)
    env.workbook.write_bytes(make_xlsx([["Big", 1e300, 12345678901234.0]]))  # one row, huge values
    env.post_json("/sources/excel-watch/retest", {}, auth)
    _status, _h, page_body = env.request("GET", "/", auth)
    page = page_body.decode("utf-8")
    assert "12,345,678,901,234" in page  # huge values formatted, not broken
    assert page.count('<article class="widget') == 4

    # An unchanged re-poll is the designed zero state, not an empty card.
    env.clock.advance(24 * 3600)
    env.workbook.write_bytes(make_xlsx([["Big", 1e300, 12345678901234.0]]))
    env.post_json("/sources/excel-watch/retest", {}, auth)
    _status, _h, page_body = env.request("GET", "/", auth)
    assert "No changes in the last 24 hours." in page_body.decode("utf-8")
