"""The double-click entry point: tools/agent-desk.cmd.

Like the probe's .cmd, this file is read as text and asserted by content,
never executed by tests: on the real laptop a human double-clicks it. It
must start the server module windowless, never elevate, leave no console
open (the browser is the surface), fall back across interpreters, and
reach uv's native-TLS bootstrap last so a bare laptop can still boot.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CMD = REPO_ROOT / "tools" / "agent-desk.cmd"

ELEVATION_MARKERS = ("runas", "-verb runas", "sudo", "elevate")


def cmd_text() -> str:
    return CMD.read_text(encoding="utf-8", errors="replace").lower()


def test_agent_desk_cmd_exists():
    assert CMD.is_file(), f"missing double-click entry: {CMD}"


def test_agent_desk_cmd_starts_the_server_module():
    text = cmd_text()
    assert "python -m agentdesk.server" in text


def test_agent_desk_cmd_points_pythonpath_at_the_source_tree():
    text = cmd_text()
    assert "pythonpath" in text
    assert "src" in text


def test_agent_desk_cmd_never_elevates():
    text = cmd_text()
    for marker in ELEVATION_MARKERS:
        assert marker not in text, f"elevation marker found: {marker}"


def test_agent_desk_cmd_leaves_no_console_open():
    # Unlike the probe (whose report must stay readable), the dashboard is
    # the surface: the launcher window closes itself.
    assert "pause" not in cmd_text()


def test_agent_desk_cmd_prefers_the_windowless_interpreter():
    assert "pythonw" in cmd_text()


def test_agent_desk_cmd_gates_on_python_version_not_just_presence():
    """The Microsoft Store python.exe stub must not hijack the run."""
    assert "version_info >= (3, 10)" in cmd_text()


def test_agent_desk_cmd_has_a_python_fallback():
    text = cmd_text()
    assert "py -3" in text
    assert "not found" in text


def test_agent_desk_cmd_reaches_uv_as_the_last_rung():
    text = cmd_text()
    assert "uv run --no-project python -m agentdesk.server" in text


def test_agent_desk_cmd_forces_the_windows_trust_store_for_uv():
    # A9.2 rule 5: bootstrap package resolution must go through the
    # corporate trust store. Old and new uv spell the switch differently;
    # the .cmd sets both spellings as environment variables.
    text = cmd_text()
    assert "uv_system_certs=1" in text
    assert "uv_native_tls=1" in text
