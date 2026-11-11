"""Gate implementations for the environment probe.

Every gate takes its side effects (command execution, URL reachability,
process listing, OneDrive discovery) as injectable callables so tests can
pass fakes; the default adapters live in agentdesk.probe.adapters.
"""

import os
import sys
from pathlib import Path

from agentdesk.probe.core import FAIL, GATE_EXEC, GATE_UV, PASS, UNKNOWN, GateResult, RunResult

HELLO_SCRIPT_NAME = "probe_hello.py"
HELLO_MARKER = "PROBE_OK"

VENV_DIR_NAME = "probe-venv"
INSTALL_PACKAGE = "six"

# Keyword sets used to classify uv install failures; TLS hints are checked
# first because certificate errors often also mention connections.
TLS_HINTS = ("certificate", "ssl", "tls", "self-signed", "pkix", "proxy", "trust")
CONNECTION_HINTS = (
    "timed out",
    "timeout",
    "connection",
    "refused",
    "unreachable",
    "resolve",
    "network",
    "temporary failure",
    "getaddrinfo",
)


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


def classify_install_failure(text: str) -> str:
    """Map raw uv stderr/error text to a human failure mode."""
    lowered = (text or "").lower()
    for hint in TLS_HINTS:
        if hint in lowered:
            return f"TLS inspection or proxy interference (matched: {hint})"
    for hint in CONNECTION_HINTS:
        if hint in lowered:
            return f"blocked host or proxy (matched: {hint})"
    return "unclassified failure"


def gate_uv_tls_bootstrap(runner, workdir: Path, find_uv) -> GateResult:
    """Gate 2: can uv bootstrap itself and install packages under corporate TLS.

    Requires uv on PATH (UNKNOWN, with manual-install instructions, when
    absent). Otherwise creates a venv under the workdir and installs the tiny
    pure-python package `six` into it through the injectable runner. Failures
    are classified as TLS/proxy, blocked host, or unclassified, with the raw
    stderr kept as evidence.
    """
    uv = find_uv()
    if not uv:
        return GateResult(
            key=GATE_UV,
            number=2,
            title="uv bootstrap under corporate TLS",
            status=UNKNOWN,
            evidence=("uv lookup on PATH: not found",),
            note=(
                "uv is not installed for this user; install it manually per the "
                "project docs, then re-run the probe to test package installs"
            ),
        )

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    venv_dir = workdir / VENV_DIR_NAME
    venv_cmd = [uv, "venv", str(venv_dir)]
    evidence = [f"command: {' '.join(venv_cmd)}"]

    try:
        venv_res = runner(venv_cmd)
    except OSError as exc:
        evidence.append(f"error: {exc}")
        return GateResult(
            key=GATE_UV,
            number=2,
            title="uv bootstrap under corporate TLS",
            status=FAIL,
            evidence=tuple(evidence),
            note="uv itself could not be started; application control may block it",
        )

    if venv_res.returncode != 0:
        evidence.append(_runner_result(venv_res))
        return GateResult(
            key=GATE_UV,
            number=2,
            title="uv bootstrap under corporate TLS",
            status=FAIL,
            evidence=tuple(evidence),
            note="uv venv creation failed; uv may not be usable under application control",
        )

    is_windows = os.name == "nt"
    python_exe = venv_dir / ("Scripts" if is_windows else "bin") / ("python.exe" if is_windows else "python")
    install_cmd = [uv, "pip", "install", "--python", str(python_exe), INSTALL_PACKAGE]
    evidence = [f"command: {' '.join(install_cmd)}"]

    try:
        install_res = runner(install_cmd)
    except OSError as exc:
        evidence.append(f"error: {exc}")
        return GateResult(
            key=GATE_UV,
            number=2,
            title="uv bootstrap under corporate TLS",
            status=FAIL,
            evidence=tuple(evidence),
            note="uv pip install could not be started; application control may block it",
        )

    if install_res.returncode == 0:
        evidence.append(_runner_result(install_res))
        return GateResult(
            key=GATE_UV,
            number=2,
            title="uv bootstrap under corporate TLS",
            status=PASS,
            evidence=tuple(evidence),
        )

    classification = classify_install_failure(install_res.stderr or install_res.error)
    evidence.append(_runner_result(install_res))
    evidence.append(f"failure mode: {classification}")
    return GateResult(
        key=GATE_UV,
        number=2,
        title="uv bootstrap under corporate TLS",
        status=FAIL,
        evidence=tuple(evidence),
        note=f"uv package install failed: {classification}",
    )
