"""The start-everything entry point: tools/start.cmd.

Read as text and asserted by content, never executed by tests: on the
real laptop a human double-clicks it. With no arguments it must behave
exactly like the double-click launcher (delegate to agent-desk.cmd).
With the dev argument it runs the development stack: the Python API and
the npm UI dev server, each in its own labeled window. It must never
elevate.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CMD = REPO_ROOT / "tools" / "start.cmd"

ELEVATION_MARKERS = ("runas", "-verb runas", "sudo", "elevate")


def cmd_text() -> str:
    return CMD.read_text(encoding="utf-8", errors="replace").lower()


def test_start_cmd_exists():
    assert CMD.is_file(), f"missing start entry: {CMD}"


def test_start_cmd_delegates_the_double_click_path():
    # No arguments must mean the ordinary dashboard launch, not a fork.
    assert 'call "%~dp0agent-desk.cmd"' in cmd_text()


def test_start_cmd_dev_branch_starts_both_processes():
    text = cmd_text()
    assert "dev" in text
    assert "agentdesk.server --port 8765" in text
    assert "npm --prefix" in text
    assert "run dev" in text


def test_start_cmd_dev_labels_its_windows():
    # Two processes, two windows: the user must be able to tell them apart.
    text = cmd_text()
    assert "agent desk api (dev)" in text
    assert "agent desk ui (dev)" in text


def test_start_cmd_points_pythonpath_at_the_source_tree():
    text = cmd_text()
    assert "pythonpath" in text
    assert "src" in text


def test_start_cmd_gates_on_python_version_not_just_presence():
    assert "version_info >= (3, 10)" in cmd_text()


def test_start_cmd_has_the_same_interpreter_fallbacks():
    text = cmd_text()
    assert "py -3" in text
    assert "uv run --no-project python" in text


def test_start_cmd_checks_npm_and_frontend_before_dev():
    # Honest dead-ends instead of a window that opens and dies.
    text = cmd_text()
    assert "where npm" in text
    assert "frontend\\package.json" in text
    assert "not found" in text


def test_start_cmd_never_elevates():
    for marker in ELEVATION_MARKERS:
        assert marker not in cmd_text(), f"elevation marker found: {marker}"
