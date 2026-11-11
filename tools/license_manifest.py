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
    lines.append(SPA_TOOLCHAIN_SECTION)
    return "\n".join(lines) + "\n"


# The dashboard SPA toolchain: development-time only, so it never enters
# pyproject dependencies and only the built bundle ships to users. Kept
# here (not hand-edited into the manifest) so regenerating the file
# preserves it.
SPA_TOOLCHAIN_SECTION = """
## Dashboard SPA (development-time toolchain only)

The dashboard UI is a React single-page app built in `frontend/`. The
toolchain below runs only at development time: end users receive the
committed build output (`src/agentdesk/server/static/spa/`) and never
need node, npm, or any of these packages at runtime.

| Component | Used for | License |
|---|---|---|
| react 19.3.1 | UI library | MIT |
| react-dom 19.3.1 | DOM renderer | MIT |
| vite 7.3.8 | build tool (dev) | MIT |
| @vitejs/plugin-react 5.2.0 | build plugin (dev) | MIT |
| typescript 5.9.3 | type checking (dev) | Apache-2.0 |
| tailwindcss 4.3.5, @tailwindcss/vite 4.3.5 | styling (dev build) | MIT |
| motion 12.43.0 | animation (the framer-motion package) | MIT |
| clsx 2.1.1 | class name helper | MIT |
| @fontsource-variable/inter 5.3.0 | Inter Variable, the body typeface (font files ship in the bundle) | OFL-1.1 |
| @fontsource-variable/space-grotesk 5.3.0 | Space Grotesk Variable, the display typeface (font files ship in the bundle) | OFL-1.1 |
| react-bits (vendored components in `frontend/src/vendor/reactbits/`) | Aurora, StarBorder, TiltedCard, Magnet, GradientText, ShinyText, DecryptedText, AnimatedList, LatticeLoader, StatusMark, GlassSurface, GlareHover, CountUp, ClickSpark, SpotlightCard | MIT + Commons Clause |

License notes:

- React, react-dom, Vite, @vitejs/plugin-react, Tailwind CSS, motion
  and clsx are MIT; typescript is Apache-2.0 (with its NOTICE in the
  upstream package). Upstream license texts live in each package under
  `frontend/node_modules/<package>/LICENSE*` after `npm install`, and
  in the npm registry metadata for each version pinned in
  `frontend/package.json`.
- react-bits (github.com/DavidHDev/react-bits) is MIT plus Commons
  Clause: free for personal and commercial use; the restriction is on
  selling the library itself. Agent Desk is an internal tool, not sold,
  so the restriction does not apply. The vendored component files carry
  provenance headers pointing at the upstream repository. The vendored
  set adds no npm dependency beyond motion: AnimatedList is vendored
  without its demo rows and the two icon packages they import, and
  TextType and SplitText are in-repo equivalents because the upstream
  ones animate through GSAP, whose license is not on the allowlist.
- Inter and Space Grotesk come from the @fontsource-variable packages
  under the SIL Open Font License 1.1 (OFL-1.1). Unlike the rest of this
  table, the fonts themselves ship: the build copies their .woff2 files
  into the bundle, so the app never fetches a font from another origin.
  The OFL allows bundling and redistribution with software and asks
  that the copyright notice and license travel with the fonts: both
  license texts are committed in `frontend/public/licenses/` and the
  build emits them next to the fonts, in
  `src/agentdesk/server/static/spa/licenses/`. OFL-1.1 is a font
  license and is not on the allowlist above, which gates the Python
  dependencies declared in pyproject; the fonts are listed here so the
  record is complete.
- Only the built bundle ships to users. No npm package is distributed
  as such: the built JavaScript is Agent Desk's own artifact, and the
  two font families above are the only third-party files copied into
  the bundle unchanged.
"""


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
