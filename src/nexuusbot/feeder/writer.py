"""The one serializer: header-only .eml bytes and the files that hold them.

The mail path reads headers only, so the feeder writes headers only. A
file is a header block and a blank line, with nothing after it: no
body, no MIME envelope, no preview line. Values are stripped of CR and
LF before they become lines, so a collector cannot smuggle a second
header into a file the watcher will later read.

A message that arrives without a Message-ID gets a generated one
derived from its own headers. The derivation is deterministic, so a
rerun produces the same id and the same filename, and distinct messages
get distinct ids.
"""

import hashlib
import json
import os
import re
import secrets
from email.utils import formatdate
from pathlib import Path

from nexuusbot.mail.core import Message, parse_eml

# Feeder-owned files carry this prefix; pruning never touches a file the
# user saved with Save as, and temp files never end in .eml.
FEEDER_PREFIX = "feeder-"
GENERATED_ID_DOMAIN = "agent-desk.local"

DAY_S = 24 * 60 * 60
_FILENAME_HASH_CHARS = 16
_ID_HASH_CHARS = 32
_NEWLINES = re.compile(r"[\r\n]+")


def _clean(value: str) -> str:
    """One header value on one line: CR/LF stripped, outer space trimmed."""
    return _NEWLINES.sub(" ", value or "").strip()


def _message_id(message: Message) -> str:
    """The Message-ID this record is written under.

    A real id is kept exactly as collected, because threading reads it.
    A missing one is generated from the headers that identify the
    message, which makes it stable across reruns and distinct between
    distinct records. Two records identical in every header collide by
    design: they are the same message and one file is enough.
    """
    real = _clean(message.id)
    if real:
        return real
    seed = "\x1f".join(
        _clean(part)
        for part in (
            message.sender,
            message.to,
            message.cc,
            message.subject,
            repr(message.date_ts),
            message.in_reply_to,
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:_ID_HASH_CHARS]
    return f"<feeder-{digest}@{GENERATED_ID_DOMAIN}>"


def render_eml(message: Message) -> bytes:
    """One Message as RFC 822 header block bytes, and no body.

    Headers appear in a fixed order: From, To, Cc, Subject, Date,
    Message-ID, In-Reply-To, Importance. A field the record does not
    carry is left out rather than invented, which is what an index with
    partial metadata looks like; Message-ID is the exception, generated
    when absent because every file needs a unique one. Date is RFC 2822
    in GMT. Lines end CRLF and the block ends with the blank line.
    """
    fields = (
        ("From", message.sender),
        ("To", message.to),
        ("Cc", message.cc),
        ("Subject", message.subject),
        ("Date", formatdate(message.date_ts, usegmt=True) if message.date_ts else ""),
        ("Message-ID", _message_id(message)),
        ("In-Reply-To", message.in_reply_to),
        ("Importance", message.importance),
    )
    header_lines = [
        f"{name}: {cleaned}"
        for name, value in fields
        if (cleaned := _clean(value))
    ]
    return ("\r\n".join(header_lines) + "\r\n\r\n").encode("utf-8")


def _filename(message_id: str) -> str:
    """The deterministic file name for one Message-ID.

    A stable hash rather than the id itself: ids carry angle brackets and
    addresses, which are awkward in file names and unsafe on some
    volumes. The same message therefore always lands in the same file,
    so a rerun overwrites instead of duplicating.
    """
    digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:_FILENAME_HASH_CHARS]
    return f"{FEEDER_PREFIX}{digest}.eml"


def _atomic_write(path: Path, data: bytes) -> None:
    """Write bytes to path so a reader sees the old file or the new one.

    The temp file lives in the same folder (so os.replace is a rename,
    not a copy across volumes) and ends in .tmp, so the mail watcher's
    .eml listing never picks up a half-written file. A failed write or
    replace removes the temp and leaves the previous file untouched.
    """
    temp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _prune(folder: Path, *, now: float, window_days: int) -> None:
    """Remove feeder-owned files whose message date is outside the window.

    The window is the one the collector was given, measured on the Date
    header rather than the file's mtime, so a file disappears when its
    message leaves the window. Only names this writer produced are
    considered: a file the user saved by hand is never deleted, and a
    feeder file whose Date cannot be read is kept rather than guessed
    at.
    """
    cutoff = now - window_days * DAY_S
    for path in folder.glob(f"{FEEDER_PREFIX}*.eml"):
        try:
            message = parse_eml(path.read_bytes().decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 - an unreadable file is kept, never deleted
            continue
        if message.date_ts and message.date_ts < cutoff:
            try:
                path.unlink()
            except OSError:
                continue


def write_mail(messages, folder, *, now: float, window_days: int) -> int:
    """Write one header-only .eml per message and prune expired ones.

    Writes are atomic per file and deterministic per message id, so a
    rerun republishes the same files rather than growing the folder.
    Files this writer created whose message date has left the window are
    pruned after the new set is in place. Returns the number of files
    written (duplicate ids count once, since they name one file).
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    payloads = {
        folder / _filename(_message_id(message)): render_eml(message)
        for message in messages
    }
    for path, data in payloads.items():
        _atomic_write(path, data)
    _prune(folder, now=now, window_days=window_days)
    return len(payloads)


def write_status(status: dict, path) -> None:
    """Record one feeder status as JSON at path, atomically.

    The app reads this file when it builds the mail watcher, so it must
    never see a half-written document: the temp file plus os.replace
    gives it the previous status or the new one. Keys stay as given; the
    runner owns their names and values.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(status, indent=2, sort_keys=True, ensure_ascii=False)
    _atomic_write(path, (data + "\n").encode("utf-8"))
