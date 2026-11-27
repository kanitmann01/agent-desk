"""The Nexuus Bot naming guard: the contract in tools/naming/, enforced.

Spec 032, tickets 01a (issue 354, the data) and 01b (issue 355, this
guard). Nothing is renamed here: the guard is green on the untouched
tree with every per-family temporary-list entry still in place, and a
later ticket clears its own family by renaming its surfaces and
emptying its file.

The rules, each with its source:

1.  Pins. Every pinned entry of inventory.json still carries the
    approved literals, and the two exact pins of the old two-literal
    guard keep their strictness (README line 1 and the face constant).
2.  Old display forms, the spellings inventory.json names under
    old_display_forms (the spaced wordmark, the compact forms and, with
    them, the uppercase prefix used as display text) are rejected
    case-insensitively on production source and live documents,
    everywhere outside the per-family temporary-list entries and the
    compatibility allowlist contexts. Python files are searched through
    their string and comment tokens, so code identifiers (import
    paths, class names) are not display text. This source never spells
    the old forms: they are read from the data, or the guard would
    reject its own text.
3.  The old `AD` initials are rejected in avatar contexts only: a line
    that draws the avatar mark and puts `AD` in its element text or its
    children value is a violation unless a temporary entry covers the
    file. The entries that declare `initials` expect `NB`.
4.  The U+2014 ban keeps its existing live-tree scope: src, tools,
    scripts, frontend/src and tests, plus the five named root files,
    with the docs trees and build folders excluded, exactly as the
    guard before it walked them.
5.  Tracked path names: an old-form path survives only as a retained
    launcher, a test of a retained launcher, a legal file, a dated
    archive, or inside the temporary package-path entries.
6.  The count report implements the R2 method over tracked text and
    tracked paths: occurrences are regex matches (not lines), and
    old-form tracked paths are counted separately.

Run it directly, or read the report:

    python tools/naming_guard.py
    python tools/naming_guard.py --report

The report compares its live numbers with the before-numbers the
ticket 01a sweep recorded (pull request 375). The guard starts no desk,
no walk and no application: it reads the tracked tree and prints a
verdict.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMING = ROOT / "tools" / "naming"

APPROVED_NAME = "Nexuus Bot"
APPROVED_INITIALS = "NB"
OLD_INITIALS = "AD"
EM_DASH = chr(0x2014)

_OLD_FORMS: tuple[str, ...] | None = None

TEXT_SUFFIXES = {
    ".md", ".txt", ".json", ".toml", ".yml", ".yaml", ".html", ".css",
    ".js", ".ts", ".tsx", ".jsx", ".cmd", ".command", ".ps1", ".svg",
    ".xml", ".ini", ".cfg",
}
TEXT_NAMES = {".gitignore", ".gitattributes"}
PY_SUFFIX = ".py"

# An avatar context: the line draws the avatar mark (the word avatar)
# and puts the old initials in its element text or its children value,
# the three shapes the live renderers and the committed bundle use.
AVATAR_INITIALS = re.compile(r"(>\s*AD\s*<|children\s*:\s*[\"']AD[\"'])")

# The em-dash live-tree scope, exactly the guard before this one kept.
EM_ROOTS = (
    ROOT / "src",
    ROOT / "tools",
    ROOT / "scripts",
    ROOT / "frontend" / "src",
    ROOT / "tests",
)
EM_FILES = (
    ROOT / "README.md",
    ROOT / "DEMO.md",
    ROOT / "frontend" / "README.md",
    ROOT / "frontend" / "package.json",
    ROOT / "frontend" / "index.html",
)
EM_SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache", ".venv"}
EM_ARCHIVE_PREFIXES = ("docs-evidence", "docs-tickets", "docs-plans",
                       "docs-ideas", "docs-superpowers", "docs-plugins")

# The before-numbers of this tree, recorded by the ticket 01a sweep
# (pull request 375) and quoted by the spec's measured notes.
RECORDED_BASELINE = {
    "recorded_by": "ticket 01a sweep (issue 354), pull request 375",
    "scanned_files": 466,
    "occurrences": 835,
    "allowlisted": 660,
    "temporary": 175,
    "unclassified": 0,
    "old_form_paths": 301,
}


@dataclass
class Contract:
    """The name contract as data, read once per run."""

    inventory: dict
    allowlist: dict
    exclusions: dict
    temporary: list


def old_forms() -> tuple[str, ...]:
    """The old display forms, lowercased, read from the inventory.

    The spellings come from the data, never from this source: the guard
    files live inside the scan scope, and a spelled form here would be
    an occurrence the guard rejects.
    """
    global _OLD_FORMS
    if _OLD_FORMS is None:
        data = json.loads(
            (NAMING / "inventory.json").read_text(encoding="utf-8"))
        _OLD_FORMS = tuple(dict.fromkeys(
            form.lower() for form in data["old_display_forms"]))
    return _OLD_FORMS


def load_contract() -> Contract:
    """Read the four contract files and the per-family temporary lists."""
    def _read(name: str) -> dict:
        return json.loads((NAMING / name).read_text(encoding="utf-8"))

    temporary = []
    for path in sorted((NAMING / "temporary").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data["entries"]:
            temporary.append((path.name, data["family"], entry))
    return Contract(
        inventory=_read("inventory.json"),
        allowlist=_read("allowlist.json"),
        exclusions=_read("exclusions.json"),
        temporary=temporary,
    )


def tracked_paths() -> list[Path]:
    """Every tracked file of this worktree, as repo-relative paths."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True
    )
    if out.returncode != 0:
        raise RuntimeError("git ls-files failed; the tree walk is broken")
    return [Path(p) for p in out.stdout.split("\0") if p]


def scope_files(contract: Contract):
    """Every tracked file inside the live-scan scope, as repo paths.

    The scan roots and named files come from the inventory; test trees,
    audit fixtures and the contract's own data folder are skipped.
    """
    scan = contract.inventory["scan"]
    roots = tuple(Path(r) for r in scan["roots"])
    files = {Path(f) for f in scan["files"]}
    skip = tuple(Path(s) for s in scan.get("skip", ()))
    for path in tracked_paths():
        if path in files:
            yield path
            continue
        if any(path == s or s in path.parents for s in skip):
            continue
        if any(tree in path.parents for tree in roots):
            yield path


def is_excluded(path: Path, exclusions: dict) -> bool:
    """True when a file sits in a legal, notice or dated-archive tree."""
    posix = path.as_posix()
    for entry in exclusions["entries"]:
        for pattern in entry["paths"]:
            if fnmatch(posix, pattern):
                return True
    return False


def _py_lines_from_text(text: str) -> list[tuple[int, str]]:
    """The string and comment text of Python source, as (lineno, line).

    Code identifiers (import paths, class names, constants) are not
    display text, so only string and comment tokens are searched. An
    unreadable file is the grammar gate's finding, not this one: every
    physical line is searched instead.
    """
    lines = []
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING or (
                fstring_middle is not None and tok.type == fstring_middle
            ) or tok.type == tokenize.COMMENT:
                base = tok.start[0]
                for offset, line in enumerate(tok.string.splitlines()):
                    lines.append((base + offset, line))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        for number, line in enumerate(text.splitlines(), start=1):
            lines.append((number, line))
    return lines


def py_text_lines(path: Path) -> list[tuple[int, str]]:
    """The string and comment text of one Python file, as (lineno, line)."""
    return _py_lines_from_text(path.read_text(encoding="utf-8",
                                              errors="replace"))


def file_lines(path: Path, overrides: dict | None) -> list[tuple[int, str]]:
    """The scanned lines of one in-scope file, as (lineno, line).

    Python files are read through their string and comment tokens; the
    named text suffixes are read as text; anything else (an image, a
    generated metadata blob) is not display text and is skipped, the
    same filter the ticket 01a sweep applied. An override carries the
    content of a temporary copy, so the drift fixtures plant their text
    without touching the tree.
    """
    if overrides is not None:
        text = overrides.get(path.as_posix())
        if text is not None:
            if path.suffix == PY_SUFFIX:
                return _py_lines_from_text(text)
            return list(enumerate(text.splitlines(), start=1))
    if path.suffix == PY_SUFFIX:
        return py_text_lines(path)
    if path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
        text = path.read_text(encoding="utf-8", errors="replace")
        return list(enumerate(text.splitlines(), start=1))
    return []


def occurrences(line: str) -> list[tuple[int, int, str]]:
    """The old-form occurrences on one line, as (start, end, form).

    R2 counts matches, not lines: a line with two occurrences is two.
    """
    found = []
    lowered = line.lower()
    for form in old_forms():
        for match in re.finditer(re.escape(form), lowered):
            found.append((match.start(), match.end(), form))
    return sorted(found)


def _overlaps(span: tuple[int, int], start: int, end: int) -> bool:
    """True when two spans share at least one character."""
    return span[0] < end and start < span[1]


def allowlist_hit(path: Path, line: str, span: tuple[int, int],
                  allowlist: dict) -> bool:
    """True when an allowlisted identifier occurrence covers this span.

    An entry tolerates its identifier only in the files its documented
    context paths match; no spelling is allowlisted globally.
    """
    posix = path.as_posix()
    lowered = line.lower()
    for entry in allowlist["entries"]:
        if not any(fnmatch(posix, pattern)
                   for pattern in entry["context_paths"]):
            continue
        needle = entry["identifier"].lower()
        at = lowered.find(needle)
        while at != -1:
            if _overlaps(span, at, at + len(needle)):
                return True
            at = lowered.find(needle, at + 1)
    return False


def temporary_hits(path: Path, line: str, span: tuple[int, int],
                   temporary: list) -> list:
    """The temporary entries whose files and matches cover this span.

    Package-path entries (scope paths) claim whole trees for the path
    check, not display text, so they never cover a content span.
    """
    posix = path.as_posix()
    hits = []
    for file_name, family, entry in temporary:
        if entry.get("scope") == "paths":
            continue
        in_files = posix in entry.get("files", [])
        in_globs = any(fnmatch(posix, pattern)
                       for pattern in entry.get("paths", []))
        if not (in_files or in_globs):
            continue
        matches = entry.get("matches")
        if matches is None:
            hits.append((file_name, family, entry))
            continue
        lowered = line.lower()
        for needle in matches:
            at = lowered.find(needle.lower())
            claimed = False
            while at != -1:
                if _overlaps(span, at, at + len(needle)):
                    hits.append((file_name, family, entry))
                    claimed = True
                    break
                at = lowered.find(needle.lower(), at + 1)
            if claimed:
                break
    return hits


def avatar_initials_hits(line: str) -> list[tuple[int, int]]:
    """The old-initials spans of one line, when the line is an avatar.

    Unrelated uppercase AD (Azure AD, an AD group) has no avatar mark on
    the line and never matches.
    """
    if "avatar" not in line.lower():
        return []
    return [match.span() for match in AVATAR_INITIALS.finditer(line)]


def pin_violations(contract: Contract, overrides: dict | None) -> list[str]:
    """Every pinned entry of the inventory must carry its literals."""
    misses = []
    for surface in contract.inventory["pinned"]:
        rel = surface["file"]
        if overrides is not None and rel in overrides:
            content = overrides[rel]
        else:
            path = ROOT / rel
            if not path.is_file():
                misses.append(f"pin {surface['surface']}: {rel} is missing")
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
        for needle in surface["must_contain"]:
            if needle not in content:
                misses.append(
                    f"pin {surface['surface']}: {rel} lost {needle!r}"
                )
    return misses


def exact_pin_violations(overrides: dict | None) -> list[str]:
    """The two strict pins the two-literal guard carried, kept strict."""
    misses = []
    title = f"# {APPROVED_NAME}"
    if overrides is not None and "README.md" in overrides:
        readme = overrides["README.md"]
    else:
        readme = (ROOT / "README.md").read_text(encoding="utf-8",
                                                errors="replace")
    heads = readme.splitlines()
    if not heads or heads[0] != title:
        misses.append(f"pin README title: the first line is not {title!r}")
    face_constant = f"export const AGENT_NAME = '{APPROVED_NAME}';"
    if overrides is not None and "frontend/src/face/name.ts" in overrides:
        face = overrides["frontend/src/face/name.ts"]
    else:
        face = (ROOT / "frontend" / "src" / "face" / "name.ts").read_text(
            encoding="utf-8", errors="replace")
    if face_constant not in face:
        misses.append(
            "pin agent face constant: frontend/src/face/name.ts lost "
            f"{face_constant}"
        )
    return misses


def display_violations(contract: Contract,
                       overrides: dict | None) -> list[str]:
    """Old display forms on production source and live documents.

    Every occurrence must sit in an allowlisted context or under one
    temporary entry; anything else is rejected.
    """
    misses = []
    seen = set()
    for path in scope_files(contract):
        if is_excluded(path, contract.exclusions):
            continue
        for number, line in file_lines(path, overrides):
            for span in occurrences(line):
                if allowlist_hit(path, line, span, contract.allowlist):
                    continue
                if temporary_hits(path, line, span, contract.temporary):
                    continue
                key = (path.as_posix(), number)
                if key in seen:
                    continue
                seen.add(key)
                misses.append(
                    f"{path.as_posix()}:{number}: old display form outside "
                    f"every exception: {line.strip()[:90]!r}"
                )
    return misses


def avatar_violations(contract: Contract,
                      overrides: dict | None) -> list[str]:
    """The old initials in avatar contexts, outside the declared entries."""
    misses = []
    for path in scope_files(contract):
        if is_excluded(path, contract.exclusions):
            continue
        for number, line in file_lines(path, overrides):
            for span in avatar_initials_hits(line):
                if temporary_hits(path, line, span, contract.temporary):
                    continue
                misses.append(
                    f"{path.as_posix()}:{number}: old initials in an avatar "
                    f"context: {line.strip()[:90]!r}"
                )
    return misses


def initials_contract_violations(contract: Contract) -> list[str]:
    """Avatar entries declare the old initials and expect the approved ones."""
    misses = []
    for file_name, family, entry in contract.temporary:
        if not entry.get("initials"):
            continue
        if entry["initials"] != OLD_INITIALS:
            misses.append(
                f"{family}: entry {entry['surface']!r} declares initials "
                f"{entry['initials']!r}, not the retired ones"
            )
        if entry.get("expected_initials") != APPROVED_INITIALS:
            misses.append(
                f"{family}: entry {entry['surface']!r} expects "
                f"{entry.get('expected_initials')!r}, not {APPROVED_INITIALS!r}"
            )
    return misses


def path_miss(posix: str, contract: Contract) -> str | None:
    """Why an old-form path is not allowed to keep its name, or None.

    A path survives only when exactly one temporary package-path entry
    claims it, or exactly one allowlist entry names it (a retained
    launcher, a test of a retained launcher, a legal file), or it sits
    in a dated archive.
    """
    path = Path(posix)
    lowered = posix.lower()
    if not any(form in lowered for form in old_forms()):
        return None
    if is_excluded(path, contract.exclusions):
        return None
    claims = sorted({family for _f, family, entry in contract.temporary
                     if any(fnmatch(posix, pattern)
                            for pattern in entry.get("paths", []))})
    allowed = sorted({pattern
                      for entry in contract.allowlist["entries"]
                      for pattern in entry.get("paths", [])
                      if fnmatch(posix, pattern)})
    if len(claims) == 1 and not allowed:
        return None
    if len(claims) == 0 and len(allowed) == 1:
        return None
    return (
        f"{posix}: claimed by {claims or 'nothing'}, "
        f"path-allowlisted by {allowed}"
    )


def path_violations(contract: Contract) -> list[str]:
    """Old-form tracked paths must be retained, excluded or temporary."""
    misses = []
    for path in tracked_paths():
        miss = path_miss(path.as_posix(), contract)
        if miss is not None:
            misses.append(miss)
    return misses


def _em_iter_files():
    """The em-dash walk: the live roots by filesystem order, plus files."""
    for root in EM_ROOTS:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in EM_SKIP_DIRS for part in path.relative_to(ROOT).parts):
                continue
            yield path
    yield from EM_FILES


def em_dash_violations(overrides: dict | None = None) -> list[str]:
    """U+2014 anywhere in its live-tree scope; the docs trees stay out.

    The scope is the one the guard before this one walked: src, tools,
    scripts, frontend/src and tests, plus the five named root files.
    Dated records under docs/ are history, not live copy.
    """
    hits = []
    seen = set()
    for path in _em_iter_files():
        rel_posix = path.relative_to(ROOT).as_posix()
        if rel_posix.startswith(EM_ARCHIVE_PREFIXES) or rel_posix.startswith("docs"):
            continue
        text = None
        if overrides is not None:
            text = overrides.get(rel_posix)
        if text is None:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                hits.append(f"{rel_posix}: unreadable ({exc})")
                continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if EM_DASH not in line:
                continue
            key = (rel_posix, lineno)
            if key in seen:
                continue
            seen.add(key)
            hits.append(f"{rel_posix}:{lineno}")
    return hits


def check(overrides: dict | None = None) -> list[str]:
    """Every guard rule at once; the violations, empty on a clean tree.

    The overrides carry temporary copies of live files, so the negative
    fixtures plant drift without touching the tree.
    """
    contract = load_contract()
    problems = []
    problems += pin_violations(contract, overrides)
    problems += exact_pin_violations(overrides)
    problems += display_violations(contract, overrides)
    problems += avatar_violations(contract, overrides)
    problems += initials_contract_violations(contract)
    problems += path_violations(contract)
    problems += em_dash_violations(overrides)
    return problems


def count(overrides: dict | None = None) -> dict:
    """The R2 count over tracked text and tracked paths.

    Occurrences are regex matches over the tracked text of the live
    scan scope, classified by the same rules the guard enforces;
    old-form tracked paths are counted separately.
    """
    contract = load_contract()
    scanned = 0
    total = allow = temp = unclass = 0
    for path in scope_files(contract):
        scanned += 1
        if is_excluded(path, contract.exclusions):
            continue
        for _number, line in file_lines(path, overrides):
            for span in occurrences(line):
                total += 1
                if allowlist_hit(path, line, span, contract.allowlist):
                    allow += 1
                elif temporary_hits(path, line, span, contract.temporary):
                    temp += 1
                else:
                    unclass += 1
    paths_total = sum(
        1 for path in tracked_paths()
        if any(form in path.as_posix().lower() for form in old_forms())
    )
    return {
        "scanned_files": scanned,
        "occurrences": total,
        "allowlisted": allow,
        "temporary": temp,
        "unclassified": unclass,
        "old_form_paths": paths_total,
    }


def _report() -> int:
    """Print the count report and its verdict against the recorded baseline."""
    live = count()
    keys = ("scanned_files", "occurrences", "allowlisted", "temporary",
            "unclassified", "old_form_paths")
    print("Nexuus Bot naming count report (R2 method: regex matches over "
          "tracked text; tracked paths separately)")
    print(f"scanned tracked files: {live['scanned_files']}")
    print(
        f"old-form content occurrences: {live['occurrences']} "
        f"(allowlisted {live['allowlisted']}, temporary {live['temporary']}, "
        f"unclassified {live['unclassified']})"
    )
    print(f"old-form tracked paths: {live['old_form_paths']}")
    print(
        f"recorded baseline ({RECORDED_BASELINE['recorded_by']}): "
        f"{RECORDED_BASELINE['scanned_files']} files, "
        f"{RECORDED_BASELINE['occurrences']} occurrences, "
        f"{RECORDED_BASELINE['allowlisted']} allowlisted, "
        f"{RECORDED_BASELINE['temporary']} temporary, "
        f"{RECORDED_BASELINE['unclassified']} unclassified, "
        f"{RECORDED_BASELINE['old_form_paths']} old-form paths"
    )
    if all(live[key] == RECORDED_BASELINE[key] for key in keys):
        print("baseline: MATCH")
    else:
        print("baseline: DRIFT (a rename ticket moved the counts; "
              "record the new numbers in the ticket's evidence)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the guard, or print the count report with --report."""
    parser = argparse.ArgumentParser(
        description="The Nexuus Bot naming guard over tools/naming/")
    parser.add_argument(
        "--report", action="store_true",
        help="print the R2 count report instead of the verdict")
    args = parser.parse_args(argv)
    if args.report:
        return _report()
    problems = check()
    if problems:
        print("NAMING GUARD FAIL")
        for problem in problems[:40]:
            print(f"FAIL {problem}")
        if len(problems) > 40:
            print(f"... and {len(problems) - 40} more")
        return 1
    print("NAMING GUARD PASS (pins, display forms, avatar initials, "
          "tracked paths, em dash)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
