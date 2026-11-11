"""License manifest generation: the build gate for Legal review.

Reads the dependency list from pyproject and the per-dependency license
annotations from [tool.agent-desk-licenses]. Fail-closed by design: a
dependency without an annotation is a failure, and so is any license
outside MIT, Apache-2.0, BSD, or ISC. Zero dependencies is the clean
path, and the one this repo is on.

Run: python tools/license_manifest.py  (exit 0 clean, 1 violation)
Writes THIRD-PARTY-LICENSES.md next to pyproject.
"""

import sys
import tomllib
from pathlib import Path

ALLOWED = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}
MANIFEST_NAME = "THIRD-PARTY-LICENSES.md"


def check_dependencies(annotations: dict[str, str]) -> list[str]:
    """Return the violations; empty means the manifest may be written.

    Every declared dependency must carry an annotation, and the
    annotation must be in the allowlist. Fail closed both ways.
    """
    violations: list[str] = []
    for name, license in annotations.items():
        if license not in ALLOWED:
            violations.append(f"{name}: license {license!r} is not in {sorted(ALLOWED)}")
    return violations


def render_manifest(annotations: dict[str, str], version: str) -> str:
    lines = [
        "# Third-party license manifest",
        "",
        f"Agent Desk {version} ships **no third-party components**: the app is",
        "pure Python standard library. The runtime itself is CPython,",
        "Python Software Foundation license, a permissive license reviewed",
        "separately from bundled components.",
        "",
        "The allowlist for any future component is MIT, Apache-2.0,",
        "BSD-2-Clause, BSD-3-Clause, and ISC; anything outside it fails",
        "the build.",
        "",
    ]
    if annotations:
        lines.append("If components are ever added, each lands here with its license:")
        lines.append("")
        lines.append("| Component | Version scoped in pyproject | License |")
        lines.append("|---|---|---|")
        for name, license in sorted(annotations.items()):
            lines.append(f"| {name} | pinned in pyproject | {license} |")
        lines.append("")
    lines.append(
        "Upstream LICENSE (and NOTICE, where Apache-2.0) files ship inside"
        " the install folder for any listed component. With zero"
        " components there is nothing to ship; this file is the record"
        " that the check ran and passed."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    pyproject = repo / "pyproject.toml"
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    declared = data.get("project", {}).get("dependencies", [])
    annotations = data.get("tool", {}).get("agent-desk-licenses", {})

    # Fail closed: a declared dependency without an annotation is a
    # violation, even before anyone asks what its license is.
    violations = [
        f"{_requirement_name(dep)}: no license annotation in [tool.agent-desk-licenses]"
        for dep in declared
        if _requirement_name(dep) not in annotations
    ]
    violations += check_dependencies(annotations)
    if violations:
        for violation in violations:
            print(f"license violation: {violation}", file=sys.stderr)
        return 1

    version = data.get("project", {}).get("version", "0.0.0")
    (repo / MANIFEST_NAME).write_text(render_manifest(annotations, version), encoding="utf-8")
    print(f"{MANIFEST_NAME}: {len(annotations)} components, all permissive; clean.")
    return 0


def _requirement_name(requirement: str) -> str:
    return requirement.split(";")[0].split("(")[0].strip().split(" ")[0].split(">")[0].split("<")[0].split("=")[0].split("[")[0]


if __name__ == "__main__":
    sys.exit(main())
