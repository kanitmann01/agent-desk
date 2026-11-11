"""Wizard view tests: the four states, the approval summary, the CSP line.

Pure render tests, no server: each page must read correctly, escape
every dynamic value, and hold the offline line (no inline styles, no
absolute URLs) on its own, the way the strict Content-Security-Policy
needs it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.server.wizard_view import (  # noqa: E402
    approval_summary,
    preview_lines,
    render_wizard_page,
)

VERSION = "0.1.0-test"

DRAFT = {
    "id": "morning-sales",
    "name": "Morning sales",
    "description": "Shows the sales delta every morning.",
    "permissions": {
        "filesystem": {"read": ["${workspace}/reports/*.xlsx"], "write": []},
        "network": {"allow": []},
        "shell": "none",
    },
}

QUESTIONS_SESSION = {
    "id": "wiz-42",
    "state": "questions",
    "description": "A widget that shows how sales changed overnight.",
    "questions": [
        {
            "question": "Which file should it read?",
            "options": ["The sales workbook", "The calendar file"],
            "default": "The sales workbook",
        },
        {
            "question": "How should the numbers be grouped?",
            "options": ["By region", "By product", "In one total"],
            "default": "By region",
        },
    ],
}


def _preview_session() -> dict:
    return {
        "id": "wiz-9",
        "state": "preview",
        "description": "A widget that shows how sales changed overnight.",
        "draft": DRAFT,
        "ui_schema": {"title": "Overnight sales", "columns": ["region", "delta"]},
        "sample_rows": [
            {"region": "DACH", "delta": "+4.2%"},
            {"region": "Nordics", "delta": "0.0%"},
        ],
    }


def test_questions_state_renders_every_question_as_radio_forms():
    page = render_wizard_page(QUESTIONS_SESSION, VERSION)
    assert "Which file should it read?" in page
    assert "How should the numbers be grouped?" in page
    assert page.count('type="radio"') == 5
    # The default of each question is pre-selected.
    assert 'value="The sales workbook" checked' in page
    assert 'value="By region" checked' in page
    # One plain form per question, each posting to the answer endpoint.
    assert page.count('action="/wizard/wiz-42/answer"') == 2
    assert 'method="post"' in page
    assert page.count("Ask</button>") == 2


def test_describing_state_echoes_the_description_and_keeps_asking():
    session = dict(QUESTIONS_SESSION, state="describing")
    page = render_wizard_page(session, VERSION)
    assert "You asked for" in page
    assert "A widget that shows how sales changed overnight." in page
    assert 'action="/wizard/wiz-42/answer"' in page
    assert "Which file should it read?" in page


def test_describing_with_nothing_yet_offers_the_entry_form():
    page = render_wizard_page({"id": "wiz-1", "state": "describing"}, VERSION)
    assert 'name="description"' in page
    assert 'action="/wizard/wiz-1/answer"' in page


def test_preview_state_shows_rows_summary_and_the_two_actions():
    page = render_wizard_page(_preview_session(), VERSION)
    # The would-be widget, labeled as a preview of sample data.
    assert "Preview, sample data" in page
    assert "DACH | +4.2%" in page
    assert "Nordics | 0.0%" in page
    # The consolidated approval summary block.
    assert "What it does" in page
    assert "Shows the sales delta every morning." in page
    assert "${workspace}/reports/*.xlsx" in page
    assert "Runs no code" in page
    assert "Opens no network connection" in page
    assert "Delete it from the Plugins surface, or delete the app folder." in page
    # Approve posts to approve; escalate posts to escalate.
    assert 'action="/wizard/wiz-9/approve"' in page
    assert 'action="/wizard/wiz-9/escalate"' in page
    assert "Escalate it" in page


def test_approved_state_shows_summary_pilot_note_and_dashboard_link():
    session = {"id": "wiz-9", "state": "approved", "draft": DRAFT}
    page = render_wizard_page(session, VERSION)
    assert "Shows the sales delta every morning." in page
    assert "in pilot mode" in page
    assert "Remove it from the Plugins surface" in page
    assert 'href="/"' in page


def test_escalated_state_shows_dead_end_and_user_words():
    session = {
        "id": "wiz-3",
        "state": "escalated",
        "description": "Email the report to my team every Friday.",
        "cannot": "Sending mail is outside the declarative vocabulary.",
    }
    page = render_wizard_page(session, VERSION)
    assert "Sending mail is outside the declarative vocabulary." in page
    assert "Email the report to my team every Friday." in page
    assert "feature request" in page
    assert 'href="/"' in page


def test_approval_summary_lists_reads_and_never_lines():
    summary = approval_summary(DRAFT)
    assert summary["does"] == "Shows the sales delta every morning."
    assert summary["reads"] == ["${workspace}/reports/*.xlsx"]
    assert "Runs no code" in summary["never"]
    assert "Opens no network connection" in summary["never"]
    assert "Writes no files" in summary["never"]
    assert summary["remove"] == "Delete it from the Plugins surface, or delete the app folder."


def test_approval_summary_never_claims_what_permissions_allow():
    wide = {
        "name": "Wide",
        "permissions": {
            "filesystem": {"read": ["a*.csv"], "write": ["${pluginData}"]},
            "network": {"allow": []},
            "shell": "none",
        },
    }
    summary = approval_summary(wide)
    assert summary["reads"] == ["a*.csv"]
    assert "Writes no files" not in summary["never"]


def test_preview_lines_columns_shape_renders_one_line_per_row():
    lines = preview_lines(
        {"title": "Overnight sales", "columns": ["region", "delta"]},
        [
            {"region": "DACH", "delta": "+4.2%"},
            {"region": "Nordics", "delta": "0.0%"},
        ],
    )
    assert lines == ["Overnight sales", "DACH | +4.2%", "Nordics | 0.0%"]


def test_preview_lines_fields_shape_renders_key_value_lines():
    lines = preview_lines(
        {"title": "Account card", "fields": ["balance", "owner"]},
        [{"balance": 1240, "owner": "Priya"}],
    )
    assert lines == ["Account card", "balance: 1240", "owner: Priya"]


def test_preview_lines_tolerates_missing_pieces():
    assert preview_lines({}, []) == []
    assert preview_lines({"title": "T", "columns": ["a"]}, []) == ["T"]
    assert preview_lines({"title": "T", "fields": ["a"]}, []) == ["T"]


def test_pages_hold_the_csp_line():
    sessions = [
        {"id": "wiz-1", "state": "describing"},
        QUESTIONS_SESSION,
        _preview_session(),
        {"id": "wiz-9", "state": "approved", "draft": DRAFT},
        {"id": "wiz-3", "state": "escalated", "description": "Text."},
    ]
    for session in sessions:
        page = render_wizard_page(session, VERSION)
        assert "style=" not in page, session["state"]
        assert "http://" not in page, session["state"]
        assert "https://" not in page, session["state"]


def test_dynamic_values_are_escaped():
    session = {
        "id": "wiz-x",
        "state": "questions",
        "description": '<script>alert("pwned")</script> show sales',
        "questions": [
            {
                "question": 'Read "Q4" & totals <here>?',
                "options": ['File "a<b>.xlsx"', "Other"],
                "default": 'File "a<b>.xlsx"',
            }
        ],
    }
    page = render_wizard_page(session, VERSION)
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "Read &quot;Q4&quot; &amp; totals &lt;here&gt;?" in page
    assert "<b>" not in page

    preview = {
        "id": "wiz-y",
        "state": "preview",
        "draft": {"name": "<b>bold name</b>"},
        "ui_schema": {"title": "<script>bad()</script>", "columns": ["a"]},
        "sample_rows": [{"a": "<img src=x>"}],
    }
    page = render_wizard_page(preview, VERSION)
    assert "<script>" not in page
    assert "&lt;script&gt;bad()&lt;/script&gt;" in page
    assert "<img" not in page
    assert "&lt;img src=x&gt;" in page
    assert "&lt;b&gt;bold name&lt;/b&gt;" in page
