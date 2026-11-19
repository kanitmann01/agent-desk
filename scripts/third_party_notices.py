#!/usr/bin/env python3
"""Regenerate THIRD-PARTY-NOTICES.md from the CycloneDX SBOM.

The notices file is generated, never hand-edited. It lists every component
that ships in the bundle, its licence, and the upstream licence text that
travels with it. Build-only components are listed separately because the
licence gate still checks them but they are not distributed.

Usage:
    python scripts/third_party_notices.py [--sbom PATH] [--output PATH]
    python scripts/third_party_notices.py --check

`--check` regenerates in memory and exits 1 if the committed file differs,
so CI can catch a stale notices file. Generation fails if a distributed
component has no upstream licence text on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SBOM = REPO_ROOT / "build" / "sbom.cdx.json"
DEFAULT_OUTPUT = REPO_ROOT / "THIRD-PARTY-NOTICES.md"
LICENSE_FILE_PROPERTY = "agentdesk:license-file"
EXCEPTION_PROPERTY = "agentdesk:license-exception"


def _licences(component: dict[str, Any]) -> list[str]:
    """Collect one component's licence identifiers, sorted and deduplicated.

    An SPDX expression is kept as one string rather than split; a component
    with nothing usable declared yields ["UNKNOWN"], so the generated table
    never shows an empty licence cell.
    """
    values: list[str] = []
    for entry in component.get("licenses") or []:
        if not isinstance(entry, dict):
            continue
        expression = entry.get("expression")
        if isinstance(expression, str) and expression.strip():
            values.append(expression.strip())
            continue
        licence = entry.get("license")
        if isinstance(licence, dict):
            value = licence.get("id") or licence.get("name")
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    return sorted(dict.fromkeys(values)) or ["UNKNOWN"]


def _property(component: dict[str, Any], name: str) -> str | None:
    """Return the value of the named CycloneDX property, or None.

    Only the first match is read, and a property whose value is not a string
    counts as absent.
    """
    for prop in component.get("properties") or []:
        if isinstance(prop, dict) and prop.get("name") == name:
            value = prop.get("value")
            return value if isinstance(value, str) else None
    return None


def _sha256(path: Path) -> str:
    """Return the hex sha256 of a file, read in 64 KiB chunks.

    The notices file records it beside each upstream licence text, so an
    edited licence shows up as a diff in the generated document.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cell(value: str) -> str:
    """Escape a value for a Markdown table cell.

    Only the pipe needs escaping, because it would otherwise end the cell; new
    lines never reach here from an SBOM field in practice.
    """
    return value.replace("|", "\\|")


def _component_table(
    components: list[dict[str, Any]], root: Path, require_text: bool
) -> tuple[list[str], list[str]]:
    """Render the Markdown table for one component list, plus the errors found.

    A licence text recorded in the SBOM but missing on disk is always an
    error; a component with no text recorded is one only when require_text is
    set, which is how build-only components are allowed to ship none. The
    CPython row reports its version as "bundled" because the patch level
    follows the build host and would make the committed file churn.
    """
    lines = [
        "| Component | Version | Licence | Upstream text |",
        "|---|---|---|---|",
    ]
    errors: list[str] = []
    for component in components:
        name = str(component.get("name") or "<unnamed>")
        version = str(component.get("version") or "")
        if name == "cpython":
            # The bundled interpreter patch version changes with the build
            # host. Keep the committed notice stable and point to the
            # manifest/SBOM for the exact version.
            version = "bundled"
        if str(component.get("purl") or "").startswith("pkg:pypi/"):
            # A Python dependency's version is resolved from the build host's
            # environment, exactly like the CPython patch level, so printing
            # it would churn the committed file on every upgrade. The SBOM
            # row carries the exact version.
            version = "resolved (see SBOM)"
        licences = ", ".join(_licences(component))
        text_path = _property(component, LICENSE_FILE_PROPERTY)
        if text_path:
            path = root / text_path
            if not path.is_file():
                errors.append(f"missing licence text: {text_path} (for {name})")
                upstream = f"`{text_path}` (MISSING)"
            else:
                upstream = (
                    f"`{text_path}` (sha256 `{_sha256(path)}`, "
                    f"{path.stat().st_size} bytes)"
                )
        else:
            if require_text:
                errors.append(f"no upstream licence text recorded for {name}")
            upstream = "not shipped (build-only)"
        lines.append(
            f"| {_cell(name)} | {_cell(version)} | {_cell(licences)} | {upstream} |"
        )
    return lines, errors


def render(sbom: dict[str, Any], root: Path) -> tuple[str, list[str]]:
    """Render the whole notices document from one SBOM.

    Returns the document and the errors that should stop it being written; a
    document that is not CycloneDX 1.6 renders as empty text with that error.
    Distributed and build-only components get separate tables, each sorted by
    name and version, and the SBOM's timestamp and serial are deliberately not
    reproduced so the file stays stable for --check.
    """
    if sbom.get("bomFormat") != "CycloneDX" or str(sbom.get("specVersion")) != "1.6":
        return "", ["not a CycloneDX 1.6 document"]
    components = [c for c in sbom.get("components") or [] if isinstance(c, dict)]
    distributed = [
        c for c in components if str(c.get("scope") or "required") != "excluded"
    ]
    build_only = [
        c for c in components if str(c.get("scope")) == "excluded"
    ]
    distributed.sort(key=lambda c: (str(c.get("name")), str(c.get("version"))))
    build_only.sort(key=lambda c: (str(c.get("name")), str(c.get("version"))))
    metadata = sbom.get("metadata") or {}
    app = (metadata.get("component") or {})

    lines = [
        "# Third-party notices",
        "",
        "<!-- GENERATED FILE - DO NOT EDIT.",
        "     Run: python scripts/third_party_notices.py",
        "     Source: build/sbom.cdx.json (CycloneDX 1.6).",
        "     CI runs --check and fails if this file is stale. -->",
        "",
        "Agent Desk bundles third-party components under the licences below.",
        "The Agent Desk core itself is proprietary; the plugin SDK boundary is",
        "Apache-2.0. See `LICENSE`, `LICENSE-SDK` and `docs/licensing.md`.",
        "",
        "- Source: `build/sbom.cdx.json` (CycloneDX 1.6, generated by",
        "  `scripts/sbom.py`; the document timestamp and serial are omitted",
        "  here so this file is stable for `--check`).",
        f"- Components in SBOM: {len(components)} "
        f"({len(distributed)} distributed, {len(build_only)} build-only)",
        "",
        "## Distributed components",
        "",
        "These components ship inside `dist/agent-desk/`. The `Upstream text`",
        "column is the repository path; `scripts/build_bundle.py` copies",
        "`licenses/third-party/` unchanged and `frontend/public/licenses/` to",
        "`licenses/fonts/` inside the bundle.",
        "",
    ]
    table, errors = _component_table(distributed, root, require_text=True)
    lines.extend(table)
    lines.extend(
        [
            "",
            "### Fonts",
            "",
            "The dashboard uses Geist, Geist Mono and Montserrat through",
            "`@fontsource` packages. All are SIL Open Font License 1.1. The",
            "licence text and copyright notice ship with the font files in",
            "`frontend/public/licenses/` and are copied into the bundle.",
            "",
            "### Python runtime",
            "",
            "The executable is built with Nuitka and embeds CPython. The CPython",
            "licence (PSF-2.0) is included in `dist/agent-desk/licenses/`. The",
            "exact CPython version is recorded in `manifest.json` and the SBOM;",
            "the table above says `bundled` so this file is stable across build",
            "interpreters. Python dependencies declared in `pyproject.toml` each",
            "get a row above, licensed from `[tool.agent-desk-licenses]`; their",
            "version column says `resolved (see SBOM)` because the installed",
            "version follows the build environment, like the CPython patch",
            "level. `cryptography` (memory encryption at rest, Apache-2.0 OR",
            "BSD-3-Clause) is the dependency shipped today, and its licence",
            "text travels in `licenses/third-party/cryptography-LICENSE.txt`.",
            "Nuitka is a build tool and is not redistributed; its own AGPL-3.0",
            "licence has a runtime exception that does not reach the compiled",
            "output.",
            "",
            "## Build-only components",
            "",
            "These packages are used to build or test the frontend and are not",
            "distributed. The licence gate still checks every one of them.",
            "",
        ]
    )
    table, _ = _component_table(build_only, root, require_text=False)
    lines.extend(table)
    lines.extend(
        [
            "",
            "## Regenerating",
            "",
            "```",
            "python scripts/sbom.py",
            "python scripts/license_gate.py build/sbom.cdx.json",
            "python scripts/third_party_notices.py",
            "```",
            "",
            "Do not edit this file by hand. A hand edit fails `--check` in CI.",
            "",
        ]
    )
    return "\n".join(lines), errors


def main(argv: list[str] | None = None) -> int:
    """Regenerate or check THIRD-PARTY-NOTICES.md and return the exit code.

    Reads --sbom (default build/sbom.cdx.json). With --check it compares the
    rendered text against --output and writes nothing, so CI can catch a stale
    file; without it, --output is overwritten with Unix newlines. Returns 0 on
    success and 1 when the SBOM cannot be read, the render found errors, or
    --check found a difference, with the reason on stderr.
    """
    parser = argparse.ArgumentParser(
        prog="third_party_notices.py",
        description="Regenerate THIRD-PARTY-NOTICES.md from the SBOM.",
    )
    parser.add_argument("--sbom", type=Path, default=DEFAULT_SBOM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check", action="store_true",
        help="fail if the output file is stale instead of writing it",
    )
    args = parser.parse_args(argv)
    try:
        sbom = json.loads(args.sbom.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"notices: cannot read {args.sbom}: {exc}", file=sys.stderr)
        return 1
    text, errors = render(sbom, REPO_ROOT)
    if errors:
        for error in errors:
            print(f"notices: {error}", file=sys.stderr)
        return 1
    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"notices: cannot read {args.output}: {exc}", file=sys.stderr)
            return 1
        if current != text:
            print(
                f"notices: {args.output} is stale; run "
                "python scripts/third_party_notices.py",
                file=sys.stderr,
            )
            return 1
        print(f"notices: {args.output} is up to date")
        return 0
    try:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"notices: cannot write {args.output}: {exc}", file=sys.stderr)
        return 1
    print(f"notices: wrote {args.output} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
