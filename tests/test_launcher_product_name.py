"""The retained launchers print Nexuus Bot; their filenames stay (032-2).

Spec 032 ticket 02 (issue 356). Where a retained launcher script prints
the product name it prints the approved one: the double-click comments,
the macOS starting echoes and the dev-stack window titles. The
filenames do not change and the module invocations keep their retained
compatibility spellings (pinned by the launcher tests beside these).

The files are read as text and asserted by content, never executed, the
way tests/test_agent_desk_cmd.py reads the Windows launcher.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

APPROVED_NAME = "Nexuus Bot"
OLD_WORDMARK = "agent desk"


def _text(name: str) -> str:
    return (TOOLS / name).read_text(encoding="utf-8", errors="replace")


def _assert_cleared(name: str) -> None:
    lowered = _text(name).lower()
    assert OLD_WORDMARK not in lowered, f"{name}: still names the old product"


def test_agent_desk_cmd_comments_name_the_product():
    assert f"REM {APPROVED_NAME}: double-click me." in _text("agent-desk.cmd")
    _assert_cleared("agent-desk.cmd")


def test_agent_desk_command_prints_the_new_name():
    text = _text("agent-desk.command")
    assert f"# {APPROVED_NAME}: double-click me from Finder." in text
    assert (f'echo "{APPROVED_NAME} is starting. '
            'Your browser opens when the server is up."') in text
    assert (f'echo "{APPROVED_NAME} is starting via uv. '
            'Your browser opens when the server is up."') in text
    _assert_cleared("agent-desk.command")


def test_probe_cmd_comments_name_the_product():
    assert f"REM {APPROVED_NAME} P0 probe: double-click me." in \
        _text("probe.cmd")
    _assert_cleared("probe.cmd")


def test_probe_command_comments_name_the_product():
    assert f"# {APPROVED_NAME} P0 probe: double-click me from Finder." in \
        _text("probe.command")
    _assert_cleared("probe.command")


def test_start_cmd_comments_and_window_titles_name_the_product():
    text = _text("start.cmd")
    assert f"REM {APPROVED_NAME}: start everything." in text
    assert text.count(f'start "{APPROVED_NAME} API (dev)"') == 3
    assert f'start "{APPROVED_NAME} UI (dev)"' in text
    _assert_cleared("start.cmd")


def test_start_command_comments_name_the_product():
    assert f"# {APPROVED_NAME}: start everything." in _text("start.command")
    _assert_cleared("start.command")


def test_the_retained_module_invocations_keep_their_spelling():
    """The compatibility command stays: the launchers still start the
    server module by its retained name until the package move."""
    assert "-m agentdesk.server" in _text("agent-desk.cmd")
    assert "python -m agentdesk.server" in _text("agent-desk.cmd")
    assert "-m agentdesk.server" in _text("agent-desk.command")
    assert "python -m agentdesk.probe" in _text("probe.cmd")
    assert "python3 -m agentdesk.probe" in _text("probe.command")
    assert "-m agentdesk.server" in _text("start.cmd")
    assert "-m agentdesk.server" in _text("start.command")
