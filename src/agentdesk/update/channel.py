"""The update channel: version folders on the share IT publishes.

One definition decides which folder is newer, so the check, the settings
line and the desk check cannot disagree. Every unreadable answer is a named
cause, never a traceback on a page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "manifest.json"
BUNDLE_NAME = "agent-desk.zip"
SCHEMA_VERSION = 1


class ChannelUnreadable(Exception):
    """The share cannot be read, with a plain cause for the settings line."""


@dataclass(frozen=True)
class Available:
    """One newer version folder on the share."""

    version: str
    folder: Path
    manifest: dict


def parse_version(value: str) -> tuple[int, ...]:
    """Turn a dotted version into numbers that sort correctly.

    Version 0.10.0 is newer than 0.9.9; a non-numeric part is refused
    rather than guessed, so a malformed folder cannot win a comparison.
    """
    parts = str(value).strip().split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"{value!r} is not a version number.")
    return tuple(int(part) for part in parts)


def _manifest(folder: Path) -> dict:
    """Read one version folder's manifest, with a plain cause on failure."""
    path = folder / MANIFEST_NAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChannelUnreadable(f"the manifest in {folder.name} could not be read.") from exc
    if not isinstance(document, dict):
        raise ChannelUnreadable(f"the manifest in {folder.name} is not an object.")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ChannelUnreadable(
            f"the manifest in {folder.name} is not version {SCHEMA_VERSION}."
        )
    version = document.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ChannelUnreadable(f"the manifest in {folder.name} has no version.")
    return document


def newest(channel: Path, current: str) -> Available | None:
    """The highest published version newer than the running one, or None.

    A folder without a manifest is ignored: half-written scratch folders
    are normal on a share. A manifest that exists but cannot be understood
    stops the check with ChannelUnreadable so the desk reports it rather
    than silently staying behind.
    """
    root = Path(channel)
    if not root.is_dir():
        raise ChannelUnreadable("the folder does not exist.")
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        raise ChannelUnreadable("the folder could not be listed.") from exc
    current_parts = parse_version(current)
    winner: Available | None = None
    for folder in children:
        if not folder.is_dir() or not (folder / MANIFEST_NAME).exists():
            continue
        try:
            parts = parse_version(folder.name)
        except ValueError:
            continue
        document = _manifest(folder)
        if document["version"] != folder.name:
            raise ChannelUnreadable(
                f"the folder {folder.name} says it is version {document['version']}."
            )
        if parts <= current_parts:
            continue
        if winner is None or parts > parse_version(winner.version):
            winner = Available(version=folder.name, folder=folder, manifest=document)
    return winner
