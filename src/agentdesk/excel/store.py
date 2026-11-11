"""The snapshot store: SQLite rows with poll times, the delta clock.

The workbook carries no timestamps, so the store is the clock: the delta
always compares against the newest snapshot taken at or before T-24h. The
schema is deliberately boring: snapshots plus a tiny meta table (the
registered workbook path, so a restart resumes the same watch), bulk
inserts, three queries.
"""

import json
import sqlite3

WINDOW_24H = 24 * 60 * 60.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  poll_ts REAL NOT NULL,
  row_index INTEGER NOT NULL,
  row_digest TEXT NOT NULL,
  row_values TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_source_ts ON snapshots(source, poll_ts);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# The registered workbook path, keyed here so the watch survives restarts.
WORKBOOK_PATH_KEY = "workbook_path"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def save_snapshot(conn: sqlite3.Connection, source: str, ts: float, rows: list, digest) -> None:
    """Store one poll's rows. `digest` is the row_hash function (injected)."""
    payload = [
        (source, ts, i, digest(row), json.dumps(row, ensure_ascii=False))
        for i, row in enumerate(rows)
    ]
    with conn:
        conn.executemany(
            "INSERT INTO snapshots (source, poll_ts, row_index, row_digest, row_values)"
            " VALUES (?, ?, ?, ?, ?)",
            payload,
        )


def load_reference(conn: sqlite3.Connection, source: str, now: float, window_s: float = WINDOW_24H) -> list | None:
    """The newest snapshot at or before now minus the window, or None.

    None means no baseline exists yet: the widget says the 24-hour view
    starts with the next poll instead of inventing a delta.
    """
    boundary = now - window_s
    row = conn.execute(
        "SELECT MAX(poll_ts) FROM snapshots WHERE source = ? AND poll_ts <= ?",
        (source, boundary),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    ref_ts = row[0]
    return [
        json.loads(r[0])
        for r in conn.execute(
            "SELECT row_values FROM snapshots WHERE source = ? AND poll_ts = ?"
            " ORDER BY row_index",
            (source, ref_ts),
        )
    ]


def snapshot_count(conn: sqlite3.Connection, source: str) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT poll_ts) FROM snapshots WHERE source = ?", (source,)
    ).fetchone()
    return int(row[0]) if row else 0


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None
