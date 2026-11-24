"""The macOS Notification Center reader: local Outlook alerts, headers only.

macOS persists delivered notifications in a per-user SQLite database
under the usernoted group container. The reader never opens the live
file: it copies db, db-wal and db-shm together into a temp directory
and opens that copy read-only, so Outlook or Notification Center can
keep writing while a pass runs.

A record's data is a binary property list whose layout belongs to the
posting app. This reader keeps the title and subtitle only, drops the
body and every other key, and never reads a body value, not even as a
fallback. The plist dies here: only the agentdesk.mail.core.Message
records leave this module, and that record has no body field.

Reading the store needs Full Disk Access, a per-app user consent. The
unavailable causes say so in plain words rather than reporting zero.
"""

import plistlib
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from agentdesk.mail.core import Message

NAME = "mac-notifications"

DEFAULT_DB_PATH = (
    Path.home()
    / "Library/Group Containers/group.com.apple.usernoted/db2/db"
)

# The bundle ids Outlook for Mac has used; anything else is another app.
OUTLOOK_BUNDLE_IDS = (
    "com.microsoft.Outlook",
    "com.microsoft.OutlookForMac",
)

APPLE_EPOCH_OFFSET_S = 978307200  # 2001-01-01 in unix seconds
FIELD_CAP = 500  # an alert line is short; a malformed plist value is not

TITLE_KEYS = frozenset({"title", "titl", "sender"})
SUBTITLE_KEYS = frozenset({"subtitle", "subt", "sub", "subject"})
BODY_KEYS = frozenset({"body", "preview"})

PLATFORM_CAUSE = (
    "The macOS Notification Center reader only runs on macOS."
    " Save messages into the .eml folder instead."
)
MISSING_CAUSE = (
    "The macOS Notification Center database is not on this Mac, so"
    " there are no Outlook alerts to read. Save messages into the"
    " .eml folder instead."
)
FULL_DISK_ACCESS_CAUSE = (
    "macOS is blocking access to the Notification Center database."
    " Give Agent Desk Full Disk Access in System Settings > Privacy &"
    " Security > Full Disk Access, or save messages into the .eml"
    " folder instead."
)
UNREADABLE_CAUSE = (
    "The macOS Notification Center database could not be read. Save"
    " messages into the .eml folder instead."
)
NO_OUTLOOK_CAUSE = (
    "No Outlook notifications are in the macOS Notification Center"
    " store yet. Save messages into the .eml folder instead."
)

_NEWLINES = re.compile(r"[\r\n]+")
_BODY_IN_KEY = ("body", "preview")


class MacNotificationCollector:
    """One read-only view of the Notification Center store's Outlook alerts."""

    name = NAME

    def __init__(self, db_path=None, *, platform: str | None = None) -> None:
        """Point the reader at one store; platform is injectable for parsers."""
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.platform = sys.platform if platform is None else platform

    def available(self) -> tuple[bool, str]:
        """Whether this host can read Outlook alerts, and the cause when not."""
        if self.platform != "darwin":
            return False, PLATFORM_CAUSE
        if not self.db_path.exists():
            return False, MISSING_CAUSE
        try:
            rows = self._select(limit=1)
        except PermissionError:
            return False, FULL_DISK_ACCESS_CAUSE
        except (OSError, sqlite3.Error):
            return False, UNREADABLE_CAUSE
        if not rows:
            return False, NO_OUTLOOK_CAUSE
        return True, ""

    def collect(self, since: datetime, limit: int) -> list[Message]:
        """Outlook alerts delivered since the moment, oldest first, up to limit."""
        if limit < 1:
            return []
        cutoff = since.timestamp() - APPLE_EPOCH_OFFSET_S
        messages = []
        seen = set()
        for _rec_id, uuid, identifier, data, delivered in self._select(
            cutoff=cutoff, limit=limit
        ):
            lines = _lines(data)
            if not lines:
                continue
            sender, subject = (
                (lines[0], lines[1]) if len(lines) > 1 else ("", lines[0])
            )
            message = Message(
                id=f"<mac-notifications-{uuid}@{identifier}>",
                in_reply_to="",
                sender=sender,
                to="",
                cc="",
                subject=subject,
                date_ts=float(delivered) + APPLE_EPOCH_OFFSET_S,
                thread="",
                importance="",
            )
            if message.id not in seen:
                seen.add(message.id)
                messages.append(message)
        return messages

    def _select(self, *, cutoff: float | None = None, limit: int) -> list[tuple]:
        """Outlook rows from a read-only copy of the store, oldest first."""
        with tempfile.TemporaryDirectory(prefix="agentdesk-mac-alerts-") as tmp:
            copy = Path(tmp) / "db"
            self._copy_store(copy)
            sql = (
                "SELECT r.rec_id, r.uuid, a.identifier, r.data, r.delivered_date"
                " FROM record AS r JOIN app AS a ON a.app_id = r.app_id"
                f" WHERE a.identifier IN ({','.join('?' * len(OUTLOOK_BUNDLE_IDS))})"
            )
            params: list = list(OUTLOOK_BUNDLE_IDS)
            if cutoff is not None:
                sql += " AND r.delivered_date >= ?"
                params.append(cutoff)
            sql += " ORDER BY r.delivered_date ASC, r.rec_id ASC LIMIT ?"
            params.append(limit)
            conn = sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True)
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()

    def _copy_store(self, target: Path) -> None:
        """Copy db and its WAL sidecars together, so the copy is consistent."""
        for suffix in ("", "-wal", "-shm"):
            source = Path(f"{self.db_path}{suffix}")
            if source.exists():
                shutil.copy2(source, f"{target}{suffix}")


def _one_line(value: str) -> str:
    """One alert line: CR/LF flattened, outer space trimmed, capped."""
    return _NEWLINES.sub(" ", value).strip()[:FIELD_CAP]


def _walk(value, pairs: list[tuple[str, object]]) -> None:
    """Every key and value in a plist, depth first, keys lowercased."""
    if isinstance(value, dict):
        for key, nested in value.items():
            pairs.append((str(key).strip().lower(), nested))
            _walk(nested, pairs)
    elif isinstance(value, list):
        for item in value:
            _walk(item, pairs)


def _is_body(key: str) -> bool:
    """A body or preview key is never a source for a header line."""
    return key in BODY_KEYS or any(part in key for part in _BODY_IN_KEY)


def _lines(data) -> list[str]:
    """The title and subtitle lines from one record's binary plist.

    Keys are matched case-insensitively across the whole plist because
    Notification Center nests them (req.titl is the common shape). When
    neither key is present, the first two non-empty string values stand
    in. Body and preview values are excluded before any fallback, so
    they cannot leak through the back door. An unreadable plist has no
    lines: the record is skipped rather than guessed at.
    """
    try:
        plist = plistlib.loads(data)
    except Exception:  # noqa: BLE001 - one malformed record must not kill a pass
        return []
    pairs: list[tuple[str, object]] = []
    _walk(plist, pairs)
    values = [
        _one_line(value)
        for key, value in pairs
        if isinstance(value, str) and not _is_body(key)
    ]
    values = [value for value in values if value]
    title = _by_key(pairs, TITLE_KEYS)
    subtitle = _by_key(pairs, SUBTITLE_KEYS)
    rest = [value for value in values if value not in (title, subtitle)]
    if not title and rest:
        title = rest.pop(0)
    if not subtitle and rest:
        subtitle = rest.pop(0)
    return [line for line in (title, subtitle) if line]


def _by_key(pairs: list[tuple[str, object]], keys: frozenset[str]) -> str:
    """The first non-empty string under one of the given key spellings."""
    for key, value in pairs:
        if key in keys and isinstance(value, str):
            line = _one_line(value)
            if line:
                return line
    return ""
