"""Marketplace HTTP API tests against the real server over real sockets."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from server_harness import Booted
from agentdesk.registry.install import tree_digest


@pytest.fixture()
def booted():
    boot = Booted()
    boot.auth = boot.exchange()
    try:
        yield boot
    finally:
        boot.close()


def workspace(boot) -> Path:
    return Path(boot.server.plugins.workspace_dir)


def marketplace_dir(boot) -> Path:
    folder = workspace(boot) / "marketplace"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def make_plugin(root, plugin_id, *, version="1.0.0", folder_name=None,
                publisher="agent-desk", category="time", tags=("time",),
                summary="A sample widget", network=(), llm_allow=False):
    folder = Path(root) / (folder_name or plugin_id)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": 2,
        "id": plugin_id,
        "name": plugin_id.replace("-", " ").title(),
        "version": version,
        "publisher": publisher,
        "class": "declarative",
        "engines": {"dashboardHost": ">=1.0.0"},
        "license": "MIT",
        "permissions": {
            "shell": "none",
            "filesystem": {"read": [], "write": []},
            "network": {"allow": []},
            "llm": {"allow": llm_allow},
        },
        "activationEvents": ["onDashboardOpen"],
        "contributes": {"widgets": [{
            "id": "main",
            "size": "2x1",
            "dataSource": {"type": "manual-metric", "file": "data.json"},
            "render": {"type": "ui-schema", "file": "widget.json"},
        }]},
        "category": category,
        "tags": list(tags),
        "icon": "clock",
        "summary": summary,
        "description": "A longer description used by the marketplace tests.",
        "highlights": ["One", "Two", "Three"],
        "sample": "sample.json",
    }
    if network:
        manifest["optionalPermissions"] = {"network": {"allow": list(network)}}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (folder / "widget.json").write_text(json.dumps(
        {"elements": [{"type": "metric", "label": "Value", "value": "ok"}]}),
        encoding="utf-8")
    (folder / "sample.json").write_text(json.dumps({"bindings": {}}), encoding="utf-8")
    (folder / "data.json").write_text(json.dumps({"value": 1}), encoding="utf-8")
    return folder


_AUTO_PIN = object()


def catalog_entry(folder, plugin_id, *, version="1.0.0", risk="T1",
                  signature="signed", publisher="agent-desk", category="time",
                  tags=("time",), summary="A sample widget", capabilities=None,
                  name=None, digest=_AUTO_PIN):
    entry = {
        "id": plugin_id,
        "name": name or plugin_id.replace("-", " ").title(),
        "version": version,
        "publisher": publisher,
        "publisherVerified": True,
        "category": category,
        "tags": list(tags),
        "summary": summary,
        "description": "A longer description used by the marketplace tests.",
        "icon": "clock",
        "riskTier": risk,
        "license": "MIT",
        "signature": {"status": signature},
        "path": str(folder),
    }
    if capabilities is not None:
        entry["capabilities"] = capabilities
    if digest is _AUTO_PIN:
        entry["digest"] = tree_digest(Path(folder))
    elif isinstance(digest, str) and digest:
        entry["digest"] = digest
    return entry


def write_org_catalog(boot, entries):
    (marketplace_dir(boot) / "org-catalog.json").write_text(
        json.dumps({"schemaVersion": 2, "plugins": entries}), encoding="utf-8")


def write_peer_catalog(boot, entries):
    (marketplace_dir(boot) / "peer-catalog.json").write_text(
        json.dumps({"schemaVersion": 2, "plugins": entries}), encoding="utf-8")


def write_policy(boot, policy):
    (marketplace_dir(boot) / "policy.json").write_text(
        json.dumps(policy), encoding="utf-8")


def write_packs(boot, packs):
    """Point this boot at a registry fixture that carries only packs.json."""
    root = workspace(boot) / "packs-registry"
    root.mkdir(parents=True, exist_ok=True)
    (root / "packs.json").write_text(
        json.dumps({"schemaVersion": 1, "packs": packs}), encoding="utf-8")
    boot.server.registry_root = str(root)
    return root


def get_json(boot, path, headers=None):
    status, _headers, body = boot.request(
        "GET", path, headers=headers or boot.auth)
    return status, json.loads(body)


def post_json(boot, path, payload, headers=None):
    status, _headers, body = boot.post_json(
        path, payload, headers=headers or boot.auth)
    return status, json.loads(body)


def installed_plugins(boot):
    status, body = get_json(boot, "/api/marketplace/installed")
    assert status == 200
    return {plugin["id"]: plugin for plugin in body["plugins"]}


# -- auth gates ---------------------------------------------------------

def test_catalog_requires_session(booted):
    status, _headers, _body = booted.request(
        "GET", "/api/marketplace/catalog", headers=booted.host_header())
    assert status == 401


def test_every_marketplace_get_route_requires_session(booted):
    for path in ("/api/marketplace/catalog", "/api/marketplace/plugin/sample",
                 "/api/marketplace/installed", "/api/marketplace/publisher/acme",
                 "/api/marketplace/policy", "/api/marketplace/audit",
                 "/api/marketplace/packs"):
        status, _headers, _body = booted.request(
            "GET", path, headers=booted.host_header())
        assert status == 401, path


def test_every_marketplace_post_route_requires_session(booted):
    for path in ("/install", "/update", "/consent", "/rollback", "/uninstall",
                 "/enable", "/disable", "/retest", "/purge-data", "/report",
                 "/publish", "/deprecate", "/yank", "/quarantine",
                 "/packs/install", "/validate"):
        status, _headers, _body = booted.post_json(
            "/api/marketplace" + path, {"id": "sample"},
            headers=booted.host_header())
        assert status == 401, path


def test_marketplace_rejects_a_foreign_origin(booted):
    headers = dict(booted.auth)
    headers["Origin"] = "http://evil.example"
    status, _headers, _body = booted.request(
        "GET", "/api/marketplace/catalog", headers=headers)
    assert status == 403
    status, _headers, _body = booted.request(
        "POST", "/api/marketplace/install", headers=headers,
        body=b"{}")
    assert status == 403


def test_marketplace_rejects_a_foreign_host(booted):
    headers = {"Cookie": booted.auth["Cookie"], "Host": "evil.example"}
    status, _headers, _body = booted.request(
        "GET", "/api/marketplace/catalog", headers=headers)
    assert status == 403


# -- catalog ------------------------------------------------------------

def test_catalog_filters_compose(booted):
    root = workspace(booted) / "fixtures"
    alpha = make_plugin(root, "alpha", folder_name="alpha",
                        tags=("clock", "focus"), summary="Focus timer")
    beta = make_plugin(root, "beta", folder_name="beta", category="finance",
                       publisher="other-co", tags=("money",),
                       summary="Spend tracker")
    killed = make_plugin(root, "kill-me", folder_name="kill-me",
                         tags=("clock",), summary="Focus experiment")
    write_org_catalog(booted, [
        catalog_entry(alpha, "alpha", tags=("clock", "focus"),
                      summary="Focus timer"),
        catalog_entry(beta, "beta", category="finance", publisher="other-co",
                      tags=("money",), summary="Spend tracker"),
        catalog_entry(killed, "kill-me", tags=("clock",),
                      summary="Focus experiment"),
    ])
    write_policy(booted, {"killSwitch": ["kill-me"]})

    status, body = get_json(booted, "/api/marketplace/catalog?source=org")
    assert status == 200
    assert body["total"] == 3
    sources = {entry["source"]: entry["count"] for entry in body["sources"]}
    assert sources["org"] == 3
    assert sources.get("bundled", 0) == 3
    assert body["policy"]["mode"] == "curated"

    _status, body = get_json(booted, "/api/marketplace/catalog?source=org&q=focus")
    assert {entry["id"] for entry in body["entries"]} == {"alpha", "kill-me"}

    _status, body = get_json(booted, "/api/marketplace/catalog?source=org&q=SPEND")
    assert [entry["id"] for entry in body["entries"]] == ["beta"]

    _status, body = get_json(
        booted,
        "/api/marketplace/catalog?source=org&q=clock&category=time&eligible=true")
    assert [entry["id"] for entry in body["entries"]] == ["alpha"]

    _status, body = get_json(
        booted, "/api/marketplace/catalog?source=org&category=finance")
    assert [entry["id"] for entry in body["entries"]] == ["beta"]

    _status, body = get_json(booted, "/api/marketplace/catalog?source=peer")
    assert body["entries"] == []

    _status, body = get_json(booted, "/api/marketplace/catalog?source=org&risk=T0")
    assert body["entries"] == []

    _status, body = get_json(booted, "/api/marketplace/catalog?source=org&eligible=true")
    assert {entry["id"] for entry in body["entries"]} == {"alpha", "beta"}

    _status, full = get_json(booted, "/api/marketplace/catalog?source=org")
    killed_card = next(entry for entry in full["entries"] if entry["id"] == "kill-me")
    assert killed_card["eligible"] is False
    assert killed_card["ineligibleReasons"][0]["code"] == "policy:kill-switch"


def test_missing_registry_falls_back_to_the_committed_bundle(booted):
    status, body = get_json(booted, "/api/marketplace/catalog")
    assert status == 200
    assert body["total"] == 3
    assert all(entry["source"] == "bundled" for entry in body["entries"])
    assert body["entries"]


def test_kill_switch_blocks_install(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "kill-me")
    write_org_catalog(booted, [catalog_entry(folder, "kill-me")])
    write_policy(booted, {"killSwitch": ["kill-me"]})

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "kill-me"})
    assert status == 403
    assert body["error"] == "policy:kill-switch"
    assert body["details"]["reasons"][0]["code"] == "policy:kill-switch"


# -- digest enforcement -------------------------------------------------

def test_install_refuses_a_tampered_tree_and_installs_nothing(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "tamper-me")
    ui = folder / "widget.ui.json"
    ui.write_text('{"elements": []}', encoding="utf-8")
    write_org_catalog(booted, [catalog_entry(folder, "tamper-me")])
    ui.write_text('{"elements": []} ', encoding="utf-8")

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "tamper-me"})
    assert status == 409
    assert body["error"] == "install:digest-mismatch"
    assert body["details"]["id"] == "tamper-me"
    assert body["details"]["expected"] != body["details"]["actual"]
    assert installed_plugins(booted) == {}


def test_install_accepts_a_tree_that_matches_the_pin(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "pinned")
    write_org_catalog(booted, [catalog_entry(folder, "pinned")])
    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "pinned"})
    assert status == 200
    assert body["status"] == "installed"
    assert "pinned" in installed_plugins(booted)


def test_install_refuses_a_missing_catalog_pin(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "unpinned")
    write_org_catalog(booted, [
        catalog_entry(folder, "unpinned", digest=None)])

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "unpinned"})
    assert status == 409
    assert body["error"] == "install:digest-mismatch"
    assert "unpinned" in body["message"]
    assert "no digest pinned" in body["message"]
    assert installed_plugins(booted) == {}


def test_update_refuses_a_tampered_tree(booted):
    root = workspace(booted) / "fixtures"
    v1 = make_plugin(root, "upd-tamper", version="1.0.0",
                     folder_name="upd-tamper-v1")
    write_org_catalog(booted, [
        catalog_entry(v1, "upd-tamper", version="1.0.0")])
    status, _body = post_json(
        booted, "/api/marketplace/install", {"id": "upd-tamper"})
    assert status == 200

    v2 = make_plugin(root, "upd-tamper", version="1.1.0",
                     folder_name="upd-tamper-v2")
    write_org_catalog(booted, [
        catalog_entry(v2, "upd-tamper", version="1.1.0")])
    (v2 / "widget.ui.json").write_text('{"elements": []} ', encoding="utf-8")

    status, body = post_json(
        booted, "/api/marketplace/update", {"id": "upd-tamper"})
    assert status == 409
    assert body["error"] == "install:digest-mismatch"
    assert "upd-tamper" in installed_plugins(booted)


def test_pack_install_refuses_one_tampered_member_and_installs_none(booted):
    root = workspace(booted) / "fixtures"
    alpha = make_plugin(root, "alpha")
    beta = make_plugin(root, "beta")
    ui = beta / "widget.ui.json"
    ui.write_text('{"elements": []}', encoding="utf-8")
    write_org_catalog(booted, [
        catalog_entry(alpha, "alpha"), catalog_entry(beta, "beta")])
    write_packs(booted, [{
        "id": "manager", "name": "Manager pack", "plugins": ["alpha", "beta"],
    }])
    ui.write_text('{"elements": []} ', encoding="utf-8")

    status, body = post_json(
        booted, "/api/marketplace/packs/install", {"id": "manager"})
    assert status == 409
    assert body["error"] == "install:digest-mismatch"
    assert body["details"]["blockedMember"] == "beta"
    assert body["details"]["installed"] == []
    assert installed_plugins(booted) == {}


# -- moderation enforcement --------------------------------------------

def test_yank_blocks_install(booted, admin):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "yanked")
    write_org_catalog(booted, [catalog_entry(folder, "yanked")])

    status, body = post_json(booted, "/api/marketplace/yank", {
        "id": "yanked", "version": "1.0.0", "reason": "malware"})
    assert status == 200

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "yanked"})
    assert status == 403
    assert body["error"] == "policy:yanked"
    assert installed_plugins(booted) == {}


def test_quarantine_blocks_install(booted, admin):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "quarantined")
    write_org_catalog(booted, [catalog_entry(folder, "quarantined")])

    status, body = post_json(booted, "/api/marketplace/quarantine", {
        "id": "quarantined", "version": "1.0.0", "reason": "investigation"})
    assert status == 200

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "quarantined"})
    assert status == 403
    assert body["error"] == "policy:quarantined"
    assert installed_plugins(booted) == {}


def test_deprecate_keeps_the_plugin_installable(booted, admin):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "deprecated")
    write_org_catalog(booted, [catalog_entry(folder, "deprecated")])

    status, body = post_json(booted, "/api/marketplace/deprecate", {
        "id": "deprecated", "version": "1.0.0", "reason": "superseded"})
    assert status == 200

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "deprecated"})
    assert status == 200
    assert body["status"] == "installed"

    _status, card = get_json(booted, "/api/marketplace/catalog")
    entry = [item for item in card["entries"] if item["id"] == "deprecated"][0]
    assert entry["eligible"] is True
    assert entry["deprecated"]["reason"] == "superseded"


def test_network_allowlist_blocks_then_allows(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "net-plugin", network=("api.example.com",))
    write_org_catalog(booted, [catalog_entry(
        folder, "net-plugin", risk="T2", publisher="net-co",
        capabilities={"network": ["api.example.com"]})])
    write_policy(booted, {
        "riskCeiling": "T2",
        "allowedPublishers": ["net-co"],
        "networkAllowlist": [],
    })

    _status, body = get_json(booted, "/api/marketplace/catalog?source=org")
    card = body["entries"][0]
    assert card["id"] == "net-plugin"
    assert card["eligible"] is False
    assert card["ineligibleReasons"][0]["code"] == "policy:network-not-allowed"

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "net-plugin"})
    assert status == 403
    assert body["error"] == "policy:network-not-allowed"

    write_policy(booted, {
        "riskCeiling": "T2",
        "allowedPublishers": ["net-co"],
        "networkAllowlist": ["api.example.com"],
    })
    _status, body = get_json(booted, "/api/marketplace/catalog?source=org")
    assert body["entries"][0]["id"] == "net-plugin"
    assert body["entries"][0]["eligible"] is True

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "net-plugin"})
    assert status == 200
    assert body["id"] == "net-plugin"
    assert body["status"] == "installed"


# -- updates, consent, rollback ----------------------------------------

def test_widening_update_needs_consent_and_narrowing_does_not(booted):
    root = workspace(booted) / "fixtures"
    v1 = make_plugin(root, "upd", version="1.0.0", folder_name="upd-v1")
    write_org_catalog(booted, [catalog_entry(v1, "upd", version="1.0.0")])
    status, _body = post_json(booted, "/api/marketplace/install", {"id": "upd"})
    assert status == 200

    v2 = make_plugin(root, "upd", version="1.1.0", folder_name="upd-v2",
                     llm_allow=True)
    write_org_catalog(booted, [catalog_entry(v2, "upd", version="1.1.0")])
    status, body = post_json(booted, "/api/marketplace/update", {"id": "upd"})
    assert status == 200
    assert body["pendingConsent"] is True
    assert body["addedScopes"]
    assert body["widening"] == body["addedScopes"]
    assert body["to"] == "1.1.0"

    status, body = post_json(
        booted, "/api/marketplace/consent", {"id": "upd", "decision": "accept"})
    assert status == 200
    assert body["version"] == "1.1.0"

    # A True->False value drop is a narrowing to the display lists but a
    # held value change to the runtime, so the user, not the marketplace,
    # accepts it (fail-closed: the runtime's diff is the only decision
    # input).
    v3 = make_plugin(root, "upd", version="1.2.0", folder_name="upd-v3",
                     llm_allow=False)
    write_org_catalog(booted, [catalog_entry(v3, "upd", version="1.2.0")])
    status, body = post_json(booted, "/api/marketplace/update", {"id": "upd"})
    assert status == 200
    assert body["pendingConsent"] is True
    assert body["addedScopes"] == []
    assert body["removedScopes"]
    status, body = post_json(
        booted, "/api/marketplace/consent", {"id": "upd", "decision": "accept"})
    assert status == 200
    assert body["version"] == "1.2.0"
    assert installed_plugins(booted)["upd"]["version"] == "1.2.0"


def test_pure_narrowing_update_applies_without_consent(booted):
    """Removing an entire optional scope key, with no value changes, is a
    narrowing to the runtime too: its diff adds nothing, so the update
    applies at once."""
    root = workspace(booted) / "fixtures"
    v1 = make_plugin(root, "narrow", version="1.0.0", folder_name="narrow-v1",
                     network=("api.example.com",))
    write_org_catalog(booted, [catalog_entry(v1, "narrow", version="1.0.0")])
    status, _body = post_json(booted, "/api/marketplace/install", {"id": "narrow"})
    assert status == 200

    v2 = make_plugin(root, "narrow", version="1.1.0", folder_name="narrow-v2")
    write_org_catalog(booted, [catalog_entry(v2, "narrow", version="1.1.0")])
    status, body = post_json(booted, "/api/marketplace/update", {"id": "narrow"})
    assert status == 200
    assert body["pendingConsent"] is False
    assert body["addedScopes"] == []
    assert body["removedScopes"]
    assert body["to"] == "1.1.0"
    assert installed_plugins(booted)["narrow"]["version"] == "1.1.0"


def test_widening_an_optional_network_scope_also_needs_consent(booted):
    root = workspace(booted) / "fixtures"
    v1 = make_plugin(root, "optnet", version="1.0.0", folder_name="optnet-v1")
    write_org_catalog(booted, [catalog_entry(v1, "optnet", version="1.0.0")])
    status, _body = post_json(booted, "/api/marketplace/install", {"id": "optnet"})
    assert status == 200

    write_policy(booted, {"networkAllowlist": ["api.example.com"]})
    v2 = make_plugin(root, "optnet", version="1.1.0", folder_name="optnet-v2",
                     network=["api.example.com"])
    write_org_catalog(booted, [catalog_entry(
        v2, "optnet", version="1.1.0",
        capabilities={"network": ["api.example.com"]})])
    status, body = post_json(booted, "/api/marketplace/update", {"id": "optnet"})
    assert status == 200, body
    assert body["pendingConsent"] is True
    assert any("api.example.com" in scope for scope in body["widening"])
    assert installed_plugins(booted)["optnet"]["version"] == "1.0.0"

    status, body = post_json(
        booted, "/api/marketplace/consent", {"id": "optnet", "decision": "reject"})
    assert status == 200
    assert body["status"] == "rejected"
    assert installed_plugins(booted)["optnet"]["version"] == "1.0.0"


def test_rollback_reverts_to_the_previous_version(booted):
    root = workspace(booted) / "fixtures"
    v1 = make_plugin(root, "roll", version="1.0.0", folder_name="roll-v1")
    write_org_catalog(booted, [catalog_entry(v1, "roll", version="1.0.0")])
    status, _body = post_json(booted, "/api/marketplace/install", {"id": "roll"})
    assert status == 200

    v2 = make_plugin(root, "roll", version="1.1.0", folder_name="roll-v2")
    write_org_catalog(booted, [catalog_entry(v2, "roll", version="1.1.0")])
    status, body = post_json(booted, "/api/marketplace/update", {"id": "roll"})
    assert status == 200
    assert body["pendingConsent"] is False

    status, body = post_json(
        booted, "/api/marketplace/rollback", {"id": "roll"})
    assert status == 200
    assert body["from"] == "1.1.0"
    assert body["to"] == "1.0.0"
    assert installed_plugins(booted)["roll"]["version"] == "1.0.0"


def test_rollback_honours_an_explicit_prior_version(booted):
    root = workspace(booted) / "fixtures"
    for version in ("1.0.0", "1.1.0", "1.2.0"):
        folder = make_plugin(root, "rollx", version=version,
                             folder_name="rollx-" + version)
        write_org_catalog(booted, [catalog_entry(folder, "rollx", version=version)])
        verb = "install" if version == "1.0.0" else "update"
        status, _body = post_json(
            booted, "/api/marketplace/" + verb, {"id": "rollx"})
        assert status == 200
    assert installed_plugins(booted)["rollx"]["version"] == "1.2.0"

    status, body = post_json(
        booted, "/api/marketplace/rollback",
        {"id": "rollx", "toVersion": "1.0.0"})
    assert status == 200, body
    assert body["from"] == "1.2.0"
    assert body["to"] == "1.0.0"
    assert installed_plugins(booted)["rollx"]["version"] == "1.0.0"

    status, body = post_json(
        booted, "/api/marketplace/rollback", {"id": "rollx", "toVersion": ""})
    assert status == 400
    assert body["error"] == "marketplace:invalid-request"


# -- lifecycle ----------------------------------------------------------

def test_purge_without_confirmation_returns_the_confirmation_error(booted):
    root = workspace(booted) / "fixtures"
    v1 = make_plugin(root, "purge-me")
    write_org_catalog(booted, [catalog_entry(v1, "purge-me")])
    status, _body = post_json(
        booted, "/api/marketplace/install", {"id": "purge-me"})
    assert status == 200

    status, body = post_json(
        booted, "/api/marketplace/purge-data", {"id": "purge-me"})
    assert status == 409
    assert body["error"] == "purge:confirmation-required"

    status, body = post_json(
        booted, "/api/marketplace/purge-data",
        {"id": "purge-me", "confirm": "delete-data:purge-me"})
    assert status == 200
    assert body["purged"] == "purge-me"


def test_installed_lists_runtime_records(booted):
    root = workspace(booted) / "fixtures"
    v1 = make_plugin(root, "listed")
    write_org_catalog(booted, [catalog_entry(v1, "listed")])
    status, _body = post_json(
        booted, "/api/marketplace/install", {"id": "listed"})
    assert status == 200
    plugins = installed_plugins(booted)
    listed = plugins["listed"]
    assert listed["pinned"]["version"] == "1.0.0"
    assert listed["enabled"] is True
    assert listed["pendingConsent"] is False
    assert "status" in listed


# -- policy and errors --------------------------------------------------

def test_policy_route_invalid_json_falls_back_with_warning(booted):
    (marketplace_dir(booted) / "policy.json").write_text(
        "{not json", encoding="utf-8")
    status, body = get_json(booted, "/api/marketplace/policy")
    assert status == 200
    assert body["mode"] == "curated"
    assert body["riskCeiling"] == "T1"
    assert body["signatureStatus"] == "unsigned"
    assert body["warning"]


def test_float_bearing_policy_keeps_marketplace_routes_alive(booted):
    signer = make_key("policy-signer")
    bundle = policy_bundle(signer)
    bundle["policy"]["retentionDays"] = 30.5
    write_policy(booted, bundle)

    status, catalog = get_json(booted, "/api/marketplace/catalog")
    assert status == 200
    assert catalog["policy"] == {"mode": "curated", "source": "built-in",
                                 "signatureStatus": "tampered"}

    status, policy = get_json(booted, "/api/marketplace/policy")
    assert status == 200
    assert policy["mode"] == "curated"
    assert policy["signatureStatus"] == "tampered"
    assert "rejected" in policy["warning"]

    status, trust = get_json(booted, "/api/marketplace/trust")
    assert status == 200
    assert trust["policy"]["signatureStatus"] == "tampered"


def test_unsigned_overlay_cannot_forge_the_catalog_policy_banner(booted):
    write_policy(booted, {"source": "signed", "signatureStatus": "signed"})

    status, catalog = get_json(booted, "/api/marketplace/catalog")
    assert status == 200
    assert catalog["policy"] == {"mode": "curated", "source": "local-admin",
                                 "signatureStatus": "unsigned"}

    status, policy = get_json(booted, "/api/marketplace/policy")
    assert status == 200
    assert policy["source"] == "local-admin"
    assert policy["signatureStatus"] == "unsigned"


def test_unknown_plugin_and_route_are_catalog_not_found(booted):
    status, body = get_json(booted, "/api/marketplace/plugin/nope")
    assert status == 404
    assert body["error"] == "catalog:not-found"
    assert body["details"]["id"] == "nope"

    status, body = post_json(
        booted, "/api/marketplace/install", {"id": "nope"})
    assert status == 404
    assert body["error"] == "catalog:not-found"

    status, body = get_json(booted, "/api/marketplace/nope")
    assert status == 404
    assert body["error"] == "catalog:not-found"
    assert body["details"]["path"] == "/api/marketplace/nope"


def test_legacy_plugin_and_registry_routes_are_unchanged(booted):
    status, body = get_json(booted, "/api/plugins")
    assert status == 200
    assert body == {"plugins": []}

    status, body = get_json(booted, "/api/registry")
    assert status == 200
    assert body["ok"] is False
    assert "origin" in body


def test_plugin_detail_route_shape(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "detailed", summary="Detail sample")
    write_org_catalog(booted, [catalog_entry(folder, "detailed",
                                             summary="Detail sample")])
    status, _body = post_json(
        booted, "/api/marketplace/install", {"id": "detailed"})
    assert status == 200

    status, body = get_json(booted, "/api/marketplace/plugin/detailed")
    assert status == 200
    plugin = body["plugin"]
    assert plugin["id"] == "detailed"
    for key in ("description", "highlights", "license", "homepage",
                "requires", "minHost", "digest", "signature", "provenance",
                "capabilities", "changelog", "publishedAt", "validation",
                "eligible", "ineligibleReasons"):
        assert key in plugin, key
    assert body["installed"]["id"] == "detailed"
    assert body["versions"][0]["version"] == "1.0.0"
    assert "detailed" not in {item["id"] for item in body["alternatives"]}

    status, body = get_json(
        booted, "/api/marketplace/plugin/detailed?version=9.9.9")
    assert status == 404
    assert body["error"] == "catalog:not-found"


def test_lifecycle_toggles_retest_uninstall_and_audit(booted, admin):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "toggle")
    write_org_catalog(booted, [catalog_entry(folder, "toggle")])
    status, _body = post_json(
        booted, "/api/marketplace/install", {"id": "toggle"})
    assert status == 200

    status, body = post_json(
        booted, "/api/marketplace/disable", {"id": "toggle"})
    assert status == 200
    assert body["state"] == "disabled"
    assert installed_plugins(booted)["toggle"]["enabled"] is False

    status, body = post_json(
        booted, "/api/marketplace/enable", {"id": "toggle"})
    assert status == 200
    assert body["state"] == "enabled"
    assert installed_plugins(booted)["toggle"]["enabled"] is True

    status, _body = post_json(
        booted, "/api/marketplace/retest", {"id": "toggle"})
    assert status == 200

    status, body = post_json(
        booted, "/api/marketplace/uninstall", {"id": "toggle"})
    assert status == 200
    assert body["state"] == "uninstalled"

    status, body = get_json(booted, "/api/marketplace/audit?limit=20")
    assert status == 200
    actions = [event["action"] for event in body["events"]]
    assert "install" in actions
    assert "uninstall" in actions


def test_publish_queues_a_pending_publication(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "publish-me")
    status, body = post_json(
        booted, "/api/marketplace/publish", {"folder": str(folder)})
    assert status == 202
    assert body["pendingId"].startswith("pub-")
    assert body["validation"]["ok"] is True
    queued = marketplace_dir(booted) / "pending" / f"{body['pendingId']}.json"
    assert queued.is_file()

# -- packs --------------------------------------------------------------

def test_packs_list_member_cards_scopes_and_eligibility(booted):
    root = workspace(booted) / "fixtures"
    alpha = make_plugin(root, "alpha", folder_name="alpha")
    beta = make_plugin(root, "beta", folder_name="beta", category="finance")
    write_org_catalog(booted, [
        catalog_entry(alpha, "alpha", capabilities={
            "permissions": ["filesystem.read: ${workspace}/finance/**"]}),
        catalog_entry(beta, "beta", category="finance", capabilities={
            "permissions": ["filesystem.read: ${workspace}/sales/**"]}),
    ])
    write_packs(booted, [{
        "id": "manager",
        "name": "Manager pack",
        "audience": "Managers",
        "summary": "A pack for the weekly manager review.",
        "icon": "folder",
        "plugins": ["alpha", "beta"],
        "excluded": [{"id": "competitor-watch",
                      "reason": "network plugin, excluded from packs"}],
        "sampleData": False,
        "firstRun": True,
    }])

    status, body = get_json(booted, "/api/marketplace/packs")
    assert status == 200
    assert body["total"] == 1
    assert body["policy"]["mode"] == "curated"
    pack = body["packs"][0]
    assert pack["id"] == "manager"
    assert pack["name"] == "Manager pack"
    assert pack["eligible"] is True
    assert pack["blockedMember"] is None
    assert [member["id"] for member in pack["members"]] == ["alpha", "beta"]
    assert pack["members"][0]["scopes"] == [
        "filesystem.read: ${workspace}/finance/**"]
    assert [card["id"] for card in pack["plugins"]] == ["alpha", "beta"]
    assert pack["excluded"][0]["id"] == "competitor-watch"


def test_pack_install_is_all_or_none_and_names_the_blocked_member(booted):
    root = workspace(booted) / "fixtures"
    alpha = make_plugin(root, "alpha", folder_name="alpha")
    beta = make_plugin(root, "beta", folder_name="beta")
    write_org_catalog(booted, [
        catalog_entry(alpha, "alpha"), catalog_entry(beta, "beta")])
    write_packs(booted, [{
        "id": "manager", "name": "Manager pack", "plugins": ["alpha", "beta"],
    }])
    write_policy(booted, {"killSwitch": ["beta"]})

    status, body = get_json(booted, "/api/marketplace/packs")
    pack = body["packs"][0]
    assert pack["eligible"] is False
    assert pack["blockedMember"] == "beta"
    assert pack["blockedReason"]

    status, body = post_json(
        booted, "/api/marketplace/packs/install", {"id": "manager"})
    assert status == 403
    assert body["error"] == "policy:kill-switch"
    assert body["details"]["blockedMember"] == "beta"
    assert body["details"]["installed"] == []
    assert "beta is blocked" in body["message"]
    assert installed_plugins(booted) == {}


def test_pack_install_installs_every_member_then_reports_already_installed(booted):
    root = workspace(booted) / "fixtures"
    alpha = make_plugin(root, "alpha", folder_name="alpha")
    beta = make_plugin(root, "beta", folder_name="beta")
    write_org_catalog(booted, [
        catalog_entry(alpha, "alpha"), catalog_entry(beta, "beta")])
    write_packs(booted, [{
        "id": "manager", "name": "Manager pack", "plugins": ["alpha", "beta"],
    }])

    status, body = post_json(
        booted, "/api/marketplace/packs/install", {"id": "manager"})
    assert status == 200
    assert body["status"] == "installed"
    assert [item["id"] for item in body["installed"]] == ["alpha", "beta"]
    assert body["alreadyInstalled"] == []
    installed = installed_plugins(booted)
    assert set(installed) == {"alpha", "beta"}

    status, body = post_json(
        booted, "/api/marketplace/packs/install", {"id": "manager"})
    assert status == 200
    assert body["installed"] == []
    assert body["alreadyInstalled"] == ["alpha", "beta"]


def test_unknown_pack_install_is_a_404(booted):
    write_packs(booted, [])
    status, body = post_json(
        booted, "/api/marketplace/packs/install", {"id": "missing"})
    assert status == 404
    assert body["error"] == "pack:not-found"


# -- studio validate and inline publish ---------------------------------

def _inline_body(folder):
    return {
        "manifest": json.loads((folder / "manifest.json").read_text(encoding="utf-8")),
        "widgetUi": json.loads((folder / "widget.json").read_text(encoding="utf-8")),
        "sample": json.loads((folder / "sample.json").read_text(encoding="utf-8")),
    }


def test_validate_accepts_an_inline_manifest_and_reports_failures(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "inline-check")
    body = _inline_body(folder)

    status, verdict = post_json(booted, "/api/marketplace/validate", body)
    assert status == 200
    assert verdict["ok"] is True
    assert verdict["failures"] == []

    worst = dict(body)
    worst["manifest"] = dict(body["manifest"])
    worst["manifest"]["summary"] = "x" * 121
    status, verdict = post_json(booted, "/api/marketplace/validate", worst)
    assert status == 200
    assert verdict["ok"] is False
    assert any(failure["code"] == "bad-schema"
               for failure in verdict["failures"])


def test_inline_publish_requires_changelog_and_license_grant(booted):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "studio-plugin")
    body = _inline_body(folder)
    body["changelog"] = "First release."
    body["licenseGrant"] = True

    status, response = post_json(booted, "/api/marketplace/publish", body)
    assert status == 202
    assert response["status"] == "pending-review"
    assert response["validation"]["ok"] is True
    queued = marketplace_dir(booted) / "pending" / f"{response['pendingId']}.json"
    assert queued.is_file()
    record = json.loads(queued.read_text(encoding="utf-8"))
    assert record["changelog"] == "First release."
    assert record["licenseGrant"] is True
    assert record["manifest"]["id"] == "studio-plugin"

    without_changelog = dict(body)
    del without_changelog["changelog"]
    status, response = post_json(
        booted, "/api/marketplace/publish", without_changelog)
    assert status == 400
    assert response["error"] == "publish:changelog-required"

    without_grant = dict(body)
    without_grant["licenseGrant"] = False
    status, response = post_json(
        booted, "/api/marketplace/publish", without_grant)
    assert status == 400
    assert response["error"] == "publish:license-required"

# -- signed policy, admin and trust center (T13) -------------------------

from trust_fixtures import make_key, policy_bundle, policy_bundle_fields  # noqa: E402
from agentdesk.marketplace.signed_policy import fingerprint  # noqa: E402


@pytest.fixture()
def admin(monkeypatch):
    monkeypatch.setenv("AGENTDESK_MARKETPLACE_ADMIN", "1")
    return monkeypatch


def queue_publication(boot, plugin_id="pending-widget", **kwargs):
    root = workspace(boot) / "publication-sources"
    folder = make_plugin(root, plugin_id, **kwargs)
    status, body = post_json(
        boot, "/api/marketplace/publish",
        {"folder": str(folder), "changelog": "Adds the first widget."})
    assert status == 202, body
    return folder, body["pendingId"]


def test_admin_is_403_without_the_environment(booted, monkeypatch):
    monkeypatch.delenv("AGENTDESK_MARKETPLACE_ADMIN", raising=False)

    for path in ("/api/marketplace/admin", "/api/marketplace/audit",
                 "/api/marketplace/audit/export"):
        status, body = get_json(booted, path)
        assert status == 403
        assert body["error"] == "admin:disabled"

    status, body = post_json(booted, "/api/marketplace/policy/import",
                             {"bundle": {}})
    assert status == 403
    assert body["error"] == "admin:disabled"
    assert not (marketplace_dir(booted) / "policy.json").exists()


def test_admin_is_200_with_the_environment(booted, admin):
    status, body = get_json(booted, "/api/marketplace/admin")
    assert status == 200
    assert set(body) == {"posture", "anchor", "policy", "pending", "revoked",
                        "inventory", "catalogSource", "auditEvents"}
    assert body["anchor"] == {"epoch": 0, "fingerprints": []}
    assert body["policy"]["signatureStatus"] == "unsigned"
    assert body["policy"]["warning"] is None
    assert body["catalogSource"] == "bundled"
    assert body["pending"] == []
    assert isinstance(body["auditEvents"], int)

    status, trust = get_json(booted, "/api/marketplace/trust")
    assert status == 200
    assert trust["reportPath"] == "/marketplace/report"
    assert trust["anchor"] == {"epoch": 0, "fingerprints": []}
    assert trust["lastValidatorRun"] == {
        "at": None, "ok": None, "failures": [], "scope": None}
    assert trust["guarantees"] and all(
        isinstance(item, str) and item.strip() for item in trust["guarantees"])
    assert trust["cannotHappen"] and all(
        isinstance(item, str) for item in trust["cannotHappen"])
    assert trust["trustStore"] == {
        "configured": False,
        "path": None,
        "note": "no registry root is available",
    }
    copy = " ".join(trust["guarantees"]).lower()
    assert "digest pinned in the catalog" in copy
    assert "not cryptographically re-verified" in copy


def test_governance_routes_require_admin(booted, monkeypatch):
    monkeypatch.delenv("AGENTDESK_MARKETPLACE_ADMIN", raising=False)
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "gated")
    write_org_catalog(booted, [catalog_entry(folder, "gated")])

    for action in ("deprecate", "yank", "quarantine"):
        status, body = post_json(booted, f"/api/marketplace/{action}", {
            "id": "gated", "version": "1.0.0", "reason": "test"})
        assert status == 403, action
        assert body["error"] == "admin:disabled"
    assert not (marketplace_dir(booted) / "governance.json").exists()

    monkeypatch.setenv("AGENTDESK_MARKETPLACE_ADMIN", "1")
    recorded = {"deprecate": "deprecated", "yank": "yanked",
                "quarantine": "quarantined"}
    for action, record in recorded.items():
        status, body = post_json(booted, f"/api/marketplace/{action}", {
            "id": "gated", "version": "1.0.0", "reason": "test"})
        assert status == 200, action
        assert body["ok"] is True
        assert body["entry"]["action"] == record


def test_session_check_precedes_admin_mode(booted, admin):
    headers = {"Host": booted.host_header()["Host"]}
    for path in ("/api/marketplace/admin", "/api/marketplace/trust",
                 "/api/marketplace/audit/export"):
        status, _headers, _body = booted.request("GET", path, headers=headers)
        assert status == 401, path
    for path in ("/api/marketplace/policy/import",
                 "/api/marketplace/admin/kill-switch",
                 "/api/marketplace/admin/publications/pub-abc/approve"):
        status, _headers, _body = booted.request(
            "POST", path, headers={**headers, "Content-Type": "application/json"},
            body=b"{}")
        assert status == 401, path


def test_policy_import_shows_the_diff_before_applying(booted, admin):
    signer = make_key("policy-signer")
    bundle = policy_bundle(
        signer, fields=policy_bundle_fields(
            mode="open", riskCeiling="T2", allowedPublishers=["zeta", "acme"]),
        revocation_epoch=2)

    status, body = post_json(
        booted, "/api/marketplace/policy/import",
        {"bundle": bundle, "confirm": False})

    assert status == 200
    assert body["applied"] is False
    verification = body["verification"]
    assert verification["signatureStatus"] == "signed"
    assert verification["epoch"] == 2
    assert verification["signerFingerprint"] == fingerprint(signer.public)
    assert verification["warning"] is None
    fields = [change["field"] for change in body["diff"]]
    assert fields == sorted(fields)
    by_field = {change["field"]: change for change in body["diff"]}
    assert by_field["mode"] == {"field": "mode", "before": "curated",
                                "after": "open"}
    assert by_field["riskCeiling"]["after"] == "T2"
    assert by_field["allowedPublishers"]["after"] == ["acme", "zeta"]
    assert all(set(change) == {"field", "before", "after"}
               for change in body["diff"])

    # Nothing was written and the effective policy is still the default.
    assert not (marketplace_dir(booted) / "policy.json").exists()
    status, policy = get_json(booted, "/api/marketplace/policy")
    assert status == 200
    assert policy["signatureStatus"] == "unsigned"
    assert policy["mode"] == "curated"


def test_policy_import_applies_after_confirm_and_pins_the_anchor(booted, admin):
    signer = make_key("policy-signer")
    bundle = policy_bundle(
        signer, fields=policy_bundle_fields(mode="open", riskCeiling="T2"),
        revocation_epoch=2)

    status, body = post_json(
        booted, "/api/marketplace/policy/import",
        {"bundle": bundle, "confirm": True})

    assert status == 200, body
    assert body["applied"] is True
    written = json.loads((marketplace_dir(booted) / "policy.json").read_text(
        encoding="utf-8"))
    assert written == bundle

    status, policy = get_json(booted, "/api/marketplace/policy")
    assert status == 200
    assert policy["mode"] == "open"
    assert policy["riskCeiling"] == "T2"
    assert policy["source"] == "signed"
    assert policy["signatureStatus"] == "signed"
    assert policy["epoch"] == 2
    assert policy["signerFingerprint"] == fingerprint(signer.public)

    status, snapshot = get_json(booted, "/api/marketplace/admin")
    assert status == 200
    assert snapshot["anchor"] == {
        "epoch": 2, "fingerprints": [fingerprint(signer.public)]}
    assert snapshot["policy"]["signatureStatus"] == "signed"
    assert snapshot["auditEvents"] >= 1

    audit_path = marketplace_dir(booted) / "audit.json"
    events = json.loads(audit_path.read_text(encoding="utf-8"))
    assert events[-1]["action"] == "policy.import"
    assert events[-1]["outcome"] == "applied"

    status, trust = get_json(booted, "/api/marketplace/trust")
    assert trust["policy"]["signatureStatus"] == "signed"
    assert trust["lastValidatorRun"]["ok"] is True
    assert trust["lastValidatorRun"]["scope"] == "policy"
    assert trust["lastValidatorRun"]["at"]


def test_tampered_import_is_rejected_and_nothing_is_written(booted, admin):
    signer = make_key("policy-signer")
    bundle = policy_bundle(signer)
    bundle["policy"]["riskCeiling"] = "T3"

    status, body = post_json(
        booted, "/api/marketplace/policy/import",
        {"bundle": bundle, "confirm": True})

    assert status == 400
    assert body["error"] == "policy:bad-signature"
    assert "message" in body
    assert not (marketplace_dir(booted) / "policy.json").exists()
    events = json.loads(
        (marketplace_dir(booted) / "audit.json").read_text(encoding="utf-8"))
    rejected = [event for event in events
                if event["action"] == "policy.import" and event["outcome"] == "rejected"]
    assert rejected and rejected[-1]["detail"] == "policy:bad-signature"


def test_import_rejects_a_lower_revocation_epoch_than_the_anchor(booted, admin):
    signer = make_key("policy-signer")
    (marketplace_dir(booted) / "anchor.json").write_text(json.dumps(
        {"epoch": 3, "fingerprints": [fingerprint(signer.public)]}),
        encoding="utf-8")
    bundle = policy_bundle(signer, revocation_epoch=1)

    status, body = post_json(
        booted, "/api/marketplace/policy/import",
        {"bundle": bundle, "confirm": True})

    assert status == 400
    assert body["error"] == "policy:stale-epoch"
    assert not (marketplace_dir(booted) / "policy.json").exists()


def test_import_needs_a_bundle_object(booted, admin):
    status, body = post_json(booted, "/api/marketplace/policy/import", {})
    assert status == 400
    assert body["error"] == "marketplace:invalid-request"
    assert body["details"]["field"] == "bundle"


def test_kill_switch_disables_an_entry_and_is_audited(booted, admin):
    root = workspace(booted) / "fixtures"
    folder = make_plugin(root, "kill-target")
    write_org_catalog(booted, [catalog_entry(folder, "kill-target")])

    status, catalog = get_json(booted, "/api/marketplace/catalog")
    entry = {item["id"]: item for item in catalog["entries"]}["kill-target"]
    assert entry["source"] == "org"
    assert entry["eligible"] is True

    status, body = post_json(
        booted, "/api/marketplace/admin/kill-switch",
        {"pluginId": "kill-target", "enabled": True})
    assert status == 200
    assert body == {"ok": True, "pluginId": "kill-target", "enabled": True,
                    "killSwitch": ["kill-target"]}

    status, catalog = get_json(booted, "/api/marketplace/catalog")
    entry = {item["id"]: item for item in catalog["entries"]}["kill-target"]
    assert entry["eligible"] is False
    assert [reason["code"] for reason in entry["ineligibleReasons"]] == [
        "policy:kill-switch"]

    status, policy = get_json(booted, "/api/marketplace/policy")
    assert policy["killSwitch"] == ["kill-target"]

    status, snapshot = get_json(booted, "/api/marketplace/admin")
    assert snapshot["posture"]["killSwitch"] == ["kill-target"]
    events = json.loads(
        (marketplace_dir(booted) / "audit.json").read_text(encoding="utf-8"))
    assert events[-1]["action"] == "policy.kill-switch"
    assert events[-1]["outcome"] == "on"

    status, body = post_json(
        booted, "/api/marketplace/admin/kill-switch",
        {"pluginId": "kill-target", "enabled": False})
    assert status == 200
    assert body["killSwitch"] == []

    status, body = post_json(
        booted, "/api/marketplace/admin/kill-switch",
        {"pluginId": "kill-target", "enabled": "yes"})
    assert status == 400
    assert body["details"]["field"] == "enabled"


def test_approving_a_publication_appends_an_org_release_and_audits(booted, admin):
    folder, pending_id = queue_publication(booted, "pending-widget")

    status, snapshot = get_json(booted, "/api/marketplace/admin")
    assert snapshot["pending"][0]["id"] == pending_id
    assert snapshot["pending"][0]["pluginId"] == "pending-widget"
    assert snapshot["pending"][0]["changelog"] == "Adds the first widget."

    status, body = post_json(
        booted, f"/api/marketplace/admin/publications/{pending_id}/approve", {})

    assert status == 200, body
    assert body["decision"] == "approve"
    assert body["pluginId"] == "pending-widget"
    assert body["catalogSource"] == "org"
    assert not (marketplace_dir(booted) / "pending" / f"{pending_id}.json").exists()

    document = json.loads(
        (marketplace_dir(booted) / "org-catalog.json").read_text(encoding="utf-8"))
    release = {item["id"]: item for item in document["plugins"]}["pending-widget"]
    assert release["signature"]["status"] == "org-approved"
    org_path = Path(release["path"])
    assert org_path.is_dir()
    assert org_path.parent.parent.name == "org"
    assert release["digest"] == tree_digest(org_path)

    events = json.loads(
        (marketplace_dir(booted) / "audit.json").read_text(encoding="utf-8"))
    assert events[-1]["action"] == "publish.approve"
    assert events[-1]["outcome"] == "ok"

    status, snapshot = get_json(booted, "/api/marketplace/admin")
    assert snapshot["pending"] == []
    assert snapshot["catalogSource"] == "org"

    status, catalog = get_json(booted, "/api/marketplace/catalog")
    entry = {item["id"]: item for item in catalog["entries"]}["pending-widget"]
    assert entry["eligible"] is True

    # An approved publication must be installable from the org catalog; the
    # old flow deleted the pending folder and left no digest behind.
    status, installed = post_json(
        booted, "/api/marketplace/install", {"id": "pending-widget"})
    assert status == 200, installed
    assert installed["id"] == "pending-widget"


def test_an_approved_release_overrides_a_bundled_plugin_of_the_same_id(
        booted, admin):
    """A local approval for a shipped id must not be shadowed by the bundle."""
    _folder, pending_id = queue_publication(
        booted, "ar-aging", version="0.3.0",
        summary="An org override of the bundled plugin.")

    status, body = post_json(
        booted, f"/api/marketplace/admin/publications/{pending_id}/approve", {})
    assert status == 200, body

    status, catalog = get_json(booted, "/api/marketplace/catalog")
    entry = {item["id"]: item for item in catalog["entries"]}["ar-aging"]
    assert entry["source"] == "org"
    assert entry["version"] == "0.3.0"

    status, installed = post_json(
        booted, "/api/marketplace/install", {"id": "ar-aging"})
    assert status == 200, installed
    assert installed["id"] == "ar-aging"
    assert installed["version"] == "0.3.0"


def test_rejecting_a_publication_requires_a_reason(booted, admin):
    _folder, pending_id = queue_publication(booted, "rejected-widget")

    status, body = post_json(
        booted, f"/api/marketplace/admin/publications/{pending_id}/reject", {})
    assert status == 400
    assert body["details"]["field"] == "reason"
    assert (marketplace_dir(booted) / "pending" / f"{pending_id}.json").is_file()

    status, body = post_json(
        booted, f"/api/marketplace/admin/publications/{pending_id}/reject",
        {"reason": "Not needed for this release."})
    assert status == 200
    assert body["decision"] == "reject"
    assert not (marketplace_dir(booted) / "pending" / f"{pending_id}.json").exists()

    events = json.loads(
        (marketplace_dir(booted) / "audit.json").read_text(encoding="utf-8"))
    assert events[-1]["action"] == "publish.reject"
    assert events[-1]["detail"] == "Not needed for this release."


def test_unknown_publication_is_404(booted, admin):
    status, body = post_json(
        booted, "/api/marketplace/admin/publications/pub-missing/approve", {})
    assert status == 404
    assert body["error"] == "publish:not-found"


def test_audit_export_is_jsonl_without_message_bodies(booted, admin):
    _folder, pending_id = queue_publication(booted, "export-widget")
    status, _body = post_json(
        booted, f"/api/marketplace/admin/publications/{pending_id}/reject",
        {"reason": "SECRET-REJECTION-REASON"})
    assert status == 200

    status, headers, body = booted.request(
        "GET", "/api/marketplace/audit/export", headers=booted.auth)

    assert status == 200
    assert headers["Content-Type"].startswith("application/x-ndjson")
    assert headers["Content-Disposition"] == (
        'attachment; filename="marketplace-audit.jsonl"')
    lines = [line for line in body.decode("utf-8").splitlines() if line]
    assert lines
    events = [json.loads(line) for line in lines]
    for event in events:
        assert set(event) == {"at", "action", "pluginId", "actor", "outcome"}
    assert [event["action"] for event in events][-1] == "publish.reject"
    assert "SECRET-REJECTION-REASON" not in body.decode("utf-8")
    assert not any("detail" in line for line in lines)


def test_trust_center_starts_honest_and_follows_an_import(booted, admin):
    status, trust = get_json(booted, "/api/marketplace/trust")
    assert status == 200
    assert trust["lastValidatorRun"]["at"] is None
    assert trust["lastValidatorRun"]["ok"] is None
    assert trust["policy"]["signatureStatus"] == "unsigned"

    signer = make_key("policy-signer")
    bundle = policy_bundle(signer, revocation_epoch=1)
    status, _body = post_json(
        booted, "/api/marketplace/policy/import",
        {"bundle": bundle, "confirm": True})
    assert status == 200

    status, trust = get_json(booted, "/api/marketplace/trust")
    assert trust["anchor"] == {
        "epoch": 1, "fingerprints": [fingerprint(signer.public)]}
    assert trust["policy"]["signatureStatus"] == "signed"
    assert trust["lastValidatorRun"]["ok"] is True


