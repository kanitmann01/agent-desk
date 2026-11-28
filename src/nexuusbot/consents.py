"""Task-scoped consent allows, keyed (plugin, scope).

The port of the donor approvals module's taskAllows set: accepting an
update-consent card "for this plugin" records an allow for the exact
(plugin, scope) pair, and the next identical re-ask is answered without
prompting again. A widened (different) scope is a different key, so it
always re-asks. Purely in-memory and process-lifetime: a restart forgets
every allow, by construction, which is the honest default for a
permission remembered on the user's behalf.
"""


class ConsentStore:
    """The (plugin, scope) allow set; injectable, inert by nature."""

    def __init__(self) -> None:
        """Start with nothing allowed; a pair only becomes allowed through `allow`."""
        self._allowed: set[tuple[str, str]] = set()

    def allow(self, plugin_id: str, scope: str) -> None:
        """Record: this plugin may widen with exactly this scope again."""
        self._allowed.add((plugin_id, scope))

    def allowed(self, plugin_id: str, scope: str) -> bool:
        """Has this exact (plugin, scope) widening been allowed?"""
        return (plugin_id, scope) in self._allowed

    def clear(self) -> None:
        """Forget every allow (used by tests; restart does it for real)."""
        self._allowed.clear()
