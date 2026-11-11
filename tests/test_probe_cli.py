"""CLI wiring tests: --workdir, --self-check, exit-code mapping, report file.

The full CLI flow runs with fake adapters, so no test touches the real
network, OneDrive or EDR. One smoke test spawns a subprocess only to check
`python -m agentdesk.probe --self-check` wiring.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from probe_fakes import (
    FakeOneDriveDiscoverer,
    FakeProcessLister,
    FakeReacher,
    FakeUvFinder,
    SequenceRunner,
)

from agentdesk.probe.adapters import Adapters
from agentdesk.probe.cli import main
from agentdesk.probe.core import RunResult


def all_pass_adapters(workdir: Path, onedrive_dir: Path) -> Adapters:
    onedrive_dir.mkdir(parents=True, exist_ok=True)
    return Adapters(
        runner=SequenceRunner(
            RunResult(returncode=0, stdout="PROBE_OK\n"),  # gate 1
            RunResult(returncode=0),  # gate 2: venv
            RunResult(returncode=0, stdout="Installed 1 package: six"),  # gate 2: install
        ),
        find_uv=FakeUvFinder("uv"),
        reach=FakeReacher(status=200),
        list_processes=FakeProcessLister(stdout='"notepad.exe","900","N/A"\n'),
        discover_onedrive=FakeOneDriveDiscoverer(path=str(onedrive_dir), how="fake discovery"),
    )


def last_stdout_line(capsys):
    out = capsys.readouterr().out
    return [line for line in out.splitlines() if line.strip()][-1]


class TestCliRun:
    def test_go_run_returns_0_writes_report_stdout_verdict(self, tmp_path, capsys):
        adapters = all_pass_adapters(tmp_path, tmp_path / "OneDrive")
        code = main(["--workdir", str(tmp_path / "run")], adapters=adapters)

        assert code == 0
        report = (tmp_path / "run" / "probe-report.md").read_text(encoding="utf-8")
        assert "VERDICT: GO" in report
        for key in ("exec-user-space", "uv-tls-bootstrap", "power-automate-flows", "onedrive-sync", "edr-identity"):
            assert key in report
        assert last_stdout_line(capsys) == "VERDICT: GO"

    def test_gate1_fail_returns_4_and_no_go_report(self, tmp_path, capsys):
        adapters = all_pass_adapters(tmp_path, tmp_path / "OneDrive")
        blocked = Adapters(
            runner=SequenceRunner(RunResult(returncode=1, stderr="blocked by policy")),
            find_uv=adapters.find_uv,
            reach=adapters.reach,
            list_processes=adapters.list_processes,
            discover_onedrive=adapters.discover_onedrive,
        )
        code = main(["--workdir", str(tmp_path / "run")], adapters=blocked)

        assert code == 4
        report = (tmp_path / "run" / "probe-report.md").read_text(encoding="utf-8")
        assert "VERDICT: NO-GO" in report
        assert last_stdout_line(capsys).startswith("VERDICT: NO-GO")

    def test_gate2_fail_returns_3_reshape(self, tmp_path):
        adapters = all_pass_adapters(tmp_path, tmp_path / "OneDrive")
        tls_fail = Adapters(
            runner=SequenceRunner(
                RunResult(returncode=0, stdout="PROBE_OK\n"),  # gate 1 passes
                RunResult(returncode=0),  # gate 2 venv ok
                RunResult(returncode=1, stderr="certificate verify failed"),  # install fails
            ),
            find_uv=adapters.find_uv,
            reach=adapters.reach,
            list_processes=adapters.list_processes,
            discover_onedrive=adapters.discover_onedrive,
        )
        code = main(["--workdir", str(tmp_path / "run")], adapters=tls_fail)

        assert code == 3
        report = (tmp_path / "run" / "probe-report.md").read_text(encoding="utf-8")
        assert "VERDICT: RESHAPE" in report

    def test_creates_missing_workdir(self, tmp_path):
        adapters = all_pass_adapters(tmp_path, tmp_path / "OneDrive")
        target = tmp_path / "deep" / "nested" / "run"
        code = main(["--workdir", str(target)], adapters=adapters)

        assert code == 0
        assert (target / "probe-report.md").exists()

    def test_default_workdir_is_probe_run_in_cwd(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        adapters = all_pass_adapters(tmp_path, tmp_path / "OneDrive")
        code = main([], adapters=adapters)

        assert code == 0
        assert (tmp_path / "probe-run" / "probe-report.md").exists()


class TestCliUsageAndSelfCheck:
    def test_unknown_flag_is_usage_error_exit_2(self):
        assert main(["--bogus-flag"]) == 2

    def test_self_check_exits_0_and_prints_classified_outcomes(self, capsys):
        code = main(["--self-check"])
        out = capsys.readouterr().out

        assert code == 0
        assert "SELF-CHECK OK" in out
        for key in ("exec-user-space", "uv-tls-bootstrap", "power-automate-flows", "onedrive-sync", "edr-identity"):
            assert key in out
        for status in ("PASS", "FAIL", "UNKNOWN"):
            assert status in out

    def test_module_execution_smoke_test(self):
        # `python -m agentdesk.probe --self-check` must work with src on the path.
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "agentdesk.probe", "--self-check"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=env,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "SELF-CHECK OK" in proc.stdout
