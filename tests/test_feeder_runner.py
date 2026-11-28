"""The feeder runner: one pass, one lock, one honest status.

Every side effect is injected: collectors, the folder provider, the
clock and the status path. A pass picks the first collector that says it
can run, writes its headers, records the outcome atomically, and never
raises into the caller, including when the collector or the folder
fails.
"""

import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.agentloop.schedule import claim_run, release_run
from nexuusbot.feeder.contract import MANUAL_CAUSE, UnavailableCollector
from nexuusbot.feeder.runner import OutlookFeeder
from nexuusbot.mail.core import Message, parse_eml

SAMPLE_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc).timestamp()
DAY_S = 24 * 60 * 60

STATUS_KEYS = {
    "collector", "platform", "lastRunTs", "lastResult", "lastError", "written",
    "coverageFromTs", "coverageToTs",
}


def message(**overrides) -> Message:
    """One fully populated header record, with fields a test can replace."""
    fields = {
        "id": "<a-1@example.com>",
        "in_reply_to": "",
        "sender": "a@example.com",
        "to": "employee@example.com",
        "cc": "",
        "subject": "North contract",
        "date_ts": SAMPLE_NOW - DAY_S,
        "importance": "",
    }
    fields.update(overrides)
    return Message(**fields)


class FakeCollector:
    """A collector whose availability, records and failure are all scripted."""

    def __init__(
        self,
        name: str = "fake",
        messages=(),
        available: bool = True,
        cause: str = "",
        failure: Exception | None = None,
        availability_failure: Exception | None = None,
    ) -> None:
        """Hold the scripted answers and the messages to hand back."""
        self.name = name
        self.messages = list(messages)
        self._available = available
        self._cause = cause
        self.failure = failure
        self.availability_failure = availability_failure
        self.calls: list[tuple] = []

    def available(self) -> tuple[bool, str]:
        """Report the scripted availability, or raise the scripted error."""
        if self.availability_failure is not None:
            raise self.availability_failure
        return self._available, self._cause

    def collect(self, since: datetime, limit: int) -> list[Message]:
        """Record the call and hand back the messages, or raise."""
        self.calls.append((since, limit))
        if self.failure is not None:
            raise self.failure
        return list(self.messages)


def make_feeder(tmp_path, collectors, *, folder=None, now=SAMPLE_NOW, **kwargs):
    """One feeder over fresh status and lock paths, with a frozen clock."""
    target = folder if folder is not None else tmp_path / "mail"
    feeder = OutlookFeeder(
        collectors=collectors,
        folder_provider=lambda: str(target),
        clock=lambda: now,
        status_path=tmp_path / "feeder-status.json",
        platform="test-os",
        **kwargs,
    )
    return feeder, target, tmp_path / "feeder-status.json"


def status_file(path: Path) -> dict:
    """The persisted status document."""
    return json.loads(path.read_text(encoding="utf-8"))


# -- selection and the happy path -----------------------------------------


def test_run_once_picks_the_first_available_collector_and_records_it(tmp_path):
    first = FakeCollector(name="first", available=False, cause="the index is off")
    second = FakeCollector(
        name="second",
        messages=[message(id="<b-1@example.com>"), message(id="<b-2@example.com>", subject="Re: North")],
    )
    third = FakeCollector(name="third", messages=[message(id="<c-1@example.com>")])
    feeder, folder, status_path = make_feeder(
        tmp_path, [first, second, third], window_days=7, limit=3,
    )

    status = feeder.run_once()

    assert status["collector"] == "second"
    assert status["platform"] == "test-os"
    assert status["lastRunTs"] == SAMPLE_NOW
    assert status["lastResult"] == "ok"
    assert status["lastError"] == ""
    assert status["written"] == 2
    assert set(status) == STATUS_KEYS
    assert first.calls == []
    assert third.calls == []
    (since, limit), = second.calls
    assert since == datetime.fromtimestamp(SAMPLE_NOW - 7 * DAY_S, tz=timezone.utc)
    assert limit == 3
    assert sorted(p.suffix for p in folder.iterdir()) == [".eml", ".eml"]
    assert status_file(status_path) == status


def test_run_once_reports_the_coverage_window_of_the_collected_messages(tmp_path):
    collector = FakeCollector(messages=[
        message(id="<a-1@example.com>", date_ts=SAMPLE_NOW - 3 * DAY_S),
        message(id="<b-1@example.com>", date_ts=SAMPLE_NOW - DAY_S),
        message(id="<c-1@example.com>", date_ts=SAMPLE_NOW - 2 * DAY_S),
    ])
    feeder, _, status_path = make_feeder(tmp_path, [collector])

    status = feeder.run_once()

    assert status["coverageFromTs"] == SAMPLE_NOW - 3 * DAY_S
    assert status["coverageToTs"] == SAMPLE_NOW - DAY_S
    assert status_file(status_path) == status


def test_an_undated_record_does_not_widen_the_coverage_window(tmp_path):
    collector = FakeCollector(messages=[message(id="<a-1@example.com>", date_ts=0.0)])
    feeder, _, _ = make_feeder(tmp_path, [collector])

    status = feeder.run_once()

    assert status["written"] == 1  # the file is still written
    assert status["coverageFromTs"] is None  # but no window is claimed
    assert status["coverageToTs"] is None


def test_run_once_is_idempotent_across_reruns(tmp_path):
    collector = FakeCollector(messages=[message(id="<a-1@example.com>")])
    feeder, folder, _ = make_feeder(tmp_path, [collector])

    first = feeder.run_once()
    first_files = {p.name: p.read_bytes() for p in folder.iterdir()}
    second = feeder.run_once()

    assert first["written"] == second["written"] == 1
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == first_files


def test_no_body_token_reaches_the_folder(tmp_path):
    source = (
        "From: a@example.com\r\n"
        "Subject: Quarterly plan\r\n"
        "Date: Wed, 11 Nov 2026 10:00:00 GMT\r\n"
        "Message-ID: <q-1@example.com>\r\n"
        "\r\n"
        "SECRET-BODY-TOKEN\r\n"
    )
    feeder, folder, _ = make_feeder(tmp_path, [FakeCollector(messages=[parse_eml(source)])])
    feeder.run_once()
    for path in folder.iterdir():
        assert b"SECRET-BODY-TOKEN" not in path.read_bytes()


# -- the honest not-run outcomes ------------------------------------------


def test_run_once_reports_the_platform_collector_cause_when_nothing_can_run(tmp_path):
    unavailable = FakeCollector(
        name="mac-notifications",
        available=False,
        cause="Give Agent Desk Full Disk Access.",
    )
    feeder, folder, status_path = make_feeder(tmp_path, [unavailable])

    status = feeder.run_once()

    assert status["lastResult"] == "unavailable"
    assert status["collector"] == "mac-notifications"
    assert status["lastError"] == "Give Agent Desk Full Disk Access."
    assert status["written"] == 0
    assert unavailable.calls == []
    assert not folder.exists()  # nothing was collected, so nothing was written
    assert status_file(status_path) == status


def test_run_once_names_the_platform_cause_ahead_of_a_manual_fallback(tmp_path):
    unavailable = FakeCollector(
        name="wpn", available=False,
        cause="No Outlook notification handler is registered.",
    )
    feeder, _, status_path = make_feeder(
        tmp_path, [unavailable, UnavailableCollector()],
    )

    status = feeder.run_once()

    assert status["lastResult"] == "unavailable"
    assert status["collector"] == "wpn"
    assert status["lastError"] == "No Outlook notification handler is registered."
    assert status_file(status_path) == status


def test_run_once_with_only_the_manual_fallback_records_its_own_cause(tmp_path):
    feeder, _, status_path = make_feeder(tmp_path, [UnavailableCollector()])

    status = feeder.run_once()

    assert status["lastResult"] == "unavailable"
    assert status["collector"] == "manual"
    assert status["lastError"] == MANUAL_CAUSE
    assert "Save as" in status["lastError"]
    assert status_file(status_path) == status


def test_run_once_without_a_folder_reports_an_honest_error(tmp_path):
    collector = FakeCollector()
    feeder, _, status_path = make_feeder(tmp_path, [collector], folder="")

    status = feeder.run_once()

    assert status["lastResult"] == "error"
    assert "folder" in status["lastError"].lower()
    assert status["written"] == 0
    assert collector.calls == []
    assert status_file(status_path) == status


def test_a_collector_failure_leaves_the_folder_untouched_and_reports_error(tmp_path):
    folder = tmp_path / "mail"
    folder.mkdir()
    existing = folder / "save-as-copy.eml"
    existing.write_bytes(b"From: a@example.com\r\n\r\n")
    broken = FakeCollector(name="broken", failure=RuntimeError("the index is offline"))
    feeder, _, status_path = make_feeder(tmp_path, [broken])

    status = feeder.run_once()

    assert status["lastResult"] == "error"
    assert status["collector"] == "broken"
    assert "the index is offline" in status["lastError"]
    assert status["written"] == 0
    assert sorted(p.name for p in folder.iterdir()) == [existing.name]
    assert status_file(status_path) == status


def test_a_collector_that_raises_while_reporting_availability_is_skipped(tmp_path):
    broken = FakeCollector(name="broken", availability_failure=RuntimeError("no probe"))
    good = FakeCollector(name="good", messages=[message()])
    feeder, folder, _ = make_feeder(tmp_path, [broken, good])

    status = feeder.run_once()

    assert status["lastResult"] == "ok"
    assert status["collector"] == "good"
    assert broken.calls == []
    assert len(list(folder.iterdir())) == 1


def test_a_writer_failure_is_reported_not_raised(tmp_path):
    not_a_folder = tmp_path / "mail-is-a-file"
    not_a_folder.write_text("not a folder", encoding="utf-8")
    collector = FakeCollector(messages=[message()])
    feeder = OutlookFeeder(
        collectors=[collector],
        folder_provider=lambda: str(not_a_folder),
        clock=lambda: SAMPLE_NOW,
        status_path=tmp_path / "feeder-status.json",
        platform="test-os",
    )

    status = feeder.run_once()

    assert status["lastResult"] == "error"
    assert status["written"] == 0
    assert status["lastError"]
    assert collector.calls  # the collector ran; the failure is the write
    assert status_file(tmp_path / "feeder-status.json") == status


# -- the lock -------------------------------------------------------------


def test_the_lock_prevents_overlapping_runs(tmp_path):
    collector = FakeCollector(messages=[message()])
    feeder, _, status_path = make_feeder(tmp_path, [collector])
    lock_path = feeder.lock_path
    assert claim_run(lock_path, now=SAMPLE_NOW) is True

    busy = feeder.run_once()

    assert set(busy) == STATUS_KEYS
    assert busy["lastResult"] == "busy"
    assert busy["lastRunTs"] is None
    assert busy["written"] == 0
    assert busy["coverageFromTs"] is None
    assert "in progress" in busy["lastError"]
    assert collector.calls == []
    assert not status_path.exists()  # a skipped pass must not clobber the run
    assert lock_path.exists()

    release_run(lock_path, start_ts=SAMPLE_NOW)
    status = feeder.run_once()
    assert status["lastResult"] == "ok"
    assert status_file(status_path) == status


def test_run_once_releases_the_lock_after_success_and_after_a_failure(tmp_path):
    broken = FakeCollector(name="broken", failure=RuntimeError("the index is offline"))
    feeder, _, _ = make_feeder(tmp_path, [broken])

    feeder.run_once()
    assert not feeder.lock_path.exists()

    good = FakeCollector(name="good", messages=[message()])
    feeder.collectors = [good]
    feeder.run_once()
    assert not feeder.lock_path.exists()


# -- the privacy seam -----------------------------------------------------


FEEDER_SRC = ROOT / "src" / "nexuusbot" / "feeder"
FORBIDDEN_ROOTS = {
    "ctypes", "http", "requests", "socket", "subprocess",
    "urllib", "win32api", "win32com", "winreg", "nexuusbot.llm",
}


def imported_roots(path: Path) -> set[str]:
    """The top-level modules one source file imports, relative imports aside."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_feeder_module_imports_a_network_platform_or_model_client():
    for path in sorted(FEEDER_SRC.glob("*.py")):
        assert not imported_roots(path) & FORBIDDEN_ROOTS, path.name
