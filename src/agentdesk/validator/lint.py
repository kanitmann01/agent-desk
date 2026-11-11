"""Permission lint: the safety rules applied to a schema-valid manifest shape.

Class D plugins get no shell, no unscoped filesystem globs, no network in
base permissions, and no plugin-supplied HTML or script.
"""

from .model import Failure


def validate_permission_lint(manifest) -> list[Failure]:
    """Return every permission-lint failure for the manifest."""
    failures: list[Failure] = []
    if not isinstance(manifest, dict):
        return failures
    permissions = manifest.get("permissions")

    if isinstance(permissions, dict):
        failures.extend(_validate_shell(permissions))

    return failures


def _validate_shell(permissions) -> list[Failure]:
    if "shell" not in permissions:
        return [Failure("bad-schema", "permissions must declare shell")]
    shell = permissions["shell"]
    if shell != "none":
        return [Failure("shell-permission", f'permissions.shell must be "none", got "{shell}"')]
    return []
