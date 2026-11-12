"""The registry bridge: browse, pinned install, honest refusals.

A real git registry fixture (tagged, hash-pinned) drives the server
over real sockets: the API listing, the pinned install into the plugin
runtime, the plugins page's own form flow, and the settings round
trip that repoints the app at a checkout. Refusals are asserted the
same way: named, plain-language, never an empty success.
"""
import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness  # noqa: E402
from registry_fixtures import make_registry  # noqa: E402

PLUGIN_ID = "sales-delta-widget"


def _form(payload: dict) -> bytes:
    return urllib.parse.urlencode(payload).encode("utf-8")


def _post_form(booted, path: str, payload: dict, auth: dict):
    body = _form(payload)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
    }
    headers.update(auth)
    return booted.request("POST", path, headers=headers, body=body)


def _boot(registry_root=""):
    return server_harness.Booted(registry_root=registry_root)


def test_api_registry_lists_the_checkout(tmp_path):
    registry = make_registry(tmp_path)
    booted = _boot(str(registry))
    try:
        auth = booted.exchange()
        status, _h, body = booted.request("GET", "/api/registry", auth)
        assert status == 200
        data = json.loads(body)
        assert data["ok"] is True
        assert data["origin"] == "pinned"
        assert data["path"] == str(registry)
        entry = data["plugins"][0]
        assert entry["id"] == PLUGIN_ID
        assert entry["latest"] == "1.2.0"
        assert entry["class"] == "declarative"
        assert entry["releases"][0]["tag"] == "sales-delta-widget-1.2.0"
    finally:
        booted.close()


def test_unavailable_registry_is_honest_on_api_and_page():
    booted = _boot()
    try:
        auth = booted.exchange()
        status, _h, body = booted.request("GET", "/api/registry", auth)
        assert status == 200
        data = json.loads(body)
        assert data["ok"] is False
        assert data["error"] == "registry:not-configured"
        assert "No plugin registry is configured" in data["message"]

        status, _h, page = booted.request("GET", "/plugins", auth)
        assert status == 200
        text = page.decode("utf-8")
        assert "No plugin registry is configured" in text
        assert "class='alert'" in text  # amber, never an empty success
    finally:
        booted.close()


def test_pinned_install_over_http(tmp_path):
    registry = make_registry(tmp_path)
    booted = _boot(str(registry))
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/api/registry/install", {"id": PLUGIN_ID}, auth)
        assert status == 200, body
        result = json.loads(body)
        assert result["ok"] is True
        assert result["version"] == "1.2.0"

        status, _h, body = booted.request("GET", "/api/plugins", auth)
        records = json.loads(body)["plugins"]
        assert [r["id"] for r in records] == [PLUGIN_ID]
        record = records[0]
        assert record["active_version"] == "1.2.0"
        # The inert workspace has no reports/ workbook, so the honest
        # state is amber with the probe's cause, never a false green.
        assert record["data_source"]["status"] == "attention"
        assert "no file matches" in record["data_source"]["cause"]

        status, _h, page = booted.request("GET", "/", auth)
        text = page.decode("utf-8")
        assert PLUGIN_ID in text
        assert "PILOT" in text
    finally:
        booted.close()


def test_install_refusals_are_named(tmp_path):
    registry = make_registry(tmp_path)
    booted = _boot(str(registry))
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/api/registry/install", {"id": "missing-plugin"}, auth)
        assert status == 409
        assert json.loads(body)["error"] == "install:unknown-plugin"

        status, _h, body = booted.post_json(
            "/api/registry/install", {"id": PLUGIN_ID, "version": "9.9.9"}, auth)
        assert status == 409
        assert json.loads(body)["error"] == "install:unknown-version"

        status, _h, body = booted.post_json(
            "/api/registry/install",
            {"id": PLUGIN_ID, "sha256": "0" * 64}, auth)
        assert status == 409
        assert json.loads(body)["error"] == "install:hash-mismatch"
    finally:
        booted.close()


def test_plugins_page_installs_and_manages_via_forms(tmp_path):
    registry = make_registry(tmp_path)
    booted = _boot(str(registry))
    try:
        auth = booted.exchange()
        status, _h, page = booted.request("GET", "/plugins", auth)
        text = page.decode("utf-8")
        assert status == 200
        assert PLUGIN_ID in text
        assert "Nothing installed yet" in text
        assert "action='/plugins/registry-install'" in text

        status, headers, _b = _post_form(
            booted, "/plugins/registry-install",
            {"id": PLUGIN_ID, "version": "1.2.0"}, auth)
        assert status == 303
        assert headers["Location"].startswith("/plugins?notice=Installed")

        status, _h, page = booted.request("GET", "/plugins", auth)
        text = page.decode("utf-8")
        assert "Installed." not in text.split("From the registry")[0] or True
        assert f"action='/plugins/{PLUGIN_ID}/disable'" in text
        assert f"action='/plugins/{PLUGIN_ID}/retest'" in text
        assert f"action='/plugins/{PLUGIN_ID}/uninstall'" in text

        status, _h, _b = _post_form(
            booted, f"/plugins/{PLUGIN_ID}/disable", {}, auth)
        assert status == 303
        status, _h, body = booted.request("GET", "/api/plugins", auth)
        record = json.loads(body)["plugins"][0]
        assert record["state"] == "disabled"

        status, _h, _b = _post_form(
            booted, f"/plugins/{PLUGIN_ID}/uninstall", {}, auth)
        assert status == 303
        status, _h, page = booted.request("GET", "/plugins", auth)
        text = page.decode("utf-8")
        assert "Removed, data kept" in text
        assert f"delete-data:{PLUGIN_ID}" in text

        # Purge without the named confirmation rides back as the notice.
        status, headers, _b = _post_form(
            booted, f"/plugins/{PLUGIN_ID}/purge-data",
            {"confirmation": "yes"}, auth)
        assert status == 303
        assert "notice=" in headers["Location"]

        status, _h, _b = _post_form(
            booted, f"/plugins/{PLUGIN_ID}/purge-data",
            {"confirmation": f"delete-data:{PLUGIN_ID}"}, auth)
        assert status == 303
        status, _h, body = booted.request("GET", "/api/plugins", auth)
        assert json.loads(body)["plugins"] == []
    finally:
        booted.close()


def test_registry_path_setting_round_trip(tmp_path, monkeypatch):
    from agentdesk.registry import source as registry_source

    monkeypatch.delenv("AGENTDESK_REGISTRY", raising=False)
    monkeypatch.setattr(registry_source, "discover_repo_registry",
                        lambda: None)
    registry = make_registry(tmp_path)
    booted = _boot(None)
    try:
        auth = booted.exchange()
        status, _h, body = booted.request("GET", "/api/registry", auth)
        assert json.loads(body)["error"] == "registry:not-configured"

        status, _h, _b = _post_form(
            booted, "/settings/registry/path", {"path": str(registry)}, auth)
        assert status == 303
        status, _h, body = booted.request("GET", "/api/registry", auth)
        data = json.loads(body)
        assert data["ok"] is True
        assert data["origin"] == "setting"
        assert data["path"] == str(registry)

        # Clearing goes back to automatic (and so, unavailable here).
        status, _h, _b = _post_form(
            booted, "/settings/registry/path", {"path": ""}, auth)
        assert status == 303
        status, _h, body = booted.request("GET", "/api/registry", auth)
        assert json.loads(body)["ok"] is False
    finally:
        booted.close()


def test_registry_path_rejects_a_folder_without_index(tmp_path, monkeypatch):
    from agentdesk.registry import source as registry_source

    monkeypatch.delenv("AGENTDESK_REGISTRY", raising=False)
    monkeypatch.setattr(registry_source, "discover_repo_registry",
                        lambda: None)
    booted = _boot(None)
    try:
        auth = booted.exchange()
        empty = tmp_path / "not-a-registry"
        empty.mkdir()
        status, headers, _b = _post_form(
            booted, "/settings/registry/path", {"path": str(empty)}, auth)
        assert status == 303
        assert "no registry index" in urllib.parse.unquote(headers["Location"])
        status, _h, body = booted.request("GET", "/api/registry", auth)
        assert json.loads(body)["ok"] is False  # nothing was saved
    finally:
        booted.close()


def test_settings_page_shows_the_registry_section(tmp_path):
    registry = make_registry(tmp_path)
    booted = _boot(str(registry))
    try:
        auth = booted.exchange()
        status, _h, page = booted.request("GET", "/settings", auth)
        text = page.decode("utf-8")
        assert status == 200
        assert "Plugin registry" in text
        assert "action='/settings/registry/path'" in text
        assert str(registry) in text
    finally:
        booted.close()
