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
import io
import json
import re
import zipfile
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9]+")
# A deck is a zip. Its outer bytes are fingerprinted, and so is every
# part inside: XML is token-scanned, media is hashed as bytes.
PACKAGE_SUFFIXES = {".pptx"}
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".emf", ".wdp", ".bin", ".jpeg"}


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
    contribute lower-cased tokens. A .pptx is opened and each part is
    scanned the same way, so a token that lives only inside slide XML
    still matches. Every file also contributes its byte hash.
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
    if path.suffix.lower() in PACKAGE_SUFFIXES:
        return _package_hit(blob, hashes)
    if path.suffix.lower() in MEDIA_SUFFIXES:
        return False
    return _text_hit(blob, hashes)


def _package_hit(blob: bytes, hashes: set[str]) -> bool:
    """Whether any part of a .pptx hits the denylist.

    XML and other text parts are token-scanned. Media parts are matched
    by the hash of their bytes. A package that is not a zip is ignored
    beyond the outer hash already checked.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return False
    for name in archive.namelist():
        try:
            data = archive.read(name)
        except zipfile.BadZipFile:
            continue
        if hashlib.sha256(data).hexdigest() in hashes:
            return True
        suffix = Path(name).suffix.lower()
        if suffix in MEDIA_SUFFIXES or "/media/" in name.replace("\\", "/"):
            continue
        if _text_hit(data, hashes):
            return True
    return False


def _text_hit(blob: bytes, hashes: set[str]) -> bool:
    """Whether any lower-cased token in this text is denylisted."""
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return any(
        hashlib.sha256(token.encode("utf-8")).hexdigest() in hashes
        for token in TOKEN.findall(text.lower())
    )
