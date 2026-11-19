"""The plugin runtime lifecycle (ticket #9), tested through its public API.

Install validates before anything executes, lands the plugin in a
versioned directory recorded in a lockfile, and starts it in pilot
mode. Enable, disable, uninstall (data preserved), a separately named
data purge, updates with scope diffing, rollback, and the amber
data-source state with Re-test.
"""
import json
from pathlib import Path

import pytest

from .plugins_fixtures import shell_zip, valid_zip, widened_zip

NOW = "2026-11-11T16:00:00"


@pytest.fixture()
def runtime(tmp_path):
    from agentdesk.plugins.runtime import PluginRuntime
    return PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now=NOW,
    )


def zip_file(path, **overrides):
    return valid_zip(path, overrides=overrides)


def test_install_makes_widget_with_pilot_badge_and_lockfile_record(runtime, tmp_path):
    out = runtime.install(zip_file(tmp_path / "plugin.zip"), source="zip")
    assert out["ok"] is True
    assert out["id"] == "sales-delta-widget"
    assert out["version"] == "1.2.0"
    assert out["pilot"] is True

    record = runtime.record("sales-delta-widget")
    assert record["state"] == "enabled"
    assert record["pilot_views_left"] > 0
    assert record["name"] == "Sales 24h Delta"

    lockfile = json.loads(
        (runtime.plugins_dir / "lockfile.json").read_text(encoding="utf-8"))
    entry = lockfile["plugins"]["sales-delta-widget"]
    assert entry["id"] == "sales-delta-widget"
    assert entry["active_version"] == "1.2.0"
    assert entry["source"] == "zip"
    assert entry["sha256"]
    assert entry["installed_at"] == NOW
    assert entry["versions"][0]["version"] == "1.2.0"


def test_install_refuses_invalid_manifest_before_anything_executes(runtime, tmp_path):
    bad = shell_zip(tmp_path / "shell.zip")
    plugins_before = sorted(p.name for p in runtime.plugins_dir.iterdir()) \
        if runtime.plugins_dir.exists() else []
    from agentdesk.plugins.runtime import PluginError
    with pytest.raises(PluginError) as excinfo:
        runtime.install(bad, source="zip")
    assert excinfo.value.code == "install:validator-failed"
    plugins_after = sorted(p.name for p in runtime.plugins_dir.iterdir()) \
        if runtime.plugins_dir.exists() else []
    assert plugins_after == plugins_before
    assert runtime.plugins_dir / "lockfile.json" \
        and not (runtime.plugins_dir / "lockfile.json").exists()


def test_disable_hides_without_data_loss_and_reenable_restores(runtime, tmp_path):
    runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
    data_dir = runtime.record("sales-delta-widget")["data_dir"]

    runtime.disable("sales-delta-widget")
    assert runtime.record("sales-delta-widget")["state"] == "disabled"
    assert Path(data_dir).is_dir()

    runtime.enable("sales-delta-widget")
    assert runtime.record("sales-delta-widget")["state"] == "enabled"
    assert Path(runtime.record("sales-delta-widget")["data_dir"]).is_dir()


def test_uninstall_keeps_data_and_purge_needs_named_confirmation(runtime, tmp_path):
    runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
    data_dir = Path(runtime.record("sales-delta-widget")["data_dir"])
    version_dir = Path(runtime.record("sales-delta-widget")["versions"][0]["dir"])

    runtime.uninstall("sales-delta-widget")
    assert not version_dir.exists()
    assert data_dir.is_dir()
    assert runtime.record("sales-delta-widget")["state"] == "uninstalled"

    from agentdesk.plugins.runtime import PluginError
    with pytest.raises(PluginError) as excinfo:
        runtime.purge_data("sales-delta-widget", confirmation=None)
    assert excinfo.value.code == "purge:confirmation-required"
    with pytest.raises(PluginError) as excinfo:
        runtime.purge_data("sales-delta-widget", confirmation="please")
    assert excinfo.value.code == "purge:confirmation-required"

    runtime.purge_data("sales-delta-widget", confirmation="delete-data:sales-delta-widget")
    assert not data_dir.exists()


def test_same_scope_update_applies_silently(runtime, tmp_path):
    runtime.install(zip_file(tmp_path / "v1.zip"), source="zip")
    same = zip_file(tmp_path / "v2.zip", version="1.2.1")
    out = runtime.update("sales-delta-widget", same)
    assert out["applied"] is True
    assert runtime.record("sales-delta-widget")["active_version"] == "1.2.1"
    assert runtime.record("sales-delta-widget")["pending_update"] is None


def test_widened_update_holds_for_reconsent_with_exact_diff(runtime, tmp_path):
    runtime.install(zip_file(tmp_path / "v1.zip"), source="zip")
    widened = widened_zip(tmp_path / "wide.zip")
    out = runtime.update("sales-delta-widget", widened)
    assert out["applied"] is False
    assert out["status"] == "pending-consent"
    record = runtime.record("sales-delta-widget")
    assert record["active_version"] == "1.2.0"  # held, not applied
    assert record["pending_update"]["added_scopes"] == [
        "filesystem.read: ${workspace}/reports/*.pdf"]

    runtime.consent("sales-delta-widget")
    record = runtime.record("sales-delta-widget")
    assert record["active_version"] == "1.2.1"
    assert record["pending_update"] is None


def test_rollback_restores_prior_version(runtime, tmp_path):
    runtime.install(zip_file(tmp_path / "v1.zip"), source="zip")
    runtime.update("sales-delta-widget",
                   zip_file(tmp_path / "v2.zip", version="1.2.1"))
    out = runtime.rollback("sales-delta-widget")
    assert out["rolled_back_to"] == "1.2.0"
    record = runtime.record("sales-delta-widget")
    assert record["active_version"] == "1.2.0"
    # History stays append-only: both versions remain recorded, the
    # rollback repoints the lockfile's active version at the prior one.
    assert [v["version"] for v in record["versions"]] == ["1.2.0", "1.2.1"]


def test_amber_data_source_with_cause_and_retest(runtime, tmp_path):
    runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
    status = runtime.source_status("sales-delta-widget")
    assert status["status"] == "attention"
    assert "reports" in status["cause"] or "no file" in status["cause"]

    # A file that is not a workbook stays amber: Re-test attaches the
    # real pipeline now (#69), and the parser's honest refusal beats a
    # fresh-from-presence that binds nothing.
    (runtime.workspace_dir / "reports").mkdir(parents=True)
    (runtime.workspace_dir / "reports" / "q4.xlsx").write_bytes(b"x")
    status = runtime.retest("sales-delta-widget")
    assert status["status"] == "attention"

    # A genuine workbook recovers to fresh through the same Re-test.
    from excel_fixtures import make_xlsx

    (runtime.workspace_dir / "reports" / "q4.xlsx").write_bytes(
        make_xlsx([["Region", "Sales"], ["North", 10]]))
    status = runtime.retest("sales-delta-widget")
    assert status["status"] == "fresh"

def test_a_restarted_runtime_rebinds_enabled_plugins_on_the_dashboard(tmp_path):
    from agentdesk.plugins.runtime import PluginRuntime
    from excel_fixtures import make_xlsx

    dirs = dict(plugins_dir=tmp_path / "plugins", data_dir=tmp_path / "data",
                workspace_dir=tmp_path / "workspace", now=NOW)
    first = PluginRuntime(**dirs)
    first.install(zip_file(tmp_path / "a.zip"), source="zip")
    (tmp_path / "workspace" / "reports").mkdir(parents=True)
    (tmp_path / "workspace" / "reports" / "q4.xlsx").write_bytes(
        make_xlsx([["Region", "Sales"], ["North", 10]]))

    restarted = PluginRuntime(**dirs)
    assert restarted.widget_payload("sales-delta-widget") is None
    cards = restarted.widget_cards()
    assert len(cards) == 1
    assert cards[0]["freshness"] == "fresh", cards[0]
    assert cards[0]["payload"]["elements"], cards[0]
    assert restarted.widget_payload("sales-delta-widget") is not None


def test_widget_payload_detects_in_place_tampering(tmp_path):
    from agentdesk.plugins.runtime import PluginError, PluginRuntime

    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now=NOW,
    )
    runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
    version_dir = Path(runtime.record("sales-delta-widget")["versions"][0]["dir"])
    target = version_dir / "manifest.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(PluginError) as excinfo:
        runtime.widget_payload("sales-delta-widget")
    assert excinfo.value.code == "plugin:tampered"
    assert excinfo.value.status == 409

    with pytest.raises(PluginError) as excinfo:
        runtime.source_status("sales-delta-widget")
    assert excinfo.value.code == "plugin:tampered"

    with pytest.raises(PluginError) as excinfo:
        runtime.retest("sales-delta-widget")
    assert excinfo.value.code == "plugin:tampered"

    fresh = PluginRuntime(
        plugins_dir=tmp_path / "fresh-plugins",
        data_dir=tmp_path / "fresh-data",
        workspace_dir=tmp_path / "workspace",
        now=NOW,
    )
    fresh.install(zip_file(tmp_path / "fresh.zip"), source="zip")
    assert fresh.widget_payload("sales-delta-widget") is None



def test_a_widget_card_names_its_plugin_for_the_reading_seam(runtime, tmp_path):
    """The coupled-intelligence seam keys off pluginId (#165).

    A single-instance card used to leave pluginId empty, so the digest,
    calendar and research families never attached their reading or press
    to the cards the dashboard actually serves. Every card shape (setup,
    config-backed instance, live single-instance) must name its plugin.
    """
    runtime.install(zip_file(tmp_path / "plugin.zip"), source="zip")
    cards = runtime.widget_cards()
    assert len(cards) == 1
    assert cards[0]["pluginId"] == "sales-delta-widget", cards[0]
    assert cards[0]["instanceId"] == "main", cards[0]
