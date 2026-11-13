"""The UI polish wave 2 contract: the layout defects the 2026-11-13
screenshot audit measured, pinned so they cannot creep back.

The findings this file pins (each measured in the live browser first):

- inbox cards stacked with 0px between them (card 1 ended at y=600, card
  2 started at y=600);
- the inbox quick-action fields kept their natural widths (162/132/175px
  in a 652px row) with an unstyled native 17px select, and the three
  submit buttons sat on three different baselines (y=501/521/541);
- the wizard's description textarea rendered inline at 162px beside its
  own label text, overlapping it;
- the plugins registry list painted five solid-green Install primaries
  on one surface against the One Voice Rule;
- no breadcrumb existed anywhere, and the rail had no collapse.

These tests read the rendered HTML through the real HTTP seam and the
served stylesheet, the way a browser would.
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
from agentdesk.server.plugins_view import render_plugins_page

SHELL_PAGES = [
    ("/inbox", "Inbox"),
    ("/assistant", "Assistant"),
    ("/activity", "Activity"),
    ("/memory", "Memory"),
    ("/mail", "Mail"),
    ("/capabilities", "Capabilities"),
    ("/plugins", "Plugins"),
    ("/settings", "Settings"),
    ("/walkthrough/calendar", "Connect your calendar"),
    ("/what-this-touches", "What this app touches"),
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


def _stylesheet(booted) -> str:
    headers = booted.exchange()
    status, _headers, body = booted.request("GET", "/static/app.css", headers)
    assert status == 200
    return body.decode("utf-8")


def _app_js(booted) -> str:
    headers = booted.exchange()
    status, _headers, body = booted.request("GET", "/static/app.js", headers)
    assert status == 200
    return body.decode("utf-8")


def _sample_inbox_page(booted) -> str:
    headers = booted.exchange()
    status, _headers, _body = booted.post_json(
        "/settings/toggle", {"key": "sample_data"}, headers)
    assert status == 200, status
    status, _headers, body = booted.request("GET", "/inbox", headers)
    assert status == 200
    return body.decode("utf-8")


# -- The inbox card stack -------------------------------------------------

def test_waiting_inbox_cards_sit_in_a_spaced_stack(booted):
    page = _sample_inbox_page(booted)
    assert "<div class='card-stack'>" in page, "the waiting cards have no stack wrapper"
    stack = page.split("<div class='card-stack'>")[1].split("</div>\n")[0]
    assert "<article" in stack, "no card inside the stack wrapper"


def test_the_stylesheet_spaces_the_card_stack_at_a_grid_step(booted):
    css = _stylesheet(booted)
    rule = re.search(r"\.card-stack\{[^}]*\}", css)
    assert rule, "no .card-stack rule in the served stylesheet"
    assert "display:flex" in rule.group(0)
    assert "gap:16px" in rule.group(0), rule.group(0)


# -- The inbox quick-action grid ------------------------------------------

def test_the_stylesheet_lays_the_quick_actions_on_a_shared_grid(booted):
    css = _stylesheet(booted)
    rule = re.search(r"\.cardforms\{[^}]*\}", css)
    assert rule, "no .cardforms grid rule"
    assert "display:grid" in rule.group(0), rule.group(0)
    # Proportional columns: at least two flexible fr columns, never the
    # natural-width row the audit measured.
    assert re.search(r"grid-template-columns:[^;}]*1\.\d+fr[^;}]*1\.\d*fr", rule.group(0)), \
        rule.group(0)


def test_the_quick_action_forms_share_rows_so_buttons_align(booted):
    css = _stylesheet(booted)
    # The forms take their rows from the shared grid (subgrid), so the
    # labels, the controls and the buttons land on one baseline each.
    sub = re.search(r"\.cardforms \.cardform\{[^}]*\}", css)
    assert sub, "no .cardforms .cardform rule"
    assert "grid-template-rows:subgrid" in sub.group(0), sub.group(0)
    # A graceful fallback keeps the buttons bottom-aligned without
    # subgrid support.
    fallback = re.search(r"@supports not \(grid-template-rows: subgrid\)\{[^{]*\{[^}]*\}[^}]*\}", css)
    assert fallback and "margin-top:auto" in fallback.group(0), css[-2000:]


def test_every_quick_action_control_is_styled_to_the_same_height(booted):
    css = _stylesheet(booted)
    # The select was left unstyled at a native 17px next to a 58px
    # textarea; the control rule must cover all three.
    rule = re.search(r"\.cardform input,\.cardform select,\.cardform textarea\{[^}]*\}", css)
    assert rule, f"the control rule must style input, select and textarea: {rule}"
    assert "min-height:36px" in rule.group(0), rule.group(0)
    width_rule = re.search(r"\.cardforms (input|select|textarea)[^{]*\{[^}]*\}", css)
    assert width_rule and "width:100%" in width_rule.group(0), \
        "the controls must fill their proportional columns"


def test_the_quick_action_buttons_fill_their_columns(booted):
    css = _stylesheet(booted)
    rule = re.search(r"\.cardforms \.btn\{[^}]*\}", css)
    assert rule, "no .cardforms .btn rule"
    assert "width:100%" in rule.group(0) and "justify-content:center" in rule.group(0)


def test_the_consent_checkbox_keeps_its_system_size(booted):
    css = _stylesheet(booted)
    rule = re.search(r"\.cardforms input\[type=\"checkbox\"\]\{[^}]*\}", css)
    assert rule, "the consent checkbox has no size exemption rule"
    assert "width:18px" in rule.group(0) and "min-height:0" in rule.group(0), rule.group(0)


def test_the_quick_actions_carry_a_grouping_head(booted):
    page = _sample_inbox_page(booted)
    assert "Ask the agent" in page, "the three follow-up forms carry no grouping head"


# -- The wizard's description field ---------------------------------------

def test_the_wizard_description_is_a_full_width_block(booted):
    css = _stylesheet(booted)
    rule = re.search(r"\.answer\{[^}]*\}", css)
    assert rule, "no .answer rule"
    assert "display:flex;flex-direction:column" in rule.group(0), rule.group(0)
    well = re.search(r"\.answer \.well-input\{[^}]*\}", css)
    assert well and "width:100%" in well.group(0), "the wizard textarea must fill its column"


def test_the_wizard_page_keeps_the_answer_form(booted):
    page = _get(booted, "/wizard")
    assert 'class="answer"' in page and 'well-input' in page, page[:400]


# -- The plugins registry list --------------------------------------------

def _registry_listing():
    return {
        "ok": True,
        "path": "registry",
        "origin": "checkout",
        "plugins": [{
            "id": "sample-plugin",
            "publisher": "agent-desk",
            "latest": "0.1.0",
            "risk": "low",
            "class": "declarative",
            "releases": [{"version": "0.1.0", "yanked": False}],
        }],
    }


def test_registry_installs_are_not_primary_actions():
    page = render_plugins_page([], _registry_listing(), "checkout", "0.0.0-test")
    registry = page.split("<h2>From the registry</h2>")[1]
    assert "Install</button>" in registry
    # One Voice Rule: a catalog row's Install is a routine action, not
    # the surface's one commanding green.
    assert "btn-primary' type='submit'>Install" not in registry, registry[:400]
    assert "btn-secondary' type='submit'>Install" in registry


def test_purge_is_marked_destructive():
    record = {
        "id": "sample-plugin", "name": "Sample plugin", "state": "uninstalled",
        "active_version": "0.1.0", "source": "zip", "pilot_views_left": 0,
        "versions": ["0.1.0"],
    }
    page = render_plugins_page([record], _registry_listing(), "checkout", "0.0.0-test")
    assert "btn-danger' type='submit'>Purge data" in page, page[-600:]


# -- The breadcrumb ---------------------------------------------------------

@pytest.mark.parametrize("path,title", SHELL_PAGES)
def test_every_shell_page_carries_a_breadcrumb_naming_the_page(booted, path, title):
    page = _get(booted, path)
    assert '<nav class="crumbs" aria-label="Breadcrumb">' in page, path
    crumbs = page.split('<nav class="crumbs" aria-label="Breadcrumb">')[1].split("</nav>")[0]
    assert '<a href="/">Agent Desk</a>' in crumbs, (path, crumbs[:200])
    assert f'<span aria-current="page">{title}</span>' in crumbs, (path, crumbs[:200])


def test_the_breadcrumb_reads_as_a_quiet_utility_line(booted):
    css = _stylesheet(booted)
    rule = re.search(r"\.crumbs\{[^}]*\}", css)
    assert rule, "no .crumbs rule in the served stylesheet"
    assert "font-size:12px" in rule.group(0), rule.group(0)


# -- The rail collapse --------------------------------------------------------

def test_the_rail_carries_a_collapse_control(booted):
    page = _get(booted, "/inbox")
    assert 'class="rail-toggle"' in page, page[:400]
    toggle = page.split('class="rail-toggle"')[1].split("</button>")[0]
    assert 'aria-expanded="false"' in toggle, toggle[:200]
    assert "aria-label" in toggle, toggle[:200]


def test_the_collapse_state_persists_through_the_app_script(booted):
    js = _app_js(booted)
    assert "agentdesk.railCollapsed" in js, "the rail state has no persistence key"
    assert "rail-collapsed" in js, "the script never applies the collapsed class"


def test_the_stylesheet_collapses_the_rail_to_its_marks(booted):
    css = _stylesheet(booted)
    rule = re.search(r"\.app\.rail-collapsed\{[^}]*\}", css)
    assert rule, "no collapsed-rail rule"
    assert "grid-template-columns:68px 1fr" in rule.group(0), rule.group(0)
    # Collapsed, the entries show their marks only: the text hides, the
    # count badge stays.
    hide = re.search(r"\.rail-collapsed \.rail a [^{]*\{[^}]*\}", css) \
        or re.search(r"\.rail-collapsed \.rail a\{[^}]*\}", css)
    assert hide, "no collapsed-entry rule"


def test_the_collapse_control_leaves_the_narrow_strip_alone(booted):
    css = _stylesheet(booted)
    narrow = css.split("@media (max-width:980px){")[1].split("}@media")[0] \
        if "@media (max-width:980px){" in css else ""
    assert narrow, "no narrow-width media block"
    assert ".rail-toggle{display:none}" in narrow, narrow[:400]


# -- Contrast and the footer column ---------------------------------------

def test_the_footer_and_table_heads_read_in_ink3_not_faint(booted):
    css = _stylesheet(booted)
    foot = re.search(r"\.page-foot\{[^}]*\}", css)
    assert foot and "color:var(--ink-3)" in foot.group(0), foot.group(0) if foot else "missing"
    th = re.search(r"table\.rows th\{[^}]*\}", css)
    assert th and "color:var(--ink-3)" in th.group(0), th.group(0) if th else "missing"


def test_the_footer_lives_in_the_page_column(booted):
    page = _get(booted, "/inbox")
    # The footer follows the content inside the .doc column, so its
    # hairline matches the text column instead of spanning main.
    doc = page.split('<div class="doc">')[1]
    assert '<footer class="page-foot">' in doc, "the footer sits outside the content column"
