"""Plugin validation: manifest in, verdict out.

This module is the single validation entry point. The CLI, the app's
install path, and registry CI all run this same code.
"""

import json
from pathlib import Path

from .hashes import check_release_hashes
from .lint import validate_permission_lint
from .model import Failure, Verdict
from .reader import MANIFEST_NAME, DirectoryReader, ValidatorIOError
from .schema import validate_schema

_FAILURE_CODE_ORDER = (
    "unknown-key",
    "bad-schema",
    "bad-license",
    "shell-permission",
    "unscoped-filesystem",
    "plugin-html",
    "over-permission",
    "unknown-datasource",
    "missing-file",
    "bad-json",
    "hash-mismatch",
)


def _sorted_failures(failures) -> tuple[Failure, ...]:
    """Deterministic order: stable code order first, then message."""
    code_rank = {code: rank for rank, code in enumerate(_FAILURE_CODE_ORDER)}
    return tuple(
        sorted(
            failures,
            key=lambda failure: (
                code_rank.get(failure.code, len(_FAILURE_CODE_ORDER)),
                failure.message,
            ),
        )
    )


def validate_plugin(path) -> Verdict:
    """Validate the plugin directory or zip at ``path`` and return a Verdict.

    Raises ValidatorIOError when ``path`` cannot be read at all.
    """
    root = Path(path)
    if not root.exists():
        raise ValidatorIOError(f"path does not exist: {root.name}")
    if not root.is_dir():
        raise ValidatorIOError(f"path is neither a plugin directory nor a zip: {root.name}")

    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return Verdict((Failure("missing-file", f"missing {MANIFEST_NAME}"),))
    try:
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Verdict((Failure("bad-json", f"{MANIFEST_NAME} is not valid JSON: {exc}"),))

    reader = DirectoryReader(root)
    failures = validate_schema(manifest)
    failures.extend(validate_permission_lint(manifest, reader))
    failures.extend(check_release_hashes(reader))
    return Verdict(_sorted_failures(failures))
