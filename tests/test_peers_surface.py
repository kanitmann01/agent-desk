"""The peer surface end to end (ticket #67), over two real servers.

Every acceptance path runs hermetically in one process: two full server
instances on ephemeral ports with their own data dirs, real sockets, a
real UDP announce port. Pairing via code, the wrong-code refusal, the
token-gated read-only peer endpoint, share -> discover -> install, the
publisher's version bump -> update-available -> one-click update, and
the honest unreachable state. Wrong or missing tokens are named
refusals; nothing else under /peer/ answers at all.
"""
import http.client
import json
import sqlite3
import sys
import time
import urllib.parse
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness  # noqa: E402
import pytest  # noqa: E402
from plugins_fixtures import valid_zip  # noqa: E402

from nexuusbot.assistant import audit as audit_store  # noqa: E402
from nexuusbot.peers.store import PeerStore, derive_token  # noqa: E402
from nexuusbot.registry.install import tree_digest  # noqa: E402

PLUGIN_ID = "sales-delta-widget"


def _boot(**kwargs) -> server_harness.Booted:
    kwargs.setdefault(
        "peer_store",
        PeerStore(sqlite3.connect(":memory:", check_same_thread=False),
                  time.time))
    return server_harness.Booted(**kwargs)


def _form(payload: dict) -> bytes:
    return urllib.parse.urlencode(payload).encode("utf-8")


def _post_form(booted, path: str, payload: dict, auth: dict):
    body = _form(payload)
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Content-Length": str(len(body))}
    headers.update(auth)
    return booted.request("POST", path, headers=headers, body=body)


def _free_udp_port() -> int:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _api_peers(booted, auth) -> dict:
    status, _h, body = booted.request("GET", "/api/peers", auth)
    assert status == 200, body
    return json.loads(body)


def _install_plugin(booted, auth, tmp_path, version=None) -> Path:
    overrides = {"version": version} if version else None
    zip_path = valid_zip(tmp_path / f"plugin-{version or '1.2.0'}.zip",
                         overrides=overrides)
    status, _h, body = booted.post_json(
        "/api/plugins/install", {"zip_path": str(zip_path)}, auth)
    assert status == 200, body
    return zip_path


# -- the quiet default and the peers page --------------------------------


def test_fresh_boot_is_silent_and_the_peers_page_starts_discovery():
    booted = _boot()
    try:
        assert booted.server.peer_discovery is None  # silent by default
        auth = booted.exchange()
        status, _h, page = booted.request("GET", "/peers", auth)
        assert status == 200
        text = page.decode("utf-8")
        assert "<h1>Peers</h1>" in text
        # Peers is hidden from the rail for now; the page itself still
        # answers for the pairing flow and for direct links.
        assert 'href="/peers"' not in text
        assert booted.server.peer_discovery is not None
        assert booted.server.peer_discovery.running()
    finally:
        booted.close()


def test_discovery_between_two_instances_on_one_machine():
    announce_port = _free_udp_port()
    a = _boot(announce_port=announce_port)
    b = _boot(announce_port=announce_port)
    try:
        auth_a = a.exchange()
        auth_b = b.exchange()
        a.request("GET", "/peers", auth_a)  # starts announcing/listening
        b.request("GET", "/peers", auth_b)
        desk_a = a.server.peer_store.desk()
        deadline = time.monotonic() + 20.0
        discovered = []
        while time.monotonic() < deadline:
            discovered = [d["peer_id"] for d in _api_peers(b, auth_b)["discovered"]]
            if desk_a["peer_id"] in discovered:
                break
            time.sleep(0.25)
        assert desk_a["peer_id"] in discovered, (
            f"B never discovered A via UDP on port {announce_port}; "
            f"saw {discovered}")
    finally:
        a.close()
        b.close()


# -- the peer endpoint surface: token-gated, read-only -------------------


def test_peer_endpoint_refuses_unpaired_requests_by_name():
    booted = _boot()
    try:
        host = booted.host_header()
        status, _h, body = booted.request("GET", "/peer/info", host)
        assert status == 403
        assert json.loads(body)["error"] == "peer:token-required"

        status, _h, body = booted.request(
            "GET", "/peer/info",
            {**host, "Authorization": "Bearer not-a-real-token"})
        assert status == 403
        assert json.loads(body)["error"] == "peer:token-unknown"

        # write path does not exist: the surface is read-only
        status, _h, body = booted.request(
            "POST", "/peer/info", {**host, "Content-Length": "0"})
        assert status == 405
        assert json.loads(body)["error"] == "peer:read-only"

        # and nothing else answers under /peer/
        status, _h, body = booted.request(
            "GET", "/peer/other", {**host, "Authorization": "Bearer x"})
        assert status == 404
        assert json.loads(body)["error"] == "peer:not-found"
    finally:
        booted.close()


def test_shared_plugin_serves_info_manifest_and_bundle_with_true_digest(
        tmp_path):
    a = _boot()
    try:
        auth = a.exchange()
        _install_plugin(a, auth, tmp_path)
        status, _h, _b = _post_form(a, f"/plugins/{PLUGIN_ID}/share",
                                    {}, auth)
        assert status == 303

        # act as the other desk: ask A for a code, submit it over HTTP
        status, _h, _b = _post_form(a, "/peers/code", {}, auth)
        assert status == 303
        code = _api_peers(a, auth)["pairingCode"]["code"]
        body = json.dumps({"code": code, "peer_id": "desk-b",
                           "name": "Desk B", "host": "127.0.0.1",
                           "port": 9001}).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", a.port, timeout=5)
        conn.request("POST", "/peer/pair", body=body, headers={
            "Host": f"127.0.0.1:{a.port}",
            "Content-Type": "application/json",
            "Content-Length": str(len(body))})
        response = conn.getresponse()
        assert response.status == 200, response.read()
        conn.close()

        token = derive_token(code)
        headers = {**a.host_header(), "Authorization": f"Bearer {token}"}
        status, _h, payload = a.request("GET", "/peer/info", headers)
        assert status == 200
        info = json.loads(payload)
        assert info["peer_id"] == a.server.peer_store.desk()["peer_id"]
        assert info["name"]
        plugins = info["plugins"]
        assert [p["id"] for p in plugins] == [PLUGIN_ID]
        assert plugins[0]["version"] == "1.2.0"
        recorded = a.server.plugins.record(PLUGIN_ID)
        assert plugins[0]["sha256"] == recorded["sha256"]

        status, _h, payload = a.request(
            "GET", f"/peer/plugins/{PLUGIN_ID}/manifest", headers)
        assert status == 200
        assert json.loads(payload)["id"] == PLUGIN_ID

        status, _h, payload = a.request(
            "GET", f"/peer/plugins/{PLUGIN_ID}/bundle", headers)
        assert status == 200
        archive = zipfile.ZipFile(BytesIO(payload))
        names = sorted(archive.namelist())
        assert "manifest.json" in names
        # the bundle extracts to exactly the digest info promised
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        archive.extractall(extracted)
        assert tree_digest(extracted) == plugins[0]["sha256"]
    finally:
        a.close()


# -- pairing flows ---------------------------------------------------------


def test_pairing_succeeds_and_wrong_code_is_a_named_refusal():
    a = _boot()
    b = _boot()
    try:
        auth_a = a.exchange()
        auth_b = b.exchange()
        status, _h, _b = _post_form(a, "/peers/code", {}, auth_a)
        assert status == 303
        code = _api_peers(a, auth_a)["pairingCode"]["code"]

        # wrong code first: named refusal, nothing paired
        status, _h, body = b.post_json(
            "/peers/pair", {"address": f"127.0.0.1:{a.port}",
                            "code": "WRONG911"}, auth_b)
        assert status == 409
        assert json.loads(body)["error"] == "pairing:unknown-code"
        assert b.server.peer_store.peers() == []

        # the right code pairs both sides
        status, _h, _b = _post_form(
            b, "/peers/pair",
            {"address": f"127.0.0.1:{a.port}", "code": code}, auth_b)
        assert status == 303
        desk_a = a.server.peer_store.desk()
        desk_b = b.server.peer_store.desk()
        assert [p["peer_id"] for p in b.server.peer_store.peers()] == \
            [desk_a["peer_id"]]
        assert [p["peer_id"] for p in a.server.peer_store.peers()] == \
            [desk_b["peer_id"]]
        # both sides hold the same channel credential
        assert (b.server.peer_store.channel_token(desk_a["peer_id"])
                == derive_token(code))
        assert (a.server.peer_store.channel_token(desk_b["peer_id"])
                == derive_token(code))
        # the code is single-use: a replay is refused by name
        status, _h, body = b.post_json(
            "/peers/pair", {"address": f"127.0.0.1:{a.port}", "code": code},
            auth_b)
        assert json.loads(body)["error"] == "pairing:used"
    finally:
        a.close()
        b.close()


def test_unreachable_peer_is_listed_with_its_cause():
    a = _boot()
    b = _boot()
    try:
        auth_a = a.exchange()
        auth_b = b.exchange()
        _post_form(a, "/peers/code", {}, auth_a)
        code = _api_peers(a, auth_a)["pairingCode"]["code"]
        _post_form(b, "/peers/pair",
                   {"address": f"127.0.0.1:{a.port}", "code": code}, auth_b)
        # A goes away entirely
        a.close()
        status, _h, _b = _post_form(b, "/peers/refresh", {}, auth_b)
        assert status == 303
        data = _api_peers(b, auth_b)
        assert data["paired"], "the peer must still be listed, with its cause"
        assert data["paired"][0]["state"]["ok"] is False
        assert "could not be reached" in data["paired"][0]["state"]["cause"]
    finally:
        b.close()


# -- the full loop: share, pair, install, bump, update --------------------


def test_share_discover_pair_install_and_update_in_one_click(tmp_path):
    announce_port = _free_udp_port()
    a = _boot(announce_port=announce_port)
    b = _boot(announce_port=announce_port)
    try:
        auth_a = a.exchange()
        auth_b = b.exchange()

        # A installs a plugin and shares it
        _install_plugin(a, auth_a, tmp_path)
        _post_form(a, f"/plugins/{PLUGIN_ID}/share", {}, auth_a)
        assert a.server.peer_store.shared_ids() == {PLUGIN_ID}

        # both desks open the peers page: discovery starts, A is seen
        a.request("GET", "/peers", auth_a)
        b.request("GET", "/peers", auth_b)
        desk_a = a.server.peer_store.desk()
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if desk_a["peer_id"] in [d["peer_id"] for d
                                     in _api_peers(b, auth_b)["discovered"]]:
                break
            time.sleep(0.25)

        # B pairs with A by code
        _post_form(a, "/peers/code", {}, auth_a)
        code = _api_peers(a, auth_a)["pairingCode"]["code"]
        status, _h, _b = _post_form(
            b, "/peers/pair",
            {"address": f"127.0.0.1:{a.port}", "code": code}, auth_b)
        assert status == 303

        # B sees A's shared plugin (pairing refreshes once, honestly)
        data = _api_peers(b, auth_b)
        plugin = data["paired"][0]["plugins"][0]
        assert plugin["id"] == PLUGIN_ID
        assert plugin["version"] == "1.2.0"
        assert plugin["installed_here"] is False
        assert plugin["update_available"] is False

        # B installs it: the lockfile records the peer source
        status, _h, _body = _post_form(
            b, "/peers/install",
            {"peer_id": desk_a["peer_id"], "plugin_id": PLUGIN_ID}, auth_b)
        assert status == 303
        record = b.server.plugins.record(PLUGIN_ID)
        assert record["active_version"] == "1.2.0"
        assert record["source"].startswith("peer:")
        lockfile = json.loads((b.server.plugins.plugins_dir / "lockfile.json")
                              .read_text(encoding="utf-8"))
        assert lockfile["plugins"][PLUGIN_ID]["source"].startswith("peer:")

        data = _api_peers(b, auth_b)
        plugin = data["paired"][0]["plugins"][0]
        assert plugin["installed_here"] is True
        assert plugin["update_available"] is False

        # the publisher bumps the version
        newer = _install_plugin_newer(a, auth_a, tmp_path)
        assert newer

        # B refreshes: update-available only because it truly differs
        _post_form(b, "/peers/refresh", {}, auth_b)
        data = _api_peers(b, auth_b)
        plugin = data["paired"][0]["plugins"][0]
        assert plugin["version"] == "1.2.1"
        assert plugin["update_available"] is True

        # one click resolves it
        status, _h, _body = _post_form(
            b, "/peers/update",
            {"peer_id": desk_a["peer_id"], "plugin_id": PLUGIN_ID}, auth_b)
        assert status == 303
        assert b.server.plugins.record(PLUGIN_ID)["active_version"] == "1.2.1"

        # every step wrote its audit row
        actions = {row["action"]
                   for row in audit_store.entries(b.server.audit_conn, 100)}
        assert {"peer.pair", "peer.install", "peer.update"} <= actions
        actions_a = {row["action"]
                     for row in audit_store.entries(a.server.audit_conn, 100)}
        assert {"peer.share", "peer.paired", "peer.read"} <= actions_a
    finally:
        a.close()
        b.close()


def _install_plugin_newer(booted, auth, tmp_path) -> str:
    zip_path = valid_zip(tmp_path / "plugin-1.2.1.zip",
                         overrides={"version": "1.2.1"})
    status, _h, body = booted.post_json(
        f"/api/plugins/{PLUGIN_ID}/update", {"zip_path": str(zip_path)}, auth)
    assert status == 200, body
    return "1.2.1"


# -- the share toggle on the plugins page ---------------------------------


def test_marketplace_share_toggle_drives_the_peer_store(tmp_path):
    booted = _boot()
    try:
        auth = booted.exchange()
        _install_plugin(booted, auth, tmp_path)

        status, _h, body = booted.post_json(
            "/api/marketplace/share", {"id": PLUGIN_ID}, auth)
        assert status == 200, body
        assert json.loads(body)["shared"] is True
        assert booted.server.peer_store.shared_ids() == {PLUGIN_ID}
        status, _h, body = booted.request(
            "GET", "/api/marketplace/installed", auth)
        installed = json.loads(body)["plugins"]
        assert next(p for p in installed if p["id"] == PLUGIN_ID)["shared"] is True

        status, _h, body = booted.post_json(
            "/api/marketplace/unshare", {"id": PLUGIN_ID}, auth)
        assert status == 200, body
        assert json.loads(body)["shared"] is False
        assert booted.server.peer_store.shared_ids() == set()

        status, _h, _body = booted.post_json(
            "/api/marketplace/uninstall", {"id": PLUGIN_ID}, auth)
        assert status == 200
        status, _h, body = booted.post_json(
            "/api/marketplace/share", {"id": PLUGIN_ID}, auth)
        assert status == 404
        assert json.loads(body)["error"] == "plugin:unknown"
    finally:
        booted.close()


# -- review fixes: verification and refusal honesty ------------------------


class _FakePeerClient:
    """Stands in for PeerClient inside the server: serves a scripted
    info payload and bundle bytes without touching the network."""

    def __init__(self, info_payload: dict, bundle_bytes: bytes) -> None:
        self._info = info_payload
        self._bundle = bundle_bytes

    def info(self, base_url: str, token: str) -> dict:
        return self._info

    def bundle(self, base_url: str, token: str, plugin_id: str) -> bytes:
        return self._bundle


def _fake_paired_peer(booted) -> str:
    booted.server.peer_store.add_peer(
        peer_id="desk-fake", name="Fake Peer", base_url="127.0.0.1:1",
        token="tok")
    return "desk-fake"


def test_missing_published_digest_is_a_named_refusal_never_verified(
        tmp_path, monkeypatch):
    """/peer/info without a sha256 must not skip verification while the
    audit row still says verified: it is a named refusal."""
    from nexuusbot.server import peers_api as server_app

    booted = _boot()
    try:
        auth = booted.exchange()
        peer_id = _fake_paired_peer(booted)
        bundle = valid_zip(tmp_path / "p.zip").read_bytes()
        fake = _FakePeerClient(
            {"ok": True, "peer_id": peer_id, "name": "Fake Peer",
             "plugins": [{"id": PLUGIN_ID, "version": "1.2.0",
                          "sha256": ""}]},
            bundle)
        monkeypatch.setattr(server_app, "PeerClient", lambda: fake)
        status, _h, body = booted.post_json(
            "/peers/install", {"peer_id": peer_id, "plugin_id": PLUGIN_ID},
            auth)
        assert status == 409
        assert json.loads(body)["error"] == "peer:digest-unknown"
        rows = [row for row in audit_store.entries(booted.server.audit_conn, 50)
                if row["action"] == "peer.install"]
        assert rows and all(row["status"] == "error" for row in rows)
        assert not any("verified" in row["detail"] for row in rows)
    finally:
        booted.close()


def test_validator_refusal_on_peer_install_is_named_and_audited(
        tmp_path, monkeypatch):
    """A bundle that fails the shared validator is a named refusal with
    an error audit row, never an unnamed 500."""
    from nexuusbot.plugins.runtime import PluginError
    from nexuusbot.server import peers_api as server_app

    booted = _boot()
    try:
        auth = booted.exchange()
        peer_id = _fake_paired_peer(booted)
        from plugins_fixtures import shell_zip

        shell = shell_zip(tmp_path / "shell.zip")
        staged = tmp_path / "staged"
        staged.mkdir()
        import zipfile as _zipfile

        with _zipfile.ZipFile(shell) as archive:
            archive.extractall(staged)
        from nexuusbot.registry.install import tree_digest as _digest

        digest = _digest(staged)
        fake = _FakePeerClient(
            {"ok": True, "peer_id": peer_id, "name": "Fake Peer",
             "plugins": [{"id": PLUGIN_ID, "version": "9.9.9",
                          "sha256": digest}]},
            shell.read_bytes())
        monkeypatch.setattr(server_app, "PeerClient", lambda: fake)
        status, _h, body = booted.post_json(
            "/peers/install", {"peer_id": peer_id, "plugin_id": PLUGIN_ID},
            auth)
        assert status == 400, body
        payload = json.loads(body)
        assert payload["error"] == "install:validator-failed"
        rows = [row for row in audit_store.entries(booted.server.audit_conn, 50)
                if row["action"] == "peer.install"]
        assert rows and rows[-1]["status"] == "error"
        with pytest.raises(PluginError):
            booted.server.plugins.record(PLUGIN_ID)
    finally:
        booted.close()


def test_unsafe_flow_names_are_refused_before_any_staging():
    """A plugin id or peer id that is not a safe name is refused before
    it can name a file inside (or outside) the staging folder."""
    booted = _boot()
    try:
        auth = booted.exchange()
        _fake_paired_peer(booted)
        for path, payload in (
                ("/peers/update", {"peer_id": "desk-fake",
                                   "plugin_id": "../x"}),
                ("/peers/install", {"peer_id": "..\\evil",
                                    "plugin_id": "fine-name"}),
                ("/peers/install", {"peer_id": "desk-fake",
                                    "plugin_id": "seems/ok"}),
        ):
            status, _h, body = booted.post_json(path, payload, auth)
            assert status == 400, (path, body)
            assert json.loads(body)["error"] == "peer:unsafe-name"
    finally:
        booted.close()


def test_bad_address_refusal_names_the_typed_input():
    booted = _boot()
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/peers/pair", {"address": "not an address at all",
                            "code": "ABCD2345"}, auth)
        assert status == 400
        payload = json.loads(body)
        assert payload["error"] == "peer:bad-address"
        assert "not an address at all" in payload["message"]
        assert "None" not in payload["message"]
    finally:
        booted.close()


def test_share_response_says_when_no_desks_are_paired(tmp_path):
    booted = _boot()
    try:
        auth = booted.exchange()
        _install_plugin(booted, auth, tmp_path)
        status, _h, body = booted.post_json(
            "/api/marketplace/share", {"id": PLUGIN_ID}, auth)
        assert status == 200, body
        assert json.loads(body)["paired"] == 0

        booted.server.peer_store.add_peer(
            peer_id="desk-a", name="A", base_url="127.0.0.1:8801",
            token="t")
        status, _h, body = booted.post_json(
            "/api/marketplace/share", {"id": PLUGIN_ID}, auth)
        assert status == 200, body
        assert json.loads(body)["paired"] == 1
    finally:
        booted.close()


def test_discovered_cards_do_not_prefill_unconnectable_addresses():
    """A desk on another machine shows its real source address and an
    honest not-connectable note; only same-machine desks prefill the
    pair form."""
    from nexuusbot.server.peers_view import render_peers_page

    catalog = {
        "ok": True,
        "desk": {"peer_id": "desk-me", "name": "This Desk"},
        "pairingCode": None,
        "discovered": [
            {"peer_id": "desk-near", "name": "Near Desk",
             "host": "127.0.0.1", "port": 8801, "source": "127.0.0.1",
             "connectable": True, "pairing_required": True,
             "last_seen": 1.0},
            {"peer_id": "desk-far", "name": "Far Desk",
             "host": "127.0.0.1", "port": 8802, "source": "203.0.113.9",
             "connectable": False, "pairing_required": True,
             "last_seen": 1.0},
        ],
        "paired": [],
    }
    page = render_peers_page(catalog, "test")
    assert 'value="127.0.0.1:8801"' in page       # near desk prefills
    assert "203.0.113.9" in page                  # far desk's source shown
    assert "another machine" in page              # honest note
    assert 'value="203.0.113.9' not in page       # never prefilled
