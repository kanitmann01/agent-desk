"""The name contract as data: well formed and complete enough for 01b.

Ticket 01a of Spec 032 (issue 354). The guard that enforces this contract
is ticket 01b (issue 355); this ticket adds the data and proves it is
readable and complete. Nothing is renamed and nothing is enforced here.

The checks read only the data files under tools/naming/ and the tracked
tree. They start no desk, no walk and no application.
"""

import io
import json
import re
import subprocess
import tokenize
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMING = ROOT / "tools" / "naming"

# The approved literals (Spec 032, Implementation Decisions).
APPROVED_NAME = "Nexuus Bot"
APPROVED_INITIALS = "NB"

# The nine allowlist categories, in the spec's order.
CATEGORIES = (
    "import-compatibility",
    "data-and-local-state",
    "environment-and-tooling",
    "browser-and-secrets",
    "wire-and-recorded-identity",
    "commands-and-launchers",
    "public-distribution",
    "compliance-metadata",
    "legal-text",
)

FAMILIES = (
    ("server-pages", 356),
    ("spa-and-bundle", 357),
    ("generated-output", 358),
    ("readme-family", 359),
    ("demo-and-glossary", 359),
    ("frontend-setup", 359),
    ("operator-guides", 360),
    ("bundle-metadata", 361),
    ("python-package", 362),
    ("frontend-package", 363),
)

# The three README screenshots, from the spec and the provenance note.
RETAINED_SCREENSHOTS = (
    "docs/readme/dashboard.png",
    "docs/readme/memory.png",
    "docs/readme/marketplace.png",
)

# The old display forms, rejected case-insensitively (the old AD initials
# are an avatar-context rule that ticket 01b reads from the entries that
# carry an initials field).
FORMS = ("agent desk", "agentdesk", "agent-desk", "agent_desk")

TEXT_SUFFIXES = {
    ".md", ".txt", ".json", ".toml", ".yml", ".yaml", ".html", ".css",
    ".js", ".ts", ".tsx", ".jsx", ".cmd", ".command", ".ps1", ".svg",
    ".xml", ".ini", ".cfg",
}
TEXT_NAMES = {".gitignore", ".gitattributes"}
PY_SUFFIX = ".py"
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache", ".venv", ".git"}


def _load(name):
    return json.loads((NAMING / name).read_text(encoding="utf-8"))


def _temporary_files():
    return sorted((NAMING / "temporary").glob("*.json"))


def _all_temporary_entries():
    for path in _temporary_files():
        data = _load(path.relative_to(NAMING).as_posix())
        for entry in data["entries"]:
            yield path.name, data["family"], entry


def _tracked_paths():
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True
    )
    assert out.returncode == 0, "git ls-files failed; the tree walk is broken"
    return [Path(p) for p in out.stdout.split("\0") if p]


def _iter_scope_files(scan):
    """Every tracked file inside the live-scan scope, as repo paths."""
    roots = tuple(Path(r) for r in scan["roots"])
    files = {Path(f) for f in scan["files"]}
    skip = tuple(Path(s) for s in scan.get("skip", ()))
    for path in _tracked_paths():
        if path in files:
            yield path
            continue
        if any(path == s or s in path.parents for s in skip):
            continue
        if any(root in path.parents for root in roots):
            yield path


def _is_excluded(path, exclusions):
    posix = path.as_posix()
    for entry in exclusions["entries"]:
        for pattern in entry["paths"]:
            if fnmatch(posix, pattern):
                return True
    return False


def _py_text_lines(path):
    """The string and comment text of a Python file, as (lineno, text).

    Code identifiers (import paths, class names, constants) are not display
    text, so only string and comment tokens are searched.
    """
    lines = []
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING or (
                fstring_middle is not None and tok.type == fstring_middle
            ) or tok.type == tokenize.COMMENT:
                base = tok.start[0]
                for offset, line in enumerate(tok.string.splitlines()):
                    lines.append((base + offset, line))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        # An unreadable file is the grammar gate's finding, not this one.
        for number, line in enumerate(text.splitlines(), start=1):
            lines.append((number, line))
    return lines


def _occurrences(line):
    """The old-form occurrences on one line, as (start, end, form)."""
    found = []
    lowered = line.lower()
    for form in FORMS:
        for match in re.finditer(re.escape(form), lowered):
            found.append((match.start(), match.end(), form))
    return sorted(found)


def _overlaps(span, start, end):
    return span[0] < end and start < span[1]


def _allowlist_hit(path, line, span, allowlist):
    """True when an allowlisted identifier occurrence covers this span."""
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


def _temporary_hits(path, line, span, temporary):
    """The temporary entries whose files and matches cover this span."""
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


# --- well formed: every file parses and every entry carries its fields ---


def test_the_contract_files_exist_and_parse():
    for name in ("inventory.json", "allowlist.json", "exclusions.json",
                 "retained-media.json"):
        data = _load(name)
        assert isinstance(data, dict), f"{name} is not an object"


def test_every_family_file_exists_with_family_and_issue():
    inventory = _load("inventory.json")
    defined = {family["family"]: family for family in inventory["families"]}
    assert set(defined) == {name for name, _issue in FAMILIES}
    for name, issue in FAMILIES:
        family = defined[name]
        assert family["issue"] == issue, f"{name} names the wrong issue"
        path = NAMING / "temporary" / f"{name}.json"
        assert path.is_file(), f"the temporary file for {name} is missing"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["family"] == name
        assert data["issue"] == issue
        for entry in data["entries"]:
            assert entry.get("surface"), f"{name}: an entry has no surface"
            assert entry.get("issue") == issue, (
                f"{name}: an entry names the wrong clearing issue"
            )
            assert entry.get("files") or entry.get("paths"), (
                f"{name}: entry {entry['surface']!r} names no files"
            )


def test_every_temporary_entry_covers_at_least_one_tracked_file():
    tracked = {p.as_posix() for p in _tracked_paths()}
    for file_name, family, entry in _all_temporary_entries():
        named = list(entry.get("files", [])) + [
            pattern for pattern in entry.get("paths", [])
            if "*" not in pattern
        ]
        matches = [c for c in named if c in tracked]
        globs = [c for c in entry.get("paths", []) if "*" in c]
        assert matches or globs, (
            f"{family}: entry {entry['surface']!r} matches no tracked file"
        )


def test_every_allowlist_entry_carries_its_exact_context():
    allowlist = _load("allowlist.json")
    seen = set()
    for entry in allowlist["entries"]:
        label = f"{entry.get('identifier')!r}"
        assert entry.get("category") in CATEGORIES, (
            f"{label}: unknown allowlist category"
        )
        assert entry.get("identifier"), f"{label}: no identifier"
        assert entry.get("context"), f"{label}: no exact context"
        assert entry.get("context_paths"), f"{label}: no context paths"
        assert entry.get("purpose"), f"{label}: no purpose"
        assert entry.get("owner"), f"{label}: no owner"
        assert entry.get("review_trigger"), f"{label}: no review trigger"
        # One entry per identifier and context: the same spelling may hold
        # two contracts (health identity and audit actor share agent-desk),
        # so the key includes the context paths.
        key = (entry["category"], entry["identifier"],
               tuple(entry["context_paths"]))
        assert key not in seen, f"{label}: duplicated in {entry['category']}"
        seen.add(key)


def test_exclusions_name_legal_instruments_notices_and_archives():
    exclusions = _load("exclusions.json")
    kinds = {entry["kind"]: entry for entry in exclusions["entries"]}
    assert set(kinds) == {"legal-instrument", "notice-file", "dated-archive"}
    for entry in exclusions["entries"]:
        assert entry["paths"], f"{entry['kind']}: no paths"
        assert entry.get("reason"), f"{entry['kind']}: no reason"
        assert entry.get("pinned_as"), f"{entry['kind']}: not pinned"
    legal = " ".join(kinds["legal-instrument"]["paths"])
    assert "LICENSE" in legal, "the licence instruments are not excluded"
    notices = " ".join(kinds["notice-file"]["paths"])
    assert "THIRD-PARTY-NOTICES.md" in notices, (
        "the generated notices are not excluded"
    )
    archives = " ".join(kinds["dated-archive"]["paths"])
    for tree in ("docs/evidence", "docs/tickets", "docs/plans",
                 "docs/ideas", "docs/research", "docs/superpowers",
                 "docs/plugins", "archive"):
        assert tree in archives, f"the dated tree {tree} is not excluded"


def test_retained_media_names_the_three_readme_screenshots():
    media = _load("retained-media.json")
    by_path = {entry["path"]: entry for entry in media["entries"]}
    assert set(by_path) == set(RETAINED_SCREENSHOTS), (
        "the retained-media list must name exactly the three screenshots"
    )
    for path in RETAINED_SCREENSHOTS:
        entry = by_path[path]
        assert (ROOT / path).is_file(), f"{path} does not exist"
        assert entry.get("captured") == "2026-11-25", (
            f"{path}: the captured date is missing"
        )
        trigger = entry.get("review_trigger", "").lower()
        assert "closeout" in trigger and "retake" in trigger, (
            f"{path}: the review trigger is not the closeout retake"
        )


def test_pinned_surfaces_already_carry_the_new_name():
    inventory = _load("inventory.json")
    assert inventory["approved_name"] == APPROVED_NAME
    assert inventory["approved_initials"] == APPROVED_INITIALS
    for surface in inventory["pinned"]:
        assert surface["family"] in {name for name, _ in FAMILIES}
        assert surface["status"] == "nexuus-bot"
        for needle in surface["must_contain"]:
            path = ROOT / surface["file"]
            assert path.is_file(), f"{surface['file']} does not exist"
            assert needle in path.read_text(encoding="utf-8",
                                            errors="replace"), (
                f"{surface['file']} lost {needle!r}"
            )


def test_temporary_entries_declare_the_old_avatar_initials():
    """Every avatar entry still on the lists declares the retired
    initials and expects the approved ones, and the server pages are no
    longer declared: ticket 02 (issue 356) renamed the server shell's
    avatar, so its old declaration has left the temporary list."""
    avatars = [
        entry for _file, _family, entry in _all_temporary_entries()
        if entry.get("initials")
    ]
    for entry in avatars:
        assert entry.get("initials") == "AD"
        assert entry.get("expected_initials") == APPROVED_INITIALS
        assert "avatar" in entry["surface"].lower()
    named = {f for entry in avatars for f in entry["files"]}
    assert "src/nexuusbot/server/pages.py" not in named, (
        "the server avatar carries the approved initials; its declaration "
        "should have left the temporary list"
    )


# --- complete: every old-form occurrence in the live trees is classified ---


def _unclassified_hits():
    inventory = _load("inventory.json")
    allowlist = _load("allowlist.json")
    exclusions = _load("exclusions.json")
    temporary = list(_all_temporary_entries())
    misses = []
    checked = 0
    for path in _iter_scope_files(inventory["scan"]):
        if _is_excluded(path, exclusions):
            continue
        if path.suffix == PY_SUFFIX:
            lines = _py_text_lines(path)
        elif path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = list(enumerate(text.splitlines(), start=1))
        else:
            continue
        for number, line in lines:
            for span in _occurrences(line):
                checked += 1
                if _allowlist_hit(path, line, span, allowlist):
                    continue
                hits = _temporary_hits(path, line, span, temporary)
                if len(hits) == 1:
                    continue
                where = f"{path.as_posix()}:{number}"
                if len(hits) > 1:
                    misses.append(
                        f"{where}: {line.strip()[:90]!r} is claimed by "
                        + ", ".join(sorted({f for f, _fam, _e in hits}))
                    )
                else:
                    misses.append(
                        f"{where}: {line.strip()[:90]!r} is unclassified"
                    )
    assert checked > 100, (
        f"the scan saw only {checked} occurrences; the scope is broken"
    )
    return misses


def test_every_old_form_occurrence_in_live_trees_is_classified():
    misses = _unclassified_hits()
    assert misses == [], (
        f"{len(misses)} old-form occurrence(s) are not named by exactly one "
        "temporary entry (or an allowlist context or exclusion): "
        + " | ".join(misses[:15])
    )


def test_every_old_form_tracked_path_is_classified():
    inventory = _load("inventory.json")
    exclusions = _load("exclusions.json")
    allowlist = _load("allowlist.json")
    temporary = list(_all_temporary_entries())
    misses = []
    for path in _tracked_paths():
        posix = path.as_posix()
        lowered = posix.lower()
        if not any(form in lowered for form in FORMS):
            continue
        if _is_excluded(path, exclusions):
            continue
        claims = []
        for file_name, family, entry in temporary:
            if any(fnmatch(posix, pattern)
                   for pattern in entry.get("paths", [])):
                claims.append(family)
        allowed_paths = {
            pattern
            for entry in allowlist["entries"]
            for pattern in entry.get("paths", [])
            if fnmatch(posix, pattern)
        }
        if len(claims) == 1 and not allowed_paths:
            continue
        if len(claims) == 0 and len(allowed_paths) == 1:
            continue
        misses.append(
            f"{posix}: claimed by {claims or 'nothing'}, "
            f"path-allowlisted by {sorted(allowed_paths)}"
        )
    assert misses == [], (
        "old-form tracked paths must be named once: " + " | ".join(misses[:15])
    )
