"""The inbox stays readable when a row's kind means nothing to this build.

A card written by another build is data, not a crash: every read skips it,
it is listed raw so a later build can still act on it, and asking for it by
id is a 404 rather than a 500. The pages are driven through the real server,
because the bug this guards was every page failing at once.
"""

import json
import logging
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from nexuusbot.inbox.core import UnknownCard
from nexuusbot.inbox.store import InboxStore

NOW = 1700000000.0

RAW_COLUMNS = [
    "id", "kind", "origin", "title", "body", "action_label", "status",
    "created_ts", "window_hours", "notified_ts", "dismissed_ts",
    "accepted_ts", "draft", "snoozed_until", "meta",
]


def make_store(tmp_path: Path) -> InboxStore:
    conn = sqlite3.connect(tmp_path / "inbox.sqlite3", check_same_thread=False)
    return InboxStore(conn, lambda: NOW)


def insert_raw(store: InboxStore, kind: str = "commitment") -> str:
    """Write one row the way another build's store would: no Card involved."""
    card_id = f"raw-{uuid.uuid4().hex}"
    with store.conn:
        store.conn.execute(
            "INSERT INTO cards (id, kind, origin, title, body, action_label,"
            " status, created_ts) VALUES (?, ?, ?, ?, '', '', 'waiting', ?)",
            (card_id, kind, "Written by another build", "A card this build cannot read", NOW),
        )
    return card_id


def test_unknown_kind_row_does_not_break_reads(tmp_path):
    store = make_store(tmp_path)
    good = store.add(kind="suggestion", origin="Desk", title="A readable card")
    raw_id = insert_raw(store)

    assert [card.id for card in store.waiting()] == [good.id]
    assert [card.id for card in store.all_cards()] == [good.id]
    assert store.dismissed() == []
    with pytest.raises(UnknownCard):
        store.get(raw_id)


def test_unreadable_lists_raw_rows(tmp_path):
    store = make_store(tmp_path)
    store.add(kind="suggestion", origin="Desk", title="A readable card")
    raw_id = insert_raw(store)

    rows = store.unreadable()

    assert [row["id"] for row in rows] == [raw_id]
    assert sorted(rows[0]) == sorted(RAW_COLUMNS)
    assert rows[0]["kind"] == "commitment"
    assert rows[0]["title"] == "A card this build cannot read"


def test_unreadable_row_is_logged_once_per_id(tmp_path, caplog):
    store = make_store(tmp_path)
    raw_id = insert_raw(store)

    with caplog.at_level(logging.WARNING, logger="nexuusbot.inbox.store"):
        store.waiting()
        store.all_cards()
        store.waiting()

    mentions = [record for record in caplog.records if raw_id in record.getMessage()]
    assert len(mentions) == 1
    assert mentions[0].levelno == logging.WARNING


def test_unknown_kind_row_does_not_break_the_pages(tmp_path):
    store = make_store(tmp_path)
    raw_id = insert_raw(store)
    booted = server_harness.Booted(inbox_store=store)
    try:
        auth = booted.exchange()
        for path in ("/", "/inbox", "/settings"):
            status, _headers, _body = booted.request("GET", path, auth)
            assert status == 200, path
        status, _headers, body = booted.request("GET", "/api/dashboard", auth)
        assert status == 200
        assert json.loads(body)["inbox"]["waiting"] == 0
        status, _headers, page = booted.request("GET", "/inbox", auth)
        assert b"A card this build cannot read" not in page
        status, _headers, body = booted.post_json(f"/inbox/cards/{raw_id}/dismiss", {}, auth)
        assert status == 404
        assert json.loads(body)["error"]
    finally:
        booted.close()
