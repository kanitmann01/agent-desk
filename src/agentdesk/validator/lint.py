"""Permission lint: the safety rules applied to a schema-valid manifest shape.

Class D plugins get no shell, no unscoped filesystem globs, no network in
base permissions, and no plugin-supplied HTML or script.
"""

from .model import Failure


WORKSPACE_ROOT = "${workspace}/"
PLUGIN_DATA_ROOT = "${pluginData}"


def validate_permission_lint(manifest) -> list[Failure]:
    """Return every permission-lint failure for the manifest."""
    failures: list[Failure] = []
    if not isinstance(manifest, dict):
        return failures
    permissions = manifest.get("permissions")

    if isinstance(permissions, dict):
        failures.extend(_validate_shell(permissions))
        failures.extend(_validate_filesystem_scoping(permissions))
        failures.extend(_validate_network_allow(permissions))

    return failures


def _validate_shell(permissions) -> list[Failure]:
    if "shell" not in permissions:
        return [Failure("bad-schema", "permissions must declare shell")]
    shell = permissions["shell"]
    if shell != "none":
        return [Failure("shell-permission", f'permissions.shell must be "none", got "{shell}"')]
    return []


def _validate_filesystem_scoping(permissions) -> list[Failure]:
    filesystem = permissions.get("filesystem")
    if not isinstance(filesystem, dict):
        return []
    failures: list[Failure] = []
    for kind in ("read", "write"):
        globs = filesystem.get(kind)
        if not isinstance(globs, list):
            continue
        for glob in globs:
            if not isinstance(glob, str):
                failures.append(
                    Failure("bad-schema", "permissions.filesystem globs must be strings")
                )
            elif not _is_scoped(glob):
                failures.append(
                    Failure(
                        "unscoped-filesystem",
                        f"filesystem glob not rooted under {WORKSPACE_ROOT} or {PLUGIN_DATA_ROOT}: {glob}",
                    )
                )
    return failures


def _is_scoped(glob: str) -> bool:
    return (
        glob.startswith(WORKSPACE_ROOT)
        or glob == PLUGIN_DATA_ROOT
        or glob.startswith(PLUGIN_DATA_ROOT + "/")
    )


def _validate_network_allow(permissions) -> list[Failure]:
    network = permissions.get("network")
    if not isinstance(network, dict):
        return []
    allow = network.get("allow")
    if isinstance(allow, list) and allow:
        return [
            Failure(
                "over-permission",
                "permissions.network.allow must be empty; "
                "network access belongs in optionalPermissions",
            )
        ]
    return []


def _validate_shell(permissions) -> list[Failure]:
    if "shell" not in permissions:
        return [Failure("bad-schema", "permissions must declare shell")]
    shell = permissions["shell"]
    if shell != "none":
        return [Failure("shell-permission", f'permissions.shell must be "none", got "{shell}"')]
    return []
