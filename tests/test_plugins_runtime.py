"""The plugin runtime lifecycle (ticket #9), tested through its public API.

Install validates before anything executes, lands the plugin in a
versioned directory recorded in a lockfile, and starts it in pilot
mode. Enable, disable, uninstall (data preserved), a separately named
data purge, updates with scope diffing, rollback, and the amber
data-source state with Re-test. An install over an installed plugin
rides the update path's consent machinery, so the Install button
cannot grant what the Update button would ask for.
"""
import json
import re
import zipfile
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


def test_install_over_installed_holds_widening_and_keeps_history_and_pilot(
        runtime, tmp_path):
    """The Install button over an installed plugin is an update (audit F1).

    A widening release holds for consent exactly like the Update path,
    the version history is appended instead of replaced (rollback still
    answers), and the pilot counter does not restart.
    """
    from agentdesk.plugins.runtime import PILOT_VIEWS
    runtime.install(zip_file(tmp_path / "v1.zip"), source="zip")
    runtime.record_dashboard_view()
    runtime.record_dashboard_view()
    spent_down = PILOT_VIEWS - 2

    out = runtime.install(widened_zip(tmp_path / "wide.zip"), source="zip")

    assert out["applied"] is False
    assert out["status"] == "pending-consent"
    record = runtime.record("sales-delta-widget")
    assert record["active_version"] == "1.2.0"  # held, not applied
    assert record["pending_update"]["added_scopes"] == [
        "filesystem.read: ${workspace}/reports/*.pdf"]
    assert [v["version"] for v in record["versions"]] == ["1.2.0"]
    assert record["pilot_views_left"] == spent_down

    runtime.consent("sales-delta-widget")
    record = runtime.record("sales-delta-widget")
    assert [v["version"] for v in record["versions"]] == ["1.2.0", "1.2.1"]
    assert record["active_version"] == "1.2.1"
    assert record["pilot_views_left"] == spent_down

    assert runtime.rollback("sales-delta-widget")["rolled_back_to"] == "1.2.0"


def test_install_over_installed_applies_a_same_scope_release(runtime, tmp_path):
    runtime.install(zip_file(tmp_path / "v1.zip"), source="zip")
    runtime.record_dashboard_view()

    out = runtime.install(zip_file(tmp_path / "v2.zip", version="1.2.1"),
                          source="zip")

    assert out["applied"] is True
    record = runtime.record("sales-delta-widget")
    assert record["active_version"] == "1.2.1"
    assert [v["version"] for v in record["versions"]] == ["1.2.0", "1.2.1"]
    assert record["pending_update"] is None


def test_lockfile_write_survives_a_crash_mid_write(runtime, tmp_path, monkeypatch):
    """The lockfile is written atomically (audit F6): a crash between
    truncation and the full write must leave the previous lockfile in
    place, not a partial file every plugins route chokes on."""
    runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
    real_write_text = Path.write_text

    def crashing_write_text(self, data, *args, **kwargs):
        real_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("power loss mid-write")

    monkeypatch.setattr(Path, "write_text", crashing_write_text)
    with pytest.raises(OSError):
        runtime.disable("sales-delta-widget")
    monkeypatch.undo()

    document = json.loads(
        (runtime.plugins_dir / "lockfile.json").read_text(encoding="utf-8"))
    assert document["plugins"]["sales-delta-widget"]["state"] == "enabled"
    assert runtime.list_records()[0]["state"] == "enabled"


def test_extract_refuses_a_zip_member_over_the_size_cap(tmp_path):
    """A small bundle with one declared-huge member is refused before any
    decompression (audit F8): the cap reads the member's declared size,
    so a multi-gigabyte member cannot spike memory."""
    from agentdesk.plugins.runtime import MAX_ZIP_MEMBER_BYTES, PluginError, extract_plugin_zip

    source = tmp_path / "bomb.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("huge.bin", b"\0" * (MAX_ZIP_MEMBER_BYTES + 1))

    destination = tmp_path / "staged"
    with pytest.raises(PluginError) as excinfo:
        extract_plugin_zip(source, destination)
    assert excinfo.value.code == "install:unsafe-zip"
    assert "huge.bin" in str(excinfo.value)
    assert not (destination / "huge.bin").exists()


def test_pilot_badge_covers_exactly_the_first_five_runs(runtime, tmp_path):
    """PRD R3.7 (the binding interaction document) pins the badge at five
    runs; the runtime constant must match it, not drift again."""
    from agentdesk.plugins.runtime import PILOT_VIEWS
    prd = (Path(__file__).resolve().parents[1] / "docs" / "PRD.md").read_text(
        encoding="utf-8")
    match = re.search(r'"pilot" badge for the first (\d+) runs', prd)
    assert match, "docs/PRD.md R3.7 must state the pilot badge run count"
    assert PILOT_VIEWS == int(match.group(1)) == 5

    runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
    for _ in range(PILOT_VIEWS):
        assert runtime.record("sales-delta-widget")["pilot_views_left"] > 0
        runtime.record_dashboard_view()
    assert runtime.record("sales-delta-widget")["pilot_views_left"] == 0
    runtime.record_dashboard_view()  # run 6: no badge, no further spend
    assert runtime.record("sales-delta-widget")["pilot_views_left"] == 0


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


# -- the golden emission matrix -----------------------------------------

def _golden_runtime(case, tmp_path):
    """Build the installed-plugin state one golden-matrix row exercises."""
    from agentdesk.plugins.config import InstanceStore
    from agentdesk.plugins.runtime import PILOT_VIEWS, PluginRuntime
    from excel_fixtures import make_xlsx
    from plugin_fixtures import write_alias_plugin

    workspace = tmp_path / "workspace"
    reports = workspace / "reports"
    reports.mkdir(parents=True)
    (reports / "q4.xlsx").write_bytes(
        make_xlsx([["Region", "Sales"], ["North", 10]]))
    dirs = dict(plugins_dir=tmp_path / "plugins", data_dir=tmp_path / "data",
                workspace_dir=workspace, now=NOW)
    runtime = PluginRuntime(**dirs)
    registry = Path(__file__).resolve().parents[1] / "registry" / "plugins"
    if case == "plain":
        runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
    elif case == "alias":
        runtime.install(registry / "excel-report", source="dir")
        runtime.install(write_alias_plugin(
            tmp_path, "sales-alias", "Sales Alias", "Sales"), source="dir")
    elif case == "instances":
        runtime.install(registry / "excel-report", source="dir")
        store = InstanceStore(runtime.data_dir, workspace)
        store.create("excel-report", "main", "Main")
        store.create("excel-report", "pipeline", "Pipeline")
    elif case == "unconfirmed-main":
        runtime.install(registry / "excel-report", source="dir")
        InstanceStore(runtime.data_dir, workspace).create(
            "excel-report", "main", "Main")
    elif case == "tampered":
        runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
        version_dir = Path(
            runtime.record("sales-delta-widget")["versions"][0]["dir"])
        manifest_file = version_dir / "manifest.json"
        manifest_file.write_text(
            manifest_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        # A rebuilt runtime re-verifies the pin; the installing runtime
        # already attached its runner and would never look again.
        runtime = PluginRuntime(**dirs)
    elif case == "pilot-out":
        runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
        for _expected in range(PILOT_VIEWS):
            assert runtime.record_dashboard_view() == 1
    elif case == "disabled":
        runtime.install(zip_file(tmp_path / "a.zip"), source="zip")
        runtime.disable("sales-delta-widget")
    return runtime


GOLDEN_MATRIX = {
    # case: (layout_keys, card projections (id, pluginId, instanceId,
    # freshness, pilot, title), views spent by record_dashboard_view)
    "plain": (
        ["sales-delta-widget"],
        [("sales-delta-widget", "sales-delta-widget", "main", "fresh",
          True, "Sales 24h Delta")],
        1,
    ),
    "alias": (
        # The alias contributes none; its unconfirmed instance keys under
        # the target as plugin~instance.
        ["excel-report~sales"],
        [("excel-report~sales", "excel-report", "sales", "setup",
          True, "Sales")],
        1,
    ),
    "instances": (
        # Per-instance emission: the unconfirmed main keys as the bare
        # plugin id, the other instance as plugin~instance.
        ["excel-report", "excel-report~pipeline"],
        [("excel-report", "excel-report", "main", "setup", True, "Main"),
         ("excel-report~pipeline", "excel-report", "pipeline", "setup",
          True, "Pipeline")],
        1,
    ),
    "unconfirmed-main": (
        # The unconfirmed main instance is the plugin's own setup card.
        ["excel-report"],
        [("excel-report", "excel-report", "main", "setup", True, "Main")],
        1,
    ),
    "tampered": (
        # The key stays (the setup card has a home), the card is an
        # attention card carrying no payload, and no view is spent.
        ["sales-delta-widget"],
        [("sales-delta-widget", "sales-delta-widget", "main", "attention",
          True, "Sales 24h Delta")],
        0,
    ),
    "pilot-out": (
        ["sales-delta-widget"],
        [("sales-delta-widget", "sales-delta-widget", "main", "fresh",
          False, "Sales 24h Delta")],
        0,
    ),
    "disabled": ([], [], 0),
}


@pytest.mark.parametrize("case", sorted(GOLDEN_MATRIX))
def test_the_golden_emission_matrix_pins_all_three_emitters(case, tmp_path):
    """layout_keys, widget_cards and record_dashboard_view decide from one
    rule; the matrix pins what each answers for every shape of install.

    Before the emitters share a seam, this is the rule's photograph: any
    refactor that moves a decision must reproduce these answers exactly.
    """
    runtime = _golden_runtime(case, tmp_path)
    keys, projections, spent = GOLDEN_MATRIX[case]

    assert runtime.layout_keys() == keys
    cards = [
        (card["id"], card["pluginId"], card["instanceId"],
         card["freshness"], card["pilot"], card["title"])
        for card in runtime.widget_cards()
    ]
    assert cards == projections
    assert runtime.record_dashboard_view() == spent


def test_layout_keys_read_the_newest_manifest_and_cards_the_active_one(runtime, tmp_path):
    # Every golden-matrix case has active == newest, so the two emitters'
    # manifest sources could be swapped without a failure. A rollback
    # drives them apart: the newest recorded manifest (1.1.0) lost the
    # instance capability, the active one (0.1.0) keeps it.
    import shutil

    from agentdesk.plugins.config import InstanceStore
    from plugins_fixtures import ZIP_DATE

    registry = Path(__file__).resolve().parents[1] / "registry" / "plugins"
    runtime.install(registry / "excel-report", source="dir")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = InstanceStore(runtime.data_dir, workspace)
    store.create("excel-report", "main", "Main")
    store.create("excel-report", "pipeline", "Pipeline")

    v2_dir = tmp_path / "excel-v2"
    shutil.copytree(registry / "excel-report", v2_dir)
    manifest = json.loads((v2_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = "1.1.0"
    manifest.pop("config")
    (v2_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    v2 = tmp_path / "excel-v2.zip"
    with zipfile.ZipFile(v2, "w") as archive:
        for path in sorted(v2_dir.rglob("*")):
            if not path.is_file() or path.name == "manifest.json":
                continue
            info = zipfile.ZipInfo(
                path.relative_to(v2_dir).as_posix(), date_time=ZIP_DATE)
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("manifest.json", date_time=ZIP_DATE)
        archive.writestr(info, json.dumps(manifest, indent=2) + "\n")

    out = runtime.update("excel-report", v2)
    assert out["applied"] is True
    runtime.rollback("excel-report")
    record = runtime.record("excel-report")
    assert record["active_version"] == "0.1.0"
    assert record["versions"][-1]["version"] == "1.1.0"

    assert runtime.layout_keys() == ["excel-report"]
    cards = [(card["id"], card["instanceId"]) for card in runtime.widget_cards()]
    assert cards == [("excel-report", "main"),
                     ("excel-report~pipeline", "pipeline")]
    assert runtime.record_dashboard_view() == 1
