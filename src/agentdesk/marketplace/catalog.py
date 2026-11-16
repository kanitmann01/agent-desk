"""Catalog assembly for the plugin marketplace.

The bundled catalog is built from the repository registry by T3's
scripts/build_catalog.py, loaded through importlib so the server does not
need scripts/ to be a package and never fails when the checkout is absent.
Org and peer catalogs are plain JSON documents beside the workspace policy.
Every entry is normalized into one DTO shape that both list cards and the
detail route draw from.
"""

from __future__ import annotations

import importlib.util
import json
from fnmatch import fnmatch
from pathlib import Path

from .policy import RISK_TIERS, risk_rank

SCHEMA_VERSION = 2
SOURCES = ("bundled", "org", "peer", "installed")
RISK_LABELS = {"internal": "T0", "low": "T1", "medium": "T2", "high": "T3"}

_BUILD_CACHE: dict[str, tuple] = {}


def _build_script() -> Path:
    return Path(__file__).resolve().parents[3] / "scripts" / "build_catalog.py"


def _load_build_callable():
    """Import scripts/build_catalog.build_catalog without a package import."""
    script = _build_script()
    if not script.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "agentdesk_build_catalog", script)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        build = getattr(module, "build_catalog", None)
        return build if callable(build) else None
    except Exception:  # noqa: BLE001 - an absent or broken build never crashes the API
        return None


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _plugins_of(catalog) -> list:
    if isinstance(catalog, dict):
        plugins = catalog.get("plugins")
    elif isinstance(catalog, list):
        plugins = catalog
    else:
        plugins = None
    return plugins if isinstance(plugins, list) else []


def _risk_label(value) -> str:
    text = str(value or "").strip()
    if text in RISK_TIERS:
        return text
    return RISK_LABELS.get(text.lower(), "")


def _scope_items(permissions) -> set[str]:
    """Serialize a permission block into comparable leaf scopes."""
    items: set[str] = set()

    def walk(prefix: str, node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(f"{prefix}.{key}" if prefix else key, value)
        elif isinstance(node, list):
            for value in node:
                walk(prefix, value)
        else:
            items.add(f"{prefix}: {node}")

    walk("", permissions or {})
    return items


def _strings(value) -> list:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _signature(raw, source: str) -> dict:
    if isinstance(raw, dict):
        status = str(raw.get("status") or "").strip()
        return {
            "status": status or ("bundled" if source == "bundled" else "missing"),
            "keyId": str(raw.get("keyId") or ""),
            "fingerprint": str(raw.get("fingerprint") or ""),
            "signedAt": str(raw.get("signedAt") or ""),
        }
    if isinstance(raw, str) and raw.strip():
        return {"status": "signed", "keyId": "", "fingerprint": raw.strip(),
                "signedAt": ""}
    return {"status": "bundled" if source == "bundled" else "missing",
            "keyId": "", "fingerprint": "", "signedAt": ""}


def _capabilities(raw) -> dict:
    existing = raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else {}
    permissions = raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {}
    optional = (raw.get("optionalPermissions")
                if isinstance(raw.get("optionalPermissions"), dict) else {})

    sources: list = []
    contributes = raw.get("contributes")
    widgets = contributes.get("widgets") if isinstance(contributes, dict) else None
    if isinstance(widgets, list):
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            source = widget.get("dataSource")
            if isinstance(source, dict) and isinstance(source.get("type"), str):
                if source["type"] not in sources:
                    sources.append(source["type"])

    filesystem: list = []
    for block in (permissions, optional):
        tree = block.get("filesystem")
        if isinstance(tree, dict):
            for kind in ("read", "write"):
                filesystem.extend(_strings(tree.get(kind)))

    network: list = []
    for block in (permissions, optional):
        tree = block.get("network")
        if isinstance(tree, dict):
            network.extend(_strings(tree.get("allow")))
    deduped_network = list(dict.fromkeys(network))

    scopes = sorted(_scope_items(permissions) | _scope_items(optional))
    element_kinds = _strings(raw.get("elementKinds"))
    return {
        "sources": _strings(existing.get("sources")) or sources,
        "permissions": _strings(existing.get("permissions")) or scopes,
        "elementKinds": _strings(existing.get("elementKinds")) or element_kinds,
        "filesystem": _strings(existing.get("filesystem")) or filesystem,
        "network": _strings(existing.get("network")) or deduped_network,
    }


def _changelog(raw, version: str) -> dict:
    raw_log = raw.get("changelog")
    if isinstance(raw_log, dict):
        return {
            "version": str(raw_log.get("version") or version),
            "text": str(raw_log.get("text") or ""),
            "date": str(raw_log.get("date") or ""),
        }
    return {"version": version,
            "text": str(raw_log) if isinstance(raw_log, str) else "",
            "date": str(raw.get("publishedAt") or "")}


def normalize_entry(raw, source: str) -> dict | None:
    """One catalog entry in the shared DTO shape; None when unidentifiable."""
    if not isinstance(raw, dict):
        return None
    plugin_id = str(raw.get("id") or "").strip()
    if not plugin_id:
        return None
    version = str(raw.get("version") or raw.get("latest") or "")
    deprecated = raw.get("deprecated")
    if not isinstance(deprecated, dict):
        deprecated = None
    requirements = raw.get("requires")
    if not isinstance(requirements, dict):
        requirements = {}
    validation = raw.get("validation")
    if not isinstance(validation, dict):
        validation = {"checkedAt": "", "ok": None, "failures": []}
    failures = []
    for failure in validation.get("failures") or []:
        if isinstance(failure, dict):
            failures.append({"code": str(failure.get("code") or ""),
                             "message": str(failure.get("message") or "")})
    reasons = raw.get("ineligibleReasons")
    if not isinstance(reasons, list):
        reasons = []
    published = str(raw.get("publishedAt") or raw.get("generatedAt") or "")
    sample = raw.get("sample")
    if not isinstance(sample, dict):
        sample = None
    entry = {
        "id": plugin_id,
        "name": str(raw.get("name") or plugin_id),
        "version": version,
        "publisher": str(raw.get("publisher") or ""),
        "publisherVerified": bool(raw.get("publisherVerified", source == "bundled")),
        "category": str(raw.get("category") or ""),
        "tags": _strings(raw.get("tags")),
        "summary": str(raw.get("summary") or ""),
        "description": str(raw.get("description") or ""),
        "highlights": _strings(raw.get("highlights")),
        "icon": str(raw.get("icon") or "plugin"),
        "riskTier": _risk_label(raw.get("riskTier") or raw.get("risk")),
        "license": str(raw.get("license") or ""),
        "homepage": str(raw.get("homepage") or ""),
        "requires": requirements,
        "minHost": str(raw.get("minHost") or ""),
        "digest": str(raw.get("digest") or raw.get("sha256") or ""),
        "signature": _signature(raw.get("signature"), source),
        "provenance": {
            "builder": str((raw.get("provenance") or {}).get("builder") or "")
            if isinstance(raw.get("provenance"), dict) else "",
            "sourceCommit": str((raw.get("provenance") or {}).get("sourceCommit") or "")
            if isinstance(raw.get("provenance"), dict) else "",
        },
        "capabilities": _capabilities(raw),
        "changelog": _changelog(raw, version),
        "yanked": bool(raw.get("yanked")),
        "deprecated": deprecated,
        "publishedAt": published,
        "source": source,
        "validation": {"checkedAt": str(validation.get("checkedAt") or ""),
                       "ok": validation.get("ok"), "failures": failures},
        "eligible": bool(raw.get("eligible", False)),
        "ineligibleReasons": reasons,
        # Internal fields used by the API, never part of the card DTO.
        "platforms": _strings(raw.get("platforms")),
        "revoked": bool(raw.get("revoked")),
        "revokedAt": raw.get("revokedAt"),
        "revocationEpoch": raw.get("revocationEpoch", 0),
        "sample": sample,
        "sampleAvailable": bool(sample) or bool(raw.get("sampleAvailable")
                                               or raw.get("sample")),
        "path": str(raw.get("path") or ""),
        "versions": raw.get("versions") if isinstance(raw.get("versions"), list) else [],
        "publisherProof": raw.get("publisherProof"),
        "firstSeen": str(raw.get("firstSeen") or published),
    }
    return entry


def _merge_manifest(raw: dict, manifest: dict) -> dict:
    """Fill the descriptive gaps build_catalog leaves with manifest facts."""
    merged = dict(raw)
    for key in ("category", "tags", "icon", "summary", "description", "highlights",
                "license", "homepage", "requires", "minHost", "sample",
                "permissions", "optionalPermissions", "contributes", "platforms"):
        if key in manifest and not merged.get(key):
            merged[key] = manifest[key]
    if not merged.get("name") and manifest.get("name"):
        merged["name"] = manifest["name"]
    if not merged.get("publisher") and manifest.get("publisher"):
        merged["publisher"] = manifest["publisher"]
    return merged


def bundled_catalog_path() -> Path:
    """The catalog file build_bundle ships beside this module."""
    return Path(__file__).with_name("bundled-catalog.json")


def _committed_bundled() -> dict:
    """The build-time catalog and its independent digest pins."""
    document = _read_json(bundled_catalog_path())
    if not isinstance(document, dict):
        return {"schemaVersion": SCHEMA_VERSION, "generatedAt": None,
                "plugins": []}
    entries = []
    for raw in _plugins_of(document):
        if not isinstance(raw, dict):
            continue
        entry = normalize_entry(raw, "bundled")
        if entry is not None:
            entries.append(entry)
    return {"schemaVersion": SCHEMA_VERSION,
            "generatedAt": document.get("generatedAt"),
            "plugins": entries}


def build_bundled_catalog(registry_root) -> dict:
    """The bundled catalog: committed pins, enriched by the checkout.

    The committed file is authoritative for releases it names, so its digest
    is a real pin rather than a hash of whatever tree is on disk. A checkout
    only adds local plugins that have not been released into the bundle yet;
    shipped entries keep the build-time digest, and installation re-hashes
    the staged tree against it.
    """
    committed = _committed_bundled()
    if registry_root is None:
        return committed
    root = Path(registry_root)
    try:
        index_mtime = (root / "index.json").stat().st_mtime
    except OSError:
        index_mtime = 0.0
    try:
        script_mtime = _build_script().stat().st_mtime
        bundled_mtime = bundled_catalog_path().stat().st_mtime
    except OSError:
        script_mtime = 0.0
        bundled_mtime = 0.0
    key = str(root)
    cached = _BUILD_CACHE.get(key)
    if cached is not None and cached[0] == (index_mtime, script_mtime,
                                            bundled_mtime):
        return cached[1]

    catalog = {"schemaVersion": SCHEMA_VERSION,
               "generatedAt": committed.get("generatedAt"), "plugins": []}
    pins = {entry["id"]: entry for entry in committed.get("plugins") or []}
    build = _load_build_callable()
    if build is not None and (root / "index.json").is_file():
        try:
            built = build(root) or {}
            if isinstance(built, dict):
                if not catalog.get("generatedAt"):
                    catalog["generatedAt"] = built.get("generatedAt")
                index = _read_json(root / "index.json")
                index_plugins = {}
                if isinstance(index, dict) and isinstance(index.get("plugins"), list):
                    for plugin in index["plugins"]:
                        if isinstance(plugin, dict) and plugin.get("id"):
                            index_plugins[str(plugin["id"])] = plugin
                entries = []
                for raw in _plugins_of(built):
                    if not isinstance(raw, dict):
                        continue
                    plugin_id = str(raw.get("id") or "")
                    pinned = pins.get(plugin_id)
                    if pinned is not None:
                        # The build-time digest stays authoritative even if
                        # the checkout tree drifted; install fails closed.
                        # The one-line purpose lives on the manifest, which
                        # the pin does not carry.
                        enriched = dict(pinned)
                        manifest = _read_json(
                            root / "plugins" / plugin_id / "manifest.json")
                        if isinstance(manifest, dict):
                            for key in ("summary", "description", "highlights"):
                                if not enriched.get(key) and manifest.get(key):
                                    enriched[key] = manifest[key]
                        entries.append(enriched)
                        continue
                    manifest = _read_json(root / "plugins" / plugin_id / "manifest.json")
                    if isinstance(manifest, dict):
                        raw = _merge_manifest(raw, manifest)
                    indexed = index_plugins.get(plugin_id)
                    if isinstance(indexed, dict) and not raw.get("risk"):
                        raw["risk"] = indexed.get("risk")
                        raw.setdefault("name", indexed.get("name"))
                    entry = normalize_entry(raw, "bundled")
                    if entry is not None:
                        entries.append(entry)
                catalog["plugins"] = entries
        except Exception:  # noqa: BLE001 - a broken checkout keeps the committed pins
            catalog["plugins"] = []
    _BUILD_CACHE[key] = ((index_mtime, script_mtime, bundled_mtime), catalog)
    return catalog


def resolve_registry_root(workspace_dir):
    """Find the registry root: repo checkout, then workspace copies, else None."""
    repo = Path(__file__).resolve().parents[3] / "registry"
    if (repo / "index.json").is_file():
        return repo
    if workspace_dir is None:
        return None
    workspace = Path(workspace_dir)
    for candidate in (workspace / "registry",
                      workspace / "marketplace" / "registry"):
        if (candidate / "index.json").is_file():
            return candidate
    return None


def load_catalog_file(path, source: str) -> list:
    """Read an org/peer catalog JSON file; a missing or bad file is empty."""
    document = _read_json(Path(path))
    if document is None:
        return []
    entries = []
    for raw in _plugins_of(document):
        entry = normalize_entry(raw, source)
        if entry is not None:
            entries.append(entry)
    return entries


def read_json_catalog(path, source: str) -> list:
    """Alias kept explicit for callers that want the source label named."""
    return load_catalog_file(path, source)


def merge_catalogs(bundled, org, peer, installed=None) -> list:
    """Merge catalogs with org > bundled > peer precedence per plugin id.

    Installed entries are appended only when the installed catalog is
    supplied; that mirrors how /installed is built from the runtime rather
    than from the published catalog.
    """
    merged: list = []
    seen: set[str] = set()
    for catalog, source in ((org, "org"), (bundled, "bundled"), (peer, "peer")):
        for raw in _plugins_of(catalog):
            entry = normalize_entry(raw, source) if not (
                isinstance(raw, dict) and raw.get("source") == source
                and "signature" in raw) else dict(raw)
            if entry is None or entry["id"] in seen:
                continue
            entry["source"] = source
            seen.add(entry["id"])
            merged.append(entry)
    for raw in _plugins_of(installed):
        entry = normalize_entry(raw, "installed")
        if entry is None:
            continue
        entry["source"] = "installed"
        merged.append(entry)
    return merged


def card(entry: dict) -> dict:
    """The catalog list card: the discovery fields only."""
    return {
        "id": entry.get("id", ""),
        "name": entry.get("name", ""),
        "version": entry.get("version", ""),
        "publisher": entry.get("publisher", ""),
        "publisherVerified": bool(entry.get("publisherVerified")),
        "category": entry.get("category", ""),
        "tags": list(entry.get("tags") or []),
        "summary": entry.get("summary", ""),
        "icon": entry.get("icon", "plugin"),
        "riskTier": entry.get("riskTier", ""),
        "source": entry.get("source", ""),
        "eligible": bool(entry.get("eligible")),
        "ineligibleReasons": list(entry.get("ineligibleReasons") or []),
        "deprecated": entry.get("deprecated"),
        "yanked": bool(entry.get("yanked")),
        "sampleAvailable": bool(entry.get("sampleAvailable")),
    }


def detail(entry: dict) -> dict:
    """The detail DTO: one shape shared with the SPA surfaces."""
    payload = card(entry)
    payload.update({
        "description": entry.get("description", ""),
        "highlights": list(entry.get("highlights") or []),
        "license": entry.get("license", ""),
        "homepage": entry.get("homepage", ""),
        "requires": dict(entry.get("requires") or {}),
        "minHost": entry.get("minHost", ""),
        "digest": entry.get("digest", ""),
        "signature": dict(entry.get("signature") or {}),
        "provenance": dict(entry.get("provenance") or {}),
        "capabilities": {
            "sources": list((entry.get("capabilities") or {}).get("sources") or []),
            "permissions": list((entry.get("capabilities") or {}).get("permissions") or []),
            "elementKinds": list((entry.get("capabilities") or {}).get("elementKinds") or []),
            "filesystem": list((entry.get("capabilities") or {}).get("filesystem") or []),
            "network": list((entry.get("capabilities") or {}).get("network") or []),
        },
        "changelog": dict(entry.get("changelog") or {}),
        "publishedAt": entry.get("publishedAt", ""),
        "validation": {
            "checkedAt": (entry.get("validation") or {}).get("checkedAt", ""),
            "ok": (entry.get("validation") or {}).get("ok"),
            "failures": list((entry.get("validation") or {}).get("failures") or []),
        },
    })
    return payload


def filter_entries(entries, *, q: str = "", category: str = "",
                   source: str = "", risk: str = "", eligible_only: bool = False):
    """Compose the catalog filters; every supplied filter must pass."""
    query = (q or "").strip().lower()
    categories = {part.strip().lower() for part in (category or "").split(",") if part.strip()}
    sources = {part.strip() for part in (source or "").split(",") if part.strip()}
    ceiling = risk_rank(risk) if risk else None
    result = []
    for entry in entries:
        if query:
            haystack = " ".join([
                str(entry.get("id", "")), str(entry.get("name", "")),
                str(entry.get("summary", "")), " ".join(entry.get("tags") or []),
                str(entry.get("publisher", "")),
            ]).lower()
            if query not in haystack:
                continue
        if categories and str(entry.get("category", "")).lower() not in categories:
            continue
        if sources and str(entry.get("source", "")) not in sources:
            continue
        if risk:
            rank = risk_rank(entry.get("riskTier"))
            if rank is None or ceiling is None or rank > ceiling:
                continue
        if eligible_only and not entry.get("eligible"):
            continue
        result.append(entry)
    return result
