"""Gate classification tests: PASS / FAIL / UNKNOWN from fake evidence.

No test here depends on real network, real OneDrive or real EDR presence.
The single real-subprocess test at the bottom only needs a working Python,
which any machine running pytest has.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from probe_fakes import ExplodingRunner, FakeReacher, FakeRunner, FakeUvFinder, SequenceRunner

from agentdesk.probe.core import FAIL, PASS, UNKNOWN, RunResult
from agentdesk.probe.gates import (
    gate_exec_user_space,
    gate_power_automate,
    gate_uv_tls_bootstrap,
)


# ---------------------------------------------------------------------------
# Gate 1: exec-user-space
# ---------------------------------------------------------------------------


class TestGateExecUserSpace:
    def test_pass_when_hello_world_runs(self, tmp_path):
        runner = FakeRunner(returncode=0, stdout="PROBE_OK\n")
        result = gate_exec_user_space(runner, tmp_path)

        assert result.status == PASS
        assert result.key == "exec-user-space"
        assert result.number == 1
        # Evidence includes the exact command and its output, not just yes/no.
        assert any("probe_hello.py" in line for line in result.evidence)
        assert any("PROBE_OK" in line for line in result.evidence)

    def test_pass_actually_executes_written_script_with_current_python(self, tmp_path):
        runner = FakeRunner(returncode=0, stdout="PROBE_OK\n")
        gate_exec_user_space(runner, tmp_path)

        assert len(runner.commands) == 1
        cmd = runner.commands[0]
        assert cmd[0] == sys.executable
        script = Path(cmd[2])
        assert script.parent == tmp_path
        assert "PROBE_OK" in script.read_text(encoding="utf-8")

    def test_fail_on_nonzero_exit(self, tmp_path):
        runner = FakeRunner(returncode=1, stderr="program blocked by policy")
        result = gate_exec_user_space(runner, tmp_path)

        assert result.status == FAIL
        assert any("program blocked by policy" in line for line in result.evidence)
        assert any("rc=1" in line for line in result.evidence)

    def test_fail_on_wrong_output(self, tmp_path):
        runner = FakeRunner(returncode=0, stdout="SOMETHING_ELSE")
        result = gate_exec_user_space(runner, tmp_path)

        assert result.status == FAIL

    def test_fail_when_start_is_blocked(self, tmp_path):
        runner = ExplodingRunner("Access is denied.")
        result = gate_exec_user_space(runner, tmp_path)

        assert result.status == FAIL
        assert any("Access is denied." in line for line in result.evidence)

    def test_real_subprocess_hello_world(self, tmp_path):
        # Integration: the real adapter must execute a user-space script and
        # classify it PASS on any machine where Python itself may run.
        from agentdesk.probe.adapters import subprocess_runner

        result = gate_exec_user_space(subprocess_runner, tmp_path)
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
