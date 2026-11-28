"""Reading checks for the operator guides and the dependent specs.

Ticket 06 of Spec 032 (issue 360). Each check reads a live document the
way its story reads it: the prose names the product Nexuus Bot, the
retained distribution, marketplace and legal contracts keep their exact
spellings, the marketplace guide states the runtime data root and the
bundle install folder as two separate facts, no instruction promises an
installer or an executable the build does not make, and Specs 030 and
031 start from the renamed vocabulary. The checks read tracked files
only: no desk, no walk, no application.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION = ROOT / "docs" / "ops" / "distribution.md"
MARKETPLACE = ROOT / "docs" / "ops" / "marketplace-operator.md"
LICENSING = ROOT / "docs" / "licensing.md"
SPEC_030 = ROOT / "specs" / "030-one-shell-and-the-face-on-every-wait.md"
SPEC_031 = ROOT / "specs" / "031-three-presentation-templates.md"
TEMPORARY = ROOT / "tools" / "naming" / "temporary" / "operator-guides.json"

OLD_FORMS = ("Agent Desk", "AgentDesk", "agentdesk", "agent-desk",
             "agent_desk")


def _text(path):
    return path.read_text(encoding="utf-8")


def _guard():
    """Import the naming guard by path, the way its own tests do."""
    if "naming_guard" in sys.modules:
        return sys.modules["naming_guard"]
    spec = importlib.util.spec_from_file_location(
        "naming_guard", ROOT / "tools" / "naming_guard.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["naming_guard"] = module
    spec.loader.exec_module(module)
    return module


def test_the_distribution_guide_names_the_product_and_keeps_contracts():
    text = _text(DISTRIBUTION)
    assert "The product is Nexuus Bot." in text
    assert "docs/ops/compatibility.md" in text
    for contract in (
        "AgentDesk.exe",
        "dist/agent-desk",
        "\\\\fileserver\\AgentDesk\\stable",
        "agent-desk.zip",
        'BinaryName="AgentDesk.exe"',
        "%LOCALAPPDATA%\\AgentDesk",
        "AGENTDESK_DATA",
    ):
        assert contract in text, f"the guide lost the contract {contract!r}"
    # The AppLocker template's rule name, description and ProductName
    # condition say Nexuus Bot (ticket 07, issue 361) while the
    # BinaryName condition keeps the executable contract above.
    for label in (
        'Name="Nexuus Bot - signed publisher"',
        'Description="Allow Nexuus Bot from its per-user install folder"',
        'ProductName="Nexuus Bot"',
    ):
        assert label in text, f"the AppLocker template lost its label: {label!r}"
    for label in (
        'Name="Agent Desk - signed publisher"',
        'Description="Allow Agent Desk from its per-user install folder"',
        'ProductName="Agent Desk"',
    ):
        assert label not in text, f"the AppLocker template still says: {label!r}"
    assert "1. Close Nexuus Bot." in text
    assert "Close Agent Desk" not in text


def test_the_distribution_guide_promises_only_what_the_build_makes():
    text = _text(DISTRIBUTION)
    assert "No installer." in text
    flat = " ".join(text.split())
    assert ("Distribution is a zip or folder copy plus a per-user shortcut. "
            "There is no MSIX, MSI, or auto-update service.") in flat
    build = _text(ROOT / "scripts" / "build_bundle.py")
    assert "AgentDesk.exe" in build and "dist/agent-desk" in build, (
        "the build script no longer makes the names the guide instructs about"
    )
    update = _text(ROOT / "src" / "agentdesk" / "update" / "__init__.py")
    assert '"AgentDesk.exe"' in update and '"agentdesk.exe"' in update, (
        "the executable pair behind the update procedure is gone"
    )


def test_the_marketplace_guide_names_the_product_and_states_two_roots():
    text = _text(MARKETPLACE)
    assert "Nexuus Bot is a single-user, loopback-only app." in text
    assert "docs/ops/compatibility.md" in text
    # Fact one: the runtime data root, with its override variable.
    assert "%USERPROFILE%\\.agent-desk" in text
    assert "AGENTDESK_DATA" in text
    # Fact two: the bundle install folder contract, stated separately.
    install_lines = [line for line in text.splitlines()
                     if "%LOCALAPPDATA%\\AgentDesk" in line]
    assert any("install" in line.lower() for line in install_lines), (
        "the install folder contract is not stated as its own fact"
    )


def test_the_marketplace_backup_names_the_runtime_root():
    text = _text(MARKETPLACE)
    assert ("To back up, stop Nexuus Bot, copy the whole data folder "
            "(the runtime data root above), then start it again.") in text
    backup_line = next(line for line in text.splitlines()
                       if line.startswith("To back up"))
    assert "%LOCALAPPDATA%" not in backup_line, (
        "the backup instruction names the install folder, not the data root"
    )
    app = _text(ROOT / "src" / "agentdesk" / "server" / "app.py")
    assert 'Path(Path.home(), ".agent-desk")' in app, (
        "the guide's default data root is not the code's default"
    )


def test_the_licensing_guide_names_the_product_and_legal_bytes_hold():
    text = _text(LICENSING)
    assert "The product is Nexuus Bot." in text
    # The pinned guide fragments keep their exact bytes.
    assert ("| Agent Desk core | Proprietary, all rights reserved "
            "(`LICENSE`) |") in text
    assert ("grants Agent Desk a worldwide, non-exclusive, royalty-free, "
            "sublicensable") in text
    assert "agentdesk:license-exception" in text
    # The licence-table identifier keeps its exact bytes where it lives.
    assert "[tool.agent-desk-licenses]" in _text(
        ROOT / "pyproject.toml")


def test_spec_030_names_the_product_and_depends_on_spec_032():
    text = _text(SPEC_030)
    assert ("The agent's name is Nexuus Bot, and the product is Nexuus Bot "
            "too") in text
    assert "Copy or prompt changes that speak as Nexuus Bot" not in text, (
        "the conflicting copy exclusion is still absolute"
    )
    assert "Copy or prompt wording beyond the product name" in text
    assert "Spec 032 completes the rename before shell and face work starts" \
        in text
    assert not any(form in text for form in OLD_FORMS), (
        "Spec 030 still carries an old product form"
    )


def test_spec_031_depends_on_spec_032_and_keeps_its_templates():
    text = _text(SPEC_031)
    assert "Spec 032 completes the rename before presentation work starts" \
        in text
    assert "the product and the agent are Nexuus Bot" in text
    assert ("The three template directions: executive review, working "
            "session (consulting-style), minimal.") in text
    assert ("Twelve shared slide roles plus two per template, with "
            "shape-drawn exhibits and no chart objects.") in text
    assert not any(form in text for form in OLD_FORMS), (
        "Spec 031 still carries an old product form"
    )


def test_the_family_files_carry_no_unclassified_old_display_occurrence():
    """Every remaining old form in the family's files is a covered
    retained identifier, and none leans on this family's entries."""
    data = json.loads(TEMPORARY.read_text(encoding="utf-8"))
    assert data["entries"] == [], (
        "the operator-guides family still carries temporary entries"
    )
    g = _guard()
    contract = g.load_contract()
    assert [entry for _f, family, _e in contract.temporary
            if family == "operator-guides"] == []
    for rel in ("docs/ops/distribution.md",
                "docs/ops/marketplace-operator.md",
                "docs/licensing.md",
                "specs/030-one-shell-and-the-face-on-every-wait.md"):
        path = Path(rel)
        for number, line in g.file_lines(path, None):
            for span in g.occurrences(line):
                covered = (g.allowlist_hit(path, line, span,
                                           contract.allowlist)
                           or g.temporary_hits(path, line, span,
                                               contract.temporary))
                assert covered, (
                    f"{rel}:{number}: old display form outside every "
                    f"exception: {line.strip()[:90]!r}"
                )
