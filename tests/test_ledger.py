"""The action ledger, driven through its public seam.

These tests use only the class Undo and the pages call, with an injected
clock and a temp database, so the behaviour they pin is the behaviour the
app gets: bounded storage, captures that can be read back, latches, and
the ask-first gate.
"""

import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest

from nexuusbot.ledger import ASK_FIRST, Entry, Ledger, LedgerError, may_act
from nexuusbot.ledger.undo import undo
from nexuusbot.settings import SettingsStore


class Clock:
    """A clock the test moves by hand, so ageing is exact."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _ledger(tmp_path: Path, **kwargs) -> Ledger:
    return Ledger(tmp_path / "ledger.sqlite3", **kwargs)


def test_record_stores_captures_that_read_back(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, clock=Clock())
    try:
        before = json.dumps({"key": "daily_cap", "value": 3}).encode()
        after = json.dumps({"key": "daily_cap", "value": 1}).encode()
        entry = ledger.record(
            actor="agent-desk",
            action="settings.set",
            subject="daily_cap",
            why="Quiet hours started, so the cap went down.",
            undo_kind="settings-key",
            before=before,
            after=after,
        )
        assert isinstance(entry, Entry)
        assert entry.undoable is True
        assert entry.before_sha is not None and entry.after_sha is not None
        assert ledger.get_blob(entry.before_sha) == before
        assert ledger.get_blob(entry.after_sha) == after
        assert ledger.get(entry.id) == entry
    finally:
        ledger.close()


def test_entries_are_newest_first_and_none_is_not_undoable(tmp_path: Path) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, clock=clock)
    try:
        first = ledger.record(actor="agent-desk", action="settings.set", subject="daily_cap", why="One.")
        clock.advance(5.0)
        second = ledger.record(actor="agent-desk", action="deskcheck.fix", subject="toolbar", why="Two.")
        assert [entry.id for entry in ledger.entries()] == [second.id, first.id]
        assert ledger.entries()[0].undoable is False
        assert ledger.get("no-such-entry") is None
        assert ledger.entries(limit=1) == [second]
    finally:
        ledger.close()


def test_blob_over_cap_raises_and_the_action_does_not_run(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        with pytest.raises(LedgerError):
            ledger.put_blob(b"x" * (2 * 2**20 + 1))
        with pytest.raises(LedgerError):
            ledger.record(
                actor="agent-desk",
                action="settings.set",
                subject="daily_cap",
                why="Too big to capture.",
                undo_kind="settings-key",
                before=b"y" * (2 * 2**20 + 1),
            )
        assert ledger.entries() == []
        # Only the before state is a promise; an after capture that no
        # longer fits is dropped and the action is still recorded.
        before = b'{"key": "daily_cap", "value": 3}'
        partial = ledger.record(
            actor="agent-desk",
            action="settings.set",
            subject="daily_cap",
            why="Before kept, after too big.",
            undo_kind="settings-key",
            before=before,
            after=b"z" * (2 * 2**20 + 1),
        )
        assert partial.undoable is True
        assert ledger.get_blob(partial.before_sha) == before
        assert partial.after_sha is None
        # A plain record has no undo state to protect and never blocks.
        plain = ledger.record(actor="agent-desk", action="deskcheck.fix", subject="toolbar", why="Nothing to keep.")
        assert plain.undoable is False
    finally:
        ledger.close()


def test_latches_round_trip(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        assert ledger.latched("memory.consolidate") is False
        assert ledger.latch_value("memory.consolidate") is None
        ledger.latch("memory.consolidate")
        ledger.latch("memory.consolidate")  # idempotent
        assert ledger.latched("memory.consolidate") is True
        assert ledger.latch_value("memory.consolidate") == ""
        ledger.latch("update.check", "2026-11-20")
        assert ledger.latch_value("update.check") == "2026-11-20"
        ledger.unlatch("memory.consolidate")
        assert ledger.latched("memory.consolidate") is False
    finally:
        ledger.close()


def test_trim_keeps_cap_and_referenced_blobs(tmp_path: Path) -> None:
    clock = Clock(1_000_000.0)
    ledger = _ledger(tmp_path, clock=clock, cap_bytes=10 * 1024)
    try:
        for index in range(40):
            clock.advance(2 * 60 * 60)
            before = json.dumps({"key": "daily_cap", "value": 3, "n": index}).encode() * 6
            after = json.dumps({"key": "daily_cap", "value": 1, "n": index}).encode() * 6
            ledger.record(
                actor="agent-desk",
                action="settings.set",
                subject="daily_cap",
                why="Each quiet hour lowers the cap for a while.",
                undo_kind="settings-key",
                before=before,
                after=after,
            )
        clock.advance(2 * 60 * 60)
        kept = ledger.record(actor="agent-desk", action="deskcheck.fix", subject="toolbar", why="Newest, always kept.")
        stored = ledger.conn.execute("SELECT COALESCE(SUM(LENGTH(data)), 0) FROM blobs").fetchone()[0]
        assert stored <= 10 * 1024
        entries = ledger.entries(limit=1000)
        assert entries and entries[0].id == kept.id
        for entry in entries:
            for sha in (entry.before_sha, entry.after_sha):
                if sha is not None:
                    ledger.get_blob(sha)
    finally:
        ledger.close()


def test_trim_drops_unreferenced_blobs_without_waiting_out_the_grace(tmp_path: Path) -> None:
    clock = Clock(1_000_000.0)
    ledger = _ledger(tmp_path, clock=clock, cap_bytes=10 * 1024)
    try:
        for index in range(40):
            clock.advance(1)
            before = json.dumps({"key": "daily_cap", "value": 3, "n": index}).encode() * 6
            after = json.dumps({"key": "daily_cap", "value": 1, "n": index}).encode() * 6
            ledger.record(
                actor="agent-desk",
                action="settings.set",
                subject="daily_cap",
                why="A burst of changes, one second apart.",
                undo_kind="settings-key",
                before=before,
                after=after,
            )
        stored = ledger.conn.execute("SELECT COALESCE(SUM(LENGTH(data)), 0) FROM blobs").fetchone()[0]
        entries = ledger.entries(limit=1000)
        assert len(entries) > 1
        assert stored <= 10 * 1024
        for entry in entries:
            for sha in (entry.before_sha, entry.after_sha):
                if sha is not None:
                    ledger.get_blob(sha)
    finally:
        ledger.close()


def test_a_sealed_blob_that_will_not_open_is_not_returned_as_plaintext(tmp_path: Path) -> None:
    def seal(data: bytes) -> bytes:
        return b"\x01" + b"iv-twelve!!" + data

    def unseal(_data: bytes) -> bytes:
        raise RuntimeError("wrong key")

    ledger = Ledger(tmp_path / "ledger.sqlite3", seal=seal, unseal=unseal)
    try:
        entry = ledger.record(
            actor="agent-desk",
            action="memory.add",
            subject="memory/fact",
            why="A private fact.",
            before=b"secret",
        )
        with pytest.raises(LedgerError):
            ledger.get_blob(entry.before_sha)
        plain = ledger.put_blob(b"not an envelope")
        assert ledger.get_blob(plain) == b"not an envelope"
    finally:
        ledger.close()


def test_two_undos_at_once_record_only_one(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    settings.set("daily_cap", 1)
    server = type("Server", (), {})()
    server.ledger = ledger
    server.settings = settings
    try:
        entry = ledger.record(
            actor="agent-desk",
            action="settings.set",
            subject="daily_cap",
            why="The cap changed.",
            undo_kind="settings-key",
            before=json.dumps({"key": "daily_cap", "value": 3}).encode(),
        )
        barrier = threading.Barrier(2)
        results: list = []
        errors: list = []

        def go() -> None:
            barrier.wait()
            try:
                results.append(undo(server, ledger, entry.id))
            except LedgerError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=go) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(results) == 1
        assert len(errors) == 1
        assert ledger.get(entry.id).undone_by == results[0].id
    finally:
        ledger.close()


def test_ask_first_never_allowed() -> None:
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    try:
        assert settings.get("autonomy") is True
        for action in ("mail.send", "data.delete", "plugin.uninstall", "plugin.install"):
            assert action in ASK_FIRST
            assert may_act(settings, action) is False
        assert may_act(settings, "deskcheck.fix") is True
        settings.set("autonomy", False)
        assert may_act(settings, "deskcheck.fix") is False
    finally:
        settings.conn.close()
