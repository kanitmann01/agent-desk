"""The human-readable file properties say Nexuus Bot.

Ticket 07 of Spec 032 (issue 361). The Windows product, company and
file-description fields, the bundle manifest product and the update
tests' share-format fixtures carry the approved name, while every name a
machine matches keeps its exact contract: AgentDesk.exe, the build
entrypoint, the manifest schema and the bundle folder. The checks call
the build functions and read tracked files; they never build, smoke or
launch a bundle, and no desk, walk or application starts here.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMING = ROOT / "tools" / "naming"

# The display families of tickets 02 to 07 (Spec 032). The two package
# families stay until tickets 08 and 09 clear them.
DISPLAY_FAMILIES = (
    ("server-pages", 356),
    ("spa-and-bundle", 357),
    ("generated-output", 358),
    ("readme-family", 359),
    ("demo-and-glossary", 359),
    ("frontend-setup", 359),
    ("operator-guides", 360),
    ("bundle-metadata", 361),
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
    """Ticket 07 turns name enforcement fully on for display text.

    Every display family's file of the temporary list is empty, except
    the two recorded exceptions. The one scoped launcher-invocations
    entry in server-pages covers retained command spellings, not display
    copy, and ticket 08 (issue 362) resolves it with the package move.
    The two stale entries in frontend-setup stay because the README one
    carries whole-file coverage that is load-bearing: three src/nexuusbot
    package-path references in frontend/README.md belong to the
    python-package family (ticket 08), whose module-path entry lists
    README.md but omits frontend/README.md. The structural question is
    posted on issue 361; both entries are frozen as written here until
    it is answered.
    """
    for name, _issue in DISPLAY_FAMILIES:
        path = NAMING / "temporary" / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if name == "server-pages":
            assert len(data["entries"]) == 1, (
                "server-pages carries entries beyond the one scoped "
                "launcher-invocations entry ticket 08 resolves"
            )
            assert data["entries"][0]["matches"] == ["-m agentdesk.server"]
            continue
        if name == "frontend-setup":
            assert len(data["entries"]) == 2, (
                "frontend-setup carries entries beyond the two stale "
                "entries the structural question on issue 361 covers"
            )
            shapes = {
                (tuple(entry.get("files", [])),
                 tuple(entry.get("matches", [])))
                for entry in data["entries"]
            }
            assert shapes == {
                (("frontend/README.md",), ()),
                (("frontend/package.json",), ("agent desk",)),
            }, "the frozen frontend-setup entries moved"
            continue
        assert data["entries"] == [], (
            f"the display family {name} still carries temporary entries"
        )
