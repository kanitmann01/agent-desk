"""Permission lint: the safety rules applied to a schema-valid manifest shape.

Class D plugins get no shell, no unscoped filesystem globs, no network in
base permissions, and no plugin-supplied HTML or script.
"""

import json
import re
from fnmatch import fnmatch

from nexuusbot.plugins.vocabulary import (
    ELEMENT_KINDS as KNOWN_ELEMENT_KINDS,
    ROW_CAPS,
    SAMPLE_MAX_BYTES,
    SPARKLINE_MAX_POINTS,
    SPARKLINE_MIN_POINTS,
)

from .grammar import (
    JSON_LIST as _JSON_LIST,
    JSON_OBJECT as _JSON_OBJECT,
    PLUGIN_DATA_ROOT,
    SAFE_NAME as _SAFE_ID,
    WORKSPACE_ROOT,
)
from .model import Failure

# The declarative vocabulary of data source types. The pipeline-backed
# kinds (calendar-read, mail-digest, research-brief) read the shared
# built-in pipelines, so their manifests declare no glob of their own.
KNOWN_DATA_SOURCE_TYPES = (
    "excel-watch",
    "json-watch",
    "http-get",
    "calendar-read",
    "mail-digest",
    "outlook-brief",
    "research-brief",
    "csv-watch",
    "markdown-watch",
    "manual-metric",
    "desk-state",
    "compare",
    "aggregate",
)

# The source types whose reader opens the path named by dataSource.file.
# Other types either take no file (pipeline and desk sources, aggregate),
# or are composed from nested sources (compare), or accept a file only as
# a display hint while a host-owned default (manual-metric) is read.
FILE_READING_SOURCE_TYPES = (
    "excel-watch",
    "csv-watch",
    "json-watch",
    "markdown-watch",
)

# Absolute paths are platform-dependent, so the drive/root prefix is
# matched directly rather than through Path.is_absolute().
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")

# Known kinds and the element-specific caps from the plugin marketplace
# design all come from nexuusbot.plugins.vocabulary; the names above are the
# same objects the renderer and the generated SPA module use, so a cap can
# never be enforced differently on the two surfaces.


def validate_permission_lint(manifest, reader) -> list[Failure]:
    """Return every permission-lint failure for the manifest."""
    failures: list[Failure] = []
    if not isinstance(manifest, dict):
        return failures
    plugin_id = str(manifest.get("id", ""))
    if not _SAFE_ID.match(plugin_id) or ".." in plugin_id:
        failures.append(Failure(
            "unsafe-id",
            "the manifest id must be a safe name (letters, digits, dots, "
            "dashes, underscores; no separators or dot-segments)"))
    permissions = manifest.get("permissions")

    if isinstance(permissions, dict):
        failures.extend(_validate_shell(permissions))
        failures.extend(_validate_filesystem_scoping(permissions))
        failures.extend(_validate_network_allow(permissions))

    contributes = manifest.get("contributes")
    if isinstance(contributes, dict) and isinstance(contributes.get("widgets"), list):
        for widget in contributes["widgets"]:
            if isinstance(widget, dict):
                failures.extend(_validate_data_source_type(widget))

    failures.extend(_validate_config(manifest, permissions if isinstance(permissions, dict) else {}))
    failures.extend(_validate_network_filesystem(manifest))
    failures.extend(_validate_over_permission(manifest))
    failures.extend(_validate_data_source_permissions(manifest))
    render_failures, ui_schemas = _validate_render(manifest, reader)
    failures.extend(render_failures)
    failures.extend(_validate_sample(manifest, reader, ui_schemas))
    failures.extend(_validate_presentation_templates(manifest, reader))

    return failures


def _validate_over_permission(manifest) -> list[Failure]:
    """Every declared filesystem read glob must be used by a data source.

    Each widget's dataSource "file" field names the glob that data source
    needs; a read glob no data source references is an over-permission.
    Write globs are exempt: they target the plugin's own data directory.
    """
    permissions = manifest.get("permissions")
    if not isinstance(permissions, dict):
        return []
    filesystem = permissions.get("filesystem")
    read_globs = filesystem.get("read") if isinstance(filesystem, dict) else None
    if not isinstance(read_globs, list):
        return []

    referenced: set[str] = set()
    contributes = manifest.get("contributes")
    widgets = contributes.get("widgets") if isinstance(contributes, dict) else None
    if isinstance(widgets, list):
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            data_source = widget.get("dataSource")
            if not isinstance(data_source, dict):
                continue
            referenced.update(_data_source_files(data_source))

    return [
        Failure(
            "over-permission",
            f"filesystem read glob is not referenced by any data source: {glob}",
        )
        for glob in read_globs
        if isinstance(glob, str) and glob not in referenced
    ]


def _validate_data_source_permissions(manifest) -> list[Failure]:
    """Every file a data source reads must sit under a declared read scope.

    The read scopes are the manifest's own permissions.filesystem.read
    globs, plus the plugin's own data directory (execution already
    permits it; a plugin may read what it wrote). Only the source types
    whose reader actually opens dataSource.file are checked, so a type
    that ignores the field is not forced to declare it. Without this
    check a data source could name any path, including an absolute one,
    and the manifest would validate with no read permission. An absolute
    path can only be covered by an absolute glob, and
    _validate_filesystem_scoping already refuses those, so an absolute
    dataSource.file always fails here.
    """
    permissions = manifest.get("permissions")
    filesystem = (permissions.get("filesystem")
                  if isinstance(permissions, dict) else None)
    read_globs = filesystem.get("read") if isinstance(filesystem, dict) else None
    declared = (tuple(glob for glob in read_globs if isinstance(glob, str))
                if isinstance(read_globs, list) else ())

    failures: list[Failure] = []
    contributes = manifest.get("contributes")
    widgets = contributes.get("widgets") if isinstance(contributes, dict) else None
    if not isinstance(widgets, list):
        return failures
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        data_source = widget.get("dataSource")
        if not isinstance(data_source, dict):
            continue
        for file_glob in sorted(_opened_files(data_source)):
            if _is_plugin_data(file_glob):
                continue
            if _covered_by_read_glob(file_glob, declared):
                continue
            failures.append(Failure(
                "over-permission",
                f"data source {widget.get('id')} reads {file_glob}, which no "
                f"declared permissions.filesystem.read glob covers"))
    return failures


def _opens_declared_file(data_source) -> bool:
    """Whether dataSource.file is a path the host will actually open.

    manual-metric honours an explicit file but falls back to its own
    data directory, so only an absolute explicit file is a read worth
    checking; its relative fixture value is a display hint.
    """
    source_type = data_source.get("type")
    if source_type in FILE_READING_SOURCE_TYPES:
        return True
    file_glob = data_source.get("file")
    return (source_type == "manual-metric"
            and isinstance(file_glob, str)
            and bool(_ABSOLUTE_PATH.match(file_glob)))


def _opened_files(data_source) -> set:
    """The file paths a data source, fallback, or compare side opens."""
    files: set = set()
    if _opens_declared_file(data_source):
        file_glob = data_source.get("file")
        if isinstance(file_glob, str):
            files.add(file_glob)
    fallback = data_source.get("fallback")
    if isinstance(fallback, dict):
        files.update(_opened_files(fallback))
    for side in ("left", "right"):
        nested = data_source.get(side)
        if isinstance(nested, dict):
            files.update(_opened_files(nested))
    return files


def _is_plugin_data(file_glob: str) -> bool:
    """Whether the glob names the plugin's own data directory.

    The bare root and anything below it qualify; a sibling path that merely
    shares the prefix does not.
    """
    return (file_glob == PLUGIN_DATA_ROOT
            or file_glob.startswith(PLUGIN_DATA_ROOT + "/"))


def _covered_by_read_glob(file_glob: str, read_globs) -> bool:
    """Whether a declared read glob admits the path, exactly or by pattern.

    Exact equality is checked as well because fnmatch would read a bracket in
    a literal path as a character class.
    """
    return any(file_glob == glob or fnmatch(file_glob, glob) for glob in read_globs)


def _validate_data_source_type(widget) -> list[Failure]:
    """Check one widget's dataSource against the rules of its declared type.

    The type selects which checks run, so an unknown type fails once instead
    of drawing a complaint from every per-type rule. The widget is inspected
    rather than a source alone: a missing or non-object dataSource is itself
    the failure.
    """
    data_source = widget.get("dataSource")
    if not isinstance(data_source, dict):
        return [Failure("bad-schema", "widget dataSource must be an object")]
    source_type = data_source.get("type")
    if source_type not in KNOWN_DATA_SOURCE_TYPES:
        return [Failure("unknown-datasource", f"unknown dataSource.type: {source_type}")]

    failures: list[Failure] = []
    if source_type == "json-watch":
        selector = data_source.get("selector")
        if not _valid_json_selector(selector):
            failures.append(Failure(
                "bad-schema",
                f"json-watch selector must be $.a.b or $.a[*].n, got {selector!r}"))
    if "fallback" in data_source:
        failures.extend(_validate_fallback(data_source, source_type))
    if source_type == "compare":
        failures.extend(_validate_compare(data_source))
    if source_type == "aggregate":
        # The documented form aggregates over the plugin's own requires[],
        # which lint cannot resolve; an explicit over list must be valid.
        over = data_source.get("over")
        if over is not None and (
                not isinstance(over, list) or not over
                or not all(isinstance(item, str) for item in over)):
            failures.append(Failure(
                "bad-schema",
                "aggregate dataSource.over must be a non-empty list of plugin ids"))
    if source_type == "http-get":
        failures.extend(_validate_http_get(data_source))
    return failures


def _valid_json_selector(selector) -> bool:
    """Whether the selector is one of the two json-watch shapes.

    A non-string never parses; the grammar is an object path, or one list
    field with a scalar beneath it.
    """
    return isinstance(selector, str) and bool(
        _JSON_OBJECT.match(selector) or _JSON_LIST.match(selector))


def _validate_fallback(data_source, source_type) -> list[Failure]:
    """Check the excel-watch fallback is a csv-watch source with named columns.

    A fallback on any other type is an error rather than an ignored extra, so
    the rule is enforced where the nested block is accepted.
    """
    if source_type != "excel-watch":
        return [Failure(
            "bad-schema", "only excel-watch may declare a fallback dataSource")]
    fallback = data_source.get("fallback")
    if not isinstance(fallback, dict):
        return [Failure("bad-schema", "excel-watch fallback must be an object")]
    failures: list[Failure] = []
    if fallback.get("type") != "csv-watch":
        failures.append(Failure(
            "bad-schema", 'excel-watch fallback.type must be "csv-watch"'))
    if not isinstance(fallback.get("file"), str) or not fallback.get("file"):
        failures.append(Failure(
            "bad-schema", "excel-watch fallback.file must be a scoped glob"))
    for key in ("keyColumn", "valueColumn"):
        if not isinstance(fallback.get(key), str) or not fallback.get(key):
            failures.append(Failure(
                "bad-schema",
                f"excel-watch fallback.{key} must name a CSV column"))
    return failures


def _validate_compare(data_source) -> list[Failure]:
    """Check that both compare sides are local sources of a known type.

    http-get is a known type but is still refused here: compare reads beside
    the plugin, never over the network.
    """
    failures: list[Failure] = []
    for side in ("left", "right"):
        nested = data_source.get(side)
        if not isinstance(nested, dict):
            failures.append(Failure(
                "bad-schema", f"compare dataSource.{side} must be a source object"))
            continue
        if str(nested.get("type", "")) not in KNOWN_DATA_SOURCE_TYPES:
            failures.append(Failure(
                "bad-schema", f"compare dataSource.{side} has an unknown type"))
        elif nested.get("type") == "http-get":
            failures.append(Failure(
                "bad-schema",
                "compare may only read local sources, not http-get"))
    return failures


def _validate_http_get(data_source) -> list[Failure]:
    """Check an http-get source's URL, host allowlist and timeout.

    The allowlist must name at least one host, so a fetch can never be
    unconstrained. The timeout is optional; when present it must be greater
    than zero and at most 15 seconds.
    """
    failures: list[Failure] = []
    url = data_source.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        failures.append(Failure(
            "bad-schema", "http-get url must be an absolute http(s) URL"))
    allow = data_source.get("allow")
    if not isinstance(allow, list) or not allow or not all(
            isinstance(item, str) and item for item in allow):
        failures.append(Failure(
            "bad-schema", "http-get allow must be a non-empty host allowlist"))
    timeout = data_source.get("timeoutSeconds")
    if timeout is not None:
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                or timeout <= 0 or timeout > 15):
            failures.append(Failure(
                "bad-schema",
                "http-get timeoutSeconds must be a number between 0 and 15"))
    return failures


def _validate_network_filesystem(manifest) -> list[Failure]:
    """http-get and filesystem reads are mutually exclusive.

    A read is either a declared read glob or a manual-metric source
    naming a file outside the plugin's own data directory: the file-
    reading widgets get no network rule must hold structurally, not only
    against declared globs. A plugin-data-rooted manual-metric file stays
    allowed: it names the plugin's own data directory.
    """
    contributes = manifest.get("contributes")
    widgets = contributes.get("widgets") if isinstance(contributes, dict) else None
    if not isinstance(widgets, list):
        return []
    data_sources = [
        widget.get("dataSource") for widget in widgets
        if isinstance(widget, dict) and isinstance(widget.get("dataSource"), dict)
    ]
    has_http = any(source.get("type") == "http-get" for source in data_sources)
    if not has_http:
        return []
    permissions = manifest.get("permissions")
    filesystem = permissions.get("filesystem") if isinstance(permissions, dict) else None
    read_globs = filesystem.get("read") if isinstance(filesystem, dict) else None
    reads_declared = isinstance(read_globs, list) and bool(read_globs)
    stray_manual_metric = any(
        source.get("type") == "manual-metric"
        and isinstance(source.get("file"), str)
        and not _is_plugin_data(source["file"])
        for source in data_sources)
    if reads_declared or stray_manual_metric:
        return [Failure(
            "unsafe-network-filesystem",
            "http-get cannot be combined with filesystem read access; "
            "declare network or local files, not both")]
    return []


def _data_source_files(data_source) -> set:
    """Every file glob a data source (or a nested fallback/compare side) reads."""
    files: set = set()
    file_glob = data_source.get("file")
    if isinstance(file_glob, str):
        files.add(file_glob)
    fallback = data_source.get("fallback")
    if isinstance(fallback, dict):
        files.update(_data_source_files(fallback))
    for side in ("left", "right"):
        nested = data_source.get(side)
        if isinstance(nested, dict):
            files.update(_data_source_files(nested))
    return files


_CONFIG_KINDS = (
    "workbook", "markdown", "calendar", "mailbox",
    "research", "page", "desk", "compose",
)


def _validate_config(manifest, permissions) -> list[Failure]:
    """Check the config block a plugin declares and what it rules out.

    config.kinds must come from the host vocabulary and config.aliasOf must
    be a plugin id. A config-backed plugin is configured rather than read, so
    it may not also name a dataSource file, and permissions.llm.allow must be
    false because a suggestion is a host call.
    """
    config = manifest.get("config")
    if config is None:
        return []
    if not isinstance(config, dict):
        return [Failure("bad-schema", "config must be an object")]
    kinds = config.get("kinds")
    if not isinstance(kinds, list) or not kinds or not all(
            isinstance(item, str) and item in _CONFIG_KINDS for item in kinds):
        return [Failure(
            "bad-schema",
            "config.kinds must list workbook, markdown, calendar, mailbox, "
            "research, page, desk, or compose",
        )]
    failures: list[Failure] = []
    llm = permissions.get("llm") if isinstance(permissions, dict) else None
    if not isinstance(llm, dict) or llm.get("allow") is not False:
        failures.append(Failure(
            "over-permission",
            "permissions.llm.allow must be false; a suggestion is a host call",
        ))
    alias = config.get("aliasOf")
    if alias is not None and (not isinstance(alias, str) or not _SAFE_ID.match(alias)):
        failures.append(Failure("bad-schema", "config.aliasOf must be a plugin id"))
    contributes = manifest.get("contributes")
    widgets = contributes.get("widgets") if isinstance(contributes, dict) else None
    if isinstance(widgets, list):
        for widget in widgets:
            source = widget.get("dataSource") if isinstance(widget, dict) else None
            if isinstance(source, dict) and source.get("file"):
                failures.append(Failure(
                    "over-permission",
                    "a config-backed plugin must not also declare a dataSource file",
                ))
    return failures


def _validate_shell(permissions) -> list[Failure]:
    """Require the shell permission to be declared and set to none.

    The key is mandatory: a manifest that omits it fails rather than taking
    none as a default.
    """
    if "shell" not in permissions:
        return [Failure("bad-schema", "permissions must declare shell")]
    shell = permissions["shell"]
    if shell != "none":
        return [Failure("shell-permission", f'permissions.shell must be "none", got "{shell}"')]
    return []


def _validate_filesystem_scoping(permissions) -> list[Failure]:
    """Check every filesystem read and write glob is rooted where it may be.

    Globs must be strings and each must sit under the workspace root or the
    plugin data directory, so an absolute path is refused here too.
    """
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
    """Whether the glob is rooted at the workspace or the plugin data directory.

    The bare plugin data root counts as scoped, as does anything beneath
    either root; an absolute path outside them does not.
    """
    return (
        glob.startswith(WORKSPACE_ROOT)
        or glob == PLUGIN_DATA_ROOT
        or glob.startswith(PLUGIN_DATA_ROOT + "/")
    )


def _validate_network_allow(permissions) -> list[Failure]:
    """Require the base network allowlist to stay empty.

    Network access belongs in optionalPermissions, so a non-empty list here
    is an over-permission even when the hosts themselves are legitimate.
    """
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


def _validate_render(manifest, reader) -> tuple[list[Failure], list[dict]]:
    """Reject plugin-supplied HTML and check each widget's ui-schema file.

    The schema only accepts "type": "ui-schema" pointing at a .json file
    that parses as a JSON object. Returns the parsed ui-schema documents so
    the sample fixture can be checked against the same elements.
    """
    failures: list[Failure] = []
    ui_schemas: list[dict] = []
    contributes = manifest.get("contributes")
    if not isinstance(contributes, dict):
        return failures, ui_schemas
    widgets = contributes.get("widgets")
    if not isinstance(widgets, list):
        return failures, ui_schemas

    for widget in widgets:
        if not isinstance(widget, dict):
            failures.append(Failure("bad-schema", "each widget must be an object"))
            continue
        render = widget.get("render")
        if not isinstance(render, dict):
            failures.append(Failure("bad-schema", "widget render must be an object"))
            continue
        entry_failures, ui_schema = _validate_render_entry(
            render, reader, widget.get("dataSource"))
        failures.extend(entry_failures)
        if ui_schema is not None:
            ui_schemas.append(ui_schema)
    return failures, ui_schemas


def _validate_render_entry(render, reader,
                           source=None) -> tuple[list[Failure], dict | None]:
    """Check one widget's render entry and load the ui-schema it names.

    Plugin-supplied HTML or a template is refused before any file is read.
    The parsed document comes back beside the failures so the sample can be
    checked against the same elements; a document that never parsed is None.
    """
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
        return failures, None

    render_file = render.get("file")
    if not isinstance(render_file, str):
        failures.append(
            Failure("plugin-html", "render.file must be a string ending with .json")
        )
        return failures, None
    if not render_file.endswith(".json"):
        failures.append(
            Failure("plugin-html", f'render.file must end with .json, got "{render_file}"')
        )
        return failures, None

    content = reader.read_bytes(render_file)
    if content is None:
        failures.append(Failure("missing-file", f"ui-schema file not found: {render_file}"))
        return failures, None
    try:
        # utf-8-sig strips a leading BOM so Windows-authored files parse.
        ui_schema = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        failures.append(
            Failure("bad-json", f"ui-schema file {render_file} is not valid JSON: {exc}")
        )
        return failures, None
    if not isinstance(ui_schema, dict):
        failures.append(
            Failure("bad-json", f"ui-schema file {render_file} must be a JSON object")
        )
        return failures, None

    failures.extend(_validate_ui_schema(ui_schema, render_file, source))
    return failures, ui_schema


def _validate_ui_schema(ui_schema, render_file: str,
                        source=None) -> list[Failure]:
    """Every element must use a known kind and respect its row/point cap."""
    failures: list[Failure] = []
    elements = ui_schema.get("elements")
    if elements is None:
        return failures
    if not isinstance(elements, list):
        return [
            Failure(
                "bad-schema",
                f"ui-schema file {render_file} elements must be an array",
            )
        ]

    for element in elements:
        if not isinstance(element, dict):
            failures.append(
                Failure(
                    "bad-schema",
                    f"each ui-schema element in {render_file} must be an object",
                )
            )
            continue
        kind = element.get("type")
        if not isinstance(kind, str) or kind not in KNOWN_ELEMENT_KINDS:
            failures.append(Failure("unknown-element", f"unknown element kind: {kind}"))
            continue
        failures.extend(_validate_element_caps(kind, element))
        failures.extend(_validate_element_source(kind, element, render_file))
    return failures


def _validate_element_source(kind: str, element, render_file: str) -> list[Failure]:
    """An element must declare the data its kind needs to render."""
    if kind == "table" and not isinstance(element.get("columns"), list):
        return [Failure(
            "bad-schema",
            f"table element in {render_file} requires a columns list")]
    if kind == "sparkline" and not isinstance(
            element.get("pointsBinding"), str):
        return [Failure(
            "bad-schema",
            f"sparkline element in {render_file} requires a pointsBinding")]
    if kind == "progress":
        target = element.get("target")
        numeric = (isinstance(target, (int, float))
                   and not isinstance(target, bool))
        if not numeric and not isinstance(element.get("targetBinding"), str):
            return [Failure(
                "bad-schema",
                f"progress element in {render_file} requires target or "
                "targetBinding")]
    return []


def _validate_element_caps(kind: str, element) -> list[Failure]:
    """Check the row or point count an element declares against its cap.

    Only list and table carry row caps and only sparkline carries a point
    range, so other kinds are never counted. A missing or non-list count
    passes here.
    """
    failures: list[Failure] = []
    if kind in ROW_CAPS:
        rows = element.get("rows")
        if isinstance(rows, list):
            failure = _cap_failure(kind, len(rows))
            if failure is not None:
                failures.append(failure)
    elif kind == "sparkline":
        points = element.get("points")
        if isinstance(points, list):
            failure = _cap_failure(kind, len(points))
            if failure is not None:
                failures.append(failure)
    return failures


def _cap_failure(kind: str, count: int) -> Failure | None:
    """Return the failure a count earns against its kind's cap, or None.

    List and table are capped above only; a sparkline has a floor as well as
    a ceiling. A kind with no cap never fails.
    """
    if kind in ROW_CAPS:
        cap = ROW_CAPS[kind]
        if count > cap:
            return Failure(
                "bad-schema",
                f"{kind} element allows at most {cap} rows, got {count}",
            )
        return None
    if kind == "sparkline":
        if not SPARKLINE_MIN_POINTS <= count <= SPARKLINE_MAX_POINTS:
            return Failure(
                "bad-schema",
                f"sparkline element must have {SPARKLINE_MIN_POINTS} to "
                f"{SPARKLINE_MAX_POINTS} points, got {count}",
            )
    return None


def _is_v2(manifest) -> bool:
    """Whether the manifest is a version 2 document.

    schemaVersion must be the integer 2. bool is an int in Python, so True is
    excluded rather than read as 2.
    """
    version = manifest.get("schemaVersion")
    return isinstance(version, int) and not isinstance(version, bool) and version == 2


def _validate_presentation_templates(manifest, reader) -> list[Failure]:
    """A presentationTemplates contribution names shells, recipes and thumbs.

    Absent means the plugin is not a template pack. Present means each
    entry is an object and every path it names is a file in the pack.
    """
    contributes = manifest.get("contributes")
    if not isinstance(contributes, dict):
        return []
    templates = contributes.get("presentationTemplates")
    if templates is None:
        return []
    if not isinstance(templates, list) or not templates:
        return [Failure("bad-schema", "contributes.presentationTemplates must be a non-empty list")]
    failures: list[Failure] = []
    for item in templates:
        if not isinstance(item, dict):
            failures.append(Failure("bad-schema", "each presentation template must be an object"))
            continue
        for key in ("id", "name", "variants", "recipes"):
            if key not in item:
                failures.append(Failure(
                    "bad-schema", f"presentation template missing {key}"))
        variants = item.get("variants")
        if isinstance(variants, dict):
            for label, path in variants.items():
                if not isinstance(path, str) or reader.read_bytes(path) is None:
                    failures.append(Failure(
                        "missing-file", f"template variant {label} file not found: {path}"))
        elif "variants" in item:
            failures.append(Failure("bad-schema", "presentation template variants must be an object"))
        recipes = item.get("recipes")
        if isinstance(recipes, list):
            for path in recipes:
                if not isinstance(path, str) or reader.read_bytes(path) is None:
                    failures.append(Failure("missing-file", f"template recipe not found: {path}"))
        thumbs = item.get("thumbs")
        if isinstance(thumbs, dict):
            for label, path in thumbs.items():
                if not isinstance(path, str) or reader.read_bytes(path) is None:
                    failures.append(Failure(
                        "missing-file", f"template thumb {label} file not found: {path}"))
        guidance = item.get("guidance")
        if isinstance(guidance, str) and reader.read_bytes(guidance) is None:
            failures.append(Failure("missing-file", f"template guidance not found: {guidance}"))
    return failures


def _validate_sample(manifest, reader, ui_schemas) -> list[Failure]:
    """For v2 only: the sample fixture must exist, parse, and stay small."""
    if not _is_v2(manifest):
        return []
    sample = manifest.get("sample")
    if not isinstance(sample, str):
        return []

    content = reader.read_bytes(sample)
    if content is None:
        return [Failure("missing-file", f"sample file not found: {sample}")]
    if len(content) > SAMPLE_MAX_BYTES:
        return [
            Failure(
                "bad-sample",
                f"sample file {sample} exceeds the {SAMPLE_MAX_BYTES} byte cap",
            )
        ]
    try:
        # utf-8-sig strips a leading BOM so Windows-authored files parse.
        document = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [
            Failure(
                "bad-json",
                f"sample file {sample} is not valid JSON: {exc}",
            )
        ]
    if not isinstance(document, dict):
        return [
            Failure("bad-json", f"sample file {sample} must be a JSON object")
        ]
    bindings = document.get("bindings")
    if not isinstance(bindings, dict):
        return [
            Failure(
                "bad-schema",
                f"sample file {sample} must contain a bindings object",
            )
        ]

    return _validate_sample_caps(ui_schemas, bindings)


def _validate_sample_caps(ui_schemas, bindings) -> list[Failure]:
    """Caps also apply to the data each binding supplies in the sample."""
    failures: list[Failure] = []
    seen: set[tuple[str, str]] = set()
    for ui_schema in ui_schemas:
        elements = ui_schema.get("elements")
        if not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, dict):
                continue
            kind = element.get("type")
            if not isinstance(kind, str) or kind not in KNOWN_ELEMENT_KINDS:
                continue
            failure = _binding_cap_failure(element, bindings)
            if failure is None:
                continue
            key = (failure.code, failure.message)
            if key not in seen:
                seen.add(key)
                failures.append(failure)
    return failures


def _binding_cap_failure(element, bindings) -> Failure | None:
    """Return a cap failure when a sample binding supplies too many values.

    The binding key follows the kind: rowsBinding for list and table,
    pointsBinding for the rest. A missing binding name or an unreadable value
    passes here, since only a count that breaks a cap fails.
    """
    kind = element.get("type")
    binding_key = "rowsBinding" if kind in ROW_CAPS else "pointsBinding"
    binding_name = element.get(binding_key)
    if not isinstance(binding_name, str):
        return None
    values = bindings.get(binding_name)
    if not isinstance(values, list):
        return None
    return _cap_failure(kind, len(values))