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

from probe_fakes import ExplodingRunner, FakeRunner

from agentdesk.probe.core import FAIL, PASS
from agentdesk.probe.gates import gate_exec_user_space


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
