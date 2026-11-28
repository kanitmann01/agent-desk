"""The macOS Notification Center reader: one synthetic usernoted store.

The live store needs Full Disk Access and holds the user's own alerts,
so every test here builds a small SQLite database with the two tables
the reader joins and binary plists for the payloads. The body sentinel
proves the reader keeps only the title and subtitle. The permission and
no-Outlook causes are exercised on the available() seam; only the
live-path check is skipped off macOS.
"""

import dataclasses
import os
import plistlib
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.feeder.collectors.mac_notifications import (
    NO_OUTLOOK_CAUSE,
    MacNotificationCollector,
)
from nexuusbot.feeder.writer import write_mail

APPLE_EPOCH_OFFSET_S = 978307200
OUTLOOK = "com.microsoft.Outlook"
CHAT = "com.apple.MobileSMS"

T1 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc).timestamp()
T2 = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc).timestamp()
T3 = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc).timestamp()

BODY_SENTINEL = "SENTINEL-BODY-DO-NOT-STORE"
REMINDER_SENTINEL = "SENTINEL-REMINDER-BODY"
CHAT_SENTINEL = "SENTINEL-CHAT-BODY"


def apple(dt: float) -> float:
    """Unix seconds as the Notification Center's 2001-01-01 seconds."""
    return dt - APPLE_EPOCH_OFFSET_S


def payload(**fields) -> bytes:
    """One record.data binary property list."""
    return plistlib.dumps(fields, fmt=plistlib.FMT_BINARY)


def build_store(
    folder: Path,
    apps: list[tuple[int, str]],
    records: list[tuple[int, int, str, bytes, float]],
) -> Path:
    """A synthetic db2/db with the two tables the reader joins.

    apps is (app_id, identifier); records is
    (rec_id, app_id, uuid, data, delivered_date) with an Apple-epoch
    delivered_date. The database is closed before the reader sees it,
    which is the same state as a snapshot.
    """
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE app (app_id INTEGER PRIMARY KEY, identifier TEXT)")
        conn.execute(
            "CREATE TABLE record ("
            "rec_id INTEGER PRIMARY KEY, app_id INTEGER, uuid TEXT,"
            " data BLOB, delivered_date REAL)"
        )
        conn.executemany("INSERT INTO app (app_id, identifier) VALUES (?, ?)", apps)
        conn.executemany(
            "INSERT INTO record (rec_id, app_id, uuid, data, delivered_date)"
            " VALUES (?, ?, ?, ?, ?)",
            records,
        )
        conn.commit()
    finally:
        conn.close()
    return db


def three_records(folder: Path) -> Path:
    """Outlook mail with a body, Outlook reminder, and a non-Outlook chat."""
    return build_store(
        folder,
        apps=[(1, OUTLOOK), (2, CHAT)],
        records=[
            (1, 1, "mail-uuid", payload(
                title="Priya Sharma <priya@example.com>",
                subtitle="Q4 budget",
                body=BODY_SENTINEL,
            ), apple(T1)),
            (2, 1, "reminder-uuid", payload(
                titl="Standup reminder",
                subt="In 10 minutes",
                body=REMINDER_SENTINEL,
            ), apple(T2)),
            (3, 2, "chat-uuid", payload(
                title="Sam", subtitle="Lunch?", body=CHAT_SENTINEL,
            ), apple(T3)),
        ],
    )


def collector(db: Path) -> MacNotificationCollector:
    """A reader over a synthetic store, forced onto the macOS branch."""
    return MacNotificationCollector(db, platform="darwin")


def since(ts: float) -> datetime:
    """An aware datetime one second before the given unix timestamp."""
    return datetime.fromtimestamp(ts - 1, tz=timezone.utc)


# -- mapping --------------------------------------------------------------


def test_outlook_records_map_to_sender_and_subject(tmp_path):
    messages = collector(three_records(tmp_path)).collect(since(T1), 10)

    assert len(messages) == 2  # the non-Outlook chat is filtered out
    mail, reminder = messages
    assert mail.sender == "Priya Sharma <priya@example.com>"
    assert mail.subject == "Q4 budget"
    assert mail.date_ts == T1
    assert mail.in_reply_to == ""
    assert mail.to == ""
    assert mail.cc == ""
    assert mail.thread == ""
    assert mail.importance == ""
    assert OUTLOOK in mail.id and "mail-uuid" in mail.id

    assert reminder.sender == "Standup reminder"
    assert reminder.subject == "In 10 minutes"
    assert reminder.date_ts == T2
    assert "reminder-uuid" in reminder.id


def test_body_sentinel_never_reaches_a_message_or_a_file(tmp_path):
    db = three_records(tmp_path)
    messages = collector(db).collect(since(T1), 10)
    folder = tmp_path / "mail"
    write_mail(messages, folder, now=T3, window_days=14)

    written = b"".join(path.read_bytes() for path in folder.glob("*.eml"))
    for sentinel in (BODY_SENTINEL, REMINDER_SENTINEL, CHAT_SENTINEL):
        assert sentinel.encode() not in written
        for message in messages:
            for field in dataclasses.fields(message):
                assert sentinel not in str(getattr(message, field.name))


def test_since_filters_older_records(tmp_path):
    messages = collector(three_records(tmp_path)).collect(since(T2), 10)
    assert [message.date_ts for message in messages] == [T2]


def test_limit_keeps_the_oldest_records_first(tmp_path):
    messages = collector(three_records(tmp_path)).collect(since(T1), 1)
    assert [message.date_ts for message in messages] == [T1]


def test_second_pass_returns_the_same_stable_ids(tmp_path):
    reader = collector(three_records(tmp_path))
    first = reader.collect(since(T1), 10)
    second = reader.collect(since(T1), 10)
    assert [message.id for message in first] == [message.id for message in second]
    assert len({message.id for message in first}) == len(first)


# -- payload parsing ------------------------------------------------------


def test_nested_short_keys_are_read_case_insensitively(tmp_path):
    db = build_store(
        tmp_path,
        apps=[(1, OUTLOOK)],
        records=[(1, 1, "nested", payload(
            req={"TiTl": "Alice", "SuBt": "Budget", "body": BODY_SENTINEL},
        ), apple(T1))],
    )
    [message] = collector(db).collect(since(T1), 10)
    assert (message.sender, message.subject) == ("Alice", "Budget")


def test_unrecognized_keys_are_skipped_without_reading_the_value(tmp_path):
    db = build_store(
        tmp_path,
        apps=[(1, OUTLOOK)],
        records=[(1, 1, "body-only", payload(message=BODY_SENTINEL), apple(T1))],
    )
    messages = collector(db).collect(since(T1), 10)
    assert messages == []
    assert BODY_SENTINEL not in repr(messages)


def test_one_line_is_the_subject_and_sender_stays_empty(tmp_path):
    db = build_store(
        tmp_path,
        apps=[(1, OUTLOOK)],
        records=[(1, 1, "solo", payload(title="Only line", body=BODY_SENTINEL),
                  apple(T1))],
    )
    [message] = collector(db).collect(since(T1), 10)
    assert message.subject == "Only line"
    assert message.sender == ""


def test_carriage_returns_are_flattened(tmp_path):
    db = build_store(
        tmp_path,
        apps=[(1, OUTLOOK)],
        records=[(1, 1, "lines", payload(title="Priya\r\nSharma", subtitle="A\nB"),
                  apple(T1))],
    )
    [message] = collector(db).collect(since(T1), 10)
    assert (message.sender, message.subject) == ("Priya Sharma", "A B")


# -- availability ---------------------------------------------------------


def test_off_macos_is_unavailable_with_the_platform_cause(tmp_path):
    reader = MacNotificationCollector(three_records(tmp_path), platform="win32")
    available, cause = reader.available()
    assert not available
    assert "macOS" in cause


def test_missing_store_is_unavailable(tmp_path):
    reader = collector(tmp_path / "missing" / "db")
    available, cause = reader.available()
    assert not available
    assert "not" in cause.lower()


def test_permission_denied_names_full_disk_access(tmp_path, monkeypatch):
    reader = collector(three_records(tmp_path))

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(shutil, "copy2", denied)
    available, cause = reader.available()
    assert not available
    assert "Full Disk Access" in cause


def test_a_denied_stat_names_full_disk_access_not_a_missing_store(tmp_path, monkeypatch):
    """exists() swallows PermissionError, so the reader stats the store:
    a denied path is present and needs Full Disk Access."""
    reader = collector(three_records(tmp_path))

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "stat", denied)
    available, cause = reader.available()
    assert not available
    assert "Full Disk Access" in cause


def test_a_denied_copy_during_collect_raises_the_full_disk_access_sentence(
        tmp_path, monkeypatch):
    reader = collector(three_records(tmp_path))

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(shutil, "copy2", denied)
    with pytest.raises(RuntimeError) as caught:
        reader.collect(since(T1), 10)
    assert "Full Disk Access" in str(caught.value)


def test_a_store_with_no_outlook_app_row_is_unavailable_with_its_own_cause(tmp_path):
    db = build_store(
        tmp_path,
        apps=[(2, CHAT)],
        records=[(1, 2, "chat", payload(title="Sam", subtitle="Hi"), apple(T1))],
    )
    available, cause = collector(db).available()
    assert not available
    assert cause == NO_OUTLOOK_CAUSE
    assert "Outlook" in cause


def test_a_store_with_an_outlook_app_row_and_no_records_is_available(tmp_path):
    db = build_store(tmp_path, apps=[(1, OUTLOOK)], records=[])

    reader = collector(db)

    assert reader.available() == (True, "")
    assert reader.collect(since(T1), 10) == []


def test_outlook_records_make_the_reader_available(tmp_path):
    assert collector(three_records(tmp_path)).available() == (True, "")


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("AGENTDESK_MACOS_LIVE_STORE") != "1",
    reason="the live Notification Center store needs macOS and "
           "AGENTDESK_MACOS_LIVE_STORE=1",
)
def test_live_store_path_is_the_usernoted_database():
    reader = MacNotificationCollector()
    assert str(reader.db_path).endswith("group.com.apple.usernoted/db2/db")
    available, cause = reader.available()
    assert isinstance(available, bool)
    assert isinstance(cause, str)
