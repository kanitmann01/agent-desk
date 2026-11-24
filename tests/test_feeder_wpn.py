"""The WPN collector: Outlook toast metadata, headers only.

Every test builds its own notification store with the real Windows schema
(Notification joined to NotificationHandler) under tmp_path, so no test
opens the live %LOCALAPPDATA% store. The toast XML carries a sentinel in
the third text node, the preview line; it must never reach a Message.
"""

import dataclasses
import hashlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.feeder.collectors.wpn import NO_HANDLER_CAUSE, WpnCollector
from agentdesk.feeder.contract import MailCollector
from agentdesk.feeder.runner import OutlookFeeder

SENTINEL = "BODY-PREVIEW-SENTINEL-9f3c"
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

OUTLOOK = "Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows"
OTHER = "com.example.other"

SCHEMA = """
CREATE TABLE [NotificationHandler] (
 [RecordId] INTEGER PRIMARY KEY,
 [PrimaryId] TEXT NOT NULL COLLATE NOCASE,
 [WNSId] TEXT COLLATE NOCASE,
 [HandlerType] TEXT,
 [WNFEventName] INT64,
 [SystemDataPropertySet] BLOB,
 [CreatedTime] DATETIME,
 [ModifiedTime] DATETIME,
 [ParentId] TEXT COLLATE NOCASE,
 [ContainerSid] TEXT COLLATE NOCASE
);
CREATE TABLE [Notification] (
 [Order] INTEGER NOT NULL PRIMARY KEY,
 [Id] INTEGER NOT NULL,
 [HandlerId] INTEGER CONSTRAINT[NotificationToHandler]
   REFERENCES[NotificationHandler]([RecordId]),
 [ActivityId] GUID,
 [Type] TEXT NOT NULL,
 [Payload] BLOB,
 [Tag] TEXT,
 [Group] TEXT,
 [ExpiryTime] INT64,
 [ArrivalTime] INT64,
 [DataVersion] INT64 DEFAULT '0',
 [PayloadType] TEXT NOT NULL,
 [BootId] INT64 DEFAULT '0',
 [ExpiresOnReboot] BOOLEAN DEFAULT 'FALSE',
 UNIQUE([Id]) ON CONFLICT REPLACE
);
"""


def filetime(moment: datetime) -> int:
    """A UTC datetime as a Windows FILETIME (100ns ticks since 1601)."""
    return int((moment - FILETIME_EPOCH).total_seconds() * 10_000_000)


def toast(sender: str, subject: str, preview: str) -> str:
    """The ToastGeneric shape Outlook raises: sender, subject, preview."""
    return (
        '<toast launch="mail:item-1"><visual>'
        '<binding template="ToastGeneric">'
        f"<text>{sender}</text><text>{subject}</text><text>{preview}</text>"
        "</binding></visual></toast>"
    )


def make_store(path: Path, rows: list[tuple]) -> Path:
    """Create the real two-table store and insert (handler, id, type, xml, at)."""
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        handlers = {}
        for name in (OUTLOOK, OTHER):
            cur = con.execute(
                "INSERT INTO NotificationHandler (PrimaryId, HandlerType) VALUES (?, ?)",
                (name, "app:immersive"),
            )
            handlers[name] = cur.lastrowid
        for order, (handler_name, notification_id, kind, payload, arrived) in enumerate(rows):
            con.execute(
                'INSERT INTO Notification ("Order", Id, HandlerId, Type, Payload, '
                'PayloadType, ArrivalTime) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (
                    order,
                    notification_id,
                    handlers[handler_name],
                    kind,
                    payload,
                    "Xml",
                    filetime(arrived),
                ),
            )
        con.commit()
    finally:
        con.close()
    return path


@pytest.fixture
def store(tmp_path):
    """One Outlook mail toast, its duplicate, a reminder, and decoys.

    The duplicate has its own notification Id but the same text, so both
    are real rows and the writer still lands them in stable files.
    """
    mail = toast("Example Sender", "Quarterly Report Q3", SENTINEL)
    reminder = toast("Reminder: Board review", "10:00 AM, 11/25/2026", "Calendar preview")
    rows = [
        (OUTLOOK, 900001, "toast", mail, NOW - timedelta(seconds=100)),
        (OUTLOOK, 900002, "toast", reminder, NOW - timedelta(seconds=200)),
        (OTHER, 900003, "toast", toast("Other App", "Other subject", "Other preview"),
         NOW - timedelta(seconds=5)),
        (OUTLOOK, 900004, "toastCondensed", None, NOW - timedelta(seconds=4)),
        (OUTLOOK, 900005, "toast", mail, NOW - timedelta(seconds=50)),
    ]
    return make_store(tmp_path / "wpndatabase.db", rows)


def test_the_collector_satisfies_the_contract_and_names_itself(store):
    collector = WpnCollector(store_path=store)
    assert isinstance(collector, MailCollector)
    assert collector.name == "wpn"
    ok, cause = collector.available()
    assert ok is True
    assert cause == ""


def test_collect_maps_outlook_toasts_to_header_only_messages(store):
    collector = WpnCollector(store_path=store)
    messages = collector.collect(NOW - timedelta(seconds=300), limit=10)
    by_id = {m.id: m for m in messages}
    assert len(messages) == 3
    assert len(by_id) == 3
    mail = min(
        (m for m in messages if m.subject == "Quarterly Report Q3"),
        key=lambda m: m.date_ts,
    )
    assert mail.sender == "Example Sender"
    assert mail.to == ""
    assert mail.cc == ""
    assert mail.in_reply_to == ""
    assert mail.thread == ""
    assert mail.importance == ""
    assert SENTINEL not in mail.subject
    assert mail.date_ts == pytest.approx((NOW - timedelta(seconds=100)).timestamp())
    assert OUTLOOK in mail.id and "900001" in mail.id
    reminder = next(m for m in messages if m.sender == "Reminder: Board review")
    assert reminder.subject == "10:00 AM, 11/25/2026"
    assert not hasattr(mail, "body")


def test_the_preview_sentinel_never_appears_in_any_message_field(store):
    messages = WpnCollector(store_path=store).collect(NOW - timedelta(seconds=300), limit=10)
    for message in messages:
        for field in dataclasses.fields(message):
            assert SENTINEL not in str(getattr(message, field.name))
    assert SENTINEL not in repr(messages)


def test_collect_filters_to_outlook_toasts_since_the_given_moment(store):
    collector = WpnCollector(store_path=store)
    recent = collector.collect(NOW - timedelta(seconds=75), limit=10)
    assert {m.sender for m in recent} == {"Example Sender"}
    assert {m.subject for m in recent} == {"Quarterly Report Q3"}
    older = collector.collect(NOW - timedelta(seconds=300), limit=10)
    assert any(m.sender == "Reminder: Board review" for m in older)
    assert all("Other App" not in m.sender for m in older)


def test_collect_honours_the_limit_and_returns_the_newest_rows(store):
    messages = WpnCollector(store_path=store).collect(NOW - timedelta(seconds=300), limit=2)
    assert len(messages) == 2
    assert {m.id for m in messages} == {
        m.id for m in WpnCollector(store_path=store).collect(
            NOW - timedelta(seconds=300), limit=10
        ) if m.subject == "Quarterly Report Q3"
    }
    assert WpnCollector(store_path=store).collect(NOW, limit=0) == []


def test_a_second_collect_returns_the_same_rows(store):
    collector = WpnCollector(store_path=store)
    since = NOW - timedelta(seconds=300)
    first = collector.collect(since, limit=10)
    second = collector.collect(since, limit=10)
    assert second == first
    fingerprints = [
        hashlib.sha256(repr(m).encode("utf-8")).hexdigest() for m in first
    ]
    assert fingerprints == [hashlib.sha256(repr(m).encode("utf-8")).hexdigest() for m in second]


def test_a_store_without_an_outlook_handler_says_why(tmp_path):
    path = make_store(
        tmp_path / "wpndatabase.db",
        [(OTHER, 1, "toast", toast("Other App", "Other subject", "Other preview"), NOW)],
    )
    con = sqlite3.connect(path)
    try:
        con.execute("DELETE FROM NotificationHandler WHERE PrimaryId = ?", (OUTLOOK,))
        con.commit()
    finally:
        con.close()
    collector = WpnCollector(store_path=path)
    assert collector.available() == (False, NO_HANDLER_CAUSE)
    with pytest.raises(RuntimeError, match="Outlook notification handler"):
        collector.collect(NOW - timedelta(days=1), limit=10)


def test_a_store_with_an_outlook_handler_and_no_toasts_is_available(tmp_path):
    path = make_store(tmp_path / "wpndatabase.db", [])
    collector = WpnCollector(store_path=path)
    assert collector.available() == (True, "")
    assert collector.collect(NOW - timedelta(days=1), limit=10) == []


def test_the_runner_records_the_no_handler_cause_in_its_status(tmp_path, monkeypatch):
    path = make_store(
        tmp_path / "wpndatabase.db",
        [(OTHER, 1, "toast", toast("Other App", "Other subject", "Other preview"), NOW)],
    )
    con = sqlite3.connect(path)
    try:
        con.execute("DELETE FROM NotificationHandler WHERE PrimaryId = ?", (OUTLOOK,))
        con.commit()
    finally:
        con.close()
    monkeypatch.setattr(sys, "platform", "win32")
    feeder = OutlookFeeder(
        collectors=[WpnCollector(store_path=path)],
        folder_provider=lambda: str(tmp_path / "mail"),
        clock=lambda: NOW.timestamp(),
        status_path=tmp_path / "feeder-status.json",
        platform="win32",
    )

    status = feeder.run_once()

    assert status["lastResult"] == "unavailable"
    assert status["collector"] == "wpn"
    assert status["lastError"] == NO_HANDLER_CAUSE
    assert status["written"] == 0


def test_available_is_false_off_windows_or_without_the_store(tmp_path, monkeypatch):
    missing = WpnCollector(store_path=tmp_path / "absent.db")
    ok, cause = missing.available()
    assert ok is False
    assert "notification store" in cause
    monkeypatch.setattr(sys, "platform", "darwin")
    ok, cause = WpnCollector(store_path=tmp_path / "absent.db").available()
    assert ok is False
    assert "Windows" in cause
