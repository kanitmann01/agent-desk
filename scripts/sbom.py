#!/usr/bin/env python3
"""Generate the Agent Desk CycloneDX 1.6 SBOM.

Sources of truth:
  * pyproject.toml   declared Python runtime dependencies, licensed via
                      [tool.agent-desk-licenses] and version-resolved from
                      the installed environment
  * package-lock.json frontend dependency tree with pinned versions and
                      npm integrity hashes
  * the interpreter running this script for the CPython runtime component

Output is deterministic in ordering: components are sorted by bom-ref, and
arrays of strings/hashes/external references are sorted where order carries
no meaning. The document timestamp can be pinned with SOURCE_DATE_EPOCH.

Usage:
    python scripts/sbom.py [--output build/sbom.cdx.json]

The script exits 1 with an actionable message if a source file is missing.
It never invents a licence: a package without licence data is emitted with
no `licenses` array so the licence gate fails it visibly.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - exercised on 3.10 only
    tomllib = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "build" / "sbom.cdx.json"
APP_NAME = "agent-desk"
APP_VERSION_FALLBACK = "0.0.0"
SERIAL_NAMESPACE = uuid.UUID("0f4f7f8a-5a2c-5a6e-9a7f-3f0b8f2a1c11")
LICENSE_FILE_PROPERTY = "agentdesk:license-file"
EXCEPTION_PROPERTY = "agentdesk:license-exception"

# Licences that are valid SPDX identifiers and may be emitted as
# `{"license": {"id": ...}}`. Anything else is emitted by name.
SPDX_LICENSE_IDS = {
    "MIT",
    "ISC",
    "Apache-2.0",
    "OFL-1.1",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MIT-0",
    "CC-BY-4.0",
    "PSF-2.0",
}

# Components that ship inside the bundle and therefore must ship their
# upstream licence text. Paths are relative to the repository root.
LOCAL_LICENSE_FILES = {
    "pkg:npm/react@19.3.1": "licenses/third-party/react-19.3.1-LICENSE.txt",
    "pkg:npm/react-dom@19.3.1": "licenses/third-party/react-dom-19.3.1-LICENSE.txt",
    "pkg:npm/scheduler@0.28.0": "licenses/third-party/scheduler-0.28.0-LICENSE.txt",
    "pkg:npm/%40fontsource/geist@5.2.8": "frontend/public/licenses/OFL-Geist.txt",
    "pkg:npm/%40fontsource/geist-mono@5.2.7": (
        "frontend/public/licenses/OFL-GeistMono.txt"
    ),
    "pkg:npm/%40fontsource/montserrat@5.3.0": (
        "frontend/public/licenses/OFL-Montserrat.txt"
    ),
    "pkg:generic/cpython": "licenses/third-party/python-LICENSE.txt",
}

# Python runtime dependencies and the upstream licence texts that travel
# with them in the bundle. Keyed by name rather than purl because the
# version is resolved from the installed environment at build time, so a
# purl key would silently stop matching after an upgrade.
PYTHON_LICENSE_FILES = {
    "cryptography": "licenses/third-party/cryptography-LICENSE.txt",
}

# Only these non-allowlist licences are excepted, and only for the
# components listed here. Keep in sync with scripts/license_gate.py.
LICENSE_EXCEPTIONS = {
    "pkg:generic/cpython": "PSF-2.0",
    "pkg:npm/%40fontsource/geist@5.2.8": "OFL-1.1",
    "pkg:npm/%40fontsource/geist-mono@5.2.7": "OFL-1.1",
    "pkg:npm/%40fontsource/montserrat@5.3.0": "OFL-1.1",
    "pkg:npm/%40csstools/color-helpers@5.1.0": "MIT-0",
    "pkg:npm/caniuse-lite@1.0.30001826": "CC-BY-4.0",
}


def _sha256(data: bytes) -> str:
    """Return the hex sha256 of a byte string.

    This is the digest form CycloneDX records, used here for the frontend
    lockfile so the document names the exact dependency tree it describes.
    """
    return hashlib.sha256(data).hexdigest()


def _load_pyproject(path: Path) -> dict:
    """Parse pyproject.toml, or exit 1 with the reason on stderr.

    On Python 3.11+ that is tomllib. The 3.10 fallback reads only name,
    version and license with a regex, and it accepts an empty dependency list
    only: a non-empty one exits, because resolving it without a TOML parser
    would mean guessing which packages ship.
    """
    if not path.is_file():
        raise SystemExit(f"sbom: missing {path}")
    text = path.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    # Python 3.10 fallback: the project has a single, simple [project] table,
    # but a non-empty dependency array cannot be parsed safely without tomli.
    project: dict[str, str] = {}
    for key in ("name", "version", "license"):
        match = re.search(rf'^{key}\s*=\s*"([^"]*)"', text, re.MULTILINE)
        if match:
            project[key] = match.group(1)
    if re.search(r"^dependencies\s*=\s*\[\s*\]", text, re.MULTILINE) is None:
        raise SystemExit(
            "sbom: Python 3.11+ (tomllib) is required to parse a non-empty "
            "pyproject dependency list"
        )
    project["dependencies"] = "[]"
    return {"project": project}


def _npm_purl(name: str, version: str) -> str:
    """Build the CycloneDX package URL for one npm name and version.

    Scoped names are split at the slash and both halves are percent-encoded,
    which is why a purl in the document reads %40fontsource-variable rather
    than @fontsource-variable.
    """
    if name.startswith("@"):
        scope, _, bare = name.partition("/")
        return f"pkg:npm/{quote(scope, safe='')}/{quote(bare, safe='')}@{quote(version, safe='')}"
    return f"pkg:npm/{quote(name, safe='')}@{quote(version, safe='')}"


def _sha512_from_integrity(integrity: str | None) -> str | None:
    """Convert an npm "sha512-" integrity string to hex, or return None.

    Only the first sha512 token is used. An absent, non-sha512 or undecodable
    value yields None, and the component is emitted without a hash rather than
    with a wrong one.
    """
    if not integrity:
        return None
    for token in integrity.split():
        if token.startswith("sha512-"):
            try:
                return base64.b64decode(token[len("sha512-"):]).hex()
            except (ValueError, TypeError):
                return None
    return None


def _licence_object(licence: str) -> dict:
    """Wrap one licence string in a CycloneDX license choice object.

    Identifiers in SPDX_LICENSE_IDS are emitted as an id and everything else
    by name, because an id has to be a real SPDX identifier for the document
    to be valid.
    """
    if licence in SPDX_LICENSE_IDS:
        return {"license": {"id": licence}}
    return {"license": {"name": licence}}


# An SPDX licence expression operator, matched the same way the licence
# gate splits expressions, so what is emitted here is what is checked there.
_SPDX_OPERATOR = re.compile(r"\s+(?:OR|AND|WITH)\s+", re.IGNORECASE)


def _python_licences(licence: str) -> list[dict]:
    """Wrap one [tool.agent-desk-licenses] value for a component.

    A value carrying an SPDX operator, such as cryptography's
    "Apache-2.0 OR BSD-3-Clause", is kept as one expression so the licence
    gate can check every alternative; a single identifier goes through
    _licence_object like the npm licences do.
    """
    if _SPDX_OPERATOR.search(licence):
        return [{"expression": licence}]
    return [_licence_object(licence)]


_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")


def _requirement_name(requirement: str) -> str:
    """Return the bare distribution name from a PEP 508 requirement string.

    Entries in [project].dependencies arrive as strings like
    "cryptography>=44", "requests[security]>=2.31" or
    "pywin32; sys_platform == 'win32'". The name is whatever precedes the
    first specifier, extra or marker, which the anchored pattern captures
    without a full PEP 508 parser.
    """
    match = _REQUIREMENT_NAME.match(requirement)
    if not match:
        raise SystemExit(f"sbom: cannot read a package name in {requirement!r}")
    return match.group(1)


def _component(
    *,
    bom_ref: str,
    name: str,
    version: str,
    ctype: str,
    licenses: list[dict] | None,
    scope: str | None = None,
    purl: str | None = None,
    hashes: list[dict] | None = None,
    external_refs: list[dict] | None = None,
    properties: list[dict] | None = None,
) -> dict:
    """Assemble one CycloneDX component from the fields that are set.

    Unset optionals are omitted rather than written as empty arrays, and
    hashes, external references and properties are sorted by their key fields,
    so the output does not depend on the order a source file happened to be
    walked.
    """
    component: dict = {
        "type": ctype,
        "bom-ref": bom_ref,
        "name": name,
        "version": version,
    }
    if purl:
        component["purl"] = purl
    if scope:
        component["scope"] = scope
    if hashes:
        component["hashes"] = sorted(hashes, key=lambda item: (item["alg"], item["content"]))
    if licenses is not None:
        component["licenses"] = licenses
    if external_refs:
        component["externalReferences"] = sorted(
            external_refs, key=lambda item: (item["type"], item["url"])
        )
    if properties:
        component["properties"] = sorted(properties, key=lambda item: item["name"])
    return component


def _npm_components(lock_path: Path) -> list[dict]:
    """Turn package-lock.json's packages map into components.

    The root entry is skipped and a purl already seen is dropped, so a package
    hoisted into several node_modules paths appears once. Dev dependencies keep
    scope "excluded" while their licence, hash and distribution URL are still
    recorded. Components named in LOCAL_LICENSE_FILES or LICENSE_EXCEPTIONS
    gain the matching properties, which the notices renderer and the licence
    gate read back. A bad entry, a missing version or an unreadable lockfile
    exits instead of producing a half-filled component.
    """
    if not lock_path.is_file():
        raise SystemExit(f"sbom: missing {lock_path}")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"sbom: {lock_path} is not valid JSON: {exc}") from exc
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise SystemExit("sbom: package-lock.json has no 'packages' object")
    seen: set[str] = set()
    components: list[dict] = []
    for key in sorted(packages):
        if key == "":
            continue
        entry = packages[key]
        if not isinstance(entry, dict):
            raise SystemExit(f"sbom: bad lock entry {key!r}")
        name = key.split("node_modules/")[-1]
        if not name:
            raise SystemExit(f"sbom: bad lock key {key!r}")
        version = entry.get("version")
        if not isinstance(version, str) or not version:
            raise SystemExit(f"sbom: lock entry {key!r} has no version")
        purl = _npm_purl(name, version)
        if purl in seen:
            continue
        seen.add(purl)
        dev = bool(entry.get("dev"))
        licence = entry.get("license")
        licences = [_licence_object(str(licence))] if isinstance(licence, str) and licence else None
        properties: list[dict] = []
        if dev:
            properties.append({"name": "agentdesk:dev-dependency", "value": "true"})
        license_file = LOCAL_LICENSE_FILES.get(purl)
        if license_file:
            properties.append({"name": LICENSE_FILE_PROPERTY, "value": license_file})
        exception = LICENSE_EXCEPTIONS.get(purl)
        if exception:
            properties.append({"name": EXCEPTION_PROPERTY, "value": exception})
        hashes = []
        digest = _sha512_from_integrity(entry.get("integrity"))
        if digest:
            hashes.append({"alg": "SHA-512", "content": digest})
        refs = []
        resolved = entry.get("resolved")
        if isinstance(resolved, str) and resolved:
            refs.append({"type": "distribution", "url": resolved})
        components.append(
            _component(
                bom_ref=purl,
                name=name,
                version=version,
                ctype="library",
                licenses=licences,
                scope="excluded" if dev else None,
                purl=purl,
                hashes=hashes,
                external_refs=refs,
                properties=properties,
            )
        )
    return components


def _python_components(pyproject: dict) -> list[dict]:
    """Return the CPython component plus one per declared runtime dependency.

    The interpreter running this script is the one Nuitka embeds, so its
    version is what the document records. Each entry in
    [project].dependencies is resolved the same disciplined way: the name
    before any specifier must carry a licence in [tool.agent-desk-licenses]
    and must be installed in this environment. A dependency the generator
    cannot licence or resolve refuses the build, because a runtime
    dependency is a licensing decision and a guessed version would be
    worse than no document at all.
    """
    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise SystemExit("sbom: pyproject.toml has no [project] table")
    dependencies = project.get("dependencies") or []
    if not isinstance(dependencies, list):
        raise SystemExit("sbom: [project].dependencies must be an array")
    licence_table = (pyproject.get("tool") or {}).get("agent-desk-licenses") or {}
    if not isinstance(licence_table, dict):
        raise SystemExit("sbom: [tool.agent-desk-licenses] must be a table")
    runtime_version = platform.python_version()
    licence_file = "licenses/third-party/python-LICENSE.txt"
    component = _component(
        bom_ref="pkg:generic/cpython",
        name="cpython",
        version=runtime_version,
        ctype="platform",
        purl=f"pkg:generic/cpython@{runtime_version}",
        licenses=[{"license": {"id": "PSF-2.0"}}],
        properties=[
            {"name": LICENSE_FILE_PROPERTY, "value": licence_file},
            {"name": EXCEPTION_PROPERTY, "value": "PSF-2.0"},
            {"name": "agentdesk:stdlib-note", "value": (
                "CPython standard library, PSF-2.0; bundled by Nuitka; "
                "third-party Python dependencies are emitted as their own "
                "pkg:pypi components"
            )},
        ],
    )
    components = [component]
    seen: set[str] = set()
    for requirement in dependencies:
        name = _requirement_name(str(requirement))
        licence = licence_table.get(name)
        if not isinstance(licence, str) or not licence:
            # Refuse rather than emitting the component without licences:
            # the annotation is the licensing decision, so make it explicit.
            raise SystemExit(
                f"sbom: no licence recorded for runtime dependency {name!r}; "
                "add it to [tool.agent-desk-licenses] in pyproject.toml "
                "before shipping"
            )
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise SystemExit(
                f"sbom: runtime dependency {name!r} is not installed; "
                "install the project dependencies so the SBOM can record "
                "a real version"
            ) from exc
        # The purl uses the canonical PyPI form (lowercase, underscores to
        # hyphens); the component keeps the name as declared in pyproject.
        purl_name = name.lower().replace("_", "-")
        purl = f"pkg:pypi/{quote(purl_name, safe='')}@{quote(version, safe='')}"
        if purl in seen:
            continue
        seen.add(purl)
        properties = []
        license_file = PYTHON_LICENSE_FILES.get(name)
        if license_file:
            properties.append({"name": LICENSE_FILE_PROPERTY, "value": license_file})
        components.append(
            _component(
                bom_ref=purl,
                name=name,
                version=version,
                ctype="library",
                purl=purl,
                licenses=_python_licences(licence),
                properties=properties,
            )
        )
    return components


def build_sbom(root: Path = REPO_ROOT) -> dict:
    """Build the whole SBOM document for one repository root.

    Deterministic apart from the timestamp: components are sorted by bom-ref
    and the serial number is a UUIDv5 over the canonical metadata and
    component list, so the same inputs and the same SOURCE_DATE_EPOCH give the
    same bytes. Raises SystemExit when pyproject.toml or the frontend lockfile
    is missing or unusable.
    """
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "frontend" / "package-lock.json"
    pyproject = _load_pyproject(pyproject_path)
    project = pyproject.get("project", {})
    app_version = str(project.get("version") or APP_VERSION_FALLBACK)
    lock_bytes = lock_path.read_bytes()
    lock_sha = _sha256(lock_bytes)
    components = _npm_components(lock_path) + _python_components(pyproject)
    components.sort(key=lambda item: item["bom-ref"])
    python_deps = ", ".join(
        f"{component['name']} {component['version']}"
        for component in sorted(
            (c for c in components if str(c.get("purl", "")).startswith("pkg:pypi/")),
            key=lambda item: item["name"],
        )
    ) or "none"

    app_ref = f"pkg:generic/{APP_NAME}@{app_version}"
    app_licence = "LicenseRef-Proprietary"
    metadata_component = _component(
        bom_ref=app_ref,
        name=APP_NAME,
        version=app_version,
        ctype="application",
        purl=app_ref,
        licenses=[{"license": {"name": "Proprietary"}}],
        properties=[
            {"name": LICENSE_FILE_PROPERTY, "value": "LICENSE"},
            {"name": "agentdesk:license-ref", "value": app_licence},
            {"name": "agentdesk:sdk-license", "value": "Apache-2.0 (LICENSE-SDK)"},
        ],
    )

    timestamp = _timestamp()
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "scripts/sbom.py",
                        "version": "1",
                    }
                ]
            },
            "component": metadata_component,
            "properties": [
                {"name": "agentdesk:bundle", "value": "Nuitka standalone one-folder (dist/agent-desk)"},
                {"name": "agentdesk:python-runtime-dependencies", "value": python_deps},
                {
                    "name": "agentdesk:frontend-lockfile",
                    "value": "frontend/package-lock.json",
                },
                {"name": "agentdesk:frontend-lockfile-sha256", "value": lock_sha},
            ],
        },
        "components": components,
    }
    canonical = json.dumps(
        {"metadata": document["metadata"], "components": document["components"]},
        sort_keys=True,
        separators=(",", ":"),
    )
    document["serialNumber"] = "urn:uuid:" + str(
        uuid.uuid5(SERIAL_NAMESPACE, canonical)
    )
    return document


def _timestamp() -> str:
    """Return the document timestamp, honoring SOURCE_DATE_EPOCH.

    Microseconds are dropped and the UTC offset is written as "Z", so two
    runs with the same pinned epoch are byte-identical. An unparseable epoch
    exits rather than silently falling back to the current time.
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            moment = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        except (ValueError, OSError) as exc:
            raise SystemExit(f"sbom: invalid SOURCE_DATE_EPOCH: {exc}") from exc
    else:
        moment = datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    """Write the SBOM to --output and report what it contains.

    --root defaults to the parent of scripts/. Creates the output directory,
    writes UTF-8 with Unix newlines and a trailing newline, then prints the
    path, the required/excluded tally and the serial number. Returns 1 when
    the output cannot be written; an unusable input exits before anything is
    written.
    """
    parser = argparse.ArgumentParser(
        prog="sbom.py", description="Generate build/sbom.cdx.json (CycloneDX 1.6)."
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"output path (default: {DEFAULT_OUTPUT.as_posix()})",
    )
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT,
        help="repository root (default: the parent of scripts/)",
    )
    args = parser.parse_args(argv)
    document = build_sbom(args.root.resolve())
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(document, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        print(f"sbom: cannot write {args.output}: {exc}", file=sys.stderr)
        return 1
    counts: dict[str, int] = {}
    for component in document["components"]:
        scope = component.get("scope", "required")
        counts[scope] = counts.get(scope, 0) + 1
    print(
        f"sbom: wrote {args.output} ({len(document['components'])} components; "
        f"required={counts.get('required', 0)}, excluded={counts.get('excluded', 0)})"
    )
    print(f"sbom: serial {document['serialNumber']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
