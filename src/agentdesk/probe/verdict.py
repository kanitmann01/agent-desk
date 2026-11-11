"""Pure verdict aggregation: gate results -> GO / RESHAPE / NO-GO.

No side effects, no I/O; fully testable with hand-built GateResults.
"""

from agentdesk.probe.core import (
    FAIL,
    GATE_EDR,
    GATE_EXEC,
    GATE_FLOW,
    GATE_KEYS,
    GATE_ONEDRIVE,
    GATE_UV,
    UNKNOWN,
    VERDICT_GO,
    VERDICT_NO_GO,
    VERDICT_RESHAPE,
    GateResult,
    Verdict,
)

# One remediation clause per gate, used in RESHAPE and NO-GO verdict lines.
REMEDIATIONS = {
    GATE_EXEC: (
        "user-space execution is blocked; request an AppLocker/WDAC exception "
        "for a user-space runtime, or deliver the agent as an approved package"
    ),
    GATE_UV: (
        "package installs fail under corporate TLS; request a proxy/CA "
        "exception or an internal PyPI mirror for uv"
    ),
    GATE_FLOW: (
        "make.powerautomate.com is blocked at network level; ask IT to allow "
        "the Power Automate endpoint, then verify flow creation in a browser"
    ),
    GATE_ONEDRIVE: (
        "the OneDrive sync root is not writable; verify OneDrive sign-in and "
        "the sync root folder"
    ),
}


def _detail(failed_gates) -> str:
    return "; ".join(
        f"gate {g.number} ({g.key}): {REMEDIATIONS[g.key]}" for g in failed_gates
    )


def aggregate_verdict(results) -> Verdict:
    """Aggregate the five gate results into a verdict.

    NO-GO when gate 1 fails (nothing may run user-space). RESHAPE for any
    other hard failure (gates 2, 3 or 4 FAIL). GO when gates 1 and 2 are not
    hard failures (gate 2 UNKNOWN, i.e. uv absent, still allows GO with a
    note). Gate 5 is informational and never changes the verdict.
    """
    by_key = {r.key: r for r in results}
    missing = [key for key in GATE_KEYS if key not in by_key]
    if missing:
        raise ValueError(f"aggregate_verdict needs all five gates, missing: {', '.join(missing)}")

    g1 = by_key[GATE_EXEC]
    g2 = by_key[GATE_UV]
    decisive_failures = tuple(
        by_key[key] for key in (GATE_UV, GATE_FLOW, GATE_ONEDRIVE) if by_key[key].status == FAIL
    )

    if g1.status == FAIL:
        return Verdict(
            name=VERDICT_NO_GO,
            detail=_detail((g1,)),
            failed_gates=(g1,),
        )
    if decisive_failures:
        return Verdict(
            name=VERDICT_RESHAPE,
            detail=_detail(decisive_failures),
            failed_gates=decisive_failures,
        )

    notes = ()
    if g2.status == UNKNOWN:
        notes = (f"gate 2 (uv-tls-bootstrap) is UNKNOWN: {g2.note}",)
    return Verdict(name=VERDICT_GO, notes=notes)


def verdict_line(verdict: Verdict) -> str:
    """The single verdict line: VERDICT: GO | VERDICT: RESHAPE (...) | VERDICT: NO-GO (...)."""
    if verdict.name == VERDICT_GO:
        return "VERDICT: GO"
    return f"VERDICT: {verdict.name} ({verdict.detail})"
