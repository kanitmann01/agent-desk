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
from agentdesk.plugins.config import ConfigError
from agentdesk.server import app as server_app
from excel_fixtures import BASE_ROWS, base_workbook, make_xlsx

CHANGED_ROWS = [
    ["Product line", "Units", "Revenue"],
    ["Atlas ERP modules", 44.0, 176000.0],
    ["Field services", 12.0, 58000.0],
    ["Care plans", 7.0, 22500.0],
]


def _torn_workbook_bytes() -> bytes:
    """A genuine fixture whose first shared-string cell points past the
    table: zip-valid, parse-torn."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base_workbook())) as src, zipfile.ZipFile(buffer, "w") as out:
        for info in src.infolist():
            out.writestr(info, src.read(info).decode("utf-8").replace(
                '<c r="A1" t="s"><v>0</v></c>', '<c r="A1" t="s"><v>999</v></c>'))
    return buffer.getvalue()


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


def test_registration_rejects_a_missing_path(env, auth):
    ghost = env.workbook.parent / "not-there.xlsx"
    status, _h, body = env.post_json("/sources/excel-watch", {"path": str(ghost)}, auth)
    payload = json.loads(body)
    assert status == 400
    assert "does not exist" in payload["error"]
    assert str(ghost) in payload["error"]


def test_registration_rejects_a_directory(env, auth):
    status, _h, body = env.post_json(
        "/sources/excel-watch", {"path": str(env.workbook.parent)}, auth
    )
    payload = json.loads(body)
    assert status == 400
    assert "folder" in payload["error"]


def test_registration_rejects_an_unsupported_extension(env, auth):
    csv = env.workbook.parent / "Q4-sales.csv"
    csv.write_text("Product line,Units\nAtlas,41\n", encoding="utf-8")
    status, _h, body = env.post_json("/sources/excel-watch", {"path": str(csv)}, auth)
    payload = json.loads(body)
    assert status == 400
    # The cause names what the reader can actually open.
    assert ".xlsx" in payload["error"] and ".xlsm" in payload["error"]
    assert ".xls" in payload["error"] and ".csv" in payload["error"]


def test_registration_rejects_an_unreadable_file(env, auth, monkeypatch):
    monkeypatch.setattr(server_app, "probe_readable", lambda candidate: False)
    status, _h, body = env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    payload = json.loads(body)
    assert status == 400
    assert "locked" in payload["error"]
    # Nothing was registered: the watch stays unconfigured.
    assert json.loads(env.request("GET", "/widgets/sales-24h", auth)[2])["configured"] is False


def test_registration_error_is_json_so_the_card_can_show_it(env, auth):
    status, headers, body = env.post_json(
        "/sources/excel-watch", {"path": "D:/ghost/Q4.xlsx"}, auth
    )
    assert status == 400
    assert headers["Content-Type"].startswith("application/json")
    assert "error" in json.loads(body)


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
    assert "No workbook is connected yet" in page_body.decode("utf-8")

    env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    _status, _h, page_body = env.request("GET", "/", auth)
    page = page_body.decode("utf-8")
    assert "First snapshot taken" in page  # honest: deltas start next poll
    assert "No workbook is connected yet" not in page

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
    assert page.count('<article class="widget') == 3

    # An unchanged re-poll is the designed zero state, not an empty card.
    env.clock.advance(24 * 3600)
    env.workbook.write_bytes(make_xlsx([["Big", 1e300, 12345678901234.0]]))
    env.post_json("/sources/excel-watch/retest", {}, auth)
    _status, _h, page_body = env.request("GET", "/", auth)
    assert "No changes in the last 24 hours." in page_body.decode("utf-8")


class FakePickerProcess:
    """What subprocess.run returns for a picker child: stdout only matters."""

    def __init__(self, stdout):
        self.stdout = stdout


class TestTkPickerParentParsing:
    """The picker child does the Tk work; the parent only parses stdout.

    The real child (a fresh interpreter running Tk on its own main thread)
    is never spawned here: subprocess.run is faked, so these tests hold on
    any OS and never open a dialog.
    """

    def test_returns_the_path_the_child_printed(self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["kwargs"] = kwargs
            return FakePickerProcess(stdout=json.dumps(
                {"status": "picked", "path": "D:/books/Q4-sales.xlsx"}) + "\n")

        monkeypatch.setattr(server_app.subprocess, "run", fake_run)

        assert server_app.tk_pick_workbook() == "D:/books/Q4-sales.xlsx"
        # The child is a fresh interpreter running the snippet, not this server.
        assert seen["cmd"][0] == sys.executable
        assert "-c" in seen["cmd"]

    def test_empty_output_is_still_none_for_the_workbook_picker(self, monkeypatch):
        # The dashboard and calendar pages publish 200 {"path": null} for
        # "no dialog here, type it", so the workbook picker keeps folding
        # an unreadable child into None; only the plugin picker reports it.
        def fake_run(cmd, **kwargs):
            return FakePickerProcess(stdout="\n")

        monkeypatch.setattr(server_app.subprocess, "run", fake_run)

        assert server_app.tk_pick_workbook() is None

    def test_a_child_that_cannot_start_is_not_an_error(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise OSError("child could not start")

        monkeypatch.setattr(server_app.subprocess, "run", fake_run)

        assert server_app.tk_pick_workbook() is None

    def test_the_plugin_picker_reports_a_dialog_that_did_not_open(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return FakePickerProcess(stdout="")

        monkeypatch.setattr(server_app.subprocess, "run", fake_run)

        # The setup route is the one that must tell a cancel from a broken
        # dialog, so its picker propagates the refusal instead of None.
        with pytest.raises(ConfigError) as caught:
            server_app.tk_pick_plugin_file()
        assert caught.value.code == "config:picker-unavailable"
        assert server_app.tk_pick_workbook() is None


class TestPickerOutcome:
    """The child's one JSON line: picked, cancelled, unavailable.

    Nothing else may mean cancelled - a traceback or an empty line is a
    dialog that did not open, not a decision the user made.
    """

    def test_a_picked_document_returns_the_path(self):
        stdout = '\n{"status": "picked", "path": "C:/books/q4.xlsx"}\n\n'
        assert server_app._picker_outcome(stdout) == "C:/books/q4.xlsx"

    def test_a_cancelled_document_answers_none(self):
        assert server_app._picker_outcome('{"status": "cancelled"}') is None

    def test_an_unavailable_document_raises_picker_unavailable(self):
        with pytest.raises(ConfigError) as caught:
            server_app._picker_outcome('{"status": "unavailable", "reason": "TclError"}')
        assert caught.value.code == "config:picker-unavailable"
        assert caught.value.message == (
            "The file dialog could not open on this computer. "
            "Type the file's path, or upload the file instead.")

    def test_garbage_raises_picker_unavailable(self):
        with pytest.raises(ConfigError) as caught:
            server_app._picker_outcome("Traceback (most recent call last):\n  TclError: no display")
        assert caught.value.code == "config:picker-unavailable"

    def test_empty_output_raises_picker_unavailable(self):
        with pytest.raises(ConfigError) as caught:
            server_app._picker_outcome("")
        assert caught.value.code == "config:picker-unavailable"


class TestPickerDialogVisibility:
    """The dialog must be findable: parented, lifted, focused, topmost.

    A parentless dialog on Windows can open behind the browser, which
    reads to the manager as a button that does nothing.
    """

    def test_workbook_snippet_parents_and_raises_the_dialog(self):
        snippet = server_app.WORKBOOK_PICK_SNIPPET
        assert "parent=root" in snippet
        assert "root.lift()" in snippet
        assert "root.focus_force()" in snippet
        assert "-topmost" in snippet

    def test_snippet_survives_a_broken_tk(self):
        # The child answers one JSON document, never a traceback: the
        # three statuses are what separate a cancel from a broken dialog.
        snippet = server_app.WORKBOOK_PICK_SNIPPET
        assert '"status": "picked"' in snippet
        assert '"status": "cancelled"' in snippet
        assert '"status": "unavailable"' in snippet
        assert "json.dumps" in snippet
        assert "print(chosen)" not in snippet
        # The answer leaves the child before teardown can fail.
        assert snippet.index("json.dumps") < snippet.index("root.destroy")


def test_pick_failure_is_never_silent_and_never_teaches_a_typed_path():
    from agentdesk.server import pages

    script = pages.APP_JS
    # A null path is its own honest amber note: try again, never type.
    assert "The file dialog did not open" in script
    assert "Type the workbook path" not in script
    assert "data-manual-connect" not in script
    assert "workbook-path" not in script
    # Fetch and HTTP failures surface inline instead of disappearing.
    assert script.count(".catch(") >= 3
    assert "res.data.error" in script


def test_unconfigured_card_is_picker_only(env, auth):
    """The native picker is the contract: the card offers the dialog and
    an amber note for its failure, and no typed-path form anywhere."""
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert 'data-pick' in page
    assert 'id="pick-note" hidden' in page
    assert "manual-connect" not in page
    assert 'id="workbook-path"' not in page
    assert "Type the workbook path" not in page


def test_a_malformed_workbook_registers_into_the_amber_state_not_a_500(
        env, auth, tmp_path):
    """A zip-valid but torn workbook (shared-string index past the table)
    lands in the designed unreadable amber with a cause; the register
    route and the dashboard answer, never the generic error page."""
    torn_path = tmp_path / "torn.xlsx"
    torn_path.write_bytes(_torn_workbook_bytes())
    status, _h, body = env.post_json("/sources/excel-watch", {"path": str(torn_path)}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "unreadable"
    assert "Can't read the workbook" in payload["cause"]
    page_status, _h, page_body = env.request("GET", "/", auth)
    page = page_body.decode("utf-8")
    assert page_status == 200
    assert "Check it is a valid .xlsx" in page  # the amber cause, escaped
    assert "Something broke" not in page


def test_the_delta_label_names_the_actual_window_after_a_long_gap(env, auth):
    """A closed laptop over a weekend: the diff is still against the
    newest snapshot before the 24-hour mark, and the card says which
    window that was instead of claiming '24 hours'."""
    env.post_json("/sources/excel-watch", {"path": str(env.workbook)}, auth)
    env.workbook.write_bytes(make_xlsx(CHANGED_ROWS))
    env.clock.advance(3 * 24 * 3600)
    status, _h, body = env.post_json("/sources/excel-watch/retest", {}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "healthy"
    assert payload["reference_ts"] is not None
    assert payload["last_ok_ts"] - payload["reference_ts"] > 2 * 24 * 3600
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert "Rows changed, 24 h" not in page
    assert "newest snapshot before the 24-hour mark" in page
