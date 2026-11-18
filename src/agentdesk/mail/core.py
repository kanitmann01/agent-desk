"""Header-only mail parsing and the digest/follow-up thread sets.

Ported from the teammate's packages/host/src/mail/mail.ts with one
deliberate divergence that shapes everything here: the donor kept the
message body on the parsed record and read bodies into model prompts,
which breaks this product's data-egress rule. This port is
metadata-only by construction. The stdlib email parser extracts exactly
the named headers (From, To, Cc, Subject, Date, Message-ID,
In-Reply-To) and the payload is never read: the Message record has no
body field at all, so there is nothing downstream that could carry a
body into a prompt, a card, a store or a file. The thread
sets (24-hour digest, no-action follow-ups) are pure functions over the
parsed records with an injectable clock; the donor's digestThreads
called the model with thread names and is not ported: the digest card
carries thread metadata only and no LLM call exists anywhere in the
mail path.
"""

import os
import re
import secrets
import time
from dataclasses import dataclass, replace
from datetime import datetime
from email import policy
from email.header import decode_header
from email.parser import Parser
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from typing import Callable

# The user's own address, the donor's v1 constant. Reply-all minus self
# and the follow-up exclusion both key on it.
MAIL_USER = "employee@example.com"

FOLLOW_UP_DAYS = 2  # the donor's threshold for "nobody acted on this"
DIGEST_HOURS = 24   # a thread is "active today" when a message landed in this window

DAY_S = 24 * 60 * 60

_RE_PREFIX = re.compile(r"^re:\s*", re.IGNORECASE)
_ADDRESS_SPLIT = re.compile(r"[,;]")


@dataclass(frozen=True)
class Message:
    """One message's headers and nothing else.

    There is no body field by design: parse_eml cannot produce one, so
    no caller can leak body text through this module (the DLP rule,
    enforced by the shape of the record, not by discipline).
    """

    id: str            # Message-ID
    in_reply_to: str   # In-Reply-To
    sender: str        # From
    to: str
    cc: str
    subject: str
    date_ts: float     # epoch seconds from the Date header; 0.0 when absent or unparseable
    thread: str = ""   # the root subject (Re: stripped), filled by with_threads
    importance: str = ""  # Importance or X-Priority, as written; "" when absent


def _decode_value(raw: str) -> str:
    """One header value as readable text: RFC 2047 encoded words decoded,
    folding whitespace collapsed."""
    if "=?" not in raw:
        return re.sub(r"\s+", " ", raw).strip()
    parts = decode_header(raw)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return re.sub(r"\s+", " ", "".join(decoded)).strip()


def parse_eml(text: str) -> Message:
    """Parse one .eml into its named headers, discarding the body.

    The parser runs in compat32 mode, which returns header values as the
    plain strings the sender wrote; only encoded words are decoded. This
    is a deliberate divergence from the plan's email.policy.default: the
    strict header registry parses address lists and silently drops what
    it cannot parse (a Cc line like "c@x.com; d@y.com" collapses to
    "<>"), while reply-all needs the addresses exactly as written. The
    parser object (which holds the payload) is local to this function
    and only the header values are copied out; the body is never read,
    stored or returned. A missing or unparseable Date header becomes
    0.0, which sorts oldest and never reads as recent.
    """
    parsed = Parser(policy=policy.compat32).parsestr(text)
    date_ts = 0.0
    raw_date = parsed.get("Date")
    if raw_date:
        try:
            date_ts = parsedate_to_datetime(raw_date.strip()).timestamp()
        except (TypeError, ValueError):
            date_ts = 0.0

    def header(name: str) -> str:
        """One named header as readable text; empty when the header is absent."""
        value = parsed.get(name)
        return _decode_value(value) if value is not None else ""

    message = Message(
        id=header("Message-ID"),
        in_reply_to=header("In-Reply-To"),
        sender=header("From"),
        to=header("To"),
        cc=header("Cc"),
        subject=header("Subject"),
        date_ts=date_ts,
        importance=(header("Importance") or header("X-Priority")),
    )
    return message  # the parsed object, body included, dies here


def read_eml_folder_reported(folder: Path) -> tuple[list[Message], int]:
    """Every .eml in the folder, parsed to headers only, date ascending,
    plus the count of files that could not be parsed.

    Per-file isolation: a file that raises while parsing (an unknown
    encoded-word charset, truncated headers, anything else a malformed
    export can produce) is skipped and counted, so one bad file cannot
    kill a whole poll or the mail page. The folder itself missing (or
    naming a file) still raises OSError, which the watcher reports as
    its error state; an existing but empty folder is simply no
    messages.
    """
    messages: list[Message] = []
    unparsed = 0
    for name in sorted(os.listdir(folder)):  # FileNotFoundError is an OSError
        if not name.endswith(".eml"):
            continue
        try:
            raw = (folder / name).read_bytes()
            messages.append(parse_eml(raw.decode("utf-8", errors="replace")))
        except Exception:  # noqa: BLE001 - one bad file must not kill the read
            unparsed += 1
    return messages, unparsed


def read_eml_folder(folder: Path) -> list[Message]:
    """The plain reader: the good messages only. See
    read_eml_folder_reported for the isolation contract and the count."""
    return read_eml_folder_reported(folder)[0]


def thread_of(message: Message, by_id: dict[str, Message]) -> str:
    """Walk In-Reply-To to the root and take its subject, Re: stripped.

    The donor's walk, with the same cycle guard: a thread whose parents
    loop (or point at themselves) terminates because no id is visited
    twice. An orphan (In-Reply-To names an absent message) threads under
    its own subject.
    """
    current = message
    seen: set[str] = set()
    while (
        current.in_reply_to
        and current.in_reply_to in by_id
        and current.id not in seen
    ):
        seen.add(current.id)
        current = by_id[current.in_reply_to]
    return _RE_PREFIX.sub("", current.subject).strip()


def with_threads(messages: list[Message]) -> list[Message]:
    """Fill the thread field on every message, date ascending."""
    by_id = {m.id: m for m in messages}
    threaded = [replace(m, thread=thread_of(m, by_id)) for m in messages]
    return sorted(threaded, key=lambda m: (m.date_ts, m.id))


def latest_by_thread(messages: list[Message]) -> dict[str, Message]:
    """The newest message per thread, the donor's follow-up window."""
    latest: dict[str, Message] = {}
    for message in messages:
        current = latest.get(message.thread)
        if current is None or message.date_ts > current.date_ts:
            latest[message.thread] = message
    return latest


def recent_threads(messages: list[Message], now: float, hours: float = DIGEST_HOURS) -> list[str]:
    """Threads with at least one message inside the window, sorted.

    The donor's recentThreads as a pure function: the thread NAMES are
    metadata, and this set is exactly what the digest card carries.
    """
    cutoff = now - hours * 3600
    names = {m.thread for m in messages if m.date_ts >= cutoff}
    return sorted(names)


def digest_details(messages: list[Message], now: float, hours: float = DIGEST_HOURS) -> list[dict]:
    """The digest as card/page metadata: thread, message count, last sender."""
    latest = latest_by_thread(messages)
    details = []
    for name in recent_threads(messages, now, hours):
        last = latest[name]
        count = sum(1 for m in messages if m.thread == name)
        details.append({
            "thread": name,
            "count": count,
            "lastFrom": last.sender,
            "lastTs": last.date_ts,
        })
    return details


def follow_ups(
    messages: list[Message],
    handled: set[str],
    now: float,
    days: float = FOLLOW_UP_DAYS,
    self_address: str = MAIL_USER,
) -> list[str]:
    """Threads whose newest message is not the user's, sits past the
    threshold, and is not handled, sorted.

    The donor's followUps with the handled set passed in instead of
    queried from a database: the store is the watcher's concern, this
    stays pure.
    """
    cutoff = now - days * DAY_S
    mine = self_address.lower()
    names = []
    for name, message in latest_by_thread(messages).items():
        if (
            message.sender.lower() != mine
            and message.date_ts < cutoff
            and name not in handled
        ):
            names.append(name)
    return sorted(names)


def follow_up_details(
    messages: list[Message],
    handled: set[str],
    now: float,
    days: float = FOLLOW_UP_DAYS,
    self_address: str = MAIL_USER,
) -> list[dict]:
    """The follow-ups as card/page metadata: thread and its latest message."""
    latest = latest_by_thread(messages)
    details = []
    for name in follow_ups(messages, handled, now, days, self_address):
        last = latest[name]
        details.append({
            "thread": name,
            "messageId": last.id,
            "from": last.sender,
            "dateTs": last.date_ts,
            "days": days,
        })
    return details


def reply_recipients(message: Message, self_address: str = MAIL_USER) -> str:
    """Reply-all minus this user's own address, deduped, From first.

    The donor's replyRecipients: split on commas and semicolons, drop
    empties, drop the self address case-insensitively, keep the first
    spelling of every address. Raises when nobody else is left, because
    a reply to no one is not a reply.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for raw in _ADDRESS_SPLIT.split(f"{message.sender},{message.to},{message.cc}"):
        address = raw.strip()
        key = address.lower()
        if not address or key == self_address.lower() or key in seen:
            continue
        seen.add(key)
        kept.append(address)
    if not kept:
        raise ValueError("There is nobody else to reply to on this message.")
    return ", ".join(kept)


def reply_subject(subject: str) -> str:
    """The subject a reply carries: Re: once, never Re: Re:."""
    if _RE_PREFIX.match(subject):
        return subject
    return f"Re: {subject}"


def write_reply(
    outbox: Path,
    original_id: str,
    to: str,
    subject: str,
    body: str,
    clock: Callable[[], float] = time.time,
) -> Path:
    """Write the threaded reply as an .eml file into the outbox folder.

    The donor's writeReply: proper headers, a fresh Message-ID, In-
    Reply-To pointing at the original, CRLF line endings. The body is
    what the user typed on the card; this function is the only place a
    mail file is ever written, and sending it remains the user's own
    act in their own mail client.

    Header injection guard: to, subject and original_id are written
    verbatim into the header block, and they can arrive from places
    this app does not compose (the generic cards route stores a card's
    meta as given). Any CR or LF in them raises ValueError BEFORE
    anything is created, because a line break there would smuggle a
    second header line (a Bcc:, say) into a file the user later sends
    from their own mail client. The body is exempt: newlines there are
    the user's own words, and they live after the header block.
    """
    for name, value in (("original id", original_id), ("recipients", to), ("subject", subject)):
        if "\r" in value or "\n" in value:
            raise ValueError(
                f"The reply's {name} contain a line break, which could "
                "smuggle a header line into the reply file; nothing was written."
            )
    outbox = Path(outbox)
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = int(clock() * 1000)
    message_id = f"<reply-{stamp}@example.com>"
    file = outbox / f"{stamp}-{secrets.token_hex(4)}.eml"
    text = "\r\n".join([
        f"From: {MAIL_USER}",
        f"To: {to}",
        f"Subject: {subject}",
        f"Date: {formatdate(stamp / 1000, usegmt=True)}",
        f"Message-ID: {message_id}",
        f"In-Reply-To: {original_id}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "",
        body,
        "",
    ])
    file.write_bytes(text.encode("utf-8"))
    return file


def format_header_ts(date_ts: float) -> str:
    """A message date for the page and cards, plain local words. Odd
    Date headers (a pre-1970 date raises OSError on Windows, an
    out-of-range one raises OverflowError) read as 'unknown date'
    instead of losing the whole render."""
    if not date_ts:
        return "unknown date"
    try:
        return datetime.fromtimestamp(date_ts).astimezone().strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "unknown date"
