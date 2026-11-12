"""Shared data model and constants for the environment probe.

The probe answers five go/no-go gates for running personal agents on a
locked-down corporate Windows laptop. Everything decisive here is a pure
data structure so gate logic and the verdict aggregator stay testable with
fakes on any machine.
"""

from dataclasses import dataclass

# Gate statuses
PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

# Gate keys (stable identifiers used in reports, verdicts and tests)
GATE_EXEC = "exec-user-space"
GATE_UV = "uv-tls-bootstrap"
GATE_FLOW = "power-automate-flows"
GATE_ONEDRIVE = "onedrive-sync"
GATE_EDR = "edr-identity"

GATE_KEYS = (GATE_EXEC, GATE_UV, GATE_FLOW, GATE_ONEDRIVE, GATE_EDR)

# The Power Automate endpoint gate 3 checks (single definition, imported by
# the adapters and gates modules).
POWER_AUTOMATE_URL = "https://make.powerautomate.com"

# Verdicts
VERDICT_GO = "GO"
VERDICT_RESHAPE = "RESHAPE"
VERDICT_NO_GO = "NO-GO"

# Exit codes
EXIT_GO = 0
EXIT_USAGE = 2
EXIT_RESHAPE = 3
EXIT_NO_GO = 4


@dataclass(frozen=True)
class RunResult:
    """Outcome of one command execution (real or faked)."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    error: str = ""  # set when the command could not start, or it timed out


@dataclass(frozen=True)
class ReachResult:
    """Outcome of one HTTPS reachability check."""

    url: str
    status: int | None = None  # HTTP status when a response arrived
    error: str | None = None  # connection-level failure text, if any


@dataclass(frozen=True)
class OneDriveInfo:
    """A discovered OneDrive sync root and how it was found."""

    path: str
    how: str


@dataclass(frozen=True)
class GateResult:
    """One gate's answer with evidence lines (command output or method)."""

    key: str
    number: int
    title: str
    status: str
    evidence: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Verdict:
    """Aggregated go/no-go answer over all gate results."""

    name: str
    detail: str = ""  # names failed gates with one remediation clause each
    notes: tuple[str, ...] = ()  # caveats (e.g. uv absent) that do not block GO
    # GateResult is defined above: the annotation is evaluated eagerly on
    # Pythons before 3.14 (PEP 649 made it lazy there), and a forward
    # reference to a later class is a NameError at import time on them.
    failed_gates: tuple[GateResult, ...] = ()

    @property
    def exit_code(self) -> int:
        return {VERDICT_GO: EXIT_GO, VERDICT_RESHAPE: EXIT_RESHAPE, VERDICT_NO_GO: EXIT_NO_GO}[self.name]
