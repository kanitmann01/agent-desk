"""Memory auto-save by default, and the folder-age migration (ticket 08).

A data folder born on this build saves captured facts without a review
card, one ledger entry per fact, each undoable from the Activity page.
A folder that predates this default keeps "ask me first": the boot
stores the explicit False before any store reads the setting, and a
user's explicit choice always survives.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.inbox.store import SCHEMA as INBOX_SCHEMA
from agentdesk.settings import SettingsStore


class ReplyLlm:
    """Answers the turn; any extraction prompt gets a facts payload."""

    def __init__(self, facts=None) -> None:
        self.facts = facts

    def __call__(self, prompt: str) -> str:
        if "durable memory facts" in prompt and self.facts is not None:
            return json.dumps({"facts": self.facts})
        if "You keep one short observation about" in prompt:
            name = prompt.split("observation about ", 1)[1].split(" in a work", 1)[0]
            ids = [int(line.split(" |", 1)[0]) for line in
                   prompt.split("Facts (id | date | text):\n", 1)[1].splitlines()]
            return json.dumps({"text": f"{name} stands on facts.",
                               "sourceFactIds": ids[:1]})
        return "Noted."


def _default_stores(folder: Path):
    """Boot with the real file-backed settings, inbox and memory stores
    under `folder` (AGENTDESK_DATA), everything else inert as usual."""
    return server_harness.Booted(
        settings_store=None, inbox_store=None, memory_store=None)


def _folder_with_inbox(data: Path) -> Path:
    """A folder an earlier build already used: it has an inbox database
    with the store's own schema (empty, as a quiet desk would be)."""
    data.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data / "inbox.sqlite3")
    conn.executescript(INBOX_SCHEMA)
    conn.commit()
    conn.close()
    return data


def test_auto_approve_migration_by_folder_age(tmp_path, monkeypatch):
    # An existing folder stores the explicit False so the new default
    # cannot flip an old desk's "ask me first".
    data = _folder_with_inbox(tmp_path / "data")
    monkeypatch.setenv("AGENTDESK_DATA", str(data))
    booted = _default_stores(data)
    try:
        assert booted.server.settings.get("memory_auto_approve") is False
        stored = sqlite3.connect(data / "settings.sqlite3").execute(
            "SELECT value FROM settings WHERE key = 'memory_auto_approve'"
        ).fetchone()
        assert stored == ("0",)
    finally:
        booted.close()

    # A fresh folder reads the new default True and stores no row at
    # all, so the setting stays a default the user can still change.
    fresh = tmp_path / "fresh"
    monkeypatch.setenv("AGENTDESK_DATA", str(fresh))
    booted = _default_stores(fresh)
    try:
        assert booted.server.settings.get("memory_auto_approve") is True
        assert sqlite3.connect(fresh / "settings.sqlite3").execute(
            "SELECT COUNT(*) FROM settings WHERE key = 'memory_auto_approve'"
        ).fetchone()[0] == 0
    finally:
        booted.close()

    # A folder where the user explicitly chose auto-approve keeps it:
    # the migration only fills the missing row.
    chosen = _folder_with_inbox(tmp_path / "chosen")
    monkeypatch.setenv("AGENTDESK_DATA", str(chosen))
    conn = sqlite3.connect(chosen / "settings.sqlite3")
    SettingsStore(conn).set("memory_auto_approve", True)
    conn.close()
    booted = _default_stores(chosen)
    try:
        assert booted.server.settings.get("memory_auto_approve") is True
    finally:
        booted.close()


def _boot_with_facts(facts, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    booted = server_harness.Booted(
        llm=ReplyLlm(facts=facts), llm_endpoint="http://endpoint.test/v1")
    return booted


FACTS = [
    {"text": "Priya Shah owns the Acme Corp renewal.", "kind": "world",
     "entities": [{"name": "Acme Corp", "type": "org"}]},
    {"text": "Acme Corp ships on Mondays.", "kind": "world",
     "entities": [{"name": "Acme Corp", "type": "org"}]},
]


def test_a_new_folder_saves_captured_facts_without_a_card(tmp_path, monkeypatch):
    booted = _boot_with_facts(FACTS, tmp_path, monkeypatch)
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/assistant/ask", {"question": "Who owns the Acme renewal?"}, auth)
        assert status == 200
        state = json.loads(booted.request(
            "GET", "/api/memory/loop", auth)[2])
        # No review card: the facts went straight to memory.
        assert state["counts"]["facts"] == 2
        assert state["candidates"] == []
        assert state["capture"]["autoApprove"] is True
        entries = [e for e in booted.server.ledger.entries(50)
                   if e.action == "memory.auto-saved"]
        assert len(entries) == 2
        for entry in entries:
            assert entry.undo_kind == "memory-fact"
            assert entry.undoable is True
    finally:
        booted.close()


def test_auto_saved_fact_is_undoable(tmp_path, monkeypatch):
    booted = _boot_with_facts(FACTS, tmp_path, monkeypatch)
    try:
        auth = booted.exchange()
        booted.post_json("/assistant/ask",
                         {"question": "Who owns the Acme renewal?"}, auth)
        saved = [e for e in booted.server.ledger.entries(50)
                 if e.action == "memory.auto-saved"]
        assert len(saved) == 2
        first = saved[0]
        status, _h, body = booted.post_json("/api/ledger/undo",
                                            {"id": first.id}, auth)
        assert status == 200
        assert json.loads(body)["undone"] == first.id
        state = json.loads(booted.request("GET", "/api/memory/loop", auth)[2])
        assert state["counts"]["facts"] == 1
        # The other fact's entry is still there and still undoable.
        still = [e for e in booted.server.ledger.entries(50)
                 if e.action == "memory.auto-saved" and e.undone_by is None]
        assert len(still) == 1
    finally:
        booted.close()


def test_the_activity_page_lists_the_auto_save_with_undo(tmp_path, monkeypatch):
    booted = _boot_with_facts(FACTS, tmp_path, monkeypatch)
    try:
        auth = booted.exchange()
        booted.post_json("/assistant/ask",
                         {"question": "Who owns the Acme renewal?"}, auth)
        page = booted.request("GET", "/settings/activity", auth)[2].decode("utf-8")
        assert "Saved a captured fact" in page
        assert "/api/ledger/undo" in page
        actions = {row[0] for row in booted.server.audit_conn.execute(
            "SELECT action FROM audit").fetchall()}
        assert "memory.auto-saved" in actions
    finally:
        booted.close()


def test_an_existing_folder_still_asks_first(tmp_path, monkeypatch):
    data = _folder_with_inbox(tmp_path / "data")
    monkeypatch.setenv("AGENTDESK_DATA", str(data))
    booted = server_harness.Booted(
        settings_store=None, inbox_store=None, memory_store=None,
        llm=ReplyLlm(facts=FACTS), llm_endpoint="http://endpoint.test/v1")
    try:
        auth = booted.exchange()
        booted.post_json("/assistant/ask",
                         {"question": "Who owns the Acme renewal?"}, auth)
        state = json.loads(booted.request("GET", "/api/memory/loop", auth)[2])
        # The old desk's contract: facts wait as review cards.
        assert state["counts"]["facts"] == 0
        assert len(state["candidates"]) == 2
        assert [e for e in booted.server.ledger.entries(50)
                if e.action == "memory.auto-saved"] == []
    finally:
        booted.close()
