"""The audit store: what left the machine, and when.

Every outbound model or search call lands here with its target endpoint
and timestamp. Raw file contents never enter the log: an entry records
the call's shape (kind, endpoint, model, request size, outcome), which is
exactly what an IT reviewer needs and nothing a leak would want.
"""

import sqlite3
import time
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  kind TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  request_bytes INTEGER NOT NULL,
  detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assistant_log (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def record(
    conn: sqlite3.Connection,
    kind: str,
    endpoint: str,
    model: str,
    status: str,
    request_bytes: int,
    detail: str = "",
    clock: Callable[[], float] = time.time,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO audit (ts, kind, endpoint, model, status, request_bytes, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (clock(), kind, endpoint, model, status, request_bytes, detail),
        )


def entries(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, kind, endpoint, model, status, request_bytes, detail"
        " FROM audit ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "ts": r[0],
            "kind": r[1],
            "endpoint": r[2],
            "model": r[3],
            "status": r[4],
            "request_bytes": r[5],
            "detail": r[6],
        }
        for r in rows
    ]


def last_ok_ts(conn: sqlite3.Connection, kind: str) -> float | None:
    row = conn.execute(
        "SELECT MAX(ts) FROM audit WHERE kind = ? AND status = 'ok'", (kind,)
    ).fetchone()
    return row[0] if row and row[0] is not None else None
