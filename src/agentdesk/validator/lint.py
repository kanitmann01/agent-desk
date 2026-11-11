"""Permission lint: the safety rules applied to a schema-valid manifest shape.

Class D plugins get no shell, no unscoped filesystem globs, no network in
base permissions, and no plugin-supplied HTML or script.
"""

import json

from .model import Failure


WORKSPACE_ROOT = "${workspace}/"
PLUGIN_DATA_ROOT = "${pluginData}"


def validate_permission_lint(manifest, reader) -> list[Failure]:
    """Return every permission-lint failure for the manifest."""
    failures: list[Failure] = []
    if not isinstance(manifest, dict):
        return failures
    permissions = manifest.get("permissions")

    if isinstance(permissions, dict):
        failures.extend(_validate_shell(permissions))
        failures.extend(_validate_filesystem_scoping(permissions))
        failures.extend(_validate_network_allow(permissions))

    failures.extend(_validate_render(manifest, reader))

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


def _validate_render(manifest, reader) -> list[Failure]:
    """Reject plugin-supplied HTML and check each widget's ui-schema file.

    The schema only accepts "type": "ui-schema" pointing at a .json file
    that parses as a JSON object with at least "type": "card".
    """
    failures: list[Failure] = []
    contributes = manifest.get("contributes")
    if not isinstance(contributes, dict):
        return failures
    widgets = contributes.get("widgets")
    if not isinstance(widgets, list):
        return failures

    for widget in widgets:
        if not isinstance(widget, dict):
            failures.append(Failure("bad-schema", "each widget must be an object"))
            continue
        render = widget.get("render")
        if not isinstance(render, dict):
            failures.append(Failure("bad-schema", "widget render must be an object"))
            continue
        failures.extend(_validate_render_entry(render, reader))
    return failures


def _validate_render_entry(render, reader) -> list[Failure]:
    failures: list[Failure] = []

    for banned_key in ("template", "html"):
        if banned_key in render:
            failures.append(
                Failure("plugin-html", f"render must not contain plugin-supplied keys: {banned_key}")
            )

    render_type = render.get("type")
    if render_type != "ui-schema":
        failures.append(
            Failure("plugin-html", f'render.type must be "ui-schema", got "{render_type}"')
        )
        return failures

    render_file = render.get("file")
    if not isinstance(render_file, str):
        failures.append(
            Failure("plugin-html", "render.file must be a string ending with .json")
        )
        return failures
    if not render_file.endswith(".json"):
        failures.append(
            Failure("plugin-html", f'render.file must end with .json, got "{render_file}"')
        )
        return failures

    content = reader.read_bytes(render_file)
    if content is None:
        failures.append(Failure("missing-file", f"ui-schema file not found: {render_file}"))
        return failures
    try:
        ui_schema = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        failures.append(
            Failure("bad-json", f"ui-schema file {render_file} is not valid JSON: {exc}")
        )
        return failures
    if not isinstance(ui_schema, dict) or ui_schema.get("type") != "card":
        failures.append(
            Failure(
                "bad-json",
                f'ui-schema file {render_file} must be a JSON object with "type": "card"',
            )
        )
    return failures


def _validate_shell(permissions) -> list[Failure]:
    if "shell" not in permissions:
        return [Failure("bad-schema", "permissions must declare shell")]
    shell = permissions["shell"]
    if shell != "none":
        return [Failure("shell-permission", f'permissions.shell must be "none", got "{shell}"')]
    return []
