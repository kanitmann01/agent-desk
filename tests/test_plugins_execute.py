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
from agentdesk.plugins.render import PluginRenderError  # noqa: E402
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
              file_glob="${workspace}/reports/*.xlsx", elements=None,
              source: dict | None = None) -> dict:
    data_source = {"type": source_type, "file": file_glob,
                   "deltaWindow": "24h"}
    if source:
        data_source.update(source)
    return {
        "id": "sales-delta-widget",
        "contributes": {"widgets": [{
            "id": "sales-delta",
            "dataSource": data_source,
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


def test_json_watch_attaches_and_reports_its_blank_state(workspace, tmp_path):
    """json-watch executes now: a selector-less source attaches as a
    blank with the reason, instead of keeping probe silence."""
    workbook = FakeWorkbook([["x"]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    _write_ui(tmp_path / "plugin", [{"type": "metric", "binding": "value"}])
    status = runner.attach("p1", _manifest(tmp_path, source_type="json-watch"),
                           tmp_path / "plugin", tmp_path / "data")
    assert status["status"] == "attention"
    assert status["state"] == "blank"
    assert status["reason"] == "bad-schema"
    assert "selector" in status["cause"]
    assert runner.attached("p1")
    payload = runner.payload("p1")
    assert payload["status"] == "attention"
    assert payload["source"]["state"] == "blank"
    assert payload["source"]["type"] == "json-watch"


def test_no_matching_file_is_attention(workspace, tmp_path):
    workbook = FakeWorkbook([["x"]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    status = runner.attach("p1", _manifest(
        tmp_path, file_glob="${workspace}/reports/*.missing"),
        tmp_path / "plugin", tmp_path / "data")
    assert status["status"] == "attention"
    assert "no file matches" in status["cause"]


def test_unknown_binding_renders_a_blank_element(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "inventedNumber", "label": "Made up"},
        {"type": "metric", "binding": "rowsSeen", "label": "Rows"},
        {"type": "text", "text": "Static note"},
    ])
    runner.attach("p1", _manifest(tmp_path), version_dir, tmp_path / "data")
    payload = runner.payload("p1")
    assert payload["elements"][0] == {
        "kind": "metric", "state": "blank",
        "reason": "no value for binding inventedNumber",
        "label": "Made up", "value": "",
    }
    assert payload["elements"][0]["value"] != "0"
    assert payload["elements"][1:] == [
        {"kind": "metric", "label": "Rows", "value": "1"},
        {"kind": "text", "text": "Static note"},
    ]


def test_unknown_element_kind_raises(workspace, tmp_path):
    workbook = FakeWorkbook([["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "chart", "binding": "delta24h"}])
    runner.attach("p1", _manifest(tmp_path), version_dir, tmp_path / "data")
    with pytest.raises(PluginRenderError) as info:
        runner.payload("p1")
    assert info.value.code == "plugin:unknown-element"
    assert "chart" in str(info.value)


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


def test_retest_attaches_a_source_that_became_available(tmp_path):
    """The amber install recovers through Re-test (#69): the workbook
    lands in the workspace after install, and the re-test must retry the
    attachment so the card binds real values, not just file presence."""
    workspace = tmp_path / "workspace"
    reports = workspace / "reports"
    reports.mkdir(parents=True)  # empty: the install is honestly amber
    workbook = FakeWorkbook([["Region", "Sales"], ["North", 10]])
    clock = [1_000_000.0]
    runner = _runner(workspace, workbook, clock)
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    runtime.install(valid_zip(tmp_path / "sales.zip"))
    record = runtime.record("sales-delta-widget")
    assert record["data_source"]["status"] == "attention"
    assert "no file matches" in record["data_source"]["cause"]
    assert not runner.attached("sales-delta-widget")

    # the workbook arrives after the amber install; Re-test recovers
    (reports / "sales.xlsx").write_bytes(b"xlsx")
    status = runtime.retest("sales-delta-widget")
    assert status["status"] == "fresh"
    assert runner.attached("sales-delta-widget")
    cards = runtime.widget_cards()
    payload = cards[0]["payload"]
    assert payload is not None
    metrics = [e["value"] for e in payload["elements"] if e["kind"] == "metric"]
    assert metrics == ["First snapshot taken; changes show on the next refresh."]


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

def _pipeline_manifest(source_type: str, source: dict | None = None) -> dict:
    """A pipeline-backed widget: the data lives in the shared pipeline,
    so the data source names its type. A source dict adds the optional
    per-widget options (for example mail-digest's vips)."""
    data_source = {"type": source_type}
    if source:
        data_source.update(source)
    return {
        "id": f"{source_type}-widget",
        "contributes": {"widgets": [{
            "id": "w",
            "dataSource": data_source,
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }


def _bridge(tmp_path, now, events, llm=None):
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
    if llm is None:
        llm = lambda _p: '{"subtasks": [], "followups": []}'  # noqa: E731
    bridge = CalendarBridge(sqlite3.connect(":memory:", check_same_thread=False),
                            adapters, llm=llm)
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


def test_calendar_card_retest_makes_no_llm_call(workspace, tmp_path):
    """The plugin card's re-test must spend zero endpoint requests
    (#75 review): it polls the shared bridge breakdown-free, so the
    counting client sees only the test's own setup poll."""
    now = datetime(2026, 11, 13, 9, 0, 0).astimezone()
    calls: list[str] = []

    def llm(prompt):
        calls.append(prompt)
        return '{"subtasks": [], "followups": []}'

    events = [
        {"id": "a", "subject": "Q4 pipeline review",
         "start": now.replace(hour=14).isoformat(),
         "end": now.replace(hour=15).isoformat()},
    ]
    bridge = _bridge(tmp_path, now, events, llm=llm)
    assert len(calls) == 1  # the setup poll's own breakdown
    runner = PluginWidgetRunner(workspace, calendar=bridge)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "nextEventTitle", "label": "Next"},
    ])
    runner.attach("p1", _pipeline_manifest("calendar-read"),
                  version_dir, tmp_path / "data")
    assert len(calls) == 1  # attaching reads the day view only

    # Move the event so the breakdown cache no longer answers for it:
    # a poll that wants a breakdown would have to ask the model now.
    events[0]["subject"] = "Moved review"
    events[0]["start"] = now.replace(hour=15).isoformat()
    events[0]["end"] = now.replace(hour=16).isoformat()
    status = runner.retest("p1")

    assert len(calls) == 1  # the re-test itself: no endpoint request
    assert status["status"] == "fresh"
    assert runner.payload("p1")["elements"] == [
        {"kind": "metric", "label": "Next", "value": "Moved review"},
    ]


def test_calendar_read_renders_busy_for_an_unnamed_event(workspace, tmp_path):
    """A real key event whose subject is empty is a busy slot, not an
    empty day (#75 review): the clear-day fallback applies only when
    there is no key event at all."""
    now = datetime(2026, 11, 13, 9, 0, 0).astimezone()
    events = [
        {"id": "a", "subject": "",
         "start": now.replace(hour=14).isoformat(),
         "end": now.replace(hour=15).isoformat()},
    ]
    runner = PluginWidgetRunner(workspace, calendar=_bridge(tmp_path, now, events))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "metric", "binding": "nextEventTitle", "label": "Next"},
    ])
    runner.attach("p1", _pipeline_manifest("calendar-read"),
                  version_dir, tmp_path / "data")
    assert runner.payload("p1")["elements"] == [
        {"kind": "metric", "label": "Next", "value": "Busy"},
    ]

    # The fallback stays honest on a genuinely clear day: everything
    # already over, no key event left.
    over = [
        {"id": "done", "subject": "Standup",
         "start": now.replace(hour=7).isoformat(),
         "end": now.replace(hour=8).isoformat()},
    ]
    clear = PluginWidgetRunner(workspace, calendar=_bridge(tmp_path, now, over))
    clear.attach("p2", _pipeline_manifest("calendar-read"),
                 version_dir, tmp_path / "data2")
    assert clear.payload("p2")["elements"] == [
        {"kind": "metric", "label": "Next", "value": "Nothing left today"},
    ]


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
        {"kind": "metric", "state": "blank",
         "reason": "no value for binding delta24h",
         "label": "Changed", "value": ""},
        {"kind": "metric", "state": "blank",
         "reason": "no value for binding inventedNumber",
         "label": "Made up", "value": ""},
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
    assert payload["elements"][0] == {
        "kind": "metric", "label": "Messages", "value": "1",
    }
    assert payload["elements"][1:] == [
        {"kind": "metric", "state": "blank",
         "reason": "no value for binding body",
         "label": "Body", "value": ""},
        {"kind": "metric", "state": "blank",
         "reason": "no value for binding messageBody",
         "label": "Message body", "value": ""},
        {"kind": "metric", "state": "blank",
         "reason": "no value for binding bodyPreview",
         "label": "Preview", "value": ""},
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


# The research-brief binding: the latest stored sourced answer, read
# from the local store. No endpoint client exists anywhere in the
# runner, so the plugin path cannot call one.

RESEARCH_WINDOW_NOTE = ("The latest stored research answer; showing it "
                        "made no endpoint call.")


def _research_store(now_ts: float, answer=None):
    import sqlite3

    from agentdesk.assistant.research_store import ResearchStore

    store = ResearchStore(
        sqlite3.connect(":memory:", check_same_thread=False),
        clock=lambda: now_ts)
    if answer is not None:
        store.save(answer[0], answer[1])
    return store


def test_research_brief_binds_the_latest_stored_answer(workspace, tmp_path):
    now = datetime(2026, 11, 13, 9, 41, 0).astimezone()
    runner = PluginWidgetRunner(workspace, research=_research_store(
        now.timestamp(),
        ("Five of nine EU partners reflected the new prices.",
         ["eu-price-memo.pdf", "channel-weekly.xlsx"])))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "text", "binding": "summary"},
        {"type": "metric", "binding": "sourcesCount", "label": "Sources"},
        {"type": "metric", "binding": "answeredAt", "label": "Answered"},
        {"type": "text", "binding": "windowNote"},
    ])
    status = runner.attach("p1", _pipeline_manifest("research-brief"),
                           version_dir, tmp_path / "data")
    assert status["status"] == "fresh"
    payload = runner.payload("p1")
    assert payload["status"] == "fresh"
    assert payload["elements"] == [
        {"kind": "text",
         "text": "Five of nine EU partners reflected the new prices."},
        {"kind": "metric", "label": "Sources", "value": "2"},
        {"kind": "metric", "label": "Answered", "value": "2026-11-13 09:41"},
        {"kind": "text", "text": RESEARCH_WINDOW_NOTE},
    ]


def test_research_brief_with_nothing_asked_is_the_honest_empty_state(
        workspace, tmp_path):
    now = datetime(2026, 11, 13, 9, 41, 0).astimezone()
    runner = PluginWidgetRunner(workspace,
                                research=_research_store(now.timestamp()))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "text", "binding": "summary"},
        {"type": "metric", "binding": "sourcesCount", "label": "Sources"},
        {"type": "text", "binding": "windowNote"},
    ])
    status = runner.attach("p1", _pipeline_manifest("research-brief"),
                           version_dir, tmp_path / "data")
    assert status["status"] == "attention"
    assert "Research" in status["cause"]
    payload = runner.payload("p1")
    assert payload["status"] == "attention"
    assert payload["elements"] == []


def test_research_brief_reads_only_the_local_store(workspace, tmp_path):
    """No LLM call occurs in the plugin path, pinned by construction:
    the binding's only data source is the store, and every read of the
    pipeline is a read of it."""
    now = datetime(2026, 11, 13, 9, 41, 0).astimezone()
    store = _research_store(now.timestamp(), ("Summary.", ["src"]))
    reads = []
    inner_latest = store.latest

    def counting_latest():
        reads.append(1)
        return inner_latest()

    store.latest = counting_latest
    runner = PluginWidgetRunner(workspace, research=store)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "text", "binding": "summary"}])
    runner.attach("p1", _pipeline_manifest("research-brief"),
                  version_dir, tmp_path / "data")
    runner.status("p1")
    payload = runner.payload("p1")
    assert payload["elements"] == [{"kind": "text", "text": "Summary."}]
    assert reads  # every pipeline read went through the store
    assert not hasattr(runner, "llm")  # and no endpoint client exists to call


def test_dashboard_build_reads_the_mail_folder_once(workspace, tmp_path):
    """One dashboard render, one pipeline read (#75 review): the runtime
    builds a plugin card's freshness and its bound payload from a single
    status+bindings pass, so the mail folder is read and parsed once per
    view, not once per half."""
    import sqlite3

    from agentdesk.inbox.store import InboxStore
    from agentdesk.mail.core import read_eml_folder_reported
    from agentdesk.mail.store import MailStore
    from agentdesk.mail.watcher import Adapters as MailAdapters
    from agentdesk.mail.watcher import MailWatch

    now = datetime(2026, 11, 13, 12, 0, 0).astimezone().timestamp()
    folder = tmp_path / "mail"
    folder.mkdir()
    (folder / "m1.eml").write_bytes(
        _eml("<1@x>", "Q4 pricing", "a@example.com", now - 60))
    reads = []

    def read_folder(path):
        reads.append(path)
        return read_eml_folder_reported(path)

    watch = MailWatch(
        inbox=InboxStore(sqlite3.connect(":memory:", check_same_thread=False),
                         lambda: now),
        store=MailStore(sqlite3.connect(":memory:", check_same_thread=False),
                        lambda: now),
        adapters=MailAdapters(read_folder=read_folder, clock=lambda: now),
        folder_provider=lambda: str(folder),
    )
    runner = PluginWidgetRunner(workspace, mail=watch)
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    source = tmp_path / "plugin-src"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({
        "schemaVersion": 1,
        "id": "desk-mail-digest",
        "name": "Mail digest",
        "version": "1.0.0",
        "publisher": "desk",
        "class": "declarative",
        "engines": {"dashboardHost": ">=1.0.0 <2.0.0"},
        "license": "MIT",
        "permissions": {
            "filesystem": {"read": [], "write": ["${pluginData}"]},
            "network": {"allow": []},
            "llm": {"allow": False},
            "shell": "none",
        },
        "activationEvents": ["onWidget:mail-digest"],
        "contributes": {"widgets": [{
            "id": "mail-digest", "size": "2x1",
            "dataSource": {"type": "mail-digest"},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
    }), encoding="utf-8")
    (source / "widget.ui.json").write_text(json.dumps({
        "type": "card", "elements": [
            {"type": "metric", "binding": "messages", "label": "Messages"},
        ]}), encoding="utf-8")
    assert runtime.install(source)["ok"] is True
    reads.clear()  # the install's own attach read once already

    cards = runtime.widget_cards()

    assert len(cards) == 1
    assert cards[0]["freshness"] == "fresh"
    metrics = [e["value"] for e in cards[0]["payload"]["elements"]
               if e["kind"] == "metric"]
    assert metrics == ["1"]
    assert len(reads) == 1  # one read for the whole dashboard build

# ---- header-mapped excel bindings ----

AGING_UI = [
    {"type": "metric", "binding": "value", "label": "Cash stuck"},
    {"type": "status", "binding": "status", "toneBinding": "tone"},
    {"type": "table", "title": "Aging buckets",
     "rowsBinding": "bucketTable",
     "columns": ["Bucket", "Amount", "Invoices"]},
    {"type": "list", "title": "Oldest balances", "rowsBinding": "rows"},
]


def test_excel_header_mapping_builds_rows_table_and_aging_buckets(workspace, tmp_path):
    """The manifest names columns; the workbook supplies the header. The
    card gets header-mapped rows, the windowed aggregate and the aging
    buckets, all capped and formatted, plus a target verdict."""
    now = datetime(2026, 11, 15, 12, 0, 0).astimezone()
    workbook = FakeWorkbook([
        ["Customer", "Balance", "DueDate"],
        ["Acme", 1200, "2026-11-10"],
        ["Beta", 800, "2026-09-01"],
        ["Gamma", 400, "2026-01-01"],
    ])
    clock = [now.timestamp()]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, AGING_UI)
    source = {"keyColumn": "Customer", "valueColumn": "Balance",
              "dateColumn": "DueDate", "window": "90d", "aggregate": "sum",
              "buckets": [30, 60, 90], "target": 1000}

    status = runner.attach("p1", _manifest(tmp_path, source=source),
                           version_dir, tmp_path / "data")

    assert status["status"] == "fresh"
    result, bindings = runner._read_pair("p1")
    assert result.state == "ok"
    assert bindings["value"] == 2000  # Gamma's 400 is outside the 90d window
    assert bindings["rowsSeen"] == 4
    assert bindings["direction"] == "flat"
    assert bindings["columns"] == ["Customer", "Balance", "DueDate"]
    assert bindings["rows"] == [
        {"primary": "Acme", "secondary": "1,200", "meta": "2026-11-10"},
        {"primary": "Beta", "secondary": "800", "meta": "2026-09-01"},
    ]
    assert bindings["table"] == {
        "columns": ["Customer", "Balance", "DueDate"],
        "rows": [["Acme", "1,200", "2026-11-10"],
                 ["Beta", "800", "2026-09-01"]],
    }
    assert bindings["bucketTable"] == [
        ["0-30", "1,200", "1"],
        ["31-60", "", "0"],
        ["61-90", "800", "1"],
        ["90+", "", "0"],
    ]
    assert bindings["bucketRows"][0] == {
        "primary": "0-30", "secondary": "1,200", "meta": "1 invoices"}
    assert bindings["target"] == 1000
    assert bindings["status"] == "over target"
    assert bindings["tone"] == "attention"

    payload = runner.payload("p1")
    assert payload["elements"] == [
        {"kind": "metric", "label": "Cash stuck", "value": "2000"},
        {"kind": "status", "text": "over target", "tone": "attention"},
        {"kind": "table", "title": "Aging buckets",
         "columns": ["Bucket", "Amount", "Invoices"],
         "rows": [["0-30", "1,200", "1"], ["31-60", "", "0"],
                  ["61-90", "800", "1"], ["90+", "", "0"]]},
        {"kind": "list", "title": "Oldest balances",
         "rows": [
             {"primary": "Acme", "secondary": "1,200", "meta": "2026-11-10"},
             {"primary": "Beta", "secondary": "800", "meta": "2026-09-01"},
         ]},
    ]


def test_excel_rows_and_table_are_capped_but_the_total_is_not(workspace, tmp_path):
    """Caps bound the card, not the arithmetic: the aggregate still sums
    every row in the window."""
    now = datetime(2026, 11, 15, 12, 0, 0).astimezone()
    workbook = FakeWorkbook(
        [["Customer", "Balance"]]
        + [[f"Customer {i}", 10] for i in range(30)])
    clock = [now.timestamp()]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "list", "rowsBinding": "rows"}])
    source = {"keyColumn": "Customer", "valueColumn": "Balance"}

    runner.attach("p1", _manifest(tmp_path, source=source), version_dir,
                  tmp_path / "data")

    _result_, bindings = runner._read_pair("p1")
    assert len(bindings["rows"]) == 8
    assert len(bindings["table"]["rows"]) == 20
    assert bindings["value"] == 300


def test_excel_without_a_target_reports_a_read_time_status(workspace, tmp_path):
    """A source with no target gets a truthful freshness line, not a
    made-up verdict."""
    now = datetime(2026, 11, 15, 12, 0, 0).astimezone()
    workbook = FakeWorkbook([["Customer", "Balance"], ["Acme", 1200]])
    clock = [now.timestamp()]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "status", "binding": "status",
                             "toneBinding": "tone"}])
    source = {"keyColumn": "Customer", "valueColumn": "Balance"}

    status = runner.attach("p1", _manifest(tmp_path, source=source),
                           version_dir, tmp_path / "data")

    assert status["status"] == "fresh"
    _result_, bindings = runner._read_pair("p1")
    assert bindings["status"] == "Read 12:00"
    assert bindings["tone"] == "ok"
    assert "target" not in bindings
    assert runner.payload("p1")["elements"] == [
        {"kind": "status", "text": "Read 12:00", "tone": "ok"}]


def test_excel_missing_column_blanks_with_the_column_name(workspace, tmp_path):
    """A declared column the workbook does not have is a blank that names
    it, never an empty card or an invented zero."""
    now = datetime(2026, 11, 15, 12, 0, 0).astimezone()
    workbook = FakeWorkbook([["Customer", "Balance"], ["Acme", 1200]])
    clock = [now.timestamp()]
    runner = _runner(workspace, workbook, clock)
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "metric", "binding": "value"}])
    source = {"keyColumn": "Customer", "valueColumn": "Outstanding"}

    status = runner.attach("p1", _manifest(tmp_path, source=source),
                           version_dir, tmp_path / "data")

    assert status["status"] == "attention"
    assert "Outstanding" in status["cause"]
    payload = runner.payload("p1")
    assert payload["status"] == "attention"
    assert payload["elements"] == []


def test_calendar_day_view_binds_week_points_upcoming_and_prep(workspace, tmp_path):
    """The bridge's day view carries the two-week load, the upcoming
    timeline and the next event's attendee prep list; the calendar card
    binds them without a model call."""
    now = datetime(2026, 11, 13, 9, 0, 0).astimezone()

    def at(days=0, hour=9):
        return (now + timedelta(days=days)).replace(hour=hour, minute=0)

    starts = {
        "a": at(hour=14), "b": at(hour=16), "c": at(days=1, hour=10),
        "d": at(days=3, hour=9), "e": at(days=20, hour=9),
    }
    events = [
        {"id": "a", "subject": "Q4 pipeline review",
         "start": starts["a"].isoformat(),
         "end": starts["a"].replace(hour=15).isoformat(),
         "attendees": ["Ana", "Ben"]},
        {"id": "b", "subject": "Later sync",
         "start": starts["b"].isoformat(),
         "end": starts["b"].replace(hour=17).isoformat(),
         "attendees": 3},
        {"id": "c", "subject": "Tomorrow",
         "start": starts["c"].isoformat(),
         "end": starts["c"].replace(hour=12).isoformat(),
         "location": "Room 4"},
        {"id": "d", "subject": "Next week",
         "start": starts["d"].isoformat(),
         "end": starts["d"].replace(hour=10).isoformat()},
        {"id": "e", "subject": "Far off",
         "start": starts["e"].isoformat(),
         "end": starts["e"].replace(hour=10).isoformat()},
    ]
    runner = PluginWidgetRunner(workspace, calendar=_bridge(tmp_path, now, events))
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [
        {"type": "sparkline", "pointsBinding": "weekPoints"},
        {"type": "checklist", "itemsBinding": "items"},
        {"type": "timeline", "itemsBinding": "upcoming"},
        {"type": "metric", "binding": "weekHours", "label": "Hours"},
    ])
    runner.attach("p1", _pipeline_manifest("calendar-read"),
                  version_dir, tmp_path / "data")

    _result_, bindings = runner._read_pair("p1")
    assert bindings["weekPoints"] == [2, 1, 0, 1] + [0] * 10
    assert bindings["weekHours"] == 5.0  # 1h + 1h + 2h + 1h, next 7 days
    assert bindings["upcoming"] == [
        {"time": starts["a"].isoformat(), "title": "Q4 pipeline review",
         "meta": "2 attendees"},
        {"time": starts["b"].isoformat(), "title": "Later sync",
         "meta": "3 attendees"},
        {"time": starts["c"].isoformat(), "title": "Tomorrow",
         "meta": "Room 4"},
        {"time": starts["d"].isoformat(), "title": "Next week", "meta": ""},
    ]
    assert bindings["todayRows"] == [
        {"primary": "Q4 pipeline review", "secondary": "14:00", "meta": ""},
        {"primary": "Later sync", "secondary": "16:00", "meta": ""},
    ]
    assert bindings["rows"] == bindings["todayRows"]
    assert bindings["items"] == [
        {"text": "Confirm with Ana", "done": False,
         "due": starts["a"].isoformat()},
        {"text": "Confirm with Ben", "done": False,
         "due": starts["a"].isoformat()},
    ]

    elements = runner.payload("p1")["elements"]
    assert elements[0] == {"kind": "sparkline", "points": bindings["weekPoints"],
                           "min": 0, "max": 2}
    assert elements[1] == {"kind": "checklist", "items": bindings["items"]}
    assert [item["title"] for item in elements[2]["items"]] == [
        "Q4 pipeline review", "Later sync", "Tomorrow", "Next week"]
    assert elements[3] == {"kind": "metric", "label": "Hours", "value": "5.0"}


def test_mail_vips_filter_sender_rows_when_declared(workspace, tmp_path):
    """A declared vips list narrows the sender rows; with none declared
    the list is honestly empty rather than every sender relabelled VIP."""
    now = datetime(2026, 11, 13, 12, 0, 0).astimezone().timestamp()
    files = {
        "m1.eml": _eml("<1@x>", "Pricing", "vip@example.com", now - 3600),
        "m2.eml": _eml("<2@x>", "Lunch", "other@example.com", now - 1800),
        "m3.eml": _eml("<3@x>", "Deck", "VIP@Example.com", now - 900),
    }
    version_dir = tmp_path / "plugin"
    _write_ui(version_dir, [{"type": "list", "rowsBinding": "vipRows"}])

    with_vips = _mail_runner(workspace, tmp_path, now, files,
                             folder=lambda: str(tmp_path / "mail"))
    with_vips.attach("p1",
                     _pipeline_manifest("mail-digest", {"vips": ["vip@"]}),
                     version_dir, tmp_path / "data")
    _result_, bindings = with_vips._read_pair("p1")
    assert [row["primary"] for row in bindings["vipRows"]] == [
        "VIP@Example.com", "vip@example.com"]

    without_vips = _mail_runner(workspace, tmp_path, now, files,
                                folder=lambda: str(tmp_path / "mail"))
    without_vips.attach("p2", _pipeline_manifest("mail-digest"), version_dir,
                        tmp_path / "data2")
    _result_, bindings = without_vips._read_pair("p2")
    assert bindings["vipRows"] == []
