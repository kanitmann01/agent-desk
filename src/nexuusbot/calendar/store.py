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
    """Create the calendar store's tables.

    Idempotent: the schema uses IF NOT EXISTS, so this runs on every open.
    """
    conn.executescript(SCHEMA)
    conn.commit()


def set_check(conn: sqlite3.Connection, event_id: str, idx: int, checked: bool) -> None:
    """Record one subtask's checkbox state, replacing an earlier value.

    idx is the subtask's position rather than its text, so the state follows
    position if a breakdown is regenerated in a different order.
    """
    with conn:
        conn.execute(
            "INSERT INTO checks (event_id, idx, checked) VALUES (?, ?, ?)"
            " ON CONFLICT(event_id, idx) DO UPDATE SET checked = excluded.checked",
            (event_id, idx, 1 if checked else 0),
        )


def get_checks(conn: sqlite3.Connection, event_id: str) -> dict[int, bool]:
    """Return the checked state of each subtask, keyed by position.

    Only rows written for this event appear: a subtask never touched is
    absent from the mapping rather than present as False.
    """
    return {
        int(idx): bool(checked)
        for idx, checked in conn.execute(
            "SELECT idx, checked FROM checks WHERE event_id = ?", (event_id,)
        )
    }


def cached_breakdown(conn: sqlite3.Connection, cache_key: str) -> dict | None:
    """Return the stored breakdown for this key, or None when nothing is cached.

    The payload is decoded on the way out, so callers get the dict that was
    saved rather than JSON text.
    """
    row = conn.execute(
        "SELECT payload FROM breakdowns WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    return json.loads(row[0]) if row else None


def save_breakdown(conn: sqlite3.Connection, cache_key: str, payload: dict) -> None:
    """Store one breakdown payload under a cache key, replacing an earlier one.

    The payload is serialized here with non-ASCII text left readable, so the
    row can be inspected directly.
    """
    with conn:
        conn.execute(
            "INSERT INTO breakdowns (cache_key, payload) VALUES (?, ?)"
            " ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload",
            (cache_key, json.dumps(payload, ensure_ascii=False)),
        )


def set_flag(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Write one value into the meta key/value table, replacing an earlier one.

    Flags are the store's small pieces of state; each is read back by key
    alone.
    """
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_flag(conn: sqlite3.Connection, key: str) -> str | None:
    """Return the stored value for a meta key, or None when it was never set."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


# The explicitly chosen calendar file, keyed here like the excel watch
# keys its registered workbook: the choice survives restarts.
CALENDAR_PATH_KEY = "calendar_path"


def set_calendar_path(conn: sqlite3.Connection, path: str) -> None:
    """Remember the calendar file the user chose.

    Stored under one fixed key, so a new choice replaces the previous one.
    """
    set_flag(conn, CALENDAR_PATH_KEY, path)


def get_calendar_path(conn: sqlite3.Connection) -> str | None:
    """Return the chosen calendar file, or None before one is chosen."""
    return get_flag(conn, CALENDAR_PATH_KEY)


def clear_calendar_path(conn: sqlite3.Connection) -> None:
    """Forget the chosen calendar file, leaving the other meta flags untouched.

    Clearing puts the widget back in its unconfigured state; the checks and
    the breakdown cache are kept, so reconnecting the same file restores
    them.
    """
    with conn:
        conn.execute("DELETE FROM meta WHERE key = ?", (CALENDAR_PATH_KEY,))
