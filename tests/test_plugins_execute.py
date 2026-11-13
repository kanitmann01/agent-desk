"""The plugin widget runner: excel-watch execution and ui-schema binding.

Adapters are fakes throughout (the shadow copy is the identity, the
parser returns a mutable list, the clock is a number the test moves),
so these tests cover the runner's own behavior: probe-shaped status,
honest amber states, and the binding of real poll results into the
ui-schema render model. The excel arithmetic itself is covered by the
excel suite; here it only has to arrive. The pipeline bindings
(calendar-read, mail-digest, research-brief) run against real bridges,
watches and stores over in-memory sqlite and frozen clocks: the same
objects the dashboard's own cards read.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.excel.core import WorkbookLocked  # noqa: E402
from agentdesk.excel.watcher import Adapters  # noqa: E402
from agentdesk.plugins.execute import PluginWidgetRunner  # noqa: E402
from agentdesk.plugins.runtime import PluginRuntime  # noqa: E402
from plugins_fixtures import valid_zip  # noqa: E402

DAY = 24 * 60 * 60.0


class FakeWorkbook:
    """A parseable workbook the test mutates between polls."""

    def __init__(self, rows):
        self.rows = rows
        self.locked = False

    def parse(self, _path):
        if self.locked:
            raise WorkbookLocked()
        return self.rows


def _runner(workspace: Path, workbook: FakeWorkbook, clock: list[float]):
    adapters = Adapters(copy_shadow=lambda path: Path(path),
                        parse_workbook=workbook.parse,
                        clock=lambda: clock[0])
    return PluginWidgetRunner(workspace, adapters=adapters)


def _manifest(tmp_path: Path, *, source_type="excel-watch",
              file_glob="${workspace}/reports/*.xlsx", elements=None) -> dict:
    return {
        "id": "sales-delta-widget",
        "contributes": {"widgets": [{
            "id": "sales-delta",
            "dataSource": {"type": source_type, "file": file_glob,
                           "deltaWindow": "24h"},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }


@pytest.fixture
def workspace(tmp_path):
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    (reports / "sales.xlsx").write_bytes(b"xlsx")
    return tmp_path / "workspace"


def _write_ui(version_dir: Path, elements: list) -> None:
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (version_dir / "widget.ui.json").write_text(
        json.dumps({"type": "card", "elements": elements}), encoding="utf-8")


def test_first_poll_is_fresh_with_baseline_note(workspace, tmp_path):
    workbook = FakeWorkbook([["Region", "Sales"], ["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "delta24h", "label": "Changed rows"},
    ])
    status = runner.attach("p1", _manifest(tmp_path), version_dir,
                           tmp_path / "data")
    assert status["status"] == "fresh"
    payload = runner.payload("p1")
    assert payload is not None
    assert payload["status"] == "fresh"
    assert payload["elements"] == [
        {"kind": "metric", "label": "Changed rows",
         "value": "First snapshot taken; changes show on the next refresh."},
    ]


def test_delta_binds_after_the_window(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "delta24h"},
        {"type": "metric", "binding": "addedCount", "label": "New"},
        {"type": "metric", "binding": "removedCount", "label": "Removed"},
        {"type": "text", "binding": "windowNote"},
    ])
    runner.attach("p1", _manifest(tmp_path), version_dir, tmp_path / "data")
    workbook.rows = [["North", 10], ["South", 20]]
    clock[0] += DAY + 60
    status = runner.retest("p1")
    assert status["status"] == "fresh"
    payload = runner.payload("p1")
    metrics = [e["value"] for e in payload["elements"] if e["kind"] == "metric"]
    assert metrics[0] == "1 new rows."
    assert metrics[1] == "1"
    assert metrics[2] == "0"
    notes = [e["text"] for e in payload["elements"] if e["kind"] == "text"]
    assert notes == ["Compared with the snapshot from about 24 hours ago."]


def test_locked_workbook_is_amber_with_cause(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "metric", "binding": "delta24h"}])
    runner.attach("p1", _manifest(tmp_path), version_dir, tmp_path / "data")
    workbook.locked = True
    clock[0] += DAY + 60
    status = runner.retest("p1")
    assert status["status"] == "attention"
    assert "open in Excel" in status["cause"]
    # The card renders amber; the payload still binds nothing false.
    payload = runner.payload("p1")
    assert payload["status"] == "attention"


def test_unexecutable_type_keeps_probe_parity(workspace, tmp_path):
    workbook = FakeWorkbook([["x"]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    status = runner.attach("p1", _manifest(tmp_path, source_type="json-watch"),
                           tmp_path / "plugin", tmp_path / "data")
    assert status == {"status": "fresh", "cause": "",
                      "checked_at": status["checked_at"],
                      "file": "sales.xlsx"}
    assert not runner.attached("p1")
    assert runner.payload("p1") is None


def test_no_matching_file_is_attention(workspace, tmp_path):
    workbook = FakeWorkbook([["x"]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    status = runner.attach("p1", _manifest(
        tmp_path, file_glob="${workspace}/reports/*.missing"),
        tmp_path / "plugin", tmp_path / "data")
    assert status["status"] == "attention"
    assert "no file matches" in status["cause"]


def test_unknown_bindings_and_kinds_are_dropped(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "inventedNumber"},
        {"type": "metric", "binding": "rowsSeen", "label": "Rows"},
        {"type": "chart", "binding": "delta24h"},
        {"type": "text", "text": "Static note"},
    ])
    runner.attach("p1", _manifest(tmp_path), version_dir, tmp_path / "data")
    payload = runner.payload("p1")
    assert payload["elements"] == [
        {"kind": "metric", "label": "Rows", "value": "1"},
        {"kind": "text", "text": "Static note"},
    ]


def test_runtime_installs_executes_and_retests_the_widget(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    zip_path = valid_zip(tmp_path / "sales.zip")
    result = runtime.install(zip_path)
    assert result["ok"] is True
    record = runtime.record("sales-delta-widget")
    assert record["data_source"]["status"] == "fresh"

    cards = runtime.widget_cards()
    assert len(cards) == 1
    payload = cards[0]["payload"]
    assert payload is not None
    metrics = [e["value"] for e in payload["elements"] if e["kind"] == "metric"]
    assert metrics == ["First snapshot taken; changes show on the next refresh."]

    workbook.rows = [["North", 10], ["South", 20], ["East", 5], ["West", 1]]
    clock[0] += DAY + 60
    runtime.retest("sales-delta-widget")
    cards = runtime.widget_cards()
    metrics = [e["value"] for e in cards[0]["payload"]["elements"]
               if e["kind"] == "metric"]
    assert metrics[0] == "3 new rows."


def test_disable_detaches_and_enable_reattaches(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    runtime.install(valid_zip(tmp_path / "sales.zip"))
    assert runner.attached("sales-delta-widget")

    runtime.disable("sales-delta-widget")
    assert not runner.attached("sales-delta-widget")
    assert runtime.widget_cards() == []

    runtime.enable("sales-delta-widget")
    assert runner.attached("sales-delta-widget")
    cards = runtime.widget_cards()
    assert cards and cards[0]["freshness"] == "fresh"


def test_uninstall_detaches_but_keeps_data(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    runtime.install(valid_zip(tmp_path / "sales.zip"))
    data_dir = Path(runtime.record("sales-delta-widget")["data_dir"])

    runtime.uninstall("sales-delta-widget")
    assert not runner.attached("sales-delta-widget")
    assert data_dir.exists()  # preserved until the named purge


# The pipeline bindings (#64): calendar-read, mail-digest and
# research-brief execute against the built-in pipelines, injected the
# way the excel path injects its watches. A real bridge/watch/store over
# an in-memory sqlite and a frozen clock, so every state here is the
# state the dashboard's own cards would see.

def _pipeline_manifest(source_type: str) -> dict:
    """A pipeline-backed widget: the data lives in the shared pipeline,
    so the data source names its type and nothing else."""
    return {
        "id": f"{source_type}-widget",
        "contributes": {"widgets": [{
            "id": "w",
            "dataSource": {"type": source_type},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }


def _bridge(tmp_path, now, events):
    """A real CalendarBridge over a seeded calendar_sync.json body, its
    clock frozen at `now`, already polled once so its document is live.
    events=None seeds no file at all: the bridge's empty state."""
    import sqlite3

    from agentdesk.calendar.watcher import Adapters as CalendarAdapters
    from agentdesk.calendar.watcher import CalendarBridge

    def read_calendar():
        if events is None:
            return None
        doc = json.dumps({"generatedAt": now.isoformat(), "events": events})
        return ("onedrive/agent-desk/calendar_sync.json", doc.encode("utf-8"))

    adapters = CalendarAdapters(read_calendar=read_calendar,
                                clock=lambda: now.timestamp())
    bridge = CalendarBridge(sqlite3.connect(":memory:", check_same_thread=False),
                            adapters,
                            llm=lambda _p: '{"subtasks": [], "followups": []}')
    bridge.poll()
    return bridge


def test_calendar_read_binds_today_from_the_bridge(workspace, tmp_path):
    now = datetime(2026, 11, 13, 9, 0, 0).astimezone()
    events = [
        {"id": "a", "subject": "Q4 pipeline review",
         "start": now.replace(hour=14).isoformat(),
         "end": now.replace(hour=15).isoformat()},
        {"id": "b", "subject": "Later sync",
         "start": now.replace(hour=16).isoformat(),
         "end": now.replace(hour=17).isoformat()},
        {"id": "c", "subject": "Tomorrow",
         "start": (now + timedelta(days=1)).replace(hour=10).isoformat(),
         "end": (now + timedelta(days=1)).replace(hour=11).isoformat()},
    ]
    runner = PluginWidgetRunner(workspace, calendar=_bridge(tmp_path, now, events))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "nextEventTitle", "label": "Next"},
        {"type": "metric", "binding": "nextEventTime", "label": "At"},
        {"type": "metric", "binding": "eventsToday", "label": "Today"},
        {"type": "text", "binding": "windowNote"},
    ])
    status = runner.attach("p1", _pipeline_manifest("calendar-read"),
                           version_dir, tmp_path / "data")
    assert status["status"] == "fresh"
    payload = runner.payload("p1")
    assert payload["status"] == "fresh"
    assert payload["cause"] == ""
    assert payload["elements"] == [
        {"kind": "metric", "label": "Next", "value": "Q4 pipeline review"},
        {"kind": "metric", "label": "At", "value": now.replace(hour=14).strftime("%H:%M")},
        {"kind": "metric", "label": "Today", "value": "2"},
        {"kind": "text",
         "text": "The next commitment and today's count, from the calendar file your flow syncs."},
    ]


def test_calendar_read_with_no_calendar_is_amber_with_cause(workspace, tmp_path):
    now = datetime(2026, 11, 13, 9, 0, 0).astimezone()
    runner = PluginWidgetRunner(workspace, calendar=_bridge(tmp_path, now, None))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "nextEventTitle", "label": "Next"},
        {"type": "metric", "binding": "eventsToday", "label": "Today"},
        {"type": "text", "binding": "windowNote"},
    ])
    status = runner.attach("p1", _pipeline_manifest("calendar-read"),
                           version_dir, tmp_path / "data")
    assert status["status"] == "attention"
    assert "calendar" in status["cause"].lower()
    payload = runner.payload("p1")
    assert payload["status"] == "attention"
    # Amber binds nothing: no invented titles, counts or notes.
    assert payload["elements"] == []


def test_calendar_read_without_a_bridge_is_amber(workspace, tmp_path):
    runner = PluginWidgetRunner(workspace)  # no calendar wired
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "metric", "binding": "nextEventTitle",
                             "label": "Next"}])
    status = runner.attach("p1", _pipeline_manifest("calendar-read"),
                           version_dir, tmp_path / "data")
    assert status["status"] == "attention"
    assert "calendar bridge" in status["cause"]
    payload = runner.payload("p1")
    assert payload["status"] == "attention"
    assert payload["elements"] == []


def test_calendar_card_ignores_excel_and_unknown_bindings(workspace, tmp_path):
    """Bindings are per source: a calendar card asking for excel counts
    or an invented name renders nothing for them, never a number."""
    now = datetime(2026, 11, 13, 9, 0, 0).astimezone()
    events = [
        {"id": "a", "subject": "Q4 pipeline review",
         "start": now.replace(hour=14).isoformat(),
         "end": now.replace(hour=15).isoformat()},
    ]
    runner = PluginWidgetRunner(workspace, calendar=_bridge(tmp_path, now, events))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "delta24h", "label": "Changed"},
        {"type": "metric", "binding": "inventedNumber", "label": "Made up"},
        {"type": "metric", "binding": "eventsToday", "label": "Today"},
        {"type": "text", "text": "Static note"},
    ])
    runner.attach("p1", _pipeline_manifest("calendar-read"),
                  version_dir, tmp_path / "data")
    payload = runner.payload("p1")
    assert payload["elements"] == [
        {"kind": "metric", "label": "Today", "value": "1"},
        {"kind": "text", "text": "Static note"},
    ]


# The mail-digest binding: a real MailWatch over a seeded .eml folder.
# The fixture files carry a placeholder body on purpose: the pipeline
# discards it at parse time (the Message record has no body field), and
# the tests pin that the bound card can only ever carry header counts.

def _eml(message_id: str, subject: str, sender: str, date_ts: float,
         in_reply_to: str = "") -> bytes:
    from email.utils import formatdate

    lines = [
        f"From: {sender}",
        "To: employee@example.com",
        f"Subject: {subject}",
        f"Date: {formatdate(date_ts, usegmt=True)}",
        f"Message-ID: {message_id}",
    ]
    if in_reply_to:
        lines.append(f"In-Reply-To: {in_reply_to}")
    lines += ["MIME-Version: 1.0",
              "Content-Type: text/plain; charset=utf-8",
              "",
              "a body that must never reach a card"]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _mail_runner(workspace, tmp_path, now_ts: float, files: dict,
                 folder=lambda: ""):
    import sqlite3

    from agentdesk.inbox.store import InboxStore
    from agentdesk.mail.core import read_eml_folder_reported
    from agentdesk.mail.store import MailStore
    from agentdesk.mail.watcher import Adapters as MailAdapters
    from agentdesk.mail.watcher import MailWatch

    folder_path = tmp_path / "mail"
    folder_path.mkdir(exist_ok=True)
    for name, raw in files.items():
        (folder_path / name).write_bytes(raw)
    chosen = folder()
    watch = MailWatch(
        inbox=InboxStore(sqlite3.connect(":memory:", check_same_thread=False),
                         lambda: now_ts),
        store=MailStore(sqlite3.connect(":memory:", check_same_thread=False),
                        lambda: now_ts),
        adapters=MailAdapters(read_folder=read_eml_folder_reported,
                              clock=lambda: now_ts),
        folder_provider=lambda: chosen,
    )
    return PluginWidgetRunner(workspace, mail=watch)


MAIL_WINDOW_NOTE = ("Counts cover the last 24 hours of message headers; "
                    "bodies are never read.")


def test_mail_digest_binds_header_only_counts(workspace, tmp_path):
    now = datetime(2026, 11, 13, 12, 0, 0).astimezone().timestamp()
    files = {
        # One active thread ("Q4 pricing": three messages, two senders)
        # and one thread whose only message is three days old.
        "m1.eml": _eml("<1@x>", "Q4 pricing", "a@example.com", now - 2 * 3600),
        "m2.eml": _eml("<2@x>", "Re: Q4 pricing", "b@example.com",
                       now - 3600, in_reply_to="<1@x>"),
        "m3.eml": _eml("<3@x>", "Re: Q4 pricing", "a@example.com",
                       now - 1800, in_reply_to="<2@x>"),
        "m4.eml": _eml("<4@x>", "Old thread", "c@example.com", now - 3 * DAY),
    }
    runner = _mail_runner(workspace, tmp_path, now, files,
                          folder=lambda: str(tmp_path / "mail"))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "messages", "label": "Messages"},
        {"type": "metric", "binding": "threads", "label": "Threads"},
        {"type": "metric", "binding": "topSenders", "label": "Top senders"},
        {"type": "text", "binding": "windowNote"},
    ])
    status = runner.attach("p1", _pipeline_manifest("mail-digest"),
                           version_dir, tmp_path / "data")
    assert status["status"] == "fresh"
    payload = runner.payload("p1")
    assert payload["status"] == "fresh"
    assert payload["elements"] == [
        {"kind": "metric", "label": "Messages", "value": "3"},
        {"kind": "metric", "label": "Threads", "value": "1"},
        {"kind": "metric", "label": "Top senders",
         "value": "a@example.com (2), b@example.com (1)"},
        {"kind": "text", "text": MAIL_WINDOW_NOTE},
    ]


def test_mail_digest_payload_carries_no_body_field(workspace, tmp_path):
    """The no-body rule is by construction, and pinned: the Message
    record has no body field, the binding vocabulary has no body-ish
    name, and a card asking for one renders nothing for it."""
    from dataclasses import fields

    from agentdesk.mail.core import Message
    from agentdesk.plugins.execute import BINDINGS

    assert "body" not in {f.name for f in fields(Message)}
    assert not any("body" in name.lower() for name in BINDINGS)

    now = datetime(2026, 11, 13, 12, 0, 0).astimezone().timestamp()
    files = {"m1.eml": _eml("<1@x>", "Q4 pricing", "a@example.com", now - 60)}
    runner = _mail_runner(workspace, tmp_path, now, files,
                          folder=lambda: str(tmp_path / "mail"))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "messages", "label": "Messages"},
        {"type": "metric", "binding": "body", "label": "Body"},
        {"type": "metric", "binding": "messageBody", "label": "Message body"},
        {"type": "metric", "binding": "bodyPreview", "label": "Preview"},
    ])
    runner.attach("p1", _pipeline_manifest("mail-digest"),
                  version_dir, tmp_path / "data")
    payload = runner.payload("p1")
    assert payload["elements"] == [
        {"kind": "metric", "label": "Messages", "value": "1"},
    ]
    assert "a body that must never reach a card" not in json.dumps(payload)


def test_mail_digest_without_a_folder_is_amber_with_cause(workspace, tmp_path):
    now = datetime(2026, 11, 13, 12, 0, 0).astimezone().timestamp()
    runner = _mail_runner(workspace, tmp_path, now, {}, folder=lambda: "")
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "messages", "label": "Messages"},
        {"type": "text", "binding": "windowNote"},
    ])
    status = runner.attach("p1", _pipeline_manifest("mail-digest"),
                           version_dir, tmp_path / "data")
    assert status["status"] == "attention"
    assert "Settings" in status["cause"]
    payload = runner.payload("p1")
    assert payload["status"] == "attention"
    assert payload["elements"] == []


def test_mail_digest_not_running_is_amber(workspace, tmp_path):
    runner = PluginWidgetRunner(workspace)  # no mail watcher wired
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "messages", "label": "Messages"},
    ])
    status = runner.attach("p1", _pipeline_manifest("mail-digest"),
                           version_dir, tmp_path / "data")
    assert status["status"] == "attention"
    assert "mail digest" in status["cause"].lower()
    assert runner.payload("p1")["elements"] == []
