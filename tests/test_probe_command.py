"""The double-click entry point on macOS: tools/probe.command.

Like the probe's .cmd tests, this file is read as text and asserted by
content, never executed by tests: on the real laptop a human double-clicks
it from Finder. It must cd to the script dir (Finder starts .command files
in the user home, and the report lands in cwd/probe-run), run the probe
module with the caller's arguments, never elevate, and pause at the end so
the report stays readable.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND = REPO_ROOT / "tools" / "probe.command"
GITATTRIBUTES = REPO_ROOT / ".gitattributes"

ELEVATION_MARKERS = ("runas", "-verb runas", "sudo", "elevate", "osascript")


def command_text() -> str:
    return COMMAND.read_text(encoding="utf-8", errors="replace").lower()


def test_probe_command_exists():
    assert COMMAND.is_file(), f"missing double-click entry: {COMMAND}"


def test_probe_command_runs_the_module_with_passthrough_args():
    text = command_text()
    assert "python3 -m agentdesk.probe" in text
    assert '"$@"' in text


def test_probe_command_points_pythonpath_at_the_source_tree():
    # POSIX joins search paths with colons, not the Windows semicolon.
    text = command_text()
    assert "pythonpath" in text
    assert "../src" in text


def test_probe_command_runs_from_the_script_dir():
    # Finder starts .command files in the user home; the probe writes its
    # report to cwd/probe-run, so the script must cd to its own directory
    # to match what a double-clicked .cmd does on Windows.
    assert 'cd "$dir"' in command_text()


def test_probe_command_never_elevates():
    text = command_text()
    for marker in ELEVATION_MARKERS:
        assert marker not in text, f"elevation marker found: {marker}"


def test_probe_command_gates_on_python_version_not_just_presence():
    """A broken or stub python3 on PATH must not hijack the run."""
    assert "version_info >= (3, 10)" in command_text()


def test_probe_command_reaches_uv_as_the_last_rung():
    text = command_text()
    assert "uv run --no-project python -m agentdesk.probe" in text


def test_probe_command_sets_only_the_native_tls_spelling_for_uv():
    # uv reads the macOS system keychain through UV_NATIVE_TLS; the Windows
    # certs spelling is a different bootstrap switch and must not leak into
    # the Mac launcher where it does nothing.
    text = command_text()
    assert "uv_native_tls=1" in text
    assert "uv_system_certs" not in text


def test_probe_command_keeps_window_open():
    # The report must stay readable, like the .cmd's pause: a prompt plus a
    # blocking read holds the Terminal window until the user lets it go.
    text = command_text()
    assert "press return" in text
    assert "read -r" in text


def test_probe_command_names_python3_in_the_install_hint():
    text = command_text()
    assert "not found" in text
    assert "python3" in text


def test_gitattributes_checks_shell_scripts_out_lf():
    # sh and Terminal.app break on CRLF bytes; the eol=lf rules keep the
    # .command launchers double-clickable no matter which OS checked them out.
    text = GITATTRIBUTES.read_text(encoding="utf-8")
    assert "*.command text eol=lf" in text
    assert "*.sh text eol=lf" in text
