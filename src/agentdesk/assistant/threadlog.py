"""The assistant thread: one local conversation, newest last.

Single-user app, one thread, kept in the local store next to the audit
log. The page renders it; nothing here talks to the network.
"""

import sqlite3
import time
from collections.abc import Callable

MAX_TURNS = 50


def append(conn: sqlite3.Connection, role: str, text: str, clock: Callable[[], float] = time.time) -> None:
    with conn:
        conn.execute(
            "INSERT INTO assistant_log (ts, role, text) VALUES (?, ?, ?)",
            (clock(), role, text),
        )
        # Bound the thread: keep the newest MAX_TURNS lines.
        conn.execute(
            "DELETE FROM assistant_log WHERE id NOT IN"
            " (SELECT id FROM assistant_log ORDER BY id DESC LIMIT ?)",
            (MAX_TURNS,),
        )


def turns(conn: sqlite3.Connection, limit: int = MAX_TURNS) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, role, text FROM (SELECT * FROM assistant_log ORDER BY id DESC LIMIT ?)"
        " ORDER BY id ASC",
        (limit,),
    ).fetchall()
    return [{"ts": r[0], "role": r[1], "text": r[2]} for r in rows]
