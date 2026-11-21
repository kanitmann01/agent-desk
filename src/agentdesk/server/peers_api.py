"""The peers api: the peer-to-peer surface, page and JSON both.

Moved verbatim out of server/app.py (spec 017 #217 workstream 11c, the
second of exactly two splits by job): the request gate, routing and the
bootstrap stay in app.py. The mixin's methods answer through self, so
the shared handler machinery they call lives on DashboardHandler; the
peers suites (tests/test_peers_*.py) are the proof nothing changed.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import quote
import json
import logging
import re
import tempfile
import zipfile

import agentdesk

from agentdesk.peers.client import PeerClient, PeerClientError, extract_bundle
from agentdesk.peers.store import PeerError, PeerStore, derive_token
from agentdesk.plugins.runtime import PluginError, PluginRuntime
from agentdesk.registry.install import tree_digest
from agentdesk.server.core import _active_version_dir
from agentdesk.server.guard import check_peer_request, check_request
from agentdesk.server.peers_view import render_peers_page

LOG = logging.getLogger("agentdesk.server")


def _peer_plugin_path(path: str) -> tuple[str | None, str]:
    """'/peer/plugins/<id>/<tail>' as (plugin_id, tail), with the id
    checked against the safe-name rule before it ever names a file; a
    path that is not that shape answers (None, '')."""
    prefix = "/peer/plugins/"
    if not path.startswith(prefix):
        return None, ""
    remainder = path[len(prefix):]
    plugin_id, sep, tail = remainder.partition("/")
    if not sep or not plugin_id or not _PEER_SAFE_NAME.match(plugin_id):
        return None, ""
    return plugin_id, tail

def _normalize_peer_address(address: str) -> str | None:
    """host:port with an optional http:// scheme stripped; None when the
    shape is wrong (a hostname without a port is refused: the peer
    surface always names its port)."""
    text = address.strip()
    for scheme in ("http://", "https://"):
        if text.startswith(scheme):
            text = text[len(scheme):]
    text = text.rstrip("/")
    host, sep, port_text = text.partition(":")
    if not sep or not host or not port_text.isascii() or not port_text.isdigit():
        return None
    port = int(port_text)
    if not (0 < port < 65536):
        return None
    return f"{host}:{port}"

_PEER_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PeersApiMixin:
    """The peers surface's handler methods, moved unchanged."""

    # -- the peer-to-peer surface (issue #67) ------------------------------

    def _peer_bearer_token(self) -> str:
        """The channel token from the one transport the peer surface
        accepts: an Authorization: Bearer header. There is no
        query-string form by design (tokens must not land in logs)."""
        header = self.headers.get("Authorization") or ""
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return ""

    def _route_peer_get(self, path: str) -> None:
        """Serve one peer GET, gated for a paired desk rather than a browser session.

        The guard weighs Host, Origin and the pairing token together, and a request
        failing it gets a peer:blocked 403 with the reason. The three read paths
        (/peer/info, a plugin's manifest and its bundle) each check the token again
        before answering, because the guard's token test is also what a desk without a
        token fails. Every read is audited as peer.read, so another desk's access shows
        up in this desk's trail.
        """
        token = self._peer_bearer_token()
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        token_ok = bool(store is not None and token
                        and store.token_valid(token))
        verdict = check_peer_request(
            self.headers.get("Host"), self.headers.get("Origin"),
            self.server.port, token_ok=token_ok)  # type: ignore[attr-defined]
        if not verdict.allowed:
            self._send_json(403, {
                "error": "peer:blocked",
                "message": ("This request did not come from a paired desk: "
                            + verdict.reason)})
            return
        if path == "/peer/info":
            if not self._peer_token_passed(token, token_ok):
                return
            self._audit("peer.read", target="info",
                        detail="a paired desk listed shared plugins")
            self._send_json(200, self._peer_info_payload())
            return
        plugin_id, tail = _peer_plugin_path(path)
        if plugin_id is not None and tail == "manifest":
            if not self._peer_token_passed(token, token_ok):
                return
            self._peer_serve_manifest(plugin_id)
            return
        if plugin_id is not None and tail == "bundle":
            if not self._peer_token_passed(token, token_ok):
                return
            self._peer_serve_bundle(plugin_id)
            return
        self._send_json(404, {"error": "peer:not-found",
                              "message": "No peer path lives at " + path})

    def _peer_token_passed(self, token: str, token_ok: bool) -> bool:
        """403 with the named reason when the token is missing or wrong."""
        if token_ok:
            return True
        if not token:
            self._send_json(403, {
                "error": "peer:token-required",
                "message": "This surface is for paired desks: send the "
                           "channel token as an Authorization: Bearer "
                           "header."})
        else:
            self._send_json(403, {
                "error": "peer:token-unknown",
                "message": "That channel token does not name a paired "
                           "desk here."})
        return False

    def _route_peer_post(self, path: str) -> None:
        """Handle the one peer POST that exists, pairing, and refuse everything else.

        Pairing has no token to present (its code is the gate), so it takes the plain
        Host and Origin guard. Any other peer POST is a 405 explaining that the surface
        reads and pairs and changes nothing else.
        """
        if path == "/peer/pair":
            # The pairing path has no token (its code is the gate), so
            # it takes the plain guard, unchanged.
            verdict = check_request(
                self.headers.get("Host"), self.headers.get("Origin"),
                self.server.port)  # type: ignore[attr-defined]
            if not verdict.allowed:
                self._send_json(403, {
                    "error": "peer:blocked",
                    "message": ("This request did not come from a paired "
                                "desk: " + verdict.reason)})
                return
            self._peer_pair()
            return
        self._send_json(405, {
            "error": "peer:read-only",
            "message": "The peer surface serves reads and one pairing "
                       "path; nothing else changes anything here."})

    def _peer_pair(self) -> None:
        """Another desk submits a pairing code plus its own identity."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._send_json(503, {"error": "peers:unavailable",
                                  "message": "The peer store is not "
                                             "available on this desk."})
            return
        body = self._read_json_body() or {}
        code = str(body.get("code", "")).strip()
        peer_id = str(body.get("peer_id", "")).strip()
        name = str(body.get("name", "")).strip()
        host = str(body.get("host", "")).strip()
        port = body.get("port")
        if not code or not peer_id or not name or not host \
                or not isinstance(port, int):
            self._send_json(400, {
                "error": "pairing:bad-request",
                "message": 'expected {"code", "peer_id", "name", "host",'
                           ' "port"}'})
            return
        try:
            store.exchange_pairing_code(
                code, peer_id=peer_id, name=name,
                base_url=f"{host}:{port}")
        except PeerError as exc:
            self._send_json(403, {"error": exc.code, "message": str(exc)})
            return
        desk = store.desk()
        self._audit("peer.paired", target=peer_id,
                    detail=f"{name} at {host}:{port} redeemed a pairing code")
        self._send_json(200, {"ok": True, "app": "agent-desk",
                              "peer_id": desk["peer_id"],
                              "name": desk["name"]})

    def _peer_shared_plugins(self) -> list[dict]:
        """The shared-plugin list computed live from the runtime: ids the
        user marked shared, installed, with the active version and its
        digest. A shared id that is no longer installed is honestly
        absent, not invented."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if store is None or plugins is None:
            return []
        out = []
        for plugin_id in sorted(store.shared_ids()):
            try:
                record = plugins.record(plugin_id)
            except PluginError:
                continue
            if record.get("state") == "uninstalled" or not record.get("versions"):
                continue
            out.append({
                "id": plugin_id,
                "name": str(record.get("name", plugin_id)),
                "version": str(record.get("active_version", "")),
                "sha256": str(record.get("sha256", "")),
            })
        return out

    def _peer_info_payload(self) -> dict:
        """What this desk tells a paired peer: its identity and the plugins it shares.

        A missing store still yields the same shape with an empty identity, so the
        guard, not the payload, is what refuses an unpaired reader.
        """
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        desk = store.desk() if store is not None else {"peer_id": "",
                                                       "name": ""}
        return {"ok": True, "app": "agent-desk",
                "peer_id": desk["peer_id"], "name": desk["name"],
                "plugins": self._peer_shared_plugins()}

    def _peer_plugin_record(self, plugin_id: str) -> dict | None:
        """The shared, installed record for one plugin id, or None."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        if store is None or plugins is None:
            return None
        if plugin_id not in store.shared_ids():
            return None
        try:
            record = plugins.record(plugin_id)
        except PluginError:
            return None
        if record.get("state") == "uninstalled" or not record.get("versions"):
            return None
        return record

    def _peer_serve_manifest(self, plugin_id: str) -> None:
        """Serve one shared plugin's manifest.json.

        An unknown plugin and a manifest that cannot be read answer the same 404,
        because from the other desk both mean there is nothing to install; a successful
        read is audited as peer.read.
        """
        record = self._peer_plugin_record(plugin_id)
        if record is None:
            self._send_json(404, {"error": "peer:unknown-plugin",
                                  "message": f"{plugin_id} is not a shared "
                                             "plugin on this desk."})
            return
        manifest_path = _active_version_dir(record) / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._send_json(404, {"error": "peer:unknown-plugin",
                                  "message": f"{plugin_id}'s manifest could "
                                             "not be read."})
            return
        self._audit("peer.read", target=plugin_id, detail="manifest")
        self._send_json(200, manifest)

    def _peer_serve_bundle(self, plugin_id: str) -> None:
        """Zip one shared plugin's active version and serve it.

        The archive is built in memory from that version directory, with entry names
        relative to it, so the other desk can install exactly the files this desk holds.
        An unknown plugin is a 404 and the transfer is audited as peer.read.
        """
        record = self._peer_plugin_record(plugin_id)
        if record is None:
            self._send_json(404, {"error": "peer:unknown-plugin",
                                  "message": f"{plugin_id} is not a shared "
                                             "plugin on this desk."})
            return
        version_dir = _active_version_dir(record)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for file in sorted(version_dir.rglob("*")):
                if file.is_file():
                    archive.write(file,
                                  file.relative_to(version_dir).as_posix())
        self._audit("peer.read", target=plugin_id, detail="bundle")
        self._send_bytes(200, buffer.getvalue(), "application/zip")

    # -- the peers page and its flows ---------------------------------------

    def _send_peers_page(self, notice: str = "") -> None:
        """Render the peers page, starting discovery first if it never started.

        Discovery is lazy by design: a desk that never opens this page announces
        nothing, so the page rather than the constructor is where announcing begins.
        """
        self.server.ensure_peer_discovery()  # type: ignore[attr-defined]
        page = render_peers_page(
            self._peers_catalog(), agentdesk.__version__, notice=notice,
            inbox_count=self._inbox_waiting_count())
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _peers_catalog(self) -> dict:
        """Everything the peers page and /api/peers show, as data: this
        desk, its live pairing code, discovered desks, and paired peers
        with their shared plugins and the honest reachability state."""
        self.server.ensure_peer_discovery()  # type: ignore[attr-defined]
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            return {"ok": False, "error": "peers:unavailable",
                    "message": "The peer store is not available."}
        plugins: PluginRuntime | None = self.server.plugins  # type: ignore[attr-defined]
        code = store.active_pairing_code()
        discovery = self.server.peer_discovery  # type: ignore[attr-defined]
        subscriptions = {}
        for sub in store.subscriptions():
            subscriptions.setdefault(sub["peer_id"], []).append(sub)
        paired = []
        for peer in store.peers():
            peer_id = peer["peer_id"]
            plugin_rows = []
            for sub in subscriptions.get(peer_id, []):
                record = None
                if plugins is not None:
                    try:
                        record = plugins.record(sub["plugin_id"])
                    except PluginError:
                        record = None
                installed_here = bool(
                    record is not None
                    and record.get("state") != "uninstalled"
                    and record.get("versions"))
                installed_version = (str(record.get("active_version", ""))
                                     if installed_here else None)
                local_sha = (str(record.get("sha256", ""))
                             if installed_here else "")
                plugin_rows.append({
                    "id": sub["plugin_id"],
                    "version": sub["seen_version"],
                    "sha256": sub["seen_sha256"],
                    "installed_here": installed_here,
                    "installed_version": installed_version,
                    # update-available only when the publisher's version
                    # or digest truly differs from what runs here
                    "update_available": bool(
                        installed_here
                        and (installed_version != sub["seen_version"]
                             or local_sha != sub["seen_sha256"])),
                })
            paired.append({
                "peer_id": peer_id,
                "name": peer["name"],
                "base_url": peer["base_url"],
                "state": store.peer_state(peer_id),
                "plugins": plugin_rows,
            })
        return {
            "ok": True,
            "desk": store.desk(),
            "pairingCode": {"code": code["code"],
                            "expires_at": code["expires_at"]}
            if code else None,
            "discovered": discovery.discovered() if discovery else [],
            "discovery_running": bool(discovery and discovery.running()),
            "paired": paired,
        }

    def _peers_redirect(self, message: str) -> None:
        """Send the browser back to the peers page carrying a notice.

        Every peer action posted as a form answers this way, so a client without
        JavaScript sees the outcome as text on the page it came from.
        """
        self._send_redirect(f"/peers?notice={quote(message)}")

    def _peers_refuse(self, code: str, message: str,
                      status: int = 409) -> None:
        """The peers page's own refusals: forms get the notice line,
        JSON callers get the named error."""
        self._respond_form_or_json(f"/peers?notice={quote(message)}",
                                   {"error": code, "message": message}, status)

    def _peers_code_generate(self) -> None:
        """Mint a single-use pairing code and tell the user what it is.

        The store gives it a ten-minute life and one redemption; a form post redirects
        with the code in the notice, while a fetch gets the store's own JSON. Both are
        audited, because minting a code is the moment this desk offers another desk
        access.
        """
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        out = store.create_pairing_code()
        self._audit("peer.code", target="pairing-code",
                    detail="a single-use pairing code was generated")
        self._respond_form_or_json(
            "/peers?notice=" + quote(
                f"Pairing code {out['code']}. Another desk can redeem it "
                "for the next ten minutes; it works once."), out)

    def _peers_pair(self) -> None:
        """This desk types the other desk's code: submit it, then pin the
        peer identity and the shared channel token."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        body = self._read_json_body() or {}
        typed_address = str(body.get("address", "")).strip()
        code = str(body.get("code", "")).strip()
        if not typed_address or not code:
            self._peers_refuse(
                "peer:bad-request",
                "Type both the other desk's address (host:port) and its "
                "pairing code.", 400)
            return
        address = _normalize_peer_address(typed_address)
        if address is None:
            self._peers_refuse(
                "peer:bad-address",
                f"{typed_address!r} is not a host:port address.", 400)
            return
        desk = store.desk()
        try:
            answer = PeerClient().pair(
                address, code=code, my_peer_id=desk["peer_id"],
                my_name=desk["name"], my_host="127.0.0.1",
                my_port=self.server.port)  # type: ignore[attr-defined]
        except PeerClientError as exc:
            self._peers_refuse(exc.code, str(exc))
            return
        store.add_peer(peer_id=str(answer.get("peer_id", "")),
                       name=str(answer.get("name", "peer")),
                       base_url=address, token=derive_token(code))
        self._audit("peer.pair", target=str(answer.get("peer_id", "")),
                    detail=f"paired with {answer.get('name', '')} at {address}")
        # One honest refresh right away, so the page shows the peer's
        # shares (or the cause it could not be read).
        self._refresh_one_peer(str(answer.get("peer_id", "")))
        self._respond_form_or_json(
            "/peers?notice=" + quote(
                f"Paired with {answer.get('name', 'the other desk')}."),
            {"ok": True, "peer_id": answer.get("peer_id"),
             "name": answer.get("name")})

    def _refresh_one_peer(self, peer_id: str) -> bool:
        """Fetch one peer's shared-plugin list into the subscription
        snapshot; record the honest outcome either way."""
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        peer = store.peer(peer_id) if store is not None else None
        if peer is None:
            return False
        token = store.channel_token(peer_id) if store is not None else None
        try:
            info = PeerClient().info(peer["base_url"], token=token or "")
        except PeerClientError as exc:
            store.record_peer_refresh(peer_id, ok=False, cause=str(exc))
            return False
        for plugin in info.get("plugins", []):
            if not isinstance(plugin, dict):
                continue
            store.record_seen(str(plugin.get("id", "")), peer_id,
                              str(plugin.get("version", "")),
                              str(plugin.get("sha256", "")))
        store.record_peer_refresh(peer_id, ok=True, cause="")
        return True

    def _peers_refresh(self) -> None:
        """Ask every paired desk for its current listing, then report how many answered.

        Each peer is refreshed on its own, so one unreachable desk does not stop the
        rest; the notice counts reached against total and, when any failed, points at
        the per-peer causes the page lists.
        """
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        reached = 0
        peers = store.peers()
        for peer in peers:
            if self._refresh_one_peer(peer["peer_id"]):
                reached += 1
        message = (f"Refreshed {reached} of {len(peers)} paired desks.")
        if reached < len(peers):
            message += " The unreachable ones list their cause below."
        self._peers_redirect(message)

    def _peers_install(self) -> None:
        """Install one shared plugin from a paired peer: download the
        bundle, recompute the tree digest against the publisher's, run
        the shared validator through the runtime, and record the peer
        as the source."""
        store, plugins, peer, plugin_id, names_ok = self._peers_flow_args()
        if not names_ok:
            return  # the refusal already went out
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        if peer is None:
            self._peers_refuse("peer:unknown-peer",
                               "No paired desk matches that request.")
            return
        if plugins is None:
            self._peers_refuse("plugins:unavailable",
                               "No plugin runtime is configured.")
            return
        if not plugin_id:
            self._peers_refuse("peer:bad-request",
                               "Which plugin, from which desk?", 400)
            return
        try:
            existing = plugins.record(plugin_id)
            already = bool(existing.get("versions")
                           and existing.get("state") != "uninstalled")
        except PluginError:
            already = False
        if already:
            self._peers_refuse(
                "peer:already-installed",
                f"{plugin_id} is already installed here; use Update to "
                "move to the peer's version.")
            return
        with tempfile.TemporaryDirectory(prefix="agentdesk-peer-") as tmp:
            staged = self._peer_stage(plugins, peer, plugin_id, Path(tmp))
            if staged is None:
                return  # the refusal already went out
            try:
                result = plugins.install(staged["dir"],
                                         source=f"peer:{peer['name']}")
            except PluginError as exc:
                self._audit("peer.install", target=plugin_id,
                            status="error",
                            detail=f"refused by the shared validator: "
                                   f"{exc.code}")
                self._peers_refuse(exc.code, str(exc), exc.status)
                return
        store.record_seen(plugin_id, peer["peer_id"], staged["version"],
                          staged["sha256"])
        store.set_installed(plugin_id, peer["peer_id"], result["version"])
        self._audit("peer.install", target=plugin_id,
                    detail=f"from {peer['name']} v{result['version']} "
                           f"digest {staged['sha256'][:12]} verified")
        self._respond_form_or_json(
            "/peers?notice=" + quote(
                f"Installed {plugin_id} v{result['version']} from "
                f"{peer['name']}."), result)

    def _peers_update(self) -> None:
        """One click to the publisher's newer version: same staging and
        verification, then the runtime's own update path (a widened
        permission set still holds for consent)."""
        store, plugins, peer, plugin_id, names_ok = self._peers_flow_args()
        if not names_ok:
            return  # the refusal already went out
        if store is None:
            self._peers_refuse("peers:unavailable",
                               "The peer store is not available.")
            return
        if peer is None:
            self._peers_refuse("peer:unknown-peer",
                               "No paired desk matches that request.")
            return
        if plugins is None:
            self._peers_refuse("plugins:unavailable",
                               "No plugin runtime is configured.")
            return
        if not plugin_id:
            self._peers_refuse("peer:bad-request",
                               "Which plugin, from which desk?", 400)
            return
        with tempfile.TemporaryDirectory(prefix="agentdesk-peer-") as tmp:
            staged = self._peer_stage(plugins, peer, plugin_id, Path(tmp))
            if staged is None:
                return
            zip_path = Path(tmp) / f"{plugin_id}.zip"
            zip_path.write_bytes(staged["bundle"])
            try:
                result = plugins.update(plugin_id, zip_path)
            except PluginError as exc:
                self._audit("peer.update", target=plugin_id,
                            status="error",
                            detail=f"refused: {exc.code}")
                self._peers_refuse(exc.code, str(exc), exc.status)
                return
        if isinstance(result, dict) and result.get("status") == "pending-consent":
            result = self._hold_update_for_consent(plugins, plugin_id, result)
        if isinstance(result, dict) and result.get("applied"):
            store.record_seen(plugin_id, peer["peer_id"], staged["version"],
                              staged["sha256"])
            store.set_installed(plugin_id, peer["peer_id"],
                                str(result.get("version", "")))
        self._audit("peer.update", target=plugin_id,
                    detail=f"from {peer['name']} to v{staged['version']}")
        if self._is_form_submit():
            if isinstance(result, dict) and result.get("applied"):
                self._peers_redirect(
                    f"Updated {plugin_id} to v{result.get('version', '')} "
                    f"from {peer['name']}.")
            else:
                self._peers_redirect(
                    f"The update to {staged['version']} waits for your OK: "
                    "it asks for more access. Decide it on the inbox.")
            return
        self._send_json(200, result if isinstance(result, dict) else {})

    def _peers_flow_args(self):
        """(store, plugins, peer, plugin_id, names_ok) for the install
        and update flows. ids that are not safe names are refused here,
        before either can name a file (a planted ../id would otherwise
        escape the staging dir) or a store row."""
        body = self._read_json_body() or {}
        peer_id = str(body.get("peer_id", "")).strip()
        plugin_id = str(body.get("plugin_id", "")).strip()
        names_ok = self._peer_flow_names_ok(peer_id, plugin_id)
        store: PeerStore | None = self.server.peer_store  # type: ignore[attr-defined]
        peer = store.peer(peer_id) if store is not None and names_ok else None
        return (store, self.server.plugins, peer, plugin_id, names_ok)  # type: ignore[attr-defined]

    def _peer_flow_names_ok(self, peer_id: str, plugin_id: str) -> bool:
        """Whether the peer and plugin ids of a flow are safe to place in a path.

        An unsafe name is refused with a 400 and a quoted, shortened excerpt rather than
        silently sanitised, so the answer tells the truth about what was rejected. An
        empty name passes: whether one is required is the next check's business, not
        this one's.
        """
        for name, what in ((peer_id, "peer id"), (plugin_id, "plugin id")):
            if name and not _PEER_SAFE_NAME.match(name):
                self._peers_refuse(
                    "peer:unsafe-name",
                    f"The {what} is not a safe name: {name[:40]!r}.", 400)
                return False
        return True

    def _peer_stage(self, plugins: PluginRuntime, peer: dict,
                    plugin_id: str, tmp: Path) -> dict | None:
        """Download, verify and stage one plugin from a peer. Returns the
        staged {dir, bundle, version, sha256}, or None after sending the
        named refusal."""
        token = self.server.peer_store.channel_token(peer["peer_id"])  # type: ignore[attr-defined]
        client = PeerClient()
        try:
            info = client.info(peer["base_url"], token=token or "")
            bundle = client.bundle(peer["base_url"], token=token or "",
                                   plugin_id=plugin_id)
        except PeerClientError as exc:
            self._peers_refuse(exc.code, str(exc))
            return None
        offered = next((p for p in info.get("plugins", [])
                        if isinstance(p, dict)
                        and str(p.get("id", "")) == plugin_id), None)
        if offered is None:
            self._peers_refuse(
                "peer:plugin-not-shared",
                f"{peer['name']} does not share {plugin_id}.")
            return None
        staged_dir = tmp / "plugin"
        staged_dir.mkdir()
        try:
            extract_bundle(bundle, staged_dir)
        except PeerClientError as exc:
            self._peers_refuse(exc.code, str(exc))
            return None
        digest = tree_digest(staged_dir)
        expected = str(offered.get("sha256", ""))
        if not expected:
            # No announced digest means nothing to verify against: a
            # refusal, never a silent skip that the audit row would
            # then call verified.
            self._audit("peer.install", target=plugin_id, status="error",
                        detail=f"{peer['name']} publishes no digest for "
                               f"{plugin_id}; refused")
            self._peers_refuse(
                "peer:digest-unknown",
                f"{peer['name']} publishes no digest for {plugin_id}, so "
                "this desk cannot verify the bundle against anything. "
                "Nothing was installed.")
            return None
        if digest != expected:
            self._audit("peer.install", target=plugin_id, status="error",
                        detail=f"bundle digest {digest[:12]} does not match "
                               f"the published {expected[:12]}; refused")
            self._peers_refuse(
                "peer:digest-mismatch",
                f"The bundle from {peer['name']} does not match the "
                f"digest it publishes ({digest[:12]} vs {expected[:12]}). "
                "Nothing was installed.")
            return None
        return {"dir": staged_dir, "bundle": bundle,
                "version": str(offered.get("version", "")),
                "sha256": digest}
