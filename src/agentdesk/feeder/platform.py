"""The one platform branch: which collectors this host should try.

The core never asks what platform it is on; it asks each collector
whether it is available. This module is where that list is built, so a
platform import stays out of the contract, the writer and the runner.
The Windows WPN reader and the macOS Notification Center reader are
chosen here, each alone so its own unavailable cause (no Outlook
handler, Full Disk Access) reaches the status. Only a platform with no
reader gets the manual fallback.
"""

import sys

from agentdesk.feeder.collectors.mac_notifications import MacNotificationCollector
from agentdesk.feeder.collectors.wpn import WpnCollector
from agentdesk.feeder.contract import MailCollector, UnavailableCollector


def current_platform() -> str:
    """The host platform label recorded in the feeder status."""
    return sys.platform


def default_collectors(platform: str | None = None) -> tuple[MailCollector, ...]:
    """The collectors to try, in trust order, on this host.

    win32 tries the Windows toast reader, darwin tries the macOS
    Notification Center reader, and every other label gets the manual
    fallback alone. The reader stands alone so its own unavailable cause
    (no Outlook handler, a missing store, Full Disk Access) is what the
    status records instead of a generic manual sentence. The platform
    parameter is the seam tests use; None means this host.
    """
    label = current_platform() if platform is None else platform
    if label == "win32":
        return (WpnCollector(),)
    if label == "darwin":
        return (MacNotificationCollector(),)
    return (UnavailableCollector(),)
