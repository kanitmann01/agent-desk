"""Manifest schema: required top-level keys, their types, no unknown keys."""

from .model import Failure

REQUIRED_KEY_TYPES = {
    "schemaVersion": int,
    "id": str,
    "name": str,
    "version": str,
    "publisher": str,
    "class": str,
    "engines": dict,
    "license": str,
    "permissions": dict,
    "activationEvents": list,
    "contributes": dict,
}

OPTIONAL_KEY_TYPES = {
    "optionalPermissions": dict,
}

_TYPE_NAMES = {str: "string", int: "integer", dict: "object", list: "array"}


def validate_schema(manifest) -> list[Failure]:
    """Check top-level keys and types; return every schema failure found."""
    if not isinstance(manifest, dict):
        return [Failure("bad-schema", "manifest must be a JSON object")]

    failures: list[Failure] = []

    known_keys = set(REQUIRED_KEY_TYPES) | set(OPTIONAL_KEY_TYPES)
    for key in sorted(set(manifest) - known_keys):
        failures.append(Failure("unknown-key", f"unknown top-level key: {key}"))

    for key, expected_type in REQUIRED_KEY_TYPES.items():
        if key not in manifest:
            failures.append(Failure("bad-schema", f"missing required key: {key}"))
        elif not isinstance(manifest[key], expected_type):
            failures.append(
                Failure(
                    "bad-schema",
                    f"key '{key}' must be a {_TYPE_NAMES[expected_type]}",
                )
            )
    for key, expected_type in OPTIONAL_KEY_TYPES.items():
        if key in manifest and not isinstance(manifest[key], expected_type):
            failures.append(
                Failure(
                    "bad-schema",
                    f"key '{key}' must be a {_TYPE_NAMES[expected_type]}",
                )
            )

    return failures
