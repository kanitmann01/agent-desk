"""The Windows toast collector: Outlook alerts from the WPN store.

Windows keeps each displayed toast in a per-user SQLite database,
%LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db, in WAL
mode. Outlook raises new-mail and reminder alerts as toasts whose XML
payload carries the sender as the first text node and the subject as the
second. The third node is the message preview and is never read into a
record: this collector stops after the second text node.

The live store is never opened for writing or even queried in place. A
consistent snapshot is taken with the sqlite3 backup API; if that fails,
the database, WAL and SHM files are copied together and the copy is
opened. Only toast rows with an Outlook handler are selected.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from nexuusbot.mail.core import Message

STORE_RELATIVE = Path("Microsoft") / "Windows" / "Notifications" / "wpndatabase.db"
OUTLOOK_HANDLER_PREFIXES = (
    "microsoft.outlookforwindows",
    "microsoft.office.outlook.exe",
)
NOT_WINDOWS_CAUSE = "The Windows notification store is only available on Windows."
MISSING_STORE_CAUSE = "No Windows notification store was found on this machine."
NO_HANDLER_CAUSE = (
    "No Outlook notification handler is registered in the Windows notification"
    " store."
)
UNREADABLE_STORE_CAUSE = "The Windows notification store could not be read."

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
FILETIME_UNIX_OFFSET_S = 11_644_473_600
TICKS_PER_SECOND = 10_000_000
STORE_SUFFIXES = ("", "-wal", "-shm")


def _string(value) -> str:
    """One flattened XML text value: CR/LF and repeated space collapsed."""
    return " ".join(str(value or "").split())


def _filetime_ts(value) -> float:
    """A FILETIME as epoch seconds; 0.0 when absent or unreadable."""
    try:
        ticks = int(value)
    except (TypeError, ValueError):
        return 0.0
    if ticks <= 0:
        return 0.0
    return (ticks - FILETIME_UNIX_OFFSET_S * TICKS_PER_SECOND) / TICKS_PER_SECOND


def _to_filetime(moment: datetime) -> int:
    """An aware (or UTC-assumed) datetime as FILETIME ticks."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int((moment - FILETIME_EPOCH).total_seconds() * TICKS_PER_SECOND)


def _toast_texts(payload) -> list[str] | None:
    """The first two text nodes of one toast payload, and nothing after.

    Only a parsed toast with at least one non-empty text node yields a
    result. The sender is index 0 and the subject index 1; index 2 and
    later, which is where Outlook puts the preview, are never returned.
    """
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = str(payload)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    if root.tag.rsplit("}", 1)[-1].lower() != "toast":
        return None
    kept = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() != "text":
            continue
        kept.append(_string(element.text))
        if len(kept) == 2:
            break
    return kept if any(kept) else None


def _snapshot(store: Path, folder: Path) -> Path:
    """A readable copy of the store, never the live one.

    The backup API is the normal path: it takes a consistent copy
    including committed WAL pages. If it fails, the three live files are
    copied together and the copy is opened, which lets SQLite recover
    the copied WAL.
    """
    target = folder / "wpndatabase.db"
    try:
        source = sqlite3.connect(
            f"file:{store.as_posix()}?mode=ro", uri=True, timeout=5,
        )
        try:
            copy = sqlite3.connect(target)
            try:
                source.backup(copy)
            finally:
                copy.close()
        finally:
            source.close()
        return target
    except (sqlite3.Error, OSError):
        for suffix in STORE_SUFFIXES:
            Path(str(target) + suffix).unlink(missing_ok=True)
        for suffix in STORE_SUFFIXES:
            source = Path(str(store) + suffix)
            if source.exists():
                try:
                    shutil.copy2(source, Path(str(target) + suffix))
                except OSError:
                    pass
        if not target.is_file():
            raise RuntimeError(UNREADABLE_STORE_CAUSE)
        return target


def _outlook_handler_ids(con: sqlite3.Connection) -> list[int]:
    """Handler rows whose PrimaryId names an Outlook client."""
    where = " OR ".join("lower(PrimaryId) LIKE ?" for _ in OUTLOOK_HANDLER_PREFIXES)
    rows = con.execute(
        f"SELECT RecordId FROM NotificationHandler WHERE {where}",
        tuple(prefix + "%" for prefix in OUTLOOK_HANDLER_PREFIXES),
    ).fetchall()
    return [int(row[0]) for row in rows]


class WpnCollector:
    """Outlook toast alerts from the Windows notification store.

    The store path is injectable so tests and a non-default profile never
    touch the live file. The live store is only ever read through a
    snapshot.
    """

    name = "wpn"

    def __init__(self, store_path=None) -> None:
        """Hold the store path; None means this user's standard store."""
        self._store_path = Path(store_path) if store_path is not None else None

    def _store(self) -> Path | None:
        """The store this collector reads, or None when it cannot be named."""
        if self._store_path is not None:
            return self._store_path
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) / STORE_RELATIVE if local else None

    def available(self) -> tuple[bool, str]:
        """Windows only, when the store exists and registers an Outlook handler."""
        if sys.platform != "win32":
            return False, NOT_WINDOWS_CAUSE
        store = self._store()
        if store is None or not store.is_file():
            return False, MISSING_STORE_CAUSE
        try:
            with tempfile.TemporaryDirectory(prefix="nexuusbot-wpn-") as temp:
                snapshot = _snapshot(store, Path(temp))
                con = sqlite3.connect(snapshot, timeout=5)
                try:
                    handlers = _outlook_handler_ids(con)
                finally:
                    con.close()
        except (sqlite3.Error, OSError, RuntimeError):
            return False, UNREADABLE_STORE_CAUSE
        if not handlers:
            return False, NO_HANDLER_CAUSE
        return True, ""

    def collect(self, since: datetime, limit: int) -> list[Message]:
        """Outlook toast headers since the moment, newest first.

        A store with no Outlook handler raises with that plain cause;
        the runner records it instead of showing an invented zero. A row
        that is not toast XML, or has no usable text, is skipped.
        """
        store = self._store()
        if store is None or not store.is_file():
            raise RuntimeError(MISSING_STORE_CAUSE)
        if limit <= 0:
            return []
        since_ticks = _to_filetime(since)
        with tempfile.TemporaryDirectory(prefix="nexuusbot-wpn-") as temp:
            snapshot = _snapshot(store, Path(temp))
            con = sqlite3.connect(snapshot, timeout=5)
            try:
                handler_ids = _outlook_handler_ids(con)
                if not handler_ids:
                    raise RuntimeError(NO_HANDLER_CAUSE)
                marks = ",".join("?" for _ in handler_ids)
                rows = con.execute(
                    f"SELECT n.Id, n.ArrivalTime, h.PrimaryId, n.Payload"
                    f" FROM Notification n"
                    f" JOIN NotificationHandler h ON h.RecordId = n.HandlerId"
                    f" WHERE n.HandlerId IN ({marks})"
                    f' AND n.Type = "toast" AND n.PayloadType = "Xml"'
                    f" AND n.ArrivalTime >= ?"
                    f' ORDER BY n.ArrivalTime DESC, n.Id DESC LIMIT ?',
                    (*handler_ids, since_ticks, int(limit)),
                ).fetchall()
            finally:
                con.close()
        messages = []
        for notification_id, arrival, handler, payload in rows:
            texts = _toast_texts(payload)
            if texts is None:
                continue
            messages.append(Message(
                id=f"<wpn-{int(notification_id)}-{handler}@agent-desk.local>",
                in_reply_to="",
                sender=texts[0],
                to="",
                cc="",
                subject=texts[1] if len(texts) > 1 else "",
                date_ts=_filetime_ts(arrival),
                thread="",
                importance="",
            ))
        return messages
