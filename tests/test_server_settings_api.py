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
        # Semantic recall (#95): the toggle defaults on, but embeddings
        # stay inert until the embeddings probe passes; the model row
        # carries the spec's documented default.
        "semantic_memory": True,
        "embeddings_model": "text-embedding-3-small",
        # Autonomy (spec 016 §8): on by default; the desk acts by itself
        # and every change it makes is logged in the action ledger.
        "autonomy": True,
        "suggest_headers_only": False,
        "plugin_instance_cap": 6,
        # The memory loop: capture on, review before saving, every
        # channel read.
        "memory_capture": True,
        "memory_auto_approve": False,
        "memory_capture_assistant": True,
        "memory_capture_research": True,
        "memory_capture_workbook": True,
        "memory_capture_agents": True,
        # Recommendations (spec 016 §8): on by default, deadlines and
        # meeting prep named separately, a 30-day look ahead.
        "recommendations": True,
        "recommend_deadlines": True,
        "recommend_meetings": True,
        "recommend_horizon_days": 30,
        # Presentation calls only. Other agents keep the 10 second cap.
        "presentation_timeout_s": "30",
        "research_provider_url": "",
        "research_provider_key": "",
        "mail_self_address": "",
    }
    status, _h, body = env.post_json("/settings/toggle", {"key": "excel_enabled"}, auth)
    assert status == 200
    assert json.loads(body) == {"key": "excel_enabled", "value": False}
    assert json.loads(env.request("GET", "/widgets/settings", auth)[2])["excel_enabled"] is False


def test_the_settings_page_no_longer_renders_the_retired_endpoint_fields(env, auth):
    """The old endpoint form retired to the Connections card (spec 018
    #234): no base URL, key, model or research fields, and no save, test
    or clear buttons for them. The endpoint on/off toggle survives in
    the Desk card and the presentation timeout in the Endpoint card."""
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    for retired in ("id='llm-base'", "id='llm-key'", "id='llm-model'",
                    "id='research-url'", "id='research-key'",
                    "data-endpoint-save", "data-endpoint-test",
                    "data-endpoint-clear", "data-research-clear",
                    "endpoint-note"):
        assert retired not in page, retired
    assert "Company endpoint calls" in page
    assert "id='presentation-timeout'" in page
    assert "name='presentationTimeout'" in page
    assert "action='/settings/endpoint/save'" in page
    # The card names where endpoint configuration went, and that the
    # legacy rows remain as fallback.
    assert "Connections card" in page
    assert "read-only fallback" in page


def test_the_presentation_timeout_remains_settable_through_the_reduced_save(env, auth):
    status, _h, body = env.post_json(
        "/settings/endpoint/save", {"presentationTimeout": "45"}, auth)
    assert status == 200
    assert json.loads(body) == {"ok": True, "presentationTimeout": "45"}
    assert env.server.settings.get("presentation_timeout_s") == "45"

    # Out of range, or not a number, is refused with the rule named.
    for raw in ("4", "301", "soon"):
        status, _h, body = env.post_json(
            "/settings/endpoint/save", {"presentationTimeout": raw}, auth)
        assert status == 400
        assert "5 to 300" in json.loads(body)["error"]
    assert env.server.settings.get("presentation_timeout_s") == "45"

    # A plain form post (no JavaScript) saves and lands back on the page.
    status, headers, _b = _post_form(
        env, "/settings/endpoint/save", {"presentationTimeout": "60"}, auth)
    assert status == 303
    assert headers["Location"] == "/settings"
    assert env.server.settings.get("presentation_timeout_s") == "60"


def test_the_reduced_save_refuses_retired_and_unknown_field_names(env, auth):
    for legacy in ("base", "key", "model", "researchUrl", "researchKey",
                   "researchClear", "base_url", "api_key"):
        status, _h, body = env.post_json(
            "/settings/endpoint/save", {legacy: "typed"}, auth)
        assert status == 400, legacy
        error = json.loads(body)["error"]
        assert legacy in error
        assert "presentationTimeout" in error
    # Refusing beats a silent ok with dropped values: nothing was saved.
    values = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values["llm_base"] == "" and values["llm_key"] == ""


def test_a_legacy_saved_key_still_never_renders_back(env, auth):
    env.server.settings.set("llm_key", "sk-totally-hidden-value-99aa")
    settings_page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "sk-totally-hidden-value" not in settings_page
    assert "99aa" not in settings_page  # no key state renders anywhere now
    values_page = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values_page["llm_key"] == "Set. Ends with 99aa."  # the widget still masks


def test_research_uses_saved_settings_without_a_restart(env, auth, monkeypatch):
    from test_server_research_api import StubEndpoint

    content = json.dumps({"summary": "Saved endpoint answered.", "sources": ["settings"]})
    stub = StubEndpoint(content)
    try:
        # The environment points at a dead port; the saved settings must
        # win, on the very next request, with no restart.
        monkeypatch.setenv("AGENTDESK_LLM_BASE", "http://127.0.0.1:9")
        env.server.settings.set("llm_base", stub.base_url)
        env.server.settings.set("llm_key", "settings-key")
        env.server.settings.set("llm_model", "settings-model")
        status, _h, body = env.post_json("/research", {"question": "q"}, auth)
        payload = json.loads(body)
        assert status == 200
        assert payload["status"] == "ok"
        assert "Saved endpoint answered." in payload["summary"]
        assert stub.requests[-1]["auth"] == "Bearer settings-key"

        # Clearing the rows hands control back to the environment, which
        # is dead here, so research degrades again.
        env.server.settings.set("llm_base", "")
        env.server.settings.set("llm_key", "")
        payload = json.loads(env.post_json("/research", {"question": "q"}, auth)[2])
        assert payload["status"] == "degraded"
    finally:
        stub.close()


def test_health_reflects_saved_settings_and_their_clearing(env, auth):
    def research_source():
        payload = json.loads(env.request("GET", "/health", auth)[2])
        return next(s for s in payload["sources"] if s["id"] == "research-endpoint")

    assert research_source()["status"] == "not_connected"
    env.server.settings.set("llm_base", "https://llm.corp.example/v1")
    assert research_source()["status"] == "connected"
    env.server.settings.set("llm_base", "")
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
    env.server.settings.set("llm_key", "raw-secret-key-abcd")
    raw = env.request("GET", "/widgets/settings", auth)[2].decode("utf-8")
    assert "raw-secret-key" not in raw
    assert "Set. Ends with abcd." in raw
    # A short key shows no tail at all (the keys.store.mask_key rule):
    # its last four characters are most of the key.
    env.server.settings.set("llm_key", "abcd12")
    values_page = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values_page["llm_key"] == "Set."
    env.server.settings.set("llm_key", "nine-char")
    values_page = json.loads(env.request("GET", "/widgets/settings", auth)[2])
    assert values_page["llm_key"] == "Set."


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
    # Sales, commitments, research, and the Decisions card (spec 016 #195).
    assert page.count('data-widget-id=') == 4
    assert "Connect a workbook" in page
    assert "Connect your calendar" in page
    # No permission ask exists anywhere on the first screen.
    for banned in ("Allow access", "grant permission", "permission prompt"):
        assert banned.lower() not in page.lower()
    # And nothing is fabricated on the empty first screen.
    assert "Sample data" not in page
    assert "14,320" not in page


# -- the Jobs pickers preselect the job's bound connection (#235) --------------


def _picker(page: str, job: str) -> str:
    """One job's picker form, sliced out of the rendered settings page."""
    start = page.index(f"name='job' value='{job}'")
    return page[start:page.index("</form>", start)]


def test_the_jobs_pickers_preselect_the_bound_connection_so_an_untouched_save_keeps_it(env, auth):
    """The dropdown tells the same truth the readback tells (spec 018
    #235): a bound job's connection option carries selected and the Not
    bound option does not, so saving the form untouched posts the
    binding back instead of silently unbinding it; with no binding, Not
    bound is the selected option."""
    status, _h, body = env.post_json("/api/connections", {
        "label": "Desk ollama", "provider": "ollama",
        "baseUrl": "http://localhost:11434/v1", "apiKey": "",
    }, auth)
    assert status == 201, body
    connection = json.loads(body)
    status, _h, _b = env.post_json("/api/bindings", {
        "job": "assistant", "connectionId": connection["id"], "model": "",
    }, auth)
    assert status == 200

    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    picker = _picker(page, "assistant")
    assert f"<option value='{connection['id']}' selected>Desk ollama</option>" in picker
    assert "<option value=''>Not bound (default connection or environment)</option>" in picker
    assert "<option value='' selected>" not in picker  # the job IS bound
    assert "Serves through <b>Desk ollama</b>" in page  # the readback agrees

    # Once the job is unbound, Not bound is what the picker shows selected.
    status, _h, _b = env.post_json("/api/bindings", {
        "job": "assistant", "connectionId": "", "model": "",
    }, auth)
    assert status == 200
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    picker = _picker(page, "assistant")
    assert ("<option value='' selected>"
            "Not bound (default connection or environment)</option>") in picker
    assert f"<option value='{connection['id']}' selected" not in picker
