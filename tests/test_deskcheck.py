"""The desk check contract: findings, the registry, and the five checks.

Every check is exercised against real collaborators (a real SettingsStore, a
real InboxStore, a real ExcelWatch/CalendarBridge, a real PluginRuntime over a
temp lockfile), and the expected values come from the spec's check table, not
from the implementation.
"""

import json
import sqlite3
import time
from pathlib import Path

import pytest

import server_harness
from agentdesk import deskcheck
from agentdesk.calendar.watcher import Adapters as CalendarAdapters
from agentdesk.calendar.watcher import CalendarBridge
from agentdesk.deskcheck import (
    REGISTRY,
    CheckResult,
    DeskContext,
    Finding,
    run_checks,
    summary,
)
from agentdesk.excel.watcher import Adapters as ExcelAdapters
from agentdesk.excel.watcher import ExcelWatch
from agentdesk.inbox.store import InboxStore
from agentdesk.plugins.runtime import PluginRuntime
from agentdesk.settings import SettingsStore

NOW = 1700000000.0

CHECK_IDS = [
    "inbox-unreadable-rows",
    "sample-not-wired",
    "source-on-not-connected",
    "retired-plugins-installed",
    "sample-plugin-not-installed",
    "fix-failing",
]


# ---- real collaborators over temp files ----------------------------------


def settings_store(**values):
    """A real settings store, defaulted like the app then overridden."""
    store = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False),
                          lambda: NOW)
    for key, value in values.items():
        store.set(key, value)
    return store


def inbox_store(tmp_path):
    """A real inbox store with nothing in it."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    return InboxStore(sqlite3.connect(tmp_path / "inbox.sqlite3",
                                      check_same_thread=False), lambda: NOW)


def inbox_with_raw_row(tmp_path):
    """A real inbox store holding one row written by a build this one doesn't know."""
    store = inbox_store(tmp_path)
    store.conn.execute(
        "INSERT INTO cards (id, kind, origin, title, body, action_label,"
        " status, created_ts, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("raw-commitment", "commitment", "Written by another build",
         "A card this build cannot read", "", "", "waiting", NOW, "{}"),
    )
    store.conn.commit()
    return store


def excel_watch(conn=None):
    """A real workbook watch with nothing registered."""
    adapters = ExcelAdapters(
        copy_shadow=lambda path: Path(path),
        parse_workbook=lambda path: [],
        clock=lambda: NOW,
    )
    return ExcelWatch(conn or sqlite3.connect(":memory:", check_same_thread=False),
                      adapters)


def calendar_bridge(conn=None):
    """A real calendar bridge with nothing connected."""
    adapters = CalendarAdapters(read_calendar=lambda: None, clock=lambda: NOW)
    return CalendarBridge(conn or sqlite3.connect(":memory:", check_same_thread=False),
                          adapters)


def plugin_runtime(tmp_path, **records):
    """A real plugin runtime over a temp lockfile carrying the given entries."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    entries = {plugin_id: {"id": plugin_id, "state": state}
               for plugin_id, state in records.items()}
    (plugins_dir / "lockfile.json").write_text(
        json.dumps({"plugins": entries, "graveyard": {}}), encoding="utf-8")
    return PluginRuntime(plugins_dir, tmp_path / "plugin-data", tmp_path / "workspace")


def context(tmp_path, **kw):
    """A desk context over real collaborators; anything not named is absent."""
    values = dict(settings=None, inbox=None, excel=None, calendar=None,
                  plugins=None, catalog_ids=frozenset(), data_dir=tmp_path,
                  ledger=None, clock=lambda: NOW)
    values.update(kw)
    return DeskContext(**values)


def fired(check_id, ctx):
    """The findings one registered check raised for this context."""
    return [finding for finding in run_checks(ctx).findings
            if finding.id == check_id]


# ---- the registry and the runner -----------------------------------------


def test_registry_runs_the_checks_in_registration_order():
    assert [check_id for check_id, _ in REGISTRY] == CHECK_IDS


def test_crashing_check_becomes_fatal(monkeypatch):
    def boom(ctx, should_fix):
        raise RuntimeError("kaboom")

    healthy = Finding(id="healthy", title="Healthy", cause="Nothing to do.",
                      severity="attention", confident=False, fix="none",
                      fix_label="")

    def fine(ctx, should_fix):
        return CheckResult(findings=[healthy])

    monkeypatch.setattr(deskcheck.core, "REGISTRY",
                        [("boom", boom), ("healthy", fine)])
    result = run_checks(context(Path(".")))

    crashed = [finding for finding in result.findings
               if finding.id == "deskcheck-crashed:boom"]
    assert len(crashed) == 1
    assert crashed[0].severity == "fatal"
    assert crashed[0].confident is False
    assert crashed[0].fix == "none"
    assert "RuntimeError" in crashed[0].cause
    assert result.failed == {"deskcheck-crashed:boom": "RuntimeError: kaboom"}
    assert [finding.id for finding in result.findings] == [
        "deskcheck-crashed:boom", "healthy"]


def test_summary_counts_attention_and_names_the_top_finding():
    fatal = Finding(id="fatal-one", title="Fatal", cause="Broke.",
                    severity="fatal", confident=False, fix="none", fix_label="")
    attention = Finding(id="attention-one", title="Attention", cause="Look.",
                        severity="attention", confident=False, fix="none",
                        fix_label="")
    quiet = Finding(id="info-one", title="Info", cause="Note.",
                    severity="info", confident=False, fix="none", fix_label="")

    got = summary(CheckResult(findings=[quiet, attention, fatal]))
    assert got["attention"] == 2
    assert got["top"]["id"] == "fatal-one"
    assert got["top"]["severity"] == "fatal"

    assert summary(CheckResult()) == {"attention": 0, "top": None}


# ---- the five checks ------------------------------------------------------


CASES = [
    (
        "inbox-unreadable-rows",
        lambda tmp_path: context(tmp_path, settings=settings_store(),
                                 inbox=inbox_with_raw_row(tmp_path)),
        lambda tmp_path: context(tmp_path, settings=settings_store(),
                                 inbox=inbox_store(tmp_path / "quiet")),
        {
            "title": "1 inbox card this version cannot read",
            "severity": "attention",
            "confident": True,
            "fix": "auto",
            "fix_label": "Fix it",
            "href": "",
            "detail": {"count": 1, "kinds": ["commitment"]},
        },
    ),
    (
        "sample-not-wired",
        lambda tmp_path: context(tmp_path, settings=settings_store(sample_data=True),
                                 excel=excel_watch()),
        lambda tmp_path: context(tmp_path, settings=settings_store(sample_data=False),
                                 excel=excel_watch()),
        {
            "title": "Sample data is on but the sample files are not wired",
            "severity": "attention",
            "confident": True,
            "fix": "auto",
            "fix_label": "Fix it",
            "href": "",
            "detail": {"sources": ["workbook"]},
        },
    ),
    (
        "source-on-not-connected",
        lambda tmp_path: context(tmp_path, settings=settings_store(),
                                 excel=excel_watch()),
        lambda tmp_path: context(
            tmp_path, settings=settings_store(excel_enabled=False,
                                              calendar_enabled=False),
            excel=excel_watch()),
        {
            "title": "Workbook watching is on but no workbook is connected",
            "severity": "attention",
            "confident": False,
            "fix": "link",
            "fix_label": "Open",
            "href": "/settings#sources",
            "detail": {"sources": ["workbook"]},
        },
    ),
    (
        "source-on-not-connected",
        lambda tmp_path: context(tmp_path, settings=settings_store(),
                                 calendar=calendar_bridge()),
        lambda tmp_path: context(
            tmp_path, settings=settings_store(excel_enabled=False,
                                              calendar_enabled=False),
            calendar=calendar_bridge()),
        {
            "title": "Calendar reading is on but no calendar is connected",
            "severity": "attention",
            "confident": False,
            "fix": "link",
            "fix_label": "Open",
            "href": "/walkthrough/calendar",
            "detail": {"sources": ["calendar"]},
        },
    ),
    (
        "retired-plugins-installed",
        lambda tmp_path: context(tmp_path, settings=settings_store(),
                                 plugins=plugin_runtime(tmp_path,
                                                        **{"retired-thing": "enabled"}),
                                 catalog_ids=frozenset({"kept-plugin"})),
        lambda tmp_path: context(tmp_path, settings=settings_store(),
                                 plugins=plugin_runtime(tmp_path,
                                                        **{"retired-thing": "enabled"}),
                                 catalog_ids=frozenset({"kept-plugin",
                                                        "retired-thing"})),
        {
            "title": "1 installed plugin the catalog no longer carries",
            "severity": "attention",
            "confident": False,
            "fix": "ask",
            "fix_label": "Review card",
            "href": "",
            "detail": {"ids": ["retired-thing"]},
        },
    ),
    (
        "sample-plugin-not-installed",
        lambda tmp_path: context(tmp_path, settings=settings_store(sample_data=True),
                                 plugins=plugin_runtime(tmp_path)),
        lambda tmp_path: context(tmp_path, settings=settings_store(sample_data=False),
                                 plugins=plugin_runtime(tmp_path)),
        {
            "title": "The sample plugin is not installed",
            "severity": "info",
            "confident": False,
            "fix": "link",
            "fix_label": "Open",
            "href": "/marketplace/plugin/sample-demo-plugin",
            "detail": {},
        },
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_each_check_fires_and_stays_quiet(case, tmp_path):
    check_id, fire, quiet, expected = case

    findings = fired(check_id, fire(tmp_path))
    assert len(findings) == 1, fired(check_id, fire(tmp_path))
    finding = findings[0]
    for attribute, value in expected.items():
        assert getattr(finding, attribute) == value, attribute

    assert fired(check_id, quiet(tmp_path)) == []


def test_an_installed_but_uninstalled_plugin_is_not_retired(tmp_path):
    ctx = context(
        tmp_path, settings=settings_store(),
        plugins=plugin_runtime(tmp_path, **{"gone-thing": "uninstalled"}),
        catalog_ids=frozenset())
    assert fired("retired-plugins-installed", ctx) == []


def test_an_empty_catalog_does_not_retire_every_plugin(tmp_path, monkeypatch):
    import agentdesk.marketplace.catalog as catalog

    monkeypatch.setattr(catalog, "load_catalog_file", lambda path, source: [])
    ctx = context(
        tmp_path,
        plugins=plugin_runtime(tmp_path, **{"kept-plugin": "enabled"}),
        catalog_ids=None,
    )
    result = run_checks(ctx)
    assert [finding.id for finding in result.findings if "retired" in finding.id] == []


def test_a_catalog_that_will_not_load_is_one_crashed_check(tmp_path, monkeypatch):
    import agentdesk.marketplace.catalog as catalog

    def unreadable(path, source):
        raise RuntimeError("catalog unreadable")

    monkeypatch.setattr(catalog, "load_catalog_file", unreadable)
    ctx = context(
        tmp_path,
        plugins=plugin_runtime(tmp_path, **{"kept-plugin": "enabled"}),
        catalog_ids=None,
    )
    result = run_checks(ctx)
    crashed = [finding for finding in result.findings
               if finding.id == "deskcheck-crashed:retired-plugins-installed"]
    assert len(crashed) == 1
    assert crashed[0].title == (
        "Couldn't run the check for installed plugins the catalog no longer carries"
    )
    assert crashed[0].title != "Installed plugins the catalog no longer carries"


def test_a_fresh_context_has_no_catalog_until_one_is_loaded(tmp_path, monkeypatch):
    import agentdesk.marketplace.catalog as catalog

    monkeypatch.setattr(catalog, "load_catalog_file", lambda path, source: [])
    ctx = DeskContext(
        plugins=plugin_runtime(tmp_path, **{"kept-plugin": "enabled"}),
        data_dir=tmp_path,
    )
    assert ctx.catalog_ids is None
    result = run_checks(ctx)
    assert [finding.id for finding in result.findings if "retired" in finding.id] == []


def test_every_check_skips_silently_without_its_collaborators(tmp_path):
    result = run_checks(DeskContext())
    assert result.findings == []


# ---- the HTTP seam -------------------------------------------------------


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


def get_json(booted, auth, path):
    status, headers, body = booted.request("GET", path, auth)
    assert status == 200, (status, body)
    assert headers["Content-Type"].startswith("application/json")
    return json.loads(body)


def raw_inbox_row(store):
    """One row written by a build whose kind this one does not know."""
    store.conn.execute(
        "INSERT INTO cards (id, kind, origin, title, body, action_label,"
        " status, created_ts, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("raw-commitment", "commitment", "Written by another build",
         "A card this build cannot read", "", "", "waiting", NOW, "{}"),
    )
    store.conn.commit()


def _snapshot(root):
    """Every file under the data folder, by relative path; mtime and size."""
    return {
        str(path.relative_to(root)): (path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_desk_check_api_requires_a_session(booted):
    status, _headers, _body = booted.request("GET", "/api/desk-check",
                                             booted.host_header())
    assert status == 401


def test_desk_check_api_lists_the_unreadable_inbox_row(booted, auth):
    raw_inbox_row(booted.server.inbox)
    payload = get_json(booted, auth, "/api/desk-check")

    assert sorted(payload) == ["failed", "findings", "ranTs"]
    assert isinstance(payload["ranTs"], (int, float))
    assert payload["failed"] == {}
    finding = next(f for f in payload["findings"]
                   if f["id"] == "inbox-unreadable-rows")
    assert finding["title"] == "1 inbox card this version cannot read"
    assert finding["severity"] == "attention"
    assert finding["confident"] is True
    assert finding["fix"] == "auto"
    assert finding["fixLabel"] == "Fix it"
    assert finding["detail"] == {"count": 1, "kinds": ["commitment"]}


def test_desk_check_api_fires_sample_not_wired_and_retired_plugins(tmp_path):
    runtime = plugin_runtime(tmp_path, **{"retired-thing": "enabled"})
    server = server_harness.Booted(plugins=runtime)
    try:
        auth = server.exchange()
        server.server.settings.set("sample_data", True)
        payload = get_json(server, auth, "/api/desk-check")
    finally:
        server.close()

    by_id = {finding["id"]: finding for finding in payload["findings"]}
    assert by_id["sample-not-wired"]["severity"] == "attention"
    assert by_id["sample-not-wired"]["detail"] == {
        "sources": ["workbook", "calendar"]}
    assert by_id["retired-plugins-installed"]["detail"] == {
        "ids": ["retired-thing"]}
    assert by_id["retired-plugins-installed"]["fix"] == "ask"


def test_a_crashing_check_is_a_fatal_finding_over_http(booted, auth, monkeypatch):
    def boom(ctx, should_fix):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(deskcheck.core, "REGISTRY", [("boom", boom)])
    payload = get_json(booted, auth, "/api/desk-check")

    assert [finding["id"] for finding in payload["findings"]] == [
        "deskcheck-crashed:boom"]
    assert payload["findings"][0]["severity"] == "fatal"
    assert payload["failed"] == {
        "deskcheck-crashed:boom": "RuntimeError: kaboom"}


def test_desk_check_is_read_only(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AGENTDESK_DATA", str(data_dir))
    server = server_harness.Booted(settings_store=None, inbox_store=None,
                                   plugins=None)
    try:
        auth = server.exchange()
        before = _snapshot(data_dir)
        status, _headers, _body = server.request("GET", "/api/desk-check", auth)
        assert status == 200
        after = _snapshot(data_dir)
    finally:
        server.close()

    assert after == before


def test_dashboard_payload_carries_the_desk_check_summary(booted, auth):
    payload = get_json(booted, auth, "/api/dashboard")

    assert set(payload["deskCheck"]) == {"attention", "top"}
    assert payload["deskCheck"]["attention"] == 1
    assert payload["deskCheck"]["top"]["id"] == "source-on-not-connected"
    assert payload["deskCheck"]["top"]["severity"] == "attention"


def test_settings_page_offers_fix_for_an_automatic_finding(booted, auth):
    """A finding the desk is sure about carries its Fix it button."""
    raw_inbox_row(booted.server.inbox)
    status, _headers, body = booted.request("GET", "/settings", auth)
    page = body.decode()
    assert status == 200
    start = page.index("id='desk-check'")
    section = page[start:page.index("<section", start + 1)]
    assert "1 inbox card this version cannot read" in section
    assert "no card kind called commitment" in section
    assert "Last run" in section
    assert "action='/api/desk-check/fix'" in section
    assert ">Fix it</button>" in section

def test_settings_page_stays_up_when_the_desk_check_cannot_run(booted, auth, monkeypatch):
    import agentdesk.server.app as app

    def down(server):
        raise RuntimeError("desk check down")

    monkeypatch.setattr(app, "desk_check_api_payload", down)
    status, _headers, body = booted.request("GET", "/settings", auth)
    page = body.decode()
    assert status == 200
    assert "id='desk-check'" in page
    assert "The desk check could not finish" in page


def test_settings_page_says_the_desk_check_found_nothing(booted, auth):
    booted.server.settings.set("excel_enabled", False)
    booted.server.settings.set("calendar_enabled", False)
    status, _headers, body = booted.request("GET", "/settings", auth)
    page = body.decode()

    assert status == 200
    start = page.index("id='desk-check'")
    section = page[start:page.index("<section", start + 1)]
    assert "Everything the desk checks is fine." in section

