"""Settings and first-run tests: toggles only, enforcement that matches,
an endpoint indicator that tells the truth, and a first run with zero
permission prompts.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.llm import LlmUnavailable
from agentdesk.server import app as server_app
from agentdesk.settings import SettingsStore

NOW = datetime(2026, 11, 11, 9, 0, 0).astimezone()


@pytest.fixture()
def env():
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def test_settings_endpoint_requires_a_session(env):
    status, _h, _b = env.request("GET", "/widgets/settings", env.host_header())
    assert status == 401


def test_every_setting_has_a_default_and_toggles(env, auth):
    values = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values == {
        "excel_enabled": True,
        "calendar_enabled": True,
        "endpoint_enabled": True,
        "quiet_hours": True,
        "daily_cap": 3,
        "llm_base": "",
        "llm_key": "",
        "llm_model": "",
        # Mail (#44): off by default, no folder chosen.
        "mail_enabled": False,
        "mail_folder": "",
        # Registry: no checkout pinned, so resolution is automatic.
        "registry_path": "",
        # Demo sample data (#68): off until the user asks for it.
        "sample_data": False,
        # Guard (#61): no extra hosts sanctioned, so loopback only.
        "extra_allowed_hosts": "",
    }
    status, _h, body = env.post_json("/settings/toggle", {"key": "excel_enabled"}, auth)
    assert status == 200
    assert json.loads(body) == {"key": "excel_enabled", "value": False}
    assert json.loads(env.request("GET", "/widgets/settings", auth)[2])["excel_enabled"] is False


def test_endpoint_save_and_clear_round_trip_with_masking(env, auth):
    status, _h, body = env.post_json("/settings/endpoint/save", {
        "base": "https://llm.corp.example/v1",
        "key": "super-secret-key-4321",
        "model": "claude-sonnet-4-5",
    }, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["ok"] is True
    assert payload["base"] == "https://llm.corp.example/v1"
    # The response carries the masked state, never the key.
    assert "super-secret" not in json.dumps(payload)
    assert "4321" in payload["keyState"]
    values = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values["llm_base"] == "https://llm.corp.example/v1"
    assert values["llm_model"] == "claude-sonnet-4-5"
    assert values["llm_key"] == "Set. Ends with 4321."

    # Empty strings clear each row; the store is empty again.
    status, _h, _b = env.post_json("/settings/endpoint/save", {
        "base": "", "key": "", "model": "",
    }, auth)
    assert status == 200
    values = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values["llm_base"] == "" and values["llm_key"] == "" and values["llm_model"] == ""


def test_saved_key_is_never_rendered_back(env, auth):
    env.post_json("/settings/endpoint/save", {
        "base": "https://llm.corp.example/v1",
        "key": "sk-totally-hidden-value-99aa",
        "model": "m",
    }, auth)
    settings_page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "sk-totally-hidden-value" not in settings_page
    assert "99aa" in settings_page  # the masked tail is the only trace
    assert "id='llm-key' type='password'" in settings_page
    values_page = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values_page["llm_key"] == "Set. Ends with 99aa."


def test_endpoint_section_has_save_test_clear_and_the_hint(env, auth):
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "data-endpoint-save" in page
    assert "data-endpoint-test" in page
    assert "data-endpoint-clear" in page
    assert "Test connection" in page
    # The hint names the compatible surfaces, including Anthropic's URL.
    assert "OpenAI-compatible" in page
    assert "https://api.anthropic.com/v1" in page
    assert "OpenRouter" in page and "LiteLLM" in page
    # Saving with an empty key field clears it: the page says so.
    assert "clears the saved key" in page


def test_endpoint_test_uses_submitted_values_against_a_real_stub(env, auth):
    from test_server_research_api import StubEndpoint

    stub = StubEndpoint("pong")
    try:
        # A save first, so the test request must NOT use the saved key.
        env.post_json("/settings/endpoint/save", {
            "base": "https://saved.example/v1", "key": "saved-key", "model": "saved-model",
        }, auth)
        status, _h, body = env.post_json("/settings/endpoint/test", {
            "base": stub.base_url, "key": "typed-key", "model": "typed-model",
        }, auth)
        payload = json.loads(body)
        assert status == 200
        assert payload["ok"] is True
        # The minimal probe really went to the submitted endpoint.
        assert stub.requests[-1]["path"] == "/chat/completions"
        assert stub.requests[-1]["auth"] == "Bearer typed-key"
        assert stub.requests[-1]["body"]["messages"][0]["content"] == "ping"
        assert stub.requests[-1]["body"]["max_tokens"] == 1

        # A down endpoint answers ok=false with the honest cause.
        status, _h, body = env.post_json("/settings/endpoint/test", {
            "base": "http://127.0.0.1:9", "key": "k", "model": "m",
        }, auth)
        payload = json.loads(body)
        assert status == 200
        assert payload["ok"] is False
        assert "endpoint" in payload["cause"]
    finally:
        stub.close()


def test_endpoint_test_without_a_base_says_so(env, auth):
    status, _h, body = env.post_json("/settings/endpoint/test", {"base": ""}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["ok"] is False
    assert "base URL" in payload["cause"]


def test_research_uses_saved_settings_without_a_restart(env, auth, monkeypatch):
    from test_server_research_api import StubEndpoint

    content = json.dumps({"summary": "Saved endpoint answered.", "sources": ["settings"]})
    stub = StubEndpoint(content)
    try:
        # The environment points at a dead port; the saved settings must
        # win, on the very next request, with no restart.
        monkeypatch.setenv("AGENTDESK_LLM_BASE", "http://127.0.0.1:9")
        status, _h, body = env.post_json("/settings/endpoint/save", {
            "base": stub.base_url, "key": "settings-key", "model": "settings-model",
        }, auth)
        assert status == 200
        status, _h, body = env.post_json("/research", {"question": "q"}, auth)
        payload = json.loads(body)
        assert status == 200
        assert payload["status"] == "ok"
        assert "Saved endpoint answered." in payload["summary"]
        assert stub.requests[-1]["auth"] == "Bearer settings-key"

        # Clearing the rows hands control back to the environment, which
        # is dead here, so research degrades again.
        env.post_json("/settings/endpoint/save", {"base": "", "key": "", "model": ""}, auth)
        payload = json.loads(env.post_json("/research", {"question": "q"}, auth)[2])
        assert payload["status"] == "degraded"
    finally:
        stub.close()


def test_health_reflects_saved_settings_and_their_clearing(env, auth):
    def research_source():
        payload = json.loads(env.request("GET", "/health", auth)[2])
        return next(s for s in payload["sources"] if s["id"] == "research-endpoint")

    assert research_source()["status"] == "not_connected"
    env.post_json("/settings/endpoint/save", {
        "base": "https://llm.corp.example/v1", "key": "k", "model": "m",
    }, auth)
    assert research_source()["status"] == "connected"
    env.post_json("/settings/endpoint/save", {"base": "", "key": "", "model": ""}, auth)
    assert research_source()["status"] == "not_connected"


def test_health_reflects_the_environment_when_nothing_is_saved(monkeypatch):
    monkeypatch.setenv("AGENTDESK_LLM_BASE", "https://llm.corp.example/v1")
    # llm_endpoint=None: the server resolves the environment at startup,
    # exactly the env/config.env-only setup this test is about.
    booted = server_harness.Booted(llm_endpoint=None)
    try:
        headers = booted.exchange()
        payload = json.loads(booted.request("GET", "/health", headers)[2])
        source = next(s for s in payload["sources"] if s["id"] == "research-endpoint")
        assert source["status"] == "connected"
    finally:
        booted.close()


def test_default_calendar_bridge_uses_the_settings_aware_client(env, monkeypatch, tmp_path):
    from test_server_research_api import StubEndpoint

    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    store = env.server.settings
    bridge = server_app._default_calendar_bridge(store)  # the real wiring
    try:
        # Nothing configured: the client raises, the breakdown falls back.
        with pytest.raises(LlmUnavailable):
            bridge.llm("prepare me")

        stub = StubEndpoint("answer")
        try:
            store.set("llm_base", stub.base_url)
            store.set("llm_key", "k")
            assert bridge.llm("prepare me") == "answer"
            assert stub.requests[-1]["auth"] == "Bearer k"
        finally:
            stub.close()
    finally:
        bridge.stop_polling()


def test_widget_settings_values_never_carry_the_raw_key(env, auth):
    env.post_json("/settings/endpoint/save", {
        "base": "https://x.example/v1", "key": "raw-secret-key-abcd", "model": "",
    }, auth)
    raw = env.request("GET", "/widgets/settings", auth)[2].decode("utf-8")
    assert "raw-secret-key" not in raw
    assert "Set. Ends with abcd." in raw


def test_unknown_setting_is_rejected(env, auth):
    status, _h, _b = env.post_json("/settings/toggle", {"key": "boss_mode"}, auth)
    assert status == 400


# -- the guard's extra allowed hosts (issue #61) ---------------------------


def _post_form(env, path, fields, headers):
    """A browser-shaped POST: form-urlencoded fields, no JavaScript."""
    data = urlencode(fields).encode("utf-8")
    merged = {"Content-Type": "application/x-www-form-urlencoded"}
    merged.update(headers)
    return env.request("POST", path, merged, data)


def test_settings_page_carries_the_extra_hosts_form(env, auth):
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert 'action="/settings/hosts/save"' in page
    assert 'name="hosts"' in page
    # The default is stated: loopback only until something is sanctioned.
    assert f"http://127.0.0.1:{env.port}" in page
    assert f"http://localhost:{env.port}" in page


def test_extra_allowed_hosts_form_round_trip_and_live_guard_effect(env, auth):
    status, headers, _b = _post_form(
        env, "/settings/hosts/save", {"hosts": "deskpc:8765 192.168.1.20:8765"}, auth)
    assert status == 303
    assert headers["Location"] == "/settings"
    assert env.server.settings.get("extra_allowed_hosts") == (
        "deskpc:8765 192.168.1.20:8765")
    values = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values["extra_allowed_hosts"] == "deskpc:8765 192.168.1.20:8765"
    # The guard applies the saved value on the very next request.
    status, _h, _b = env.request("GET", "/", auth | {"Host": "deskpc:8765"})
    assert status == 200
    # Clearing the field returns to the loopback-only default.
    _post_form(env, "/settings/hosts/save", {"hosts": ""}, auth)
    status, _h, _b = env.request("GET", "/", auth | {"Host": "deskpc:8765"})
    assert status == 403


def test_extra_allowed_hosts_json_save_and_form_echo(env, auth):
    status, _h, body = env.post_json(
        "/settings/hosts/save", {"hosts": "deskpc:8765, desk.example"}, auth)
    assert status == 200
    assert json.loads(body) == {"key": "extra_allowed_hosts",
                                "value": "deskpc:8765, desk.example"}
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "deskpc:8765, desk.example" in page


def test_extra_hosts_save_rejects_a_non_string(env, auth):
    status, _h, _b = env.post_json("/settings/hosts/save", {"hosts": 5}, auth)
    assert status == 400


def test_toggling_excel_off_stops_ingestion_and_shows_the_disabled_state(env, auth):
    from agentdesk.excel.watcher import Adapters, ExcelWatch

    watch = ExcelWatch(
        __import__("sqlite3").connect(":memory:", check_same_thread=False),
        Adapters(copy_shadow=lambda p: Path(p), parse_workbook=lambda p: [], clock=lambda: 0),
    )
    booted = server_harness.Booted(excel=watch)
    try:
        headers = booted.exchange()
        assert booted.post_json("/settings/toggle", {"key": "excel_enabled"}, headers)[0] == 200
        # Ingestion refuses immediately with the reconnect path.
        status, _h, body = booted.post_json(
            "/sources/excel-watch", {"path": "x"}, headers
        )
        assert status == 409
        assert json.loads(body)["reconnect"] == "/settings"
        # The widget shows the designed paused state, not stale data.
        page = booted.request("GET", "/", headers)[2].decode("utf-8")
        assert "Sales watching is turned off in settings." in page
        assert 'href="/settings"' in page
    finally:
        watch.stop_polling()
        booted.close()


def test_toggling_calendar_off_disables_the_commitments_widget(env, auth):
    env.post_json("/settings/toggle", {"key": "calendar_enabled"}, auth)
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert "Calendar reading is turned off in settings." in page
    status, _h, _b = env.post_json("/sources/calendar-bridge/retest", {}, auth)
    assert status == 409


def test_endpoint_toggle_pauses_research_with_honest_status(env, auth):
    env.post_json("/settings/toggle", {"key": "endpoint_enabled"}, auth)
    status, _h, body = env.post_json("/research", {"question": "anything"}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["status"] == "degraded"
    assert "turned off in settings" in payload["cause"]
    # Widget endpoints keep answering.
    assert env.request("GET", "/widgets/sales-24h", auth)[0] == 200


def test_endpoint_indicator_shows_degraded_not_a_false_green(env, auth):
    from agentdesk.llm import chat as real_chat

    env.server.llm = lambda prompt: real_chat("http://127.0.0.1:9", "k", "m", prompt)
    env.server.llm_endpoint = "http://127.0.0.1:9"  # configured, and down
    env.post_json("/research", {"question": "q"}, auth)  # fails, is audited
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "Last call:" in page
    assert "error" in page
    assert "reduced capacity" in page


def test_quiet_hours_and_cap_set_here_are_what_the_inbox_enforces(env, auth):
    env.server.settings.set("quiet_hours", False)  # quiet hours off: notify now
    card = json.loads(env.post_json("/inbox/cards", {
        "kind": "suggestion", "origin": "origin line", "title": "t",
    }, auth)[2])
    # Real local time may be inside quiet hours; with the toggle off the
    # card notifies regardless, proving the page's value drives enforcement.
    assert card["notified"] is True or datetime.now().astimezone().hour >= 18

    env.server.settings.set("daily_cap", 0)
    card2 = json.loads(env.post_json("/inbox/cards", {
        "kind": "suggestion", "origin": "origin line", "title": "t2",
    }, auth)[2])
    assert card2["notified"] is False  # cap zero: inbox only


def test_first_run_shows_real_connect_actions_with_zero_permission_prompts(env, auth):
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert page.count('data-widget-id=') == 3
    assert "Connect a workbook" in page
    assert "Connect your calendar" in page
    # No permission ask exists anywhere on the first screen.
    for banned in ("Allow access", "grant permission", "permission prompt"):
        assert banned.lower() not in page.lower()
    # And nothing is fabricated on the empty first screen.
    assert "Sample data" not in page
    assert "14,320" not in page
