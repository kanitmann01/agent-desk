"""The peer HTTP client: pair with, read from, download from a desk.

Everything the client side of sharing needs, over stdlib http.client:
submit a pairing code (with this desk's own announce identity), read a
paired peer's shared-plugin info, fetch one manifest, fetch one bundle.
The channel token travels as an Authorization: Bearer header (the one
transport the peer endpoint accepts; there is no query-string form).

Every failure is a named PeerClientError: "peer:unreachable" with the
socket cause, the server's own error name for refusals (a wrong pairing
code, a missing token), and "peer:bad-response" when the answer is not
the JSON the surface promises. Nothing is retried and nothing is
invented: one attempt, one honest answer.
"""

import http.client
import json
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

from agentdesk.plugins.runtime import PluginError, extract_plugin_zip

DEFAULT_TIMEOUT_S = 5.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024  # bundles are small; refuse huge ones


class PeerClientError(Exception):
    """A named client-side refusal: ``code`` is the stable vocabulary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def extract_bundle(bundle: bytes, destination: Path) -> None:
    """Extract a downloaded bundle into ``destination`` through the one
    extractor the app uses for plugin zips (the runtime's, with its
    containment rules); the peer-specific naming happens here, so a
    bundle that cannot be read or would escape the staging folder is
    ``peer:bad-bundle``."""
    destination = Path(destination)
    with tempfile.TemporaryDirectory(prefix="agentdesk-bundle-") as tmp:
        zip_path = Path(tmp) / "bundle.zip"
        zip_path.write_bytes(bundle)
        try:
            extract_plugin_zip(zip_path, destination)
        except zipfile.BadZipFile as exc:
            raise PeerClientError(
                "peer:bad-bundle",
                f"The downloaded bundle is not a readable zip: {exc}") from exc
        except PluginError as exc:
            raise PeerClientError(
                "peer:bad-bundle", str(exc)) from exc


class PeerClient:
    """One-shot requests; no connection state worth keeping."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self.timeout = timeout

    # -- request plumbing ------------------------------------------------

    def _request(self, base_url: str, method: str, path: str, *,
                 token: str | None = None, body: bytes | None = None) -> tuple[int, bytes]:
        host, _, port_text = base_url.partition(":")
        try:
            port = int(port_text) if port_text else 80
        except ValueError:
            raise PeerClientError(
                "peer:bad-address",
                f"{base_url!r} is not a host:port address") from None
        headers = {"Host": base_url}  # the guard expects the real pair
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        try:
            conn = http.client.HTTPConnection(host, port, timeout=self.timeout)
            try:
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            finally:
                conn.close()
        except (OSError, http.client.HTTPException) as exc:
            raise PeerClientError(
                "peer:unreachable",
                f"The desk at {base_url} could not be reached: {exc}") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise PeerClientError(
                "peer:too-large",
                f"The answer from {base_url} is larger than this client "
                "will read.")
        return response.status, payload

    def _json(self, base_url: str, method: str, path: str, *,
              token: str | None = None, body: bytes | None = None) -> dict:
        status, payload = self._request(base_url, method, path,
                                        token=token, body=body)
        if status != 200:
            raise PeerClientError(*_error_name(status, payload, base_url))
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise PeerClientError(
                "peer:bad-response",
                f"The desk at {base_url} answered something this client "
                f"cannot read: {exc}") from exc
        if not isinstance(parsed, dict):
            raise PeerClientError(
                "peer:bad-response",
                f"The desk at {base_url} did not answer an object.")
        return parsed

    # -- the peer surface --------------------------------------------------

    def pair(self, base_url: str, *, code: str, my_peer_id: str,
             my_name: str, my_host: str, my_port: int) -> dict:
        """Submit a pairing code to the desk that showed it."""
        body = json.dumps({
            "code": code,
            "peer_id": my_peer_id,
            "name": my_name,
            "host": my_host,
            "port": my_port,
        }).encode("utf-8")
        return self._json(base_url, "POST", "/peer/pair", body=body)

    def info(self, base_url: str, token: str) -> dict:
        """The desk's name, id, and shared plugins with digests."""
        return self._json(base_url, "GET", "/peer/info", token=token)

    def manifest(self, base_url: str, token: str, plugin_id: str) -> dict:
        """One shared plugin's manifest."""
        return self._json(base_url, "GET",
                          f"/peer/plugins/{quote(plugin_id, safe='')}/manifest",
                          token=token)

    def bundle(self, base_url: str, token: str, plugin_id: str) -> bytes:
        """One shared plugin's bundle as zip bytes."""
        status, payload = self._request(
            base_url, "GET",
            f"/peer/plugins/{quote(plugin_id, safe='')}/bundle",
            token=token)
        if status != 200:
            raise PeerClientError(*_error_name(status, payload, base_url))
        return payload


def _error_name(status: int, payload: bytes, base_url: str) -> tuple[str, str]:
    """The server's own refusal when it sent one; a plain statement
    otherwise. Never an empty message."""
    try:
        parsed = json.loads(payload.decode("utf-8"))
        if isinstance(parsed, dict) and parsed.get("error"):
            return str(parsed["error"]), str(
                parsed.get("message") or parsed["error"])
    except (ValueError, UnicodeDecodeError):
        pass
    return "peer:http-error", f"The desk at {base_url} answered {status}."
