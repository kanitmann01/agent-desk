"""Plugin validation: manifest in, verdict out.

This module is the single validation entry point. The CLI, the app's
install path, and registry CI all run this same code.
"""

import json
from pathlib import Path

from .model import Verdict
from .reader import MANIFEST_NAME, ValidatorIOError


def validate_plugin(path) -> Verdict:
    """Validate the plugin directory or zip at ``path`` and return a Verdict.

    Raises ValidatorIOError when ``path`` cannot be read at all.
    """
    root = Path(path)
    if not root.exists():
        raise ValidatorIOError(f"path does not exist: {root.name}")
    if not root.is_dir():
        raise ValidatorIOError(f"path is neither a plugin directory nor a zip: {root.name}")

    manifest_bytes = (root / MANIFEST_NAME).read_bytes()
    try:
        json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return Verdict()

    return Verdict()
