"""Task-scoped consents (ticket #41): the donor's taskAllows, keyed
(plugin, scope), on the real plugin runtime and HTTP seam.

A widening update creates an update_consent card; accepting it "for this
plugin" records the allow, so an identical widening never re-prompts,
while a different (widened further) scope always does. Also checks the
plugin lifecycle audit rows, written through the same dispatch.
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from nexuusbot.consents import ConsentStore
from nexuusbot.plugins.runtime import PluginRuntime
from plugins_fixtures import VALID_PLUGIN_DIR, valid_zip, widened_zip

PLUGIN = "sales-delta-widget"


# -- the pure store -----------------------------------------------------

def test_consent_store_keys_on_plugin_and_scope():
    store = ConsentStore()
    assert store.allowed(PLUGIN, "filesystem.read: a") is False
    store.allow(PLUGIN, "filesystem.read: a")
    assert store.allowed(PLUGIN, "filesystem.read: a") is True
    # A different scope, or the same scope for another plugin, asks again.
    assert store.allowed(PLUGIN, "filesystem.read: b") is False
    assert store.allowed("other-plugin", "filesystem.read: a") is False


def test_consent_store_clear_forgets_every_allow():
    store = ConsentStore()
    store.allow(PLUGIN, "scope")
    store.clear()
    assert store.allowed(PLUGIN, "scope") is False


def test_booted_defaults_to_a_fresh_inert_consent_store():
    booted = server_harness.Booted()
    try:
        assert isinstance(booted.server.consents, ConsentStore)
        assert booted.server.consents.allowed(PLUGIN, "scope") is False
    finally:
        booted.close()


# -- the HTTP flow ------------------------------------------------------

def _widened(destination: Path, *, version: str, glob: str) -> Path:
    """The valid plugin plus one extra scoped read glob, version-bumped:
    a widening whose exact scope the test controls."""
    manifest = json.loads((VALID_PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    reads = manifest["permissions"]["filesystem"]["read"]
    manifest["permissions"]["filesystem"]["read"] = sorted(set(reads) | {glob})
    widgets = manifest["contributes"]["widgets"]
    extra = json.loads(json.dumps(widgets[0]))
    extra["id"] = f"widget-{version}"
    extra["dataSource"]["file"] = glob
    widgets.append(extra)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as archive:
        for path in sorted(VALID_PLUGIN_DIR.rglob("*")):
            if not path.is_file() or path.name == "manifest.json":
                continue
            archive.writestr(path.relative_to(VALID_PLUGIN_DIR).as_posix(),
                             path.read_bytes())
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
    return destination


class Running:
    def __init__(self, tmp_path):
        runtime = PluginRuntime(
            plugins_dir=tmp_path / "plugins",
            data_dir=tmp_path / "data",
            workspace_dir=tmp_path / "workspace",
            now="2026-11-11T16:00:00",
        )
        self.booted = server_harness.Booted(plugins=runtime)
        self.runtime = runtime
        self.auth = self.booted.exchange()

    def post(self, path, payload=None):
        status, _h, body = self.booted.post_json(path, payload or {}, self.auth)
        return status, json.loads(body)

    def get(self, path):
        status, _h, body = self.booted.request("GET", path, self.auth)
        return status, json.loads(body)

    def close(self):
        self.booted.close()


@pytest.fixture()
def running(tmp_path):
    r = Running(tmp_path)
    try:
        yield r
    finally:
        r.close()


def _consent_card(running) -> dict:
    status, out = running.get("/widgets/inbox")
    assert status == 200
    cards = running.booted.server.inbox.waiting()
    consent = [c for c in cards if c.kind == "update_consent"]
    assert len(consent) == 1
    return consent[0]


def test_widened_update_creates_an_update_consent_card(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    status, out = running.post("/api/plugins/" + PLUGIN + "/update", {
        "zip_path": str(widened_zip(tmp_path / "wide.zip"))})
    assert status == 200
    assert out["applied"] is False
    card = _consent_card(running)
    assert card.meta["pluginId"] == PLUGIN
    assert "filesystem.read: ${workspace}/reports/*.pdf" in card.meta["scope"]
    assert card.meta["version"] == "1.2.1"
    entries = running.get("/audit/tail")[1]["entries"]
    assert any(e["action"] == "inbox.pending" and "waiting" in e["detail"]
               for e in entries)


def test_accept_for_this_plugin_applies_and_records_the_allow(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    running.post("/api/plugins/" + PLUGIN + "/update",
                 {"zip_path": str(widened_zip(tmp_path / "wide.zip"))})
    card = _consent_card(running)
    status, out = running.post(f"/inbox/cards/{card.id}/accept",
                               {"forPlugin": True})
    assert status == 200
    assert running.runtime.record(PLUGIN)["active_version"] == "1.2.1"
    assert running.booted.server.consents.allowed(
        PLUGIN, card.meta["scope"]) is True
    entries = running.get("/audit/tail")[1]["entries"]
    assert any(e["action"] == "inbox.approved" and e["target"] == card.id
               for e in entries)
    # The card path applies the update, so it writes the same lifecycle
    # row the API endpoint would: the touches badge cannot lie by flow.
    assert any(e["action"] == "plugin.consent" and e["target"] == PLUGIN
               for e in entries)


def test_accept_without_the_choice_does_not_record_an_allow(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    running.post("/api/plugins/" + PLUGIN + "/update",
                 {"zip_path": str(widened_zip(tmp_path / "wide.zip"))})
    card = _consent_card(running)
    running.post(f"/inbox/cards/{card.id}/accept", {})
    assert running.runtime.record(PLUGIN)["active_version"] == "1.2.1"
    assert running.booted.server.consents.allowed(
        PLUGIN, card.meta["scope"]) is False


def test_identical_re_ask_does_not_prompt_again(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    running.post("/api/plugins/" + PLUGIN + "/update",
                 {"zip_path": str(widened_zip(tmp_path / "wide.zip"))})
    card = _consent_card(running)
    running.post(f"/inbox/cards/{card.id}/accept", {"forPlugin": True})
    assert running.runtime.record(PLUGIN)["active_version"] == "1.2.1"

    # Roll back, then offer the identical widening again: the recorded
    # allow answers it without a card.
    running.post("/api/plugins/" + PLUGIN + "/rollback", {})
    assert running.runtime.record(PLUGIN)["active_version"] == "1.2.0"
    status, out = running.post("/api/plugins/" + PLUGIN + "/update", {
        "zip_path": str(widened_zip(tmp_path / "wide-again.zip"))})
    assert status == 200
    assert out["applied"] is True
    assert out["auto_consented"] is True
    assert running.runtime.record(PLUGIN)["active_version"] == "1.2.1"
    assert running.get("/widgets/inbox")[1]["waiting"] == 0
    entries = running.get("/audit/tail")[1]["entries"]
    assert any(e["action"] == "inbox.approved"
               and "pre-approved" in e["detail"] for e in entries)
    # The auto-apply is a real consent application: it writes the row too.
    assert any(e["action"] == "plugin.consent" and e["target"] == PLUGIN
               for e in entries)


def test_a_widened_further_scope_always_re_asks(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    running.post("/api/plugins/" + PLUGIN + "/update",
                 {"zip_path": str(widened_zip(tmp_path / "wide.zip"))})
    card = _consent_card(running)
    running.post(f"/inbox/cards/{card.id}/accept", {"forPlugin": True})

    status, out = running.post("/api/plugins/" + PLUGIN + "/update", {
        "zip_path": str(_widened(tmp_path / "wider.zip", version="1.3.0",
                                 glob="${workspace}/other/*.csv"))})
    assert status == 200
    assert out["applied"] is False  # a different scope asks again
    assert running.runtime.record(PLUGIN)["active_version"] == "1.2.1"
    new_card = _consent_card(running)
    assert new_card.id != card.id
    assert "other/*.csv" in new_card.meta["scope"]


def test_dismissing_the_consent_card_leaves_the_update_held(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    running.post("/api/plugins/" + PLUGIN + "/update",
                 {"zip_path": str(widened_zip(tmp_path / "wide.zip"))})
    card = _consent_card(running)
    status, _out = running.post(f"/inbox/cards/{card.id}/dismiss", {})
    assert status == 200
    assert running.runtime.record(PLUGIN)["pending_update"] is not None
    assert running.booted.server.consents.allowed(PLUGIN, card.meta["scope"]) is False


# -- plugin lifecycle audit rows ----------------------------------------

def test_plugin_lifecycle_actions_write_audit_rows(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    running.post("/api/plugins/" + PLUGIN + "/update", {
        "zip_path": str(valid_zip(tmp_path / "v2.zip",
                                  overrides={"version": "1.2.1"}))})
    running.post("/api/plugins/" + PLUGIN + "/retest", {})
    running.post("/api/plugins/" + PLUGIN + "/disable", {})
    running.post("/api/plugins/" + PLUGIN + "/enable", {})
    running.post("/api/plugins/" + PLUGIN + "/rollback", {})
    running.post("/api/plugins/" + PLUGIN + "/consent", {})  # nothing pending: refused
    running.post("/api/plugins/" + PLUGIN + "/uninstall", {})
    running.post("/api/plugins/" + PLUGIN + "/purge-data",
                 {"confirmation": f"delete-data:{PLUGIN}"})
    actions = {e["action"]: e for e in running.get("/audit/tail")[1]["entries"]}
    for expected in ("plugin.install", "plugin.update", "plugin.retest",
                     "plugin.disable", "plugin.enable", "plugin.rollback",
                     "plugin.uninstall", "plugin.purge-data"):
        assert expected in actions, f"missing audit row {expected}"
        assert actions[expected]["target"] == PLUGIN
    # The refused consent did not mutate anything, so it wrote no row.
    assert "plugin.consent" not in actions


def test_plugin_consent_through_the_api_is_audited(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    running.post("/api/plugins/" + PLUGIN + "/update",
                 {"zip_path": str(widened_zip(tmp_path / "wide.zip"))})
    status, out = running.post("/api/plugins/" + PLUGIN + "/consent", {})
    assert status == 200
    assert out["applied"] is True
    actions = {e["action"] for e in running.get("/audit/tail")[1]["entries"]}
    assert "plugin.consent" in actions


def test_touches_page_flips_the_badge_once_a_plugin_action_ran(running, tmp_path):
    running.post("/api/plugins/install",
                 {"zip_path": str(valid_zip(tmp_path / "v1.zip"))})
    status, _h, body = running.booted.request("GET", "/what-this-touches",
                                              running.auth)
    page = body.decode("utf-8")
    assert status == 200
    row = page.split("plugin.install", 1)[1]
    assert "in use" in row.split("</tr>")[0]
