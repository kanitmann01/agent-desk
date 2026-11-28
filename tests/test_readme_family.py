"""Ticket 05 (issue 359): the README family tells one Nexuus Bot story.

The checks read the family's live documents and the code the corrected
sentences describe, and compare what the documents claim with what the
toolchain and the keychain code actually do. They start no desk, no walk
and no application, and open no browser: the capture instructions are
read and cross-checked against the audit tool's own source, never run.
The three README screenshots, their alt text and the provenance source
block are pinned byte for byte (Spec 032 testing decision 6).
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

README = ROOT / "README.md"
PROVENANCE = ROOT / "docs" / "readme" / "README.md"
DEMO = ROOT / "DEMO.md"
GLOSSARY = ROOT / "GLOSSARY.md"
DESIGN = ROOT / "DESIGN.md"
DESIGN_LANGUAGE = ROOT / "docs" / "design-language.md"
FRONTEND_README = ROOT / "frontend" / "README.md"
FRONTEND_PACKAGE = ROOT / "frontend" / "package.json"
FRONTEND_LOCK = ROOT / "frontend" / "package-lock.json"
DEMO_TOOL = ROOT / "tools" / "demo_walkthrough.py"
README_FAMILY_TEMPORARY = ROOT / "tools" / "naming" / "temporary" / "readme-family.json"
ALLOWLIST = ROOT / "tools" / "naming" / "allowlist.json"

# The three README screenshots, pinned by the guard's retained-media data.
SCREENSHOT_HASHES = {
    "docs/readme/dashboard.png":
        "ba3c908a1ef55347854ba4843fcda756d362b84b36b0eee0a5a4512573073440",
    "docs/readme/memory.png":
        "8e1b34c1826162d5f382a2cdae0bc66a75ea3a07856a63fe2b0d9f486859b7ca",
    "docs/readme/marketplace.png":
        "abe2ee5a3df5d5acd33d2309d8cd2c51f821ee3bc98004843075b22064885739",
}

# The exact alt text of the three images, byte for byte through this spec.
ALT_TEXTS = (
    'alt="Nexuus Bot dashboard with sample workbook, calendar, decision, '
    'and plugin cards"',
    "![Nexuus Bot memory page with sample facts, sources, and graph "
    "controls](docs/readme/memory.png)",
    "![Nexuus Bot marketplace with sample plugin catalog]"
    "(docs/readme/marketplace.png)",
)

# The provenance source block: where the current screenshots came from.
# It keeps these bytes until the wave-closeout retake replaces both the
# images and this record together.
PROVENANCE_SOURCE_BLOCK = """## Source

- Repository: `kanitmann01/agent-desk`
- Source commit: `37515e9643c60857263c65b376e8c54f51dcc04a`
- Capture date: 2026-11-25
- Theme: Unkey
- Viewport: 1280\u00d7800
"""

# Every repository target the README's instructions name. The reading
# check for "each instruction points at something real".
README_INSTRUCTION_TARGETS = (
    "pyproject.toml",
    "frontend/package.json",
    "docs/PRD.md",
    "docs/design-language.md",
    "docs/known-limitations.md",
    "docs/ops/marketplace-operator.md",
    "docs/ops/distribution.md",
    "docs/licensing.md",
    "DEMO.md",
    "docs/evidence",
    "tools/agent-desk.cmd",
    "tools/agent-desk.command",
    "tools/demo_readiness.py",
    "tools/ci_local.py",
    "tools/layout_audit.py",
    "tools/face_walkthrough.py",
    "src/nexuusbot/feeder",
    "src/nexuusbot/server",
    "docs/readme/dashboard.png",
    "docs/readme/memory.png",
    "docs/readme/marketplace.png",
    "docs/readme/architecture.svg",
)

# Installer and executable artifacts that do not exist on this tree; no
# README instruction may name one as something the reader can get.
MISSING_ARTIFACTS = (
    "AgentDesk.exe",
    "agentdesk.exe",
    "agent-desk.zip",
    "agent-desk-bundle",
    ".msi",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    """The document with every run of space as one: wrapping is not meaning."""
    return " ".join(_text(path).split())


# -- the family's temporary entries leave in the same change ---------------


def test_the_readme_family_temporary_entries_are_cleared():
    data = json.loads(_text(README_FAMILY_TEMPORARY))
    assert data["family"] == "readme-family" and data["issue"] == 359
    assert data["entries"] == [], (
        "ticket 05 clears the readme-family file: its entries must be gone "
        f"once DESIGN.md and the design-language title carry the new name"
    )


# -- the family's live documents say Nexuus Bot -----------------------------


def test_design_md_names_the_product():
    text = _text(DESIGN)
    assert "name: Nexuus Bot" in text, "the frontmatter name still says the old name"
    assert "\n# Nexuus Bot\n" in text, "the document heading still says the old name"
    assert "Agent Desk" not in text


def test_the_design_language_title_names_the_product():
    first = _text(DESIGN_LANGUAGE).splitlines()[0]
    assert first == "# Design language: Nexuus Bot", (
        f"the design-language title is {first!r}"
    )


def test_the_demo_script_says_nexuus_bot_in_spoken_and_written_copy():
    text = _normalized(DEMO)
    assert "demo of Nexuus Bot" in text, "the demo intro still says the old name"
    assert '"This is Nexuus Bot.' in text, "the spoken opening still says the old name"
    assert "Agent Desk" not in text and "AgentDesk" not in text, (
        "written or spoken demo copy still carries an old display form"
    )


def test_the_demo_script_keeps_its_retained_commands_exact():
    text = _normalized(DEMO)
    # The environment prefix, the launcher filenames and the backup data
    # folder are compatibility contracts: exact spellings, unchanged.
    assert "set AGENTDESK_DATA=%TEMP%\\demo-desk-1" in text
    assert "tools\\agent-desk.cmd" in text
    assert ".agent-desk-backup" in text


def test_the_demo_walkthrough_tool_says_nexuus_bot():
    source = _text(DEMO_TOOL)
    assert "Nexuus Bot servers" in source, (
        "the walkthrough docstring still says the old name"
    )
    assert '"Nexuus Bot demo walkthrough"' in source, (
        "the walkthrough's banner print still says the old name"
    )
    assert "AGENTDESK_DATA" in source, "the retained environment prefix moved"


def test_the_frontend_readme_and_package_description_say_nexuus_bot():
    assert "The Nexuus Bot dashboard is a React single-page app." in _text(
        FRONTEND_README)
    package = json.loads(_text(FRONTEND_PACKAGE))
    assert package["description"].startswith("The Nexuus Bot dashboard"), (
        "the package description still says the old name"
    )
    # Ticket 09 (issue 363) renames the package identity; this ticket
    # must not touch it.
    assert package["name"] == "agentdesk-dashboard-spa"
    lock = json.loads(_text(FRONTEND_LOCK))
    assert lock["name"] == "agentdesk-dashboard-spa"


# -- sentence fix (a): the Node floor comes from the toolchain --------------


def _vite_node_engines() -> str:
    lock = json.loads(_text(FRONTEND_LOCK))
    return lock["packages"]["node_modules/vite"]["engines"]["node"]


def test_the_frontend_prerequisite_names_the_toolchain_node_floor():
    """The floor the README states must equal the one the lockfile records.

    The expected numbers are derived from frontend/package-lock.json, so
    a toolchain bump fails this test until the README follows: the value
    is read, never guessed.
    """
    engines = _vite_node_engines()
    match = re.fullmatch(r"\^(\d+)\.(\d+)\.\d+ \|\| >=(\d+)\.(\d+)\.\d+",
                         engines)
    assert match is not None, (
        f"the test only reads a caret-or-newer pair, got {engines!r}; "
        "update the derivation with the toolchain"
    )
    floor_20 = f"{match.group(1)}.{match.group(2)}"
    floor_new = f"{match.group(3)}.{match.group(4)}"
    text = _normalized(README)
    assert f"Node {floor_20}" in text, "the 20-line floor is not stated"
    assert f"Node {floor_new}" in text, "the new-line floor is not stated"
    assert "do not work" in text, "the versions below the floor are not named"
    # Which versions below do not work: the older lines, the gap before
    # each floor, and the whole skipped 21 line.
    for line in ("Node 18", "Node 19", "Node 21"):
        assert line in text, f"the excluded {line} line is not named"
    assert "frontend/package-lock.json" in text, (
        "the README does not record where the value comes from"
    )
    assert "Vite 7" in text, "the README does not name the tool that sets the floor"


# -- sentence fix (b): the keychain sentence says what the code does --------


def test_the_keychain_sentence_claims_only_what_the_code_does(monkeypatch):
    """Each clause of the README bullet must map to a keychain code path.

    The document half reads the bullet; the code half exercises the
    public seam behind every clause with injected stand-ins: no real
    keychain is touched and no application starts.
    """
    bullet = next(
        line for line in _text(README).splitlines()
        if line.startswith("- ") and "keychain" in line
        and "masked hints" in line
    )
    for marker in ("usable OS keychain", "no key is stored", "config.env",
                   "legacy settings rows", "masked hints"):
        assert marker in bullet, f"the keychain sentence lost its {marker!r} claim"

    from nexuusbot.config import PREFIX, parse_env_file
    from nexuusbot.keys.secrets import KeychainSecrets, MemoryKeychain, SERVICE
    from nexuusbot.keys.store import SCHEMA
    from nexuusbot.llm import effective_llm_config

    # "where a usable keychain is available": the retained service, and a
    # usable backend stores and returns the secret.
    assert SERVICE == "agent-desk"
    usable = KeychainSecrets(backend=MemoryKeychain())
    assert usable.store("connection-1", "model-key") is True
    assert usable.fetch("connection-1") == "model-key"

    # "where there is none, no key is stored": keyring's fail backend is
    # its honest no-keychain answer; store refuses and nothing lands.
    class _FailKeyring:
        pass

    _FailKeyring.__module__ = "keyring.backends.fail.Keyring"

    class _NoKeychainBackend:
        def get_keyring(self):
            return _FailKeyring()

    missing = KeychainSecrets(backend=_NoKeychainBackend())
    assert missing.store("connection-1", "model-key") is False
    assert missing.fetch("connection-1") is None

    # the save route refuses rather than keep a connection with no secret
    app_source = _text(ROOT / "src" / "nexuusbot" / "server" / "app.py")
    assert "not server.keychain.store(" in app_source

    # "plaintext configuration": the optional config.env file carries the
    # AGENTDESK_-prefixed key, and the environment leg reads it.
    assert PREFIX == "AGENTDESK_"
    assert parse_env_file("AGENTDESK_LLM_KEY=plaintext-key") == {
        "AGENTDESK_LLM_KEY": "plaintext-key"}

    # "legacy fallback paths": the pre-keys-store settings rows still
    # serve the key when no connection is saved.
    for var in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY",
                "AGENTDESK_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)

    class _LegacySettings:
        def get(self, name):
            return {"llm_key": "legacy-key"}.get(name, "")

    _base, key, _model = effective_llm_config(_LegacySettings())
    assert key == "legacy-key"

    # "SQLite keeps masked hints only": the schema holds a masked hint
    # column and no plaintext secret column.
    assert "masked_key" in SCHEMA
    lowered = SCHEMA.lower()
    assert "secret" not in lowered and "api_key" not in lowered


# -- sentence fix (c): the capture instructions install the browser ---------


def test_the_capture_instructions_install_the_browser_and_miss_nothing():
    sys.path.insert(0, str(ROOT / "tools"))
    import layout_audit

    provenance = _text(PROVENANCE)
    # (1) The step the instructions left out: installing the browser the
    # audit drives, before the capture command.
    install_at = provenance.index("playwright install chromium")
    capture_at = provenance.index("tools/layout_audit.py")
    assert install_at < capture_at, (
        "the browser install step must come before the capture command"
    )
    audit_source = _text(ROOT / "tools" / "layout_audit.py")
    assert "playwright.chromium.launch" in audit_source, (
        "the audit no longer drives Chromium; the documented install must "
        "name what the tool launches"
    )

    # (2) The capture command keeps its recorded facts.
    for fact in ("--conditions fresh,data",
                 '--routes "dashboard,marketplace,memory"',
                 "--widths 1280", "--themes unkey", "--no-stress",
                 "--fail-on none", "--out build/readme-shots",
                 "--with keyring", "--with cryptography"):
        assert fact in provenance, f"the capture command lost {fact!r}"

    # (3) The replacement mapping names each produced file, derived from
    # the tool's own path formula, so the retake needs no hand work.
    def produced(view_path: str, state: str) -> str:
        screenshot = layout_audit._screenshot_file(
            Path("build/readme-shots"),
            {"condition": "data", "width": 1280, "theme": "unkey"},
            {"path": view_path, "state": state})
        return screenshot.as_posix()

    for view_path, state, image in (
        ("/", "dashboard", "docs/readme/dashboard.png"),
        ("/memory", "memory", "docs/readme/memory.png"),
        ("/marketplace", "marketplace", "docs/readme/marketplace.png"),
    ):
        produced_path = produced(view_path, state)
        assert produced_path in provenance, (
            f"the replacement note does not name the produced {produced_path}"
        )
        assert image in provenance, (
            f"the replacement note does not name the target {image}"
        )

    # (4) The provenance source block keeps its exact bytes.
    assert PROVENANCE_SOURCE_BLOCK in provenance


# -- the public introduction promises only real things ----------------------


def test_the_readme_instructions_point_at_real_files():
    readme = _text(README)
    for target in README_INSTRUCTION_TARGETS:
        assert (ROOT / target).exists(), (
            f"the README instructs about {target}, which does not exist"
        )
    for artifact in MISSING_ARTIFACTS:
        assert artifact not in readme, (
            f"the README names {artifact}, which no build produces"
        )
    assert "No signed installer or released distribution exists." in readme, (
        "the honest status line is gone"
    )


def test_the_readme_labels_its_retained_names_as_compatibility_contracts():
    text = _normalized(README)
    assert "compatibility contract" in text, (
        "the retained names are not labelled as compatibility contracts"
    )
    for retained in ("kanitmann01/agent-desk", "launcher filenames",
                     "data folder"):
        assert retained in text, (
            f"the label does not name the retained {retained!r}"
        )


# -- the retained media stays byte for byte ---------------------------------


def test_the_three_screenshots_and_their_alt_text_are_untouched():
    for rel, digest in SCREENSHOT_HASHES.items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        assert actual == digest, f"{rel} changed under this ticket"
    readme = _text(README)
    for alt in ALT_TEXTS:
        assert alt in readme, f"the pinned alt text moved: {alt[:60]!r}"


# -- the glossary distinguishes the name from the code identities -----------


def test_the_glossary_title_and_definition_say_nexuus_bot():
    text = _text(GLOSSARY)
    assert text.splitlines()[0] == "# Nexuus Bot", (
        "the glossary title still says the old name"
    )
    for marker in ("**Nexuus Bot** is the product's name",
                   "compatibility contract", "never imitates"):
        assert marker in text, (
            f"the glossary definition lost its {marker!r} distinction"
        )


def test_the_glossary_names_the_identifiers_it_distinguishes():
    """Every identifier the definition names must sit in an exact-context
    allowlist entry, so the exception is documented rather than folklore."""
    data = json.loads(_text(ALLOWLIST))
    glossary_contexts = {
        entry["identifier"]: entry for entry in data["entries"]
        if "GLOSSARY.md" in entry.get("context_paths", [])
    }
    for identifier in ("agentdesk", "AGENTDESK_", ".agent-desk",
                       "agentdesk_session"):
        assert identifier in glossary_contexts, (
            f"the glossary names {identifier} with no allowlist context"
        )
        entry = glossary_contexts[identifier]
        assert entry.get("owner") and entry.get("review_trigger"), (
            f"{identifier}: the glossary entry has no owner or review trigger"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
