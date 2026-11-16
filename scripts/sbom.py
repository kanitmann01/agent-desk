#!/usr/bin/env python3
"""Generate the Agent Desk CycloneDX 1.6 SBOM.

Sources of truth:
  * pyproject.toml   Python runtime dependency set (currently empty)
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
    "pkg:npm/%40fontsource-variable/source-serif-4@5.3.1": (
        "frontend/public/licenses/OFL-SourceSerif4.txt"
    ),
    "pkg:npm/%40fontsource-variable/source-sans-3@5.3.1": (
        "frontend/public/licenses/OFL-SourceSans3.txt"
    ),
    "pkg:npm/%40fontsource/ibm-plex-mono@5.3.0": (
        "frontend/public/licenses/OFL-IBMPlexMono.txt"
    ),
    "pkg:generic/cpython": "licenses/third-party/python-LICENSE.txt",
}

# Only these non-allowlist licences are excepted, and only for the
# components listed here. Keep in sync with scripts/license_gate.py.
LICENSE_EXCEPTIONS = {
    "pkg:generic/cpython": "PSF-2.0",
    "pkg:npm/%40fontsource-variable/source-serif-4@5.3.1": "OFL-1.1",
    "pkg:npm/%40fontsource-variable/source-sans-3@5.3.1": "OFL-1.1",
    "pkg:npm/%40fontsource/ibm-plex-mono@5.3.0": "OFL-1.1",
    "pkg:npm/%40csstools/color-helpers@5.1.0": "MIT-0",
    "pkg:npm/caniuse-lite@1.0.30001826": "CC-BY-4.0",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_pyproject(path: Path) -> dict:
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
    if name.startswith("@"):
        scope, _, bare = name.partition("/")
        return f"pkg:npm/{quote(scope, safe='')}/{quote(bare, safe='')}@{quote(version, safe='')}"
    return f"pkg:npm/{quote(name, safe='')}@{quote(version, safe='')}"


def _sha512_from_integrity(integrity: str | None) -> str | None:
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
    if licence in SPDX_LICENSE_IDS:
        return {"license": {"id": licence}}
    return {"license": {"name": licence}}


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
    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise SystemExit("sbom: pyproject.toml has no [project] table")
    dependencies = project.get("dependencies") or []
    if not isinstance(dependencies, list):
        raise SystemExit("sbom: [project].dependencies must be an array")
    if dependencies:
        # Deliberately refuse rather than silently omitting packages. Adding
        # a runtime dependency is a licensing decision, so make it explicit.
        raise SystemExit(
            "sbom: pyproject declares runtime dependencies; teach scripts/sbom.py "
            "how to resolve and license them before shipping: "
            + ", ".join(str(item) for item in dependencies)
        )
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
                "CPython standard library, PSF-2.0; bundled by Nuitka; no "
                "third-party Python runtime dependencies"
            )},
        ],
    )
    return [component]


def build_sbom(root: Path = REPO_ROOT) -> dict:
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "frontend" / "package-lock.json"
    pyproject = _load_pyproject(pyproject_path)
    project = pyproject.get("project", {})
    app_version = str(project.get("version") or APP_VERSION_FALLBACK)
    lock_bytes = lock_path.read_bytes()
    lock_sha = _sha256(lock_bytes)
    components = _npm_components(lock_path) + _python_components(pyproject)
    components.sort(key=lambda item: item["bom-ref"])

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
                {"name": "agentdesk:python-runtime-dependencies", "value": "none"},
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
