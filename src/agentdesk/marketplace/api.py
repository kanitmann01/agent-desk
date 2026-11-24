"""The marketplace JSON API.

Handlers run on the live DashboardHandler after app.py's existing _gate
(session cookie plus same-origin Host/Origin checks), so no authentication
logic is duplicated here. Every response uses the stable envelope
{"error", "message", "details"} on failure, and mutations delegate to the
installed PluginRuntime instead of reimplementing install state.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from ..plugins.render import PluginRenderError, render_sample
from ..plugins.runtime import PluginError
from ..registry.install import tree_digest
from ..trust import TrustError
from ..validator.core import validate_plugin
from . import signed_policy
from .catalog import (
    build_bundled_catalog,
    card,
    detail,
    filter_entries,
    load_catalog_file,
    merge_catalogs,
    normalize_entry,
)
from .policy import (
    POLICY_FILE,
    RISK_TIERS,
    Policy,
    evaluate,
    load_effective_policy,
    policy_payload,
    risk_rank,
)

PREFIX = "/api/marketplace"
PENDING_DIR = "pending"
GOVERNANCE_FILE = "governance.json"
ORG_CATALOG_FILE = "org-catalog.json"
PEER_CATALOG_FILE = "peer-catalog.json"
REPORTS_FILE = "reports.json"
AUDIT_FILE = "audit.json"
VALIDATION_FILE = "validation.json"
ADMIN_ENV = "AGENTDESK_MARKETPLACE_ADMIN"

# Static, server-rendered Trust Center copy: what the marketplace actually
# promises today, each clause backed by a check in this codebase.
GUARANTEES = (
    "Every install, pack install and update hashes the staged plugin tree and "
    "compares it with the digest pinned in the catalog; an unpinned or "
    "mismatched tree is refused before the runtime stores it.",
    "A release becomes eligible only when its declared risk tier is within the "
    "active policy and its catalog signature status (signed, bundled, or "
    "org-approved) is accepted by that policy.",
    "Signature status is a catalog and policy check (signed, bundled, or "
    "org-approved); the release signature is not cryptographically "
    "re-verified at install time.",
    "A plugin can read only the data sources and capabilities its manifest "
    "declares, and the widget footer names the source on every read.",
    "Network access is denied unless the destination host appears in the "
    "enterprise policy allowlist.",
    "The administrator kill switch removes a plugin from eligibility at once, "
    "before the next catalog read.",
    "The signed policy bundle is the record: changing the policy needs a "
    "verified bundle, not a form field.",
    "Audit events stay on this machine in the local audit store; the JSONL "
    "export is produced on request and nothing is sent to a vendor.",
)
CANNOT_HAPPEN = (
    "No plugin runs without an eligible policy decision.",
    "No tampered, expired or stale-epoch policy takes effect: the curated "
    "default stays active and an amber banner explains why.",
    "No browser form edits the policy. The signed file is the only mutation "
    "of record.",
    "No telemetry, usage counter or event leaves this machine.",
    "No admin route opens without the admin mode and a signed-in session.",
)

_PUBLISH_ACTION_SUFFIXES = ("/approve", "/reject")


class MarketplaceError(Exception):
    """A route-level failure carried straight to the error envelope."""

    def __init__(self, status: int, code: str, message: str,
                 details: dict | None = None) -> None:
        """Bind the status, code, message and details carried to the error envelope."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def _now() -> str:
    """The local wall clock as a second-precision ISO 8601 string.

    Audit and pending records carry local time with no offset."""
    return datetime.now().isoformat(timespec="seconds")


class _API:
    def __init__(self, handler) -> None:
        """Hold the live request handler for one request; no desk state is read yet."""
        self.handler = handler

    # -- shared plumbing -------------------------------------------------

    @property
    def server(self):
        """The HTTP server the request arrived on, which owns the desk's runtimes."""
        return self.handler.server

    @property
    def plugins(self):
        """The desk's plugin runtime, or None when the server was built without one."""
        return getattr(self.server, "plugins", None)

    @property
    def workspace(self) -> Path:
        """The desk's workspace folder; a temp folder when the server has no runtime.

        Marketplace state lives under this folder, so one desk's catalogs and
        audit never mix with another's."""
        runtime = self.plugins
        if runtime is not None:
            workspace = getattr(runtime, "workspace_dir", None)
            if workspace:
                return Path(workspace)
            data_dir = getattr(runtime, "data_dir", None)
            if data_dir:
                return Path(data_dir).parent / "workspace"
        return Path(tempfile.gettempdir()) / "agentdesk-marketplace"

    def marketplace_dir(self, *parts: str) -> Path:
        """A path inside this desk's marketplace state folder, joined per part."""
        return self.workspace.joinpath("marketplace", *parts)

    def send(self, status: int, payload: dict) -> None:
        """Write one JSON response through the handler's own sender."""
        self.handler._send_json(status, payload)

    def fail(self, status: int, code: str, message: str,
             details: dict | None = None) -> None:
        """Send the stable error envelope for a status the route chose itself."""
        self.send(status, {"error": code, "message": message,
                           "details": details or {}})

    def body(self) -> dict:
        """The request body parsed as a JSON object.

        A body that is absent or not an object raises the 400 envelope; the
        details name the path without its query string."""
        parsed = self.handler._read_json_body()
        if parsed is None:
            raise MarketplaceError(
                400, "marketplace:invalid-json",
                "the request body must be a JSON object",
                {"path": self.handler.path.partition("?")[0]})
        return parsed

    def _registry_root(self):
        """The registry checkout this request resolves to, or None for offline mode.

        The handler may have no resolver, and a resolver that raises means the
        registry is unavailable; both read as a missing registry, not an error."""
        resolver = getattr(self.handler, "_registry_root_for_request", None)
        if resolver is None:
            return None
        try:
            root, _origin = resolver()
        except Exception:  # noqa: BLE001 - an unreadable registry is offline mode
            return None
        return root

    def _trust_store_status(self) -> dict:
        """Describe the trust anchor at the registry root for the Trust Center.

        A present anchor.json is reported as configured, but this build does not
        re-verify release signatures against it; the note says that instead of
        implying a check that never happens."""
        root = self._registry_root()
        if root is None:
            return {"configured": False, "path": None,
                    "note": "no registry root is available"}
        anchor = Path(root) / "anchor.json"
        if anchor.is_file():
            return {"configured": True, "path": str(anchor),
                    "note": "a trust store anchor is present; this build does "
                            "not re-verify release signatures against it"}
        return {"configured": False, "path": None,
                "note": "no anchor.json at the registry root; release "
                        "signatures are status checks only"}

    # -- catalog ---------------------------------------------------------

    def _entries(self, policy=None):
        """Every catalog entry this desk can see, with policy eligibility applied.

        Org, bundled and peer catalogs merge in that precedence by plugin id; the
        governance overlay then marks a version, and evaluate() sets eligible and
        ineligibleReasons. Returns the entries and the policy they were judged by,
        so a caller can render the policy banner without a second load."""
        if policy is None:
            policy, _verification = load_effective_policy(self.workspace)
        root = self._registry_root()
        bundled = (build_bundled_catalog(root) if root is not None
                   else build_bundled_catalog(None))
        org = load_catalog_file(
            self.marketplace_dir(ORG_CATALOG_FILE), "org")
        peer = load_catalog_file(
            self.marketplace_dir(PEER_CATALOG_FILE), "peer")
        governance = self._governance()
        entries = []
        for entry in merge_catalogs(bundled, org, peer):
            entry = self._apply_governance(entry, governance)
            installed = False
            record = self._record(entry.get("id", ""))
            installed = record is not None and record.get("state") != "uninstalled"
            decision = evaluate(entry, policy, installed=installed)
            entry["eligible"] = decision["eligible"]
            entry["ineligibleReasons"] = decision["reasons"]
            entries.append(entry)
        return entries, policy

    def _apply_governance(self, entry: dict, governance: dict) -> dict:
        """Overlay the administrator's governance record onto one catalog entry.

        A quarantine, yank or deprecation record applies only to the version it
        names, so another release of the same plugin keeps its status. A
        quarantine also carries a deprecation block, because the card has one
        place to explain why a plugin is refused. Returns a copy; the input entry
        is not mutated."""
        entry = dict(entry)
        plugins = governance.get("plugins") if isinstance(governance, dict) else None
        record = plugins.get(entry.get("id")) if isinstance(plugins, dict) else None
        if not isinstance(record, dict):
            return entry
        version = entry.get("version")
        for action in ("quarantined", "yanked", "deprecated"):
            item = record.get(action)
            if not isinstance(item, dict):
                continue
            if item.get("version") and version and item["version"] != version:
                continue
            if action == "deprecated":
                entry["deprecated"] = {
                    "reason": str(item.get("reason") or ""),
                    "advisory": str(item.get("advisory") or item.get("reason") or ""),
                    "replacement": item.get("replacement"),
                }
            elif action == "yanked":
                entry["yanked"] = True
            else:
                entry["quarantined"] = True
                entry["deprecated"] = {
                    "reason": str(item.get("reason") or "quarantined"),
                    "advisory": "quarantined: " + str(item.get("reason") or ""),
                    "replacement": item.get("replacement"),
                }
        return entry

    def _record(self, plugin_id: str):
        """The runtime's install record for one plugin id, or None when unknown.

        A runtime that does not know the id raises PluginError; a failed lookup
        reads as not installed, so a catalog listing still renders."""
        if self.plugins is None or not plugin_id:
            return None
        try:
            return self.plugins.record(plugin_id)
        except PluginError:
            return None

    def _find_entry(self, plugin_id: str):
        """Resolve one requested id to its entry, the entry list and the policy.

        An id with no catalog entry still resolves from a live install record, so
        a locally built plugin has a detail page; the catalog listing itself stays
        catalog-only. Raises 404 when the id names neither a catalog entry nor a
        live install."""
        entries, policy = self._entries()
        for entry in entries:
            if entry.get("id") == plugin_id:
                return entry, entries, policy
        # A wizard install (any local install, really) is in no catalog:
        # the requested id still resolves, from the installed record
        # itself. The listing above stays catalog-only, so the Discover
        # surface never gains an installed-only entry; only the
        # resolution of one requested id falls back to installed. The
        # approved screen's manage link depends on this (T6 review).
        synthesized = self._installed_entry(plugin_id, policy)
        if synthesized is not None:
            return synthesized, entries, policy
        raise MarketplaceError(
            404, "catalog:not-found",
            f"no catalog entry for plugin {plugin_id}", {"id": plugin_id})

    def _installed_entry(self, plugin_id: str, policy) -> dict | None:
        """One catalog-shaped entry synthesized from the installed record.

        The runtime carries name, version, digest and the installed
        manifest; a wizard build never published a catalog entry. The
        shared normalize_entry keeps the exact detail DTO shape, the
        same policy evaluate() the listing applies decides eligibility,
        and governance (quarantine, yank, deprecation) rides on top, so
        a refused plugin looks refused here too. None when the id names
        no live install."""
        record = self._record(plugin_id)
        if record is None or record.get("state") == "uninstalled":
            return None
        manifest = self._installed_manifest(record)
        raw = {
            **manifest,
            "id": str(record.get("id") or plugin_id),
            "name": str(manifest.get("name") or record.get("name") or plugin_id),
            "version": str(record.get("active_version")
                           or manifest.get("version") or ""),
            "digest": str(record.get("sha256") or ""),
            "publishedAt": str(record.get("installed_at") or ""),
            "source": "installed",
            "versions": [
                {"version": str(item.get("version") or ""),
                 "sha256": str(item.get("sha256") or "")}
                for item in (record.get("versions") or [])
                if isinstance(item, dict)
            ],
        }
        entry = normalize_entry(raw, "installed")
        if entry is None:
            return None
        decision = evaluate(entry, policy, installed=True)
        entry["eligible"] = decision["eligible"]
        entry["ineligibleReasons"] = decision["reasons"]
        entry = self._apply_governance(entry, self._governance())
        return entry

    def _installed_manifest(self, record: dict) -> dict:
        """The active version's manifest from the runtime's own tree."""
        versions = record.get("versions")
        folder = ""
        if isinstance(versions, list) and versions:
            last = versions[-1]
            if isinstance(last, dict):
                folder = str(last.get("dir") or "")
        if not folder:
            folder = str(record.get("folder") or "")
        if not folder:
            return {}
        document = signed_policy.read_json(Path(folder) / "manifest.json", {})
        return document if isinstance(document, dict) else {}

    def _installed_summary(self, record: dict) -> dict:
        """The installed-plugin DTO the Installed surface renders.

        Pending update, live data-source status and the shared flag come from the
        runtime record; a configured peer store is the authority on sharing, and a
        broken store reads as not shared. dataDirSize counts bytes on disk."""
        pending = record.get("pending_update")
        data_source = record.get("data_source")
        if not isinstance(data_source, dict):
            data_source = {}
        pending_scopes = list((pending or {}).get("added_scopes") or [])
        peer_store = getattr(self.server, "peer_store", None)
        if peer_store is not None:
            try:
                shared = record.get("id", "") in peer_store.shared_ids()
            except Exception:  # noqa: BLE001 - a broken store is not a share
                shared = False
        else:
            shared = bool(record.get("shared"))
        return {
            "id": record.get("id", ""),
            "name": record.get("name", record.get("id", "")),
            "version": record.get("active_version", ""),
            "pinned": {"version": record.get("active_version", ""),
                       "sha256": record.get("sha256", "")},
            "status": {
                "status": data_source.get("status", "unknown"),
                "cause": data_source.get("cause", ""),
                "checked_at": data_source.get("checked_at", ""),
            },
            "pilot": {"views": record.get("pilot_views_left", 0),
                      "remaining": record.get("pilot_views_left", 0)},
            "update": ({
                "version": pending.get("version", ""),
                "digest": pending.get("sha256", ""),
                "widening": pending_scopes,
                "scopes": pending_scopes,
            } if isinstance(pending, dict) else None),
            "pendingConsent": isinstance(pending, dict),
            "shared": shared,
            "enabled": record.get("state") == "enabled",
            "dataDirSize": self._dir_size(record.get("data_dir")),
        }

    @staticmethod
    def _dir_size(path) -> int:
        """Total bytes of the regular files under a plugin's data directory.

        Unreadable entries are skipped and a missing path is zero bytes, so the
        result is a measurement rather than a failure."""
        total = 0
        if not path:
            return total
        root = Path(path)
        if not root.is_dir():
            return total
        for item in root.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
        return total

    # -- GET routes ------------------------------------------------------

    def get(self, path: str, query: dict) -> None:
        """Dispatch a GET under the marketplace prefix to its route.

        An unknown route answers 404 in the error envelope instead of raising out
        of the handler."""
        route = path[len(PREFIX):]
        if route == "/catalog":
            self.get_catalog(query)
        elif route.startswith("/plugin/"):
            self.get_plugin(route[len("/plugin/"):], query)
        elif route == "/installed":
            self.get_installed()
        elif route == "/packs":
            self.get_packs()
        elif route.startswith("/publisher/"):
            self.get_publisher(route[len("/publisher/"):])
        elif route == "/policy":
            self.get_policy()
        elif route == "/audit":
            self.get_audit(query)
        elif route == "/audit/export":
            self.get_audit_export()
        elif route == "/admin":
            self.get_admin()
        elif route == "/trust":
            self.get_trust()
        else:
            self.fail(404, "catalog:not-found",
                      f"no marketplace route at {path}", {"path": path})

    def get_catalog(self, query: dict) -> None:
        """The filtered catalog listing, with per-source counts and the policy banner.

        Filters are the q, category, source, risk and eligible query parameters;
        risk is a ceiling, so a T2 filter keeps T0 through T2. Counts are taken
        before filtering, so every source chip shows its unfiltered total."""
        entries, policy = self._entries()
        counts: dict[str, int] = {}
        for entry in entries:
            source = entry.get("source", "")
            counts[source] = counts.get(source, 0) + 1
        filtered = filter_entries(
            entries,
            q=query.get("q", ""),
            category=query.get("category", ""),
            source=query.get("source", ""),
            risk=query.get("risk", ""),
            eligible_only=query.get("eligible", "").lower() in ("1", "true", "yes"),
        )
        sources = [{"source": source, "count": counts[source]}
                   for source in ("bundled", "org", "peer", "installed")
                   if counts.get(source)]
        self.send(200, {
            "entries": [card(entry) for entry in filtered],
            "total": len(filtered),
            "sources": sources,
            "policy": {"mode": policy.mode, "source": policy.source,
                       "signatureStatus": policy.signatureStatus},
        })

    def get_plugin(self, plugin_id: str, query: dict) -> None:
        """One plugin's detail payload: detail, installed state, versions and sample.

        A version query must name a version the entry lists, and a missing one is a
        404 rather than a silent fallback to the current release. Alternatives are
        up to five other entries in the same category. An entry that carries no
        stored sample has one rendered from its plugin folder; a broken fixture
        stays null."""
        entry, entries, policy = self._find_entry(plugin_id)
        requested = query.get("version", "")
        versions = self._versions(entry)
        if requested and requested not in [item["version"] for item in versions]:
            raise MarketplaceError(
                404, "catalog:not-found",
                f"plugin {plugin_id} has no version {requested}",
                {"id": plugin_id, "version": requested})
        record = self._record(plugin_id)
        alternatives = [
            card(other) for other in entries
            if other.get("id") != plugin_id
            and other.get("category") == entry.get("category")
        ][:5]
        sample = entry.get("sample")
        if not isinstance(sample, dict):
            # The bundled catalog is built from registry manifests and does
            # not carry the rendered fixture. Render it from the plugin
            # folder so the detail page can show a live sample; a broken
            # fixture stays an honest null, never an invented one.
            sample = self._rendered_sample(entry)
        if isinstance(sample, dict):
            sample = {
                "elements": list(sample.get("elements") or []),
                "status": str(sample.get("status") or ""),
                "cause": str(sample.get("cause") or ""),
                "checked_at": sample.get("checked_at") or sample.get("checkedAt"),
            }
        else:
            sample = None
        self.send(200, {
            "plugin": detail(entry),
            "installed": self._installed_summary(record) if record else None,
            "versions": versions,
            "alternatives": alternatives,
            "sample": sample,
        })

    def _versions(self, entry: dict) -> list:
        """Every known version of an entry, the current release first.

        The current version leads with the entry's digest and yank flag; declared
        versions follow in order with repeats dropped. An entry with no version
        still yields one row, so a detail page always has a version to show."""
        versions = [{"version": entry.get("version", ""),
                     "digest": entry.get("digest", ""),
                     "yanked": bool(entry.get("yanked"))}]
        seen = {entry.get("version", "")}
        for raw in entry.get("versions") or []:
            if not isinstance(raw, dict):
                continue
            version = str(raw.get("version") or "")
            if not version or version in seen:
                continue
            seen.add(version)
            versions.append({"version": version,
                             "digest": str(raw.get("sha256") or raw.get("digest") or ""),
                             "yanked": bool(raw.get("yanked"))})
        return versions

    def get_installed(self) -> None:
        """Every installed plugin, sorted by id, with the policy banner.

        Without a plugin runtime the route answers 503 rather than an empty list,
        because an empty list would claim nothing is installed."""
        if self.plugins is None:
            raise MarketplaceError(503, "marketplace:unavailable",
                                   "no plugin runtime is configured")
        policy, _verification = load_effective_policy(self.workspace)
        records = sorted(self.plugins.list_records(), key=lambda item: item.get("id", ""))
        self.send(200, {
            "plugins": [self._installed_summary(record) for record in records],
            "policy": {"mode": policy.mode, "source": policy.source,
                       "signatureStatus": policy.signatureStatus},
        })

    def _rendered_sample(self, entry: dict):
        """Render a plugin's sample card from its folder, or None when it fails.

        The bundled catalog is built from manifests and carries no rendered
        fixture, so the detail page renders one; a broken fixture stays an honest
        null."""
        plugin_dir = self._plugin_dir(entry)
        if plugin_dir is None:
            return None
        try:
            return render_sample(plugin_dir)
        except (PluginRenderError, OSError, ValueError):
            return None

    def _pack_document(self) -> dict:
        """The registry's packs.json, or an empty document without a registry root."""
        root = self._registry_root()
        if root is None:
            return {"schemaVersion": 1, "packs": []}
        document = signed_policy.read_json(Path(root) / "packs.json", {})
        return document if isinstance(document, dict) else {"schemaVersion": 1, "packs": []}

    def get_packs(self) -> None:
        """Every pack the registry declares, resolved against the visible catalog."""
        entries, policy = self._entries()
        by_id = {entry.get("id"): entry for entry in entries}
        document = self._pack_document()
        packs = []
        for raw in document.get("packs") or []:
            if not isinstance(raw, dict):
                continue
            pack = self._pack_payload(raw, by_id)
            packs.append(pack)
        self.send(200, {
            "packs": packs,
            "total": len(packs),
            "policy": {"mode": policy.mode, "source": policy.source,
                       "signatureStatus": policy.signatureStatus},
        })

    def _pack_payload(self, raw: dict, by_id: dict) -> dict:
        """The pack DTO: member cards, member scopes and the first blocking member.

        A member the catalog does not carry stays in the list as ineligible with a
        catalog:not-found reason, so the pack page explains the gap instead of
        dropping the member. blockedMember and blockedReason name the first
        failure, and eligible is false when there is one."""
        members = []
        cards = []
        blocked = None
        for plugin_id in raw.get("plugins") or []:
            if not isinstance(plugin_id, str):
                continue
            entry = by_id.get(plugin_id)
            if entry is None:
                member = {
                    "id": plugin_id, "name": plugin_id, "version": "",
                    "eligible": False, "ineligibleReasons": [{
                        "code": "catalog:not-found",
                        "message": "This plugin is not in the catalog this desk can see.",
                    }],
                    "scopes": [],
                }
            else:
                member = {
                    "id": entry.get("id", ""),
                    "name": entry.get("name", ""),
                    "version": entry.get("version", ""),
                    "eligible": bool(entry.get("eligible")),
                    "ineligibleReasons": list(entry.get("ineligibleReasons") or []),
                    "scopes": self._member_scopes(entry),
                }
                cards.append(card(entry))
            if not member["eligible"] and blocked is None:
                reason = (member["ineligibleReasons"] or [{}])[0]
                blocked = {"id": member["id"], "name": member["name"],
                           "message": reason.get("message", "This plugin is not eligible.")}
            members.append(member)
        excluded = []
        for item in raw.get("excluded") or []:
            if isinstance(item, dict) and item.get("id"):
                excluded.append({"id": str(item["id"]),
                                 "reason": str(item.get("reason") or "")})
        return {
            "id": str(raw.get("id") or ""),
            "name": str(raw.get("name") or raw.get("id") or ""),
            "audience": str(raw.get("audience") or ""),
            "summary": str(raw.get("summary") or ""),
            "icon": str(raw.get("icon") or "plugin"),
            "excluded": excluded,
            "sampleData": bool(raw.get("sampleData")),
            "firstRun": bool(raw.get("firstRun")),
            "plugins": cards,
            "members": members,
            "eligible": blocked is None,
            "blockedMember": blocked["id"] if blocked else None,
            "blockedReason": blocked["message"] if blocked else "",
        }

    def _member_scopes(self, entry: dict) -> list:
        """The scopes a pack member asks for, preferring the staged manifest.

        A plugin whose files are not on this desk falls back to the permissions the
        catalog declared."""
        plugin_dir = self._plugin_dir(entry)
        if plugin_dir is not None:
            scopes = self._manifest_scopes(plugin_dir)
            if scopes:
                return scopes
        return list((entry.get("capabilities") or {}).get("permissions") or [])

    def get_publisher(self, name: str) -> None:
        """A publisher page: their entries, verification, proof and first sighting.

        The name match is case-insensitive. verified is true when any entry carries
        publisherVerified, proof is the first non-empty proof, and firstSeen is the
        earliest entry date, empty when none is known."""
        entries, _policy = self._entries()
        matches = [entry for entry in entries
                   if str(entry.get("publisher", "")).lower() == name.lower()]
        if not matches:
            raise MarketplaceError(
                404, "catalog:not-found",
                f"no catalog entries from publisher {name}", {"publisher": name})
        verified = any(entry.get("publisherVerified") for entry in matches)
        proof = next((entry.get("publisherProof") for entry in matches
                      if entry.get("publisherProof")), None)
        first_seen = min(
            (entry.get("firstSeen") or entry.get("publishedAt") or "")
            for entry in matches) or ""
        self.send(200, {
            "publisher": name,
            "verified": verified,
            "proof": proof,
            "plugins": [card(entry) for entry in matches],
            "firstSeen": first_seen,
        })

    def get_policy(self) -> None:
        """The effective policy with its verification block, as JSON."""
        policy, verification = load_effective_policy(self.workspace)
        self.send(200, policy_payload(policy, verification))

    def get_audit(self, query: dict) -> None:
        """One page of audit events after a cursor.

        Admin only, like the export: with admin mode off nothing is served on
        either audit read. since is an index into the store and limit is
        clamped to 1..200; next is the cursor for the following page, or null
        at the end. Malformed parameters fall back to the first page."""
        self._require_admin()
        events = self._audit_events()
        try:
            since = max(int(query.get("since", 0) or 0), 0)
        except (TypeError, ValueError):
            since = 0
        try:
            limit = max(1, min(int(query.get("limit", 50) or 50), 200))
        except (TypeError, ValueError):
            limit = 50
        window = events[since:since + limit]
        next_cursor = since + len(window)
        self.send(200, {"events": window,
                        "next": next_cursor if next_cursor < len(events) else None})
    # -- admin, trust and evidence (T13) --------------------------------

    @staticmethod
    def admin_enabled() -> bool:
        """Admin mode is an environment switch, read on every request."""
        return os.environ.get(ADMIN_ENV, "").strip() == "1"

    def _require_admin(self) -> None:
        """Refuse the request unless the admin environment switch is on."""
        if not self.admin_enabled():
            raise MarketplaceError(
                403, "admin:disabled",
                "the marketplace admin surface is disabled; set "
                f"{ADMIN_ENV}=1 and reload the server",
                {"env": ADMIN_ENV})

    def get_admin(self) -> None:
        """The admin snapshot: policy posture, anchor, pending work and inventory.

        Requires admin mode. The policy block reports the verification verdict, not
        the policy body, which /policy already serves."""
        self._require_admin()
        policy, verification = load_effective_policy(self.workspace)
        self.send(200, {
            "posture": {
                "mode": policy.mode,
                "riskCeiling": policy.riskCeiling,
                "requireSignatures": policy.requireSignatures,
                "killSwitch": sorted(policy.killSwitch or ()),
                "allowedPublishers": sorted(policy.allowedPublishers or ()),
                "allowedCategories": sorted(policy.allowedCategories or ()),
                "networkAllowlist": sorted(policy.networkAllowlist or ()),
                "enabledSources": sorted(policy.enabledSources or ()),
            },
            "anchor": signed_policy.load_anchor(self.workspace),
            "policy": {
                "signatureStatus": verification.get("signatureStatus"),
                "warning": verification.get("warning"),
                "epoch": verification.get("epoch", 0),
                "signerFingerprint": verification.get("signerFingerprint"),
                "expiresAt": verification.get("expiresAt"),
            },
            "pending": self._pending_publications(),
            "revoked": self._revoked_entries(),
            "inventory": self._inventory(policy),
            "catalogSource": self._catalog_source(),
            "auditEvents": len(self._audit_events()),
        })

    def get_trust(self) -> None:
        """The Trust Center snapshot: anchor, policy, last validation and the copy.

        The guarantee list is static server text with the live trust-store note
        appended, so the page never claims a check this build does not run."""
        policy, verification = load_effective_policy(self.workspace)
        trust_store = self._trust_store_status()
        self.send(200, {
            "anchor": signed_policy.load_anchor(self.workspace),
            "policy": policy_payload(policy, verification),
            "lastValidatorRun": self._last_validator_run(),
            "guarantees": [*GUARANTEES,
                           f"Trust store: {trust_store['note']}."],
            "cannotHappen": list(CANNOT_HAPPEN),
            "trustStore": trust_store,
            "reportPath": "/marketplace/report",
        })

    def get_audit_export(self) -> None:
        """Download the audit store as NDJSON.

        Admin only. Each line carries the five evidence columns (time, action,
        plugin, actor, outcome) and no message body, note or reason."""
        self._require_admin()
        lines = []
        for event in self._audit_events():
            # Evidence, not content: no message bodies, notes or reasons.
            line = {key: event.get(key, "")
                    for key in ("at", "action", "pluginId", "actor", "outcome")}
            lines.append(json.dumps(line, sort_keys=True))
        body = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
        self.handler._send_bytes(
            200, body, "application/x-ndjson; charset=utf-8",
            {"Content-Disposition":
             'attachment; filename="marketplace-audit.jsonl"'})

    def _catalog_source(self) -> str:
        """Name the catalog the desk serves from: 'org' when an org entry exists,
        otherwise 'bundled'."""
        document = signed_policy.read_json(self.marketplace_dir(ORG_CATALOG_FILE), None)
        plugins = document.get("plugins") if isinstance(document, dict) else None
        if isinstance(plugins, list) and any(
                isinstance(item, dict) and item.get("id") for item in plugins):
            return "org"
        return "bundled"

    def _manifest_of(self, record: dict) -> dict:
        """A pending publication's manifest: the inline copy, else the staged one.

        The staged copy is read from the record's folder; a missing or unreadable
        manifest.json reads as an empty mapping."""
        manifest = record.get("manifest")
        if isinstance(manifest, dict) and manifest:
            return manifest
        folder = record.get("folder")
        if not isinstance(folder, str) or not folder.strip():
            return {}
        document = signed_policy.read_json(Path(folder) / "manifest.json", {})
        return document if isinstance(document, dict) else {}

    def _pending_publications(self) -> list:
        """Publications waiting for an admin decision, ordered by pending file name.

        The id is the record's pendingId, falling back to the file name; the plugin
        id, version and publisher come from the manifest, which may be missing."""
        directory = self.marketplace_dir(PENDING_DIR)
        if not directory.is_dir():
            return []
        items = []
        for path in sorted(directory.glob("*.json")):
            record = signed_policy.read_json(path, None)
            if not isinstance(record, dict):
                continue
            manifest = self._manifest_of(record)
            items.append({
                "id": str(record.get("pendingId") or path.stem),
                "pluginId": str(manifest.get("id") or ""),
                "version": str(manifest.get("version") or ""),
                "publisher": str(manifest.get("publisher") or ""),
                "submittedAt": str(record.get("queuedAt") or ""),
                "changelog": str(record.get("changelog") or ""),
                "validation": record.get("validation"),
            })
        return items

    def _revoked_entries(self) -> list:
        """Quarantine and yank records as admin rows, stamped with the policy epoch.

        Deprecation is advisory and stays out of this list; the epoch is the one the
        active policy enforces, not the record's own."""
        policy, _verification = load_effective_policy(self.workspace)
        governance = self._governance()
        plugins = governance.get("plugins") if isinstance(governance, dict) else None
        items = []
        if isinstance(plugins, dict):
            for plugin_id in sorted(plugins):
                record = plugins.get(plugin_id)
                if not isinstance(record, dict):
                    continue
                for action in ("quarantined", "yanked"):
                    item = record.get(action)
                    if not isinstance(item, dict):
                        continue
                    items.append({
                        "id": str(plugin_id),
                        "version": str(item.get("version") or ""),
                        "action": action,
                        "reason": str(item.get("reason") or ""),
                        "at": str(item.get("at") or ""),
                        "epoch": int(policy.minRevocationEpoch or 0),
                    })
        return items

    def _inventory(self, policy) -> list:
        """One row per installed plugin: version, digest, enabled and eligibility.

        An installed plugin with no catalog entry is judged from its id alone, so
        the source rule refuses it instead of it disappearing from the list."""
        entries, _policy = self._entries(policy)
        by_id = {entry.get("id", ""): entry for entry in entries}
        records = self.plugins.list_records() if self.plugins is not None else []
        items = []
        for record in sorted(records, key=lambda item: item.get("id", "")):
            if record.get("state") == "uninstalled":
                continue
            plugin_id = str(record.get("id") or "")
            entry = by_id.get(plugin_id) or {"id": plugin_id}
            decision = evaluate(entry, policy, installed=True)
            items.append({
                "id": plugin_id,
                "version": str(record.get("active_version") or ""),
                "publisher": str(entry.get("publisher") or ""),
                "digest": str(record.get("sha256") or ""),
                "enabled": record.get("state") == "enabled",
                "eligible": decision["eligible"],
                "reasons": decision["reasons"],
            })
        return items

    def _record_validation(self, validation: dict, scope: str, subject: str) -> None:
        """Persist the last validator verdict the Trust Center reports."""
        signed_policy.write_json(self.marketplace_dir(VALIDATION_FILE), {
            "at": _now(),
            "ok": bool(validation.get("ok")),
            "failures": [failure for failure in validation.get("failures") or ()
                         if isinstance(failure, dict)],
            "scope": scope,
            "subject": subject,
        })

    def _last_validator_run(self) -> dict:
        """The last recorded validator verdict, or an all-null block when none ran."""
        document = signed_policy.read_json(self.marketplace_dir(VALIDATION_FILE), None)
        if not isinstance(document, dict):
            return {"at": None, "ok": None, "failures": [], "scope": None}
        return {
            "at": document.get("at"),
            "ok": document.get("ok"),
            "failures": [failure for failure in document.get("failures") or ()
                         if isinstance(failure, dict)],
            "scope": document.get("scope"),
        }


    # -- file-backed state ----------------------------------------------

    def _governance(self) -> dict:
        """The admin governance record; a missing or broken file is empty."""
        document = signed_policy.read_json(self.marketplace_dir(GOVERNANCE_FILE), {})
        return document if isinstance(document, dict) else {}

    def _audit_events(self) -> list:
        """The local audit store's rows, dropping anything that is not an object."""
        document = signed_policy.read_json(self.marketplace_dir(AUDIT_FILE), [])
        return [item for item in document if isinstance(item, dict)] if isinstance(
            document, list) else []

    def audit(self, action: str, plugin_id: str, outcome: str, detail_text: str = "") -> None:
        """Append one admin action to the local audit store.

        The store keeps the most recent 1000 events; older rows are dropped."""
        events = self._audit_events()
        events.append({"at": _now(), "action": action, "pluginId": plugin_id,
                       "actor": "local-admin", "outcome": outcome,
                       "detail": detail_text})
        signed_policy.write_json(self.marketplace_dir(AUDIT_FILE), events[-1000:])

    def _deny(self, decision: dict) -> None:
        """Raise the first policy reason as a 403, carrying every reason in details.

        A decision with no reasons still refuses, under policy:source-not-enabled."""
        reasons = decision.get("reasons") or []
        first = reasons[0] if reasons else {
            "code": "policy:source-not-enabled", "message": "the entry is not eligible"}
        raise MarketplaceError(
            403, first.get("code", "policy:source-not-enabled"),
            first.get("message", "the entry is not eligible"),
            {"reasons": reasons})

    # -- install/update helpers -----------------------------------------

    def _plugin_dir(self, entry: dict):
        """Locate a catalog entry's plugin folder on this desk, or None.

        Candidates are the entry's own path, the registry checkout, then a staged
        copy under the marketplace folder; only a folder holding manifest.json
        counts."""
        candidates = []
        raw = entry.get("path")
        if raw:
            path = Path(raw)
            candidates.append(path if path.is_absolute()
                              else self.marketplace_dir(path))
        root = self._registry_root()
        if root is not None:
            candidates.append(Path(root) / "plugins" / str(entry.get("id", "")))
        candidates.append(self.marketplace_dir("plugins", str(entry.get("id", ""))))
        for candidate in candidates:
            if candidate.is_dir() and (candidate / "manifest.json").is_file():
                return candidate
        return None

    @staticmethod
    def _granted_scopes(manifest: dict) -> set:
        """Only scopes the manifest actually grants, so dropping a scope is a
        narrowing rather than a value change the runtime would treat as new."""
        items: set = set()

        def walk(prefix: str, node) -> None:
            """Flatten one permission block into 'path: value' leaves.

            A list reuses its key as the prefix, so several values for one permission
            become several leaves. None, false, an empty string and 'none' are
            skipped, so dropping a permission narrows the set instead of changing a
            value."""
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(f"{prefix}.{key}" if prefix else key, value)
            elif isinstance(node, list):
                for value in node:
                    walk(prefix, value)
            elif node is not None and node is not False and node != "" and node != "none":
                items.add(f"{prefix}: {node}")

        walk("", manifest.get("permissions") or {})
        walk("", manifest.get("optionalPermissions") or {})
        return items

    def _manifest_scopes(self, plugin_dir: Path) -> list:
        """Sorted 'path: value' scopes granted by a plugin folder's manifest.

        An unreadable or absent manifest grants nothing, which is the safe answer
        for a widening check."""
        try:
            manifest = json.loads(
                (Path(plugin_dir) / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        return sorted(self._granted_scopes(manifest))

    def _zip_dir(self, plugin_dir: Path) -> Path:
        """Zip a plugin folder into a temporary archive and return its path.

        Member names are POSIX and relative to the plugin root; the caller owns the
        file and must delete it."""
        handle = tempfile.NamedTemporaryFile(
            suffix=".zip", prefix="marketplace-", delete=False)
        handle.close()
        target = Path(handle.name)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(Path(plugin_dir).rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(plugin_dir).as_posix())
        return target

    def _runtime(self):
        """The plugin runtime, or the 503 every mutating route raises without one."""
        if self.plugins is None:
            raise MarketplaceError(503, "marketplace:unavailable",
                                   "no plugin runtime is configured")
        return self.plugins

    def _entry_for_install(self, plugin_id: str):
        """Resolve the entry to install and the folder its files come from.

        Eligibility is re-decided for a fresh install, so an installed record
        cannot excuse a policy the entry now fails; a refusal is audited before it
        is raised. Raises 409 when the entry names no readable plugin folder."""
        entry, _entries, policy = self._find_entry(plugin_id)
        decision = evaluate(entry, policy)
        if not decision["eligible"]:
            self.audit("install", plugin_id, "denied",
                       decision["reasons"][0]["code"] if decision["reasons"] else "")
            self._deny(decision)
        plugin_dir = self._plugin_dir(entry)
        if plugin_dir is None:
            raise MarketplaceError(
                409, "install:source-unavailable",
                f"the catalog entry {plugin_id} resolves to no plugin directory",
                {"id": plugin_id, "source": entry.get("source", "")})
        return entry, plugin_dir

    def _verify_tree_digest(self, entry: dict, plugin_dir) -> str:
        """Fail closed unless the staged tree matches the catalog pin."""
        plugin_id = str(entry.get("id") or "")
        pin = ""
        for key in ("digest", "sha256"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                pin = value.strip()
                break
        if not pin:
            raise MarketplaceError(
                409, "install:digest-mismatch",
                f"plugin {plugin_id} has no digest pinned in the catalog; "
                "refusing to install an unpinned tree",
                {"id": plugin_id, "pin": None})
        actual = tree_digest(plugin_dir)
        if actual != pin:
            raise MarketplaceError(
                409, "install:digest-mismatch",
                f"the staged plugin tree for {plugin_id} does not match the "
                "digest pinned in the catalog",
                {"id": plugin_id, "expected": pin, "actual": actual})
        return actual

    # -- POST routes -----------------------------------------------------

    def post(self, path: str) -> None:
        """Dispatch a POST under the marketplace prefix to its route.

        Publication decisions are matched first because their route carries the
        pending id; every other route is an exact match. An unknown route raises
        the same 404 the envelope renders."""
        route = path[len(PREFIX):]
        if route.startswith("/admin/publications/") and route.endswith(
                _PUBLISH_ACTION_SUFFIXES):
            action = "approve" if route.endswith("/approve") else "reject"
            pending_id = route[len("/admin/publications/"):-(len(action) + 1)]
            self.post_publication_decision(pending_id, action, self.body())
            return
        api = {
            "/install": self.post_install,
            "/packs/install": self.post_pack_install,
            "/validate": self.post_validate,
            "/update": self.post_update,
            "/consent": self.post_consent,
            "/rollback": self.post_rollback,
            "/uninstall": self.post_uninstall,
            "/enable": self.post_enable,
            "/disable": self.post_disable,
            "/retest": self.post_retest,
            "/manual-value": self.post_manual_value,
            "/purge-data": self.post_purge_data,
            "/report": self.post_report,
            "/share": lambda body: self._set_shared(body, True),
            "/unshare": lambda body: self._set_shared(body, False),
            "/publish": self.post_publish,
            "/studio/install": self.post_studio_install,
            "/policy/import": self.post_policy_import,
            "/admin/kill-switch": self.post_kill_switch,
            "/deprecate": lambda body: self.post_governance("deprecated", body),
            "/yank": lambda body: self.post_governance("yanked", body),
            "/quarantine": lambda body: self.post_governance("quarantined", body),
        }.get(route)
        if api is None:
            raise MarketplaceError(
                404, "catalog:not-found",
                f"no marketplace route at {path}", {"path": path})
        api(self.body())

    @staticmethod
    def _required_id(body: dict) -> str:
        """The trimmed plugin id from a request body, or a 400 naming the field."""
        plugin_id = body.get("id")
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "the request body must carry a plugin id", {"field": "id"})
        return plugin_id.strip()

    def post_install(self, body: dict) -> None:
        """Install one catalog entry onto this desk.

        The body may pin source, version and digest, and each must agree with the
        entry; only the entry's current release is installable. The staged tree
        must hash to the catalog pin before the runtime sees it, and a refusal is
        audited. A fresh install widens nothing, so widening is always empty."""
        plugin_id = self._required_id(body)
        entry, plugin_dir = self._entry_for_install(plugin_id)
        source = body.get("source")
        if isinstance(source, str) and source and source != entry.get("source"):
            raise MarketplaceError(
                404, "catalog:not-found",
                f"plugin {plugin_id} is not available from source {source}",
                {"id": plugin_id, "source": source})
        version = body.get("version")
        if isinstance(version, str) and version and version != entry.get("version"):
            raise MarketplaceError(
                404, "catalog:not-found",
                f"plugin {plugin_id} has no version {version}",
                {"id": plugin_id, "version": version})
        sha256 = body.get("sha256")
        if isinstance(sha256, str) and sha256 and entry.get("digest") and (
                sha256 != entry["digest"]):
            raise MarketplaceError(
                409, "install:digest-mismatch",
                "the requested digest does not match the catalog pin",
                {"id": plugin_id})
        runtime = self._runtime()
        try:
            self._verify_tree_digest(entry, plugin_dir)
        except MarketplaceError as exc:
            self.audit("install", plugin_id, "denied", exc.code)
            raise
        try:
            result = runtime.install(plugin_dir, source=entry.get("source", "catalog"))
        except PluginError as exc:
            raise MarketplaceError(exc.status, exc.code, str(exc),
                                   {"id": plugin_id}) from exc
        scopes = list((entry.get("capabilities") or {}).get("permissions") or [])
        self.audit("install", plugin_id, "ok", result.get("version", ""))
        self.send(200, {"id": plugin_id, "version": result.get("version", ""),
                        "scopes": scopes, "widening": [], "status": "installed"})

    # -- packs and studio validation -------------------------------------

    def _inline_manifest(self, body: dict) -> dict:
        """The request's manifest object, accepting its JSON string form.

        Studio posts the manifest as an object or as its JSON text; anything else is
        a 400 naming the manifest field."""
        manifest = body.get("manifest")
        if isinstance(manifest, str):
            try:
                manifest = json.loads(manifest)
            except json.JSONDecodeError as exc:
                raise MarketplaceError(
                    400, "marketplace:invalid-json",
                    f"manifest is not valid JSON: {exc}", {"field": "manifest"}) from exc
        if not isinstance(manifest, dict):
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "the request body must carry a manifest object",
                {"field": "manifest"})
        return manifest

    @staticmethod
    def _inline_name(manifest: dict, kind: str) -> str:
        """Pick the in-tree file name for an inline widget UI or sample document.

        The manifest may name the file, but only a relative path inside the plugin
        folder is honoured: an absolute or traversing name falls back to
        widget.ui.json or sample.json."""
        name = ""
        if kind == "widget":
            contributes = manifest.get("contributes")
            widgets = contributes.get("widgets") if isinstance(contributes, dict) else None
            if isinstance(widgets, list) and widgets and isinstance(widgets[0], dict):
                render = widgets[0].get("render")
                if isinstance(render, dict):
                    name = str(render.get("file") or "")
        else:
            name = str(manifest.get("sample") or "")
        path = Path(name) if name else None
        if (path is None or not name or path.is_absolute()
                or ".." in path.parts):
            return "widget.ui.json" if kind == "widget" else "sample.json"
        return name

    def _write_inline_plugin(self, folder: Path, body: dict) -> dict:
        """Write an inline manifest, widget UI and sample into a plugin folder.

        The widget UI and sample are written at the relative names the manifest
        declares, as text when given text and as pretty JSON otherwise. Returns the
        parsed manifest."""
        manifest = self._inline_manifest(body)
        folder.mkdir(parents=True, exist_ok=True)
        files = {"manifest.json": json.dumps(manifest, indent=2)}
        widget = body.get("widgetUi", body.get("widget_ui"))
        if widget is not None:
            files[self._inline_name(manifest, "widget")] = (
                widget if isinstance(widget, str) else json.dumps(widget, indent=2))
        sample = body.get("sample")
        if sample is not None:
            files[self._inline_name(manifest, "sample")] = (
                sample if isinstance(sample, str) else json.dumps(sample, indent=2))
        for relative, text in files.items():
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return manifest

    @staticmethod
    def _studio_manual_source(manifest: dict) -> dict | None:
        """The first widget's manual-metric data source, or None for any other kind."""
        contributes = manifest.get("contributes")
        widgets = contributes.get("widgets") if isinstance(contributes, dict) else None
        if not (isinstance(widgets, list) and widgets and isinstance(widgets[0], dict)):
            return None
        source = widgets[0].get("dataSource")
        if not isinstance(source, dict) or source.get("type") != "manual-metric":
            return None
        return source

    def _seed_studio_manual_metric(self, manifest: dict, body: dict,
                                   plugin_id: str, runtime) -> None:
        """Give a Studio-created manual metric its first file.

        The Studio card is declared over ${pluginData}/manual.json, and
        the manual-metric source does not invent a file: without this the
        card lands amber with zero elements. The validated sample's value
        is the only number the creator has already stated, so it becomes
        the starting point, never a made-up figure.
        """
        source = self._studio_manual_source(manifest)
        if source is None or source.get("file"):
            return
        sample = body.get("sample")
        bindings = sample.get("bindings") if isinstance(sample, dict) else None
        raw = bindings.get("value") if isinstance(bindings, dict) else 0
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raw = 0
        number = int(raw) if float(raw).is_integer() else float(raw)
        folder = Path(runtime.data_dir) / plugin_id
        folder.mkdir(parents=True, exist_ok=True)
        document = {
            "value": number,
            "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        (folder / "manual.json").write_text(
            json.dumps(document, indent=2), encoding="utf-8")

    def post_studio_install(self, body: dict) -> None:
        """Create a plugin in Studio and install it on this desk now.

        Publishing for review is a distribution action and still needs the
        admin switch. This is the personal path: validate the inline draft,
        keep the exact tree, and hand it to the runtime the same way the
        wizard does. Nothing about it is catalog-signed, and the audit row
        says so.
        """
        manifest = self._inline_manifest(body)
        plugin_id = str(manifest.get("id") or "").strip()
        version = str(manifest.get("version") or "").strip()
        _safe_component(plugin_id, "plugin id")
        _safe_component(version, "version")
        runtime = self._runtime()
        with tempfile.TemporaryDirectory(prefix="studio-install-") as tmp:
            folder = Path(tmp) / plugin_id
            self._write_inline_plugin(folder, body)
            try:
                validation = validate_plugin(folder).as_dict()
            except Exception as exc:  # noqa: BLE001 - a verdict, not a crash
                validation = {"ok": False, "failures": [
                    {"code": "studio:unreadable", "message": str(exc)}]}
            if not validation.get("ok"):
                self.audit("studio.install", plugin_id or "untitled",
                           "denied", "validation-failed")
                raise MarketplaceError(
                    400, "studio:validation-failed",
                    "the plugin does not pass validation, so it was not installed",
                    {"failures": validation.get("failures") or []})
            target = self.marketplace_dir("studio", plugin_id, version)
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(folder, target)
        try:
            result = runtime.install(target, source="studio")
        except PluginError as exc:
            self.audit("studio.install", plugin_id, "error", exc.code)
            raise MarketplaceError(exc.status, exc.code, str(exc),
                                   {"id": plugin_id}) from exc
        self._seed_studio_manual_metric(manifest, body, plugin_id, runtime)
        try:
            # install() probed before the seed existed, so its stored
            # status is the amber "missing file" one. One retest after the
            # seed is the same recovery the card's button runs, and it
            # keeps Installed from warning about a file that now exists.
            runtime.retest(plugin_id)
        except PluginError:
            pass  # the card's own Re-test still recovers; install stands
        self.audit("studio.install", plugin_id, "ok",
                   f"{version} created on this desk")
        self.send(200, {
            "id": plugin_id,
            "version": str(result.get("version") or version),
            "status": "installed",
            "validation": validation,
            "source": "studio",
        })

    def post_validate(self, body: dict) -> None:
        """Validate an inline draft without installing it.

        The draft is written to a temporary folder and handed to the same validator
        installs use; an unreadable staging folder is a failed verdict with a 200,
        not a crash."""
        self._inline_manifest(body)
        with tempfile.TemporaryDirectory(prefix="marketplace-validate-") as tmp:
            self._write_inline_plugin(Path(tmp), body)
            try:
                verdict = validate_plugin(tmp)
            except Exception as exc:  # noqa: BLE001 - an unreadable staging dir is a verdict
                self.send(200, {"ok": False, "failures": [
                    {"code": "validate:unreadable", "message": str(exc)}]})
                return
        self.send(200, verdict.as_dict())

    def post_pack_install(self, body: dict) -> None:
        """Install every member of a pack, or none of them.

        All members are checked first (presence, eligibility, folder, digest), so a
        blocked pack changes nothing and the error names the blocking member. A
        runtime failure during the installs unwinds the members this request
        installed; members already present are reported and left alone."""
        pack_id = self._required_id(body)
        document = self._pack_document()
        pack = next((item for item in document.get("packs") or []
                     if isinstance(item, dict) and item.get("id") == pack_id), None)
        if pack is None:
            raise MarketplaceError(
                404, "pack:not-found",
                f"no pack {pack_id} in the registry", {"id": pack_id})
        entries, policy = self._entries()
        by_id = {entry.get("id"): entry for entry in entries}
        runtime = self._runtime()
        prepared = []
        blocked = None
        for member_id in pack.get("plugins") or []:
            if not isinstance(member_id, str):
                continue
            entry = by_id.get(member_id)
            if entry is None:
                blocked = (403, member_id, "catalog:not-found",
                           "This plugin is not in the catalog this desk can see.",
                           [], {})
                break
            decision = evaluate(entry, policy,
                                installed=self._record(member_id) is not None)
            if not decision["eligible"]:
                reason = (decision["reasons"] or [{}])[0]
                blocked = (403, member_id,
                           reason.get("code", "policy:source-not-enabled"),
                           reason.get("message", "This plugin is not eligible."),
                           decision["reasons"], {})
                break
            plugin_dir = self._plugin_dir(entry)
            if plugin_dir is None:
                blocked = (403, member_id, "install:source-unavailable",
                           "This plugin resolves to no plugin folder.", [], {})
                break
            try:
                self._verify_tree_digest(entry, plugin_dir)
            except MarketplaceError as exc:
                blocked = (exc.status, member_id, exc.code, exc.message,
                           [], dict(exc.details or {}))
                break
            prepared.append((entry, plugin_dir))
        if blocked is not None:
            status, member_id, code, message, reasons, extra = blocked
            self.audit("pack-install", pack_id, "denied", member_id)
            details = {"id": pack_id, "blockedMember": member_id,
                       "reasons": reasons, "installed": []}
            for key, value in extra.items():
                if key != "id":
                    details[key] = value
            raise MarketplaceError(
                status, code,
                f"Pack {pack_id} was not installed: {member_id} is blocked. {message}",
                details)
        if not prepared:
            raise MarketplaceError(
                409, "pack:empty", f"pack {pack_id} has no installable members",
                {"id": pack_id})
        installed = []
        already = []
        try:
            for entry, plugin_dir in prepared:
                member_id = str(entry.get("id") or "")
                record = self._record(member_id)
                if record is not None and record.get("state") != "uninstalled":
                    already.append(member_id)
                    continue
                result = runtime.install(plugin_dir, source=entry.get("source", "catalog"))
                installed.append({"id": member_id,
                                  "version": result.get("version", "")})
        except PluginError as exc:
            # All-or-none: remove only the members this request installed.
            for item in installed:
                try:
                    runtime.uninstall(item["id"])
                except PluginError:
                    continue
            self.audit("pack-install", pack_id, "error", exc.code)
            raise MarketplaceError(
                409, exc.code,
                f"Pack {pack_id} was not installed: {exc}",
                {"id": pack_id, "installed": []}) from exc
        self.audit("pack-install", pack_id, "ok",
                   ",".join(item["id"] for item in installed))
        self.send(200, {
            "id": pack_id,
            "installed": installed,
            "alreadyInstalled": already,
            "total": len(prepared),
            "status": "installed",
        })

    def post_update(self, body: dict) -> None:
        """Update an installed plugin to the catalog's current release.

        The staged tree must match the catalog pin. A widened scope set is held for
        the user's consent; a narrowing or equal set is accepted at once, because
        fewer permissions never need a new approval. The response names the added
        and removed scopes."""
        plugin_id = self._required_id(body)
        runtime = self._runtime()
        try:
            record = runtime.record(plugin_id)
        except PluginError as exc:
            raise MarketplaceError(exc.status, exc.code, str(exc),
                                   {"id": plugin_id}) from exc
        entry, _entries, policy = self._find_entry(plugin_id)
        decision = evaluate(entry, policy, installed=True)
        if not decision["eligible"]:
            self._deny(decision)
        plugin_dir = self._plugin_dir(entry)
        if plugin_dir is None:
            raise MarketplaceError(
                409, "install:source-unavailable",
                f"the catalog entry {plugin_id} resolves to no plugin directory",
                {"id": plugin_id})
        try:
            self._verify_tree_digest(entry, plugin_dir)
        except MarketplaceError as exc:
            self.audit("update", plugin_id, "denied", exc.code)
            raise
        try:
            active_dir = runtime.version_dir(plugin_id)
        except PluginError:
            active_dir = None
        if active_dir is None and record.get("versions"):
            active_dir = Path(record["versions"][-1]["dir"])
        old_scopes = self._manifest_scopes(active_dir or plugin_dir)
        new_scopes = self._manifest_scopes(plugin_dir)
        zip_path = self._zip_dir(plugin_dir)
        try:
            result = runtime.update(plugin_id, zip_path)
        except PluginError as exc:
            raise MarketplaceError(exc.status, exc.code, str(exc),
                                   {"id": plugin_id}) from exc
        finally:
            try:
                zip_path.unlink()
            except OSError:
                pass
        added = sorted(set(new_scopes) - set(old_scopes))
        removed = sorted(set(old_scopes) - set(new_scopes))
        if result.get("applied"):
            to_version = str(result.get("version") or entry.get("version") or "")
            pending = False
        elif not added:
            # The runtime holds any permission value change for re-consent; a
            # narrowing only removes scopes, so the marketplace can accept it
            # immediately instead of asking the user to approve less access.
            try:
                approved = runtime.consent(plugin_id)
            except PluginError as exc:
                raise MarketplaceError(exc.status, exc.code, str(exc),
                                       {"id": plugin_id}) from exc
            to_version = str(approved.get("version") or entry.get("version") or "")
            pending = False
        else:
            diff = runtime.pending_diff(plugin_id)
            to_version = str(diff.get("version") or entry.get("version") or "")
            pending = True
        self.audit("update", plugin_id, "pending" if pending else "ok", to_version)
        self.send(200, {
            "id": plugin_id,
            "from": record.get("active_version", ""),
            "to": to_version,
            "widening": added,
            "scopes": new_scopes,
            "addedScopes": added,
            "removedScopes": removed,
            "pendingConsent": pending,
        })

    def post_consent(self, body: dict) -> None:
        """Accept or reject a pending update's widened scopes.

        decision is 'accept' or 'reject'; rejecting also names the version the
        update would have installed. The decision is audited either way."""
        plugin_id = self._required_id(body)
        decision = body.get("decision")
        if decision not in ("accept", "reject"):
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                'decision must be "accept" or "reject"', {"field": "decision"})
        runtime = self._runtime()
        if decision == "accept":
            try:
                result = runtime.consent(plugin_id)
            except PluginError as exc:
                raise MarketplaceError(exc.status, exc.code, str(exc),
                                       {"id": plugin_id}) from exc
            version = str(result.get("version", ""))
            status = "accepted"
        else:
            try:
                diff = runtime.pending_diff(plugin_id)
            except PluginError as exc:
                raise MarketplaceError(exc.status, exc.code, str(exc),
                                       {"id": plugin_id}) from exc
            declined = runtime.decline_pending(plugin_id)
            version = str(declined.get("version") or diff.get("version", ""))
            status = "rejected"
        self.audit("consent", plugin_id, status, version)
        self.send(200, {"id": plugin_id, "version": version, "status": status})

    def post_rollback(self, body: dict) -> None:
        """Roll an installed plugin back to an earlier version.

        toVersion is optional; without it the runtime picks. The response names the
        version that was active before and the one now active."""
        plugin_id = self._required_id(body)
        runtime = self._runtime()
        requested = body.get("toVersion")
        if requested is not None and (not isinstance(requested, str)
                                      or not requested.strip()):
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "toVersion must be a non-empty version string",
                {"field": "toVersion"})
        try:
            record = runtime.record(plugin_id)
            result = runtime.rollback(plugin_id,
                                      requested.strip() if requested else None)
        except PluginError as exc:
            raise MarketplaceError(exc.status, exc.code, str(exc),
                                   {"id": plugin_id}) from exc
        to_version = str(result.get("rolled_back_to") or "")
        self.audit("rollback", plugin_id, "ok", to_version)
        self.send(200, {"id": plugin_id,
                        "from": record.get("active_version", ""),
                        "to": to_version, "status": "rolled-back"})

    def _lifecycle(self, body: dict, action: str) -> None:
        """Run one runtime lifecycle action and answer with its result plus ok.

        action must name a PluginRuntime method; purge_data is the only one that
        takes the body's confirmation token. A runtime failure becomes a
        MarketplaceError, and the action is audited only after it succeeds."""
        plugin_id = self._required_id(body)
        runtime = self._runtime()
        method = getattr(runtime, action)
        try:
            if action == "purge_data":
                confirmation = body.get("confirm")
                result = method(plugin_id, confirmation)
            else:
                result = method(plugin_id)
        except PluginError as exc:
            raise MarketplaceError(exc.status, exc.code, str(exc),
                                   {"id": plugin_id}) from exc
        self.audit(action.replace("_", "-"), plugin_id, "ok")
        payload = dict(result)
        payload["ok"] = True
        self.send(200, payload)

    def post_uninstall(self, body: dict) -> None:
        """Uninstall a plugin; the runtime keeps its data directory and says where."""
        self._lifecycle(body, "uninstall")

    def post_enable(self, body: dict) -> None:
        """Start a disabled plugin again, re-attaching its data source."""
        self._lifecycle(body, "enable")

    def post_disable(self, body: dict) -> None:
        """Stop a plugin without removing it: the runtime detaches its data source."""
        self._lifecycle(body, "disable")

    def post_retest(self, body: dict) -> None:
        """Re-probe an installed plugin's data source and store the new status."""
        self._lifecycle(body, "retest")

    def post_purge_data(self, body: dict) -> None:
        """Delete an installed plugin's stored data after the confirmation token."""
        self._lifecycle(body, "purge_data")

    def post_manual_value(self, body: dict) -> None:
        """Save the value a manager keeps for a hand-kept number tile.

        The write lands in the plugin's own data directory, as the JSON object
        the manual-metric reader already reads: a numeric value plus an
        optional unit, target and update time. Nothing else is accepted, so a
        caller cannot point the tile at a different file.
        """
        plugin_id = self._required_id(body)
        plugins = self.plugins
        if plugins is None:
            raise MarketplaceError(503, "marketplace:unavailable",
                                   "the plugin runtime is not configured")
        try:
            installed = plugins.record(plugin_id)
        except PluginError:
            installed = None
        if not installed or not installed.get("versions"):
            raise MarketplaceError(404, "plugin:unknown",
                                   f"plugin {plugin_id} is not installed",
                                   {"id": plugin_id})
        raw_value = body.get("value")
        try:
            value = float(raw_value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise MarketplaceError(400, "manual-value:bad",
                                   "a value is required and must be a number")
        if value != value or value in (float("inf"), float("-inf")):
            raise MarketplaceError(400, "manual-value:bad",
                                   "the value must be a finite number")
        document = {"value": int(value) if value.is_integer() else value,
                    "updatedAt": datetime.now().isoformat(timespec="seconds")}
        unit = body.get("unit")
        if isinstance(unit, str) and unit.strip():
            document["unit"] = unit.strip()[:24]
        target = _finite(body.get("target"))
        if target is not None:
            document["target"] = int(target) if target.is_integer() else target
        history = _manual_history(installed, document["value"])
        if history:
            document["history"] = history
        data_dir = Path(str(installed.get("data_dir") or ""))
        data_dir.mkdir(parents=True, exist_ok=True)
        target_path = data_dir / "manual.json"
        target_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        # The tile's own mode decides what it shows next; a re-test here would
        # defeat a "when it changes" tile's stored reading, so the refresh is
        # the change hook's job.
        self.audit("manual-value", plugin_id, "ok")
        self.send(200, {"ok": True, "saved": document})


    def _set_shared(self, body: dict, shared: bool) -> None:
        """Share an installed plugin with paired desks (peer plane)."""
        plugin_id = self._required_id(body)
        try:
            installed = self.plugins is not None and self.plugins.record(plugin_id)
        except PluginError:
            installed = None
        if (not installed
                or installed.get("state") == "uninstalled"
                or not installed.get("versions")):
            raise MarketplaceError(
                404, "plugin:unknown",
                f"plugin {plugin_id} is not installed", {"id": plugin_id})
        peer_store = getattr(self.server, "peer_store", None)
        if peer_store is None:
            raise MarketplaceError(
                503, "marketplace:unavailable",
                "peer sharing is not configured for this desk")
        peer_store.set_shared(plugin_id, shared)
        paired = len(peer_store.peers() or ())
        self.audit("share" if shared else "unshare", plugin_id, "ok")
        self.send(200, {"id": plugin_id, "shared": shared, "paired": paired})

    def post_report(self, body: dict) -> None:
        """Record a local problem report against a plugin.

        Reports stay in this desk's marketplace folder (most recent 1000) and are
        never sent anywhere. The reason is required; the note is optional."""
        plugin_id = self._required_id(body)
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "the report needs a reason", {"field": "reason"})
        reports = signed_policy.read_json(self.marketplace_dir(REPORTS_FILE), [])
        if not isinstance(reports, list):
            reports = []
        report = {"id": plugin_id, "reason": reason.strip(),
                  "note": str(body.get("note") or ""), "at": _now(),
                  "actor": "local-admin"}
        reports.append(report)
        signed_policy.write_json(self.marketplace_dir(REPORTS_FILE), reports[-1000:])
        self.audit("report", plugin_id, "ok", report["reason"])
        self.send(200, {"ok": True, "report": report})

    def post_publish(self, body: dict) -> None:
        """Queue a plugin for review: an inline draft or an existing folder.

        An inline body needs a changelog, an explicit license grant and an SPDX
        license in the manifest. The validator runs at submission and its verdict
        is stored with the pending record; a failed verdict still queues, and
        approval re-validates. Answers 202 with the pending id."""
        folder = body.get("folder")
        inline = not (isinstance(folder, str) and folder.strip())
        if inline:
            manifest = self._inline_manifest(body)
            changelog = body.get("changelog")
            if not isinstance(changelog, str) or not changelog.strip():
                raise MarketplaceError(
                    400, "publish:changelog-required",
                    "publish needs a changelog describing what changed",
                    {"field": "changelog"})
            if body.get("licenseGrant") is not True:
                raise MarketplaceError(
                    400, "publish:license-required",
                    "publish needs an explicit license grant",
                    {"field": "licenseGrant"})
            if not str(manifest.get("license") or "").strip():
                raise MarketplaceError(
                    400, "publish:license-required",
                    "the manifest must name an SPDX license before publish",
                    {"field": "license"})
            pending_id = f"pub-{uuid.uuid4().hex[:12]}"
            path = self.marketplace_dir(PENDING_DIR, pending_id, "plugin")
            self._write_inline_plugin(path, body)
        else:
            path = Path(folder)
            if not path.is_absolute():
                path = self.marketplace_dir(folder)
            if not path.is_dir():
                raise MarketplaceError(
                    400, "publish:folder-not-found",
                    f"no folder at {path}", {"folder": str(path)})
            pending_id = f"pub-{uuid.uuid4().hex[:12]}"
        try:
            verdict = validate_plugin(path)
            validation = verdict.as_dict()
        except Exception as exc:  # noqa: BLE001 - unreadable folder is a report, not a crash
            validation = {"ok": False, "failures": [
                {"code": "publish:unreadable", "message": str(exc)}]}
        record = {"pendingId": pending_id, "folder": str(path),
                  "queuedAt": _now(), "validation": validation,
                  "actor": "local-admin"}
        changelog = body.get("changelog")
        if isinstance(changelog, str) and changelog.strip():
            record["changelog"] = changelog.strip()
        if inline:
            record["licenseGrant"] = True
            record["manifest"] = manifest
        signed_policy.write_json(
            self.marketplace_dir(PENDING_DIR, f"{pending_id}.json"), record)
        self.audit("publish", pending_id, "queued",
                   "ok" if validation.get("ok") else "validation-failed")
        self.send(202, {"pendingId": pending_id, "validation": validation,
                        "status": "pending-review"})
    # -- admin mutations (T13) -------------------------------------------

    def post_policy_import(self, body: dict) -> None:
        """Verify a signed policy bundle and, with confirm, make it the policy.

        Admin only. Without confirm the route returns the field diff and the
        verification block and writes nothing. With it, the bundle is re-verified
        against the anchor as it stands now, then written, the anchor advanced and
        the validation recorded; a rejection leaves the current policy in force."""
        self._require_admin()
        bundle = body.get("bundle")
        if not isinstance(bundle, dict):
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "the request body must carry a bundle object", {"field": "bundle"})
        anchor = signed_policy.load_anchor(self.workspace)
        try:
            result = signed_policy.verify_policy_bundle(
                bundle, now=signed_policy.utc_now(),
                pinned_epoch=anchor["epoch"], trusted_keys=None)
        except TrustError as exc:
            self.audit("policy.import", "", "rejected", exc.code)
            raise MarketplaceError(
                400, exc.code, exc.message, getattr(exc, "details", {}) or {})
        candidate = Policy(
            **{name: result[name] for name in signed_policy.POLICY_FIELDS})
        current, _verification = load_effective_policy(self.workspace)
        diff = signed_policy.policy_diff(current, candidate)
        verification = {
            key: result["verification"].get(key)
            for key in ("signatureStatus", "signerFingerprint", "warning",
                        "epoch", "expiresAt")
        }
        if body.get("confirm") is not True:
            self.send(200, {"diff": diff, "verification": verification,
                            "applied": False})
            return
        # Re-verify against the anchor as it stands right now, then write.
        anchor = signed_policy.load_anchor(self.workspace)
        try:
            result = signed_policy.verify_policy_bundle(
                bundle, now=signed_policy.utc_now(),
                pinned_epoch=anchor["epoch"], trusted_keys=None)
        except TrustError as exc:
            self.audit("policy.import", "", "rejected", exc.code)
            raise MarketplaceError(
                400, exc.code, exc.message, getattr(exc, "details", {}) or {})
        signed_policy.write_json(self.marketplace_dir(POLICY_FILE), bundle)
        epoch = int(bundle.get("revocationEpoch") or 0)
        fingerprint = result["verification"].get("signerFingerprint")
        signed_policy.write_anchor(
            self.workspace, epoch=epoch,
            fingerprints=[fingerprint] if fingerprint else [])
        self._record_validation({"ok": True, "failures": []}, "policy", "bundle")
        self.audit("policy.import", "", "applied",
                   f"epoch {epoch} key {result['verification'].get('keyId') or ''}".strip())
        verification = {
            key: result["verification"].get(key)
            for key in ("signatureStatus", "signerFingerprint", "warning",
                        "epoch", "expiresAt")
        }
        self.send(200, {"diff": diff, "verification": verification,
                        "applied": True})

    def post_kill_switch(self, body: dict) -> None:
        """Turn the administrator kill switch on or off for one plugin.

        Admin only. The overlay is stored apart from the signed policy, so the
        switch keeps working while a bundle is active; the response lists every
        disabled id."""
        self._require_admin()
        plugin_id = body.get("pluginId")
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "the request body must carry a pluginId", {"field": "pluginId"})
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "the request body must carry a boolean enabled flag",
                {"field": "enabled"})
        plugins = signed_policy.set_kill_switch(
            self.workspace, plugin_id.strip(), enabled)
        self.audit("policy.kill-switch", plugin_id.strip(),
                   "on" if enabled else "off", "")
        self.send(200, {"ok": True, "pluginId": plugin_id.strip(),
                        "enabled": enabled, "killSwitch": plugins})

    def post_publication_decision(self, pending_id: str, action: str,
                                  body: dict) -> None:
        """Approve or reject one pending publication.

        Admin only. Rejecting needs a reason and only drops the pending record.
        Approving re-validates the staged folder, copies it to a stable org
        location and pins its tree digest, then replaces that plugin's org catalog
        entry, so the release is as installable and digest-checked as a bundled
        one."""
        self._require_admin()
        pending_id = pending_id.strip().strip("/")
        path = self.marketplace_dir(PENDING_DIR, f"{pending_id}.json")
        record = signed_policy.read_json(path, None)
        if not isinstance(record, dict):
            raise MarketplaceError(
                404, "publish:not-found",
                f"no pending publication {pending_id}", {"id": pending_id})
        manifest = self._manifest_of(record)
        plugin_id = str(manifest.get("id") or "")
        version = str(manifest.get("version") or "")
        if action == "reject":
            reason = body.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise MarketplaceError(
                    400, "marketplace:invalid-request",
                    "rejecting a publication needs a reason", {"field": "reason"})
            self._remove_pending(path, record)
            self.audit("publish.reject", plugin_id or pending_id, "ok",
                       reason.strip())
            self.send(200, {"ok": True, "id": pending_id, "decision": "reject",
                            "pluginId": plugin_id})
            return

        folder = Path(str(record.get("folder") or ""))
        validation = self._validate_pending(folder)
        if not validation.get("ok"):
            self.audit("publish.approve", plugin_id or pending_id, "blocked",
                       "validation-failed")
            raise MarketplaceError(
                400, "publish:validation-failed",
                "the pending publication does not pass validation",
                {"pendingId": pending_id,
                 "failures": validation.get("failures") or []})
        # Approval is a release action, so the validated tree must survive
        # the pending folder. Copy it to a stable org location first, then pin
        # the digest the install path enforces.
        plugin_id = str(manifest.get("id") or "")
        _safe_component(plugin_id, "plugin id")
        org_version = version or "unversioned"
        _safe_component(org_version, "version")
        org_dir = self.marketplace_dir("org", plugin_id, org_version)
        if org_dir.exists():
            shutil.rmtree(org_dir)
        org_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, org_dir)
        release = self._approved_release(manifest, org_dir, body, record, version)
        release["path"] = str(org_dir)
        release["digest"] = tree_digest(org_dir)
        release["sha256"] = release["digest"]
        document = signed_policy.read_json(self.marketplace_dir(ORG_CATALOG_FILE), {})
        plugins = document.get("plugins") if isinstance(document, dict) else None
        plugins = [item for item in plugins or () if isinstance(item, dict)]
        plugins = [item for item in plugins if item.get("id") != plugin_id]
        plugins.append(release)
        signed_policy.write_json(self.marketplace_dir(ORG_CATALOG_FILE), {
            "schemaVersion": 2,
            "generatedAt": _now(),
            "plugins": plugins,
        })
        self._record_validation(validation, "publication", plugin_id or pending_id)
        self._remove_pending(path, record)
        self.audit("publish.approve", plugin_id or pending_id, "ok",
                   f"{version or '(no version)'} at {release['riskTier']}")
        self.send(200, {"ok": True, "id": pending_id, "decision": "approve",
                        "pluginId": plugin_id, "version": version,
                        "catalogSource": "org", "validation": validation})

    def _validate_pending(self, folder: Path) -> dict:
        """Validate a staged publication folder and return the verdict document.

        A folder the validator cannot read at all still yields a failed verdict
        with a publish:unreadable failure rather than raising."""
        try:
            return validate_plugin(folder).as_dict()
        except Exception as exc:  # noqa: BLE001 - an unreadable folder is a verdict
            return {"ok": False, "failures": [
                {"code": "publish:unreadable", "message": str(exc)}]}

    def _approved_release(self, manifest: dict, folder: Path, body: dict,
                          record: dict, version: str) -> dict:
        """Build the org catalog release an approved publication becomes.

        The risk tier comes from the approval body, else the manifest, else T1
        rather than a guessed higher tier. Permissions, optional permissions and
        widget contributes are copied only when the manifest declares them as
        objects; the caller stamps path and digest afterwards."""
        requested = body.get("riskTier")
        if not isinstance(requested, str) or not requested.strip():
            requested = manifest.get("riskTier")
        rank = risk_rank(requested)
        risk_tier = RISK_TIERS[rank] if rank is not None else "T1"
        plugin_id = str(manifest.get("id") or "")
        changelog = record.get("changelog")
        release = {
            "id": plugin_id,
            "name": str(manifest.get("name") or plugin_id),
            "version": version,
            "publisher": str(manifest.get("publisher") or ""),
            "publisherVerified": True,
            "category": str(manifest.get("category") or ""),
            "tags": [str(item) for item in manifest.get("tags") or ()
                     if isinstance(item, str)],
            "summary": str(manifest.get("summary") or ""),
            "description": str(manifest.get("description") or ""),
            "icon": str(manifest.get("icon") or "plugin"),
            "riskTier": risk_tier,
            "license": str(manifest.get("license") or ""),
            "signature": {"status": "org-approved", "keyId": "local-admin",
                          "signedAt": _now()},
            "path": str(folder),
            "platforms": [str(item) for item in manifest.get("platforms") or ()
                          if isinstance(item, str)],
            "publishedAt": _now(),
        }
        for key in ("permissions", "optionalPermissions", "contributes"):
            if isinstance(manifest.get(key), dict):
                release[key] = manifest[key]
        if isinstance(changelog, str) and changelog.strip():
            release["changelog"] = [{"version": version,
                                     "notes": changelog.strip()}]
        return release

    def _remove_pending(self, path: Path, record: dict) -> None:
        """Drop a decided publication's record and its staged tree.

        Only a folder inside the pending directory is removed, so a record pointing
        elsewhere cannot delete it."""
        try:
            Path(path).unlink()
        except OSError:
            pass
        folder = record.get("folder")
        if not isinstance(folder, str) or not folder.strip():
            return
        pending_root = self.marketplace_dir(PENDING_DIR)
        try:
            resolved = Path(folder).resolve()
            if resolved.is_dir() and pending_root.resolve() in resolved.parents:
                shutil.rmtree(resolved)
        except OSError:
            pass

    def post_governance(self, action: str, body: dict) -> None:
        """Record a quarantine, yank or deprecation for one plugin version.

        Admin only. The record is keyed by plugin then action, so re-issuing an
        action replaces its version, reason and timestamp. A replacement version,
        when given, becomes the advisory text."""
        self._require_admin()
        plugin_id = self._required_id(body)
        version = body.get("version")
        if not isinstance(version, str) or not version.strip():
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "the request body must carry a version", {"field": "version"})
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise MarketplaceError(
                400, "marketplace:invalid-request",
                "the request body must carry a reason", {"field": "reason"})
        governance = self._governance()
        plugins = governance.setdefault("plugins", {})
        record = plugins.setdefault(plugin_id, {})
        entry = {"version": version.strip(), "reason": reason.strip(), "at": _now()}
        replacement = body.get("replacement")
        if isinstance(replacement, str) and replacement.strip():
            entry["replacement"] = replacement.strip()
            entry["advisory"] = (
                f"{reason.strip()} Use {replacement.strip()} instead.")
        else:
            entry["advisory"] = reason.strip()
        record[action] = entry
        signed_policy.write_json(self.marketplace_dir(GOVERNANCE_FILE), governance)
        self.audit(action, plugin_id, "ok", version.strip())
        self.send(200, {"ok": True, "entry": {
            "id": plugin_id, "version": version.strip(),
            "action": action, **entry}})


def _safe_component(value: str, field: str) -> str:
    """One path component, checked before it reaches the filesystem."""
    if (not value or value in (".", "..") or value.startswith("-")
            or "/" in value or "\\" in value):
        raise MarketplaceError(
            400, "marketplace:invalid-request",
            f"the {field} is not a safe path component",
            {"field": field, "value": value})
    return value


def _query_dict(query: str) -> dict:
    """Parse a URL query string into a flat dict.

    Keys and values are percent- and plus-decoded; a repeated key keeps its last
    value."""
    values: dict[str, str] = {}
    for pair in query.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        from urllib.parse import unquote_plus
        values[unquote_plus(key)] = unquote_plus(value)
    return values


def _run(handler, method: str):
    """Run one request and always answer, turning failures into the envelope.

    MarketplaceError keeps its status and code, a runtime failure keeps its own,
    and anything else becomes a 500 without dropping the connection. A failed
    POST is audited with the route as its subject."""
    path, _, query = handler.path.partition("?")
    api = _API(handler)
    try:
        if method == "GET":
            api.get(path, _query_dict(query))
        else:
            api.post(path)
    except MarketplaceError as exc:
        if method == "POST":
            api.audit(path[len(PREFIX):].lstrip("/") or "unknown", "",
                      "error", exc.code)
        api.fail(exc.status, exc.code, exc.message, exc.details)
    except PluginError as exc:
        api.fail(exc.status, exc.code, str(exc), {})
    except Exception as exc:  # noqa: BLE001 - the API never drops the connection
        api.fail(500, "marketplace:internal",
                 f"the marketplace failed: {exc}", {})


def handle_get(handler) -> bool:
    """Answer a GET under /api/marketplace/; the caller already gated it."""
    path = handler.path.partition("?")[0]
    if not path.startswith(PREFIX + "/"):
        return False
    _run(handler, "GET")
    return True


def handle_post(handler) -> bool:
    """Answer a POST under /api/marketplace/; body is already drained."""
    path = handler.path.partition("?")[0]
    if not path.startswith(PREFIX + "/"):
        return False
    _run(handler, "POST")
    return True


def _finite(value) -> float | None:
    """A finite number from a request field, or None when it is not one."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _manual_history(installed: dict, value) -> list:
    """The previous values plus this one, for the tile's own trend.

    The reader draws a sparkline from ``history``, so a hand-kept number
    gathers its series the same way an aggregate does. A missing or corrupt
    existing file simply starts the series here.
    """
    data_dir = Path(str(installed.get("data_dir") or ""))
    previous: list = []
    try:
        existing = json.loads((data_dir / "manual.json").read_text(encoding="utf-8"))
        if isinstance(existing, dict) and isinstance(existing.get("history"), list):
            previous = [entry for entry in existing["history"]
                        if isinstance(entry, dict)][-29:]
    except (OSError, ValueError):
        previous = []
    previous.append({"at": datetime.now().isoformat(timespec="seconds"),
                     "value": value})
    return previous
