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

import re
import sys
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

def test_a_rail_entry_name_keeps_one_line_in_its_own_scroller():
    label = rule(".rail .rail-label")
    assert "white-space:nowrap" in label
    assert "overflow-x:auto" in label
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
