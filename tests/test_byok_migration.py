"""Legacy migration and form retirement through the real HTTP seam
(spec 018, ticket #234).

Every test here boots the harness on a data directory whose settings
sqlite carries the pre-upgrade rows (seeded by raw SQL, the shape the
old version left behind), with file-backed connections and settings
stores and the in-memory fake keychain standing in for the OS keychain.
A boot is a restart in miniature: the files and the fake keychain
persist across two boots, and the stores are re-opened, so the
delete-then-restart recovery loop is exercised for real.
"""

import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.keys import migrate
from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain
from agentdesk.keys.store import KeysStore
from agentdesk.settings import SettingsStore

ENDPOINT_KEY = "sk-live-quietly-aaaaaaaaaaaaaaaa-9999"
RESEARCH_KEY = "rk-live-quietly-bbbbbbbbbbbbbbbb-4444"
LEGACY_BASE = "https://llm.corp.example/v1"
LEGACY_MODEL = "corp-model-8"
LEGACY_RESEARCH_URL = "https://research.corp.example/v1"
LEGACY_ROWS = {
    "llm_base": LEGACY_BASE,
    "llm_key": ENDPOINT_KEY,
    "llm_model": LEGACY_MODEL,
    "research_provider_url": LEGACY_RESEARCH_URL,
    "research_provider_key": RESEARCH_KEY,
}


class DeadKeychain:
    """A keyring-shaped backend with no keychain behind it, ever."""

    def get_keyring(self):
        raise RuntimeError("no backend on this machine")

    def set_password(self, *_args):
        raise RuntimeError("no backend on this machine")

    def get_password(self, *_args):
        raise RuntimeError("no backend on this machine")

    def delete_password(self, *_args):
        raise RuntimeError("no backend on this machine")


def _seed_data_dir(data_dir: Path) -> Path:
    """One data directory whose settings table carries the legacy rows,
    written by raw SQL exactly as the pre-upgrade version left them."""
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "settings.sqlite3")
    try:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS settings"
            " (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
        conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?)",
                         list(LEGACY_ROWS.items()))
        conn.commit()
    finally:
        conn.close()
    return data_dir / "settings.sqlite3"


def _boot(data_dir: Path, keychain):
    """One boot over the data directory's files: fresh store connections
    to the same sqlite files, the same fake keychain across boots."""
    settings = SettingsStore(
        sqlite3.connect(data_dir / "settings.sqlite3", check_same_thread=False),
        time.time)
    keys = KeysStore(
        sqlite3.connect(data_dir / "keys.sqlite3", check_same_thread=False),
        time.time)
    return server_harness.Booted(settings_store=settings, keys_store=keys,
                                 keychain=KeychainSecrets(keychain))


def _raw_setting(settings_path: Path, key: str):
    """One settings row read by raw SQL, outside every store."""
    conn = sqlite3.connect(settings_path)
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


def _listing(booted, auth) -> dict:
    return {c["label"]: c for c in json.loads(
        booted.request("GET", "/api/connections", auth)[2])["connections"]}


def _bindings(booted, auth) -> dict:
    return {b["job"]: b for b in json.loads(
        booted.request("GET", "/api/bindings", auth)[2])["bindings"]}


def _delete(booted, auth, connection_id, confirm=False):
    body = {"confirm": True} if confirm else {}
    return booted.post_json(f"/api/connections/{connection_id}/delete", body, auth)


# -- the upgrade: legacy rows in, migrated connections out --------------------


def test_legacy_rows_become_migrated_connections_with_bound_jobs_and_the_key_out_of_the_database(tmp_path):
    settings_path = _seed_data_dir(tmp_path / "data")
    keychain = MemoryKeychain()
    booted = _boot(tmp_path / "data", keychain)
    try:
        auth = booted.exchange()
        listing = json.loads(booted.request("GET", "/api/connections", auth)[2])
        assert listing["keychainAvailable"] is True
        by_label = {c["label"]: c for c in listing["connections"]}
        assert set(by_label) == {"Migrated endpoint", "Migrated research provider"}
        endpoint = by_label["Migrated endpoint"]
        research = by_label["Migrated research provider"]
        # The stable ids are what re-link the keychain entry after a delete.
        assert endpoint["id"] == "migrated-endpoint"
        assert research["id"] == "migrated-research"
        assert endpoint["provider"] == "custom" and research["provider"] == "custom"
        assert endpoint["baseUrl"] == LEGACY_BASE
        assert research["baseUrl"] == LEGACY_RESEARCH_URL
        assert endpoint["enabled"] is True and research["enabled"] is True
        assert endpoint["isDefault"] is True and research["isDefault"] is False
        # The masked hint is the moved key's first three and last four.
        assert endpoint["maskedKey"] == "sk-...9999"
        assert research["maskedKey"] == "rk-...4444"

        by_job = _bindings(booted, auth)
        assert by_job["default"]["connectionId"] == "migrated-endpoint"
        assert by_job["default"]["model"] == LEGACY_MODEL
        assert by_job["research-web"]["connectionId"] == "migrated-research"
        assert set(by_job) == {"default", "research-web"}

        # Raw SQL on the settings sqlite: the secrets left, the fallback
        # rows (base, model, research URL) stayed.
        assert _raw_setting(settings_path, "llm_key") == ""
        assert _raw_setting(settings_path, "research_provider_key") == ""
        assert _raw_setting(settings_path, "llm_base") == LEGACY_BASE
        assert _raw_setting(settings_path, "llm_model") == LEGACY_MODEL
        assert _raw_setting(settings_path, "research_provider_url") == LEGACY_RESEARCH_URL

        # The fake keyring holds both secrets under the spec's shape.
        assert keychain.secrets == {
            ("agent-desk", "key/migrated-endpoint"): ENDPOINT_KEY,
            ("agent-desk", "key/migrated-research"): RESEARCH_KEY,
        }
        # The audit trail names the lifecycle and carries no secret.
        entries = json.loads(booted.request("GET", "/audit/tail", auth)[2])["entries"]
        creates = {e["target"] for e in entries if e["action"] == "keys.create"}
        assert creates == {"migrated-endpoint", "migrated-research"}
        assert ENDPOINT_KEY not in json.dumps(entries)
        assert RESEARCH_KEY not in json.dumps(entries)
    finally:
        booted.close()


def test_a_second_boot_creates_no_duplicates_and_changes_nothing(tmp_path):
    _seed_data_dir(tmp_path / "data")
    keychain = MemoryKeychain()
    booted = _boot(tmp_path / "data", keychain)
    try:
        auth = booted.exchange()
        first = (booted.request("GET", "/api/connections", auth)[2],
                 booted.request("GET", "/api/bindings", auth)[2])
        rows_first = {key: _raw_setting(tmp_path / "data" / "settings.sqlite3", key)
                      for key in LEGACY_ROWS}
    finally:
        booted.close()

    booted = _boot(tmp_path / "data", keychain)
    try:
        auth = booted.exchange()
        second = (booted.request("GET", "/api/connections", auth)[2],
                  booted.request("GET", "/api/bindings", auth)[2])
        rows_second = {key: _raw_setting(tmp_path / "data" / "settings.sqlite3", key)
                       for key in LEGACY_ROWS}
        assert second == first
        assert rows_second == rows_first
        assert keychain.secrets == {
            ("agent-desk", "key/migrated-endpoint"): ENDPOINT_KEY,
            ("agent-desk", "key/migrated-research"): RESEARCH_KEY,
        }
    finally:
        booted.close()


# -- the delete-then-restart recovery loop --------------------------------------


def test_deleting_the_migrated_connections_keeps_the_keys_and_the_next_boot_restores_them(tmp_path):
    _seed_data_dir(tmp_path / "data")
    keychain = MemoryKeychain()
    booted = _boot(tmp_path / "data", keychain)
    try:
        auth = booted.exchange()
        # The first post names the jobs and the recovery instead of deleting.
        status, _h, body = _delete(booted, auth, "migrated-endpoint")
        assert status == 409
        payload = json.loads(body)
        assert payload["boundJobs"] == ["default"]
        assert "keychain" in payload["error"] and "next start" in payload["error"]
        status, _h, _b = _delete(booted, auth, "migrated-endpoint", confirm=True)
        assert status == 200
        status, _h, _b = _delete(booted, auth, "migrated-research", confirm=True)
        assert status == 200
        # Within this boot the connections are gone, but the keys stayed
        # in the keychain and the settings database is still secret-free.
        assert _listing(booted, auth) == {}
        assert keychain.secrets == {
            ("agent-desk", "key/migrated-endpoint"): ENDPOINT_KEY,
            ("agent-desk", "key/migrated-research"): RESEARCH_KEY,
        }
        assert _raw_setting(tmp_path / "data" / "settings.sqlite3", "llm_key") == ""
    finally:
        booted.close()

    # The next boot: the migration step sees the legacy rows with no live
    # migrated connection and puts both back. Nothing was retyped.
    booted = _boot(tmp_path / "data", keychain)
    try:
        auth = booted.exchange()
        by_label = _listing(booted, auth)
        assert by_label["Migrated endpoint"]["id"] == "migrated-endpoint"
        assert by_label["Migrated endpoint"]["maskedKey"] == "sk-...9999"
        assert by_label["Migrated endpoint"]["isDefault"] is True
        assert by_label["Migrated research provider"]["maskedKey"] == "rk-...4444"
        by_job = _bindings(booted, auth)
        assert by_job["default"]["connectionId"] == "migrated-endpoint"
        assert by_job["research-web"]["connectionId"] == "migrated-research"
        assert keychain.secrets == {
            ("agent-desk", "key/migrated-endpoint"): ENDPOINT_KEY,
            ("agent-desk", "key/migrated-research"): RESEARCH_KEY,
        }
        assert _raw_setting(tmp_path / "data" / "settings.sqlite3", "llm_key") == ""
    finally:
        booted.close()


def test_the_no_js_delete_confirmation_for_a_migrated_connection_names_the_restart_recovery(tmp_path):
    _seed_data_dir(tmp_path / "data")
    keychain = MemoryKeychain()
    booted = _boot(tmp_path / "data", keychain)
    try:
        auth = booted.exchange()
        data = b"confirm="
        status, _h, body = booted.request(
            "POST", "/api/connections/migrated-endpoint/delete",
            {**auth, "Content-Type": "application/x-www-form-urlencoded",
             "Content-Length": str(len(data))}, data)
        assert status == 200
        page = body.decode("utf-8")
        assert "came from the upgrade migration" in page
        assert "key stays in this machine's keychain" in page
        assert "puts the connection back" in page
        # The whole migrated consequence paragraph, pinned verbatim
        # (spec 019 #258): every fragment join keeps its space, so a
        # dropped join space anywhere in the paragraph fails the pin.
        assert (
            "<p><b>Migrated endpoint</b> came from the upgrade migration"
            " (the legacy endpoint rows). Deleting it removes the"
            " connection and those bindings, but the key stays in this"
            " machine's keychain, and on the next start the migration step"
            " sees the legacy rows and puts the connection back with its"
            " key and its jobs: nothing needs retyping. The jobs you left"
            " bound to your own connections stay exactly as they"
            " are.</p>"
        ) in page
        for run_on in ("thosebindings", "ownconnections", "jobs:nothing",
                       "andputs"):
            assert run_on not in page, run_on
        assert "action='/api/connections/migrated-endpoint/delete'" in page
        assert "name='confirm'" in page
        # The warning answered, nothing landed yet.
        assert "Migrated endpoint" in _listing(booted, auth)
    finally:
        booted.close()


def test_a_connection_the_user_bound_between_boots_keeps_its_star_and_its_jobs(tmp_path):
    _seed_data_dir(tmp_path / "data")
    keychain = MemoryKeychain()
    booted = _boot(tmp_path / "data", keychain)
    try:
        auth = booted.exchange()
        status, _h, _b = _delete(booted, auth, "migrated-endpoint", confirm=True)
        assert status == 200
        # The user moves on: a local connection needs no key and no keychain.
        status, _h, body = booted.post_json("/api/connections", {
            "label": "Own box", "provider": "ollama",
            "baseUrl": "http://localhost:11434/v1", "isDefault": "1",
        }, auth)
        assert status == 201, body
        own_id = json.loads(body)["id"]
        status, _h, _b = booted.post_json("/api/bindings", {
            "job": "default", "connectionId": own_id, "model": "own-model",
        }, auth)
        assert status == 200
    finally:
        booted.close()

    booted = _boot(tmp_path / "data", keychain)
    try:
        auth = booted.exchange()
        by_label = _listing(booted, auth)
        # The recovery still puts the migrated endpoint back with its key
        # (the legacy rows are in place), but it takes nothing from the
        # connection the user chose: no star, no default binding.
        assert by_label["Migrated endpoint"]["maskedKey"] == "sk-...9999"
        assert by_label["Migrated endpoint"]["isDefault"] is False
        assert by_label["Own box"]["isDefault"] is True
        by_job = _bindings(booted, auth)
        assert by_job["default"]["connectionId"] == own_id
        assert by_job["default"]["model"] == "own-model"
        # Nothing was bound to research-web in between, so that binding
        # is restored.
        assert by_job["research-web"]["connectionId"] == "migrated-research"
    finally:
        booted.close()


# -- one refused write must not stop the other pair, and must not be quiet -------


def _exploding_settings(rows: dict, bad_row: str):
    """A settings-shaped stub whose write to one named row raises, like a
    settings database that refuses exactly one write. Reads come from the
    seeded rows; every write but the bad one lands."""
    class _Store:
        def get(self, key):
            return rows.get(key)

        def set(self, key, value):
            if key == bad_row:
                raise RuntimeError("the settings database refused the write")
            rows[key] = value

    return _Store()


def test_a_pair_whose_write_fails_is_logged_and_the_other_pair_still_migrates(caplog):
    settings = _exploding_settings(dict(LEGACY_ROWS), "research_provider_key")
    keys = KeysStore(sqlite3.connect(":memory:", check_same_thread=False),
                     time.time)
    keychain = KeychainSecrets(MemoryKeychain())
    with caplog.at_level(logging.ERROR, logger="agentdesk.keys.migrate"):
        created = migrate.migrate_legacy_settings(settings, keys, keychain)
    # The endpoint pair landed whole: connection, key in the keychain,
    # the default star and the legacy secret cleared from settings.
    assert created == ["Migrated endpoint"]
    assert [c.label for c in keys.all()] == ["Migrated endpoint"]
    endpoint = keys.get("migrated-endpoint")
    assert endpoint.is_default is True
    assert endpoint.masked_key == "sk-...9999"
    assert keychain.fetch("migrated-endpoint") == ENDPOINT_KEY
    assert keys.binding("default").connection_id == "migrated-endpoint"
    assert settings.get("llm_key") == ""
    # The research pair failed on its settings write and is left behind,
    # but the failure is logged by the migration module itself, naming it.
    assert created != ["Migrated endpoint", "Migrated research provider"]
    assert keychain.fetch("migrated-research") == RESEARCH_KEY  # landed first
    records = [r for r in caplog.records
               if r.name == "agentdesk.keys.migrate"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "Migrated research provider" in records[0].getMessage()


# -- desks with nothing to migrate ----------------------------------------------


def test_a_fresh_desk_boots_with_no_migrated_connections_and_an_empty_keychain():
    keychain = MemoryKeychain()
    booted = server_harness.Booted(keychain=KeychainSecrets(keychain))
    try:
        auth = booted.exchange()
        assert json.loads(booted.request("GET", "/api/connections", auth)[2])["connections"] == []
        assert json.loads(booted.request("GET", "/api/bindings", auth)[2])["bindings"] == []
        assert keychain.secrets == {}
    finally:
        booted.close()


def test_an_env_only_desk_migrates_nothing_and_the_environment_still_serves(monkeypatch):
    from test_server_job_routing import RecordingEndpoint

    stub = RecordingEndpoint()
    monkeypatch.setenv("AGENTDESK_LLM_BASE", stub.base_url + "/v1")
    monkeypatch.setenv("AGENTDESK_LLM_KEY", "env-key-1234")
    monkeypatch.setenv("AGENTDESK_LLM_MODEL", "env-model-9")
    keychain = MemoryKeychain()
    booted = server_harness.Booted(keychain=KeychainSecrets(keychain))
    try:
        auth = booted.exchange()
        assert json.loads(booted.request("GET", "/api/connections", auth)[2])["connections"] == []
        assert json.loads(booted.request("GET", "/api/bindings", auth)[2])["bindings"] == []
        assert keychain.secrets == {}  # env keys are never copied anywhere

        status, _h, body = booted.post_json(
            "/assistant/ask", {"question": "any commitments?"}, auth)
        assert json.loads(body)["status"] == "ok"
        chats = stub.chat_requests()
        assert len(chats) == 1
        assert chats[0]["auth"] == "Bearer env-key-1234"
        assert json.loads(chats[0]["body"])["model"] == "env-model-9"
    finally:
        booted.close()
        stub.close()


# -- a machine with no keychain --------------------------------------------------


def test_a_keychain_less_machine_migrates_with_the_key_absent_and_the_rows_still_serving(tmp_path):
    settings_path = _seed_data_dir(tmp_path / "data")
    booted = server_harness.Booted(
        settings_store=SettingsStore(
            sqlite3.connect(settings_path, check_same_thread=False), time.time),
        keys_store=KeysStore(
            sqlite3.connect(tmp_path / "data" / "keys.sqlite3",
                            check_same_thread=False), time.time),
        keychain=KeychainSecrets(DeadKeychain()))
    try:
        auth = booted.exchange()  # the migration never fails the boot
        listing = json.loads(booted.request("GET", "/api/connections", auth)[2])
        assert listing["keychainAvailable"] is False
        by_label = {c["label"]: c for c in listing["connections"]}
        assert set(by_label) == {"Migrated endpoint", "Migrated research provider"}
        # The connections carry the masked hints but are disabled and
        # unbound, so the environment leg (the untouched settings rows)
        # keeps serving exactly as before the upgrade.
        assert by_label["Migrated endpoint"]["maskedKey"] == "sk-...9999"
        assert by_label["Migrated endpoint"]["enabled"] is False
        assert by_label["Migrated research provider"]["enabled"] is False
        assert json.loads(booted.request("GET", "/api/bindings", auth)[2])["bindings"] == []
        # The key never landed in the keychain, so it is not deleted from
        # the settings database either.
        assert _raw_setting(settings_path, "llm_key") == ENDPOINT_KEY
        assert _raw_setting(settings_path, "research_provider_key") == RESEARCH_KEY
    finally:
        booted.close()


def test_a_keychain_less_machine_is_still_idempotent_on_the_next_boot(tmp_path):
    settings_path = _seed_data_dir(tmp_path / "data")
    booted = server_harness.Booted(
        settings_store=SettingsStore(
            sqlite3.connect(settings_path, check_same_thread=False), time.time),
        keys_store=KeysStore(
            sqlite3.connect(tmp_path / "data" / "keys.sqlite3",
                            check_same_thread=False), time.time),
        keychain=KeychainSecrets(DeadKeychain()))
    try:
        booted.exchange()
    finally:
        booted.close()

    booted = server_harness.Booted(
        settings_store=SettingsStore(
            sqlite3.connect(settings_path, check_same_thread=False), time.time),
        keys_store=KeysStore(
            sqlite3.connect(tmp_path / "data" / "keys.sqlite3",
                            check_same_thread=False), time.time),
        keychain=KeychainSecrets(DeadKeychain()))
    try:
        auth = booted.exchange()
        labels = sorted(_listing(booted, auth))
        assert labels == ["Migrated endpoint", "Migrated research provider"]
    finally:
        booted.close()
