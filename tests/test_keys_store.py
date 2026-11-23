"""The keys store (spec 018): named connections in their own sqlite file.

The inbox store's pattern, asserted here the same way: an idempotent
schema step, one injectable clock, ids that never collide by construction.
The store never holds secret material: a connection carries a keychain
reference and the masked hint only, and the tests say so in bytes.
"""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain
from agentdesk.keys.store import KeysStore, UnknownConnection, mask_key

# The connections table exactly as the builds before spec 022 wrote it,
# without the model column: the shape of a keys.sqlite3 such a build left.
TABLE_BEFORE_THE_MODEL = """
CREATE TABLE connections (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL,
  base_url TEXT NOT NULL,
  keychain_ref TEXT NOT NULL DEFAULT '',
  masked_key TEXT NOT NULL DEFAULT '',
  headers TEXT NOT NULL DEFAULT '{}',
  is_default INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'unknown',
  last_checked_at REAL,
  last_error TEXT NOT NULL DEFAULT '',
  last_used_at REAL,
  models TEXT NOT NULL DEFAULT '[]',
  models_fetched_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
"""


def _saved_before_the_model_column(tmp_path: Path) -> None:
    """A keys file as an earlier build left it: one connection, no model column."""
    with closing(sqlite3.connect(tmp_path / "keys.sqlite3")) as old:
        old.executescript(TABLE_BEFORE_THE_MODEL)
        old.execute(
            "INSERT INTO connections (id, label, provider, base_url,"
            " masked_key, created_at, updated_at)"
            " VALUES ('saved-earlier', 'OpenAI personal', 'openai',"
            " 'https://api.openai.com/v1', 'sk-...9999', 1.0, 1.0)")
        old.commit()
        names = {row[1] for row in old.execute("PRAGMA table_info(connections)")}
    assert "model" not in names  # the file under test really lacks the column


class FrozenClock:
    """A clock the test moves by hand, so stamps are exactly predictable."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _open(tmp_path: Path, name: str = "keys.sqlite3"):
    conn = sqlite3.connect(tmp_path / name, check_same_thread=False)
    return conn


def test_schema_step_is_idempotent(tmp_path):
    conn = _open(tmp_path)
    KeysStore(conn, lambda: 0.0)
    KeysStore(conn, lambda: 0.0)  # the second open changes nothing
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'connections'"
    ).fetchone()
    assert row[0] == 1


def test_add_and_get_round_trip_every_field(tmp_path):
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    conn = store.add(
        label="Work gateway",
        provider="custom",
        base_url="https://llm.corp.example/v1",
        masked_key="sk-...abcd",
        headers={"X-Gateway": "yes"},
        is_default=True,
    )
    assert conn.id and conn.keychain_ref == f"key/{conn.id}"
    clock.now += 10
    read = store.get(conn.id)
    assert read.label == "Work gateway"
    assert read.provider == "custom"
    assert read.base_url == "https://llm.corp.example/v1"
    assert read.masked_key == "sk-...abcd"
    assert read.headers == {"X-Gateway": "yes"}
    assert read.is_default is True
    assert read.enabled is True
    assert read.status == "unknown"
    assert read.last_error == ""
    assert read.created_at == 1_000.0
    assert read.updated_at == 1_000.0


def test_a_connection_remembers_its_model(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    saved = store.add(label="Work gateway", provider="custom",
                      base_url="https://llm.corp.example/v1",
                      model="mock-chat")
    assert saved.model == "mock-chat"
    assert store.get(saved.id).model == "mock-chat"
    assert [c.model for c in store.all()] == ["mock-chat"]


def test_update_changes_only_the_model_it_is_given(tmp_path):
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    conn = store.add(label="One", provider="custom",
                     base_url="https://llm.corp.example/v1", model="mock-chat")
    clock.now += 5
    assert store.update(conn.id, model="mock-chat-v2").model == "mock-chat-v2"
    assert store.get(conn.id).updated_at == 1_005.0
    # A change that does not name the model leaves it alone.
    assert store.update(conn.id, label="Renamed").model == "mock-chat-v2"
    # An empty model is the "none chosen" state, stored as such.
    assert store.update(conn.id, model="").model == ""
    with pytest.raises(UnknownConnection):
        store.update("no-such-id", model="mock-chat")


def test_a_store_saved_before_the_model_column_opens_and_upgrades(tmp_path):
    _saved_before_the_model_column(tmp_path)
    conn = _open(tmp_path)
    with closing(conn):
        store = KeysStore(conn, lambda: 0.0)  # what every boot does
        earlier = store.get("saved-earlier")
        assert earlier.label == "OpenAI personal"
        assert earlier.masked_key == "sk-...9999"
        assert earlier.model == ""  # nothing saved earlier changes
        saved = store.add(label="New", provider="custom",
                          base_url="https://llm.corp.example/v1",
                          model="mock-chat")
        assert saved.model == "mock-chat"
    # The next boot opens the same file again and everything is still there.
    conn = _open(tmp_path)
    with closing(conn):
        again = KeysStore(conn, lambda: 0.0)
        assert {c.label: c.model for c in again.all()} == {
            "OpenAI personal": "", "New": "mock-chat"}


def test_labels_are_unique(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    store.add(label="OpenAI personal", provider="openai", base_url="https://api.openai.com/v1")
    with pytest.raises(ValueError):
        store.add(label="OpenAI personal", provider="openai",
                  base_url="https://api.openai.com/v1")


def test_unknown_id_is_a_named_error(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    with pytest.raises(UnknownConnection):
        store.get("no-such-id")
    with pytest.raises(UnknownConnection):
        store.update("no-such-id", label="x")
    with pytest.raises(UnknownConnection):
        store.delete("no-such-id")


def test_all_lists_oldest_first(tmp_path):
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    first = store.add(label="One", provider="openai", base_url="https://a.example/v1")
    clock.now += 1
    second = store.add(label="Two", provider="groq", base_url="https://b.example/v1")
    assert [c.id for c in store.all()] == [first.id, second.id]


def test_update_touches_only_the_named_fields(tmp_path):
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    conn = store.add(label="One", provider="openai",
                     base_url="https://api.openai.com/v1", masked_key="sk-...wwww")
    clock.now += 5
    updated = store.update(conn.id, label="Renamed",
                           base_url="https://api.openai.com/v2")
    assert updated.label == "Renamed"
    assert updated.base_url == "https://api.openai.com/v2"
    assert updated.masked_key == "sk-...wwww"  # untouched
    assert updated.updated_at == 1_005.0
    assert updated.created_at == 1_000.0  # stamps never rewrite history


def test_clear_key_empties_the_hint_only(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    conn = store.add(label="One", provider="openai",
                     base_url="https://api.openai.com/v1", masked_key="sk-...abcd")
    cleared = store.clear_key(conn.id)
    assert cleared.masked_key == ""
    assert cleared.keychain_ref == f"key/{conn.id}"  # the id stays addressable


def test_setting_a_default_unsets_the_previous_one(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    first = store.add(label="One", provider="openai",
                      base_url="https://api.openai.com/v1", is_default=True)
    second = store.add(label="Two", provider="groq", base_url="https://api.groq.com/openai/v1")
    assert store.get(first.id).is_default is True
    store.set_default(second.id)
    assert store.get(first.id).is_default is False
    assert store.get(second.id).is_default is True


def test_delete_removes_the_row(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    conn = store.add(label="One", provider="openai", base_url="https://api.openai.com/v1")
    gone = store.delete(conn.id)
    assert gone.id == conn.id
    with pytest.raises(UnknownConnection):
        store.get(conn.id)


# -- health stamps (spec 018 #232) -------------------------------------------


def test_record_check_stamps_status_note_and_time(tmp_path):
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    conn = store.add(label="One", provider="openai",
                     base_url="https://api.openai.com/v1")
    clock.now += 10
    checked = store.record_check(conn.id, status="error",
                                 note="the endpoint rejected the API key")
    assert checked.status == "error"
    assert checked.last_error == "the endpoint rejected the API key"
    assert checked.last_checked_at == 1_010.0
    # An ok check clears the note, like the badge expects.
    clock.now += 10
    checked = store.record_check(conn.id, status="ok", note="")
    assert checked.status == "ok"
    assert checked.last_error == ""
    assert checked.last_checked_at == 1_020.0


def test_record_check_with_no_status_keeps_the_last_one(tmp_path):
    """The transient mapping: a 5xx or a timeout stamps the check time
    and the note, but the status only a real answer set survives."""
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    conn = store.add(label="One", provider="openai",
                     base_url="https://api.openai.com/v1")
    clock.now += 10
    store.record_check(conn.id, status="ok", note="")
    clock.now += 10
    transient = store.record_check(conn.id, status=None,
                                   note="the endpoint failed on its own side")
    assert transient.status == "ok"  # kept
    assert transient.last_error == "the endpoint failed on its own side"
    assert transient.last_checked_at == 1_020.0
    # The unknown state keeps too: a missing listing verifies nothing.
    fresh = KeysStore(_open(tmp_path, "second.sqlite3"), lambda: 0.0)
    other = fresh.add(label="Two", provider="anthropic-compat",
                      base_url="https://api.anthropic.com/v1/")
    noted = fresh.record_check(other.id, status=None, note="no model listing")
    assert noted.status == "unknown"
    with pytest.raises(UnknownConnection):
        store.record_check("no-such-id", status="ok")


def test_record_use_stamps_only_last_used_at(tmp_path):
    """The live-traffic leg: record_use is the one write the call path
    makes, and it never claims the key was checked."""
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    conn = store.add(label="One", provider="openai",
                     base_url="https://api.openai.com/v1")
    clock.now += 10
    used = store.record_use(conn.id)
    assert used.last_used_at == 1_010.0
    assert used.last_checked_at is None
    assert used.status == "unknown"


def test_set_models_caches_the_listing_with_its_fetched_at(tmp_path):
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    conn = store.add(label="One", provider="openai",
                     base_url="https://api.openai.com/v1")
    assert store.get(conn.id).models == []
    assert store.get(conn.id).models_fetched_at is None
    clock.now += 10
    cached = store.set_models(conn.id, ["gpt-4o-mini", "gpt-4o"])
    assert cached.models == ["gpt-4o-mini", "gpt-4o"]
    assert cached.models_fetched_at == 1_010.0
    clock.now += 10
    assert store.set_models(conn.id, []).models == []  # an empty listing caches too


# -- job bindings (spec 018 #233) ------------------------------------------


def test_bind_and_read_back_every_field(tmp_path):
    clock = FrozenClock()
    store = KeysStore(_open(tmp_path), clock)
    conn = store.add(label="OpenAI personal", provider="openai",
                     base_url="https://api.openai.com/v1")
    clock.now += 10
    binding = store.bind("assistant", conn.id, "gpt-4o-mini")
    assert binding.job_key == "assistant"
    assert binding.connection_id == conn.id
    assert binding.model_id == "gpt-4o-mini"
    assert binding.updated_at == 1_010.0
    clock.now += 10
    assert store.binding("assistant").updated_at == 1_010.0  # stamps never rewrite
    assert store.binding("presentations") is None


def test_rebinding_a_job_replaces_the_earlier_binding(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    first = store.add(label="One", provider="openai",
                      base_url="https://a.example/v1")
    second = store.add(label="Two", provider="groq",
                       base_url="https://b.example/v1")
    store.bind("assistant", first.id, "m-one")
    store.bind("assistant", second.id, "m-two")
    binding = store.binding("assistant")
    assert (binding.connection_id, binding.model_id) == (second.id, "m-two")
    assert [b.job_key for b in store.bindings()] == ["assistant"]


def test_bind_refuses_an_unknown_connection(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    with pytest.raises(UnknownConnection):
        store.bind("assistant", "no-such-id", "m")


def test_bindings_list_is_job_ordered_and_unbind_removes(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    conn = store.add(label="One", provider="openai",
                     base_url="https://a.example/v1")
    store.bind("research-web", conn.id)
    store.bind("assistant", conn.id, "m")
    assert [b.job_key for b in store.bindings()] == ["assistant", "research-web"]
    assert store.unbind("assistant") is True
    assert store.binding("assistant") is None
    assert store.unbind("assistant") is False  # already gone
    assert [b.job_key for b in store.bindings()] == ["research-web"]


def test_bound_jobs_names_the_jobs_a_connection_serves(tmp_path):
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    keeper = store.add(label="One", provider="openai",
                       base_url="https://a.example/v1")
    other = store.add(label="Two", provider="groq",
                      base_url="https://b.example/v1")
    store.bind("assistant", keeper.id)
    store.bind("memory", keeper.id)
    store.bind("presentations", other.id)
    assert sorted(store.bound_jobs(keeper.id)) == ["assistant", "memory"]
    assert store.bound_jobs(other.id) == ["presentations"]


def test_deleting_a_connection_takes_its_bindings_with_it(tmp_path):
    """The cascade the schema promises, asserted without relying on
    SQLite's per-connection foreign_keys pragma: the store's own delete
    removes the bindings in the same transaction."""
    store = KeysStore(_open(tmp_path), lambda: 0.0)
    conn = store.add(label="One", provider="openai",
                     base_url="https://a.example/v1")
    store.bind("assistant", conn.id)
    store.bind("default", conn.id)
    store.delete(conn.id)
    assert store.bindings() == []
    row = _open(tmp_path).execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        " AND name = 'job_bindings'"
    ).fetchone()
    assert row[0] == 1  # the table itself survives; only the rows cascade


# -- the masking rule -------------------------------------------------------


@pytest.mark.parametrize("secret, expected", [
    ("sk-proj-abcdef1234WXYZ", "sk-...WXYZ"),   # first three, last four
    ("abcdefghijklmnopqrstuvwxyz", "abc...wxyz"),
    ("short", "Set."),                          # too short to spare the middle
    ("123456789", "Set."),
    ("", ""),
    ("   ", ""),
])
def test_mask_key_first_three_last_four(secret, expected):
    assert mask_key(secret) == expected


def test_the_mask_never_carries_the_middle(tmp_path):
    secret = "sk-middle-bytes-never-shown-9999"
    masked = mask_key(secret)
    assert "middle" not in masked and "never" not in masked
    assert masked == "sk-...9999"


def test_no_secret_material_lands_in_the_sqlite_file(tmp_path):
    secret = "sk-file-level-secret-tail-7777"
    path = tmp_path / "keys.sqlite3"
    conn = sqlite3.connect(path, check_same_thread=False)
    store = KeysStore(conn, lambda: 0.0)
    saved = store.add(label="One", provider="openai",
                      base_url="https://api.openai.com/v1",
                      masked_key=mask_key(secret))
    keychain = KeychainSecrets(MemoryKeychain())
    assert keychain.store(saved.id, secret) is True
    assert keychain.fetch(saved.id) == secret
    raw = path.read_bytes()
    # The middle and the head beyond three characters never land; the
    # masked hint itself (first three, last four) is the designed trace.
    assert b"sk-file-level" not in raw
    assert b"secret-tail" not in raw
    assert b"...7777" in raw  # the masked hint is exactly what is stored


# -- the keychain wrapper ---------------------------------------------------


def test_memory_keychain_forgets_cleanly():
    keychain = KeychainSecrets(MemoryKeychain())
    keychain.store("id-1", "secret-one")
    assert keychain.fetch("id-1") == "secret-one"
    assert keychain.forget("id-1") is True
    assert keychain.fetch("id-1") is None
    assert keychain.forget("never-there") is False


def test_one_service_name_one_username_shape():
    backend = MemoryKeychain()
    keychain = KeychainSecrets(backend)
    keychain.store("conn-9", "secret")
    assert set(backend.secrets) == {("agent-desk", "key/conn-9")}


def test_unavailable_backend_never_pretends_to_store():
    class DeadKeyring:
        """Every call fails, like a machine with no keychain at all."""

        def get_keyring(self):
            raise RuntimeError("no backend")

        def set_password(self, *_args):
            raise RuntimeError("no backend")

        def get_password(self, *_args):
            raise RuntimeError("no backend")

        def delete_password(self, *_args):
            raise RuntimeError("no backend")

    keychain = KeychainSecrets(DeadKeyring())
    assert keychain.available() is False
    assert keychain.store("id-1", "secret") is False
    assert keychain.fetch("id-1") is None
