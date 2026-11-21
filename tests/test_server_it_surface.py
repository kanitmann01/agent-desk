"""The IT-facing surface tests: audit coverage, CSV export, the touches
page, and the license manifest gate.

Everything here reads the store the way Security will: through the CSV
and the generated page, not through internals.
"""

import csv
import io
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.excel.watcher import Adapters, ExcelWatch
from agentdesk.excel.xlsx import parse_workbook_bytes
from excel_fixtures import base_workbook


@pytest.fixture()
def env():
    """Booted server with inert watches wired to the audit store."""
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _csv_rows(booted, auth):
    status, headers, body = booted.request("GET", "/audit/export.csv", auth)
    assert status == 200
    assert headers["Content-Type"].startswith("text/csv")
    reader = csv.reader(io.StringIO(body.decode("utf-8")))
    return list(reader)


def test_excel_calendar_and_research_activity_all_audited(tmp_path):
    workbook = tmp_path / "Q4-sales.xlsx"
    workbook.write_bytes(base_workbook())
    watch = ExcelWatch(
        sqlite3.connect(":memory:", check_same_thread=False),
        Adapters(
            copy_shadow=lambda p: Path(p),
            parse_workbook=lambda p: parse_workbook_bytes(Path(p).read_bytes()),
            clock=lambda: 1_000_000.0,
        ),
    )
    booted = server_harness.Booted(excel=watch)
    try:
        auth = booted.exchange()
        watch.register(str(workbook))

        # Calendar ingestion through the wired bridge.
        cal_file = tmp_path / "calendar_sync.json"
        cal_file.write_text(
            json.dumps({"generatedAt": datetime.now().astimezone().isoformat(), "events": []}),
            encoding="utf-8",
        )
        bridge = booted.server.calendar
        old_read = bridge.adapters.read_calendar
        bridge.adapters.read_calendar = lambda: (str(cal_file), cal_file.read_bytes())
        try:
            booted.post_json("/sources/calendar-bridge/retest", {}, auth)
        finally:
            bridge.adapters.read_calendar = old_read

        # A research call through a stub endpoint.
        booted.server.llm = lambda prompt: json.dumps({"summary": "s", "sources": ["memo.pdf"]})
        booted.post_json("/research", {"question": "anything"}, auth)

        rows = _csv_rows(booted, auth)
        header, data = rows[0], rows[1:]
        assert header == ["actor", "action", "target", "timestamp"]
        actions = {row[1] for row in data}
        assert {"excel.register", "excel.poll", "calendar.ingest", "llm.research"} <= actions
        targets = {row[2] for row in data}
        assert "Q4-sales.xlsx" in targets
        assert "calendar_sync.json" in targets
    finally:
        booted.close()


def test_csv_opens_clean_without_multiline_cells(env, auth):
    env.server.llm = lambda prompt: "irrelevant"
    env.post_json("/research", {"question": "one"}, auth)
    env.post_json("/research", {"question": "two"}, auth)
    rows = _csv_rows(env, auth)
    assert rows[0] == ["actor", "action", "target", "timestamp"]
    for row in rows[1:]:
        assert len(row) == 4, f"row split across lines: {row}"
        for field in row:
            assert "\n" not in field and "\r" not in field


def test_touches_page_is_generated_from_the_vocabulary(env, auth):
    env.server.llm = lambda prompt: json.dumps({"summary": "s", "sources": []})
    env.post_json("/research", {"question": "anything"}, auth)
    status, _h, body = env.request("GET", "/what-this-touches", auth)
    page = body.decode("utf-8")
    assert status == 200
    # Observed vocabulary is marked in use; the rest says not observed.
    assert "llm.research" in page and "in use" in page
    assert "not observed yet" in page
    # The static facts are the same facts the code enforces.
    assert "Processes started:" in page and "none" in page
    assert "Persistence:" in page and "No Run key" in page
    assert "delete the folder" in page
    # The claim matches THIRD-PARTY-NOTICES.md: the Python runtime
    # carries exactly one dependency (ticket #94), the bundle carries
    # the documented, licensed set.
    assert "cryptography" in page
    assert "Apache-2.0 OR BSD-3-Clause" in page
    assert "No third-party components" not in page


def test_the_touches_table_lists_every_action_the_app_can_record():
    # The table is generated from VOCABULARY alone, so an action the app
    # records but the vocabulary misses under-describes the machine to
    # the one reviewer who reads this page (spec 017 workstream 3): the
    # rows the audit found missing, the press included, must all render.
    from agentdesk.assistant import audit as audit_store
    from agentdesk.server import touches
    page = touches.render_touches(
        {"insight.press"}, "test", datetime(2026, 11, 21, 9, 0)
    )
    for action in ("insight.press", "llm.observe", "memory.capture",
                   "memory.keep", "memory.remove", "memory.undo",
                   "settings.preferences", "settings.hosts",
                   "agents.download"):
        assert f"<td class='mono'>{action}</td>" in page
    # The badge tells the truth about the one action this desk ran.
    press_row = page.split("<td class='mono'>insight.press</td>", 1)[1]
    assert "touch-badge on" in press_row.split("</tr>", 1)[0]


def test_notices_file_states_the_shipped_set():
    notices = (Path(__file__).resolve().parents[1] / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    # The notices file is the authoritative distribution record now the
    # legacy manifest is gone (spec 017 6f): the Python runtime carries
    # one dependency (cryptography, ticket #94), the SPA bundle carries
    # a documented set, and every shipped component has a hashed
    # upstream licence text.
    assert "cryptography" in notices
    assert "Apache-2.0 OR BSD-3-Clause" in notices
    # The bundle ships React and the warm-paper system fonts (the
    # dark-glass theme's fonts, its vendored effects drawer, motion,
    # Tailwind and clsx all left with that theme; see DESIGN.md). The
    # shipped list here is the contract, and the replaced fonts must be
    # gone from the file entirely.
    for shipped in (
        "react | 19",
        "@fontsource/geist",
        "@fontsource/geist-mono",
        "OFL-1.1",
    ):
        assert shipped in notices, shipped
    for gone in ("@fontsource-variable/inter", "@fontsource-variable/space-grotesk"):
        assert gone not in notices, gone
    assert "MIT" in notices and "Apache-2.0" in notices


def test_license_and_notice_ship_in_the_install_folder():
    repo = Path(__file__).resolve().parents[1]
    assert (repo / "LICENSE").is_file()
    # NOTICE is required only for Apache-2.0 components; there are none,
    # and the manifest is the record of that.
    assert not (repo / "NOTICE").is_file()


def test_audit_csv_requires_a_session(env):
    status, _h, _b = env.request("GET", "/audit/export.csv", env.host_header())
    assert status == 401


def test_data_dir_statement_matches_the_real_resolution(monkeypatch, tmp_path):
    from agentdesk.server import touches
    from agentdesk.server.app import default_data_dir

    monkeypatch.delenv("AGENTDESK_DATA", raising=False)
    assert touches.data_dir_statement() == str(Path.home() / ".agent-desk")
    assert default_data_dir() == Path.home() / ".agent-desk"

    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    assert touches.data_dir_statement() == str(tmp_path / "data")
    assert default_data_dir() == Path(tmp_path / "data")
