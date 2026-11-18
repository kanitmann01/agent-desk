#!/usr/bin/env python3
"""Fail-closed license gate for the Agent Desk CycloneDX 1.6 SBOM.

The allowlist is deliberately narrow: MIT, Apache-2.0, BSD-2-Clause,
BSD-3-Clause and ISC. Every component is checked, including build-only
components whose CycloneDX scope is "excluded", so a licence landmine
cannot hide in the toolchain.

A small, explicit set of non-allowlist licences is accepted only when the
component carries an `agentdesk:license-exception` property whose value
names that licence. Those exceptions exist for assets whose licence is
appropriate but not on the code allowlist (fonts, the CPython runtime) or
for build-only packages that never enter the distributed artifact. Commons
Clause, UNLICENSED, GPL, AGPL and SSPL can never be excepted.

Usage:
    python scripts/license_gate.py [SBOM] [--report PATH]

Exit codes:
    0  every component passes
    1  the SBOM is missing or malformed
    2  one or more components fail the licence policy

No third-party Python packages are needed; this runs on the 3.10 floor.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED_LICENSES = frozenset(
    {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}
)

# Non-allowlist licences that may be accepted when the component carries an
# explicit `agentdesk:license-exception` property with the same value.
# Keep this list short and legally reasoned: it is printed in the report.
LICENSE_EXCEPTIONS = {
    "OFL-1.1": (
        "font asset licence: bundling is allowed when the copyright notice "
        "and licence travel with the fonts (see licenses/ and THIRD-PARTY-NOTICES.md)"
    ),
    "PSF-2.0": (
        "CPython runtime and standard library bundled by Nuitka; the PSF "
        "licence permits redistribution"
    ),
    "MIT-0": (
        "build-only package (@csstools/color-helpers); never distributed"
    ),
    "CC-BY-4.0": (
        "build-only data package (caniuse-lite); never distributed"
    ),
}

EXCEPTION_PROPERTY = "agentdesk:license-exception"
LICENSE_SPLIT = re.compile(r"\s+(?:OR|AND|WITH)\s+", re.IGNORECASE)


class SbomError(ValueError):
    """The file is not a usable CycloneDX 1.6 SBOM."""


@dataclass
class Failure:
    component: str
    scope: str
    licenses: tuple[str, ...]
    reason: str


@dataclass
class Excepted:
    component: str
    scope: str
    license: str
    reason: str


@dataclass
class GateResult:
    ok: bool
    total: int = 0
    excluded: int = 0
    passed: int = 0
    excepted: int = 0
    failures: list[Failure] = field(default_factory=list)
    exceptions: list[Excepted] = field(default_factory=list)


def _label(component: dict[str, Any]) -> str:
    """Name one component for a report line, with version and purl.

    The purl is appended only when the name and version are not already
    visible in it, so an ordinary npm component reads as "pkg@1.2.3" and does
    not repeat its whole coordinate.
    """
    name = str(component.get("name") or "<unnamed>")
    version = component.get("version")
    purl = component.get("purl")
    suffix = ""
    if version:
        suffix = f"@{version}"
    if purl and not (name + suffix) in str(purl):
        suffix = f"{suffix} ({purl})"
    return name + suffix


def _exception_marker(component: dict[str, Any]) -> str | None:
    """Return the component's recorded licence exception, or None.

    Reads the first ``agentdesk:license-exception`` property. A property whose
    value is not a string counts as absent, so a malformed SBOM cannot open an
    exception by accident.
    """
    for prop in component.get("properties") or []:
        if isinstance(prop, dict) and prop.get("name") == EXCEPTION_PROPERTY:
            value = prop.get("value")
            return value if isinstance(value, str) else None
    return None


def _license_tokens(component: dict[str, Any]) -> list[str]:
    """Return every licence identifier/name, splitting SPDX expressions.

    Expressions are evaluated conservatively: every identifier must be
    allowed (or excepted), even in an OR expression. That is stricter than
    SPDX semantics on purpose; a dual-licensed package should be reviewed
    and pinned to the permissive branch rather than silently accepted.
    """
    tokens: list[str] = []
    entries = component.get("licenses")
    if not isinstance(entries, list):
        return tokens
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        expression = entry.get("expression")
        if isinstance(expression, str) and expression.strip():
            for part in LICENSE_SPLIT.split(expression):
                cleaned = part.strip().strip("()").strip()
                if cleaned:
                    tokens.append(cleaned)
            continue
        licence = entry.get("license")
        if isinstance(licence, dict):
            value = licence.get("id") or licence.get("name")
            if isinstance(value, str) and value.strip():
                tokens.append(value.strip())
        elif isinstance(licence, str) and licence.strip():
            tokens.append(licence.strip())
    return tokens


def _disallowed_reason(token: str) -> str | None:
    """Return why a licence token is banned outright, or None when it is not.

    The match is on substrings of the lowercased token because SBOMs spell
    these licences many ways (GPL-3.0-only, LGPL-2.1, "AGPL v3"). A hit
    cannot be excepted: the caller fails the component without consulting the
    allowlist or the recorded exceptions.
    """
    lowered = token.lower()
    if "commons" in lowered and "clause" in lowered:
        return "Commons Clause is never distributable (and cannot be excepted)"
    if "unlicensed" in lowered or "noassertion" in lowered:
        return "the component is UNLICENSED (and cannot be excepted)"
    if "agpl" in lowered:
        return "AGPL is not allowed (and cannot be excepted)"
    if "sspl" in lowered:
        return "SSPL is not allowed (and cannot be excepted)"
    if "gpl" in lowered:
        return "GPL/LGPL-family licences are not on the allowlist (and cannot be excepted)"
    if "cc-by" in lowered and "nc" in lowered:
        return "NonCommercial Creative Commons licences are not allowed"
    return None


def evaluate(sbom: dict[str, Any]) -> GateResult:
    """Check every declared licence in one CycloneDX 1.6 document.

    Returns a GateResult whose ok is False when any component failed. A
    component that declares no licence fails; a banned token fails the
    component immediately, without looking at the rest of its expression; and
    build-only components (scope "excluded") are checked like the rest even
    though they are counted apart. Raises SbomError for anything that is not a
    CycloneDX 1.6 document with a components list, so a gate that cannot read
    its input never reports a pass.
    """
    if not isinstance(sbom, dict):
        raise SbomError("the document root must be a JSON object")
    if sbom.get("bomFormat") != "CycloneDX":
        raise SbomError("bomFormat must be 'CycloneDX'")
    if str(sbom.get("specVersion")) != "1.6":
        raise SbomError("specVersion must be '1.6'")
    components = sbom.get("components")
    if not isinstance(components, list):
        raise SbomError("'components' must be a list")

    result = GateResult(ok=True)
    for component in components:
        if not isinstance(component, dict):
            raise SbomError("every entry in 'components' must be an object")
        result.total += 1
        scope = str(component.get("scope") or "required")
        if scope == "excluded":
            result.excluded += 1
        label = _label(component)
        tokens = _license_tokens(component)
        if not tokens:
            result.failures.append(
                Failure(label, scope, (), "no licence declared (missing licence data)")
            )
            continue
        marker = _exception_marker(component)
        component_failed = False
        for token in tokens:
            banned = _disallowed_reason(token)
            if banned:
                result.failures.append(Failure(label, scope, tuple(tokens), banned))
                component_failed = True
                break
            if token in ALLOWED_LICENSES:
                continue
            if marker == token and token in LICENSE_EXCEPTIONS:
                result.exceptions.append(
                    Excepted(label, scope, token, LICENSE_EXCEPTIONS[token])
                )
                continue
            if token in LICENSE_EXCEPTIONS and marker != token:
                reason = (
                    f"licence {token!r} needs an explicit {EXCEPTION_PROPERTY} "
                    f"property with value {token!r}"
                )
            else:
                reason = (
                    f"licence {token!r} is not in the allowlist and has no "
                    "recorded exception"
                )
            result.failures.append(Failure(label, scope, tuple(tokens), reason))
            component_failed = True
            break
        if not component_failed:
            if any(marker == token for token in tokens):
                result.excepted += 1
            else:
                result.passed += 1

    result.ok = not result.failures
    return result


def render_report(result: GateResult, sbom_path: Path) -> str:
    """Render the human-readable report for stdout and for --report.

    It restates the allowlist and the recorded exceptions, so a failing run
    explains the policy it applied, and its last line is "RESULT: PASS" or
    "RESULT: FAIL". The returned text always ends with a newline.
    """
    lines = [
        "Agent Desk licence gate (CycloneDX 1.6)",
        f"SBOM: {sbom_path.as_posix()}",
        "Allowlist: " + ", ".join(sorted(ALLOWED_LICENSES)),
        "Recorded exceptions: " + ", ".join(sorted(LICENSE_EXCEPTIONS)),
        (
            f"Components: {result.total} "
            f"({result.excluded} build-only, scope=excluded; build-only is still checked)"
        ),
        f"  pass: {result.passed}",
        f"  pass via recorded exception: {result.excepted}",
        f"  fail: {len(result.failures)}",
        "",
    ]
    if result.exceptions:
        lines.append("Recorded exceptions")
        for item in result.exceptions:
            lines.append(
                f"  EXCEPTION {item.component} [{item.scope}] "
                f"{item.license}: {item.reason}"
            )
        lines.append("")
    if result.failures:
        lines.append("Failures")
        for item in result.failures:
            licences = ", ".join(item.licenses) if item.licenses else "<none>"
            lines.append(
                f"  FAIL {item.component} [{item.scope}] "
                f"licences={licences}: {item.reason}"
            )
        lines.append("")
    lines.append("RESULT: " + ("PASS" if result.ok else "FAIL"))
    return "\n".join(lines) + "\n"


def _load(path: Path) -> dict[str, Any]:
    """Read and parse one SBOM file, naming the file in any error.

    An unreadable file and invalid JSON both become SbomError, which is what
    lets main answer exit code 1 (no verdict possible) rather than a licence
    failure.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SbomError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SbomError(f"{path} is not valid JSON: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """Run the gate on one SBOM and return its documented exit code.

    Prints the report on stdout and, with --report, writes the same text to
    that path, creating parent directories. Exit 0 when every component
    passes, 1 when the SBOM is missing, unreadable or not CycloneDX 1.6 (no
    report is written then) or the report cannot be saved, and 2 when the
    licence policy fails.
    """
    parser = argparse.ArgumentParser(
        prog="license_gate.py",
        description="Fail closed on licences outside the Agent Desk allowlist.",
    )
    parser.add_argument(
        "sbom", nargs="?", default="build/sbom.cdx.json",
        help="CycloneDX 1.6 JSON (default: build/sbom.cdx.json)",
    )
    parser.add_argument(
        "--report", type=Path, default=None,
        help="also write the human-readable report to this path",
    )
    args = parser.parse_args(argv)

    path = Path(args.sbom)
    try:
        result = evaluate(_load(path))
    except SbomError as exc:
        print(f"license gate: invalid SBOM: {exc}", file=sys.stderr)
        return 1

    report = render_report(result, path)
    if args.report is not None:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(report, encoding="utf-8", newline="\n")
        except OSError as exc:
            print(f"license gate: cannot write report: {exc}", file=sys.stderr)
            return 1
    sys.stdout.write(report)
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
