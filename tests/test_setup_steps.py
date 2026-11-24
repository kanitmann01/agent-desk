"""The desk tells the truth about the AI and offers its three setup steps.

Spec 022, ticket 022-1. Two things went wrong for a real user and are
pinned here from the outside, through the surfaces a person meets:

- a saved key made the assistant work while the dashboard still said the
  Research source was off, because the dashboard read the pre-018 endpoint
  rows instead of the connections the hub resolves;
- nothing on a fresh desk said that an AI key was the first thing to add,
  and asking without one answered with a sentence about jobs and
  environment variables.

The setup object is the home screen's three-step list. A step is done
only by something real: the sample set keeps the tiles alive and must
never make the desk look finished.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.keys import health
from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain
from agentdesk.server import dashboard_state

STEP_IDS = ["ai", "workbook", "calendar"]


def _instant_check(base_url, api_key, extra_headers=None, timeout=None):
    """A save-time prober that answers instantly and hermetically."""
    return health.ProbeResult(health.OUTCOME_OK, "", ["hermetic-model"])


def _desk(**kwargs):
    """A booted desk with an in-memory keychain and nothing else saved."""
    kwargs.setdefault("keychain", KeychainSecrets(MemoryKeychain()))
    kwargs.setdefault("connection_check", _instant_check)
    return server_harness.Booted(**kwargs)


def _dashboard(booted, auth) -> dict:
    """The dashboard payload, as the home screen reads it."""
    status, _h, body = booted.request("GET", "/api/dashboard", auth)
    assert status == 200
    return json.loads(body)


def _source(payload: dict, source_id: str) -> dict:
    """One source's status row."""
    return next(item for item in payload["sources"]["items"] if item["id"] == source_id)


def _save_key(booted, auth) -> None:
    """Save one connection the way the Settings form does."""
    status, _h, _body = booted.post_json("/api/connections", {
        "provider": "custom", "label": "My AI",
        "baseUrl": "http://127.0.0.1:9/v1", "apiKey": "sk-test-0001"}, auth)
    assert status == 201


def test_a_fresh_desk_lists_three_steps_in_order_and_none_is_done():
    booted = _desk()
    try:
        auth = booted.exchange()
        setup = _dashboard(booted, auth)["setup"]
        assert [step["id"] for step in setup["steps"]] == STEP_IDS
        assert [step["done"] for step in setup["steps"]] == [False, False, False]
        for step in setup["steps"]:
            assert step["title"] and step["reason"] and step["href"]
        assert setup["sample"] is False
        # Nothing real is connected, so the strip offers sample data.
        assert setup["sampleOffer"] is True
    finally:
        booted.close()


def test_the_first_step_is_the_ai_key_and_leads_to_settings():
    booted = _desk()
    try:
        auth = booted.exchange()
        first = _dashboard(booted, auth)["setup"]["steps"][0]
        assert first["title"] == "Add your AI key"
        assert first["href"] == "/settings#ai"
        assert first["action"] is None
    finally:
        booted.close()


def test_a_saved_key_makes_the_dashboard_report_the_ai_connected():
    booted = _desk()
    try:
        auth = booted.exchange()
        assert _source(_dashboard(booted, auth), "research-endpoint")["status"] == "not_connected"
        _save_key(booted, auth)
        payload = _dashboard(booted, auth)
        assert _source(payload, "research-endpoint")["status"] == "connected"
        assert _source(payload, "research-endpoint")["detail"] == "AI connected."
        assert [step["done"] for step in payload["setup"]["steps"]] == [True, False, False]
    finally:
        booted.close()


def test_a_cleared_key_never_counts_as_the_ai_being_connected():
    """A connection whose stored key was removed cannot serve a call, so
    the desk must not claim it can: the dashboard's AI source, the setup
    step and Settings all read the same resolution hub, and asking the
    assistant says what to do instead of failing on an empty key."""
    booted = _desk()
    try:
        auth = booted.exchange()
        _save_key(booted, auth)
        created = json.loads(
            booted.request("GET", "/api/connections", auth)[2])["connections"][0]
        # Remove the stored key the way the Settings form's action does.
        status, _h, _b = booted.post_json(
            f"/api/connections/{created['id']}/update", {
                "label": "My AI", "provider": "custom",
                "baseUrl": "http://127.0.0.1:9/v1", "keyClear": "1",
            }, auth)
        assert status == 200
        payload = _dashboard(booted, auth)
        assert _source(payload, "research-endpoint")["status"] == "not_connected"
        assert _source(payload, "research-endpoint")["detail"] == "No AI key saved yet."
        assert [step["done"] for step in payload["setup"]["steps"]] == [False, False, False]
        page = booted.request("GET", "/settings", auth)[2].decode("utf-8")
        assert "No AI key is saved yet. Add one above first." in page
        status, _h, body = booted.post_json(
            "/assistant/ask", {"question": "Hello?"}, auth)
        assert status == 200
        result = json.loads(body)
        assert result["status"] == "degraded"
        assert "No AI key is saved yet" in result["cause"]
    finally:
        booted.close()


def test_a_fresh_desk_says_no_ai_key_is_saved():
    booted = _desk()
    try:
        auth = booted.exchange()
        row = _source(_dashboard(booted, auth), "research-endpoint")
        assert row["status"] == "not_connected"
        assert row["detail"] == "No AI key saved yet."
    finally:
        booted.close()


def test_the_assistant_page_without_an_ai_links_to_the_key_form():
    booted = _desk()
    try:
        auth = booted.exchange()
        _status, _h, body = booted.request("GET", "/assistant", auth)
        page = body.decode("utf-8")
        assert 'href="/settings#ai"' in page
        assert "Add your AI key" in page
        assert "unbound" not in page.lower()
        assert "AGENTDESK_" not in page
    finally:
        booted.close()


def test_asking_without_an_ai_says_so_in_plain_words():
    booted = _desk()
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json("/assistant/ask", {"question": "Hello?"}, auth)
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "degraded"
        assert "No AI key is saved yet" in payload["cause"]
        assert "unbound" not in payload["cause"]
        assert "AGENTDESK_" not in payload["cause"]
    finally:
        booted.close()


class _Workbook:
    """Only what the setup steps ask of the workbook watch."""

    def __init__(self, path) -> None:
        """Remember the registered path."""
        self.registered_path = path


class _Calendar:
    """Only what the setup steps ask of the calendar bridge."""

    def __init__(self, path, state: str = "healthy") -> None:
        """Remember the file in use and its state."""
        self._path = path
        self._state = state

    def status(self) -> dict:
        """The bridge's status shape."""
        return {"state": self._state, "path": self._path}


def test_sample_sources_do_not_complete_a_step(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    sample = tmp_path / "sample"
    sample.mkdir()
    setup = dashboard_state.setup_payload(
        ai_connected=True, sample=True,
        excel=_Workbook(str(sample / "sample-sales.xlsx")),
        calendar=_Calendar(str(sample / "sample-calendar.json")))
    assert [step["done"] for step in setup["steps"]] == [True, False, False]
    assert setup["sample"] is True
    # Sample wiring is not a real source: the offer stays.
    assert setup["sampleOffer"] is True


def test_real_sources_complete_their_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    setup = dashboard_state.setup_payload(
        ai_connected=True, sample=False,
        excel=_Workbook(str(elsewhere / "pipeline.xlsx")),
        calendar=_Calendar(str(elsewhere / "calendar.json")))
    assert [step["done"] for step in setup["steps"]] == [True, True, True]
    assert setup["sampleOffer"] is False


def test_an_empty_calendar_is_not_connected(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    setup = dashboard_state.setup_payload(
        ai_connected=False, sample=False,
        excel=_Workbook(None), calendar=_Calendar(None, state="empty"))
    assert [step["done"] for step in setup["steps"]] == [False, False, False]
    assert setup["steps"][1]["action"] == "/sources/excel-watch/pick"
    assert setup["steps"][2]["href"] == "/walkthrough/calendar"
