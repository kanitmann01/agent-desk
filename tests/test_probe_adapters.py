"""Adapter-level tests, two hermeticity levels.

The subprocess-runner tests need a real child process (no network, no
files). The platform-selection tests (which listing command, which
OneDrive sync-root shape) pass the platform explicitly and monkeypatch
Path.home, so the same code paths run on any host without touching
anything outside tmp_path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.probe.adapters import discover_onedrive, list_processes, subprocess_runner
from agentdesk.probe.core import OneDriveInfo, RunResult


class TestSubprocessRunnerDecoding:
    def test_undecodable_output_bytes_become_replacement_characters(self):
        # A real child emitting bytes that are undefined in Western codepages
        # (and invalid UTF-8) must not kill the output reader: the runner
        # decodes with replacement instead of raising or losing all stdout.
        code = "import sys; sys.stdout.buffer.write(b'ok\\x81\\x9dend\\n')"
        result = subprocess_runner([sys.executable, "-I", "-c", code], timeout=60)

        assert isinstance(result, RunResult)
        assert result.returncode == 0, result.error
        assert "ok" in result.stdout and "end" in result.stdout
        assert "\ufffd" in result.stdout  # U+FFFD replacement characters


class RecordingRunner:
    """Stands in for subprocess_runner; records the command it was handed."""

    def __init__(self):
        self.commands = []

    def __call__(self, cmd, timeout=120):
        self.commands.append(list(cmd))
        return RunResult(returncode=0, stdout="PID   COMMAND\n  1  /sbin/launchd\n")


class TestListProcessesPlatform:
    def test_windows_asks_tasklist_for_processes_and_services(self, monkeypatch):
        runner = RecordingRunner()
        monkeypatch.setattr("agentdesk.probe.adapters.subprocess_runner", runner)

        result = list_processes(windows=True)

        assert isinstance(result, RunResult)
        assert runner.commands == [["tasklist", "/svc", "/fo", "csv", "/nh"]]

    def test_everything_else_uses_the_portable_ps_shape(self, monkeypatch):
        runner = RecordingRunner()
        monkeypatch.setattr("agentdesk.probe.adapters.subprocess_runner", runner)

        result = list_processes(windows=False)

        assert isinstance(result, RunResult)
        assert runner.commands == [["ps", "-axo", "pid,comm"]]


class TestDiscoverOneDrivePlatform:
    def test_macos_sync_root_found_under_cloudstorage(self, monkeypatch, tmp_path):
        # macOS mounts the sync root as ~/Library/CloudStorage/OneDrive-<tenant>;
        # the glob means the exact tenant suffix never matters.
        root = tmp_path / "Library" / "CloudStorage" / "OneDrive-Contoso"
        root.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # The Windows environment variables are not consulted on macOS, even
        # when one happens to be set in the test's own environment.
        monkeypatch.setenv("OneDrive", str(tmp_path))

        info = discover_onedrive(windows=False)

        assert isinstance(info, OneDriveInfo)
        assert info.path == str(root)
        assert "CloudStorage" in info.how

    def test_macos_answers_none_without_a_cloudstorage_folder(self, monkeypatch, tmp_path):
        (tmp_path / "Library" / "CloudStorage").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        assert discover_onedrive(windows=False) is None

    def test_windows_environment_variable_still_wins_first(self, monkeypatch, tmp_path):
        od = tmp_path / "od"
        od.mkdir()
        monkeypatch.setenv("OneDrive", str(od))

        info = discover_onedrive(windows=True)

        assert info == OneDriveInfo(path=str(od), how="environment variable OneDrive")

    def test_windows_profile_glob_still_the_fallback(self, monkeypatch, tmp_path):
        for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            monkeypatch.delenv(var, raising=False)
        profile = tmp_path / "profile"
        (profile / "OneDrive - Contoso").mkdir(parents=True)
        monkeypatch.setenv("USERPROFILE", str(profile))

        info = discover_onedrive(windows=True)

        assert info is not None
        assert info.path == str(profile / "OneDrive - Contoso")
        assert "USERPROFILE" in info.how
