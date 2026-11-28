"""Compatibility import path for the package now named nexuusbot.

`import agentdesk` and every `agentdesk.*` submodule resolve to the SAME
module objects `nexuusbot` and `nexuusbot.*` resolve to, never to copies,
so plugins and scripts that import either path share one state. Module
identity is part of the contract (Spec 032, stories 28 to 30) and is
proved by tests/test_alias_identity.py and
tests/test_registry_dual_path.py.

How it works: importing this package installs one meta-path finder that
maps every `agentdesk.X` import onto `nexuusbot.X`, hands back the
canonical module object, and registers it in sys.modules under the alias
name too. It then swaps sys.modules["agentdesk"] for the canonical
package module itself, so attribute access goes straight to the real
submodules. The five old module commands keep their existing parser
names through this alias: python -m agentdesk.server,
python -m agentdesk.probe, python -m agentdesk.presentations.cli,
python -m agentdesk.registry and python -m agentdesk.validator.

Nothing here re-exports names: the canonical package is the module.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys

__all__: list[str] = []

_CANONICAL_PACKAGE = "nexuusbot"
_ALIAS_PACKAGE = __name__


class _CanonicalAliasLoader(importlib.abc.Loader):
    """Serve an alias import with the canonical module object and bytes."""

    def __init__(self, canonical_spec: importlib.machinery.ModuleSpec):
        # Capture the canonical loader before the finder replaces the
        # spec's own: the delegate must stay the real source loader.
        self._loader = canonical_spec.loader
        self._canonical_name_value = canonical_spec.name
        self._is_package = canonical_spec.submodule_search_locations is not None

    def _canonical_name(self, alias_name: str) -> str:
        return _CANONICAL_PACKAGE + alias_name[len(_ALIAS_PACKAGE):]

    def create_module(self, spec):
        module = importlib.import_module(self._canonical_name(spec.name))
        # The canonical module is the alias module: same object, both keys.
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module) -> None:
        """Nothing to execute: the canonical module already ran."""

    def get_code(self, fullname: str):
        return self._loader.get_code(self._canonical_name(fullname))

    def get_source(self, fullname: str):
        return self._loader.get_source(self._canonical_name(fullname))

    def get_filename(self, fullname: str | None = None):
        return self._loader.get_filename(
            self._canonical_name(fullname) if fullname else None)

    def is_package(self, fullname: str) -> bool:
        return self._is_package

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._canonical_name_value!r})"


class _CanonicalAliasFinder(importlib.abc.MetaPathFinder):
    """Map every `agentdesk.X` import onto its `nexuusbot.X` module."""

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(_ALIAS_PACKAGE + "."):
            return None
        canonical = _CANONICAL_PACKAGE + fullname[len(_ALIAS_PACKAGE):]
        try:
            spec = importlib.util.find_spec(canonical)
        except (ImportError, AttributeError, ValueError):
            return None
        if spec is None:
            return None
        spec.name = fullname
        spec.loader = _CanonicalAliasLoader(spec)
        return spec


def _install() -> None:
    """Install the finder, then hand the alias name to the canonical module."""
    for finder in sys.meta_path:
        if isinstance(finder, _CanonicalAliasFinder):
            break
    else:
        sys.meta_path.insert(0, _CanonicalAliasFinder())
    sys.modules[_ALIAS_PACKAGE] = importlib.import_module(_CANONICAL_PACKAGE)


_install()
