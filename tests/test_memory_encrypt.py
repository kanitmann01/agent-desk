"""Memory encryption at rest (ticket #94): the sealed store, the open-
time binding and the one-action conversion.

The donor's shape, pinned here: sealed writes blank the plaintext
columns and keep ciphertext plus a blind index; sealed reads REQUIRE
ciphertext, so a row without one is a hard error, never a silent
plaintext fallback; a marker without a key, a wrong key, or a key
offered to a populated plaintext bank each stop with a specific cause;
the conversion dedupes and prunes first, then seals sources, entities,
facts and observations and writes the marker in one transaction, and
the key file exists before that transaction starts. Plaintext columns
of other tables (ids, kinds, timestamps, confidence) stay plaintext.
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

from agentdesk.memory import store as memory_store_module
from agentdesk.memory.crypto import CryptoBox, MemoryEncryptedError, load_key
from agentdesk.memory.store import (
    MemoryStore,
    ensure_key_file,
    key_file_path,
    write_key_file,
)


KEY = load_key(bytes(range(32)))
OTHER_KEY = load_key(bytes(range(32, 64)))


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _open(path, key=None, key_path=None) -> MemoryStore:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    return MemoryStore(conn, FakeClock(), key=key, key_path=key_path)


def _close(store: MemoryStore) -> None:
    store.conn.close()


def _raw_fact_row(store: MemoryStore) -> sqlite3.Row:
    store.conn.row_factory = sqlite3.Row
    row = store.conn.execute("SELECT * FROM facts").fetchone()
    store.conn.row_factory = None
    return row


def _marker(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'encryption'"
    ).fetchone()
    return None if row is None else str(row[0])


# -- sealed writes and reads -------------------------------------------------


def test_sealed_add_blanks_the_plaintext_and_keeps_a_blind_index():
    store = _open(":memory:", key=KEY)
    fact = store.add("Revenue is 220", source="page")
    row = _raw_fact_row(store)
    assert row["text"] == "", "the plaintext column is blanked"
    assert row["text_enc"] is not None
    assert row["text_idx"] == CryptoBox(KEY).blind("revenue is 220")
    assert fact.text == "Revenue is 220"
    assert fact.source == "page", "provenance stays plaintext"
    assert fact.created_ts == 100.0
    _close(store)


def test_sealed_get_all_and_edit_round_trip_across_a_reopen(tmp_path):
    db = tmp_path / "memory.sqlite3"
    first = _open(db, key=KEY)
    fact = first.add("Revenue is 220", source="page")
    first.edit(fact.id, "Revenue is 480")
    _close(first)
    reopened = _open(db, key=KEY)
    assert [f.text for f in reopened.all()] == ["Revenue is 480"]
    assert reopened.get(fact.id).text == "Revenue is 480"
    _close(reopened)
    with pytest.raises(MemoryEncryptedError):
        wrong = _open(db, key=OTHER_KEY)
        wrong.all()
        _close(wrong)


def test_sealed_missing_ciphertext_is_a_hard_error_never_a_fallback():
    store = _open(":memory:", key=KEY)
    fact = store.add("Revenue is 220", source="page")
    # Simulate the mixed state: a row with plaintext and no ciphertext.
    store.conn.execute("UPDATE facts SET text = 'plain again', text_enc = NULL")
    store.conn.commit()
    with pytest.raises(MemoryEncryptedError, match=r"Missing ciphertext for facts\.text"):
        store.all()
    with pytest.raises(MemoryEncryptedError, match=r"Missing ciphertext for facts\.text"):
        store.get(fact.id)
    _close(store)


def test_sealed_add_source_blanks_all_three_text_columns():
    store = _open(":memory:", key=KEY)
    source_id = store.add_source("we met Tuesday", speaker="Kanit", context="thread")
    store.conn.row_factory = sqlite3.Row
    row = store.conn.execute(
        "SELECT * FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    store.conn.row_factory = None
    assert row["text"] == "" and row["speaker"] == "" and row["context"] == ""
    assert row["text_enc"] and row["speaker_enc"] and row["context_enc"]
    assert row["created_ts"] == 100.0
    _close(store)


def test_sealed_resolve_and_link_seals_entities_and_maintains_the_index():
    store = _open(":memory:", key=KEY)
    fact = store.add("Maya joined Acme", source="page")
    refs = store.resolve_and_link(fact.id, [("Maya Rahman", "person"), ("Acme", "org")])
    assert [(r.name, r.type) for r in refs] == [
        ("Maya Rahman", "person"), ("Acme", "org"),
    ]
    store.conn.row_factory = sqlite3.Row
    rows = store.conn.execute("SELECT * FROM entities ORDER BY id").fetchall()
    store.conn.row_factory = None
    assert [(r["canonical_name"], r["aliases_json"]) for r in rows] == [("", "[]"), ("", "[]")]
    box = CryptoBox(KEY)
    assert [r["canonical_name_enc"] is not None for r in rows] == [True, True]
    assert rows[0]["name_idx"] == box.blind("maya rahman")
    assert rows[1]["name_idx"] == box.blind("acme")
    indexed = store.conn.execute(
        "SELECT entity_id, name_idx FROM entity_name_index ORDER BY entity_id"
    ).fetchall()
    assert [(r[0], r[1]) for r in indexed] == [
        (1, box.blind("maya rahman")), (2, box.blind("acme")),
    ]
    _close(store)


def test_sealed_resolution_merges_a_typo_and_syncs_the_index():
    store = _open(":memory:", key=KEY)
    first = store.add("Obermeier Lin owns the ledger", source="page")
    second = store.add("Obermeir Lin owns the ledger", source="page")
    store.resolve_and_link(first.id, [("Obermeier Lin", "person")])
    refs = store.resolve_and_link(second.id, [("Obermeir Lin", "person")])
    assert [r.id for r in refs] == [1]
    assert len(store.conn.execute("SELECT id FROM entities").fetchall()) == 1
    box = CryptoBox(KEY)
    indexed = [r[0] for r in store.conn.execute("SELECT name_idx FROM entity_name_index")]
    assert indexed == [box.blind("obermeier lin")]
    _close(store)


def test_sealed_resolution_promotes_a_longer_weak_match_into_the_index():
    store = _open(":memory:", key=KEY)
    first = store.add("Maya sent the note", source="page")
    second = store.add("Maya Rahman sent the note", source="page")
    store.resolve_and_link(first.id, [("Maya", "person")])
    refs = store.resolve_and_link(second.id, [("Maya Rahman", "person")])
    assert [(r.id, r.name) for r in refs] == [(1, "Maya Rahman")]
    box = CryptoBox(KEY)
    indexed = {r[0] for r in store.conn.execute("SELECT name_idx FROM entity_name_index")}
    # The canonical name and the demoted alias are both indexed.
    assert indexed == {box.blind("maya rahman"), box.blind("maya")}
    _close(store)


def test_sealed_recall_finds_facts_by_keyword_and_entity():
    store = _open(":memory:", key=KEY)
    fact = store.add("the board approved the budget", source="page")
    other = store.add("revenue is 220", source="page")
    store.resolve_and_link(fact.id, [("Acme", "org")])
    assert [f.id for _s, f in store.recall("revenue")] == [other.id]
    # The graph leg rides decrypted entity names.
    assert [f.id for _s, f in store.recall("acme")] == [fact.id]
    _close(store)


def test_a_duplicate_add_reuses_the_row_in_both_modes():
    # Ticket #92 deliberately updates this pin (it replaced #94's pin
    # that a duplicate add creates a second row): write-time dedup gates
    # every write now, on a plaintext bank by the scan and on a sealed
    # bank through the text_idx blind lookup with a decrypt-verify
    # second, so a normalized duplicate reuses the existing row in both
    # modes and no second row appears.
    plain = _open(":memory:")
    first = plain.add("Revenue is 220", source="page")
    again = plain.add("  revenue\tis 220 ", source="page")
    assert again.id == first.id
    assert len(plain.all()) == 1
    sealed = _open(":memory:", key=KEY)
    sealed_first = sealed.add("Revenue is 220", source="page")
    sealed_again = sealed.add("  revenue\tis 220 ", source="page")
    assert sealed_again.id == sealed_first.id
    assert len(sealed.all()) == 1
    box = CryptoBox(KEY)
    idx = [r[0] for r in sealed.conn.execute(
        "SELECT text_idx FROM facts ORDER BY id"
    )]
    assert idx == [box.blind("revenue is 220")]
    _close(plain)
    _close(sealed)


# -- hygiene parity (ticket #92) -----------------------------------------------


def test_sealed_write_time_dedup_parity():
    # The plaintext dedup story over a sealed bank: the duplicate rides
    # the blind index (no plaintext is compared), the row is reused,
    # the null occurrence is backfilled, and nothing plaintext lands on
    # disk.
    store = _open(":memory:", key=KEY)
    first = store.add("Revenue is 220", source="page")
    assert first.occurrence_ts is None
    again = store.add(
        "  revenue   is 220 ", source="inbox card 3", occurrence_ts=1700000000.0
    )
    assert again.id == first.id
    facts = store.all()
    assert len(facts) == 1
    assert facts[0].text == "Revenue is 220", "the stored text wins"
    assert facts[0].source == "page", "the existing provenance stays"
    assert facts[0].occurrence_ts == 1700000000.0
    row = _raw_fact_row(store)
    assert row["text"] == "" and row["text_enc"] is not None
    _close(store)


def test_sealed_edit_merge_parity():
    # The edit merge over a sealed bank: mentions move, the null
    # occurrence is backfilled, the edited row goes, and every answer
    # comes back through decryption.
    store = _open(":memory:", key=KEY)
    kept = store.add("Revenue is 220", source="page")
    store.resolve_and_link(kept.id, [("Acme", "org")])
    store.clock.advance(5.0)
    edited = store.add("meeting room booked", source="page", occurrence_ts=1700000000.0)
    store.resolve_and_link(edited.id, [("Maya", "person")])
    result = store.edit(edited.id, "  revenue   is 220 ")
    assert result.merged_into is True
    assert result.fact.id == kept.id
    facts = store.all()
    assert [f.id for f in facts] == [kept.id]
    assert facts[0].text == "Revenue is 220"
    assert facts[0].occurrence_ts == 1700000000.0
    # Both entities now hang off the survivor, readable by name.
    assert [f.id for _s, f in store.recall("acme")] == [kept.id]
    assert [f.id for _s, f in store.recall("maya")] == [kept.id]
    raw_edges = store.conn.execute(
        "SELECT fact_id, entity_id FROM edges ORDER BY 1"
    ).fetchall()
    assert raw_edges == [(kept.id, 1), (kept.id, 2)]
    _close(store)


def test_sealed_sweep_and_entity_merge_parity():
    # The sweep and the entity merge read decrypted text and write no
    # plaintext anywhere: candidates classify over ciphertext, the
    # delete prunes orphans, and the merged survivor's names re-seal
    # with a rebuilt name index.
    store = _open(":memory:", key=KEY)
    junk = store.add("I do not have any information about that.", source="page")
    store.resolve_and_link(junk.id, [("Nothing Inc", "org")])
    real = store.add("revenue is 220", source="page")
    store.resolve_and_link(real.id, [("Acme", "org")])
    other = store.add("Globex shipped the widget", source="page")
    store.resolve_and_link(other.id, [("Globex", "org")])
    candidates = {c.fact.id: c.reason for c in store.sweep_candidates()}
    assert candidates == {junk.id: "knowledge-gap"}
    removed = store.remove_facts([junk.id])
    assert removed.fact_ids == (junk.id,)
    assert removed.entity_ids == (1,), "the entity the junk alone mentioned went too"
    assert [f.id for f in store.all()] == [real.id, other.id]
    # The surviving entity keeps its blind index rows; only the removed
    # entity's go.
    box = CryptoBox(KEY)
    surviving_index = store.conn.execute(
        "SELECT name_idx FROM entity_name_index WHERE entity_id = 2"
    ).fetchall()
    assert [r[0] for r in surviving_index] == [box.blind("acme")]
    survivor = store.merge_entities(2, 3)
    assert survivor.canonical_name == "Acme"
    assert survivor.aliases == ("Globex",)
    indexed = store.conn.execute(
        "SELECT name_idx FROM entity_name_index"
    ).fetchall()
    box = CryptoBox(KEY)
    assert {r[0] for r in indexed} == {box.blind("acme"), box.blind("globex")}
    # Sealed reads still answer; nothing plaintext was ever written.
    # Recency puts the newer fact first.
    assert [f.id for _s, f in store.recall("globex")] == [other.id, real.id]
    _close(store)


def test_sealed_plaintext_tables_stay_plaintext():
    store = _open(":memory:", key=KEY)
    fact = store.add("launch was friday", kind="experience", occurrence_ts=1700000000.0)
    store.resolve_and_link(fact.id, [("Acme", "org")])
    row = _raw_fact_row(store)
    assert row["kind"] == "experience" and row["occurrence_ts"] == 1700000000.0
    edge = store.conn.execute("SELECT fact_id, entity_id FROM edges").fetchone()
    assert edge == (fact.id, 1)
    _close(store)


# -- open-time binding --------------------------------------------------------


def test_a_marker_without_a_key_locks_with_the_missing_key_cause(tmp_path):
    db = tmp_path / "memory.sqlite3"
    seeded = _open(db, key=KEY)
    seeded.add("Revenue is 220", source="page")
    _close(seeded)
    locked = _open(db, key_path=tmp_path / "memory.key")
    assert locked.locked_cause is not None
    assert "encrypted" in locked.locked_cause
    assert str(tmp_path / "memory.key") in locked.locked_cause
    assert locked.is_sealed is False
    with pytest.raises(MemoryEncryptedError, match=r"key file is missing"):
        locked.all()
    with pytest.raises(MemoryEncryptedError, match=r"key file is missing"):
        locked.add("x")
    _close(locked)


def test_a_wrong_key_locks_with_the_wrong_key_cause(tmp_path):
    db = tmp_path / "memory.sqlite3"
    seeded = _open(db, key=KEY)
    seeded.add("Revenue is 220", source="page")
    _close(seeded)
    locked = _open(db, key=OTHER_KEY)
    assert locked.locked_cause == "Wrong encryption key."
    with pytest.raises(MemoryEncryptedError, match=r"Wrong encryption key"):
        locked.all()
    _close(locked)


def test_a_key_offered_to_a_populated_plaintext_bank_is_refused(tmp_path):
    db = tmp_path / "memory.sqlite3"
    plain = _open(db)
    plain.add("Revenue is 220", source="page")
    _close(plain)
    refused = _open(db, key=KEY)
    assert refused.locked_cause is not None
    assert "not encrypted" in refused.locked_cause
    assert "encryption action" in refused.locked_cause
    with pytest.raises(MemoryEncryptedError, match=r"encryption action"):
        refused.all()
    _close(refused)
    # The bank itself is untouched plaintext.
    survivor = _open(db)
    assert survivor.all()[0].text == "Revenue is 220"
    _close(survivor)


def test_a_key_on_an_empty_fresh_database_initializes_sealed(tmp_path):
    db = tmp_path / "memory.sqlite3"
    store = _open(db, key=KEY)
    assert store.is_sealed is True
    assert _marker(store.conn) is not None, "the marker is written immediately"
    fact = store.add("Revenue is 220", source="page")
    row = _raw_fact_row(store)
    assert row["text"] == "" and row["text_enc"] is not None
    _close(store)
    reopened = _open(db, key=KEY)
    assert reopened.get(fact.id).text == "Revenue is 220"
    _close(reopened)


def test_a_locked_store_refuses_every_operation(tmp_path):
    db = tmp_path / "memory.sqlite3"
    seeded = _open(db, key=KEY)
    seeded.add("Revenue is 220", source="page")
    _close(seeded)
    locked = _open(db, key_path=tmp_path / "memory.key")
    cause = locked.locked_cause
    assert cause
    operations = [
        lambda: locked.all(),
        lambda: locked.get(1),
        lambda: locked.add("x"),
        lambda: locked.edit(1, "x"),
        lambda: locked.delete(1),
        lambda: locked.add_source("x"),
        lambda: locked.resolve_and_link(1, []),
        lambda: locked.recall("x"),
        lambda: locked.plain_field_counts(),
        lambda: locked.encrypt_all(),
    ]
    for operation in operations:
        with pytest.raises(MemoryEncryptedError) as exc:
            operation()
        assert str(exc.value) == cause
    _close(locked)


def test_an_unsealed_store_reports_no_lock_and_no_seal():
    store = _open(":memory:")
    store.add("Revenue is 220", source="page")
    assert store.locked_cause is None
    assert store.is_sealed is False
    _close(store)


# -- the key file -------------------------------------------------------------


def test_key_file_path_sits_in_the_data_directory(tmp_path):
    assert key_file_path(tmp_path) == tmp_path / "memory.key"


def test_write_key_file_creates_32_random_bytes_and_refuses_to_overwrite(tmp_path):
    path = tmp_path / "memory.key"
    first = write_key_file(path)
    assert len(first) == 32
    second = write_key_file(tmp_path / "other.key")
    assert second != first, "every key is freshly random"
    with pytest.raises(FileExistsError):
        write_key_file(path)


def test_ensure_key_file_creates_once_then_reads_the_same_key(tmp_path):
    path = tmp_path / "memory.key"
    first = ensure_key_file(path)
    assert len(first) == 32
    assert ensure_key_file(path) == first


def test_key_file_permissions_are_user_only_where_the_platform_honors_it(tmp_path):
    import os
    import stat
    path = tmp_path / "memory.key"
    write_key_file(path)
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode & 0o077 == 0, f"the key file must be user-only, got {oct(mode)}"
    # Windows: the os.open mode's permission bits are best-effort (the
    # C runtime maps only the write bit); a recorded divergence, the file
    # inherits the user profile's ACLs.


# -- the conversion -----------------------------------------------------------


def _plaintext_bank(path, key_path=None) -> MemoryStore:
    store = _open(path, key_path=key_path)
    first = store.add("Revenue is 220", source="page")
    # Ticket #92: a normalized duplicate no longer inserts a row, so
    # the fixture's doomed fact is a distinct one (write-time dedup
    # only changes which text is used here, not the orphan shape).
    spare = store.add("quarterly numbers pending review", source="inbox card 3")
    meeting = store.add("the meeting room is booked", source="page")
    store.add_source("we met Tuesday", speaker="Kanit", context="thread")
    store.resolve_and_link(first.id, [("Acme", "org")])
    store.resolve_and_link(meeting.id, [("Maya Rahman", "person")])
    # A pre-reflect observation with its citation, and an orphan pair: a
    # citation whose fact is gone and an observation left with none.
    store.conn.execute(
        "INSERT INTO observations (scope_key, text, confidence, created_ts, updated_ts)"
        " VALUES ('all', 'Money matters recur in every meeting.', 0.9, 100.0, 100.0)"
    )
    store.conn.execute(
        "INSERT INTO observation_sources (observation_id, fact_id) VALUES (1, ?)",
        (first.id,),
    )
    store.conn.execute(
        "INSERT INTO observations (scope_key, text, confidence, created_ts, updated_ts)"
        " VALUES ('all', 'Orphaned pattern.', 0.5, 100.0, 100.0)"
    )
    store.conn.execute(
        "INSERT INTO observation_sources (observation_id, fact_id) VALUES (2, ?)",
        (spare.id,),
    )
    # The orphan state the prune step exists to fix: the fact is gone
    # but its citation and observation remain. Foreign keys would block
    # the delete on a live connection, so the fixture drops them exactly
    # the way an interrupted write (or a pre-guard database) would leave
    # them, then hands the store back with enforcement restored. The
    # pragma is a no-op inside a transaction, hence the commits.
    store.conn.commit()
    store.conn.execute("PRAGMA foreign_keys = OFF")
    store.conn.execute("DELETE FROM facts WHERE id = ?", (spare.id,))
    store.conn.commit()
    store.conn.execute("PRAGMA foreign_keys = ON")
    store.conn.commit()
    return store


def test_dry_run_counts_fields_per_table():
    store = _plaintext_bank(":memory:")
    counts = store.plain_field_counts()
    # facts: 2 rows; sources: text + speaker + context; entities: 2 rows
    # with no aliases; observations: 2 rows.
    assert counts == {"facts": 2, "sources": 3, "entities": 2, "observations": 2}
    assert store.encrypt_all(dry_run=True) == {
        "dry_run": True, "fields": 9,
    }
    # A dry run writes nothing.
    assert _marker(store.conn) is None
    row = store.conn.execute("SELECT text FROM facts WHERE id = 1").fetchone()
    assert row[0] == "Revenue is 220"
    _close(store)


def test_encrypt_all_seals_the_bank_and_a_reopen_reads_identically(tmp_path):
    db = tmp_path / "memory.sqlite3"
    store = _plaintext_bank(db)
    before_texts = [f.text for f in store.all()]
    result = store.encrypt_all(KEY)
    # The conversion counts after its dedupe and prune: the uncited
    # observation is gone, so one field fewer than the dry run saw.
    assert result["fields"] == 8
    assert _marker(store.conn) is not None
    assert store.is_sealed is True
    # The running store reads its own conversion immediately.
    assert [f.text for f in store.all()] == before_texts
    _close(store)

    reopened = _open(db, key=KEY)
    assert [f.text for f in reopened.all()] == [
        "Revenue is 220", "the meeting room is booked",
    ]
    assert reopened.recall("revenue")[0][1].text == "Revenue is 220"
    assert reopened.recall("acme")[0][1].text == "Revenue is 220"
    # Resolution still merges a typo over the encrypted bank.
    third = reopened.add("Obermeier Lin owns the ledger", source="page")
    reopened.resolve_and_link(third.id, [("Obermeier Lin", "person")])
    fourth = reopened.add("Obermeir Lin owns the ledger", source="page")
    refs = reopened.resolve_and_link(fourth.id, [("Obermeir Lin", "person")])
    assert len({r.id for r in refs}) == 1

    # Raw bytes: the fact texts, entity names and source text are gone
    # from the file. The base64/hex encodings make accidental substring
    # presence vanishingly unlikely.
    raw = Path(db).read_bytes()
    for secret in ("Revenue is 220", "the meeting room is booked",
                   "we met Tuesday", "Maya Rahman", "Acme",
                   "Money matters recur"):
        assert secret.encode("utf-8") not in raw, secret
    _close(reopened)


def test_encrypt_all_twice_reports_already_encrypted_and_changes_nothing(tmp_path):
    db = tmp_path / "memory.sqlite3"
    store = _plaintext_bank(db)
    store.encrypt_all(KEY)
    facts_before = store.all()
    marker_before = _marker(store.conn)
    with pytest.raises(MemoryEncryptedError, match=r"already encrypted"):
        store.encrypt_all(KEY)
    assert store.all() == facts_before
    assert _marker(store.conn) == marker_before
    _close(store)
    reopened = _open(db, key=KEY)
    assert len(reopened.all()) == 2
    _close(reopened)


def test_encrypt_all_dedupes_and_prunes_before_sealing(tmp_path):
    db = tmp_path / "memory.sqlite3"
    store = _plaintext_bank(db)
    # A duplicate of fact 1 that predates ticket #92 (a row an older
    # build or a foreign writer left behind): write-time dedup would
    # refuse it at add() today, and the conversion's own pre-step still
    # merges such rows before sealing. The newer duplicate has no edges
    # or citations, so the plain-DELETE pre-step keeps the older keeper.
    store.conn.execute(
        "INSERT INTO facts (text, source, created_ts)"
        " VALUES ('revenue is 220', 'page', 110.0)"
    )
    store.conn.commit()
    store.encrypt_all(KEY)
    reopened = _open(db, key=KEY)
    texts = [f.text for f in reopened.all()]
    assert texts.count("Revenue is 220") == 1, texts
    conn = reopened.conn
    # Orphan citations and uncited observations are gone.
    citations = conn.execute(
        "SELECT observation_id, fact_id FROM observation_sources ORDER BY 1"
    ).fetchall()
    survivors = conn.execute("SELECT id FROM observations ORDER BY id").fetchall()
    assert [r[0] for r in survivors] == [1]
    assert citations == [(1, reopened.all()[0].id)]
    _close(reopened)


def test_a_seal_failure_partway_rolls_back_to_a_valid_plaintext_bank(tmp_path):
    db = tmp_path / "memory.sqlite3"
    store = _plaintext_bank(db)
    real_seal = CryptoBox.seal

    def failing_seal(self, value, table, column, row_id):
        if table == "observations":
            raise RuntimeError("injected seal failure")
        return real_seal(self, value, table, column, row_id)

    monkey_box = type("MonkeyBox", (CryptoBox,), {"seal": failing_seal})
    original = memory_store_module.CryptoBox
    memory_store_module.CryptoBox = monkey_box
    try:
        with pytest.raises(RuntimeError, match=r"injected seal failure"):
            store.encrypt_all(KEY)
    finally:
        memory_store_module.CryptoBox = original
    # The rollback left a valid plaintext bank: no marker, every text
    # readable, the store usable for another conversion.
    assert _marker(store.conn) is None
    assert [f.text for f in store.all()] == [
        "Revenue is 220", "the meeting room is booked",
    ]
    store.add("still works", source="page")
    assert store.plain_field_counts()["facts"] == 3
    _close(store)


def test_encrypt_all_creates_the_key_file_before_the_transaction(tmp_path):
    db = tmp_path / "memory.sqlite3"
    key_path = tmp_path / "memory.key"
    store = _plaintext_bank(db, key_path=key_path)
    real_write_marker = MemoryStore._write_marker

    def failing_marker(self, key):
        raise RuntimeError("injected marker failure")

    MemoryStore._write_marker = failing_marker
    try:
        with pytest.raises(RuntimeError, match=r"injected marker failure"):
            store.encrypt_all()
    finally:
        MemoryStore._write_marker = real_write_marker
    # The key file already exists: a crash after the transaction could
    # never orphan an encrypted database without its key.
    key = ensure_key_file(key_path)
    assert len(key) == 32
    # The bank is still plaintext and converts with that very key.
    result = store.encrypt_all()
    assert result["fields"] > 0
    _close(store)
    reopened = _open(db, key=key)
    assert reopened.all()[0].text == "Revenue is 220"
    _close(reopened)


def test_encrypt_all_without_a_key_or_a_key_path_is_a_value_error():
    store = _plaintext_bank(":memory:")
    with pytest.raises(ValueError, match=r"key"):
        store.encrypt_all()
    _close(store)


# -- observations over a sealed bank (ticket #93) ------------------------------


def test_sealed_save_observation_blanks_the_plaintext_and_keeps_the_blinds():
    store = _open(":memory:", key=KEY)
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    saved = store.save_observation(
        "topic: acme", "Maya moved on from Acme", 0.9, (left.id, right.id),
        now=500.0,
    )
    store.conn.row_factory = sqlite3.Row
    row = store.conn.execute(
        "SELECT * FROM observations WHERE id = ?", (saved.observation.id,)
    ).fetchone()
    store.conn.row_factory = None
    assert row["text"] == "", "the plaintext column is blanked"
    assert row["text_enc"] is not None
    assert row["text_idx"] == CryptoBox(KEY).blind("maya moved on from acme")
    assert row["scope_key"] == CryptoBox(KEY).blind("topic: acme")
    assert row["confidence"] == 0.9, "confidence stays plaintext"
    assert saved.observation.text == "Maya moved on from Acme"
    assert saved.observation.fact_ids == (left.id, right.id)
    _close(store)


def test_sealed_save_observation_upserts_through_the_blind_index():
    store = _open(":memory:", key=KEY)
    left = store.add("Maya left Acme")
    first = store.save_observation(
        "scope", "Maya moved on", 0.8, (left.id,), now=500.0
    )
    again = store.save_observation(
        "scope", "  MAYA   moved on ", 0.95, (left.id,), now=600.0
    )
    assert again.observation.id == first.observation.id
    assert again.observation.confidence == 0.95
    assert again.observation.created_ts == 500.0
    assert [o.text for o in store.observations()] == ["MAYA   moved on"]
    _close(store)


def test_sealed_observations_read_back_across_a_reopen(tmp_path):
    db = tmp_path / "memory.sqlite3"
    first = _open(db, key=KEY)
    left = first.add("Maya left Acme")
    saved = first.save_observation("scope", "Maya moved on", 0.9, (left.id,), now=5.0)
    _close(first)
    reopened = _open(db, key=KEY)
    assert [o.text for o in reopened.observations()] == ["Maya moved on"]
    assert reopened.observations()[0].fact_ids == (left.id,)
    assert reopened.observations()[0].id == saved.observation.id
    _close(reopened)


def test_sealed_observations_demand_ciphertext_never_a_fallback():
    store = _open(":memory:", key=KEY)
    left = store.add("Maya left Acme")
    store.save_observation("scope", "Maya moved on", 0.9, (left.id,), now=5.0)
    store.conn.execute("UPDATE observations SET text = 'plain again', text_enc = NULL")
    store.conn.commit()
    with pytest.raises(
        MemoryEncryptedError, match=r"Missing ciphertext for observations\.text"
    ):
        store.observations()
    _close(store)


def test_a_conversion_seals_existing_observations_and_post_conversion_writes_seal_too(
    tmp_path,
):
    db = tmp_path / "memory.sqlite3"
    key_path = tmp_path / "memory.key"
    first = _open(db, key_path=key_path)
    left = first.add("Maya left Acme")
    first.save_observation("scope", "Written while plaintext", 0.9, (left.id,), now=5.0)
    assert first.encrypt_all() == {"fields": 2}
    assert first.is_sealed
    # A row written AFTER the conversion seals exactly like the rest.
    right = first.add("Acme ships widgets")
    saved = first.save_observation(
        "scope", "Written while sealed", 0.8, (right.id,), now=6.0
    )
    first.conn.row_factory = sqlite3.Row
    rows = first.conn.execute("SELECT * FROM observations ORDER BY id").fetchall()
    first.conn.row_factory = None
    assert len(rows) == 2
    for row in rows:
        assert row["text"] == ""
        assert row["text_enc"] is not None
        assert row["text_idx"] is not None
    assert saved.observation.text == "Written while sealed"
    _close(first)
    reopened = _open(db, key=load_key(key_path.read_bytes()))
    assert sorted(o.text for o in reopened.observations()) == [
        "Written while plaintext",
        "Written while sealed",
    ]
    _close(reopened)


def test_sealed_observation_pruning_follows_fact_deletion():
    store = _open(":memory:", key=KEY)
    left = store.add("Maya left Acme")
    right = store.add("Acme ships widgets")
    store.save_observation("scope", "Maya moved on", 0.9, (left.id, right.id), now=5.0)
    store.delete(left.id)
    assert [o.fact_ids for o in store.observations()] == [(right.id,)]
    store.delete(right.id)
    assert store.observations() == []
    _close(store)
