"""Pin the declarative dashboard route table.

The table in agentdesk.server.routes replaced the hand-written dispatch
chains; these tests freeze its shape and the statuses clients saw before
the refactor. Adding, dropping or reordering a route is therefore always a
deliberate edit here as well, and the dispatcher keeps answering the same
wire statuses it did before.
"""

import http.client
from urllib.parse import quote, urlencode

import pytest

from agentdesk.server import app as server_app
from agentdesk.server import routes
from server_harness import Booted

# (method, path, handler, prefix, arg, suffix), in dispatch order. Paths are
# literal unless prefix is true; a path may instead name wildcards ("*" is
# one path segment, "**" is any run of characters) and then match by pattern.
EXPECTED_GET_ROUTES = (
    ("GET", "/", "_send_index_or_dashboard", False, "none", ""),
    ("GET", "/health", "_send_health", False, "none", ""),
    ("GET", "/widgets/sales-24h", "_send_sales_status", False, "none", ""),
    ("GET", "/widgets/commitments", "_send_commitments_status", False, "none", ""),
    ("GET", "/walkthrough/calendar", "_send_walkthrough_calendar", False, "none", ""),
    ("GET", "/assistant", "_send_assistant_page", False, "none", ""),
    ("GET", "/agents", "_send_agents_page", False, "none", ""),
    ("GET", "/agents/templates/", "_agents_template_thumb", True, "rest", ""),
    ("GET", "/agents/runs/", "_agents_download", True, "rest", "/download"),
    ("GET", "/inbox", "_send_inbox_page", False, "none", ""),
    ("GET", "/activity", "_send_activity_redirect", False, "none", ""),
    ("GET", "/memory", "_send_memory_page", False, "none", ""),
    ("GET", "/memory/graph", "_memory_graph_page", False, "none", ""),
    ("GET", "/api/memory/loop", "_memory_loop_json", False, "none", ""),
    ("GET", "/api/memory/graph", "_memory_graph_json", False, "none", ""),
    ("GET", "/memory/sweep", "_memory_sweep_page", False, "none", ""),
    ("GET", "/memory/encrypt", "_memory_encrypt_page", False, "none", ""),
    ("GET", "/mail", "_send_mail_page", False, "none", ""),
    ("GET", "/capabilities", "_send_capabilities_page", False, "none", ""),
    ("GET", "/plugins", "_send_plugins_redirect", False, "none", ""),
    ("GET", "/peers", "_send_peers_page_request", False, "none", ""),
    ("GET", "/widgets/inbox", "_send_inbox_count", False, "none", ""),
    ("GET", "/settings/activity", "_send_audit_page", False, "none", ""),
    ("GET", "/settings", "_send_settings_page", False, "none", ""),
    ("GET", "/skills/", "_send_skill_markdown_rest", True, "rest", "/skill.md"),
    ("GET", "/audit/tail", "_send_audit_tail", False, "none", ""),
    ("GET", "/widgets/settings", "_send_settings_values", False, "none", ""),
    ("GET", "/wizard", "_wizard_request", True, "none", ""),
    ("GET", "/api/marketplace/", "_marketplace_api_get", True, "none", ""),
    ("GET", "/api/plugins", "_send_plugins_api_list", False, "none", ""),
    ("GET", "/api/registry", "_send_registry_listing", False, "none", ""),
    ("GET", "/api/peers", "_send_peers_api", False, "none", ""),
    ("GET", "/api/dashboard", "_send_dashboard_api", False, "none", ""),
    ("GET", "/api/desk-check", "_send_desk_check_api", False, "none", ""),
    ("GET", "/api/agent-loop", "_send_agent_loop_api", False, "none", ""),
    ("GET", "/api/preferences", "_send_preferences_values", False, "none", ""),
    ("GET", "/api/ledger", "_send_ledger_api", False, "none", ""),
    ("GET", "/api/connections", "_send_connections_json", False, "none", ""),
    ("GET", "/api/connections/", "_connection_models", True, "rest", "/models"),
    ("GET", "/api/bindings", "_send_bindings_json", False, "none", ""),
    ("GET", "/api/layout", "_send_layout_api", False, "none", ""),
    ("GET", "/api/plugins/**instances**", "_plugin_setup_get_request", False, "none", ""),
    ("GET", "/api/plugins/", "_plugin_record_get", True, "rest", ""),
    ("GET", "/audit/export.csv", "_send_audit_csv", False, "none", ""),
    ("GET", "/what-this-touches", "_send_touches_page", False, "none", ""),
    ("GET", "/static/app.css", "_send_styles_asset", False, "none", ""),
    ("GET", "/static/app.js", "_send_app_js_asset", False, "none", ""),
    ("GET", "/static/theme-boot.js", "_send_theme_boot_asset", False, "none", ""),
    ("GET", "/static/spa/", "_send_spa_asset", True, "rest", ""),
    ("GET", "/marketplace", "_send_marketplace_shell_request", False, "none", ""),
    ("GET", "/marketplace/", "_send_marketplace_shell_request", True, "none", ""),
)

EXPECTED_POST_ROUTES = (
    ("POST", "/api/preferences", "_preferences_write", False, "none", ""),
    ("POST", "/api/insight/draft", "_insight_draft", False, "none", ""),
    ("POST", "/insight/press", "_insight_press_page", False, "none", ""),
    ("POST", "/sources/excel-watch/pick", "_excel_watch_pick", False, "none", ""),
    ("POST", "/sources/excel-watch", "_excel_watch_register", False, "none", ""),
    ("POST", "/sources/excel-watch/retest", "_excel_watch_retest", False, "none", ""),
    ("POST", "/widgets/commitments/check", "_commitment_check", False, "none", ""),
    ("POST", "/sources/calendar-bridge/retest", "_calendar_bridge_retest", False, "none", ""),
    ("POST", "/sources/calendar-bridge/pick", "_calendar_bridge_pick", False, "none", ""),
    ("POST", "/sources/calendar-bridge/path", "_calendar_bridge_path", False, "none", ""),
    ("POST", "/sources/calendar-bridge/upload", "_calendar_bridge_upload", False, "none", ""),
    ("POST", "/sources/calendar-bridge/reset", "_calendar_bridge_reset", False, "none", ""),
    ("POST", "/research", "_research_ask", False, "none", ""),
    ("POST", "/inbox/cards", "_inbox_card_add", False, "none", ""),
    ("POST", "/inbox/cards/", "_inbox_accept", True, "rest", "/accept"),
    ("POST", "/inbox/cards/", "_inbox_dismiss", True, "rest", "/dismiss"),
    ("POST", "/inbox/cards/", "_inbox_edit", True, "rest", "/edit"),
    ("POST", "/inbox/cards/", "_inbox_snooze", True, "rest", "/snooze"),
    ("POST", "/inbox/cards/", "_inbox_more_info", True, "rest", "/more-info"),
    ("POST", "/inbox/dismissed/", "_inbox_restore", True, "rest", "/restore"),
    ("POST", "/memory/add", "_memory_add", False, "none", ""),
    ("POST", "/memory/", "_memory_edit_rest", True, "rest", "/edit"),
    ("POST", "/memory/", "_memory_delete_rest", True, "rest", "/delete"),
    ("POST", "/memory/recall", "_memory_recall", False, "none", ""),
    ("POST", "/memory/entities/merge", "_memory_entities_merge", False, "none", ""),
    ("POST", "/memory/sweep", "_memory_sweep", False, "none", ""),
    ("POST", "/memory/encrypt", "_memory_encrypt", False, "none", ""),
    ("POST", "/memory/retain", "_memory_retain", False, "none", ""),
    ("POST", "/memory/reflect", "_memory_reflect", False, "none", ""),
    ("POST", "/memory/embeddings/backfill", "_memory_embeddings_backfill", False, "none", ""),
    ("POST", "/api/memory/remove/preview", "_memory_remove_preview", False, "none", ""),
    ("POST", "/api/memory/remove", "_memory_remove_apply", False, "none", ""),
    ("POST", "/api/memory/undo", "_memory_undo", False, "none", ""),
    ("POST", "/api/desk-check/fix", "_desk_check_fix", False, "none", ""),
    ("POST", "/api/agent-loop/run", "_agent_loop_run", False, "none", ""),
    ("POST", "/api/ledger/undo", "_ledger_undo", False, "none", ""),
    ("POST", "/api/memory/facts/", "_memory_keep", True, "rest", "/keep"),
    ("POST", "/capabilities/", "_capabilities_retest", True, "rest", "/retest"),
    ("POST", "/inbox/consolidate", "_inbox_consolidate", False, "none", ""),
    ("POST", "/skills/", "_skill_run_rest", True, "rest", "/run"),
    ("POST", "/skills/", "_skill_undo_rest", True, "rest", "/undo"),
    ("POST", "/settings/toggle", "_settings_toggle", False, "none", ""),
    ("POST", "/api/connections", "_connection_create", False, "none", ""),
    ("POST", "/api/connections/", "_connection_update", True, "rest", "/update"),
    ("POST", "/api/connections/", "_connection_delete", True, "rest", "/delete"),
    ("POST", "/api/connections/", "_connection_test", True, "rest", "/test"),
    ("POST", "/api/connections/", "_connection_deep_check", True, "rest", "/check"),
    ("POST", "/api/bindings", "_binding_write", False, "none", ""),
    ("POST", "/api/layout", "_layout_save", False, "none", ""),
    ("POST", "/api/dashboard/view", "_dashboard_view_report", False, "none", ""),
    ("POST", "/settings/endpoint/save", "_endpoint_save", False, "none", ""),
    ("POST", "/settings/mail/folder", "_mail_folder_save", False, "none", ""),
    ("POST", "/settings/mail/address", "_mail_address_save", False, "none", ""),
    ("POST", "/settings/preferences", "_preferences_save", False, "none", ""),
    ("POST", "/settings/registry/path", "_registry_path_save", False, "none", ""),
    ("POST", "/settings/hosts/save", "_extra_hosts_save", False, "none", ""),
    ("POST", "/api/registry/install", "_registry_install", False, "none", ""),
    ("POST", "/plugins/registry-install", "_registry_install", False, "none", ""),
    ("POST", "/peers/code", "_peers_code_generate", False, "none", ""),
    ("POST", "/peers/pair", "_peers_pair", False, "none", ""),
    ("POST", "/peers/refresh", "_peers_refresh", False, "none", ""),
    ("POST", "/peers/install", "_peers_install", False, "none", ""),
    ("POST", "/peers/update", "_peers_update", False, "none", ""),
    ("POST", "/plugins/*/*", "_plugins_page_action_request", False, "none", ""),
    ("POST", "/mail/retest", "_mail_retest", False, "none", ""),
    ("POST", "/mail/", "_mail_draft_rest", True, "rest", "/draft"),
    ("POST", "/wizard", "_wizard_request", True, "none", ""),
    ("POST", "/api/marketplace/", "_marketplace_api_post", True, "none", ""),
    ("POST", "/api/plugins", "_plugin_api_post", True, "none", ""),
    ("POST", "/assistant/ask", "_assistant_ask", False, "none", ""),
    ("POST", "/agents/run", "_agents_run", False, "none", ""),
    ("POST", "/agents/runs/", "_agents_feedback", True, "rest", "/feedback"),
    ("POST", "/agents/runs/", "_agents_sources", True, "rest", "/sources"),
)

# Not worth pinning: these reach no response a client can depend on. The two
# pick routes open a native Tk dialog, and the retest route only surfaces the
# inert test watch raising (500 plus a traceback in the log).
SKIPPED_POST_ROUTES = {
    "/sources/excel-watch/pick": "opens a native Tk file dialog",
    "/sources/excel-watch/retest": "the inert test watch raises, answering 500",
    "/sources/calendar-bridge/pick": "opens a native Tk file dialog",
}

# Statuses recorded from the hand-written chains at the commit the table
# replaced (c8b27bf); the dispatcher must keep answering exactly these.
EXPECTED_GET_STATUS = {
    "/": 200,
    "/activity": 302,
    "/agents": 200,
    "/api/dashboard": 200,
    "/api/bindings": 200,
    "/api/desk-check": 200,
    "/api/agent-loop": 200,
    "/api/layout": 200,
    "/api/ledger": 200,
    "/api/memory/graph": 200,
    "/api/memory/loop": 200,
    "/api/peers": 200,
    "/api/connections": 200,
    "/api/plugins": 200,
    "/api/preferences": 200,
    "/api/registry": 200,
    "/assistant": 200,
    "/audit/export.csv": 200,
    "/audit/tail": 200,
    "/capabilities": 200,
    "/health": 200,
    "/inbox": 200,
    "/mail": 200,
    "/marketplace": 404,
    "/memory": 200,
    "/memory/encrypt": 200,
    "/memory/graph": 200,
    "/memory/sweep": 200,
    "/peers": 200,
    "/plugins": 302,
    "/settings": 200,
    "/settings/activity": 200,
    "/static/app.css": 200,
    "/static/app.js": 200,
    "/static/theme-boot.js": 200,
    "/walkthrough/calendar": 200,
    "/what-this-touches": 200,
    "/widgets/commitments": 200,
    "/widgets/inbox": 200,
    "/widgets/sales-24h": 200,
    "/widgets/settings": 200,
}

EXPECTED_POST_STATUS = {
    "/agents/run": 400,
    "/api/bindings": 400,
    "/api/connections": 400,
    "/api/dashboard/view": 200,
    "/api/insight/draft": 400,
    "/api/layout": 400,
    "/api/desk-check/fix": 400,
    "/api/agent-loop/run": 200,
    "/api/ledger/undo": 400,
    "/api/memory/remove": 400,
    "/api/memory/remove/preview": 400,
    "/api/memory/undo": 410,
    "/api/preferences": 200,
    "/api/registry/install": 400,
    "/assistant/ask": 400,
    "/inbox/cards": 400,
    "/inbox/consolidate": 200,
    "/insight/press": 200,
    "/mail/retest": 409,
    "/memory/add": 400,
    "/memory/embeddings/backfill": 409,
    "/memory/encrypt": 400,
    "/memory/entities/merge": 400,
    "/memory/recall": 400,
    "/memory/reflect": 200,
    "/memory/retain": 400,
    "/memory/sweep": 400,
    "/peers/code": 200,
    "/peers/install": 409,
    "/peers/pair": 400,
    "/peers/refresh": 303,
    "/peers/update": 409,
    "/plugins/registry-install": 400,
    "/research": 400,
    "/settings/endpoint/save": 200,
    "/settings/hosts/save": 400,
    "/settings/mail/folder": 400,
    "/settings/mail/address": 400,
    "/settings/preferences": 200,
    "/settings/registry/path": 303,
    "/settings/toggle": 400,
    "/sources/calendar-bridge/path": 400,
    "/sources/calendar-bridge/reset": 200,
    "/sources/calendar-bridge/retest": 200,
    "/sources/calendar-bridge/upload": 400,
    "/sources/excel-watch": 400,
    "/widgets/commitments/check": 400,
}


def rows(table):
    """Return a route table as comparable plain tuples."""
    return [
        (route.method, route.path, route.handler, route.prefix, route.arg, route.suffix)
        for route in table
    ]


def exact_paths(table, skipped=()):
    """Yield the literal paths of a table that are not prefix rows."""
    for route in table:
        if route.prefix or "*" in route.path or route.path in skipped:
            continue
        yield route.path


def test_every_table_handler_exists_on_the_dashboard_handler():
    for route in routes.GET_ROUTES + routes.POST_ROUTES:
        handler = getattr(server_app.DashboardHandler, route.handler, None)
        assert callable(handler), route


def test_no_duplicate_route_rows():
    keys = [
        (route.method, route.path, route.prefix, route.suffix)
        for route in routes.GET_ROUTES + routes.POST_ROUTES
    ]
    assert len(keys) == len(set(keys))


def test_get_table_is_frozen():
    assert rows(routes.GET_ROUTES) == list(EXPECTED_GET_ROUTES)


def test_post_table_is_frozen():
    assert rows(routes.POST_ROUTES) == list(EXPECTED_POST_ROUTES)


def test_match_prefers_an_exact_row_before_its_prefix():
    exact = routes.match("GET", "/marketplace")
    assert exact is not None
    assert exact.route.handler == "_send_marketplace_shell_request"
    assert exact.route.prefix is False

    shell = routes.match("GET", "/marketplace/installed")
    assert shell is not None
    assert shell.route.handler == "_send_marketplace_shell_request"
    assert shell.route.prefix is True

    listing = routes.match("GET", "/api/plugins")
    assert listing is not None
    assert listing.route.path == "/api/plugins"
    setup = routes.match("GET", "/api/plugins/excel-report/instances/main")
    assert setup is not None
    assert setup.route.handler == "_plugin_setup_get_request"
    record = routes.match("GET", "/api/plugins/excel-report")
    assert record is not None
    assert record.route.handler == "_plugin_record_get"
    assert record.argument == "excel-report"


def test_match_hands_the_remainder_only_to_rest_rows():
    asset = routes.match("GET", "/static/spa/assets/app.js")
    assert asset is not None
    assert asset.route.handler == "_send_spa_asset"
    assert asset.argument == "assets/app.js"

    skill = routes.match("GET", "/skills/7/skill.md")
    assert skill is not None
    assert skill.route.handler == "_send_skill_markdown_rest"
    assert skill.argument == "7"
    # The overlapping /skills/skill.md hands over an empty remainder, just as
    # the old branch handed int("") to the renderer and failed the same way.
    overlap = routes.match("GET", "/skills/skill.md")
    assert overlap is not None
    assert overlap.argument == ""

    accept = routes.match("POST", "/inbox/cards/abc/accept")
    assert accept is not None
    assert accept.route.handler == "_inbox_accept"
    assert accept.argument == "abc"

    draft = routes.match("POST", "/mail/hello%20world/draft")
    assert draft is not None
    assert draft.route.handler == "_mail_draft_rest"
    assert draft.argument == "hello%20world"


def test_match_handles_prefix_and_pattern_rows():
    wizard = routes.match("GET", "/wizardx")
    assert wizard is not None
    assert wizard.route.handler == "_wizard_request"
    assert wizard.route.prefix is True

    market = routes.match("POST", "/api/marketplace/search")
    assert market is not None
    assert market.route.handler == "_marketplace_api_post"

    action = routes.match("POST", "/plugins/foo/bar")
    assert action is not None
    assert action.route.handler == "_plugins_page_action_request"
    assert routes.match("POST", "/plugins/foo") is None


def test_match_rejects_unknown_methods_and_paths():
    assert routes.match("GET", "/nope") is None
    assert routes.match("GET", "/api/nope") is None
    assert routes.match("DELETE", "/health") is None
    assert routes.match("POST", "/health") is None
    assert routes.match("GET", "") is None


def test_every_exact_route_has_a_recorded_status():
    assert set(EXPECTED_GET_STATUS) == set(exact_paths(routes.GET_ROUTES))
    assert set(EXPECTED_POST_STATUS) == set(
        exact_paths(routes.POST_ROUTES, skipped=SKIPPED_POST_ROUTES)
    )


@pytest.fixture()
def booted(monkeypatch, tmp_path):
    """Boot the real server against a throwaway data directory."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    server = Booted()
    try:
        yield server
    finally:
        server.close()


def test_exact_get_routes_answer_as_before_the_refactor(booted):
    auth = booted.exchange()
    mismatches = {}
    for path in exact_paths(routes.GET_ROUTES):
        expected = EXPECTED_GET_STATUS[path]
        status = booted.request("GET", path, auth)[0]
        if status != expected:
            mismatches[path] = (status, expected)
    assert not mismatches


def test_exact_post_routes_answer_as_before_the_refactor(booted):
    auth = booted.exchange()
    mismatches = {}
    for path in exact_paths(routes.POST_ROUTES, skipped=SKIPPED_POST_ROUTES):
        expected = EXPECTED_POST_STATUS[path]
        status = booted.post_json(path, {}, auth)[0]
        if status != expected:
            mismatches[path] = (status, expected)
    assert not mismatches


def test_a_failure_after_a_redirect_cannot_answer_twice(booted, monkeypatch):
    """The 303 redirect marks its request answered (spec 017, 7c): a
    failure raised after it can never write a 500 over the finished
    response, so the next request on the keep-alive connection reads its
    own answer instead of the smuggled one."""
    original = server_app.DashboardHandler._send_redirect

    def redirect_then_break(self, location):
        original(self, location)
        raise RuntimeError("injected failure after the redirect")

    monkeypatch.setattr(server_app.DashboardHandler, "_send_redirect",
                        redirect_then_break)
    auth = booted.exchange()

    conn = http.client.HTTPConnection("127.0.0.1", booted.port, timeout=5)
    try:
        form = urlencode({"prepMinutes": "abc"}).encode("utf-8")
        headers = dict(auth)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request("POST", "/settings/preferences", body=form, headers=headers)
        first = conn.getresponse()
        first.read()
        assert first.status == 303
        assert first.getheader("Location") == (
            "/settings?preferences_error=" + quote(
                "Preparation minutes must be a whole number from 0 to 120."))
        # The same connection asks again: it must read health's answer,
        # not the 500 a double response would have left in the stream.
        conn.request("GET", "/health", headers=auth)
        second = conn.getresponse()
        second.read()
        assert second.status == 200
    finally:
        conn.close()
