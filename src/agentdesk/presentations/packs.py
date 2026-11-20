"""Load presentation packs from the checkout and the user's machine.

A pack is a plugin directory whose manifest contributes
`presentationTemplates`. The checkout's registry is the shipped set.
`~/.agent-desk/templates` (or AGENTDESK_TEMPLATES) is the installed set.
The same template id from both places keeps the installed pack.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from agentdesk.registry.install import tree_digest
from agentdesk.registry.source import discover_repo_registry

USER_ENV = "AGENTDESK_TEMPLATES"


@dataclass(frozen=True)
class TemplatePack:
    """One template the picker can offer."""

    id: str
    name: str
    version: str
    digest: str
    root: Path
    variants: dict
    recipes: list
    thumbs: dict
    source: str  # "shipped" or "installed"

    def recipe(self, recipe_id: str) -> dict | None:
        """The recipe document whose id matches, or None."""
        for path in self.recipes:
            try:
                document = json.loads((self.root / path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if document.get("id") == recipe_id:
                return document
        return None

    def shell_path(self, variant: str) -> Path | None:
        """The shell file for one variant, or None when the pack has none."""
        rel = self.variants.get(variant)
        if not isinstance(rel, str):
            return None
        path = self.root / rel
        return path if path.is_file() else None

    def thumb_path(self, variant: str) -> Path | None:
        """The preview image for one variant."""
        rel = self.thumbs.get(variant)
        if not isinstance(rel, str):
            return None
        path = self.root / rel
        return path if path.is_file() else None


def user_templates_dir(environ: dict | None = None) -> Path:
    """Where a person installs their own packs. Never the git tree."""
    environ = os.environ if environ is None else environ
    override = str(environ.get(USER_ENV, "")).strip()
    if override:
        return Path(override)
    return Path.home() / ".agent-desk" / "templates"


def load_packs(registry_root: Path | None = None,
               user_dir: Path | None = None,
               environ: dict | None = None) -> list[TemplatePack]:
    """Shipped packs, then installed packs. An id collision keeps the install.

    `registry_root` defaults to this checkout's registry. A missing
    directory contributes nothing, which is the honest empty.
    """
    if registry_root is None:
        discovered = discover_repo_registry()
        registry_root = discovered
    if user_dir is None:
        user_dir = user_templates_dir(environ)
    found: dict[str, TemplatePack] = {}
    if registry_root is not None:
        plugins = Path(registry_root) / "plugins"
        for pack in _packs_under(plugins, "shipped"):
            found[pack.id] = pack
    for pack in _packs_under(user_dir, "installed"):
        found[pack.id] = pack
    return [found[key] for key in sorted(found)]


def _packs_under(root: Path | None, source: str) -> list[TemplatePack]:
    """Every presentation template in the child directories of `root`."""
    if root is None or not Path(root).is_dir():
        return []
    packs = []
    for child in sorted(Path(root).iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        contributes = manifest.get("contributes")
        templates = contributes.get("presentationTemplates") if isinstance(contributes, dict) else None
        if not isinstance(templates, list):
            continue
        try:
            digest = tree_digest(child)
        except OSError:
            digest = ""
        version = str(manifest.get("version") or "")
        for item in templates:
            pack = _one(child, item, version, digest, source)
            if pack is not None:
                packs.append(pack)
    return packs


def _one(root: Path, item, version: str, digest: str, source: str) -> TemplatePack | None:
    """One template entry, or None when the entry has no id."""
    if not isinstance(item, dict):
        return None
    template_id = str(item.get("id") or "").strip()
    if not template_id:
        return None
    variants = item.get("variants") if isinstance(item.get("variants"), dict) else {}
    recipes = item.get("recipes") if isinstance(item.get("recipes"), list) else []
    thumbs = item.get("thumbs") if isinstance(item.get("thumbs"), dict) else {}
    return TemplatePack(
        id=template_id,
        name=str(item.get("name") or template_id),
        version=version,
        digest=digest,
        root=root,
        variants={str(k): str(v) for k, v in variants.items()},
        recipes=[str(path) for path in recipes],
        thumbs={str(k): str(v) for k, v in thumbs.items()},
        source=source,
    )


def file_digest(path: Path) -> str:
    """sha256 of one file. Used when a run records the shell it opened."""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
