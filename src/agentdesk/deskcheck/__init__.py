"""The desk check: what the desk notices about itself, read-only.

run_checks walks the registry in registration order and answers one
CheckResult; summary turns it into the dashboard's attention count and top
finding. Importing this package imports checks, which is what registers them.
"""

from agentdesk.deskcheck import checks  # noqa: F401  (import registers the checks)
from agentdesk.deskcheck.fixes import (
    FIXES,
    MAX_FAILURES,
    FixOutcome,
    apply_fix,
)
from agentdesk.deskcheck.core import (
    FIX_ASK,
    FIX_AUTO,
    FIX_LINK,
    FIX_NONE,
    REGISTRY,
    SEVERITY_ATTENTION,
    SEVERITY_FATAL,
    SEVERITY_INFO,
    CheckFn,
    CheckResult,
    DeskContext,
    Finding,
    finding_to_api,
    register,
    run_checks,
    summary,
)

__all__ = [
    "FIXES",
    "FIX_ASK",
    "FIX_AUTO",
    "FIX_LINK",
    "FIX_NONE",
    "MAX_FAILURES",
    "REGISTRY",
    "SEVERITY_ATTENTION",
    "SEVERITY_FATAL",
    "SEVERITY_INFO",
    "CheckFn",
    "CheckResult",
    "DeskContext",
    "Finding",
    "FixOutcome",
    "apply_fix",
    "finding_to_api",
    "register",
    "run_checks",
    "summary",
]
