"""Every server-rendered surface names the product Nexuus Bot (032-2).

Spec 032 ticket 02 (issue 356). One approved server constant carries the
name; the shell wordmark, the avatar title and its initials, the page
titles and breadcrumbs, the startup banner, the authentication recovery
sentence, the session and update and error copy, the wizard copy, the
memory and settings and commitments sentences, and the module docstrings
all render from it. The avatar initials read NB.

Pure render-function tests: each surface is called directly and its
output is read the way a person reads it. Nothing here starts a desk, a
walk or the application; the CLI check stops at the parser.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nexuusbot  # noqa: E402
import nexuusbot.validator  # noqa: E402,F401
from nexuusbot.server import pages  # noqa: E402
from nexuusbot.server import commitments  # noqa: E402
from nexuusbot.server import memory_view  # noqa: E402
from nexuusbot.server import settings_view  # noqa: E402
from nexuusbot.server import wizard_view  # noqa: E402

# The approved literals, from the contract the guard owns: the test
# reads them here so the expectations come from the spec, not from the
# code under test.
CONTRACT = json.loads(
    (ROOT / "tools" / "naming" / "inventory.json").read_text(encoding="utf-8"))
APPROVED_NAME = CONTRACT["approved_name"]
APPROVED_INITIALS = CONTRACT["approved_initials"]

OLD_WORDMARK = "agent desk"


def _assert_old_name_absent(html_out: str, where: str) -> None:
    """The rendered surface no longer carries the old wordmark."""
    assert OLD_WORDMARK not in html_out.lower(), (
        f"{where}: still carries the old wordmark"
    )


def test_the_server_reads_one_approved_constant():
    """One server constant carries the name, equal to the contract's."""
    assert nexuusbot.PRODUCT_NAME == APPROVED_NAME
    assert nexuusbot.PRODUCT_INITIALS == APPROVED_INITIALS


def test_the_shell_wordmark_breadcrumb_and_title_render_the_name():
    out = pages.page_shell("Inbox", "/inbox", "<p>hi</p>", "0.1.0")
    assert f"<title>Inbox, {APPROVED_NAME}</title>" in out
    assert f'<a href="/">{APPROVED_NAME}</a>' in out, "the breadcrumb root"
    assert f'<b class="brand-name">{APPROVED_NAME}</b>' in out, "the phone bar"
    assert (f'<div class="brand"><b class="brand-name">{APPROVED_NAME}'
            f"</b></div>") in out, "the rail brand"
    assert f'<b class="user-name">{APPROVED_NAME}</b>' in out, "the user card"
    assert (f'{APPROVED_NAME} <span class="mono">0.1.0</span>') in out, \
        "the footer version line"
    _assert_old_name_absent(out, "page_shell")


def test_the_avatar_title_and_initials_render_from_the_constants():
    out = pages.page_shell("Inbox", "/inbox", "<p>hi</p>", "0.1.0")
    assert f'title="{APPROVED_NAME}">{APPROVED_INITIALS}</span>' in out, out[
        out.find("avatar") - 100:out.find("avatar") + 100
    ]


def test_the_rail_fallback_label_is_the_name():
    out = pages.page_shell("Peers", "/peers", "<p>hi</p>", "0.1.0")
    assert f'<span class="phone-current">{APPROVED_NAME}</span>' in out


def test_the_dashboard_document_title_is_the_name():
    out = pages.render_dashboard([], "0.1.0", "Good morning", "Thu 27 Nov")
    assert f"<title>{APPROVED_NAME}</title>" in out
    _assert_old_name_absent(out, "render_dashboard")


def test_the_error_page_title_carries_the_name():
    out = pages.render_error_page("Forbidden", "not allowed")
    assert f"<title>Forbidden, {APPROVED_NAME}</title>" in out
    _assert_old_name_absent(out, "render_error_page")


def test_the_calendar_walkthrough_sentence_names_the_product():
    out = pages.render_walkthrough("hint", "", "0.1.0")
    assert f"<p>{APPROVED_NAME} reads one file" in out
    _assert_old_name_absent(out, "render_walkthrough")


def test_the_commitments_copy_names_the_product():
    paused = commitments.render_commitments_unavailable(datetime(2026, 11, 27))
    assert f"{APPROVED_NAME} usually brings it back." in paused.body_html
    _assert_old_name_absent(paused.body_html, "commitments unavailable")
    empty = commitments.render_commitments_widget(
        {"state": commitments.STATE_EMPTY}, datetime(2026, 11, 27))
    assert empty is not None
    assert f"No calendar data yet. {APPROVED_NAME} watches" in empty.body_html
    _assert_old_name_absent(empty.body_html, "commitments empty")


def test_the_memory_page_intro_names_the_product():
    assert memory_view.HOW_MEMORY_WORKS.startswith(
        f"{APPROVED_NAME} remembers facts about you and your work")


def test_the_settings_memory_card_names_the_product():
    card = settings_view._memory_card({})
    assert f"{APPROVED_NAME} remembers facts about you and your work" in card


def test_the_wizard_page_title_and_breadcrumb_name_the_product():
    page = wizard_view.render_wizard_page({
        "id": "wiz-1",
        "state": "escalated",
        "description": "Show the sales delta every morning.",
        "answers": {"source": "An Excel workbook", "show": "One status line"},
        "cannot": "This needs a code path the wizard cannot write.",
    }, "0.1.0")
    assert f"<title>Approve, {APPROVED_NAME}</title>" in page or \
        f", {APPROVED_NAME}</title>" in page
    assert f'<a href="/">{APPROVED_NAME}</a>' in page, "the wizard breadcrumb"
    _assert_old_name_absent(page, "wizard page")


def test_the_startup_banner_reads_from_the_constant():
    from nexuusbot.server.app import START_BANNER
    url = "http://127.0.0.1:8765/one-time-start"
    assert START_BANNER.format(url=url) == f"{APPROVED_NAME} is running: {url}"


def test_the_authentication_recovery_sentence_reads_from_the_constant():
    from nexuusbot.server.app import SESSION_RECOVERY
    assert SESSION_RECOVERY == (
        f"Open {APPROVED_NAME} from its shortcut to get a fresh link.")


def test_the_update_banner_names_the_product():
    from nexuusbot.update import READY
    assert READY.format(version="0.1.1") == (
        "Version 0.1.1 is ready. Restart "
        f"{APPROVED_NAME} from its shortcut to switch.")


def test_the_update_health_message_names_the_product():
    from nexuusbot.update import NO_PROGRAM_IN_STAGE
    assert NO_PROGRAM_IN_STAGE == (
        f"The update has no {APPROVED_NAME} program in it.")


def test_the_server_cli_description_names_the_product():
    from nexuusbot.server.cli import build_parser
    assert build_parser().description == (
        f"Start the {APPROVED_NAME} dashboard (127.0.0.1 only).")


def test_the_macos_notification_sentence_names_the_product():
    from nexuusbot.feeder.collectors.mac_notifications import \
        FULL_DISK_ACCESS_CAUSE
    assert f"Give {APPROVED_NAME} Full Disk Access" in FULL_DISK_ACCESS_CAUSE


def test_the_module_docstrings_name_the_product():
    assert nexuusbot.__doc__.startswith(f"{APPROVED_NAME}:")
    assert nexuusbot.validator.__doc__.startswith(
        f"{APPROVED_NAME} plugin validator")
