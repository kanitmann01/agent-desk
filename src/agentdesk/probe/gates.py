"""Gate implementations for the environment probe.

Every gate takes its side effects (command execution, URL reachability,
process listing, OneDrive discovery) as injectable callables so tests can
pass fakes; the default adapters live in agentdesk.probe.adapters.
"""

import sys
from pathlib import Path

from agentdesk.probe.core import FAIL, GATE_EXEC, PASS, GateResult, RunResult

HELLO_SCRIPT_NAME = "probe_hello.py"
HELLO_MARKER = "PROBE_OK"


def _runner_result(res: RunResult) -> str:
    parts = [f"rc={res.returncode}"]
    if res.stdout.strip():
        parts.append(f"stdout: {res.stdout.strip()}")
    if res.stderr.strip():
        parts.append(f"stderr: {res.stderr.strip()}")
    if res.error:
        parts.append(f"error: {res.error}")
    return ", ".join(parts)


def gate_exec_user_space(runner, workdir: Path) -> GateResult:
    """Gate 1: can unsigned user-space code execute at all.

    Writes a trivial runtime hello-world into the workdir and actually
    executes it with the current Python via the injectable runner. A real
    subprocess producing the expected marker is the only PASS condition.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    script = workdir / HELLO_SCRIPT_NAME
    script.write_text(f'print("{HELLO_MARKER}")\n', encoding="utf-8")
    cmd = [sys.executable, "-I", str(script)]
    command_line = " ".join(cmd)
    evidence = [f"command: {command_line}"]

    try:
        res = runner(cmd)
    except OSError as exc:
        evidence.append(f"error: {exc}")
        return GateResult(
            key=GATE_EXEC,
            number=1,
            title="User-space execution",
            status=FAIL,
            evidence=tuple(evidence),
            note="the runtime could not be started; user-space execution looks blocked",
        )

    if res.returncode == 0 and HELLO_MARKER in res.stdout:
        evidence.append(_runner_result(res))
        return GateResult(
            key=GATE_EXEC,
            number=1,
            title="User-space execution",
            status=PASS,
            evidence=tuple(evidence),
        )

    evidence.append(_runner_result(res))
    return GateResult(
        key=GATE_EXEC,
        number=1,
        title="User-space execution",
        status=FAIL,
        evidence=tuple(evidence),
        note="the hello-world did not produce the expected output; user-space execution looks blocked",
    )
