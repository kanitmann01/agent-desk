"""Text fits its box on the server-rendered pages (spec 026).

The layout audit measured prose that spilled past its card, a stamp that
squeezed into three lines, a badge that wrapped a fixed phrase, and tables
that pushed the whole page sideways. These tests pin the rules that fix
those causes, read out of the one server sheet (pages.STYLES) and out of
the markup the real server renders.

The rule set, as the spec words it:

- R1 prose breaks rather than overflows (the body root rule);
- R2 a flex or grid item that holds text can shrink (min-width: 0);
- R3 a row with text beside controls wraps before it squeezes the text;
- R4 a chip never leaves its card;
- R6 a table that cannot fit scrolls inside its own wrapper;
- R7 the server sheet carries the same wrap contract as the SPA sheet.
"""

import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.server import pages
from agentdesk.server.commitments import render_commitments_widget


@pytest.fixture()
def booted():
    """One booted desk with every store and watcher faked in memory."""
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def _get(booted, path):
    """Fetch one server page through the real HTTP seam, requiring 200."""
    headers = booted.exchange()
    status, _headers, body = booted.request("GET", path, headers)
    assert status == 200, (status, path)
    return body.decode("utf-8")


def rule(selector):
    """The declarations of the first CSS rule for one exact selector.

    The selector is matched against the whole selector list since the
    previous rule, so `.btn` never resolves to `.cardform .btn`.
    """
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", pages.STYLES):
        last = match.group(1).split("}")[-1].split("\n")[-1].strip()
        if last == selector:
            return match.group(2)
    raise AssertionError(f"no {selector} rule in the server sheet")


def sheet_rule(css, selector):
    """The declarations for one selector in any stylesheet.

    Unlike rule(), this splits a selector list, so `.w-timeline` is found
    in the SPA's `.w-timeline,.w-checklist` rule too."""
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selector_text = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)
        selectors = [part.strip() for part in selector_text.split(",")]
        if selector in selectors:
            return match.group(2)
    raise AssertionError(f"no {selector} rule in the sheet")


def css_value(declarations, prop):
    """One property's value in a declaration block, stripped."""
    for part in declarations.split(";"):
        name, _sep, value = part.partition(":")
        if name.strip() == prop:
            return value.strip()
    raise AssertionError(f"no {prop} in {declarations}")


# -- R1: the root rule ----------------------------------------------------

def test_the_body_breaks_a_word_that_would_overflow():
    assert "overflow-wrap:anywhere" in rule("body")


def test_the_server_sheet_carries_the_nowrap_helper():
    assert ".nowrap{white-space:nowrap}" in pages.STYLES


def test_the_doc_pre_scrolls_a_long_line_instead_of_breaking_it():
    pre = rule(".doc pre")
    assert "overflow:auto" in pre
    assert "white-space:pre" in pre
    assert "overflow-wrap:normal" in pre


# -- R2 and R3: rows that hold text and controls --------------------------

def test_a_rail_entry_name_keeps_one_line_and_ellipsizes_in_the_rail():
    # The SPA's final rule: the label gives way, not the mark, and the
    # link's own aria-label is the reachable full name.
    label = rule(".rail .rail-label")
    assert "white-space:nowrap" in label
    assert "overflow:hidden" in label
    assert "text-overflow:ellipsis" in label
    assert "min-width:0" in label
    count = rule(".rail .count")
    assert "flex:none" in count
    assert "white-space:nowrap" in count


def test_the_inbox_card_kind_scrolls_instead_of_widening_the_header():
    assert "overflow-x:auto" in rule(".origin-line.nowrap")


def test_the_inbox_card_kind_keeps_one_line(booted):
    headers = booted.exchange()
    status, _headers, _body = booted.post_json(
        "/settings/toggle", {"key": "sample_data"}, headers
    )
    assert status == 200
    status, _headers, body = booted.request("GET", "/inbox", headers)
    assert status == 200
    assert "<span class='origin-line nowrap'>" in body.decode("utf-8")


def test_the_content_column_can_shrink():
    # main is the app grid's 1fr item. Without min-width: 0 its content's
    # min-content width widens the track past the app (2px at 1024), and
    # the whole shell scrolls sideways under the tripled-string stress.
    assert "min-width:0" in rule("main")


def test_the_topbar_wraps_and_its_title_can_shrink():
    assert "flex-wrap:wrap" in rule(".topbar")
    assert "min-width:0" in rule(".topbar h1")


def test_the_widget_header_wraps_and_the_stamp_keeps_its_own_line():
    head = rule(".w-head")
    assert "flex-wrap:wrap" in head
    assert "gap:12px" in head
    title = rule(".w-head h2")
    assert "min-width:0" in title
    assert "flex:1 1 120px" in title
    stamp = rule(".stamp")
    assert "white-space:nowrap" in stamp
    assert "flex:none" in stamp


def test_the_setting_row_wraps_its_control_below_its_text():
    row = rule(".setting-row")
    assert "flex-wrap:wrap" in row
    assert "min-width:0" in row
    label = rule(".setting-row > span")
    assert "flex:1 1 220px" in label
    assert "min-width:0" in label


def test_the_well_wraps_its_button_below_its_text_field():
    assert "flex-wrap:wrap" in rule(".well")
    assert "min-width:0" in rule(".well .q")
    assert "min-width:0" in rule(".well-input")
    assert "flex:none" in rule(".well > .btn")


def test_the_decision_row_wraps_before_it_squeezes_the_text():
    row = rule(".decisions li")
    assert "flex-wrap:wrap" in row
    text = rule(".decision-text")
    assert "flex:1 1 220px" in text
    assert "min-width:0" in text
    assert "flex:0 0 auto" in rule(".decision-actions")


def test_the_decisions_widget_emits_the_action_wrapper():
    # The SPA's wrapping decision row puts the text in one flexible column
    # and the controls in .decision-actions; the server card uses the same
    # wrapper so the shared rule can do its work.
    widget = pages.render_decisions_widget(
        [{"title": "A decision", "why": "Because", "href": "/agents", "cardId": "c1"}],
        datetime(2026, 11, 24, 9, 0),
    )
    assert '<span class="decision-actions">' in widget.body_html
    assert '<div class="decision-text">' in widget.body_html


# -- R4: chips ------------------------------------------------------------

def test_the_touch_badge_keeps_its_phrase_on_one_line_inside_the_card():
    badge = rule(".touch-badge")
    assert "white-space:nowrap" in badge
    assert "max-width:100%" in badge


def test_the_calendar_file_name_stays_whole_in_a_scroll_wrapper():
    body = render_commitments_widget({"state": "empty"}, datetime(2026, 11, 24, 9, 0))
    assert body is not None
    assert (
        '<span class="id-scroll"><code class="nowrap">agent-desk/calendar_sync.json'
        "</code></span>" in body.body_html
    )
    scroller = rule(".id-scroll")
    assert "overflow-x:auto" in scroller
    assert "max-width:100%" in scroller


# -- R6: tables and the SPA parity items (R7) -----------------------------

def test_the_button_label_keeps_one_line_and_a_long_one_scrolls():
    button = rule(".btn")
    assert "white-space:nowrap" in button
    assert "max-width:100%" in button
    assert "overflow-x:auto" in button


def test_the_numeric_cell_and_the_kpi_value_keep_one_line():
    assert "white-space:nowrap" in rule("table.rows .num")
    assert "white-space:nowrap" in rule(".kpi .value")


def test_a_table_scrolls_inside_its_own_wrapper():
    wrapper = rule(".table-scroll")
    assert "overflow-x:auto" in wrapper
    assert "max-width:100%" in wrapper


def test_the_action_cell_no_longer_forbids_wrapping():
    match = re.search(r"\.conn-actions\{([^}]*)\}", pages.STYLES)
    assert match is None or "white-space:nowrap" not in match.group(1)


def test_the_table_cell_breaks_only_a_word_that_cannot_fit():
    # anywhere would let the auto layout give a column one character;
    # break-word keeps the column's floor at the word and scrolls the
    # table instead of breaking every word inside it.
    assert "overflow-wrap:break-word" in rule("table.rows td")
    assert "overflow-wrap:break-word" in rule("table.rows th")


def test_the_server_sheet_mirrors_the_spa_timeline_contract():
    spa = (ROOT / "frontend" / "src" / "index.css").read_text(encoding="utf-8")
    timeline = sheet_rule(pages.STYLES, ".w-timeline")
    assert "display:flex" in timeline
    assert "flex-direction:column" in timeline
    assert "list-style:none" in timeline
    assert css_value(timeline, "padding") == "0"
    assert (css_value(sheet_rule(pages.STYLES, ".w-timeline li"),
                      "grid-template-columns")
            == css_value(sheet_rule(spa, ".w-timeline li"),
                         "grid-template-columns")
            == "max-content minmax(0,1fr)")
    server_meta = sheet_rule(pages.STYLES, ".w-timeline .w-list-meta")
    spa_meta = sheet_rule(spa, ".w-timeline .w-list-meta")
    for prop in ("grid-column", "grid-row", "white-space"):
        assert css_value(server_meta, prop) == css_value(spa_meta, prop), prop
    assert ("overflow-wrap:anywhere"
            in sheet_rule(pages.STYLES, ".w-list-primary"))
    server_secondary = sheet_rule(
        pages.STYLES, ".w-timeline .w-list-secondary")
    assert css_value(server_secondary, "grid-column") == "2"
    assert "overflow-wrap:anywhere" in server_secondary


def test_a_fresh_plugin_card_draws_the_timeline_classes():
    from agentdesk.server.app import DashboardHandler

    card = {
        "id": "timeline-plugin",
        "title": "Timeline plugin",
        "version": "1.0.0",
        "pilot": False,
        "freshness": "fresh",
        "checked_at": "2026-11-24T09:00:00",
        "payload": {"elements": [{
            "kind": "timeline",
            "items": [{
                "time": "2026-11-24 09:00",
                "title": "A title long enough to wrap",
                "meta": "A meta line long enough to wrap",
            }],
        }]},
    }
    widget = DashboardHandler._plugin_widget(None, card)
    assert '<ol class="w-timeline">' in widget.body_html
    for css_class in ("w-list-meta", "w-list-primary", "w-list-secondary"):
        assert f'class="{css_class}"' in widget.body_html, css_class


def test_a_plugin_table_rides_in_a_scroller_with_breaking_cells():
    from agentdesk.plugins.html import element_html

    markup = element_html({
        "kind": "table",
        "columns": ["Deal", "Owner"],
        "rows": [["A word too long for any column", "Priya"]],
    })
    assert '<div class="table-scroll"><table class="w-table">' in markup
    assert markup.endswith("</table></div>")
    assert "overflow-x:auto" in rule(".table-scroll")
    assert "overflow-wrap:break-word" in rule(".w-table td")
    assert "overflow-wrap:break-word" in rule(".w-table th")


# -- The markup the probe measured ---------------------------------------

class _LedgerEntry:
    """One undoable ledger row, the shape the activity page reads."""

    def __init__(self) -> None:
        """Fill the attributes the undo table interpolates."""
        self.id = "ledger-1"
        self.ts = 0.0
        self.why = "A reason"
        self.subject = "subject"
        self.action = "settings.save"
        self.undoable = True
        self.undone_by = None


def test_every_server_table_rides_in_a_scroll_wrapper(booted):
    from agentdesk.server import audit_view, settings_view

    assert "<div class='table-scroll'><table class='rows touches'>" in _get(
        booted, "/what-this-touches"
    )
    trail = audit_view._rows(
        [{"action": "settings.save", "detail": "d", "target": "", "status": "ok", "ts": 0}]
    )
    assert "<div class='table-scroll'>" in trail
    assert "<div class='table-scroll'>" in audit_view.questions_table(
        [{"ts": 0, "kind": "research", "text": "q"}]
    )
    assert "<div class='table-scroll'>" in audit_view._ledger_section([_LedgerEntry()])
    assert "<div class='table-scroll'>" in settings_view._agent_steps_table(
        [{"name": "read", "ok": True, "ms": 1, "note": ""}]
    )
    assert "<div class='table-scroll'>" in settings_view._connection_rows([])
    assert "<div class='table-scroll'>" in settings_view._record_card(
        [{"action": "settings.save", "ts": 0, "status": "ok"}], 1
    )


def test_the_touches_badge_phrase_is_rendered_whole(booted):
    page = _get(booted, "/what-this-touches")
    assert '<span class="touch-badge">not observed yet</span>' in page


# -- A1: a stamp is a scroller inside its own card ------------------------

def test_the_stamp_scrolls_inside_its_card_instead_of_leaving_it():
    stamp = rule(".stamp")
    assert "flex:none" in stamp
    assert "max-width:100%" in stamp
    assert "overflow-x:auto" in stamp


# -- A2: every table on every rendered page rides in a wrapper -------------

TABLE_PAGES = (
    "/", "/inbox", "/assistant", "/agents", "/memory", "/mail",
    "/capabilities", "/peers", "/settings", "/settings/activity",
    "/walkthrough/calendar", "/what-this-touches", "/wizard",
)


def test_every_rendered_page_wraps_every_rows_table(booted):
    headers = booted.exchange()
    status, _headers, _body = booted.post_json(
        "/settings/toggle", {"key": "sample_data"}, headers
    )
    assert status == 200
    for path in TABLE_PAGES:
        status, _headers, body = booted.request("GET", path, headers)
        assert status == 200, path
        page = body.decode("utf-8")
        for match in re.finditer(r"<table\b([^>]*)>", page):
            attrs = match.group(1)
            if "rows" not in attrs:
                continue
            assert page[: match.start()].endswith("<div class='table-scroll'>"), (
                path,
                attrs,
            )
            close = page.find("</table>", match.end())
            assert close != -1, (path, attrs)
            tail = page[close: close + len("</table></div>")]
            assert tail == "</table></div>", (path, attrs, tail)


def test_the_sales_examples_table_rides_in_a_wrapper():
    from agentdesk.server.sales import render_sales_widget

    widget = render_sales_widget({
        "state": "healthy",
        "last_ok_ts": 0.0,
        "reference_ts": 0.0,
        "rowsSeen": 1,
        "delta": {"added": [["Atlas ERP", 2]], "removed": [], "unchanged": 0},
    })
    assert "<div class='table-scroll'><table class='rows'>" in widget.body_html
    assert "</table></div>" in widget.body_html


# -- A4: the legacy plugin card offers a re-test only when it can work ----

def test_the_legacy_plugin_card_offers_retest_only_when_it_can_change():
    from agentdesk.server import app as server_app

    base = {
        "id": "sample-plugin", "title": "Sample plugin", "version": "1.0.0",
        "pilot": False, "state": "enabled", "freshness": "attention",
        "checked_at": "", "pluginId": "sample-plugin", "instanceId": "main",
        "payload": None,
    }
    stuck = dict(base, cause="This desk cannot read web pages yet.")
    widget = server_app.DashboardHandler._plugin_widget(None, stuck)
    assert "Re-test" not in widget.body_html
    assert "Re-test available" not in widget.freshness.stamp

    no_file = dict(base, cause="data source has no file")
    widget = server_app.DashboardHandler._plugin_widget(None, no_file)
    assert "Re-test" not in widget.body_html
    assert "Remove the plugin" in widget.body_html

    transient = dict(base, cause="no file matches ${workspace}/reports/*.xlsx")
    widget = server_app.DashboardHandler._plugin_widget(None, transient)
    assert "Re-test" in widget.body_html
    assert widget.freshness.stamp == "Re-test available"


def test_a_stale_source_is_stamped_stale_not_live():
    from agentdesk.server import app as server_app

    card = {
        "id": "audit-overflow", "title": "Regional Pipeline", "version": "0.1.0",
        "pilot": True, "state": "enabled", "freshness": "fresh",
        "checked_at": "2020-01-01T00:00:00",
        "payload": {
            "elements": [{"kind": "metric", "value": "123456789012345",
                          "label": "Pipeline"}],
            "source": {"state": "stale", "reason": "older-than-window"},
        },
    }
    widget = server_app.DashboardHandler._plugin_widget(None, card)
    assert widget.freshness.status == "attention"
    assert widget.freshness.stamp == "Stale since 1 Jan 2020, 00:00"
    assert "123456789012345" in widget.body_html

    card["checked_at"] = datetime.now().strftime("%Y-%m-%dT09:05:00")
    widget = server_app.DashboardHandler._plugin_widget(None, card)
    assert widget.freshness.stamp == "Stale since 09:05"


# -- B: the server sheet matches the SPA wrap contract ---------------------

TWINS = (
    (".rail a,.rail .nav-off", "min-width:0"),
    (".brand b,.brand-name", "min-width:0"),
    (".rail .count", "flex:none"),
    (".rail .user .avatar", "min-width:0"),
    (".rail .user .avatar", "max-width:100%"),
    (".rail .user .avatar", "white-space:nowrap"),
    (".rail .user .avatar", "overflow:hidden"),
    (".rail .user .avatar", "text-overflow:ellipsis"),
    (".rail .user .avatar", "text-align:center"),
    (".rail .rail-label", "min-width:0"),
    (".rail .rail-label", "white-space:nowrap"),
    (".rail .rail-label", "overflow:hidden"),
    (".rail .rail-label", "text-overflow:ellipsis"),
    (".rail-toggle", "max-width:100%"),
    (".rail-toggle", "min-width:0"),
    (".rail-toggle-label", "min-width:0"),
    (".rail-toggle-label", "white-space:nowrap"),
    (".rail-toggle-label", "overflow:hidden"),
    (".rail-toggle-label", "text-overflow:ellipsis"),
    (".w-head", "flex-wrap:wrap"),
    (".w-head h2", "flex:1 1 120px"),
    (".w-head h2", "min-width:0"),
    (".w-head h2", "overflow-wrap:anywhere"),
    (".stamp", "flex:none"),
    (".stamp", "max-width:100%"),
    (".badge-pilot", "flex:none"),
    (".btn", "white-space:nowrap"),
    (".btn", "max-width:100%"),
    (".decision-actions", "flex-wrap:wrap"),
    (".decision-actions", "justify-content:flex-end"),
    (".decision-actions", "max-width:100%"),
    (".follow", "max-width:100%"),
    (".src", "max-width:100%"),
)


@pytest.mark.parametrize("selector,declaration", TWINS)
def test_the_server_sheet_matches_the_spa_wrap_contract(selector, declaration):
    assert declaration in rule(selector), (selector, declaration)


def test_the_legacy_figure_prints_in_full_without_a_scroll_well():
    # The figure's container takes the full card width (a column), and the
    # value stays on one line: no break, no cut, no scroll well.
    assert "flex-direction:column" in rule(".kpi")
    value = rule(".kpi .value")
    assert "white-space:nowrap" in value
    assert "overflow" not in value
    assert "max-width" not in value


# -- C1 and C2: the honest home screen ------------------------------------

def test_a_plugin_with_no_widget_keeps_no_card_but_stays_installed(booted):
    from plugins_fixtures import valid_zip

    headers = booted.exchange()
    with tempfile.TemporaryDirectory() as tmp:
        plugin_zip = valid_zip(
            Path(tmp) / "no-widget.zip",
            overrides={
                "contributes": {"widgets": []},
                "permissions": {"filesystem": {"read": [], "write": []}},
            },
        )
        status, _headers, out = booted.post_json(
            "/api/plugins/install",
            {"zip_path": str(plugin_zip), "source": "zip"},
            headers,
        )
        assert status == 200, out
    dashboard = json.loads(booted.request("GET", "/api/dashboard", headers)[2])
    assert dashboard["plugins"]["cards"] == []
    installed = json.loads(
        booted.request("GET", "/api/marketplace/installed", headers)[2]
    )
    row = next(item for item in installed["plugins"] if item["id"] == "sales-delta-widget")
    assert row["status"]["cause"] == "This plugin adds no card to your dashboard."


def test_the_card_filter_keeps_setup_cards():
    from agentdesk.server.dashboard_state import dashboard_plugin_cards

    no_widget = {
        "id": "empty",
        "cause": "This plugin adds no card to your dashboard.",
        "state": "enabled",
    }
    setup = {
        "id": "tracker",
        "cause": "",
        "state": "enabled",
        "payload": {"setup": {"step": "columns"}},
    }
    assert dashboard_plugin_cards([no_widget, setup]) == [setup]


def test_a_runner_that_never_ran_claims_no_checked_at(tmp_path):
    from agentdesk.plugins.execute import PluginWidgetRunner

    runner = PluginWidgetRunner(tmp_path / "workspace")
    status = runner.status("never-attached")
    assert status["cause"] == "data source has not run"
    assert status["checked_at"] == ""


# -- C3: reader language for causes ---------------------------------------

def test_the_no_transport_cause_speaks_reader_language(tmp_path):
    from agentdesk.plugins.sources import SourceContext, read_source

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ctx = SourceContext(
        plugin_id="p",
        workspace_dir=workspace,
        data_dir=tmp_path / "data",
        now=datetime(2026, 11, 24, 9, 0),
        network_allow=("https://api.example.com/*",),
        transport=None,
    )
    result = read_source(
        {
            "type": "http-get",
            "url": "https://api.example.com/data",
            "allow": ["api.example.com"],
        },
        ctx,
    )
    assert result.reason == "no-transport"
    assert result.human == "This desk cannot read web pages yet."


def test_a_plugin_with_no_widget_speaks_reader_language(tmp_path):
    from agentdesk.plugins.execute import PluginWidgetRunner

    runner = PluginWidgetRunner(tmp_path / "workspace")
    status = runner.attach(
        "p",
        {"contributes": {"widgets": []}},
        tmp_path / "version",
        tmp_path / "data",
    )
    assert status["cause"] == "This plugin adds no card to your dashboard."
    assert status["checked_at"] == ""


# -- C4 and C5: marketplace transport and desk health ---------------------

def test_the_marketplace_payloads_report_the_desk_transport(booted, tmp_path):
    from agentdesk.plugins.execute import PluginWidgetRunner
    from agentdesk.plugins.runtime import PluginRuntime

    headers = booted.exchange()

    def payload(path):
        status, _headers, body = booted.request("GET", path, headers)
        assert status == 200, (path, body[:120])
        return json.loads(body)

    catalog = payload("/api/marketplace/catalog")
    assert catalog["deskNetwork"] is False
    assert payload("/api/marketplace/installed")["deskNetwork"] is False
    assert payload("/api/marketplace/packs")["deskNetwork"] is False
    entry = catalog["entries"][0]
    detail = payload("/api/marketplace/plugin/" + entry["id"])
    assert detail["deskNetwork"] is False
    publisher = payload("/api/marketplace/publisher/" + entry["publisher"])
    assert publisher["deskNetwork"] is False

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    booted.server.plugins = PluginRuntime(
        plugins_dir=workspace.parent / "plugins",
        data_dir=workspace.parent / "plugin-data",
        workspace_dir=workspace,
        runner=PluginWidgetRunner(workspace, http_transport=lambda *args: None),
    )
    assert payload("/api/marketplace/catalog")["deskNetwork"] is True


def test_desk_health_counts_only_the_three_desk_sources(booted):
    from agentdesk.server.core import SOURCE_IDS

    headers = booted.exchange()
    payload = json.loads(booted.request("GET", "/api/dashboard", headers)[2])
    assert payload["sources"]["total"] == 3
    assert [item["id"] for item in payload["sources"]["items"]] == list(SOURCE_IDS)
