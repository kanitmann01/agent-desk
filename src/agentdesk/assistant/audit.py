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


def entries(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, actor, action, target, status, model, request_bytes, detail"
        " FROM audit ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
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
