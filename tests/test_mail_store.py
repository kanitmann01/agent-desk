"""The mail store: handled threads persist across restarts.

SQLite like every store in the repo (ensure_schema, injectable clock,
`with conn` writes), over a tmp file and reopened through
contextlib.closing to prove the persistence is real.
"""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.mail.store import MailStore, ensure_schema


def test_new_store_has_no_handled_threads(tmp_path):
    with closing(sqlite3.connect(tmp_path / "mail.sqlite3")) as conn:
        store = MailStore(conn, clock=lambda: 1000.0)
        assert store.handled() == set()
        assert not store.is_handled("North contract")


def test_mark_handled_then_read_back(tmp_path):
    with closing(sqlite3.connect(tmp_path / "mail.sqlite3")) as conn:
        store = MailStore(conn, clock=lambda: 1000.0)
        store.mark_handled("North contract")
        store.mark_handled("Q4 plan")
        assert store.handled() == {"North contract", "Q4 plan"}
        assert store.is_handled("North contract")
        assert not store.is_handled("West renewal")


def test_mark_twice_is_a_no_conflict_update(tmp_path):
    with closing(sqlite3.connect(tmp_path / "mail.sqlite3")) as conn:
        store = MailStore(conn, clock=lambda: 1000.0)
        store.mark_handled("North contract")
        store.mark_handled("North contract")  # must not raise
        assert store.handled() == {"North contract"}


def test_handled_threads_persist_across_reopen(tmp_path):
    file = tmp_path / "mail.sqlite3"
    with closing(sqlite3.connect(file)) as conn:
        MailStore(conn, clock=lambda: 1.0).mark_handled("North contract")
    with closing(sqlite3.connect(file)) as conn:
        store = MailStore(conn, clock=lambda: 2.0)
        assert store.handled() == {"North contract"}
        assert store.handled_ts("North contract") == 1.0


def test_ensure_schema_is_idempotent(tmp_path):
    with closing(sqlite3.connect(tmp_path / "mail.sqlite3")) as conn:
        ensure_schema(conn)
        ensure_schema(conn)  # must not raise


def test_handled_ts_is_unknown_for_unmarked_threads(tmp_path):
    with closing(sqlite3.connect(tmp_path / "mail.sqlite3")) as conn:
        store = MailStore(conn, clock=lambda: 5.0)
        assert store.handled_ts("Never marked") is None
