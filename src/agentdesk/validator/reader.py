"""Locate and read the manifest for a plugin directory or zip."""

MANIFEST_NAME = "manifest.json"


class ValidatorIOError(Exception):
    """The input path cannot be read at all (usage/IO error, CLI exit 2)."""
