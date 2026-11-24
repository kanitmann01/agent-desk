"""The one platform branch: which collectors this host should try.

The core never asks what platform it is on; it asks each collector
whether it is available. This module is where that list is built, so a
platform import stays out of the contract, the writer and the runner.
I1 ships the manual fallback only: the Windows WPN reader and the macOS
Notification Center reader arrive in later tickets, and they belong in
this function, not in the core.
"""

import sys

from agentdesk.feeder.contract import MailCollector, UnavailableCollector


def current_platform() -> str:
    """The host platform label recorded in the feeder status."""
    return sys.platform


def default_collectors(platform: str | None = None) -> tuple[MailCollector, ...]:
    """The collectors to try, in trust order, on this host.

    The platform parameter is the seam later collectors branch on; I1
    has no platform-specific collector yet, so every platform gets the
    manual fallback and an honest unavailable state that names Save as.
    """
    return (UnavailableCollector(),)
