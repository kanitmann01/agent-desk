"""The host-side Outlook metadata feeder.

A platform-agnostic core: collectors hand back the existing
nexuusbot.mail.core.Message records (headers only, no body field), one
writer turns them into header-only .eml files that parse_eml reads, and
the runner owns the pass, the lock and the honest status. The platform
branch lives in one module; no HTTP client and no model client exists
anywhere in this package.
"""

from nexuusbot.feeder.contract import MailCollector, UnavailableCollector
from nexuusbot.feeder.platform import default_collectors
from nexuusbot.feeder.runner import OutlookFeeder
from nexuusbot.feeder.writer import render_eml, write_mail, write_status

__all__ = [
    "MailCollector",
    "OutlookFeeder",
    "UnavailableCollector",
    "default_collectors",
    "render_eml",
    "write_mail",
    "write_status",
]
