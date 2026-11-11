"""Plugin runtime fixtures: deterministic plugin zips for lifecycle tests.

Zips are built with fixed timestamps so every digest is stable. The
workspace file the demo manifest's excel-watch source watches is created
on demand so tests control fresh-versus-amber. Importing this module
also makes the src/ package importable, like server_harness does.
"""
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FIXTURES = Path(__file__).resolve().parent
VALID_PLUGIN_DIR = FIXTURES / "fixtures" / "validator" / "valid-manifest"
SHELL_PLUGIN_DIR = FIXTURES / "fixtures" / "validator" / "shell-permission"

ZIP_DATE = (2026, 11, 11, 9, 0, 0)


def build_zip(source_dir: Path, destination: Path, *,
              manifest_overrides: dict | None = None,
              extra_file: tuple[str, str] | None = None) -> Path:
    """Zip one plugin directory, optionally patching the manifest."""
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest_overrides:
        for key, value in manifest_overrides.items():
            if isinstance(value, dict) and isinstance(manifest.get(key), dict):
                manifest[key].update(value)
            else:
                manifest[key] = value
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file() or path.name == "manifest.json":
                continue
            info = zipfile.ZipInfo(f"{path.relative_to(source_dir).as_posix()}",
                                   date_time=ZIP_DATE)
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("manifest.json", date_time=ZIP_DATE)
        archive.writestr(info, json.dumps(manifest, indent=2) + "\n")
        if extra_file:
            rel, content = extra_file
            archive.writestr(zipfile.ZipInfo(rel, date_time=ZIP_DATE), content)
    return destination


def valid_zip(destination: Path, *, overrides: dict | None = None) -> Path:
    """The valid sales-delta plugin as a zip, optionally patched."""
    return build_zip(VALID_PLUGIN_DIR, destination,
                     manifest_overrides=overrides)


def widened_zip(destination: Path) -> Path:
    """Same plugin, one added filesystem read glob, and a version bump:
    a scope widening that re-consent can apply as a real new version."""
    manifest = json.loads((VALID_PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = "1.2.1"
    reads = manifest["permissions"]["filesystem"]["read"]
    manifest["permissions"]["filesystem"]["read"] = sorted(
        set(reads) | {"${workspace}/reports/*.pdf"})
    widgets = manifest["contributes"]["widgets"]
    extra = json.loads(json.dumps(widgets[0]))
    extra["id"] = "sales-pdf-delta"
    extra["dataSource"]["file"] = "${workspace}/reports/*.pdf"
    widgets.append(extra)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as archive:
        for path in sorted(VALID_PLUGIN_DIR.rglob("*")):
            if not path.is_file() or path.name == "manifest.json":
                continue
            info = zipfile.ZipInfo(f"{path.relative_to(VALID_PLUGIN_DIR).as_posix()}",
                                   date_time=ZIP_DATE)
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("manifest.json", date_time=ZIP_DATE)
        archive.writestr(info, json.dumps(manifest, indent=2) + "\n")
    return destination


def shell_zip(destination: Path) -> Path:
    """A plugin that fails the permission lint: shell access."""
    return build_zip(SHELL_PLUGIN_DIR, destination)
