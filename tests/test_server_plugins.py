"""The plugin lifecycle over the HTTP API (ticket #9), on the primary seam.

These tests drive the real walking-skeleton server over real sockets,
with a PluginRuntime pointed at temp directories. Every lifecycle action
the ticket names is an authenticated POST; observation is a GET.
"""
import http.client
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.plugins.runtime import PluginRuntime
from agentdesk.server import app as server_app
from plugins_fixtures import shell_zip, valid_zip, widened_zip  # noqa: E402


class Running:
    """The booted server with the runtime and small request helpers."""

    def __init__(self, server, runtime):
        self.server = server
        self.runtime = runtime
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.port

    def authed_headers(self):
        status, headers, _body = self.request(
            "GET", f"/auth/{self.server.sessions.bootstrap_token()}",
            headers={"Host": f"127.0.0.1:{self.port}"})
        assert status == 303, f"auth exchange failed: {status}"
        cookie = headers["Set-Cookie"].split(";")[0]
        return {"Cookie": cookie, "Host": f"127.0.0.1:{self.port}"}

    def request(self, method, path, headers=None, body=None):
        """One real HTTP request: (status, headers-dict, parsed-or-text body)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            payload = None
            if body is not None:
                payload = json.dumps(body)
            merged = {"Host": f"127.0.0.1:{self.port}"}
            merged.update(headers or {})
            if payload is not None:
                merged["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=merged)
            response = conn.getresponse()
            raw = response.read()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw.decode("utf-8", errors="replace")
            return response.status, dict(response.getheaders()), parsed
        finally:
            conn.close()

    def post(self, path, body=None):
        status, _headers, parsed = self.request(
            "POST", path, headers=self.authed_headers(), body=body)
        return status, parsed

    def get(self, path):
        status, _headers, parsed = self.request(
            "GET", path, headers=self.authed_headers())
        return status, parsed

    def page(self, path="/"):
        status, _headers, text = self.request("GET", path,
                                              headers=self.authed_headers())
        assert status == 200
        return text

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture()
def running(tmp_path):
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now="2026-11-11T16:00:00",
    )
    server = server_app.create_server(port=0, plugins=runtime)
    running = Running(server, runtime)
    try:
        yield running
    finally:
        running.close()


def test_install_makes_widget_with_pilot_badge_and_lockfile(running, tmp_path):
    zip_path = valid_zip(tmp_path / "plugin.zip")
    status, out = running.post("/api/plugins/install",
                               {"zip_path": str(zip_path), "source": "zip"})
    assert status == 200, out
    assert out["ok"] is True

    status, listing = running.get("/api/plugins")
    entry = listing["plugins"][0]
    assert entry["id"] == "sales-delta-widget"
    assert entry["pilot"] is True
    assert entry["state"] == "enabled"

    status, page = running.get("/")
    assert "Sales 24h Delta" in page
    assert "badge-pilot" in page

    lockfile = json.loads(
        (running.runtime.plugins_dir / "lockfile.json").read_text(encoding="utf-8"))
    record = lockfile["plugins"]["sales-delta-widget"]
    assert record["id"] == "sales-delta-widget"
    assert record["active_version"] == "1.2.0"
    assert record["source"] == "zip"
    assert record["sha256"]
    assert record["installed_at"] == "2026-11-11T16:00:00"


def test_install_refuses_invalid_manifest_before_anything_executes(running, tmp_path):
    zip_path = shell_zip(tmp_path / "shell.zip")
    status, out = running.post("/api/plugins/install",
                               {"zip_path": str(zip_path), "source": "zip"})
    assert status == 400
    assert out["error"] == "install:validator-failed"
    assert running.runtime.plugins_dir.exists() is False or \
        not (running.runtime.plugins_dir / "lockfile.json").exists()


def test_disable_hides_widget_without_data_loss_and_reenable_restores(running, tmp_path):
    zip_path = valid_zip(tmp_path / "plugin.zip")
    running.post("/api/plugins/install", {"zip_path": str(zip_path), "source": "zip"})
    data_dir = Path(running.runtime.record("sales-delta-widget")["data_dir"])

    status, _ = running.post("/api/plugins/sales-delta-widget/disable")
    assert status == 200
    _, page = running.get("/")
    assert "Sales 24h Delta" not in page
    assert data_dir.is_dir()

    status, _ = running.post("/api/plugins/sales-delta-widget/enable")
    assert status == 200
    _, page = running.get("/")
    assert "Sales 24h Delta" in page


def test_uninstall_keeps_data_and_purge_needs_named_confirmation(running, tmp_path):
    zip_path = valid_zip(tmp_path / "plugin.zip")
    running.post("/api/plugins/install", {"zip_path": str(zip_path), "source": "zip"})
    record = running.runtime.record("sales-delta-widget")
    data_dir = Path(record["data_dir"])
    version_dir = Path(record["versions"][0]["dir"])

    status, _ = running.post("/api/plugins/sales-delta-widget/uninstall")
    assert status == 200
    assert not version_dir.exists()
    assert data_dir.is_dir()

    status, out = running.post("/api/plugins/sales-delta-widget/purge-data", {})
    assert status == 409
    assert out["error"] == "purge:confirmation-required"
    assert data_dir.is_dir()

    status, out = running.post("/api/plugins/sales-delta-widget/purge-data",
                               {"confirmation": "delete-data:sales-delta-widget"})
    assert status == 200
    assert not data_dir.exists()


def test_same_scope_update_applies_silently(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip")), "source": "zip"})
    status, out = running.post("/api/plugins/sales-delta-widget/update", {
        "zip_path": str(valid_zip(tmp_path / "v2.zip", overrides={"version": "1.2.1"}))})
    assert status == 200
    assert out["applied"] is True
    _, record = running.get("/api/plugins/sales-delta-widget")
    assert record["active_version"] == "1.2.1"
    assert record["pending_update"] is None


def test_widened_update_holds_with_exact_capability_diff(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip")), "source": "zip"})
    status, out = running.post("/api/plugins/sales-delta-widget/update", {
        "zip_path": str(widened_zip(tmp_path / "wide.zip"))})
    assert status == 200
    assert out["applied"] is False
    assert out["added_scopes"] == ["filesystem.read: ${workspace}/reports/*.pdf"]
    _, record = running.get("/api/plugins/sales-delta-widget")
    assert record["active_version"] == "1.2.0"

    status, out = running.post("/api/plugins/sales-delta-widget/consent", {})
    assert status == 200
    _, record = running.get("/api/plugins/sales-delta-widget")
    assert record["active_version"] == "1.2.1"


def test_rollback_restores_prior_version_and_lockfile(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip")), "source": "zip"})
    running.post("/api/plugins/sales-delta-widget/update", {
        "zip_path": str(valid_zip(tmp_path / "v2.zip",
                                  overrides={"version": "1.2.1"}))})
    status, out = running.post("/api/plugins/sales-delta-widget/rollback", {})
    assert status == 200
    assert out["rolled_back_to"] == "1.2.0"
    _, record = running.get("/api/plugins/sales-delta-widget")
    assert record["active_version"] == "1.2.0"
    assert [v["version"] for v in record["versions"]] == ["1.2.0", "1.2.1"]


def test_amber_widget_shows_cause_and_retest_recovers(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "plugin.zip")), "source": "zip"})
    _, page = running.get("/")
    assert 'data-freshness-status="attention"' in page
    assert "no file matches" in page

    reports = running.runtime.workspace_dir / "reports"
    reports.mkdir(parents=True)
    (reports / "q4.xlsx").write_bytes(b"x")
    status, out = running.post("/api/plugins/sales-delta-widget/retest", {})
    assert status == 200
    assert out["status"] == "fresh"
    _, page = running.get("/")
    assert 'data-freshness-status="fresh"' in page


def test_plugin_endpoints_require_a_session(tmp_path):
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "data",
                            workspace_dir=tmp_path / "workspace")
    server = server_app.create_server(port=0, plugins=runtime)
    running = Running(server, runtime)
    try:
        zip_path = valid_zip(tmp_path / "plugin.zip")
        status, _headers, _body = running.request(
            "POST", "/api/plugins/install",
            headers={"Host": f"127.0.0.1:{running.port}"},
            body={"zip_path": str(zip_path), "source": "zip"})
        assert status == 401
    finally:
        running.close()
