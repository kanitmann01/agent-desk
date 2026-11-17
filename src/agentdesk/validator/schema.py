"""Manifest schema: required top-level keys, their types, no unknown keys.

schemaVersion 1 is the original contract and keeps its exact key set.
schemaVersion 2 is additive: it adds the marketplace discovery fields
(category, tags, icon, summary, description, highlights, sample) as
required keys and optionally requires/minHost as optional keys. A v1
manifest that carries a v2-only key is still an unknown-key failure.
"""

import re

from .model import Failure

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

ALLOWED_LICENSES = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC")

SCHEMA_VERSIONS = (1, 2)

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
    "config": dict,
}

# The keys v2 adds on top of the v1 set. They are required for v2 and
# unknown for v1.
V2_REQUIRED_KEY_TYPES = {
    "category": str,
    "tags": list,
    "icon": str,
    "summary": str,
    "description": str,
    "highlights": list,
    "sample": str,
}

V2_OPTIONAL_KEY_TYPES = {
    "requires": list,
    "minHost": str,
}

CATEGORIES = (
    "finance",
    "time",
    "communication",
    "research",
    "operations",
    "command",
    "reference",
)

ICONS = (
    "calendar",
    "chart",
    "mail",
    "book",
    "checklist",
    "clock",
    "alert",
    "folder",
    "plugin",
    "generic",
)

TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SAFE_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

MAX_TAGS = 8
MAX_SUMMARY_CHARS = 120
MAX_DESCRIPTION_CHARS = 4000
HIGHLIGHT_COUNT = 3
MAX_HIGHLIGHT_CHARS = 120

_TYPE_NAMES = {str: "string", int: "integer", dict: "object", list: "array"}


def validate_schema(manifest) -> list[Failure]:
    """Check top-level keys and types; return every schema failure found."""
    if not isinstance(manifest, dict):
        return [Failure("bad-schema", "manifest must be a JSON object")]

    failures: list[Failure] = []
    is_v2 = _is_v2(manifest)

    required = dict(REQUIRED_KEY_TYPES)
    optional = dict(OPTIONAL_KEY_TYPES)
    if is_v2:
        required.update(V2_REQUIRED_KEY_TYPES)
        optional.update(V2_OPTIONAL_KEY_TYPES)
    known_keys = set(required) | set(optional)

    for key in sorted(set(manifest) - known_keys):
        failures.append(Failure("unknown-key", f"unknown top-level key: {key}"))

    for key, expected_type in required.items():
        if key not in manifest:
            failures.append(Failure("bad-schema", f"missing required key: {key}"))
        elif not isinstance(manifest[key], expected_type):
            failures.append(
                Failure(
                    "bad-schema",
                    f"key '{key}' must be a {_TYPE_NAMES[expected_type]}",
                )
            )
    for key, expected_type in optional.items():
        if key in manifest and not isinstance(manifest[key], expected_type):
            failures.append(
                Failure(
                    "bad-schema",
                    f"key '{key}' must be a {_TYPE_NAMES[expected_type]}",
                )
            )

    failures.extend(_validate_values(manifest, is_v2))

    return failures


def _is_v2(manifest) -> bool:
    version = manifest.get("schemaVersion")
    return isinstance(version, int) and not isinstance(version, bool) and version == 2


def _validate_values(manifest, is_v2: bool) -> list[Failure]:
    """Value rules that only apply when the key holds its expected type."""
    failures: list[Failure] = []

    version = manifest.get("schemaVersion")
    if isinstance(version, int):
        if isinstance(version, bool) or version not in SCHEMA_VERSIONS:
            failures.append(
                Failure(
                    "bad-schema",
                    f"schemaVersion must be 1 or 2, got {version}",
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

    if is_v2:
        failures.extend(_validate_v2_values(manifest))

    license_id = manifest.get("license")
    if isinstance(license_id, str) and license_id not in ALLOWED_LICENSES:
        failures.append(
            Failure("bad-license", f"license '{license_id}' is not in the allowlist")
        )

    return failures


def _validate_v2_values(manifest) -> list[Failure]:
    """The v2 discovery fields: enums, lengths, slugs and safe paths."""
    failures: list[Failure] = []

    category = manifest.get("category")
    if isinstance(category, str) and category not in CATEGORIES:
        failures.append(
            Failure(
                "bad-schema",
                f"category must be one of: {', '.join(CATEGORIES)}",
            )
        )

    tags = manifest.get("tags")
    if isinstance(tags, list):
        if len(tags) > MAX_TAGS:
            failures.append(
                Failure(
                    "bad-schema",
                    f"tags must contain at most {MAX_TAGS} entries, got {len(tags)}",
                )
            )
        seen: set[str] = set()
        for tag in tags:
            if not isinstance(tag, str) or not TAG_PATTERN.match(tag):
                failures.append(
                    Failure(
                        "bad-schema",
                        f"tag {tag!r} must be a lowercase slug matching "
                        "^[a-z0-9][a-z0-9-]*$",
                    )
                )
            elif tag in seen:
                failures.append(
                    Failure("bad-schema", f"tags must be unique, duplicate: {tag}")
                )
            else:
                seen.add(tag)

    icon = manifest.get("icon")
    if isinstance(icon, str) and icon not in ICONS:
        failures.append(
            Failure("bad-schema", f"icon must be one of: {', '.join(ICONS)}")
        )

    summary = manifest.get("summary")
    if isinstance(summary, str):
        if not summary.strip():
            failures.append(
                Failure("bad-schema", "summary must be a nonempty string")
            )
        elif len(summary) > MAX_SUMMARY_CHARS:
            failures.append(
                Failure(
                    "bad-schema",
                    f"summary must be at most {MAX_SUMMARY_CHARS} characters, "
                    f"got {len(summary)}",
                )
            )

    description = manifest.get("description")
    if isinstance(description, str):
        if not description.strip():
            failures.append(
                Failure("bad-schema", "description must be a nonempty string")
            )
        elif len(description) > MAX_DESCRIPTION_CHARS:
            failures.append(
                Failure(
                    "bad-schema",
                    f"description must be at most {MAX_DESCRIPTION_CHARS} "
                    f"characters, got {len(description)}",
                )
            )

    highlights = manifest.get("highlights")
    if isinstance(highlights, list):
        if len(highlights) != HIGHLIGHT_COUNT:
            failures.append(
                Failure(
                    "bad-schema",
                    f"highlights must contain exactly {HIGHLIGHT_COUNT} entries, "
                    f"got {len(highlights)}",
                )
            )
        for highlight in highlights:
            if (
                not isinstance(highlight, str)
                or not highlight.strip()
                or len(highlight) > MAX_HIGHLIGHT_CHARS
            ):
                failures.append(
                    Failure(
                        "bad-schema",
                        "highlights entries must be nonempty strings of at most "
                        f"{MAX_HIGHLIGHT_CHARS} characters",
                    )
                )

    sample = manifest.get("sample")
    if isinstance(sample, str):
        problem = _sample_problem(sample)
        if problem is not None:
            failures.append(Failure("bad-schema", problem))

    requires = manifest.get("requires")
    if isinstance(requires, list):
        seen_ids: set[str] = set()
        plugin_id = manifest.get("id")
        for entry in requires:
            if (
                not isinstance(entry, str)
                or not SAFE_PLUGIN_ID.match(entry)
                or ".." in entry
            ):
                failures.append(
                    Failure(
                        "bad-schema",
                        "requires entries must be safe plugin ids",
                    )
                )
            elif entry == plugin_id:
                failures.append(
                    Failure(
                        "bad-schema",
                        "requires must not list the plugin's own id",
                    )
                )
            elif entry in seen_ids:
                failures.append(
                    Failure(
                        "bad-schema",
                        f"requires entries must be unique, duplicate: {entry}",
                    )
                )
            else:
                seen_ids.add(entry)

    min_host = manifest.get("minHost")
    if isinstance(min_host, str) and not min_host.strip():
        failures.append(Failure("bad-schema", "minHost must be a nonempty string"))

    return failures


def _sample_problem(sample: str) -> str | None:
    """Return why a sample path is unsafe, or None when it is fine."""
    if not sample or not sample.endswith(".json"):
        return "sample must be a relative .json path inside the plugin"
    if sample.startswith("/") or re.match(r"^[A-Za-z]:", sample):
        return "sample must be a relative .json path inside the plugin"
    if "\\" in sample:
        return "sample must use '/' separators, not backslashes"
    parts = sample.split("/")
    if any(part == ".." for part in parts):
        return "sample must not contain '..' path segments"
    if any(part == "" for part in parts):
        return "sample must be a relative .json path inside the plugin"
    return None
