"""The double-click entry point: tools/probe.cmd.

The .cmd is read as text and asserted by content, never executed by tests:
on the real laptop a human double-clicks it. It must find Python, run the
probe module with the caller's arguments, never elevate, and keep the
window open (pause) so the report is readable.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CMD = REPO_ROOT / "tools" / "probe.cmd"

ELEVATION_MARKERS = ("runas", "-verb runas", "sudo", "elevate")


def cmd_text() -> str:
    return CMD.read_text(encoding="utf-8", errors="replace").lower()


def test_probe_cmd_exists():
    assert CMD.is_file(), f"missing double-click entry: {CMD}"


def test_probe_cmd_runs_the_module_with_passthrough_args():
    text = cmd_text()
    assert "python -m nexuusbot.probe" in text
    assert "%*" in text


def test_probe_cmd_points_pythonpath_at_the_source_tree():
    text = cmd_text()
    assert "src" in text
    assert "pythonpath" in text


def test_probe_cmd_never_elevates():
    text = cmd_text()
    for marker in ELEVATION_MARKERS:
        assert marker not in text, f"elevation marker found: {marker}"


def test_probe_cmd_keeps_window_open():
    assert "pause" in cmd_text()


def test_probe_cmd_has_a_python_fallback():
    text = cmd_text()
    assert "py -3" in text
    assert "not found" in text


def test_probe_cmd_gates_on_python_version_not_just_presence():
    """The Microsoft Store python.exe stub must not hijack the run."""
    text = cmd_text()
    assert "version_info >= (3, 10)" in text


def test_probe_cmd_sets_the_same_tls_spellings_the_launcher_sets():
    """Gate 2 must test uv the way the shipped launcher runs it.

    The app launcher exports both TLS spellings so uv reads the corporate
    trust store; a probe that launches uv without them fails under TLS
    inspection and hands a supported network a false RESHAPE verdict
    (audit plugins F5).
    """
    text = cmd_text()
    assert "uv_system_certs=1" in text
    assert "uv_native_tls=1" in text
