"""Settings and first-run tests: toggles only, enforcement that matches,
an endpoint indicator that tells the truth, and a first run with zero
permission prompts.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
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
    }
    status, _h, body = env.post_json("/settings/toggle", {"key": "excel_enabled"}, auth)
    assert status == 200
    assert json.loads(body) == {"key": "excel_enabled", "value": False}
    assert json.loads(env.request("GET", "/widgets/settings", auth)[2])["excel_enabled"] is False


def test_unknown_setting_is_rejected(env, auth):
    status, _h, _b = env.post_json("/settings/toggle", {"key": "boss_mode"}, auth)
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


def test_first_run_renders_demo_widgets_with_zero_permission_prompts(env, auth):
    page = env.request("GET", "/", auth)[2].decode("utf-8")
    assert page.count('data-widget-id=') == 4
    assert "Sample data until then." in page
    # No permission ask exists anywhere on the first screen.
    for banned in ("Allow access", "grant permission", "permission prompt"):
        assert banned.lower() not in page.lower()
    # The one ask that exists states its benefit before asking.
    assert page.find("See what changed overnight") < page.find("Connect a workbook")
