"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, hermes_cli/doctor_report.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The desk check's primitives: one finding, one check result, the frozen
context a check reads from, the registry that keeps check order, and the
runner that turns one check's crash into a fatal finding instead of a
broken page.

The shape is Hermes' doctor: a Finding dataclass a check fills in, and a
best-effort wrapper (its warn_on_error / doctor_check) so one broken check
cannot take the report down. Here a check returns its own CheckResult, the
registry is an ordered list built by the register decorator, and a crash
becomes the fatal finding deskcheck-crashed:<id> carrying the exception's
class name, so the dashboard and the settings page still render the other
checks' answers.
"""

from dataclasses import dataclass, field
from typing import Callable

# Severities a finding can carry. attention is "the desk wants a human
# look"; fatal is "the check itself broke", never a judgment about the
# desk. info is only worth mentioning.
SEVERITY_INFO = "info"
SEVERITY_ATTENTION = "attention"
SEVERITY_FATAL = "fatal"

# The way a later ticket may offer to settle a finding. Detection only in
# this ticket: nothing here reads should_fix yet.
FIX_AUTO = "auto"      # the desk can do it itself
FIX_ASK = "ask"        # the user confirms it first
FIX_LINK = "link"      # send the user to the place that fixes it
FIX_NONE = "none"      # nothing to do


@dataclass(frozen=True)
class Finding:
    """One thing the desk check noticed, and how a person would settle it."""

    id: str
    title: str
    cause: str
    severity: str
    confident: bool
    fix: str
    fix_label: str
    href: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class CheckResult:
    """What one check contributed: findings, ids it fixed, ids that crashed."""

    findings: list[Finding] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DeskContext:
    """Everything a check may read, with absent collaborators left None.

    A missing collaborator is not an error: a check that needs one skips
    silently, so the desk check still answers on a half-configured desk.
    """

    settings: object = None
    inbox: object = None
    excel: object = None
    calendar: object = None
    plugins: object = None
    catalog_ids: frozenset | None = frozenset()
    data_dir: object = None
    ledger: object = None
    clock: Callable[[], float] | None = None


CheckFn = Callable[[DeskContext, bool], CheckResult]

# Ordered (check_id, check) pairs, registration order = display order.
REGISTRY: list[tuple[str, CheckFn]] = []


def register(check_id: str, title: str):
    """Register a check under its id, with the title a person would read."""
    def decorator(check: CheckFn) -> CheckFn:
        """Append the check under its id, keeping registration order."""
        check.plain_title = title  # type: ignore[attr-defined]
        REGISTRY.append((check_id, check))
        return check

    return decorator


def finding_to_api(finding: Finding) -> dict:
    """One finding in the camelCase shape the HTTP payload and the SPA use."""
    return {
        "id": finding.id,
        "title": finding.title,
        "cause": finding.cause,
        "severity": finding.severity,
        "confident": finding.confident,
        "fix": finding.fix,
        "fixLabel": finding.fix_label,
        "href": finding.href,
        "detail": dict(finding.detail),
    }


def run_checks(ctx: DeskContext, should_fix: bool = False) -> CheckResult:
    """Run every registered check in order, surviving any single crash.

    A check that raises contributes one fatal finding named after it and one
    entry in failed; the checks after it still run, so one bug never hides
    the rest of the desk's state.
    """
    result = CheckResult()
    for check_id, check in REGISTRY:
        try:
            contribution = check(ctx, should_fix)
        except Exception as exc:  # one broken check must not break the report
            crashed_id = f"deskcheck-crashed:{check_id}"
            plain = getattr(check, "plain_title", "") or "A desk check"
            result.findings.append(Finding(
                id=crashed_id,
                title=plain,
                cause=f"The check raised {type(exc).__name__}, so its answer is missing.",
                severity=SEVERITY_FATAL,
                confident=False,
                fix=FIX_NONE,
                fix_label="",
            ))
            result.failed[crashed_id] = f"{type(exc).__name__}: {exc}"
            continue
        result.findings.extend(contribution.findings)
        result.fixed.extend(contribution.fixed)
        result.failed.update(contribution.failed)
    return result


def summary(result: CheckResult) -> dict:
    """The dashboard's one-line view: how much needs attention, and the top finding.

    The top finding is the first fatal one, so a broken check can never be
    buried under a lesser finding; otherwise it is the first attention one.
    """
    attention = [finding for finding in result.findings
                 if finding.severity in (SEVERITY_ATTENTION, SEVERITY_FATAL)]
    top = next((finding for finding in attention
                if finding.severity == SEVERITY_FATAL), None)
    if top is None:
        top = attention[0] if attention else None
    return {
        "attention": len(attention),
        "top": finding_to_api(top) if top is not None else None,
    }
