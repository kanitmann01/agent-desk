"""Command line interface for the environment probe.

Usage (via tools/probe.cmd or `python -m agentdesk.probe`):

    python -m agentdesk.probe [--workdir DIR] [--self-check]

Never elevates, never writes outside the workdir and the discovered OneDrive
folder. Exit codes: 0 GO, 3 RESHAPE, 4 NO-GO; 2 for usage errors (bad flag)
and environment errors (workdir or report path cannot be written).
With --self-check every gate runs against fakes: exit 0 when every case
matches its expected classification, 1 on any mismatch.
"""

import argparse
import platform
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from agentdesk.probe import adapters as real
from agentdesk.probe import gates
from agentdesk.probe.adapters import Adapters, RunResult
from agentdesk.probe.core import (
    EXIT_USAGE,
    FAIL,
    GATE_EDR,
    GATE_EXEC,
    GATE_FLOW,
    GATE_ONEDRIVE,
    GATE_UV,
    PASS,
    UNKNOWN,
    VERDICT_GO,
    VERDICT_NO_GO,
    VERDICT_RESHAPE,
    GateResult,
    OneDriveInfo,
    ReachResult,
)
from agentdesk.probe.report import render_report, render_summary
from agentdesk.probe.verdict import aggregate_verdict, verdict_line

REPORT_NAME = "probe-report.md"


def run_all_gates(workdir: Path, adapters: Adapters) -> list[GateResult]:
    """Run the five gates in order with the given adapter bundle."""
    return [
        gates.gate_exec_user_space(adapters.runner, workdir, adapters.write_text),
        gates.gate_uv_tls_bootstrap(adapters.runner, workdir, adapters.find_uv),
        gates.gate_power_automate(adapters.reach),
        gates.gate_onedrive(adapters.discover_onedrive, workdir, adapters.write_text, adapters.copy_file),
        gates.gate_edr_identity(adapters.list_processes),
    ]


def _run_probe(workdir: Path, adapters: Adapters) -> int:
    """Run every gate, write the report, print the summary.

    Returns the verdict's exit code, or EXIT_USAGE when the workdir or the
    report cannot be written: a probe that cannot record its findings must not
    report a verdict.
    """
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create workdir {workdir}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    results = run_all_gates(workdir, adapters)
    verdict = aggregate_verdict(results)
    context = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "user": _current_user(),
        "workdir": str(workdir),
    }
    report_path = workdir / REPORT_NAME
    try:
        report_path.write_text(render_report(results, verdict, context), encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write report {report_path}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"Report written to: {report_path}")
    print(render_summary(results, verdict))
    return verdict.exit_code


def _current_user() -> str:
    """The current account name, from the login database or the environment.

    Falls back to "unknown" rather than raising: an unnamed user must not stop
    a probe.
    """
    import getpass

    try:
        return getpass.getuser()
    except Exception:
        import os

        # USERNAME is the Windows spelling; USER and LOGNAME are what POSIX
        # shells and logins set. Any one of them beats reporting "unknown".
        for var in ("USERNAME", "USER", "LOGNAME"):
            value = os.environ.get(var)
            if value:
                return value
        return "unknown"


# ---------------------------------------------------------------------------
# Self-check: run every gate with fakes and print the classified outcomes.
# ---------------------------------------------------------------------------


def _fake_runner(returncode: int, stdout: str = "", stderr: str = ""):
    """A runner that answers every command with the same fixed result."""
    def run(cmd):
        """Return the canned result, whatever the command."""
        return RunResult(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def _fake_sequence(*results):
    """A runner that answers the nth command with the nth result.

    The last result repeats once the sequence runs out, so a gate that calls
    more often than the case lists still gets a classified answer.
    """
    state = {"calls": 0}

    def run(cmd):
        """Return the next canned result, repeating the last one."""
        index = min(state["calls"], len(results) - 1)
        state["calls"] += 1
        return results[index]

    return run


def _mk_gate(key: str, number: int, status: str) -> GateResult:
    """A gate result carrying only what aggregation reads.

    Title mirrors the key and the evidence is a placeholder: these feed verdict
    cases, not a report.
    """
    return GateResult(key=key, number=number, title=key, status=status, evidence=("fake",))


def _self_check() -> int:
    """Run every gate and three verdict cases against fakes, and compare.

    Returns 0 when every case classifies as expected, 1 otherwise. No network,
    no OneDrive write, no EDR scan; the temp workdir is removed either way.
    """
    print("self-check: running every gate with fakes (no network, no OneDrive writes, no EDR scan)")
    tmp = Path(tempfile.mkdtemp(prefix="agentdesk-selfcheck-"))
    ok = True
    try:
        tasklist_with_edr = '"CSFalconService.exe","4320","CSFalconService"\n'
        tasklist_clean = '"notepad.exe","900","N/A"\n'
        onedrive_dir = tmp / "fake-onedrive"
        onedrive_dir.mkdir()
        cases = [
            (
                "gate 1 exec-user-space (hello-world runs)",
                gates.gate_exec_user_space(_fake_runner(0, "PROBE_OK\n"), tmp, real.write_text),
                PASS,
            ),
            (
                "gate 1 exec-user-space (execution blocked)",
                gates.gate_exec_user_space(_fake_runner(1, stderr="blocked"), tmp, real.write_text),
                FAIL,
            ),
            (
                "gate 2 uv-tls-bootstrap (uv absent)",
                gates.gate_uv_tls_bootstrap(_fake_runner(0), tmp, lambda: None),
                UNKNOWN,
            ),
            (
                "gate 2 uv-tls-bootstrap (install ok)",
                gates.gate_uv_tls_bootstrap(
                    _fake_sequence(RunResult(0), RunResult(0, "Installed six")),
                    tmp,
                    lambda: "uv",
                ),
                PASS,
            ),
            (
                "gate 2 uv-tls-bootstrap (certificate failure)",
                gates.gate_uv_tls_bootstrap(
                    _fake_sequence(RunResult(0), RunResult(1, stderr="certificate verify failed")),
                    tmp,
                    lambda: "uv",
                ),
                FAIL,
            ),
            (
                "gate 2 uv-tls-bootstrap (blocked host)",
                gates.gate_uv_tls_bootstrap(
                    _fake_sequence(RunResult(0), RunResult(1, stderr="connection timed out")),
                    tmp,
                    lambda: "uv",
                ),
                FAIL,
            ),
            (
                "gate 3 power-automate-flows (endpoint reachable)",
                gates.gate_power_automate(lambda url: ReachResult(url=url, status=200)),
                UNKNOWN,
            ),
            (
                "gate 3 power-automate-flows (endpoint unreachable)",
                gates.gate_power_automate(lambda url: ReachResult(url=url, error="connection refused")),
                FAIL,
            ),
            (
                "gate 4 onedrive-sync (no folder)",
                gates.gate_onedrive(lambda: None, tmp, real.write_text, real.copy_file),
                UNKNOWN,
            ),
            (
                "gate 4 onedrive-sync (folder writable)",
                gates.gate_onedrive(
                    lambda: OneDriveInfo(path=str(onedrive_dir), how="fake discovery"),
                    tmp,
                    real.write_text,
                    real.copy_file,
                ),
                PASS,
            ),
            (
                "gate 5 edr-identity (product detected)",
                gates.gate_edr_identity(lambda: RunResult(0, stdout=tasklist_with_edr)),
                PASS,
            ),
            (
                "gate 5 edr-identity (none detected)",
                gates.gate_edr_identity(lambda: RunResult(0, stdout=tasklist_clean)),
                UNKNOWN,
            ),
        ]
        for label, result, expected in cases:
            good = result.status == expected
            ok = ok and good
            marker = "ok" if good else "MISMATCH"
            print(f"self-check {label}: classified {result.status} (expected {expected}) {marker}")

        verdict_cases = [
            (
                "aggregation GO",
                [
                    _mk_gate(GATE_EXEC, 1, PASS),
                    _mk_gate(GATE_UV, 2, PASS),
                    _mk_gate(GATE_FLOW, 3, UNKNOWN),
                    _mk_gate(GATE_ONEDRIVE, 4, PASS),
                    _mk_gate(GATE_EDR, 5, UNKNOWN),
                ],
                VERDICT_GO,
            ),
            (
                "aggregation NO-GO via gate 1",
                [
                    _mk_gate(GATE_EXEC, 1, FAIL),
                    _mk_gate(GATE_UV, 2, PASS),
                    _mk_gate(GATE_FLOW, 3, UNKNOWN),
                    _mk_gate(GATE_ONEDRIVE, 4, PASS),
                    _mk_gate(GATE_EDR, 5, UNKNOWN),
                ],
                VERDICT_NO_GO,
            ),
            (
                "aggregation RESHAPE via gate 2",
                [
                    _mk_gate(GATE_EXEC, 1, PASS),
                    _mk_gate(GATE_UV, 2, FAIL),
                    _mk_gate(GATE_FLOW, 3, UNKNOWN),
                    _mk_gate(GATE_ONEDRIVE, 4, PASS),
                    _mk_gate(GATE_EDR, 5, UNKNOWN),
                ],
                VERDICT_RESHAPE,
            ),
        ]
        for label, gate_results, expected in verdict_cases:
            verdict = aggregate_verdict(gate_results)
            good = verdict.name == expected
            ok = ok and good
            print(f"self-check {label}: classified {verdict.name} (expected {expected}) {'ok' if good else 'MISMATCH'}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("SELF-CHECK OK" if ok else "SELF-CHECK FAILED")
    return 0 if ok else 1


def main(argv=None, adapters: Adapters | None = None) -> int:
    """Parse arguments and run the self-check or the real probe.

    Returns the process exit code; argparse's own exits are turned back into
    codes instead of escaping.
    """
    parser = argparse.ArgumentParser(
        prog="agentdesk.probe",
        description="Agent Desk environment probe: go/no-go gates for the target laptop. Never elevates; writes only under --workdir.",
    )
    parser.add_argument("--workdir", default=None, help="scratch + report directory (default: ./probe-run)")
    parser.add_argument("--self-check", action="store_true", help="run every gate with fakes and print classified outcomes")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits 2 on usage errors, 0 on --help
        return int(exc.code or 0)

    if args.self_check:
        return _self_check()

    workdir = Path(args.workdir) if args.workdir else Path.cwd() / "probe-run"
    return _run_probe(workdir, adapters if adapters is not None else real.real_adapters())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
