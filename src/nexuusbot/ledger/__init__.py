"""The action ledger, and the one gate that keeps four things ask-first.

Every change the desk makes by itself is recorded here with the before and
after state, so Activity can show it and Undo can put the earlier state
back. Recording is not permission: may_act decides whether a class of
action may ever happen without asking, and the ask-first classes cannot be
talked out of it by any setting.
"""

from nexuusbot.ledger.store import Entry, Ledger, LedgerError
from nexuusbot.settings import SettingsStore

# The four classes that always ask first, whatever the autonomy setting
# says (spec §8): sending mail, deleting user data, and installing or
# uninstalling a plugin. Enforced here, not at the call sites.
ASK_FIRST = frozenset({"mail.send", "data.delete", "plugin.uninstall", "plugin.install"})


def may_act(settings: SettingsStore, action: str) -> bool:
    """Whether the desk may take this action by itself, without asking.

    Ask-first actions never may, whatever the setting; everything else
    follows the autonomy toggle, which is on by default.
    """
    return action not in ASK_FIRST and settings.get("autonomy") is True


__all__ = [
    "ASK_FIRST",
    "Entry",
    "Ledger",
    "LedgerError",
    "may_act",
]
