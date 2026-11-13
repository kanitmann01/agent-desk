"""The layout API contract tests: GET/POST /api/layout and the payload.

The dashboard becomes personal (issue #66): the order, visibility and
titles of the cards live in a per-desk layout store, POSTed as the full
desired layout on every customize action and respected by the
/api/dashboard payload. Same rules as the other API suites: every test
walks the real HTTP seam, and nothing is invented. The pinned model:

- POST /api/layout is the full desired layout: the array order is the
  card order, and a row the save does not mention is dropped (which is
  how a stale plugin row is pruned once its plugin is gone).
- A key that is neither a builtin nor an installed plugin is refused
  with the named error layout:unknown-card.
- Hidden cards never appear in the payload's layout.cards but GET
  /api/layout still lists them, so hiding is always recoverable.
- Custom titles ride the layout entries; a plugin's card title in the
  payload is overridden by its custom layout title.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.plugins.runtime import PluginRuntime
from plugins_fixtures import valid_zip

BUILTINS = ["sales", "commitments", "research", "skills"]


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture()
def auth(booted):
    return booted.exchange()


def get_layout(booted, auth):
    status, _headers, body = booted.request("GET", "/api/layout", auth)
    assert status == 200
    return json.loads(body)


def post_layout(booted, auth, cards):
    return booted.post_json("/api/layout", {"cards": cards}, auth)


def get_dashboard(booted, auth):
    status, _headers, body = booted.request("GET", "/api/dashboard", auth)
    assert status == 200
    return json.loads(body)


def full_default(booted, auth):
    """The full listing GET /api/layout returns, as POSTable cards."""
    return get_layout(booted, auth)["cards"]


def test_layout_api_requires_a_session(booted):
    status, _h, _b = booted.request("GET", "/api/layout", booted.host_header())
    assert status == 401
    status, _h, _b = booted.post_json("/api/layout", {"cards": []}, booted.host_header())
    assert status == 401


def test_get_layout_lists_the_default_arrangement(booted, auth):
    cards = get_layout(booted, auth)["cards"]
    assert [c["key"] for c in cards] == BUILTINS
    assert all(c["hidden"] is False and c["title"] is None for c in cards)


def test_post_reorders_and_the_listing_round_trips(booted, auth):
    status, _h, body = post_layout(booted, auth, [
        {"key": "commitments"},
        {"key": "research"},
        {"key": "sales"},
        {"key": "skills"},
    ])
    assert status == 200
    cards = json.loads(body)["cards"]
    assert [c["key"] for c in cards] == ["commitments", "research", "sales", "skills"]
    # And the next GET agrees: the store, not the response, is the truth.
    assert [c["key"] for c in full_default(booted, auth)] == [
        "commitments", "research", "sales", "skills",
    ]


def test_the_dashboard_payload_order_follows_the_layout(booted, auth):
    post_layout(booted, auth, [
        {"key": "research"},
        {"key": "skills"},
        {"key": "commitments"},
        {"key": "sales"},
    ])
    payload = get_dashboard(booted, auth)
    assert [c["key"] for c in payload["layout"]["cards"]] == [
        "research", "skills", "commitments", "sales",
    ]


def test_hidden_cards_are_omitted_from_the_payload_but_recoverable(booted, auth):
    post_layout(booted, auth, [
        {"key": "sales", "hidden": True},
        {"key": "commitments"},
        {"key": "research"},
        {"key": "skills"},
    ])
    payload = get_dashboard(booted, auth)
    keys = [c["key"] for c in payload["layout"]["cards"]]
    assert "sales" not in keys
    # The layout endpoint still lists the hidden card, so Restore has
    # something to act on.
    listed = {c["key"]: c for c in full_default(booted, auth)}
    assert listed["sales"]["hidden"] is True


def test_custom_titles_ride_the_payload_layout_entries(booted, auth):
    post_layout(booted, auth, [
        {"key": "sales", "title": "Revenue, 24 h"},
        {"key": "commitments"},
        {"key": "research"},
        {"key": "skills"},
    ])
    payload = get_dashboard(booted, auth)
    by_key = {c["key"]: c for c in payload["layout"]["cards"]}
    assert by_key["sales"]["title"] == "Revenue, 24 h"
    assert by_key["commitments"]["title"] is None


def test_post_rejects_an_unknown_card_with_the_named_error(booted, auth):
    cards = full_default(booted, auth)
    cards.append({"key": "salez", "hidden": False, "title": None})
    status, _h, body = post_layout(booted, auth, cards)
    assert status == 400
    error = json.loads(body)
    assert error["error"] == "layout:unknown-card"
    assert error["key"] == "salez"
    # Nothing was saved.
    assert [c["key"] for c in full_default(booted, auth)] == BUILTINS


def test_post_rejects_a_not_installed_plugin_id(booted, auth):
    cards = full_default(booted, auth)
    cards.append({"key": "sales-delta-widget"})
    status, _h, body = post_layout(booted, auth, cards)
    assert status == 400
    assert json.loads(body)["error"] == "layout:unknown-card"


def test_post_rejects_a_malformed_body(booted, auth):
    status, _h, body = booted.post_json("/api/layout", {"cards": "sales"}, auth)
    assert status == 400
    assert json.loads(body)["error"] == "layout:invalid-card"


def test_installed_plugin_cards_join_the_layout_and_can_be_arranged(
        booted, auth, tmp_path):
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now="2026-11-11T16:00:00",
    )
    booted.server.plugins = runtime
    zip_path = valid_zip(tmp_path / "plugin.zip")
    status, _h, out = booted.post_json(
        "/api/plugins/install", {"zip_path": str(zip_path), "source": "zip"}, auth)
    assert status == 200, out
    # The installed plugin appears after the builtins, visible.
    listed = full_default(booted, auth)
    assert [c["key"] for c in listed] == BUILTINS + ["sales-delta-widget"]

    # Rename it and park it first: the payload follows both.
    post_layout(booted, auth, [
        {"key": "sales-delta-widget", "title": "My delta"},
        {"key": "sales"},
        {"key": "commitments"},
        {"key": "research"},
        {"key": "skills"},
    ])
    payload = get_dashboard(booted, auth)
    layout_keys = [c["key"] for c in payload["layout"]["cards"]]
    assert layout_keys[0] == "sales-delta-widget"
    # The custom title overrides the plugin card's display name in the
    # payload, so the card data and the layout agree.
    plugin_card = next(c for c in payload["plugins"]["cards"]
                       if c["id"] == "sales-delta-widget")
    assert plugin_card["title"] == "My delta"


def test_a_hidden_plugin_card_is_omitted_but_its_data_stays(booted, auth, tmp_path):
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now="2026-11-11T16:00:00",
    )
    booted.server.plugins = runtime
    zip_path = valid_zip(tmp_path / "plugin.zip")
    booted.post_json("/api/plugins/install",
                     {"zip_path": str(zip_path), "source": "zip"}, auth)
    cards = full_default(booted, auth)
    for card in cards:
        if card["key"] == "sales-delta-widget":
            card["hidden"] = True
    status, _h, _b = post_layout(booted, auth, cards)
    assert status == 200
    payload = get_dashboard(booted, auth)
    assert "sales-delta-widget" not in [c["key"] for c in payload["layout"]["cards"]]
    # The plugin's data section keeps the card (it is data, not the
    # card listing); the layout endpoint still lists it as hidden.
    assert any(c["id"] == "sales-delta-widget" for c in payload["plugins"]["cards"])
    listed = {c["key"]: c for c in full_default(booted, auth)}
    assert listed["sales-delta-widget"]["hidden"] is True


def test_an_uninstalled_plugins_row_is_pruned_by_the_next_save(booted, auth, tmp_path):
    runtime_dir = tmp_path
    runtime = PluginRuntime(
        plugins_dir=runtime_dir / "plugins",
        data_dir=runtime_dir / "data",
        workspace_dir=runtime_dir / "workspace",
        now="2026-11-11T16:00:00",
    )
    booted.server.plugins = runtime
    zip_path = valid_zip(runtime_dir / "plugin.zip")
    booted.post_json("/api/plugins/install",
                     {"zip_path": str(zip_path), "source": "zip"}, auth)
    cards = full_default(booted, auth)
    for card in cards:
        if card["key"] == "sales-delta-widget":
            card["hidden"] = True
            card["title"] = "Delta"
    post_layout(booted, auth, cards)
    assert "sales-delta-widget" in booted.server.layout.rows()

    # The plugin goes away (uninstall, or a fresh boot without it): the
    # listing honestly stops mentioning it...
    booted.server.plugins = PluginRuntime(
        plugins_dir=runtime_dir / "plugins-2",
        data_dir=runtime_dir / "data-2",
        workspace_dir=runtime_dir / "workspace-2",
        now="2026-11-11T16:00:00",
    )
    listed = full_default(booted, auth)
    assert [c["key"] for c in listed] == BUILTINS
    # ...and the next full save drops the stale row.
    status, _h, _b = post_layout(booted, auth, listed)
    assert status == 200
    assert "sales-delta-widget" not in booted.server.layout.rows()


def test_layout_still_answers_when_the_store_is_unavailable(booted, auth):
    booted.server.layout = None
    # GET falls back to the default resolution: the dashboard keeps its
    # canonical order rather than failing.
    cards = get_layout(booted, auth)["cards"]
    assert [c["key"] for c in cards] == BUILTINS
    # POST refuses honestly: nothing can be saved.
    status, _h, body = post_layout(booted, auth, [{"key": "sales"}])
    assert status == 503
    assert json.loads(body)["error"] == "the layout store is not available"
