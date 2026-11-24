"""Regressions for the two Marketplace flows on a fresh desk.

Install: every plugin the desk ships must install from Discover. The
bundled catalog pins each plugin's tree digest and install re-hashes the
staged tree against that pin, so a plugin folder edited without
re-running scripts/sync_registry.py and scripts/build_catalog.py made
every install answer 409 install:digest-mismatch (no traceback, just a
refusal).

Create: the Studio's generated widget.ui.json must pass the same
validator that guards installs, or Publish for review never unlocks.
The payload below mirrors frontend/src/marketplace/Studio.tsx
(buildManifest, buildWidgetUi, buildSample) for a blank-template plugin.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from server_harness import Booted
from agentdesk.marketplace.catalog import bundled_catalog_path
from agentdesk.registry.install import tree_digest

REGISTRY = ROOT / "registry"


@pytest.fixture()
def booted():
    # The shipped registry, as a fresh desk run from a checkout sees it.
    boot = Booted(registry_root=str(REGISTRY))
    boot.auth = boot.exchange()
    try:
        yield boot
    finally:
        boot.close()


def _get(boot, path):
    status, _headers, body = boot.request("GET", path, boot.auth)
    return status, json.loads(body.decode("utf-8"))


def _post(boot, path, payload):
    status, _headers, body = boot.post_json(path, payload, boot.auth)
    return status, json.loads(body.decode("utf-8"))


def test_every_shipped_pin_matches_the_tree_it_ships():
    document = json.loads(bundled_catalog_path().read_text(encoding="utf-8"))
    stale = [
        entry["id"] for entry in document["plugins"]
        if entry["digest"] != tree_digest(REGISTRY / "plugins" / entry["id"])
    ]
    assert stale == [], (
        "bundled-catalog.json pins a stale digest; run scripts/sync_registry.py "
        "and scripts/build_catalog.py --out src/agentdesk/marketplace/bundled-catalog.json"
    )


def test_every_bundled_plugin_installs_from_discover(booted):
    status, catalog = _get(booted, "/api/marketplace/catalog")
    assert status == 200
    bundled = [entry["id"] for entry in catalog["entries"] if entry["source"] == "bundled"]
    assert bundled, "the fresh desk lists the shipped plugins"
    # competitor-watch is the one network plugin, honestly tiered T2 since
    # the registry sync reads optionalPermissions too (spec 017 6d): the
    # default T1 ceiling refuses it, which is the admin approval its own
    # README promises. The admin raises the ceiling and names the one host
    # the plugin declares on the policy allowlist, the documented way (the
    # local policy file), and every shipped plugin then installs.
    status, body = _post(booted, "/api/marketplace/install", {"id": "competitor-watch"})
    assert status == 403
    assert body.get("error") == "policy:risk-ceiling"
    admin_dir = Path(booted.server.plugins.workspace_dir) / "marketplace"
    admin_dir.mkdir(parents=True, exist_ok=True)
    (admin_dir / "policy.json").write_text(
        json.dumps({"riskCeiling": "T2",
                    "networkAllowlist": ["example.com"]}), encoding="utf-8")
    refused = {}
    for plugin_id in bundled:
        status, body = _post(booted, "/api/marketplace/install", {"id": plugin_id})
        if status != 200:
            refused[plugin_id] = body.get("error")
    assert refused == {}
    status, installed = _get(booted, "/api/marketplace/installed")
    assert status == 200
    assert {record["id"] for record in installed["plugins"]} >= set(bundled)


def _studio_payload(plugin_id="team-notes"):
    name = "Team notes"
    summary = "Counts open action items in the team notes."
    manifest = {
        "schemaVersion": 2,
        "id": plugin_id,
        "name": name,
        "version": "0.1.0",
        "publisher": "local",
        "class": "declarative",
        "engines": {"dashboardHost": ">=0.1.0"},
        "license": "MIT",
        "category": "reference",
        "tags": [],
        "icon": "generic",
        "summary": summary,
        "description": summary,
        "highlights": [summary, "It reads only the scopes you approve.",
                       "It runs only while the app is open."],
        "permissions": {
            "filesystem": {"read": [], "write": []},
            "network": {"allow": []},
            "llm": {"allow": False},
            "shell": "none",
        },
        "activationEvents": [f"onWidget:{plugin_id}"],
        "contributes": {"widgets": [{
            "id": plugin_id,
            "size": "2x1",
            "dataSource": {"type": "manual-metric"},
            "render": {"type": "ui-schema", "file": "widget.ui.json"},
        }]},
        "sample": "sample.json",
        "minHost": ">=0.1.0",
    }
    widget_ui = {
        "type": "card",
        "title": name,
        "elements": [
            {"type": "metric", "label": "Value", "binding": "value"},
            {"type": "text", "label": "About", "binding": "note"},
        ],
    }
    sample = {"bindings": {"value": 0, "note": "This is the plugin sample."},
              "state": "ok", "checkedAt": "2026-11-17T15:00:00Z"}
    return {"manifest": manifest, "widgetUi": widget_ui, "sample": sample}


def test_the_studio_blank_template_validates_and_publishes(booted):
    payload = _studio_payload()
    status, verdict = _post(booted, "/api/marketplace/validate", payload)
    assert status == 200
    assert verdict["failures"] == []
    assert verdict["ok"] is True

    payload["changelog"] = "First version."
    payload["licenseGrant"] = True
    status, response = _post(booted, "/api/marketplace/publish", payload)
    assert status == 202
    assert response["status"] == "pending-review"
    assert response["validation"]["ok"] is True
