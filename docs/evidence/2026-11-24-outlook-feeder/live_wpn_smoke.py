"""Live Windows WPN smoke: counts and handler ids only.

This reads the real per-user notification store through the collector's
own read-only snapshot path. It prints aggregate counts and handler
PrimaryId values, which identify the posting app. It never selects,
prints or writes any Notification payload, tag or activity text, so no
alert content from this machine can appear in the evidence.

Usage (from the repository root, on Windows):
    python docs/evidence/2026-11-24-outlook-feeder/live_wpn_smoke.py
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from agentdesk.feeder.collectors.wpn import (
    STORE_RELATIVE,
    WpnCollector,
    _snapshot,
)


def main() -> int:
    print("Windows WPN live smoke: counts and handler ids only")
    print(f"run at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"python: {sys.version.split()[0]} on {sys.platform}")
    local = os.environ.get("LOCALAPPDATA")
    store = Path(local) / STORE_RELATIVE if local else None
    print(f"store path: {store}")
    if store is None or not store.is_file():
        print("store exists: no")
        return 1
    print(f"store exists: yes ({store.stat().st_size} bytes)")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(store) + suffix)
        print(f"  sidecar {suffix}: {'yes' if sidecar.is_file() else 'no'}"
              f" ({sidecar.stat().st_size if sidecar.is_file() else 0} bytes)")

    collector = WpnCollector()
    available, cause = collector.available()
    print(f"collector.available: {available}")
    print(f"collector cause: {cause or '(none)'}")

    with tempfile.TemporaryDirectory(prefix="agentdesk-wpn-smoke-") as temp:
        snapshot = _snapshot(store, Path(temp))
        con = sqlite3.connect(snapshot, timeout=5)
        try:
            handlers = con.execute(
                "SELECT RecordId, PrimaryId, HandlerType FROM NotificationHandler"
                " ORDER BY RecordId").fetchall()
            print(f"notification handlers: {len(handlers)}")
            outlook_handlers = []
            for record_id, primary_id, handler_type in handlers:
                if str(primary_id).lower().startswith(
                        ("microsoft.outlookforwindows",
                         "microsoft.office.outlook.exe")):
                    outlook_handlers.append(record_id)
                    print(f"  outlook handler RecordId={record_id}"
                          f" PrimaryId={primary_id}"
                          f" HandlerType={handler_type}")
            print("non-Outlook handlers are counted, not named, to keep the"
                  " evidence to Outlook identifiers only")
            total = con.execute("SELECT COUNT(*) FROM Notification").fetchone()[0]
            print(f"notification rows: {total}")
            for kind, payload_type, count in con.execute(
                "SELECT Type, PayloadType, COUNT(*) FROM Notification"
                " GROUP BY Type, PayloadType ORDER BY Type, PayloadType"):
                print(f"  Type={kind} PayloadType={payload_type} count={count}")
            print(f"outlook handler RecordIds: {outlook_handlers}")
            if outlook_handlers:
                marks = ",".join("?" for _ in outlook_handlers)
                outlook_toasts = con.execute(
                    "SELECT COUNT(*) FROM Notification"
                    f" WHERE HandlerId IN ({marks})"
                    ' AND Type = "toast" AND PayloadType = "Xml"',
                    tuple(outlook_handlers)).fetchone()[0]
                non_empty = con.execute(
                    "SELECT COUNT(*) FROM Notification"
                    f" WHERE HandlerId IN ({marks})"
                    " AND Payload IS NOT NULL AND length(Payload) > 0",
                    tuple(outlook_handlers)).fetchone()[0]
                print(f"outlook toast Xml rows: {outlook_toasts}")
                print(f"outlook rows with a non-empty payload: {non_empty}")
                print("  (payload text is never selected or printed)")
            else:
                print("outlook toast Xml rows: 0 (no Outlook handler registered)")
        finally:
            con.close()

    since = datetime.now(timezone.utc) - timedelta(days=14)
    messages = collector.collect(since, limit=100)
    print(f"collector.collect(since=14 days, limit=100): {len(messages)} messages")
    print("live Outlook alert messages on this host:"
          f" {'none' if not messages else len(messages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
