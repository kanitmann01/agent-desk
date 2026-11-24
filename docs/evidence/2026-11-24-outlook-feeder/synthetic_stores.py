"""Run both alert readers over synthetic stores and print what they produce.

The builders come from the focused tests, so this evidence exercises the
same schema and fixtures the test suite pins. Everything printed here is
invented data: invented senders, invented subjects and sentinel preview
or body tokens. No live store, mailbox or notification is read.

Usage (from the repository root):
    python docs/evidence/2026-11-24-outlook-feeder/synthetic_stores.py
"""

import dataclasses
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from agentdesk.feeder.collectors.mac_notifications import MacNotificationCollector
from agentdesk.feeder.collectors.wpn import WpnCollector
from agentdesk.feeder.writer import write_mail

import test_feeder_macos as mac_fixture
import test_feeder_wpn as wpn_fixture


def print_messages(title, messages):
    print(f"{title}: {len(messages)} messages")
    for message in messages:
        print(
            f"  id={message.id}"
            f" | sender={message.sender!r}"
            f" | subject={message.subject!r}"
            f" | date_ts={message.date_ts:.0f}"
        )


def wpn_run():
    print("== Windows WPN synthetic store ==")
    sentinel = wpn_fixture.SENTINEL
    now = wpn_fixture.NOW
    mail = wpn_fixture.toast("Example Sender", "Quarterly Report Q3", sentinel)
    reminder = wpn_fixture.toast(
        "Reminder: Board review", "10:00 AM, 11/25/2026", "Calendar preview")
    rows = [
        (wpn_fixture.OUTLOOK, 900001, "toast", mail, now - timedelta(seconds=100)),
        (wpn_fixture.OUTLOOK, 900002, "toast", reminder, now - timedelta(seconds=200)),
        (wpn_fixture.OUTLOOK, 900005, "toast", mail, now - timedelta(seconds=50)),
        (wpn_fixture.OTHER, 900003, "toast",
         wpn_fixture.toast("Other App", "Other subject", "Other preview"),
         now - timedelta(seconds=5)),
        (wpn_fixture.OUTLOOK, 900004, "toastCondensed", None,
         now - timedelta(seconds=4)),
    ]
    with tempfile.TemporaryDirectory(prefix="agentdesk-wpn-evidence-") as temp:
        root = Path(temp)
        store = wpn_fixture.make_store(root / "wpndatabase.db", rows)
        collector = WpnCollector(store_path=store)
        print(f"store rows inserted: {len(rows)} (2 Outlook mail, 1 duplicate,"
              " 1 Outlook reminder, 1 other app, 1 condensed)")
        print(f"available: {collector.available()}")
        first = collector.collect(now - timedelta(seconds=300), limit=10)
        print_messages("first pass", first)
        folder = root / "mail"
        written = write_mail(first, folder, now=now.timestamp(), window_days=14)
        files = sorted(folder.glob("*.eml"))
        print(f"write_mail wrote: {written} files; files on disk: {len(files)}")
        for path in files:
            print(f"  {path.name} ({path.stat().st_size} bytes)")
        blob = b"".join(path.read_bytes() for path in files)
        print(f"preview sentinel present in any file: {sentinel.encode() in blob}")
        in_fields = any(
            sentinel in str(getattr(message, field.name))
            for message in first
            for field in dataclasses.fields(message)
        )
        print(f"sentinel present in any message field: {in_fields}")
        second = collector.collect(now - timedelta(seconds=300), limit=10)
        write_mail(second, folder, now=now.timestamp(), window_days=14)
        print(f"second pass messages: {len(second)}; files after rerun:"
              f" {len(sorted(folder.glob('*.eml')))}")
        print("first .eml headers (synthetic):")
        for line in files[0].read_text(encoding="utf-8").splitlines():
            print(f"  {line}")
    print()


def mac_run():
    print("== macOS Notification Center synthetic store ==")
    with tempfile.TemporaryDirectory(prefix="agentdesk-mac-evidence-") as temp:
        root = Path(temp)
        db = mac_fixture.three_records(root)
        collector = mac_fixture.collector(db)
        print("store records inserted: 3 (Outlook mail with body, Outlook"
              " reminder, non-Outlook chat)")
        print(f"available: {collector.available()}")
        first = collector.collect(mac_fixture.since(mac_fixture.T1), 10)
        print_messages("first pass", first)
        folder = root / "mail"
        written = write_mail(
            first, folder, now=mac_fixture.T3, window_days=14)
        files = sorted(folder.glob("*.eml"))
        print(f"write_mail wrote: {written} files; files on disk: {len(files)}")
        for path in files:
            print(f"  {path.name} ({path.stat().st_size} bytes)")
        blob = b"".join(path.read_bytes() for path in files)
        for name in ("BODY_SENTINEL", "REMINDER_SENTINEL", "CHAT_SENTINEL"):
            token = getattr(mac_fixture, name)
            print(f"{name} present in any file: {token.encode() in blob}")
        second = collector.collect(mac_fixture.since(mac_fixture.T1), 10)
        write_mail(second, folder, now=mac_fixture.T3, window_days=14)
        print(f"second pass messages: {len(second)}; files after rerun:"
              f" {len(sorted(folder.glob('*.eml')))}")
    print()


if __name__ == "__main__":
    wpn_run()
    mac_run()
