"""Gate implementations for the environment probe.

Every gate takes its side effects (command execution, URL reachability,
process listing, OneDrive discovery) as injectable callables so tests can
pass fakes; the default adapters live in agentdesk.probe.adapters.
"""

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from agentdesk.probe.core import (
    FAIL,
    GATE_EXEC,
    GATE_FLOW,
    GATE_EDR,
    GATE_ONEDRIVE,
    GATE_UV,
    PASS,
    UNKNOWN,
    GateResult,
    OneDriveInfo,
    ReachResult,
    RunResult,
)

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


POWER_AUTOMATE_URL = "https://make.powerautomate.com"

MANUAL_FLOW_STEPS = (
    "manual check required: open https://make.powerautomate.com in a browser, "
    "sign in with the corporate account, choose Create > Instant cloud flow, "
    "and confirm a personal (non-solution) flow with an Office 365 Outlook "
    "connector can be saved"
)


def gate_power_automate(reach) -> GateResult:
    """Gate 3: can the user create a personal Power Automate cloud flow.

    Creating a flow needs an interactive browser session, so this gate can
    never fully pass from the laptop. The probe checks network reachability
    of make.powerautomate.com with the injectable reacher and reports the
    manual steps. Reachable (any HTTP status) -> UNKNOWN with instructions.
    Connection-level unreachable -> FAIL, evidence toward RESHAPE.
    """
    try:
        res = reach(POWER_AUTOMATE_URL)
    except OSError as exc:
        return GateResult(
            key=GATE_FLOW,
            number=3,
            title="Power Automate personal cloud flows",
            status=FAIL,
            evidence=(f"GET {POWER_AUTOMATE_URL} failed before any response: {exc}",),
            note="the Power Automate endpoint is unreachable at network level; ask IT to allow make.powerautomate.com",
        )

    assert isinstance(res, ReachResult)
    if res.status is not None:
        return GateResult(
            key=GATE_FLOW,
            number=3,
            title="Power Automate personal cloud flows",
            status=UNKNOWN,
            evidence=(f"GET {POWER_AUTOMATE_URL} -> HTTP {res.status} (endpoint reachable)",),
            note=MANUAL_FLOW_STEPS,
        )

    return GateResult(
        key=GATE_FLOW,
        number=3,
        title="Power Automate personal cloud flows",
        status=FAIL,
        evidence=(f"GET {POWER_AUTOMATE_URL} failed: {res.error}",),
        note="the Power Automate endpoint is unreachable at network level; ask IT to allow make.powerautomate.com",
    )


ONEDRIVE_PROBE_NAME = "onedrive-probe.txt"


def gate_onedrive(discover, workdir: Path) -> GateResult:
    """Gate 4: is the OneDrive client present and syncing to the local profile.

    Looks for the sync root via the injectable discoverer, writes a probe
    file into the workdir and copies it into the sync root. Upload is never
    verified here (that needs the sync engine and time); the note says so.
    PASS = folder found and writable; UNKNOWN = no folder found.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    info = discover()
    if info is None:
        return GateResult(
            key=GATE_ONEDRIVE,
            number=4,
            title="OneDrive sync root",
            status=UNKNOWN,
            evidence=("OneDrive sync root: not found (no OneDrive* environment variable, no OneDrive* folder under the user profile)",),
            note="no OneDrive folder found; sign in to the OneDrive client manually, then re-run the probe",
        )

    assert isinstance(info, OneDriveInfo)
    source = workdir / ONEDRIVE_PROBE_NAME
    source.write_text("agentdesk probe sync test file; safe to delete\n", encoding="utf-8")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path(info.path) / f"agentdesk-probe-{stamp}.txt"
    evidence = [
        f"sync root: {info.path}",
        f"detection method: {info.how}",
        f"probe file: {source} -> {dest}",
    ]

    try:
        shutil.copy(source, dest)
    except OSError as exc:
        evidence.append(f"error: {exc}")
        return GateResult(
            key=GATE_ONEDRIVE,
            number=4,
            title="OneDrive sync root",
            status=FAIL,
            evidence=tuple(evidence),
            note="the OneDrive folder exists but is not writable; check the sync root and OneDrive sign-in",
        )

    evidence.append("copied into the sync root; upload not verified")
    return GateResult(
        key=GATE_ONEDRIVE,
        number=4,
        title="OneDrive sync root",
        status=PASS,
        evidence=tuple(evidence),
        note=(
            "sync confirmation is manual: check the probe file appears in OneDrive "
            "(File Explorer sync status or onedrive.live.com); the file is safe to delete"
        ),
    )


# Curated EDR/AV signatures: (product name, case-insensitive tokens matched
# against tasklist image names and service names).
EDR_SIGNATURES = (
    ("CrowdStrike Falcon", ("csfalcon", "csagent")),
    ("SentinelOne", ("sentinelagent", "sentinelone", "sentinelservicehost")),
    ("Microsoft Defender", ("msmpeng", "mssense")),
    ("Carbon Black", ("carbonblack", "cbdefense", "repmgr", "bdservicehost")),
    ("Trellix", ("trellix", "mfeagf", "masvc", "mfeavs")),
    ("McAfee", ("mcafee", "mcshield", "mfemms")),
)


def gate_edr_identity(list_processes) -> GateResult:
    """Gate 5: which EDR product is running.

    Scans tasklist process and service output (via the injectable lister)
    against a curated signature list. Informational: PASS when at least one
    product is identified, UNKNOWN when none is visible to a standard user
    (kernel-level agents may still be present) or tasklist itself fails.
    """
    res = list_processes()
    if res.returncode != 0:
        detail = res.stderr or res.error or f"rc={res.returncode}"
        return GateResult(
            key=GATE_EDR,
            number=5,
            title="EDR / AV identity",
            status=UNKNOWN,
            evidence=(f"tasklist failed: {detail}",),
            note="could not list processes; identify the EDR product manually",
        )

    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    detected = []
    evidence = ["detection method: tasklist /svc process and service scan against a curated signature list"]
    for product, tokens in EDR_SIGNATURES:
        matched = [line for line in lines if any(token in line.lower() for token in tokens)]
        if matched:
            detected.append(product)
            evidence.append(f"{product}: " + " | ".join(matched[:3]))

    if detected:
        evidence.append(f"detected products: {', '.join(detected)}")
        return GateResult(
            key=GATE_EDR,
            number=5,
            title="EDR / AV identity",
            status=PASS,
            evidence=tuple(evidence),
        )

    evidence.append("none detected")
    return GateResult(
        key=GATE_EDR,
        number=5,
        title="EDR / AV identity",
        status=UNKNOWN,
        evidence=tuple(evidence),
        note="no EDR or AV is visible to a standard user via tasklist; kernel-level agents may still be present",
    )
