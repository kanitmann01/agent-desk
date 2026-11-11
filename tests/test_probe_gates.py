"""Gate classification tests: PASS / FAIL / UNKNOWN from fake evidence.

No test here depends on real network, real OneDrive or real EDR presence.
The single real-subprocess test at the bottom only needs a working Python,
which any machine running pytest has.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from probe_fakes import (
    ExplodingRunner,
    FakeOneDriveDiscoverer,
    FakeProcessLister,
    FakeReacher,
    FakeRunner,
    FakeUvFinder,
    RecordingCopier,
    RecordingWriter,
    SequenceRunner,
)

from agentdesk.probe.core import FAIL, PASS, UNKNOWN, RunResult
from agentdesk.probe.gates import (
    gate_edr_identity,
    gate_exec_user_space,
    gate_onedrive,
    gate_power_automate,
    gate_uv_tls_bootstrap,
)


# ---------------------------------------------------------------------------
# Gate 1: exec-user-space
# ---------------------------------------------------------------------------


class TestGateExecUserSpace:
    def test_pass_when_hello_world_runs(self, tmp_path):
        runner = FakeRunner(returncode=0, stdout="PROBE_OK\n")
        writer = RecordingWriter()
        result = gate_exec_user_space(runner, tmp_path, writer)

        assert result.status == PASS
        assert result.key == "exec-user-space"
        assert result.number == 1
        # Evidence includes the exact command and its output, not just yes/no.
        assert any("probe_hello.py" in line for line in result.evidence)
        assert any("PROBE_OK" in line for line in result.evidence)

    def test_pass_actually_executes_written_script_with_current_python(self, tmp_path):
        runner = FakeRunner(returncode=0, stdout="PROBE_OK\n")
        writer = RecordingWriter()
        gate_exec_user_space(runner, tmp_path, writer)

        # The script is written through the injected write_text callable.
        assert len(writer.calls) == 1
        script_path, script_text, _encoding = writer.calls[0]
        assert script_path.parent == tmp_path
        assert "PROBE_OK" in script_text
        # The executed command points at exactly the written script.
        assert len(runner.commands) == 1
        cmd = runner.commands[0]
        assert cmd[0] == sys.executable
        assert Path(cmd[2]) == script_path

    def test_fail_on_nonzero_exit(self, tmp_path):
        runner = FakeRunner(returncode=1, stderr="program blocked by policy")
        result = gate_exec_user_space(runner, tmp_path, RecordingWriter())

        assert result.status == FAIL
        assert any("program blocked by policy" in line for line in result.evidence)
        assert any("rc=1" in line for line in result.evidence)

    def test_fail_on_wrong_output(self, tmp_path):
        runner = FakeRunner(returncode=0, stdout="SOMETHING_ELSE")
        result = gate_exec_user_space(runner, tmp_path, RecordingWriter())

        assert result.status == FAIL

    def test_fail_when_start_is_blocked(self, tmp_path):
        runner = ExplodingRunner("Access is denied.")
        result = gate_exec_user_space(runner, tmp_path, RecordingWriter())

        assert result.status == FAIL
        assert any("Access is denied." in line for line in result.evidence)

    def test_real_subprocess_hello_world(self, tmp_path):
        # Integration: the real adapter bundle must write a user-space script
        # and execute it, classifying PASS on any machine where Python runs.
        from agentdesk.probe.adapters import subprocess_runner, write_text

        result = gate_exec_user_space(subprocess_runner, tmp_path, write_text)
        assert result.status == PASS
        assert any("PROBE_OK" in line for line in result.evidence)


# ---------------------------------------------------------------------------
# Gate 2: uv-tls-bootstrap
# ---------------------------------------------------------------------------

CERT_FAILURE_STDERR = (
    "error: failed to fetch six from https://pypi.org/simple/six/\n"
    "Caused by: ssl error: certificate verify failed: self-signed certificate in certificate chain"
)
CONN_FAILURE_STDERR = (
    "error: failed to download six\n"
    "Caused by: operation timed out after connecting to pypi.org"
)


class VenvOkThenExplode:
    """Succeeds the uv venv step, then cannot start the install step."""

    def __init__(self, message="Access is denied."):
        self.message = message
        self.commands = []

    def __call__(self, cmd):
        self.commands.append(list(cmd))
        if "venv" in cmd:
            return RunResult(returncode=0)
        raise OSError(self.message)


class TestGateUvTlsBootstrap:
    def test_unknown_when_uv_is_absent(self, tmp_path):
        runner = FakeRunner()
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder(None))

        assert result.status == UNKNOWN
        assert result.key == "uv-tls-bootstrap"
        assert result.number == 2
        assert any("not found" in line for line in result.evidence)
        assert "uv" in result.note.lower() and "install" in result.note.lower()
        # No install attempt happens without uv.
        assert runner.commands == []

    def test_pass_runs_venv_and_real_install_of_six(self, tmp_path):
        runner = FakeRunner(returncode=0, stdout="Installed 1 package: six")
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == PASS
        assert result.number == 2
        # Two real commands: uv venv under the workdir, then uv pip install six.
        assert len(runner.commands) == 2
        venv_cmd, install_cmd = runner.commands
        assert "venv" in venv_cmd and str(tmp_path) in " ".join(venv_cmd)
        assert "pip" in install_cmd and "install" in install_cmd and "six" in install_cmd
        assert any("six" in line for line in result.evidence)
        assert any("rc=0" in line for line in result.evidence)

    def test_fail_on_venv_creation_failure(self, tmp_path):
        runner = FakeRunner(returncode=1, stderr="venv creation refused")
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == FAIL
        assert any("venv creation refused" in line for line in result.evidence)
        assert "venv" in result.note.lower()

    def test_fail_when_venv_creation_cannot_start(self, tmp_path):
        runner = ExplodingRunner("Access is denied.")
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == FAIL
        assert any("Access is denied." in line for line in result.evidence)
        assert "start" in result.note.lower()
        assert "block" in result.note.lower()

    def test_fail_when_install_cannot_start(self, tmp_path):
        runner = VenvOkThenExplode("Access is denied.")
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == FAIL
        assert any("Access is denied." in line for line in result.evidence)
        assert "start" in result.note.lower()
        assert "block" in result.note.lower()

    def test_pass_keeps_evidence_for_both_venv_and_install(self, tmp_path):
        runner = SequenceRunner(
            RunResult(returncode=0, stdout="Created virtual environment"),  # venv
            RunResult(returncode=0, stdout="Installed 1 package: six"),  # install
        )
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == PASS
        joined = "\n".join(result.evidence)
        # Both commands survive in the final evidence, with their outcomes.
        assert joined.count("command:") == 2
        assert "venv" in joined
        assert "pip" in joined and "six" in joined
        assert "Created virtual environment" in joined
        assert "Installed 1 package: six" in joined

    def test_fail_classification_reads_stdout_too(self, tmp_path):
        # uv sometimes prints the failure reason on stdout, not stderr.
        runner = SequenceRunner(
            RunResult(returncode=0),
            RunResult(returncode=1, stdout="certificate verify failed: self-signed certificate"),
        )
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == FAIL
        assert "TLS inspection or proxy" in result.note

    def test_fail_certificates_are_reported_as_tls_inspection(self, tmp_path):
        runner = SequenceRunner(
            RunResult(returncode=0),  # venv creation ok
            RunResult(returncode=1, stderr=CERT_FAILURE_STDERR),  # install fails
        )
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == FAIL
        assert "TLS inspection or proxy" in result.note
        assert any("certificate verify failed" in line for line in result.evidence)

    def test_fail_connection_timeout_is_reported_as_blocked_host(self, tmp_path):
        runner = SequenceRunner(
            RunResult(returncode=0),
            RunResult(returncode=1, stderr=CONN_FAILURE_STDERR),
        )
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == FAIL
        assert "blocked host" in result.note
        assert any("timed out" in line for line in result.evidence)

    def test_fail_unclassified_stderr_still_fails_with_evidence(self, tmp_path):
        runner = SequenceRunner(
            RunResult(returncode=0),
            RunResult(returncode=1, stderr="something unexpected happened"),
        )
        result = gate_uv_tls_bootstrap(runner, tmp_path, find_uv=FakeUvFinder("uv"))

        assert result.status == FAIL
        assert any("something unexpected happened" in line for line in result.evidence)
        assert "unclassified" in result.note


# ---------------------------------------------------------------------------
# Gate 3: power-automate-flows
# ---------------------------------------------------------------------------


class TestGatePowerAutomateFlows:
    def test_reachable_endpoint_is_unknown_with_manual_steps(self):
        reach = FakeReacher(status=200)
        result = gate_power_automate(reach)

        assert result.status == UNKNOWN
        assert result.key == "power-automate-flows"
        assert result.number == 3
        assert any("make.powerautomate.com" in line for line in reach.urls)
        assert any("HTTP 200" in line for line in result.evidence)
        assert "manual" in result.note.lower()

    def test_proxy_denial_status_still_counts_as_reachable(self):
        # Any HTTP status (even 403 from a proxy) proves network reachability;
        # only a browser session can decide license and connector policy.
        reach = FakeReacher(status=403)
        result = gate_power_automate(reach)

        assert result.status == UNKNOWN
        assert any("HTTP 403" in line for line in result.evidence)

    def test_unreachable_endpoint_fails_with_error_evidence(self):
        reach = FakeReacher(error="connection refused by proxy")
        result = gate_power_automate(reach)

        assert result.status == FAIL
        assert any("connection refused by proxy" in line for line in result.evidence)
        assert result.note  # remediation hint present

    def test_reacher_exception_is_a_network_level_failure(self):
        def exploding_reach(url):
            raise OSError("no such interface")

        result = gate_power_automate(exploding_reach)

        assert result.status == FAIL
        assert any("no such interface" in line for line in result.evidence)


# ---------------------------------------------------------------------------
# Gate 4: onedrive-sync
# ---------------------------------------------------------------------------


class TestGateOneDriveSync:
    def test_pass_when_folder_found_and_probe_file_copies(self, tmp_path):
        onedrive_dir = tmp_path / "OneDrive - Contoso"
        onedrive_dir.mkdir()
        workdir = tmp_path / "work"
        workdir.mkdir()
        discover = FakeOneDriveDiscoverer(path=str(onedrive_dir), how="env OneDrive")
        writer = RecordingWriter()
        copier = RecordingCopier()

        result = gate_onedrive(discover, workdir, writer, copier)

        assert result.status == PASS
        assert result.key == "onedrive-sync"
        assert result.number == 4
        assert any(str(onedrive_dir) in line for line in result.evidence)
        assert any("env OneDrive" in line for line in result.evidence)
        # Probe file written and copied through the injected callables.
        assert len(writer.calls) == 1
        assert len(copier.calls) == 1
        source, dest = copier.calls[0]
        assert source.parent == workdir
        assert dest.parent == onedrive_dir
        # A probe file was actually copied into the sync root, uniquely named.
        copied = list(onedrive_dir.glob("agentdesk-probe-*.txt"))
        assert len(copied) == 1
        assert copied[0].read_text(encoding="utf-8").strip()
        assert "manual" in result.note.lower()

    def test_unknown_when_no_folder_found(self, tmp_path):
        result = gate_onedrive(FakeOneDriveDiscoverer(path=None), tmp_path, RecordingWriter(), RecordingCopier())

        assert result.status == UNKNOWN
        assert any("not found" in line for line in result.evidence)
        assert result.note

    def test_fail_when_sync_root_not_usable_for_copy(self, tmp_path):
        # A stale sync root (env var points at a missing folder) simulates
        # the failure mode without touching real permissions.
        discover = FakeOneDriveDiscoverer(path=str(tmp_path / "missing-folder"), how="env OneDrive")

        result = gate_onedrive(discover, tmp_path, RecordingWriter(), RecordingCopier())

        assert result.status == FAIL
        assert result.evidence  # error text captured
        assert result.note


# ---------------------------------------------------------------------------
# Gate 5: edr-identity
# ---------------------------------------------------------------------------

TASKLIST_WITH_EDR = (
    '"CSFalconService.exe","4320","CSFalconService"                \n'
    '"MsMpEng.exe","2210","MsMpEng"                                \n'
    '"chrome.exe","512","N/A"                                      \n'
    '"SentinelAgent.exe","8110","SentinelAgent"                    \n'
)
TASKLIST_CLEAN = '"chrome.exe","512","N/A"\n"notepad.exe","900","N/A"\n'


class TestGateEdrIdentity:
    def test_detects_and_reports_edr_products_with_evidence_lines(self):
        lister = FakeProcessLister(stdout=TASKLIST_WITH_EDR)
        result = gate_edr_identity(lister)

        assert result.status == PASS
        assert result.key == "edr-identity"
        assert result.number == 5
        joined = "\n".join(result.evidence)
        assert "CrowdStrike Falcon" in joined
        assert "Microsoft Defender" in joined
        assert "SentinelOne" in joined
        # Evidence carries the raw tasklist lines, not just product names.
        assert any("CSFalconService.exe" in line for line in result.evidence)
        # Unrelated processes are not reported as EDR.
        assert "chrome.exe" not in joined

    def test_none_detected_is_unknown_not_pass(self):
        lister = FakeProcessLister(stdout=TASKLIST_CLEAN)
        result = gate_edr_identity(lister)

        assert result.status == UNKNOWN
        assert any("none detected" in line for line in result.evidence)
        assert "kernel" in result.note.lower()

    def test_lister_failure_is_unknown_with_error_evidence(self):
        lister = FakeProcessLister(returncode=1, stderr="Access denied")
        result = gate_edr_identity(lister)

        assert result.status == UNKNOWN
        assert any("Access denied" in line for line in result.evidence)


# ---------------------------------------------------------------------------
# Gate 5, macOS: same gate over ps-shaped listing text
# ---------------------------------------------------------------------------

PS_WITH_EDR = (
    "  432 /Library/CSFalconSensor/falcond\n"
    "  811 /Library/SentinelOne/sentinel-agent-811\n"
    "  220 /Library/Microsoft/wdavdaemon\n"
    "  512 /usr/sbin/cupsd\n"
)


class TestGateEdrIdentityMacos:
    """The gate names the listing it actually ran and matches mac daemon names."""

    def test_detects_mac_sensors_and_names_ps_as_the_method(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        lister = FakeProcessLister(stdout=PS_WITH_EDR)
        result = gate_edr_identity(lister)

        assert result.status == PASS
        joined = "\n".join(result.evidence)
        # The evidence names ps, not tasklist: it must match what ran.
        assert "ps -axo pid,comm" in joined
        assert "tasklist" not in joined
        assert "CrowdStrike Falcon" in joined
        assert "SentinelOne" in joined
        assert "Microsoft Defender" in joined
        assert any("falcond" in line for line in result.evidence)
        # Unrelated processes are not reported as EDR.
        assert "cupsd" not in joined

    def test_windows_evidence_names_tasklist(self, monkeypatch):
        monkeypatch.setattr(os, "name", "nt")
        result = gate_edr_identity(FakeProcessLister(stdout=TASKLIST_WITH_EDR))

        assert result.status == PASS
        assert any("tasklist /svc" in line for line in result.evidence)

    def test_none_detected_note_names_the_actual_command(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        result = gate_edr_identity(FakeProcessLister(stdout="  512 /usr/sbin/cupsd\n"))

        assert result.status == UNKNOWN
        assert "ps -axo pid,comm" in result.note
        assert "kernel" in result.note.lower()

    def test_lister_failure_evidence_names_the_actual_command(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        result = gate_edr_identity(FakeProcessLister(returncode=1, stderr="permission denied"))

        assert result.status == UNKNOWN
        assert any("ps -axo pid,comm" in line for line in result.evidence)
        assert any("permission denied" in line for line in result.evidence)
