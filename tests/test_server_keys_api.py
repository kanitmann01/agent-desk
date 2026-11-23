"""Connections CRUD through the real HTTP seam (spec 018, ticket #231).

The harness boots with an inert in-memory keys store and the in-memory
fake keychain, so every test here drives the real server over a real
socket without touching a real OS keychain. The one guarantee asserted
everywhere: the secret appears in the create request and never again,
not in a payload, not in the page, not in the sqlite file, not in the
audit trail.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.keys import health
from agentdesk.keys.presets import PRESETS, preset_for
from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain
from agentdesk.keys.store import KeysStore

SECRET = "sk-live-quietly-aaaaaaaaaaaaaaaa-9999"


def _instant_check(base_url, api_key, extra_headers=None, timeout=None):
    """A save-time prober that answers instantly, hermetically: this
    suite exercises the CRUD and markup surface, not the check itself
    (the health suite runs the real prober against a loopback stub), so
    no boot here can reach a real provider by saving a key."""
    return health.ProbeResult(health.OUTCOME_OK, "", ["hermetic-model"])


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


class RefusingStoreKeychain:
    """A keyring-shaped backend that is reachable but refuses every
    write, like an OS keychain denying the save."""

    def get_password(self, *_args):
        return None

    def set_password(self, *_args):
        raise RuntimeError("the keychain refused the write")


class NoDeleteKeychain:
    """A keyring-shaped wrapper that stores and reads through to a real
    fake but refuses every delete, like an OS keychain denying the
    removal while everything else works."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def get_password(self, service, username):
        return self._inner.get_password(service, username)

    def set_password(self, service, username, secret):
        self._inner.set_password(service, username, secret)

    def delete_password(self, service, username):
        raise RuntimeError("the keychain refused the delete")


@pytest.fixture()
def keychain():
    return MemoryKeychain()


@pytest.fixture()
def env(keychain):
    booted = server_harness.Booted(
        keychain=KeychainSecrets(keychain), connection_check=_instant_check)
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _post_form(env, path, fields, headers):
    """A browser-shaped POST: form-urlencoded fields, no JavaScript."""
    data = urlencode(fields).encode("utf-8")
    merged = {"Content-Type": "application/x-www-form-urlencoded"}
    merged.update(headers)
    return env.request("POST", path, merged, data)


def _create(env, auth, **overrides):
    """One create request with the usual hosted-preset shape."""
    body = {"label": "OpenAI personal", "provider": "openai",
            "apiKey": SECRET, **overrides}
    return env.post_json("/api/connections", body, auth)


# -- create / list / update / delete ----------------------------------------


def test_create_stores_the_key_in_the_keychain_and_answers_the_mask(env, auth, keychain):
    status, _h, body = _create(env, auth)
    assert status == 201
    payload = json.loads(body)
    assert payload["label"] == "OpenAI personal"
    assert payload["provider"] == "openai"
    # The preset default filled the blank base URL.
    assert payload["baseUrl"] == "https://api.openai.com/v1"
    assert payload["maskedKey"] == "sk-...9999"
    # The secret itself went to the keychain alone, under the spec's shape.
    assert keychain.secrets == {("agent-desk", f"key/{payload['id']}"): SECRET}


def test_create_stores_the_model_and_the_listing_returns_it(env, auth):
    """Spec 022: a connection remembers its model. Every model call then
    sends it, so one connection no longer answers gpt-4o-mini to every
    provider."""
    status, _h, body = _create(env, auth, model="mock-chat")
    assert status == 201
    assert json.loads(body)["model"] == "mock-chat"
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    assert [c["model"] for c in listing["connections"]] == ["mock-chat"]


def test_a_save_that_arrives_with_no_model_takes_the_preset_default(env, auth):
    """The form starts with the preset's default model. A save that arrives
    without one (a browser without script, after switching provider) takes
    that provider's default on the server, the way the base URL field
    works, so no provider is saved with a name it does not serve. A preset
    with no verified model records none rather than a guess."""
    assert json.loads(_create(env, auth)[2])["model"] == "gpt-6-luna"
    # A preset whose page names no default saves none: the field asks.
    status, _h, body = env.post_json("/api/connections", {
        "label": "OpenCode Go", "provider": "opencode",
        "apiKey": SECRET, "model": ""}, auth)
    assert status == 201
    assert json.loads(body)["model"] == ""


def test_the_secret_is_never_echoed_after_create(env, auth):
    _create(env, auth)
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert SECRET not in json.dumps(listing)
    assert "sk-live-quietly" not in page


def test_list_carries_every_connection_with_masked_hints_only(env, auth):
    _create(env, auth)
    status, _h, body = env.post_json("/api/connections", {
        "label": "Local ollama", "provider": "ollama",
    }, auth)
    assert status == 201
    payload = json.loads(env.request("GET", "/api/connections", auth)[2])
    assert payload["keychainAvailable"] is True
    hints = {c["maskedKey"] for c in payload["connections"]}
    assert hints == {"sk-...9999", ""}
    labels = {c["label"] for c in payload["connections"]}
    assert labels == {"OpenAI personal", "Local ollama"}


def test_unknown_fields_answer_400_naming_the_accepted_fields(env, auth):
    status, _h, body = env.post_json("/api/connections", {
        "labell": "OpenAI personal", "provider": "openai",
        "key": SECRET, "isDefault": "yes",
    }, auth)
    payload = json.loads(body)
    assert status == 400
    for typo in ("labell", "key"):
        assert typo in payload["error"]
    for accepted in ("label", "provider", "baseUrl", "apiKey", "headers",
                     "isDefault", "model"):
        assert accepted in payload["error"]
    # Refusing beats a silent ok with dropped values: nothing was saved.
    assert json.loads(env.request("GET", "/api/connections", auth)[2])["connections"] == []


def test_create_refuses_a_blank_label_an_unknown_preset_and_a_bad_base(env, auth):
    for body, fragment in (
        ({"provider": "openai", "apiKey": SECRET}, "label"),
        ({"label": "x", "provider": "madeup", "apiKey": SECRET}, "preset"),
        ({"label": "x", "provider": "custom", "baseUrl": "llm.corp.example/v1"}, "http"),
        ({"label": "x", "provider": "custom"}, "base URL"),
        ({"label": "x", "provider": "openai", "apiKey": "k",
          "headers": {"Bad": 5}}, "headers"),
    ):
        status, _h, returned = env.post_json("/api/connections", body, auth)
        assert status == 400, body
        assert fragment in json.loads(returned)["error"], body
    assert json.loads(env.request("GET", "/api/connections", auth)[2])["connections"] == []


def test_a_duplicate_label_is_refused_with_409(env, auth):
    _create(env, auth)
    status, _h, body = env.post_json("/api/connections", {
        "label": "OpenAI personal", "provider": "openai", "apiKey": "other",
    }, auth)
    assert status == 409
    assert "already used" in json.loads(body)["error"]


def test_hosted_presets_need_a_key_and_name_their_console(env, auth):
    status, _h, body = env.post_json("/api/connections", {
        "label": "No key", "provider": "openai",
    }, auth)
    assert status == 400
    error = json.loads(body)["error"]
    assert "API key" in error
    assert "https://platform.openai.com/api-keys" in error


def test_local_presets_save_with_no_key_and_skip_the_keychain(env, auth, keychain):
    status, _h, body = env.post_json("/api/connections", {
        "label": "Desk ollama", "provider": "ollama",
    }, auth)
    assert status == 201
    payload = json.loads(body)
    assert payload["maskedKey"] == ""
    assert payload["baseUrl"] == "http://localhost:11434/v1"
    assert keychain.secrets == {}  # no key, so no keychain write at all


def test_update_with_an_empty_key_keeps_the_stored_key(env, auth, keychain):
    created = json.loads(_create(env, auth)[2])
    status, _h, body = env.post_json(
        f"/api/connections/{created['id']}/update", {
            "label": "OpenAI work", "provider": "openai",
            "baseUrl": "https://api.openai.com/v1", "apiKey": "",
        }, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["label"] == "OpenAI work"
    assert payload["maskedKey"] == "sk-...9999"  # the hint survived the edit
    assert keychain.secrets == {("agent-desk", f"key/{created['id']}"): SECRET}


def test_update_changes_the_model_and_one_it_does_not_mention_keeps_it(
        env, auth):
    created = json.loads(_create(env, auth, model="mock-chat")[2])
    path = f"/api/connections/{created['id']}/update"
    edit = {"label": "OpenAI personal", "provider": "openai", "apiKey": ""}

    status, _h, body = env.post_json(path, {**edit, "model": "mock-chat-v2"}, auth)
    assert status == 200
    assert json.loads(body)["model"] == "mock-chat-v2"

    # A request that does not mention the model leaves it alone: a client
    # written before the field existed must not reset the connection.
    status, _h, body = env.post_json(path, edit, auth)
    assert status == 200
    assert json.loads(body)["model"] == "mock-chat-v2"

    # A blank model is the "none chosen" state, sent as such.
    status, _h, body = env.post_json(path, {**edit, "model": " "}, auth)
    assert status == 200
    assert json.loads(body)["model"] == ""


def test_the_edit_form_saves_the_model_it_shows(env, auth):
    """A browser always posts the form's model field, so a blank one is the
    user clearing it, and it is saved as cleared (spec 022: "Model: default")."""
    created = json.loads(_create(env, auth, model="mock-chat")[2])
    path = f"/api/connections/{created['id']}/update"
    edit = {"label": "OpenAI personal", "provider": "openai", "apiKey": ""}

    status, headers, _b = _post_form(env, path, {**edit, "model": "mock-chat-v2"}, auth)
    assert status == 303
    assert headers["Location"] == "/settings#connections"
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    assert [c["model"] for c in listing["connections"]] == ["mock-chat-v2"]

    status, _h, _b = _post_form(env, path, {**edit, "model": ""}, auth)
    assert status == 303
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    assert [c["model"] for c in listing["connections"]] == [""]


def test_the_clear_action_removes_the_stored_key(env, auth, keychain):
    created = json.loads(_create(env, auth)[2])
    status, _h, body = env.post_json(
        f"/api/connections/{created['id']}/update", {
            "label": "OpenAI personal", "provider": "openai",
            "baseUrl": "https://api.openai.com/v1", "keyClear": "1",
        }, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["maskedKey"] == ""
    assert keychain.secrets == {}


def test_update_can_replace_the_key_and_star_the_default(env, auth, keychain):
    created = json.loads(_create(env, auth)[2])
    env.post_json("/api/connections", {
        "label": "Local ollama", "provider": "ollama"}, auth)
    status, _h, body = env.post_json(
        f"/api/connections/{created['id']}/update", {
            "label": "OpenAI personal", "provider": "openai",
            "baseUrl": "https://api.openai.com/v1",
            "apiKey": "sk-rotated-bbbbbbbbbbbbbbbb-7777", "isDefault": "1",
        }, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["maskedKey"] == "sk-...7777"
    assert payload["isDefault"] is True
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    defaults = [c["label"] for c in listing["connections"] if c["isDefault"]]
    assert defaults == ["OpenAI personal"]  # the star belongs to one row


def test_update_and_delete_answer_404_for_an_unknown_id(env, auth):
    status, _h, _b = env.post_json("/api/connections/gone/update", {
        "label": "x", "provider": "openai"}, auth)
    assert status == 404
    status, _h, _b = env.post_json("/api/connections/gone/delete", {}, auth)
    assert status == 404


def test_delete_removes_the_row_and_the_keychain_entry(env, auth, keychain):
    created = json.loads(_create(env, auth)[2])
    status, _h, body = env.post_json(
        f"/api/connections/{created['id']}/delete", {}, auth)
    assert status == 200
    assert json.loads(body) == {"ok": True, "id": created["id"]}
    assert keychain.secrets == {}
    assert json.loads(env.request("GET", "/api/connections", auth)[2])["connections"] == []


# -- a keychain that refuses ---------------------------------------------------


def test_a_refused_keychain_write_leaves_the_previous_default_starred(env, auth):
    first = json.loads(env.post_json("/api/connections", {
        "label": "First and default", "provider": "openai",
        "apiKey": SECRET, "isDefault": "1",
    }, auth)[2])
    assert first["isDefault"] is True
    # The keychain starts refusing writes, so the second save's key cannot
    # land and the whole save is refused.
    env.server.keychain = KeychainSecrets(RefusingStoreKeychain())
    status, _h, body = env.post_json("/api/connections", {
        "label": "Second as default", "provider": "openai",
        "apiKey": "sk-live-quietly-bbbbbbbbbbbbbbbb-4444", "isDefault": "1",
    }, auth)
    assert status == 400
    assert "nothing was saved" in json.loads(body)["error"]
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    rows = listing["connections"]
    # The refused row is gone and the first connection still carries the
    # star: the refused save's insert had cleared it before the keychain
    # said no, and the rollback gave it back.
    assert [c["label"] for c in rows] == ["First and default"]
    assert rows[0]["isDefault"] is True
    assert rows[0]["id"] == first["id"]


def test_a_refused_keychain_delete_is_named_on_the_clear_action(
        env, auth, keychain):
    created = json.loads(_create(env, auth)[2])
    env.server.keychain = KeychainSecrets(NoDeleteKeychain(keychain))
    status, _h, body = env.post_json(
        f"/api/connections/{created['id']}/update", {
            "label": "OpenAI personal", "provider": "openai",
            "baseUrl": "https://api.openai.com/v1", "keyClear": "1",
        }, auth)
    assert status == 200
    payload = json.loads(body)
    # The row says no key from here on, and the answer names the keychain
    # that still holds the secret instead of posing as a clean clear.
    assert payload["maskedKey"] == ""
    assert "still holds the key" in payload["notice"]
    assert keychain.secrets  # the secret really is still in the keychain
    # A no-JS form post gets the same sentence as the redirect's notice.
    status, headers, _b = _post_form(
        env, f"/api/connections/{created['id']}/update", {
            "label": "OpenAI personal", "provider": "openai",
            "baseUrl": "https://api.openai.com/v1", "keyClear": "1",
        }, auth)
    assert status == 303
    assert "still holds the key" in unquote(headers["Location"])
    assert "connections_error" in headers["Location"]


def test_custom_connections_carry_extra_headers(env, auth):
    status, _h, body = env.post_json("/api/connections", {
        "label": "Work gateway", "provider": "custom",
        "baseUrl": "https://llm.corp.example/v1", "apiKey": SECRET,
        "headers": {"X-Gateway": "corp", "api-version": "2"},
    }, auth)
    assert status == 201
    assert json.loads(body)["headers"] == {"X-Gateway": "corp", "api-version": "2"}


# -- the never-leak guarantees, in bytes --------------------------------------


def test_no_secret_substring_in_the_keys_sqlite_file_or_any_payload(
        tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    conn = sqlite3.connect(tmp_path / "keys.sqlite3", check_same_thread=False)
    booted = server_harness.Booted(
        keys_store=KeysStore(conn, time.time),
        keychain=KeychainSecrets(MemoryKeychain()),
        connection_check=_instant_check)
    try:
        auth = booted.exchange()
        _create(booted, auth)
        booted.post_json("/api/connections", {
            "label": "Local ollama", "provider": "ollama"}, auth)
        created = json.loads(booted.request("GET", "/api/connections", auth)[2])
        first = created["connections"][0]
        booted.post_json(f"/api/connections/{first['id']}/update", {
            "label": "OpenAI personal", "provider": "openai",
            "baseUrl": "https://api.openai.com/v1", "apiKey": ""}, auth)
        surfaces = [
            booted.request("GET", "/api/connections", auth)[2],
            booted.request("GET", "/settings", auth)[2],
            booted.request("GET", "/settings/activity", auth)[2],
            booted.request("GET", "/audit/tail", auth)[2],
            booted.request("GET", "/audit/export.csv", auth)[2],
            (tmp_path / "keys.sqlite3").read_bytes(),
        ]
        for surface in surfaces:
            as_text = surface.decode("utf-8", errors="replace")
            assert "sk-live-quietly" not in as_text
            assert SECRET not in as_text
    finally:
        booted.close()


# -- a machine with no keychain ----------------------------------------------


def test_no_keychain_machine_names_the_state_and_still_saves_keyless_connections():
    booted = server_harness.Booted(keychain=KeychainSecrets(DeadKeychain()),
                                   connection_check=_instant_check)
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json("/api/connections", {
            "label": "OpenAI personal", "provider": "openai", "apiKey": SECRET,
        }, auth)
        assert status == 400
        assert "keychain" in json.loads(body)["error"].lower()
        # A local connection needs no secret, so it saves anyway.
        status, _h, _b = booted.post_json("/api/connections", {
            "label": "Desk ollama", "provider": "ollama"}, auth)
        assert status == 201
        listing = json.loads(booted.request("GET", "/api/connections", auth)[2])
        assert listing["keychainAvailable"] is False
        page = booted.request("GET", "/settings", auth)[2].decode("utf-8")
        assert "cannot be stored" in page
    finally:
        booted.close()


# -- the Settings page, server-rendered ---------------------------------------


def test_settings_page_carries_the_provider_select_and_console_deep_links(env, auth):
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    # The provider picker is one native select (spec 019 #263): a label
    # names it, the form posts the same provider field the radios posted,
    # and no radio grid remains on the page.
    assert "<label class='empty' for='conn-provider'>Provider</label>" in page
    assert "<select id='conn-provider' name='provider'>" in page
    assert "preset-grid" not in page and "preset-tile" not in page
    assert "<input type='radio' name='provider'" not in page
    # Three optgroups in order: the hosted providers, the local servers
    # whose labels carry the discovery fact, Custom last.
    hosted = page.index("<optgroup label='Hosted providers'>")
    local = page.index("<optgroup label='Local servers, no key needed'>")
    custom = page.index("<optgroup label='Custom'>")
    assert hosted < local < custom
    for preset in PRESETS:
        label = preset.name
        if preset.local:
            label += " (this machine, no key needed)"
        chosen = " selected" if preset.id == PRESETS[0].id else ""
        # Each option carries its preset's address and default model as
        # data, for the script that fills both fields on a choice.
        expected = (f"<option value='{preset.id}'{chosen}"
                    f" data-base='{preset.base_url}'"
                    f" data-model='{preset.default_model}'>{label}</option>")
        assert expected in page, preset.id
    # The create form opens on the first preset, where the checked radio
    # used to sit, and Custom is the last option of all.
    for preset in PRESETS[:-1]:
        assert page.index(f"<option value='{preset.id}'") < custom, preset.id
    assert ("<option value='openai' selected"
            " data-base='https://api.openai.com/v1'"
            " data-model='gpt-6-luna'>OpenAI</option>") in page
    # The console deep-links answer "where do I get a key" inline, folded
    # into a native disclosure (spec 019 #259): the summary names the
    # block, the anchors stay plain links with their hrefs, and the open
    # and close need no script.
    start = page.index("<details class='console-links'>")
    block = page[start:page.index("</details>", start)]
    assert "<summary>Where to get a key</summary>" in block
    for url in ("https://platform.openai.com/api-keys",
                "https://console.anthropic.com/settings/keys",
                "https://openrouter.ai/settings/keys"):
        assert f"<a class='btn btn-secondary' href='{url}'>" in block, url
    # The form is a real form: it posts without any script.
    assert "action='/api/connections'" in page
    assert "name='label'" in page and "name='provider'" in page
    assert "name='apiKey'" in page
    assert "type='password'" in page


def _connection_form(page: str) -> str:
    """The connection form's own markup, apart from the rest of the page."""
    start = page.index("id='connection-form'")
    return page[start:page.index("</form>", start)]


def test_the_create_form_offers_the_model_field_as_text(env, auth):
    """Nothing has listed a new connection's models yet, so the Model field
    is a text field; the script fills the selected preset's default into it
    (checked in a real browser, not here)."""
    form = _connection_form(
        env.request("GET", "/settings", auth)[2].decode("utf-8"))
    assert "<label class='empty' for='conn-model'>Model</label>" in form
    assert "<input id='conn-model' type='text' name='model'" in form
    assert "<select id='conn-model'" not in form


def test_the_edit_form_lists_the_models_the_save_check_found(env, auth):
    """A list once the save-time check filled one, the saved model selected,
    with a way back to the default (spec 022)."""
    created = json.loads(_create(env, auth, model="hermetic-model")[2])
    form = _connection_form(env.request(
        "GET", f"/settings?connection={created['id']}", auth)[2].decode("utf-8"))
    assert "<label class='empty' for='conn-model'>Model</label>" in form
    assert "<select id='conn-model' name='model'>" in form
    assert "<option value=''>default</option>" in form
    assert "<option value='hermetic-model' selected>hermetic-model</option>" in form
    assert "<input id='conn-model'" not in form

    # A model the listing does not carry stays selectable as it is, so
    # editing the label never swaps it for the first listed model.
    env.server.keys.update(created["id"], model="typed-by-hand")
    form = _connection_form(env.request(
        "GET", f"/settings?connection={created['id']}", auth)[2].decode("utf-8"))
    assert "<option value='typed-by-hand' selected>typed-by-hand</option>" in form

    # An endpoint that listed nothing leaves a text field carrying the model.
    env.server.keys.set_models(created["id"], [])
    form = _connection_form(env.request(
        "GET", f"/settings?connection={created['id']}", auth)[2].decode("utf-8"))
    assert ("<input id='conn-model' type='text' name='model'"
            " value='typed-by-hand'") in form
    assert "<select id='conn-model'" not in form


def test_each_saved_row_shows_its_model_or_default(env, auth):
    _create(env, auth, model="mock-chat")
    env.post_json("/api/connections", {
        "label": "Local ollama", "provider": "ollama",
        "baseUrl": "http://localhost:11434/v1", "model": ""}, auth)
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    rows = {row.split("</b>")[0]: row for row in page.split("<tr>")[1:]}
    assert "Model: mock-chat" in rows["<td><b>OpenAI personal"]
    # A connection with no model says so in plain words (spec 022).
    assert "Model: default" in rows["<td><b>Local ollama"]


def test_settings_page_lists_connections_with_masked_hints_and_actions(env, auth):
    created = json.loads(_create(env, auth)[2])
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "OpenAI personal" in page
    assert "sk-...9999" in page
    assert "sk-live-quietly" not in page
    assert f"/settings?connection={created['id']}" in page  # the edit link
    assert f"/api/connections/{created['id']}/delete" in page  # the delete form
    # The row compacts by layout (spec 019 #256): the URL cell takes the
    # wrapping class and the actions cell takes the one-line class.
    assert "class='mono conn-url'" in page
    assert "class='conn-actions'" in page


def test_settings_page_renders_the_badge_states_server_side(env, auth):
    """The badge is server-rendered from the row (spec 018 #232): unknown
    for a keyless connection nothing has checked, error with the cause
    inline, ok clean (a keyed save checks on save, story 3, so the badge
    is already truthful right after the redirect back). The same page
    works with no script because the state is in the markup."""
    status, _h, _b = env.post_json("/api/connections", {
        "label": "Desk ollama", "provider": "ollama"}, auth)
    assert status == 201
    created = json.loads(_create(env, auth)[2])
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "conn-unknown" in page  # the keyless connection, unchecked
    assert "conn-ok" in page  # the keyed one, checked on save
    assert f"/api/connections/{created['id']}/test' class='inlineform'" in page
    env.server.keys.record_check(
        created["id"], status="error",
        note="the endpoint rejected the API key (HTTP 401); check the key")
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "conn-error" in page
    assert "the endpoint rejected the API key (HTTP 401)" in page
    env.server.keys.record_check(created["id"], status="ok", note="")
    env.server.keys.set_models(created["id"], ["gpt-4o-mini"])
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "conn-ok" in page
    assert "1 model cached" in page


def test_edit_form_offers_the_test_and_manual_model_entry(env, auth):
    """Manual model entry is always available and never gated on a
    discovery listing: the deeper-check form carries a plain text input
    and posts it to the explicit one-token route (spec 018 #232)."""
    created = json.loads(_create(env, auth)[2])
    page = env.request("GET", f"/settings?connection={created['id']}", auth)[2]
    text = page.decode("utf-8")
    assert f"action='/api/connections/{created['id']}/test'" in text
    assert f"action='/api/connections/{created['id']}/check'" in text
    assert "name='model'" in text
    assert "never completes a chat" in text
    assert "exactly one token" in text


def test_edit_form_is_prefilled_and_posts_to_the_update_route(env, auth):
    created = json.loads(_create(env, auth, provider="groq")[2])
    page = env.request("GET", f"/settings?connection={created['id']}", auth)[2]
    text = page.decode("utf-8")
    assert f"action='/api/connections/{created['id']}/update'" in text
    assert "OpenAI personal" in text
    # The provider select mirrors the saved provider (spec 019 #263):
    # groq carries selected and it is the only option that does.
    assert (f"<option value='groq' selected"
            f" data-base='https://api.groq.com/openai/v1'"
            f" data-model='{preset_for('groq').default_model}'>Groq</option>") in text
    assert text.count(" selected data-base=") == 1
    # The empty-key-keeps rule and the separate clear action are both stated.
    assert "keeps the stored key" in text
    assert "Remove the stored key" in text


def test_form_posts_really_work_without_javascript(env, auth, keychain):
    # Create: a plain form post redirects back to the page.
    status, headers, _b = _post_form(env, "/api/connections", {
        "label": "OpenAI personal", "provider": "openai",
        "baseUrl": "", "apiKey": SECRET, "headers": "",
    }, auth)
    assert status == 303
    # The redirect anchors to the card so the saved row is in view.
    assert headers["Location"] == "/settings#connections"
    created = json.loads(env.request("GET", "/api/connections", auth)[2])["connections"][0]

    # Edit with an empty key field keeps the stored key.
    status, _h, _b = _post_form(
        env, f"/api/connections/{created['id']}/update", {
            "label": "OpenAI work", "provider": "openai",
            "baseUrl": "https://api.openai.com/v1", "apiKey": "",
        }, auth)
    assert status == 303
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    assert listing["connections"][0]["label"] == "OpenAI work"
    assert listing["connections"][0]["maskedKey"] == "sk-...9999"

    # The clear checkbox removes the stored key.
    _post_form(env, f"/api/connections/{created['id']}/update", {
        "label": "OpenAI work", "provider": "openai",
        "baseUrl": "https://api.openai.com/v1", "keyClear": "1",
    }, auth)
    listing = json.loads(env.request("GET", "/api/connections", auth)[2])
    assert listing["connections"][0]["maskedKey"] == ""
    assert keychain.secrets == {}

    # Delete is a form post too.
    status, _h, _b = _post_form(
        env, f"/api/connections/{created['id']}/delete", {}, auth)
    assert status == 303
    assert json.loads(env.request("GET", "/api/connections", auth)[2])["connections"] == []


# -- the audit trail -----------------------------------------------------------


def test_keys_lifecycle_lands_in_the_audit_trail_without_secret_material(env, auth):
    created = json.loads(_create(env, auth)[2])
    env.post_json(f"/api/connections/{created['id']}/update", {
        "label": "OpenAI work", "provider": "openai",
        "baseUrl": "https://api.openai.com/v1", "apiKey": ""}, auth)
    env.post_json(f"/api/connections/{created['id']}/delete", {}, auth)
    tail = env.request("GET", "/audit/tail", auth)[2].decode("utf-8")
    entries = json.loads(tail)["entries"]
    actions = [e["action"] for e in entries]
    for expected in ("keys.delete", "keys.update", "keys.create"):  # newest first
        assert expected in actions
    for entry in entries:
        if entry["action"].startswith("keys."):
            assert SECRET not in json.dumps(entry)
            assert "sk-" not in entry["detail"]
    # The vocabulary rows appear on the what-this-touches page.
    touches = env.request("GET", "/what-this-touches", auth)[2].decode("utf-8")
    for expected in ("keys.create", "keys.update", "keys.delete"):
        assert expected in touches


def test_the_activity_page_shows_the_key_lifecycle(env, auth):
    created = json.loads(_create(env, auth)[2])
    page = env.request("GET", "/settings/activity", auth)[2].decode("utf-8")
    assert "keys.create" in page
    assert "OpenAI personal" in page
    assert created["id"] in page


# -- the preset catalog ---------------------------------------------------------


def test_the_catalog_ships_the_thirteen_verified_presets():
    assert [p.id for p in PRESETS] == [
        "openai", "anthropic-compat", "openrouter", "groq", "together",
        "gemini", "deepseek", "mistral", "opencode", "ollama", "lmstudio",
        "vllm", "custom",
    ]
    opencode = preset_for("opencode")
    assert opencode.base_url == "https://opencode.ai/inference/go/v1"
    assert opencode.console_url.startswith("https://opencode.ai/")
    hosted = [p for p in PRESETS if not p.key_optional and p.id != "custom"]
    assert all(p.base_url.startswith("https://") for p in hosted)
    assert all(p.console_url.startswith("https://") for p in hosted)
    local = [p for p in PRESETS if p.key_optional]
    assert {p.id for p in local} == {"ollama", "lmstudio", "vllm"}
    assert all(p.base_url.startswith("http://localhost:") for p in local)
    assert all(p.console_url == "" for p in local)


def test_every_preset_records_one_default_model():
    """Spec 022: the model a new connection's form starts with. Only an id
    verified on the provider's own documentation on 2026-11-23 is recorded;
    a preset whose page names no default (the local servers, OpenCode Go,
    Custom) stays empty and the field then asks, rather than guessing."""
    defaults = {p.id: p.default_model for p in PRESETS}
    assert defaults == {
        "openai": "gpt-6-luna",
        "anthropic-compat": "claude-haiku-5-5",
        "openrouter": "openai/gpt-5.2",
        "groq": "llama-3.3-70b-versatile",
        "together": "MiniMaxAI/MiniMax-M3.1-Flash",
        "gemini": "gemini-3.5-flash-lite",
        "deepseek": "deepseek-flash",
        "mistral": "mistral-small-4-0-26-03",
        "opencode": "",
        "ollama": "",
        "lmstudio": "",
        "vllm": "",
        "custom": "",
    }


def test_a_refused_save_lands_on_the_connections_card(env, auth):
    """A refused save must land AT the card carrying its notice, the same
    anchored-redirect contract the desk-check and updates sections use:
    without the anchor the long settings page hides the failure and the
    save merely feels silent (the bug report's shape)."""
    status, headers, _b = env.post_json("/api/connections", {
        "label": "No key", "provider": "openai", "baseUrl": "",
        "apiKey": "",
    }, auth)
    assert status == 400
    # The form flow specifically.
    form = {"label": "No key", "provider": "openai"}
    data = urlencode(form).encode()
    merged = {"Content-Type": "application/x-www-form-urlencoded",
              "Content-Length": str(len(data)), **auth}
    status, headers, _b = env.request(
        "POST", "/api/connections", merged, data)
    assert status == 303
    assert headers["Location"].endswith("#connections")
    assert "connections_error" in unquote(headers["Location"])


def test_a_successful_save_lands_on_the_connections_card(env, auth):
    """The success redirect anchors to the card too, so the saved row is
    in view the moment the page returns."""
    form = {"label": "Anchored", "provider": "opencode",
            "baseUrl": "", "apiKey": "oc_sk_anchor_test"}
    data = urlencode(form).encode()
    merged = {"Content-Type": "application/x-www-form-urlencoded",
              "Content-Length": str(len(data)), **auth}
    status, headers, _b = env.request(
        "POST", "/api/connections", merged, data)
    assert status == 303
    assert headers["Location"].endswith("/settings#connections")
    cid = env.server.keys.all()[0].id
    env.post_json(f"/api/connections/{cid}/delete", {}, auth)
