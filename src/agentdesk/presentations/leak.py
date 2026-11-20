"""Fail a build when a committed template pack carries a denylisted fingerprint.

The denylist is hashes only. A token is a lower-cased run of letters and
digits. A media fingerprint is the sha256 of a file's bytes. The committed
list starts empty; the owner appends hashes locally. An optional untracked
file of the same shape is read when it sits next to the committed list.

This module does not contain the denylisted words. Add a token with:

    python -c "import hashlib; print(hashlib.sha256(b'the-token').hexdigest())"
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9]+")
MEDIA_SUFFIXES = {".pptx", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".emf", ".wdp", ".bin"}


def load_hashes(*paths: Path) -> set[str]:
    """Hex hashes from comment-stripped lines. Missing files contribute nothing."""
    found: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            word = line.split("#", 1)[0].strip().lower()
            if word:
                found.add(word)
    return found


def scan(roots: list[Path], hashes: set[str]) -> list[str]:
    """Paths under `roots` whose tokens or bytes hit `hashes`.

    An empty hash set never fails: there is nothing to match. Text files
    contribute lower-cased tokens. Every file also contributes its byte
    hash, which is how a media fingerprint is caught.
    """
    if not hashes:
        return []
    hits = []
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in files:
            if _hit(path, hashes):
                hits.append(str(path))
    return sorted(hits)


def pack_roots(registry: Path) -> list[Path]:
    """Plugin directories that contribute a presentation template."""
    plugins = registry / "plugins"
    if not plugins.is_dir():
        return []
    roots = []
    for child in sorted(plugins.iterdir()):
        manifest = child / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            document = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        contributes = document.get("contributes")
        templates = contributes.get("presentationTemplates") if isinstance(contributes, dict) else None
        if isinstance(templates, list) and templates:
            roots.append(child)
    return roots


def _hit(path: Path, hashes: set[str]) -> bool:
    """Whether this file's bytes or its lower-cased tokens are denylisted."""
    try:
        blob = path.read_bytes()
    except OSError:
        return False
    if hashlib.sha256(blob).hexdigest() in hashes:
        return True
    if path.suffix.lower() in MEDIA_SUFFIXES:
        return False
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return False
    lowered = text.lower()
    return any(hashlib.sha256(token.encode("utf-8")).hexdigest() in hashes for token in TOKEN.findall(lowered))
