"""Dashboard shell tests: freshness contract, honest states, offline CSP.

The shell is where every later ticket lands, so the contract tests here
read the rendered HTML the way a browser would: structure and attributes,
through the real HTTP seam. No card ever fabricates a value: an
unconfigured source shows what to do about it, nothing else.
"""

import json
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness


class WidgetScan(HTMLParser):
    """Collect widget cards, their freshness parts, scripts and styles."""

    def __init__(self) -> None:
        super().__init__()
        self.widgets: list[dict] = []
        self.scripts: list[dict] = []
        self.inline_styles = 0
        self._current: dict | None = None

    @staticmethod
    def _classes(attrs: dict) -> list[str]:
        return (attrs.get("class") or "").split()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "style" in a:
            self.inline_styles += 1
        if tag == "article" and "widget" in self._classes(a):
            self._current = {
                "id": a.get("data-widget-id"),
                "status": a.get("data-freshness-status"),
                "classes": self._classes(a),
                "stamp": None,
                "dot": None,
            }
            self.widgets.append(self._current)
        if self._current is None:
            if tag == "script":
                self.scripts.append(a)
            return
        if tag == "span" and "stamp" in self._classes(a):
            self._current["stamp"] = a
        if tag == "span" and any(c == "dot" or c.startswith("dot ") for c in [a.get("class") or ""]):
            if self._current["dot"] is None:
                self._current["dot"] = a.get("class")
        if tag == "script":
            self.scripts.append(a)


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture()
def page(booted):
    headers = booted.exchange()
    status, resp_headers, body = booted.request("GET", "/", headers)
    assert status == 200
    assert resp_headers["Content-Type"].startswith("text/html")
    return body.decode("utf-8")


def _scan(page: str) -> WidgetScan:
    scan = WidgetScan()
    scan.feed(page)
    return scan


class RailScan(HTMLParser):
    """The anchor hrefs inside the rail nav, in document order."""

    def __init__(self) -> None:
        super().__init__()
        self.in_rail = False
        self.hrefs: list[str] = []

    @staticmethod
    def _classes(attrs: dict) -> list[str]:
        return (attrs.get("class") or "").split()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "nav" and "rail" in self._classes(a):
            self.in_rail = True
        elif self.in_rail and tag == "a":
            self.hrefs.append(a.get("href"))

    def handle_endtag(self, tag):
        if self.in_rail and tag == "nav":
            self.in_rail = False


def test_rail_links_the_four_consolidation_pages(page):
    scan = RailScan()
    scan.feed(page)
    # Dashboard, inbox, assistant, then the four pages the consolidation
    # shipped (activity, memory, mail, capabilities), then the plugins
    # page, then the peers page (ticket #67), then settings: the rail
    # matches the SPA's entries, so Assistant, Plugins and Peers are on
    # every page too.
    assert scan.hrefs == [
        "/", "/inbox", "/assistant", "/activity", "/memory", "/mail",
        "/capabilities", "/plugins", "/peers", "/settings",
    ]


def test_dashboard_serves_three_widgets_in_varying_sizes(page):
    scan = _scan(page)
    assert len(scan.widgets) == 3
    cols = {
        next(c for c in w["classes"] if c.startswith("col-")) for w in scan.widgets
    }
    assert cols == {"col-7", "col-5", "col-8"}


def test_every_widget_carries_the_freshness_contract(page):
    scan = _scan(page)
    for widget in scan.widgets:
        assert widget["status"] in {"fresh", "attention"}, widget["id"]
        assert widget["stamp"] is not None, widget["id"]
        assert "data-freshness" in widget["stamp"], widget["id"]
        assert widget["dot"] is not None, widget["id"]
        # A card either shows when it last updated, or is an attention
        # state that says why it has nothing to show. Never a quiet card.
        if not widget["stamp"].get("data-updated-iso"):
            assert widget["status"] == "attention", widget["id"]


def test_first_run_shows_honest_states_and_no_fabricated_values(page):
    scan = _scan(page)
    statuses = sorted(w["status"] for w in scan.widgets)
    # Sales not connected and commitments empty are attention states;
    # research is an action surface (Ready). Nothing is sample anymore.
    assert statuses == ["attention", "attention", "fresh"]
    for banned in (
        "14,320",                # the old invented KPI
        "Q4 pipeline review",    # the old invented meeting
        "Sample data",           # the old sample labeling
        "tag-sample",
    ):
        assert banned not in page, banned


def test_region_mix_is_gone_from_the_page_and_its_script(booted):
    headers = booted.exchange()
    _status, _h, body = booted.request("GET", "/", headers)
    page = body.decode("utf-8")
    scan = _scan(page)
    assert all(w["id"] != "region-mix" for w in scan.widgets)
    assert 'id="retest"' not in page
    # The fake recovery script (invented "2 regions changed") went with it.
    _status, _h, js = booted.request("GET", "/static/app.js", headers)
    assert b"Recovered just now" not in js
    assert b"widget-region-mix" not in js


def test_page_is_offline_by_construction(page):
    # No CDN, no font fetches, no third-party anything.
    assert "http://" not in page
    assert "https://" not in page


def test_strict_csp_scripts_stay_self_and_pages_stay_inline_free(booted, page):
    headers = booted.exchange()
    _status, resp_headers, _body = booted.request("GET", "/", headers)
    csp = resp_headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    # Scripts are code: 'self' only, no inline, no eval, anywhere.
    assert "script-src 'self'" in csp
    assert "unsafe-eval" not in csp
    # Styles are decoration: the one measured relaxation, for the SPA's
    # motion library writing style ATTRIBUTES (see app.py SECURITY_HEADERS).
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert csp.count("unsafe-inline") == 1
    scan = _scan(page)
    assert scan.inline_styles == 0
    assert len(scan.scripts) == 1
    assert scan.scripts[0].get("src") == "/static/app.js"


def test_strict_csp_lets_bundled_fonts_load_from_self_only(booted):
    headers = booted.exchange()
    _status, resp_headers, _body = booted.request("GET", "/", headers)
    csp = resp_headers["Content-Security-Policy"]
    directives = {
        part.split()[0]: part.split()[1:]
        for part in (piece.strip() for piece in csp.split(";"))
        if part
    }
    # The SPA's typefaces ship inside the bundle. Without font-src they
    # fall back to default-src 'none' and are blocked, so the directive
    # is there, and it names the app's own origin and nothing else: no
    # font host, no data: URLs, no wildcard.
    assert directives["font-src"] == ["'self'"]
    assert directives["default-src"] == ["'none'"]


def test_security_headers_on_every_answer(booted):
    headers = booted.exchange()
    _status, resp_headers, _body = booted.request("GET", "/", headers)
    assert resp_headers["X-Content-Type-Options"] == "nosniff"
    assert resp_headers["Cache-Control"] == "no-store"
    assert resp_headers["Referrer-Policy"] == "no-referrer"


def test_design_tokens_are_served_locally(booted):
    headers = booted.exchange()
    status, _h, body = booted.request("GET", "/static/app.css", headers)
    assert status == 200
    css = body.decode("utf-8")
    assert "--primary:#8C2F2F" in css
    assert "--font-ui" in css and "--font-mono" in css
    status, _h, body = booted.request("GET", "/static/app.js", headers)
    assert status == 200


def test_unknown_path_returns_404(booted):
    headers = booted.exchange()
    status, _h, _body = booted.request("GET", "/nope", headers)
    assert status == 404


def test_research_stamp_shows_when_the_last_answer_happened(booted):
    # The writer records the action as llm.research; the stamp must query
    # exactly that name or it would never leave "Ready".
    booted.server.llm = lambda prompt: json.dumps({"summary": "s", "sources": []})
    headers = booted.exchange()
    status, _h, _b = booted.post_json("/research", {"question": "q"}, headers)
    assert status == 200
    _status, _h, body = booted.request("GET", "/", headers)
    page = body.decode("utf-8")
    assert "Answered " in page
    assert ">Ready<" not in page


def test_banner_names_the_connect_steps_when_nothing_is_connected(page):
    assert "Not connected yet: each card below has its own one-step connect." in page
    assert "Sample data. Sources connect in later builds." not in page
    assert "Cards without a connected source show sample data." not in page


def test_banner_counts_connected_sources_when_one_exists(booted):
    booted.server.llm_endpoint = "https://llm.corp.example"  # configured only
    headers = booted.exchange()
    _status, _h, body = booted.request("GET", "/", headers)
    page = body.decode("utf-8")
    assert "Live: 1 of 3 sources connected." in page
    assert "Not connected yet:" not in page


def test_sales_card_carries_the_real_connect_action(page):
    # The picker flow works from the card: the button posts pick, then
    # register, then reloads (asserted in test_server_excel_api.py).
    assert "Connect a workbook" in page
    assert "No workbook is connected yet" in page


def test_missing_bridge_shows_an_honest_unavailable_card():
    booted = server_harness.Booted()
    try:
        # create_server treats a None bridge as "build the real one"; the
        # UI path under test is the attribute being None after a failed
        # store open, so null it here exactly as the app would see it.
        booted.server.calendar = None
        headers = booted.exchange()
        _status, _h, body = booted.request("GET", "/", headers)
        page = body.decode("utf-8")
        assert 'data-widget-id="key-commitment"' in page
        assert "calendar bridge is not running" in page
        assert "Q4 pipeline review" not in page  # no invented meeting
    finally:
        booted.close()
