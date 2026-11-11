"""Dashboard shell tests: freshness contract, sample labeling, offline CSP.

The shell is where every later ticket lands, so the contract tests here
read the rendered HTML the way a browser would: structure and attributes,
through the real HTTP seam.
"""

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


def test_dashboard_serves_four_widgets_in_varying_sizes(page):
    scan = _scan(page)
    assert len(scan.widgets) == 4
    cols = {
        next(c for c in w["classes"] if c.startswith("col-")) for w in scan.widgets
    }
    assert cols == {"col-7", "col-5", "col-8", "col-4"}


def test_every_widget_carries_the_freshness_contract(page):
    scan = _scan(page)
    for widget in scan.widgets:
        assert widget["status"] in {"fresh", "attention", "sample"}, widget["id"]
        assert widget["stamp"] is not None, widget["id"]
        assert "data-freshness" in widget["stamp"], widget["id"]
        assert widget["dot"] is not None, widget["id"]
        # A card either shows when it last updated, or is an attention
        # state that says why it has nothing to show. Never a quiet card.
        if not widget["stamp"].get("data-updated-iso"):
            assert widget["status"] == "attention", widget["id"]


def test_sample_widgets_are_labeled_as_sample(page):
    scan = _scan(page)
    statuses = sorted(w["status"] for w in scan.widgets)
    # Sales is sample until connected; commitments is live-but-empty;
    # research is an action surface (Ready); region-mix shows the designed
    # amber failure state.
    assert statuses == ["attention", "attention", "fresh", "sample"]
    assert "See what changed overnight, without opening the file." in page
    assert "Sample data until then." in page
    assert "Cards without a connected source show sample data." in page


def test_amber_widget_shows_the_designed_failure_state(page):
    scan = _scan(page)
    amber = next(w for w in scan.widgets if w["id"] == "region-mix")
    assert amber["status"] == "attention"
    assert 'id="retest"' in page


def test_page_is_offline_by_construction(page):
    # No CDN, no font fetches, no third-party anything.
    assert "http://" not in page
    assert "https://" not in page


def test_strict_csp_without_inline_code(booted, page):
    headers = booted.exchange()
    _status, resp_headers, _body = booted.request("GET", "/", headers)
    csp = resp_headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "style-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    scan = _scan(page)
    assert scan.inline_styles == 0
    assert len(scan.scripts) == 1
    assert scan.scripts[0].get("src") == "/static/app.js"


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
    assert "--primary:#14594E" in css
    assert "--font-ui" in css and "--font-mono" in css
    status, _h, body = booted.request("GET", "/static/app.js", headers)
    assert status == 200


def test_unknown_path_returns_404(booted):
    headers = booted.exchange()
    status, _h, _body = booted.request("GET", "/nope", headers)
    assert status == 404
