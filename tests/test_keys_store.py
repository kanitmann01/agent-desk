"""The keys store (spec 018): named connections in their own sqlite file.

The inbox store's pattern, asserted here the same way: an idempotent
schema step, one injectable clock, ids that never collide by construction.
The store never holds secret material: a connection carries a keychain
reference and the masked hint only, and the tests say so in bytes.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain
from agentdesk.keys.store import KeysStore, UnknownConnection, mask_key


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
