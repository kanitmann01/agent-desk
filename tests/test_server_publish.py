"""The create-to-publish loop over the real server (ticket #63).

A locally installed plugin publishes to the resolved registry from the
Plugins page and from the wizard's approved screen; the release appears
in the registry listing, refuses a duplicate with a named error, writes
audit rows, and a second fresh runtime installs it by id@version from
the mutated registry root with the lockfile recording the source.
"""
import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness  # noqa: E402
from plugins_fixtures import VALID_PLUGIN_DIR  # noqa: E402
from registry_fixtures import make_registry, tree_digest  # noqa: E402

PLUGIN_ID = "team-notes-widget"
PLUGIN_VERSION = "0.2.0"


def _post_form(booted, path: str, payload: dict, auth: dict):
    body = urllib.parse.urlencode(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
    }
    headers.update(auth)
    return booted.request("POST", path, headers=headers, body=body)


def _plugin_zip(tmp_path: Path) -> Path:
    """A locally built plugin zip: the 'or otherwise' of wizard-made."""
    import zipfile
    from plugins_fixtures import ZIP_DATE

    manifest = json.loads(
        (VALID_PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = PLUGIN_ID
    manifest["name"] = "Team Notes"
    manifest["version"] = PLUGIN_VERSION
    zip_path = tmp_path / "team-notes.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in sorted(VALID_PLUGIN_DIR.rglob("*")):
            if not path.is_file() or path.name == "manifest.json":
                continue
            info = zipfile.ZipInfo(path.relative_to(VALID_PLUGIN_DIR).as_posix(),
                                   date_time=ZIP_DATE)
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("manifest.json", date_time=ZIP_DATE)
        archive.writestr(info, json.dumps(manifest, indent=2) + "\n")
    return zip_path


def _install_local_plugin(booted, auth, tmp_path) -> dict:
    zip_path = _plugin_zip(tmp_path)
    status, _h, body = booted.post_json(
        "/api/plugins/install", {"zip_path": str(zip_path)}, auth)
    assert status == 200, body
    return json.loads(body)


def test_publish_loop_end_to_end(tmp_path):
    """Install locally, publish, list, refuse the duplicate, install on a
    second fresh runtime from the mutated registry root."""
    registry = make_registry(tmp_path)
    booted = server_harness.Booted(registry_root=str(registry))
    try:
        auth = booted.exchange()
        installed = _install_local_plugin(booted, auth, tmp_path)
        assert installed["id"] == PLUGIN_ID

        # Publish through the JSON route.
        status, _h, body = booted.post_json(
            f"/api/plugins/{PLUGIN_ID}/publish", {}, auth)
        assert status == 200, body
        result = json.loads(body)
        assert result["ok"] is True
        assert result["source"] == "local"
        assert result["version"] == PLUGIN_VERSION

        # The registry listing shows the new release.
        status, _h, body = booted.request("GET", "/api/registry", auth)
        listing = json.loads(body)
        assert listing["ok"] is True
        entry = next(e for e in listing["plugins"] if e["id"] == PLUGIN_ID)
        assert entry["latest"] == PLUGIN_VERSION
        release = entry["releases"][0]
        assert release["source"] == "local"
        assert release["version"] == PLUGIN_VERSION
        assert release["sha256"] == result["sha256"]
        # The pre-existing tag-pinned release is untouched.
        sales = next(e for e in listing["plugins"]
                     if e["id"] == "sales-delta-widget")
        assert sales["releases"][0]["source"] == "tag"

        # The duplicate publish is refused with the named error.
        status, _h, body = booted.post_json(
            f"/api/plugins/{PLUGIN_ID}/publish", {}, auth)
        assert status == 409
        assert json.loads(body)["error"] == "publish:already-exists"

        # The audit row landed.
        from nexuusbot.assistant import audit as audit_store
        rows = audit_store.entries(booted.server.audit_conn, limit=50)
        published = [r for r in rows if r["action"] == "registry.publish"]
        assert published and published[0]["target"] == PLUGIN_ID

        # A second, fresh runtime installs it by id@version from the
        # mutated registry root: the registry bridge end to end.
        from nexuusbot.plugins.runtime import PluginRuntime
        from nexuusbot.registry import source as registry_source
        from nexuusbot.registry.install import read_lock

        fresh = tmp_path / "fresh-desk"
        runtime = PluginRuntime(plugins_dir=fresh / "plugins",
                                data_dir=fresh / "plugin-data",
                                workspace_dir=fresh / "workspace",
                                now="2026-11-13T09:00:00")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            staged = registry_source.stage_registry_install(
                registry, PLUGIN_ID, version=PLUGIN_VERSION,
                staging_dir=Path(tmp))
            record = runtime.install(staged["dir"], source="registry")
            # The registry-side lock pins the digest for this client.
            client_lock = read_lock(Path(tmp), PLUGIN_ID)
        assert client_lock["version"] == PLUGIN_VERSION
        assert client_lock["sha256"] == result["sha256"]
        assert record["id"] == PLUGIN_ID
        assert record["version"] == PLUGIN_VERSION
        assert record["sha256"] == result["sha256"]
        # The runtime lockfile records the source.
        lock_state = json.loads(
            (fresh / "plugins" / "lockfile.json").read_text(encoding="utf-8"))
        assert lock_state["plugins"][PLUGIN_ID]["source"] == "registry"
    finally:
        booted.close()


def test_publish_from_the_legacy_plugins_form_still_works(tmp_path):
    registry = make_registry(tmp_path)
    booted = server_harness.Booted(registry_root=str(registry))
    try:
        auth = booted.exchange()
        _install_local_plugin(booted, auth, tmp_path)

        # The page itself now points at the marketplace; the one-release
        # compatibility window still accepts the old POST form.
        status, headers, _page = booted.request("GET", "/plugins", auth)
        assert status == 302
        assert headers["Location"] == "/marketplace/installed"

        status, headers, _b = _post_form(
            booted, f"/plugins/{PLUGIN_ID}/publish", {}, auth)
        assert status == 303
        assert headers["Location"].startswith("/plugins?notice=Published")

        # The release is listed for the next visitor.
        status, _h, body = booted.request("GET", "/api/registry", auth)
        listing = json.loads(body)
        assert any(e["id"] == PLUGIN_ID for e in listing["plugins"])
    finally:
        booted.close()


def test_publish_refused_without_a_registry_names_the_sources(tmp_path):
    booted = server_harness.Booted(registry_root="")
    try:
        auth = booted.exchange()
        _install_local_plugin(booted, auth, tmp_path)

        status, _h, body = booted.post_json(
            f"/api/plugins/{PLUGIN_ID}/publish", {}, auth)
        assert status == 409
        refusal = json.loads(body)
        assert refusal["error"] == "publish:no-registry"
        for needle in ("registry_path", "AGENTDESK_REGISTRY", "checkout"):
            assert needle in refusal["message"]

        # The page form rides the same refusal back as the notice line.
        status, headers, _b = _post_form(
            booted, f"/plugins/{PLUGIN_ID}/publish", {}, auth)
        assert status == 303
        notice = urllib.parse.unquote(headers["Location"])
        assert "publish" in notice.lower() or "registry" in notice.lower()
    finally:
        booted.close()


def test_publish_unknown_plugin_is_a_named_404(tmp_path):
    registry = make_registry(tmp_path)
    booted = server_harness.Booted(registry_root=str(registry))
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/api/plugins/ghost-plugin/publish", {}, auth)
        assert status == 404
        assert json.loads(body)["error"] == "plugin:unknown"
    finally:
        booted.close()


def test_publish_after_uninstall_is_a_named_refusal(tmp_path):
    registry = make_registry(tmp_path)
    booted = server_harness.Booted(registry_root=str(registry))
    try:
        auth = booted.exchange()
        _install_local_plugin(booted, auth, tmp_path)
        status, _h, _b = booted.post_json(
            f"/api/plugins/{PLUGIN_ID}/uninstall", {}, auth)
        assert status == 200

        status, _h, body = booted.post_json(
            f"/api/plugins/{PLUGIN_ID}/publish", {}, auth)
        assert status == 409
        assert json.loads(body)["error"] == "publish:uninstalled"
    finally:
        booted.close()


class _FakeClock:
    def __init__(self, start: float) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _good_llm(prompt: str) -> str:
    """A corporate endpoint that answers the wizard's JSON asks sanely."""
    if "question" in prompt or "clarif" in prompt:
        return json.dumps({"questions": [
            {"id": "cadence", "question": "How often should it refresh?",
             "options": ["hourly", "every 15 minutes"], "default": "hourly"},
        ]})
    return json.dumps({
        "title": "Sales, last 24 hours",
        "description": "What changed in the watched workbook since yesterday.",
    })


def test_wizard_approved_screen_offers_publish(tmp_path):
    """The wizard's approved screen carries a plain no-JS Publish form."""
    import sqlite3
    from datetime import datetime

    from nexuusbot.wizard.core import WizardStore

    registry = make_registry(tmp_path)
    clock = _FakeClock(datetime(2026, 11, 11, 9, 0, 0).astimezone().timestamp())
    booted = server_harness.Booted(
        registry_root=str(registry),
        wizard_store=WizardStore(
            sqlite3.connect(":memory:", check_same_thread=False), clock),
        llm=_good_llm,
    )
    try:
        auth = booted.exchange()
        started = json.loads(booted.post_json(
            "/wizard/start",
            {"description": "Watch this workbook and show me the 24-hour change"},
            auth)[2])
        # The whole path is answered before anything builds: a workbook, its
        # latest figure, and a tile read when the desk is opened.
        booted.post_json(f"/wizard/{started['id']}/answer", {"answers": {
            "source": "An Excel workbook",
            "show": "The latest figure",
            "look": "A big number",
            "update": "When I open the desk",
        }}, auth)
        status, _h, _b = booted.request(
            "POST", f"/wizard/{started['id']}/approve", auth, b"")
        assert status == 200

        records = booted.server.plugins.list_records()
        assert len(records) == 1
        plugin_id = records[0]["id"]

        status, _h, page = booted.request("GET", f"/wizard/{started['id']}", auth)
        text = page.decode("utf-8")
        assert status == 200
        assert f'action="/plugins/{plugin_id}/publish"' in text
        assert "Publish to the registry" in text
        assert text.count("<h1>") == 1
    finally:
        booted.close()
