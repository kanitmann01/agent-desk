"""Manifest schema: required top-level keys, their types, no unknown keys."""

import re

from .model import Failure

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

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

    failures.extend(_validate_values(manifest))

    return failures


def _validate_values(manifest) -> list[Failure]:
    """Value rules that only apply when the key holds its expected type."""
    failures: list[Failure] = []

    if manifest.get("schemaVersion") is not None and isinstance(
        manifest["schemaVersion"], int
    ):
        if manifest["schemaVersion"] != 1:
            failures.append(
                Failure(
                    "bad-schema",
                    f"schemaVersion must be 1, got {manifest['schemaVersion']}",
                )
            )

    if isinstance(manifest.get("class"), str) and manifest["class"] != "declarative":
        failures.append(
            Failure(
                "bad-schema",
                f'class must be "declarative", got "{manifest["class"]}"',
            )
        )

    if isinstance(manifest.get("version"), str) and not SEMVER_PATTERN.match(
        manifest["version"]
    ):
        failures.append(
            Failure(
                "bad-schema",
                f"version must be a semver string like 1.2.0, got '{manifest['version']}'",
            )
        )

    engines = manifest.get("engines")
    if isinstance(engines, dict):
        dashboard_host = engines.get("dashboardHost")
        if not isinstance(dashboard_host, str) or not dashboard_host:
            failures.append(
                Failure("bad-schema", "engines.dashboardHost must be a nonempty string")
            )

    return failures
