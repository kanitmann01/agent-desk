"""The calendar bridge state store: checks, breakdown cache, flags.

Three boring tables: checkbox state per subtask (survives restarts, the
acceptance that matters), the breakdown cache per event (a poll never
re-asks the model), and a one-shot flag so the app can say "calendar
data is arriving" exactly once.
"""

import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
  event_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  checked INTEGER NOT NULL,
  PRIMARY KEY (event_id, idx)
);
CREATE TABLE IF NOT EXISTS breakdowns (
  cache_key TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def set_check(conn: sqlite3.Connection, event_id: str, idx: int, checked: bool) -> None:
    with conn:
        conn.execute(
            "INSERT INTO checks (event_id, idx, checked) VALUES (?, ?, ?)"
            " ON CONFLICT(event_id, idx) DO UPDATE SET checked = excluded.checked",
            (event_id, idx, 1 if checked else 0),
        )


def get_checks(conn: sqlite3.Connection, event_id: str) -> dict[int, bool]:
    return {
        int(idx): bool(checked)
        for idx, checked in conn.execute(
            "SELECT idx, checked FROM checks WHERE event_id = ?", (event_id,)
        )
    }


def cached_breakdown(conn: sqlite3.Connection, cache_key: str) -> dict | None:
    row = conn.execute(
        "SELECT payload FROM breakdowns WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    return json.loads(row[0]) if row else None


def save_breakdown(conn: sqlite3.Connection, cache_key: str, payload: dict) -> None:
    with conn:
        conn.execute(
            "INSERT INTO breakdowns (cache_key, payload) VALUES (?, ?)"
            " ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload",
            (cache_key, json.dumps(payload, ensure_ascii=False)),
        )


def set_flag(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_flag(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None
