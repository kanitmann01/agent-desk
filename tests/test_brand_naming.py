"""The full Nexuus Bot naming guard: the contract in tools/naming/, enforced.

Spec 032, ticket 01b (issue 355); the data is ticket 01a (issue 354).
This file replaces the old two-literal brand guard: every pinned
surface carries the approved literals; every old display form on
production source and live documents sits in a temporary-list entry or
an allowlisted context; the old AD initials are rejected in avatar
contexts, and after tickets 02 and 03 no temporary entry declares them;
tracked path names keep to the retained forms; the
U+2014 ban keeps its live-tree scope; the count report implements the
R2 method over tracked text and tracked paths; and the negative
fixtures prove the guard fails on a missing new name, an old wordmark,
old initials in an avatar context, an unapproved compact identifier and
injected drift in a live file.

The overrides each fixture passes carry the content of a temporary
copy, so no drift is ever written into the tree. The tests read the
tracked tree and the contract data and start no process beyond git:
no desk, no walk and no application.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "naming_guard.py"


def _guard():
    """Import tools/naming_guard.py by path so the test needs no sys.path edit.

    The module registers itself before it executes: the dataclass in it
    resolves its own module through sys.modules.
    """
    if "naming_guard" in sys.modules:
        return sys.modules["naming_guard"]
    spec = importlib.util.spec_from_file_location("naming_guard", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["naming_guard"] = module
    spec.loader.exec_module(module)
    return module


g = _guard()


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


# --- the untouched tree is green: every rule passes together ---


def test_the_guard_passes_on_the_untouched_tree():
    """Every guard rule passes with every temporary-list entry in place."""
    assert g.check() == []


# --- the pins: the approved name on every surface that carries it ---


def test_every_pinned_surface_carries_the_new_name():
    """Each pinned entry of the inventory holds its approved literals."""
    inventory = json.loads(_read("tools/naming/inventory.json"))
    assert inventory["approved_name"] == "Nexuus Bot"
    assert inventory["approved_initials"] == "NB"
    for surface in inventory["pinned"]:
        content = _read(surface["file"])
        for needle in surface["must_contain"]:
            assert needle in content, (
                f"{surface['surface']}: {surface['file']} lost {needle!r}"
            )


def test_readme_uses_the_approved_product_name():
    """The README title is exactly the approved heading (the strict pin)."""
    first_line = _read("README.md").splitlines()[0]
    assert first_line == "# Nexuus Bot"


def test_agent_face_keeps_the_approved_name():
    """The face constant is exactly the approved assignment (the strict pin)."""
    assert "export const AGENT_NAME = 'Nexuus Bot';" in _read(
        "frontend/src/face/name.ts")


def test_the_avatar_entries_expect_the_approved_initials():
    """No temporary entry may still declare old avatar initials."""
    contract = g.load_contract()
    assert g.initials_contract_violations(contract) == []
    declared = [entry for _f, _fam, entry in contract.temporary
                if entry.get("initials")]
    assert not declared, (
        "an avatar entry still declares old initials: "
        "tickets 02 and 03 renamed both avatar surfaces"
    )


def test_a_broken_avatar_expectation_fails_the_contract():
    """An avatar entry that expects anything but NB is a violation."""
    contract = g.load_contract()
    broken = g.Contract(
        inventory=contract.inventory,
        allowlist=contract.allowlist,
        exclusions=contract.exclusions,
        temporary=[("fake.json", "server-pages", {
            "surface": "fake avatar", "files": ["src/x.py"],
            "initials": "AD", "expected_initials": "XY",
        })],
    )
    misses = g.initials_contract_violations(broken)
    assert len(misses) == 1 and "XY" in misses[0]


# --- old display forms rejected outside the temporary lists ---


def test_an_old_wordmark_fails_the_guard():
    """A spaced old wordmark planted in production source is rejected."""
    planted = {
        "frontend/src/face/brain.ts":
            "export const step = 1;\n// The Agent Desk assistant greets you.\n",
    }
    problems = g.check(planted)
    assert any("frontend/src/face/brain.ts" in p and "display form" in p
               for p in problems), problems


def test_an_unapproved_compact_identifier_fails_the_guard():
    """A compact old-form identifier no entry documents is rejected."""
    planted = {
        "frontend/src/marketplace/CatalogPage.tsx":
            "export const WIDGET_CACHE_KEY = \"agentdesk.widget.cache.v1\";\n",
    }
    problems = g.check(planted)
    assert any("frontend/src/marketplace/CatalogPage.tsx" in p
               for p in problems), problems


def test_an_old_display_form_on_a_temporary_surface_stays_tolerated():
    """Rail.tsx carries the old wordmark today and only its ticket clears it."""
    contract = g.load_contract()
    rail = Path("frontend/src/dashboard/Rail.tsx")
    for number, line in g.file_lines(rail, None):
        for span in g.occurrences(line):
            assert g.allowlist_hit(rail, line, span,
                                   contract.allowlist) or g.temporary_hits(
                rail, line, span, contract.temporary), (
                f"Rail.tsx:{number} is no longer tolerated by any entry; "
                "ticket 03 should have renamed it"
            )


# --- the old initials: rejected in avatar contexts only ---


def test_the_avatar_matcher_knows_the_three_live_shapes():
    """Server HTML, JSX and the committed bundle's children all match."""
    shapes = (
        '<div class="user"><span class="avatar" aria-hidden="true" '
        'title="Agent Desk">AD</span>',
        '<span className="avatar" aria-hidden="true" title="Agent Desk">AD'
        "</span>",
        'e.jsxs("span",{className:"avatar","aria-hidden":"true",'
        'title:"Agent Desk",children:"AD"}),e.jsxs("div",{children:',
    )
    for shape in shapes:
        assert g.avatar_initials_hits(shape), shape
    assert g.avatar_initials_hits("Azure AD groups and an AD-domain example") == []
    assert g.avatar_initials_hits('<span class="avatar" title="Agent Desk">NB</span>') == []


def test_old_initials_in_an_avatar_context_fail_the_guard():
    """An avatar AD planted outside the declared entries is rejected."""
    planted = {
        "frontend/src/dashboard/TrackerCard.tsx":
            '<span className="avatar" aria-hidden="true" title="Nexuus Bot">'
            "AD</span>\n",
    }
    problems = g.check(planted)
    assert any("frontend/src/dashboard/TrackerCard.tsx" in p
               and "avatar" in p for p in problems), problems


def test_approved_initials_in_an_avatar_context_pass():
    """The same avatar line with the approved initials is clean."""
    planted = {
        "frontend/src/dashboard/TrackerCard.tsx":
            '<span className="avatar" aria-hidden="true" title="Nexuus Bot">'
            "NB</span>\n",
    }
    problems = g.check(planted)
    assert not any("frontend/src/dashboard/TrackerCard.tsx" in p
                   for p in problems), problems


def test_unrelated_uppercase_ad_is_never_rejected():
    """Azure AD and AD-group prose is not an avatar and never flagged."""
    planted = {
        "frontend/src/face/brain.ts":
            "// Syncs Azure AD groups; the AD domain stays untouched.\n",
    }
    problems = g.check(planted)
    assert not any("avatar" in p for p in problems), problems


# --- allowlist entries accepted only in their documented contexts ---


def _context_probe_path(pattern: str) -> Path:
    """A concrete path inside one context pattern."""
    return Path(pattern.replace("*", "probe"))


def test_each_allowlist_entry_is_accepted_only_in_its_documented_context():
    """Every entry admits its identifier in its context and nowhere else."""
    contract = g.load_contract()
    candidates = [
        "frontend/src/face/brain.ts",
        "frontend/src/dashboard/TrackerCard.tsx",
        "frontend/src/marketplace/CatalogPage.tsx",
        "src/agentdesk/excel/core.py",
        "src/agentdesk/server/health.py",
        "tools/probe_tool.py",
        "scripts/probe_script.py",
        "registry/probe.md",
        "docs/ops/probe.md",
        "docs/licensing.md",
        "docs/readme/README.md",
    ]
    for entry in contract.allowlist["entries"]:
        identifier = entry["identifier"]
        span = (0, len(identifier))
        in_context = _context_probe_path(entry["context_paths"][0])
        assert g.allowlist_hit(in_context, identifier, span,
                               contract.allowlist), (
            f"{identifier!r}: not accepted inside its own documented context "
            f"{entry['context_paths'][0]!r}"
        )
        outside = [
            candidate for candidate in candidates
            if not g.allowlist_hit(Path(candidate), identifier, span,
                                   contract.allowlist)
            and not g.temporary_hits(Path(candidate), identifier, span,
                                     contract.temporary)
        ]
        assert outside, (
            f"{identifier!r}: accepted on every probed surface; its context "
            "is not exact"
        )


# --- tracked path names ---


def test_tracked_paths_keep_the_retained_forms():
    """Every old-form tracked path is retained, excluded or temporary."""
    assert g.path_violations(g.load_contract()) == []


def test_a_new_old_form_path_would_be_rejected():
    """A path outside the retained forms has no claim and is a violation."""
    contract = g.load_contract()
    assert g.path_miss("docs/ops/agent-desk-guide.md", contract) is not None
    assert g.path_miss("frontend/assets/agentdesk-hero.png", contract) is not None


def test_the_retained_path_forms_stay_allowed():
    """A retained launcher, its test and the package tree keep their names."""
    contract = g.load_contract()
    assert g.path_miss("tools/agent-desk.cmd", contract) is None
    assert g.path_miss("tests/test_agent_desk_cmd.py", contract) is None
    assert g.path_miss("src/agentdesk/server/pages.py", contract) is None
    assert g.path_miss("docs/evidence/x/agent-desk-notes.md", contract) is None


# --- the em dash keeps its existing live-tree scope ---


def test_no_live_file_carries_the_banned_em_dash():
    """The em dash is banned on the live trees; the found list stays empty."""
    assert g.em_dash_violations() == [], (
        "the em dash is banned on live surfaces; "
        "found: " + ", ".join(g.em_dash_violations()[:10])
    )


def test_the_em_dash_scope_keeps_the_old_live_trees():
    """src and tests are scanned; the docs trees and records stay out."""
    dash = " // note: planted " + chr(0x2014) + " here\n"
    planted = {
        "src/agentdesk/config.py": dash,
        "tests/test_brand_naming.py": dash,
        "docs/ops/distribution.md": dash,
        "docs/docstrings.md": dash,
    }
    hits = g.em_dash_violations(planted)
    assert any(h.startswith("src/agentdesk/config.py") for h in hits), hits
    assert any(h.startswith("tests/test_brand_naming.py") for h in hits), hits
    assert not any(h.startswith("docs/") for h in hits), hits


# --- the negative fixtures and the injected drift ---


def test_a_missing_new_name_fails_the_guard():
    """A pinned surface that loses the approved name fails the guard."""
    readme = _read("README.md")
    swapped = readme.replace("# Nexuus Bot\n", "# Another Product\n", 1)
    assert swapped != readme, "the README title was not found to swap"
    problems = g.check({"README.md": swapped})
    assert any("README.md" in p and "pin" in p for p in problems), problems


def test_injected_drift_in_a_live_file_fails_the_guard():
    """Drift planted in a temporary copy of a live file fails the guard.

    The copy lives only in the override dict: the tree keeps the clean
    bytes, and the guard still reports the live surface by its real path.
    """
    drifted = _read("README.md") + "\nAgent Desk remains available in legacy builds.\n"
    problems = g.check({"README.md": drifted})
    assert any("README.md" in p and "display form" in p for p in problems), (
        problems
    )
    assert g.check() == [], "the drift leaked into the tree"


# --- the count report: the R2 method over tracked text and paths ---


def test_the_recorded_baseline_is_the_measured_notes_baseline():
    """The report's recorded before-numbers are the ticket 01a sweep's."""
    assert g.RECORDED_BASELINE == {
        "recorded_by": "ticket 01a sweep (issue 354), pull request 375",
        "scanned_files": 466,
        "occurrences": 835,
        "allowlisted": 660,
        "temporary": 175,
        "unclassified": 0,
        "old_form_paths": 301,
    }


def test_the_count_report_satisfies_the_r2_method_on_this_tree():
    """The classification adds up and nothing is left unexplained."""
    live = g.count()
    assert live["allowlisted"] + live["temporary"] + live["unclassified"] == \
        live["occurrences"]
    assert live["unclassified"] == 0
    assert live["scanned_files"] > 100, "the scan scope collapsed"
    assert live["old_form_paths"] > 100, "the tracked-path count collapsed"


def test_occurrences_count_matches_not_lines():
    """R2 counts regex matches: one line can carry several occurrences."""
    assert len(g.occurrences("a agent-desk b agent-desk c")) == 2
    assert len(g.occurrences("AGENTDESK_DATA and agentdesk.railCollapsed")) == 2
    assert g.occurrences("the desk, the rail, the ledger") == []


def test_the_count_moves_with_injected_content():
    """Planted occurrences move the totals without touching the tree."""
    base = g.count()
    planted = g.count({
        "frontend/src/face/brain.ts": "// agentdesk agentdesk agentdesk\n",
    })
    assert planted["occurrences"] == base["occurrences"] + 3
    assert planted["unclassified"] == base["unclassified"] + 3
    assert planted["allowlisted"] == base["allowlisted"]
    assert planted["old_form_paths"] == base["old_form_paths"]
