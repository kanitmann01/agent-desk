"""The human-readable file properties say Nexuus Bot.

Ticket 07 of Spec 032 (issue 361), extended by ticket 08 (issue 362):
the Windows product, company and file-description fields, the bundle
manifest product and the update tests' share-format fixtures carry the
approved name, while every name a machine matches keeps its exact
contract: AgentDesk.exe, the build entrypoint, the manifest schema and
the bundle folder. The frozen build now carries the canonical package
and the compatibility alias, and the temporary list holds only ticket
09's frontend-package entries. The checks call the build functions and
read tracked files; they never build, smoke or launch a bundle, and no
desk, walk or application starts here.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMING = ROOT / "tools" / "naming"

# The families of tickets 02 to 08 (Spec 032). Only the frontend
# package family (ticket 09) stays until it clears its own file.
DISPLAY_FAMILIES = (
    ("server-pages", 356),
    ("spa-and-bundle", 357),
    ("generated-output", 358),
    ("readme-family", 359),
    ("demo-and-glossary", 359),
    ("frontend-setup", 359),
    ("operator-guides", 360),
    ("bundle-metadata", 361),
    ("python-package", 362),
)

# The update tests whose fixture manifests pin the product the build
# writes into every bundle manifest (the share format).
UPDATE_FIXTURE_FILES = (
    "tests/test_update_channel.py",
    "tests/test_update_stage.py",
    "tests/test_update_rollback.py",
)


def _build_module():
    """Import scripts/build_bundle.py by path, the way its tests do."""
    spec = importlib.util.spec_from_file_location(
        "build_bundle", ROOT / "scripts" / "build_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _written_manifest(tmp_path):
    """The manifest document the build writes for one tiny output tree."""
    module = _build_module()
    output = tmp_path / "bundle"
    output.mkdir()
    (output / "sbom.cdx.json").write_text("{}", encoding="utf-8")
    (output / "AgentDesk.exe").write_bytes(b"stub exe")
    return module._manifest(
        ROOT, output, command=[], nuitka="test", duration=0.0,
        static_count=0, static_index_sha="0" * 64)


def test_the_windows_version_fields_say_nexuus_bot():
    """The Nuitka command stamps product, company and file description."""
    command = _build_module()._build_command(ROOT, allow_downloads=False)
    assert "--windows-product-name=Nexuus Bot" in command
    assert "--windows-company-name=Nexuus Bot" in command
    assert "--windows-file-description=Nexuus Bot local application" in command
    # The names a machine matches do not move. The frozen build carries
    # the canonical package and the compatibility alias beside it.
    assert "--output-filename=AgentDesk.exe" in command
    assert "--include-package=nexuusbot" in command
    assert "--include-package=agentdesk" in command


def test_the_bundle_manifest_product_says_nexuus_bot(tmp_path):
    """The manifest names the product Nexuus Bot and keeps its schema."""
    manifest = _written_manifest(tmp_path)
    assert manifest["product"] == "Nexuus Bot"
    assert manifest["schema_version"] == 1
    assert manifest["build"]["entrypoint"] == "AgentDesk.exe"
    assert manifest["build"]["mode"] == "nuitka-standalone-onefolder"


def test_the_update_share_fixtures_pin_the_manifest_product(tmp_path):
    """The update tests' fixture manifests mirror the product the build writes."""
    product = _written_manifest(tmp_path)["product"]
    for rel in UPDATE_FIXTURE_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert f'"product": "{product}"' in text, (
            f"{rel} does not pin the product the bundle manifest writes"
        )


def test_the_display_families_carry_no_temporary_entries():
    """Name enforcement stays fully on, now including the package move.

    Every display family's file of the temporary list is empty, and so
    is the python-package family: ticket 08 (issue 362) moved the
    package tree, re-pointed the launcher module rungs and updated the
    three frontend README package-path references, which also resolves
    the scoped launcher-invocations entry ticket 02 recorded (the
    question posted on issue 356) and empties the two stale
    frontend-setup entries (the question posted on issue 361). Only the
    frontend-package family stays until ticket 09 (issue 363) clears it.
    """
    for name, _issue in DISPLAY_FAMILIES:
        path = NAMING / "temporary" / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["entries"] == [], (
            f"the family {name} still carries temporary entries"
        )
