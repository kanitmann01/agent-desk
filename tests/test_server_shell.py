"""The shared server shell: every page carries the rail, the footer and
the system's green links, in the warm-paper language. These tests read
the rendered HTML through the real HTTP seam, the way a browser would.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness

# Every server-rendered page: path, its rail label, the href the rail
# must mark as the page you are on (empty for the doc pages, which are
# no rail entry's page).
SHELL_PAGES = [
    ("/inbox", "Inbox", "/inbox"),
    ("/assistant", "Assistant", "/assistant"),
    ("/settings/activity", "Activity", "/settings"),
    ("/memory", "Memory", "/memory"),
    ("/mail", "Mail", "/mail"),
    ("/capabilities", "Capabilities", "/settings"),
    ("/settings", "Settings", "/settings"),
    ("/walkthrough/calendar", "Walkthrough", ""),
    ("/what-this-touches", "What this app touches", ""),
]


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def _get(booted, path):
    headers = booted.exchange()
    status, _headers, body = booted.request("GET", path, headers)
    assert status == 200, (status, path)
    return body.decode("utf-8")


@pytest.mark.parametrize("path,label,active", SHELL_PAGES)
def test_every_page_carries_the_rail_marking_the_active_entry(booted, path, label, active):
    page = _get(booted, path)
    assert '<nav class="rail"' in page and 'aria-label="Main"' in page, path
    # The rail reaches every surface: all real entries present.
    for href in ("/inbox", "/assistant", "/memory", "/mail", "/settings"):
        assert f'href="{href}"' in page, (path, href)
    # Exactly the rail entries for this page's own surface are marked
    # current: one for a real page, none for a doc page.
    current = re.findall(r'<a href="([^"]*)" aria-current="page"', page)
    expected = [active] if active else []
    assert current == expected, (path, current)


@pytest.mark.parametrize("path,label,_active", SHELL_PAGES)
def test_every_page_ends_in_the_shared_footer(booted, path, label, _active):
    page = _get(booted, path)
    assert '<footer class="page-foot">' in page, path
    # The footer owns the version (never empty) and the
    # what-this-touches link.
    foot = page.split('<footer class="page-foot">')[1]
    assert "/what-this-touches" in foot
    assert re.search(r'<span class="mono">[^<]+</span>\.', foot), foot[:160]
    # The dangling back-link fragments are gone; the rail owns navigation.
    assert "Back to the dashboard" not in page, path


def test_the_served_stylesheet_speaks_the_green_link_rule():
    headers_style = None
    server = server_harness.Booted()
    try:
        headers = server.exchange()
        status, resp, body = server.request("GET", "/static/app.css", headers)
        assert status == 200
        css = body.decode("utf-8")
        # Links are the ink bottle green, underlined on hover only.
        assert "a{color:var(--primary);text-decoration:none}" in css
        assert "a:hover{text-decoration:underline}" in css
        # A styled button anchor keeps its own no-underline contract.
        assert "a.btn" in css
    finally:
        server.close()


def test_settings_has_one_display_heading_and_h2_sections(booted):
    page = _get(booted, "/settings")
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", page, flags=re.S)
    assert len(h1s) == 1, h1s
    assert "Settings" in h1s[0]
    # The cards read below it (h2) and the sub-sections inside a card are
    # h3; no inline spacing attributes either way. The six groups of spec
    # 022 are labels, not a third heading level.
    for card in ("Your AI", "Workbook, calendar and mail", "Memory", "Record",
                 "Activity log", "Skills", "Presentation timeout"):
        assert re.search(rf"<h2[^>]*>[^<]*{card}", page), card
    for sub in ("Review",):
        assert re.search(rf"<h3[^>]*>[^<]*{sub}", page), sub
    assert page.count("class='settings-section-title'") == 5
    assert "<h2 class='settings-section-title'" not in page
    assert '<h2 style=' not in page and "<h1 style=" not in page


def test_inbox_empty_state_keeps_its_header_contract(booted):
    page = _get(booted, "/inbox")
    # No ad-hoc inline sizing in the empty state: classes carry the look.
    assert "<h2 style=" not in page and "<h1 style=" not in page
    assert "Nothing needs your attention" in page
