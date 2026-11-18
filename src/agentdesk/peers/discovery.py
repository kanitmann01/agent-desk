"""UDP discovery: each desk announces itself and remembers the others.

An announcer thread holds one reusable broadcast socket and sends a
small JSON identity packet every few seconds to the loopback address
and to the broadcast address of every interface it can detect. A
listener thread binds the shared announce port (SO_REUSEADDR, plus
SO_REUSEPORT where the platform has it) so two desks on one machine
both receive broadcasts sent to that port; unicast cannot do that.
Discovered entries carry a last-seen stamp and expire after a TTL, so
the peers page never shows a desk that stopped announcing.

Honest limits, stated here because the page states them too: the HTTP
server binds loopback only, so discovery works fully between desks on
one machine; a desk elsewhere on the LAN can be seen in the discovered
list, but connecting to it will be refused (and will be reported as
unreachable with its cause) until the bind policy changes. Nothing
here opens an inbound socket beyond the listener on the announce port.
"""

import json
import logging
import socket
import threading
import time
from collections.abc import Callable

LOG = logging.getLogger("agentdesk.peers")

APP_NAME = "agent-desk"
PREFERRED_ANNOUNCE_PORT = 8799
DEFAULT_INTERVAL_S = 3.0
DEFAULT_TTL_S = 180.0  # a few minutes of silence and the entry is gone
ANNOUNCE_MAX_BYTES = 4096

# This machine's own addresses, resolved once and cached: a packet whose
# source is one of them came from a desk on this machine (connectable,
# because the servers bind loopback); anything else came from another
# machine, which the pair form must never pre-fill with our loopback.
_LOCAL_ADDRESSES: set[str] | None = None


def _local_addresses() -> set[str]:
    """Return this machine's own addresses, resolved once and then cached.

    Loopback is always present; when the hostname does not resolve it is the
    whole answer, because the servers bind loopback either way.
    """
    global _LOCAL_ADDRESSES
    if _LOCAL_ADDRESSES is None:
        addresses = {"127.0.0.1", "localhost", "::1"}
        try:
            _host, _alias, ips = socket.gethostbyname_ex(
                socket.gethostname())
            addresses.update(ips)
        except OSError:
            pass  # hostname unresolvable: loopback is still the truth
        _LOCAL_ADDRESSES = addresses
    return _LOCAL_ADDRESSES


def _broadcast_targets() -> list[str]:
    """Where to send: the loopback, each interface's subnet broadcast,
    and the limited broadcast address. Best effort on every platform:
    a target that cannot be addressed or sent to is skipped, never an
    error."""
    targets = ["127.0.0.1", "255.255.255.255"]
    try:
        _host, _alias, addresses = socket.gethostbyname_ex(
            socket.gethostname())
    except OSError:
        addresses = []
    for address in addresses:
        prefix = address.rsplit(".", 1)[0]
        targets.append(f"{prefix}.255")
    # de-duplicate, keep order
    seen: set[str] = set()
    unique = []
    for target in targets:
        if target not in seen:
            seen.add(target)
            unique.append(target)
    return unique


class DiscoveryService:
    """One desk's presence on the announce port."""

    def __init__(self, peer_id: str, name: str, http_port: int, *,
                 announce_port: int = PREFERRED_ANNOUNCE_PORT,
                 interval: float = DEFAULT_INTERVAL_S,
                 ttl: float = DEFAULT_TTL_S,
                 clock: Callable[[], float] = time.monotonic,
                 targets: list[str] | None = None) -> None:
        """Hold the identity this desk announces; nothing is opened or started.

        Targets default to the broadcast addresses detected on this machine;
        start() opens the sockets and the two threads.
        """
        self.peer_id = peer_id
        self.name = name
        self.http_port = http_port
        self.announce_port = announce_port
        self.interval = interval
        self.ttl = ttl
        self.clock = clock
        self.targets = targets if targets is not None else _broadcast_targets()
        self._peers: dict[str, dict] = {}
        self._peers_lock = threading.Lock()
        self._stop = threading.Event()
        self._listener_thread: threading.Thread | None = None
        self._announcer_thread: threading.Thread | None = None
        self._send_socket: socket.socket | None = None
        self._listen_socket: socket.socket | None = None

    # -- the wire shape -------------------------------------------------

    def announce_payload(self) -> dict:
        """The small JSON identity packet. The host is loopback because
        that is the only address the HTTP server answers on."""
        return {
            "app": APP_NAME,
            "peer_id": self.peer_id,
            "name": self.name,
            "host": "127.0.0.1",
            "port": self.http_port,
            "pairing_required": True,
        }

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Listener first (so a fast peer is heard), then the announcer."""
        if self._listener_thread is not None:
            return
        self._listen_socket = self._bind_listener()
        if self._listen_socket is not None:
            self._listener_thread = threading.Thread(
                target=self._listen_loop, name="peer-discovery-listener",
                daemon=True)
            self._listener_thread.start()
        self._announcer_thread = threading.Thread(
            target=self._announce_loop, name="peer-discovery-announcer",
            daemon=True)
        self._announcer_thread.start()

    def stop(self) -> None:
        """Signal both loops to stop and close the sockets.

        The threads are not joined: each ends on its next socket error or interval.
        Calling this twice is harmless.
        """
        self._stop.set()
        for sock in (self._listen_socket, self._send_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._listen_socket = None
        self._send_socket = None

    def running(self) -> bool:
        """Return True while an announcer thread exists and stop() has not run."""
        return self._announcer_thread is not None and not self._stop.is_set()

    # -- sockets ------------------------------------------------------------

    def _bind_listener(self) -> socket.socket | None:
        """The shared announce port, or None when it cannot be had (the
        desk still announces; it just cannot hear, which the peers page
        shows as an empty discovered list, never as a crash)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, "SO_REUSEADDR"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass  # the platform reserves it or lacks the rights
            sock.bind(("", self.announce_port))
            sock.settimeout(0.5)
            return sock
        except OSError:
            LOG.exception("peer discovery listener unavailable")
            sock.close()
            return None

    def _sender(self) -> socket.socket | None:
        """One reusable broadcast socket, created on first use."""
        if self._send_socket is not None:
            return self._send_socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, "SO_BROADCAST"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            LOG.exception("SO_BROADCAST unavailable; announcing to loopback")
        self._send_socket = sock
        return sock

    # -- loops -----------------------------------------------------------

    def _announce_loop(self) -> None:
        """Announce once per interval until stop() is signalled."""
        while not self._stop.is_set():
            self.announce_once()
            self._stop.wait(self.interval)

    def announce_once(self) -> int:
        """One identity packet to every target. Returns how many targets
        accepted it; a refused target is skipped, not an error."""
        payload = json.dumps(self.announce_payload()).encode("utf-8")
        sock = self._sender()
        if sock is None:
            return 0
        sent = 0
        for target in self.targets:
            try:
                sock.sendto(payload, (target, self.announce_port))
                sent += 1
            except OSError:
                continue  # an interface without broadcast rights, or gone
        return sent

    def _listen_loop(self) -> None:
        """Record incoming announcements until the socket closes or stop() runs.

        A poll timeout only retries, and a packet that is not JSON is dropped
        without a word.
        """
        sock = self._listen_socket
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(ANNOUNCE_MAX_BYTES)
            except socket.timeout:
                continue
            except OSError:
                break  # the socket closed: stop() or shutdown
            try:
                payload = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            self.record_announcement(payload, source_addr=addr[0])

    # -- the discovered list ----------------------------------------------

    def record_announcement(self, payload: dict, source_addr: str) -> None:
        """One announcement into the discovered list, or ignored: only
        this app's packets, only other desks, only complete identities.

        Every desk announces host 127.0.0.1 (the only address its server
        answers on), so the packet's source address is kept separately:
        a source on this machine marks the entry connectable (the pair
        form may pre-fill 127.0.0.1), anything else is a desk on another
        machine, listed with its real source and not connectable from
        here until the bind policy changes.
        """
        if not isinstance(payload, dict):
            return
        if payload.get("app") != APP_NAME:
            return
        peer_id = payload.get("peer_id")
        if not isinstance(peer_id, str) or not peer_id or peer_id == self.peer_id:
            return
        port = payload.get("port")
        if not isinstance(port, int) or not (0 < port < 65536):
            return
        now = self.clock()
        source = str(source_addr or "")
        entry = {
            "peer_id": peer_id,
            "name": str(payload.get("name") or peer_id),
            "host": str(payload.get("host") or "127.0.0.1"),
            "source": source,
            "connectable": source in _local_addresses(),
            "port": port,
            "pairing_required": bool(payload.get("pairing_required", True)),
            "last_seen": now,
        }
        with self._peers_lock:
            self._peers[peer_id] = entry

    def discovered(self) -> list[dict]:
        """Live entries only: anything past the TTL is dropped for good."""
        now = self.clock()
        with self._peers_lock:
            expired = [peer_id for peer_id, entry in self._peers.items()
                       if now - entry["last_seen"] > self.ttl]
            for peer_id in expired:
                del self._peers[peer_id]
            return sorted(self._peers.values(),
                          key=lambda entry: entry["name"])
