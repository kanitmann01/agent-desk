"""The start-everything entry point: tools/start.command.

Read as text and asserted by content, never executed by tests: on the
real laptop a human double-clicks it from Finder. With no arguments it
must behave exactly like agent-desk.command (exec it). With the dev
argument it runs the development stack: the Python API in the background
with a pid file, and the npm UI dev server in the foreground. It must
never elevate or drive the OS GUI (no osascript).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CMD = REPO_ROOT / "tools" / "start.command"

FORBIDDEN = ("sudo", "osascript", "runas", "elevate")


def cmd_text() -> str:
    return CMD.read_text(encoding="utf-8", errors="replace").lower()


def test_start_command_exists():
    assert CMD.is_file(), f"missing start entry: {CMD}"


def test_start_command_is_executable_in_git():
    mode = CMD.stat().st_mode
    # In the working tree the bit survives POSIX checkouts; on Windows
    # the committed mode is what matters (git update-index --chmod=+x).
    repo_mode = _committed_mode()
    assert repo_mode is None or repo_mode == 0o100755, f"mode: {repo_mode}"


def _committed_mode():
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "-s", "--", "tools/start.command"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not out:
        return None
    return int(out.split()[0], 8)


def test_start_command_delegates_the_double_click_path():
    assert 'exec "$dir/agent-desk.command"' in cmd_text()


def test_start_command_dev_branch_starts_both_processes():
    text = cmd_text()
    assert '"$1" = "dev"' in text
    assert "agentdesk.server --port 8765" in text
    assert 'npm --prefix "$dir/../frontend" run dev' in text


def test_start_command_dev_keeps_a_pid_file_and_a_log():
    # The API runs in the background: the user needs a stop handle.
    text = cmd_text()
    assert "agent-desk-dev.pid" in text
    assert "agent-desk-dev.log" in text
    assert "kill" in text


def test_start_command_stops_the_api_when_the_ui_stops():
    # Ctrl+C ends the foreground dev server; the background API must
    # not be orphaned.
    text = cmd_text()
    assert 'kill "$(cat "$pid")"' in text


def test_start_command_gates_on_python_version():
    assert "version_info >= (3, 10)" in cmd_text()


def test_start_command_never_elevates_or_drives_the_gui():
    for marker in FORBIDDEN:
        assert marker not in cmd_text(), f"forbidden marker found: {marker}"
