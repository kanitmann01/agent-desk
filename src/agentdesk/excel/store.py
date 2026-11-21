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

# Nothing reads a snapshot older than the 24-hour reference; seven days
# covers restarts and holidays, and keeps each source's history bounded.
PRUNE_AFTER_S = 7 * 24 * 60 * 60.0

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
    """Create the snapshot tables if they are missing."""
    conn.executescript(SCHEMA)
    conn.commit()


def save_snapshot(conn: sqlite3.Connection, source: str, ts: float, rows: list, digest) -> None:
    """Store one poll's rows, then prune this source's history.

    `digest` is the row_hash function (injected). The prune is part of
    the save so every writer stays bounded, not just the watcher's."""
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
        conn.execute(
            "DELETE FROM snapshots WHERE source = ? AND poll_ts < ?",
            (source, ts - PRUNE_AFTER_S),
        )


def load_reference(conn: sqlite3.Connection, source: str, now: float, window_s: float = WINDOW_24H) -> "tuple[float, list] | None":
    """The newest snapshot at or before now minus the window, with its
    poll time, or None.

    None means no baseline exists yet: the widget says the 24-hour view
    starts with the next poll instead of inventing a delta. The poll
    time is returned so the card can name the window it actually diffed
    against, which is not always the last 24 hours.
    """
    boundary = now - window_s
    row = conn.execute(
        "SELECT MAX(poll_ts) FROM snapshots WHERE source = ? AND poll_ts <= ?",
        (source, boundary),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    ref_ts = row[0]
    rows = [
        json.loads(r[0])
        for r in conn.execute(
            "SELECT row_values FROM snapshots WHERE source = ? AND poll_ts = ?"
            " ORDER BY row_index",
            (source, ref_ts),
        )
    ]
    return ref_ts, rows


def snapshot_count(conn: sqlite3.Connection, source: str) -> int:
    """Count how many distinct polls have been recorded for a source."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT poll_ts) FROM snapshots WHERE source = ?", (source,)
    ).fetchone()
    return int(row[0]) if row else 0


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Store a metadata value, replacing whatever the key held before."""
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Return the stored value for a metadata key, or None when unset."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None
