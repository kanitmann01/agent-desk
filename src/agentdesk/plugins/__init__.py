"""The plugin runtime: lifecycle for validated Class D plugins.

The runtime is re-exported lazily: the validator's permission lint imports
this package's element vocabulary while the package itself is still being
imported, and the runtime imports the validator back. A lazy attribute keeps
that pair from meeting while both are half-built, and every caller keeps
spelling the runtime the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imports for type checkers only
    from .runtime import PluginError, PluginRuntime, scope_diff

__all__ = ["PluginError", "PluginRuntime", "scope_diff"]


def __getattr__(name: str) -> Any:
    """Resolve a runtime name on first access, importing the runtime then.

    Raises AttributeError for any name outside this package's public list, so
    a typo still fails where it is written.
    """
    if name in __all__:
        from . import runtime

        return getattr(runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
