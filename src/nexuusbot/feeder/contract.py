"""The producer seam: what a mail collector is, and the manual fallback.

A collector is deliberately small: a name, an availability answer with
its cause, and one call that returns the existing
nexuusbot.mail.core.Message records. There is no header type here and
no body field: the no-body invariant is inherited from the record the
rest of the mail path already reads, so a collector cannot introduce
one without changing mail.core.

Nothing in this module imports a platform, a subprocess or a network
client. The platform branch lives in nexuusbot.feeder.platform, and the
collectors that use it arrive in later tickets.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from nexuusbot.mail.core import Message

# The manual path is the guaranteed fallback on every platform, so its
# sentence is one plain statement the Settings card can render as is.
MANUAL_COLLECTOR_NAME = "manual"
MANUAL_CAUSE = (
    "No automatic Outlook collector is available on this machine. Save"
    " the messages you want with Save as into the mail folder, and the"
    " desk will read them."
)


@runtime_checkable
class MailCollector(Protocol):
    """One local source of Outlook message headers.

    The runner asks every collector in trust order; the first one whose
    available() is true collects. A collector that cannot run says why
    in one plain sentence, and never raises into the runner for an
    ordinary unavailability.
    """

    name: str

    def available(self) -> tuple[bool, str]:
        """Whether this collector can run now, and its cause when it cannot."""
        ...

    def collect(self, since: datetime, limit: int) -> list[Message]:
        """Headers for messages since the given moment, up to limit of them."""
        ...


@dataclass(frozen=True)
class UnavailableCollector:
    """The manual fallback: never available, never collects anything.

    Its cause names the Save as path, so a desk with no working
    collector still tells the user what to do instead of showing an
    invented zero.
    """

    name: str = MANUAL_COLLECTOR_NAME
    cause: str = MANUAL_CAUSE

    def available(self) -> tuple[bool, str]:
        """Always unavailable, with the manual cause."""
        return False, self.cause

    def collect(self, since: datetime, limit: int) -> list[Message]:
        """Nothing to collect: the manual path is the user's Save as."""
        return []
