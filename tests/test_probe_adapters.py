"""Adapter-level tests that need a real child process (no network, no files).

Gate classification tests stay hermetic; the tests here only spawn the
current Python to prove the real runner tolerates hostile subprocess output.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.probe.adapters import subprocess_runner
from agentdesk.probe.core import RunResult


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
