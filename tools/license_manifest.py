"""License manifest generation: the build gate for Legal review.

Reads the dependency list from pyproject and the per-dependency license
annotations from [tool.agent-desk-licenses]. Fail-closed by design: a
dependency without an annotation is a failure, and so is any license
outside MIT, Apache-2.0, BSD, or ISC. An "A OR B" dual-license
annotation is admitted when every alternative is in the allowlist (the
form cryptography itself uses). Zero dependencies is still supported
and renders the zero-dependency record.

Run: python tools/license_manifest.py  (exit 0 clean, 1 violation)
Writes THIRD-PARTY-LICENSES.md next to pyproject.
"""

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, the declared floor
    tomllib = None  # the fallback reader at the bottom of this file covers it

ALLOWED = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}
MANIFEST_NAME = "THIRD-PARTY-LICENSES.md"

# Why each dependency exists, so the manifest stays a reviewable record
# rather than a bare table (one line per component, ticket #94).
PURPOSES = {
    "cryptography": "memory encryption at rest (AES-256-GCM field "
                    "encryption, HKDF key derivation and HMAC blind "
                    "indexes)",
}


def check_dependencies(annotations: dict[str, str]) -> list[str]:
    """Return the violations; empty means the manifest may be written.

    Every annotation must name a license in the allowlist, possibly as
    an "A OR B" dual license with every alternative allowed. The check
    that every declared dependency carries an annotation at all lives
    in main().
    """
    violations: list[str] = []
    for name, license in annotations.items():
        alternatives = [part.strip() for part in license.split(" OR ")]
        if not all(part in ALLOWED for part in alternatives):
            violations.append(f"{name}: license {license!r} is not in {sorted(ALLOWED)}")
    return violations


def render_manifest(annotations: dict[str, str], version: str) -> str:
    lines = [
        "# Third-party license manifest",
        "",
    ]
    if annotations:
        lines += [
            f"The Agent Desk {version} **Python runtime ships one"
            f" third-party dependency** (the first; it arrived with"
            " memory encryption at rest, ticket #94):",
            "",
            "| Component | Version scoped in pyproject | Used for | License |",
            "|---|---|---|---|",
        ]
        for name, license in sorted(annotations.items()):
            purpose = PURPOSES.get(name, "")
            lines.append(f"| {name} | pinned in pyproject | {purpose} | {license} |")
        lines += [
            "",
            "The runtime itself is CPython, Python Software Foundation",
            "license, a permissive license reviewed separately from bundled",
            "components.",
            "",
        ]
    else:
        lines += [
            f"The Agent Desk {version} **Python runtime has no third-party",
            "dependencies**: the app is pure Python standard library. The",
            "runtime itself is CPython, Python Software Foundation license, a",
            "permissive license reviewed separately from bundled components.",
            "",
        ]
    lines += [
        "The **dashboard SPA bundle does ship third-party work**: React",
        "compiled into its JavaScript, and the Geist, Geist Mono, and",
        "Montserrat font files. Every item is listed with its license in the",
        "Dashboard SPA section below.",
        "",
        "The allowlist for any Python dependency is MIT, Apache-2.0,",
        "BSD-2-Clause, BSD-3-Clause, and ISC; anything outside it fails",
        "the build.",
        "",
    ]
    lines.append(
        "Upstream LICENSE (and NOTICE, where Apache-2.0) files ship inside"
        " the install folder for any listed Python dependency."
        + ("" if annotations else
           " With zero Python dependencies there is nothing to ship on that"
           " side; this file is the record that the check ran and passed.")
    )
    lines.append(SPA_TOOLCHAIN_SECTION)
    # One final newline exactly: the section string carries its own
    # leading and trailing breaks, and a trailing blank line here would
    # make every regeneration dirty against the committed manifest.
    return "\n".join(lines).rstrip("\n") + "\n"


# The dashboard SPA: what its committed bundle carries and the toolchain
# that builds it. None of this enters pyproject dependencies. Kept here
# (not hand-edited into the manifest) so regenerating the file preserves
# it.
SPA_TOOLCHAIN_SECTION = """
## Dashboard SPA (what the bundle ships, and the toolchain that builds it)

The dashboard UI is a React single-page app built in `frontend/`. End
users receive the committed build output
(`src/agentdesk/server/static/spa/`) and never need node, npm, or the
build tools. The last column says which items are inside that output
and which only run at development time.

| Component | Used for | License | In the shipped bundle |
|---|---|---|---|
| react 19.3.1 | UI library | MIT | yes, compiled into the JavaScript |
| react-dom 19.3.1 | DOM renderer | MIT | yes, compiled into the JavaScript |
| @fontsource/geist | Geist, the UI face | OFL-1.1 | yes, the .woff2 files unchanged |
| @fontsource/geist-mono | Geist Mono, the numeric typeface | OFL-1.1 | yes, the .woff2 files unchanged |
| @fontsource/montserrat | Montserrat, the display face | OFL-1.1 | yes, the .woff2 files unchanged |
| vite | build tool | MIT | no, development only |
| @vitejs/plugin-react | build plugin | MIT | no, development only |
| typescript 5.9.3 | type checking | Apache-2.0 | no, development only |

License notes:

- React, react-dom, Vite and @vitejs/plugin-react are MIT; typescript
  is Apache-2.0 (with its NOTICE in the upstream package). Upstream
  license texts live in each package under
  `frontend/node_modules/<package>/LICENSE*` after `npm install`, and
  in the npm registry metadata for each version pinned in
  `frontend/package.json`.
- The dark-glass theme's vendored react-bits components (MIT plus
  Commons Clause) and its animation, styling and class-helper packages
  left with that theme: the warm-paper system
  (docs/design-language.md) is drawn entirely in the repo's own
  stylesheet and components. Nothing in the bundle carries a Commons
  Clause obligation anymore.
- The two font families come from their @fontsource packages under
  the SIL Open Font License 1.1 (OFL-1.1). Unlike the rest of this
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
  as such: the runtime libraries (React, react-dom) are compiled into
  the bundle's JavaScript, and the two font families above are copied
  into it unchanged.
- Test tooling (vitest, jsdom, @testing-library/*, @types/*) runs
  only in the frontend working tree; none of it enters the bundle.
"""


# The fallback TOML reader, used only when tomllib is absent. pyproject
# declares requires-python >=3.10 and the CI license gate runs on that
# floor, but tomllib ships with 3.11. The repo is stdlib-only by
# design, so instead of a dependency this reader covers exactly the
# pyproject subset the tool reads (tables with dotted bare-key headers,
# strings, arrays, booleans, integers, floats) and raises on anything
# else, so an untaught syntax fails the gate rather than being guessed
# at. Within the accepted subset obscure table-structure corners can
# still diverge from tomllib, but nothing in that class can change the
# dependencies or annotations the allowlist verdict is computed from.
# The tomllib-agreement test in tests/test_license_manifest_tool.py is
# the authority that the two readers match on this subset.
_BARE_KEY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)
_BASIC_ESCAPES = {
    '"': '"', "\\": "\\", "b": "\b", "t": "\t",
    "n": "\n", "f": "\f", "r": "\r",
}
_INT_TOKEN = re.compile(r"[+-]?(0|[1-9](_?\d)*)")
_FLOAT_TOKEN = re.compile(r"[+-]?(0|[1-9](_?\d)*)(\.(0|[1-9](_?\d)*))?([eE][+-]?(0|[1-9](_?\d)*))?")


def _load_toml(path: Path) -> dict:
    """Parse a TOML file, with the 3.10 fallback when tomllib is absent."""
    if tomllib is not None:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    return _parse_toml_subset(path.read_text(encoding="utf-8"), str(path))


def _parse_toml_subset(text: str, source: str) -> dict:
    """Parse the supported pyproject subset, raising on the rest.

    One pass over the text with a manual cursor, so every rejection
    can name its line. Nested closures share the cursor (pos) and the
    current line number; read_value may consume newlines, but only
    inside an array.
    """
    root: dict = {}
    current = root
    headers: set[tuple[str, ...]] = set()
    pos, line, end = 0, 1, len(text)

    def err(detail: str) -> ValueError:
        return ValueError(f"{source}:{line}: {detail}")

    def skip_in_line() -> None:
        nonlocal pos
        while pos < end and text[pos] in " \t\r":
            pos += 1

    def skip_blank() -> None:
        # Whitespace, newlines and comments between statements.
        nonlocal pos, line
        while pos < end:
            char = text[pos]
            if char in " \t\r":
                pos += 1
            elif char == "\n":
                pos += 1
                line += 1
            elif char == "#":
                while pos < end and text[pos] != "\n":
                    pos += 1
            else:
                break

    def expect_line_end() -> None:
        nonlocal pos
        skip_in_line()
        if pos < end and text[pos] == "#":
            while pos < end and text[pos] != "\n":
                pos += 1
        if pos < end and text[pos] != "\n":
            raise err(f"expected a comment or end of line, found {text[pos]!r}")

    def read_key() -> str:
        nonlocal pos
        start = pos
        while pos < end and text[pos] in _BARE_KEY_CHARS:
            pos += 1
        return text[start:pos]

    def read_table_header() -> dict:
        # The opening '[' is already consumed; quoted keys are refused
        # with the dotted ones below, as bare keys cover every table
        # this tool reads.
        nonlocal pos
        path = []
        while True:
            skip_in_line()
            key = read_key()
            if not key:
                raise err("expected a bare key in the table header "
                          "(quoted and dotted keys are not supported)")
            path.append(key)
            skip_in_line()
            if pos >= end:
                raise err("unterminated table header")
            char = text[pos]
            pos += 1
            if char == "]":
                break
            if char != ".":
                raise err(f"expected '.' or ']' in table header, found {char!r}")
        expect_line_end()
        if tuple(path) in headers:
            raise err(f"duplicate table header [{'.'.join(path)}]")
        headers.add(tuple(path))
        table = root
        for depth, key in enumerate(path):
            child = table.get(key)
            if child is None:
                child = {}
                table[key] = child
            if not isinstance(child, dict):
                raise err(f"key {key!r} holds a value, cannot hold table "
                          f"{'.'.join(path[:depth + 1])}")
            table = child
        return table

    def read_basic_string() -> str:
        nonlocal pos
        pos += 1  # the opening quote
        out = []
        while True:
            if pos >= end or text[pos] == "\n":
                raise err("unterminated string")
            char = text[pos]
            if char == '"':
                pos += 1
                return "".join(out)
            if char == "\\":
                pos += 1
                if pos >= end:
                    raise err("unterminated escape")
                escape = text[pos]
                if escape in _BASIC_ESCAPES:
                    out.append(_BASIC_ESCAPES[escape])
                    pos += 1
                elif escape in "uU":
                    width = 4 if escape == "u" else 8
                    digits = text[pos + 1:pos + 1 + width]
                    if not all(c in "0123456789abcdefABCDEF" for c in digits) \
                            or len(digits) < width:
                        raise err(f"bad \\{escape} escape")
                    code = int(digits, 16)
                    if code > 0x10FFFF:
                        raise err(f"escape \\{escape}{digits} is not a code point")
                    if 0xD800 <= code <= 0xDFFF:
                        raise err(f"escape \\{escape}{digits} is a lone surrogate")
                    out.append(chr(code))
                    pos += 1 + width
                else:
                    raise err(f"escape \\{escape} is not supported")
            else:
                out.append(char)
                pos += 1

    def read_literal_string() -> str:
        nonlocal pos
        pos += 1  # the opening quote
        start = pos
        while True:
            if pos >= end or text[pos] == "\n":
                raise err("unterminated literal string")
            if text[pos] == "'":
                value = text[start:pos]
                pos += 1
                return value
            pos += 1

    def read_number(token: str):
        # Dates, times, hex and their kin gather into the token and
        # then fail both patterns, so they are rejected as a unit.
        plain = token.replace("_", "")
        if _INT_TOKEN.fullmatch(token):
            return int(plain)
        if _FLOAT_TOKEN.fullmatch(token):
            return float(plain)
        raise err(f"value {token!r} is not supported by the fallback TOML reader")

    def read_value():
        nonlocal pos
        if text.startswith('"""', pos):
            raise err("multiline strings are not supported by the fallback TOML reader")
        if text.startswith("'''", pos):
            raise err("multiline literal strings are not supported by the fallback TOML reader")
        char = text[pos] if pos < end else ""
        if char == '"':
            return read_basic_string()
        if char == "'":
            return read_literal_string()
        if char == "[":
            return read_array()
        if char == "{":
            raise err("inline tables are not supported by the fallback TOML reader")
        for literal, value in (("true", True), ("false", False)):
            if text.startswith(literal, pos):
                pos += len(literal)
                return value
        if char.isdigit() or char in "+-":
            start = pos
            pos += 1
            while pos < end and (text[pos].isalnum() or text[pos] in "_+-.:"):
                pos += 1
            return read_number(text[start:pos])
        raise err(f"expected a value, found {char!r}")

    def read_array() -> list:
        nonlocal pos
        pos += 1  # the opening bracket
        items = []
        while True:
            skip_blank()
            if pos >= end:
                raise err("unterminated array")
            if text[pos] == "]":
                pos += 1
                return items
            items.append(read_value())
            skip_blank()
            if pos >= end:
                raise err("unterminated array")
            char = text[pos]
            pos += 1
            if char == "]":
                return items
            if char != ",":
                raise err(f"expected ',' or ']' in array, found {char!r}")

    while True:
        skip_blank()
        if pos >= end:
            return root
        if text[pos] == "[":
            pos += 1
            if text[pos:pos + 1] == "[":
                raise err("arrays of tables ([[...]]) are not supported "
                          "by the fallback TOML reader")
            current = read_table_header()
            continue
        key = read_key()
        if not key:
            raise err(f"expected a table header or a key, found {text[pos]!r}")
        skip_in_line()
        if pos < end and text[pos] == ".":
            raise err("dotted keys are not supported by the fallback TOML reader")
        if pos >= end or text[pos] != "=":
            raise err(f"expected '=' after key {key!r}")
        pos += 1
        skip_in_line()
        if pos >= end:
            raise err(f"expected a value for key {key!r}")
        if key in current:
            raise err(f"duplicate key {key!r}")
        current[key] = read_value()
        expect_line_end()


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    pyproject = repo / "pyproject.toml"
    data = _load_toml(pyproject)
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
    # newline="\n": the manifest is committed with LF endings, and a
    # plain write_text would flip them to CRLF on Windows.
    (repo / MANIFEST_NAME).write_text(
        render_manifest(annotations, version), encoding="utf-8", newline="\n"
    )
    print(f"{MANIFEST_NAME}: {len(annotations)} components, all permissive; clean.")
    return 0


def _requirement_name(requirement: str) -> str:
    return requirement.split(";")[0].split("(")[0].strip().split(" ")[0].split(">")[0].split("<")[0].split("=")[0].split("[")[0]


if __name__ == "__main__":
    sys.exit(main())
