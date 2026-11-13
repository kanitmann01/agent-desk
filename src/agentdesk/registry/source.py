"""Where the app's registry checkout lives, and what it offers.

Resolution order (each step honest about where it came from): the
in-app settings key ``registry_path``, the ``AGENTDESK_REGISTRY``
environment variable (config.env lands there), then the repository
checkout the app itself runs from. No step ever touches the network:
the registry is a local git checkout by design, and the add-source-by-
URL escape hatch stays off.
"""
from __future__ import annotations

import os
from pathlib import Path

from .index import RegistryIndexError, load_index
from .install import RegistryError, install_from_registry

SETTINGS_KEY = "registry_path"
ENV_KEY = "AGENTDESK_REGISTRY"


def discover_repo_registry() -> Path | None:
    """The registry/ directory of the checkout this code runs from.

    Walks up from this file (src/agentdesk/registry/source.py) looking
    for registry/index.json, so a source checkout serves its own
    registry and an installed package finds nothing (the honest
    unavailable state, not a guessed path).
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "registry" / "index.json"
        if candidate.is_file():
            return parent / "registry"
    return None


def resolve_registry_root(settings_store=None, environ=None) -> tuple[Path | None, str]:
    """(root, origin) with origin naming which step answered.

    The origin string is shown on the plugins page so the user always
    knows which registry they are browsing: a saved setting, the
    environment, this checkout, or none.
    """
    environ = os.environ if environ is None else environ
    if settings_store is not None:
        explicit = str(settings_store.get(SETTINGS_KEY) or "").strip()
        if explicit:
            return Path(explicit), "setting"
    env = str(environ.get(ENV_KEY, "")).strip()
    if env:
        return Path(env), "environment"
    discovered = discover_repo_registry()
    if discovered is not None:
        return discovered, "checkout"
    return None, "none"


def registry_listing(root: Path | None) -> dict:
    """The index as the app serves it: entries, or a named refusal.

    Refusals carry a stable code and a plain-language message; the
    plugins page shows them amber, never as an empty success.
    """
    if root is None:
        return {"ok": False, "error": "registry:not-configured",
                "message": "No plugin registry is configured. Set one in "
                           "Settings (a local git checkout of the registry)."}
    root = Path(root)
    try:
        index = load_index((root / "index.json").read_text(encoding="utf-8"))
    except OSError as exc:
        return {"ok": False, "error": "registry:index-unreadable",
                "message": f"The registry folder is not readable: {exc}"}
    except RegistryIndexError as exc:
        return {"ok": False, "error": "registry:index-invalid",
                "message": f"The registry index is not valid: {exc}"}
    return {
        "ok": True,
        "path": str(root),
        "plugins": [
            {
                "id": entry.id,
                "publisher": entry.publisher,
                "latest": entry.latest,
                "risk": entry.risk,
                "class": entry.class_,
                "releases": [
                    {"version": r.version, "sha256": r.sha256, "tag": r.tag,
                     "yanked": r.yanked, "source": r.source}
                    for r in entry.releases
                ],
            }
            for entry in index.plugins
        ],
    }


def stage_registry_install(root: Path, plugin_id: str, *,
                           version: str | None = None,
                           sha256: str | None = None,
                           staging_dir: Path) -> dict:
    """Resolve a pin, verify it, and land the plugin in ``staging_dir``.

    All verification stays in the registry machinery: the pin resolves
    against the index, the tag is extracted with git archive, the tree
    digest is recomputed and compared, and the shared validator runs
    before anything is handed to the plugin runtime. The caller gets
    the staged plugin directory plus the exact pin it installed.
    """
    root = Path(root)
    if version is None or not version.strip():
        try:
            index = load_index((root / "index.json").read_text(encoding="utf-8"))
        except (OSError, RegistryIndexError) as exc:
            raise RegistryError("install:index-unreadable", str(exc)) from exc
        entry = index.plugin(plugin_id)
        if entry is None:
            raise RegistryError("install:unknown-plugin",
                                f"no plugin {plugin_id}")
        version = entry.latest
    install_from_registry(root, plugin_id, version=version, sha256=sha256,
                          destination=staging_dir)
    staged = Path(staging_dir) / f"{plugin_id}-{version}"
    return {"dir": staged, "version": version, "plugin": plugin_id}
