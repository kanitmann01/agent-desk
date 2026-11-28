"""The double-click entry point on macOS: tools/agent-desk.command.

Like the .cmd tests, this file is read as text and asserted by content,
never executed by tests: on the real laptop a human double-clicks it from
Finder. It must start the server module detached (the Terminal window can
close; the log holds the output and the browser is the surface), never
elevate, gate on the Python version, and reach uv's native-TLS bootstrap
last with only the macOS spelling of that switch.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND = REPO_ROOT / "tools" / "agent-desk.command"
GITATTRIBUTES = REPO_ROOT / ".gitattributes"

# macOS has no UAC: the elevation risks here are the shell's password prompts
# and scripted Apple events, so those markers must never appear either.
ELEVATION_MARKERS = ("runas", "-verb runas", "sudo", "elevate", "osascript")


def command_text() -> str:
    return COMMAND.read_text(encoding="utf-8", errors="replace").lower()


def test_agent_desk_command_exists():
    assert COMMAND.is_file(), f"missing double-click entry: {COMMAND}"


def test_agent_desk_command_starts_the_server_module():
    text = command_text()
    assert "python3 -m nexuusbot.server" in text


def test_agent_desk_command_points_pythonpath_at_the_source_tree():
    # POSIX joins search paths with colons, not the Windows semicolon.
    text = command_text()
    assert "pythonpath" in text
    assert "../src" in text


def test_agent_desk_command_never_elevates():
    text = command_text()
    for marker in ELEVATION_MARKERS:
        assert marker not in text, f"elevation marker found: {marker}"


def test_agent_desk_command_gates_on_python_version_not_just_presence():
    """A broken or stub python3 on PATH must not hijack the run."""
    assert "version_info >= (3, 10)" in command_text()


def test_agent_desk_command_reaches_uv_as_the_last_rung():
    text = command_text()
    assert "uv run --no-project python -m nexuusbot.server" in text


def test_agent_desk_command_sets_only_the_native_tls_spelling_for_uv():
    # uv reads the macOS system keychain through UV_NATIVE_TLS; the Windows
    # certs spelling is a different bootstrap switch and must not leak into
    # the Mac launcher where it does nothing.
    text = command_text()
    assert "uv_native_tls=1" in text
    assert "uv_system_certs" not in text


def test_agent_desk_command_detaches_the_server_into_a_log():
    # The dashboard is the surface: nohup in the background lets the Terminal
    # window close, and the log file catches bootstrap errors a console
    # launcher would have shown.
    text = command_text()
    assert "nohup" in text
    assert "2>&1 &" in text
    assert ".agent-desk/agent-desk.log" in text


def test_agent_desk_command_tells_the_user_where_the_log_is():
    text = command_text()
    assert "starting" in text
    assert "log:" in text


def test_agent_desk_command_names_python3_in_the_install_hint():
    # macOS has no bare python: the hint must not send the user hunting for
    # a command that does not exist on their machine.
    text = command_text()
    assert "not found" in text
    assert "python3" in text
    assert "exit 1" in text


def test_gitattributes_checks_shell_scripts_out_lf():
    # sh and Terminal.app break on CRLF bytes; the eol=lf rules keep the
    # .command launchers double-clickable no matter which OS checked them out.
    text = GITATTRIBUTES.read_text(encoding="utf-8")
    assert "*.command text eol=lf" in text
    assert "*.sh text eol=lf" in text
