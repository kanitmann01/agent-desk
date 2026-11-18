#!/usr/bin/env python3
"""Server-free end-to-end walkthrough of the marketplace modules.

Run from the repository root:

    python scripts/marketplace_walkthrough.py

It builds a throwaway workspace, drives the real _API router and
PluginRuntime, prints one numbered step per assertion, and exits non-zero
on the first failure. No sockets, no network, no registry edits.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from agentdesk.marketplace.api import (  # noqa: E402
    ADMIN_ENV,
    PREFIX,
    _run,
)
from agentdesk.marketplace.catalog import resolve_registry_root  # noqa: E402
from agentdesk.plugins.runtime import PluginRuntime  # noqa: E402
from agentdesk.registry.install import tree_digest  # noqa: E402


class WalkthroughFailure(AssertionError):
    """A numbered step failed."""


class Handler:
    """The slice of DashboardHandler the marketplace router needs."""

    def __init__(self, server, registry_root: Path) -> None:
        """Record the fake server and the registry root the router will resolve.

        The rest of the instance is response state that _send_json and _send_bytes
        fill in; reset clears it before each router call.
        """
        self.server = server
        self.registry_root = registry_root
        self.path = PREFIX + "/"
        self.body = None
        self.status = 0
        self.payload = None
        self.bytes = b""
        self.content_type = ""
        self.headers = {}

    def reset(self, path: str, body=None) -> None:
        """Clear the response state and point the handler at one request.

        path is relative to the marketplace prefix and is prefixed here, so a
        caller passes "/catalog"; body becomes the request body the router reads.
        """
        self.path = PREFIX + path
        self.body = body
        self.status = 0
        self.payload = None
        self.bytes = b""
        self.content_type = ""
        self.headers = {}

    def _send_json(self, status: int, payload: dict) -> None:
        """Record what the router would have sent as a JSON response.

        Status and payload stay on the instance for the caller to assert on; no
        socket is touched.
        """
        self.status = status
        self.payload = payload

    def _read_json_body(self):
        """Return the body installed by reset, standing in for a parsed request body.

        The body is handed back unchanged rather than parsed, so a malformed body
        reaches the router exactly as the caller built it.
        """
        return self.body

    def _send_bytes(self, status: int, body: bytes, content_type: str,
                    headers: dict | None = None) -> None:
        """Record what the router would have sent as a raw byte response.

        This is the shape the audit export takes, since JSONL is not one JSON
        object; headers default to an empty mapping.
        """
        self.status = status
        self.bytes = body
        self.content_type = content_type
        self.headers = headers or {}

    def _registry_root_for_request(self):
        """Answer the registry lookup with the bundled root and its origin label.

        The real handler may serve an org or a downloaded registry; the
        walkthrough exercises only the bundled one, so it always reports
        "bundled".
        """
        return self.registry_root, "bundled"


def call(handler: Handler, method: str, path: str, body=None) -> Handler:
    """Drive one router call through the fake handler and return the handler.

    Resets first, so the response fields describe this call alone; the caller
    reads status and then payload or bytes.
    """
    handler.reset(path, body)
    _run(handler, method)
    return handler


def check(condition, message: str) -> None:
    """Fail the current step unless condition is true.

    Raises WalkthroughFailure, which main reports with the step number and
    turns into exit code 1.
    """
    if not condition:
        raise WalkthroughFailure(message)


def payload(handler: Handler) -> dict:
    """Return the handler's JSON payload, failing the step when there is none.

    A raw-bytes response leaves payload as None, so calling this after one
    fails the step instead of raising AttributeError later.
    """
    check(isinstance(handler.payload, dict),
          f"expected a JSON object, got {type(handler.payload).__name__}")
    return handler.payload


def make_plugin(folder: Path, plugin_id: str, version: str,
                write_scope: str = "") -> dict:
    """Write a minimal declarative plugin into folder and return its manifest.

    Everything is fixed except the id, the version and an optional single
    filesystem write scope, which is what drives the update-consent step:
    1.0.0 writes nothing, 1.1.0 adds one scope. Creates the folder and writes
    manifest.json, widget.json, sample.json and data.json, overwriting any of
    them that already exist.
    """
    folder.mkdir(parents=True, exist_ok=True)
    writes = [write_scope] if write_scope else []
    manifest = {
        "schemaVersion": 2,
        "id": plugin_id,
        "name": "Walkthrough Recon",
        "version": version,
        "publisher": "agent-desk",
        "class": "declarative",
        "engines": {"dashboardHost": ">=0.1.0 <2.0.0"},
        "license": "MIT",
        "permissions": {
            "shell": "none",
            "filesystem": {"read": [], "write": writes},
            "network": {"allow": []},
            "llm": {"allow": False},
        },
        "activationEvents": ["onWidget:main"],
        "contributes": {"widgets": [{
            "id": "main",
            "size": "2x1",
            "dataSource": {"type": "manual-metric", "file": "data.json"},
            "render": {"type": "ui-schema", "file": "widget.json"},
        }]},
        "category": "finance",
        "tags": ["walkthrough"],
        "icon": "clock",
        "summary": "A walkthrough-only reconciliation widget.",
        "description": "Used by scripts/marketplace_walkthrough.py to drive update consent.",
        "highlights": ["One", "Two", "Three"],
        "sample": "sample.json",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (folder / "widget.json").write_text(json.dumps(
        {"elements": [{"type": "metric", "label": "Value", "value": "ok"}]}),
        encoding="utf-8")
    (folder / "sample.json").write_text(json.dumps({"bindings": {}}), encoding="utf-8")
    (folder / "data.json").write_text(json.dumps({"value": 1}), encoding="utf-8")
    return manifest


def catalog_entry(folder: Path, plugin_id: str, version: str) -> dict:
    """Build the org-catalog entry that makes folder installable.

    The digest is taken from the folder as it is now, so the entry is only
    usable while that tree is unchanged; the signature is a local-admin one
    because the walkthrough never verifies trust.
    """
    return {
        "id": plugin_id,
        "name": "Walkthrough Recon",
        "version": version,
        "publisher": "agent-desk",
        "publisherVerified": True,
        "category": "finance",
        "tags": ["walkthrough"],
        "summary": "A walkthrough-only reconciliation widget.",
        "description": "Used by scripts/marketplace_walkthrough.py.",
        "icon": "clock",
        "riskTier": "T1",
        "license": "MIT",
        "signature": {"status": "signed", "keyId": "local-admin"},
        "path": str(folder),
        "digest": tree_digest(folder),
    }


def write_org_catalog(workspace: Path, entries: list[dict]) -> None:
    """Replace the workspace's org catalog with entries.

    The router reads <workspace>/marketplace/org-catalog.json, so each call
    rewrites the whole file: a later step's catalog replaces the previous one
    rather than adding to it.
    """
    folder = workspace / "marketplace"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "org-catalog.json").write_text(json.dumps(
        {"schemaVersion": 2, "plugins": entries}, indent=2), encoding="utf-8")


def main() -> int:
    """Run the walkthrough and return its exit code.

    Needs a bundled registry resolvable from this checkout, and sets ADMIN_ENV
    so the admin routes are reachable. Everything else lives under a temporary
    directory - plugins, their data, the workspace, the publication sources -
    which is removed on the way out, so the repository and any installed app
    are untouched. Prints one numbered line per step and "walkthrough: PASS";
    a failed check or an unexpected exception reports the step number and
    returns 1.
    """
    registry = resolve_registry_root(None)
    check(registry is not None, "no registry root resolved from the repository")
    os.environ[ADMIN_ENV] = "1"
    step = 0
    try:
        with tempfile.TemporaryDirectory(prefix="marketplace-walkthrough-") as tmp:
            tmp_root = Path(tmp)
            workspace = tmp_root / "workspace"
            runtime = PluginRuntime(
                plugins_dir=tmp_root / "plugins",
                data_dir=tmp_root / "plugin-data",
                workspace_dir=workspace,
                now="2026-11-15T12:00:00",
            )
            server = SimpleNamespace(plugins=runtime, registry_root=str(registry))
            handler = Handler(server, registry)

            step += 1
            response = call(handler, "GET", "/installed")
            print(f"{step}. first run: installed catalog is empty")
            check(response.status == 200, f"/installed returned {response.status}")
            check(payload(response)["plugins"] == [], "a first run must have no installed plugins")

            step += 1
            response = call(handler, "GET", "/catalog")
            catalog = payload(response)
            print(f"{step}. bundled catalog: {catalog.get('total')} plugins")
            check(response.status == 200, f"/catalog returned {response.status}")
            check(catalog.get("total") == 25, f"expected 25 bundled plugins, got {catalog.get('total')}")

            step += 1
            response = call(handler, "GET", "/packs")
            packs = payload(response)
            print(f"{step}. bundled packs: {packs.get('total')} packs")
            check(response.status == 200, f"/packs returned {response.status}")
            check(packs.get("total") == 3, f"expected 3 bundled packs, got {packs.get('total')}")

            step += 1
            response = call(handler, "POST", "/packs/install", {"id": "cfo"})
            pack_result = payload(response)
            print(f"{step}. install cfo pack: {len(pack_result.get('installed') or [])} plugins")
            check(response.status == 200, f"pack install returned {response.status}: {pack_result}")
            check(len(pack_result.get("installed") or []) == 8,
                  f"cfo pack should install 8 plugins, got {len(pack_result.get('installed') or [])}")

            step += 1
            response = call(handler, "GET", "/installed")
            installed = payload(response)["plugins"]
            print(f"{step}. installed records: {len(installed)} with pinned digests")
            check(len(installed) == 8, f"expected 8 installed records, got {len(installed)}")
            records = {record["id"]: record for record in runtime.list_records()}
            for record in installed:
                pinned = record.get("pinned") or {}
                lock = records[record["id"]]
                check(pinned.get("version") == record.get("version"), f"{record['id']} pinned version drifted")
                check(isinstance(pinned.get("sha256"), str) and len(pinned["sha256"]) == 64,
                      f"{record['id']} has no 64-character pinned digest")
                check(pinned["sha256"] == lock.get("sha256"), f"{record['id']} pinned digest does not match the lockfile")

            step += 1
            response = call(handler, "GET", "/plugin/ar-aging")
            detail = payload(response)
            print(f"{step}. detail DTO for ar-aging includes a sample")
            check(response.status == 200, f"detail returned {response.status}: {detail}")
            check(detail["plugin"]["id"] == "ar-aging", "detail returned the wrong plugin")
            check(detail.get("installed") is not None, "detail should report the installed record")
            check(bool((detail.get("sample") or {}).get("elements")),
                  "detail should carry rendered sample elements")

            step += 1
            custom = workspace / "walkthrough-plugins"
            v1 = custom / "walkthrough-recon-1.0.0"
            make_plugin(v1, "walkthrough-recon", "1.0.0")
            write_org_catalog(workspace, [catalog_entry(v1, "walkthrough-recon", "1.0.0")])
            response = call(handler, "POST", "/install", {"id": "walkthrough-recon"})
            print(f"{step}. install walkthrough-recon 1.0.0")
            check(response.status == 200, f"install returned {response.status}: {payload(response)}")

            step += 1
            v2 = custom / "walkthrough-recon-1.1.0"
            widened = "${workspace}/finance/recon*.xlsx"
            make_plugin(v2, "walkthrough-recon", "1.1.0", write_scope=widened)
            write_org_catalog(workspace, [catalog_entry(v2, "walkthrough-recon", "1.1.0")])
            response = call(handler, "POST", "/update", {"id": "walkthrough-recon"})
            update = payload(response)
            print(f"{step}. widening update requires consent: {update.get('addedScopes')}")
            check(response.status == 200, f"update returned {response.status}: {update}")
            check(update.get("pendingConsent") is True, "a new scope must require consent")
            check(any(widened in scope for scope in update.get("addedScopes") or []),
                  "the new write scope was not reported")

            step += 1
            response = call(handler, "POST", "/consent",
                            {"id": "walkthrough-recon", "decision": "accept"})
            print(f"{step}. accept widening consent: active 1.1.0")
            check(response.status == 200, f"consent returned {response.status}: {payload(response)}")
            check(payload(response).get("status") == "accepted", "consent was not accepted")
            check(runtime.record("walkthrough-recon").get("active_version") == "1.1.0",
                  "consent did not activate 1.1.0")

            step += 1
            v3 = custom / "walkthrough-recon-1.1.1"
            make_plugin(v3, "walkthrough-recon", "1.1.1")
            write_org_catalog(workspace, [catalog_entry(v3, "walkthrough-recon", "1.1.1")])
            response = call(handler, "POST", "/update", {"id": "walkthrough-recon"})
            narrowing = payload(response)
            print(f"{step}. narrowing update is accepted without a prompt: {narrowing.get('removedScopes')}")
            check(response.status == 200, f"narrowing update returned {response.status}: {narrowing}")
            check(narrowing.get("pendingConsent") is False, "dropping a scope must not require consent")
            check(any(widened in scope for scope in narrowing.get("removedScopes") or []),
                  "the dropped scope was not reported")
            check(runtime.record("walkthrough-recon").get("active_version") == "1.1.1",
                  "narrowing did not activate 1.1.1")

            step += 1
            response = call(handler, "POST", "/rollback", {"id": "walkthrough-recon"})
            rolled = payload(response)
            print(f"{step}. rollback restores 1.1.0 (from {rolled.get('from')})")
            check(response.status == 200, f"rollback returned {response.status}: {rolled}")
            check(rolled.get("to") == "1.1.0", f"rollback landed on {rolled.get('to')}, not 1.1.0")

            step += 1
            staged = tmp_root / "publication-sources" / "walkthrough-published"
            make_plugin(staged, "walkthrough-published", "1.0.0")
            response = call(handler, "POST", "/publish",
                            {"folder": str(staged), "changelog": "Walkthrough publish."})
            pending = payload(response)
            print(f"{step}. publish stages {pending.get('pendingId')} for review")
            check(response.status == 202, f"publish returned {response.status}: {pending}")
            check(pending.get("status") == "pending-review", "publish was not queued for review")
            pending_id = pending.get("pendingId")

            step += 1
            response = call(handler, "POST",
                            f"/admin/publications/{pending_id}/approve", {})
            approved = payload(response)
            print(f"{step}. admin approve publishes to the org catalog")
            check(response.status == 200, f"approve returned {response.status}: {approved}")
            check(approved.get("decision") == "approve", "approve did not return an approval")
            org = json.loads((workspace / "marketplace" / "org-catalog.json").read_text(encoding="utf-8"))
            check(any(item.get("id") == "walkthrough-published" for item in org.get("plugins") or []),
                  "approved plugin is missing from the org catalog")

            step += 1
            response = call(handler, "POST", "/admin/kill-switch",
                            {"pluginId": "source-ledger", "enabled": True})
            print(f"{step}. kill switch blocks an install")
            check(response.status == 200, f"kill switch returned {response.status}: {payload(response)}")
            response = call(handler, "POST", "/install", {"id": "source-ledger"})
            blocked = payload(response)
            check(response.status == 403, f"killed plugin install returned {response.status}: {blocked}")
            check(blocked.get("error") == "policy:kill-switch",
                  f"expected policy:kill-switch, got {blocked.get('error')}")

            step += 1
            response = call(handler, "GET", "/audit/export")
            print(f"{step}. audit export returns JSONL ({len(response.bytes)} bytes)")
            check(response.status == 200, f"audit export returned {response.status}")
            check(response.content_type.startswith("application/x-ndjson"),
                  f"audit export content type is {response.content_type}")
            lines = [line for line in response.bytes.decode("utf-8").splitlines() if line]
            check(bool(lines), "audit export was empty")
            actions = set()
            for line in lines:
                event = json.loads(line)
                check(set(event) == {"at", "action", "pluginId", "actor", "outcome"},
                      f"audit event keys drifted: {sorted(event)}")
                actions.add(event["action"])
            check({"install", "pack-install", "publish.approve", "policy.kill-switch"} <= actions,
                  f"audit export is missing actions: {sorted(actions)}")

        print("walkthrough: PASS")
        return 0
    except WalkthroughFailure as exc:
        print(f"walkthrough: FAILED at step {step}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - a crash is a failed walkthrough
        print(f"walkthrough: FAILED at step {step}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
