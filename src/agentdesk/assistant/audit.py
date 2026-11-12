"""The audit store: what touched what, and when.

Append-only by policy and by schema (no update or delete statements
anywhere). Every outbound model call and every brokered watch action
lands here as (actor, action, target, timestamp) plus status metadata,
exportable as plain CSV for Security review. The log describes calls; it
never carries prompt text or raw file contents.
"""

import csv
import io
import sqlite3
import time
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  actor TEXT NOT NULL DEFAULT 'agent-desk',
  action TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  request_bytes INTEGER NOT NULL DEFAULT 0,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS assistant_log (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL
);
"""

# The audit event vocabulary: every action the app can record, with the
# plain-language statement the what-this-touches page shows. The page is
# generated from this table and the store's observed actions, so it
# cannot drift from reality by more than one entry.
VOCABULARY: list[tuple[str, str, str]] = [
    ("excel.register", "file", "You choose a workbook through a file picker; its name is remembered so the app can watch it."),
    ("excel.poll", "file", "The watched workbook is copied to a temp file and read there, read-only, never opened in place."),
    ("calendar.ingest", "file", "The calendar JSON your own Power Automate flow writes to OneDrive is read, read-only."),
    ("calendar.poll", "file", "The calendar file is checked for updates, read-only."),
    ("llm.research", "endpoint", "Research questions are sent to the company LLM endpoint, as derived text only."),
    ("llm.assistant", "endpoint", "Assistant questions are sent to the company LLM endpoint, with widget context attached."),
    ("llm.breakdown", "endpoint", "Meeting breakdowns are sent to the company LLM endpoint, meeting name only."),
    ("llm.wizard", "endpoint", "Your plain-English plugin description, with the app's fixed list of data-source kinds, is sent to the company LLM endpoint so the wizard can draft its questions and the plugin manifest. No workbook, calendar or mail data is attached."),
    # The mail vocabulary (ticket #44), off by default in settings. The
    # mail path is metadata-only by construction: bodies are discarded
    # at parse time and no LLM call exists anywhere in it.
    ("mail.poll", "file", "The mail folder you chose is listed and the .eml headers are read, read-only. Message bodies are discarded at parse time and never stored. Off by default."),
    ("mail.draft", "decision", "A reply draft card was created from the message's headers (recipients, subject). The draft text is what you typed, never message content."),
    ("mail.sent", "file", "Accepting a reply draft wrote a threaded .eml file into the local outbox folder. Nothing is transmitted by this app; sending the reply is yours to do in your own mail client."),
    # The approvals vocabulary (ticket #41): every decision on an inbox
    # card, and every plugin lifecycle mutation.
    ("inbox.approved", "decision", "You accepted a card in the inbox; the acceptance is recorded against that card."),
    ("inbox.denied", "decision", "You dismissed a card in the inbox; the dismissal is recorded against that card."),
    ("inbox.edited", "decision", "You edited a card's draft; a plain-text preview of the draft is recorded, never markup."),
    ("inbox.snoozed", "decision", "You snoozed a card for one hour or until the next morning; the return time is recorded."),
    ("inbox.more-info", "decision", "You asked for more information; your instruction is recorded with the card."),
    ("inbox.pending", "decision", "A snoozed card came back due, or a plugin update began waiting for your OK; recorded so nothing reappears silently."),
    # The memory vocabulary (ticket #42): the one non-page creation path.
    # The row names the fact's source, never the fact's text.
    ("memory.fact", "decision", "An accepted inbox card carried a fact, and it was saved to the memory store. The row names where the fact came from, never the fact itself."),
    ("plugin.install", "plugin", "A plugin zip you chose, or a registry release you picked, is validated and installed under the app's own data folder, in pilot mode."),
    ("plugin.update", "plugin", "A plugin update is validated; identical or narrower permissions apply, wider ones hold for your OK."),
    ("plugin.consent", "plugin", "A held plugin update is applied after you approved its added permissions."),
    ("plugin.enable", "plugin", "An installed plugin is turned back on; its widget returns to the dashboard."),
    ("plugin.disable", "plugin", "An installed plugin is turned off; its files and data stay untouched."),
    ("plugin.uninstall", "plugin", "An installed plugin's program files are deleted; its data is kept until a separate purge."),
    ("plugin.rollback", "plugin", "A plugin is switched back to its previous version; both versions stay recorded."),
    ("plugin.retest", "plugin", "A plugin's declared data source is checked again, right now, to refresh its card."),
    ("plugin.purge-data", "plugin", "A plugin's kept data folder is deleted, only after the separate named confirmation."),
    # The registry bridge: reads stay local, no network anywhere in it.
    ("registry.read", "file", "The plugins page reads the local registry checkout's index.json, read-only, to list what can be installed."),
    ("settings.registry", "decision", "The registry checkout folder was saved or cleared in settings; the choice itself is the record."),
]

ACTOR = "agent-desk"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Light migration for stores created by earlier builds: append-only
    # means we add columns, never rewrite rows.
    for column in ("actor", "target"):
        try:
            conn.execute(f"ALTER TABLE audit ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already there
    conn.commit()


def record(
    conn: sqlite3.Connection,
    action: str,
    target: str = "",
    status: str = "ok",
    detail: str = "",
    model: str = "",
    request_bytes: int = 0,
    clock: Callable[[], float] = time.time,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO audit (ts, actor, action, target, status, model, request_bytes, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (clock(), ACTOR, action, target, status, model, request_bytes, detail),
        )


_SELECT = ("SELECT ts, actor, action, target, status, model, request_bytes,"
           " detail FROM audit")


def _as_entries(rows) -> list[dict]:
    return [
        {
            "ts": r[0],
            "actor": r[1],
            "action": r[2],
            "target": r[3],
            "status": r[4],
            "model": r[5],
            "request_bytes": r[6],
            "detail": r[7],
        }
        for r in rows
    ]


def entries(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        _SELECT + " ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return _as_entries(rows)


def decision_entries(conn: sqlite3.Connection, actions, limit: int = 100) -> list[dict]:
    """Rows for the given actions only, newest first, filtered in SQL.

    The background polls (hourly excel, half-hourly calendar) fill the
    newest-100 window of a plain entries() call in a couple of days; a
    page that promises every decision must filter before the limit, not
    after it.
    """
    actions = tuple(actions)
    if not actions:
        return []
    placeholders = ",".join("?" for _ in actions)
    rows = conn.execute(
        f"{_SELECT} WHERE action IN ({placeholders}) ORDER BY id DESC LIMIT ?",
        (*actions, limit),
    ).fetchall()
    return _as_entries(rows)


def observed_actions(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT action FROM audit")}


def csv_bytes(conn: sqlite3.Connection) -> bytes:
    """The export Security reviews: actor, action, target, timestamp.

    RFC 4180 quoting, CRLF rows, single-line fields by construction: the
    file opens in Excel exactly as it opened here.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["actor", "action", "target", "timestamp"])
    for row in conn.execute(
        "SELECT actor, action, target, ts FROM audit ORDER BY id ASC"
    ):
        writer.writerow([row[0], row[1], row[2], format_ts(row[3])])
    return buffer.getvalue().encode("utf-8")


def format_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def last_ok_ts(conn: sqlite3.Connection, action: str) -> float | None:
    row = conn.execute(
        "SELECT MAX(ts) FROM audit WHERE action = ? AND status = 'ok'", (action,)
    ).fetchone()
    return row[0] if row and row[0] is not None else None
