"""Origin and Host validation applied to every request.

A localhost app is reachable by any page the work browser has open: a
cross-site fetch would otherwise ride the user's session cookie, and a
DNS-rebinded hostname would let an internet page talk to 127.0.0.1. The
guard closes both (research A9.2 rule 8). Every HTTP and WebSocket request
must pass through check_request; nothing may grow a second entry path.
"""

from dataclasses import dataclass

from agentdesk.server.core import LOOPBACK_HOSTS

# Browsers omit Origin on plain navigations, and non-browser local tools
# omit it too. A missing Origin is therefore not an attack signal; a wrong
# one always is. Host, by contrast, is mandatory on HTTP/1.1.
MISSING = object()


@dataclass(frozen=True)
class GuardVerdict:
    """The guard's answer: allow, or the plain-language reason it did not."""

    allowed: bool
    reason: str = ""


def allowed_hosts(port: int) -> frozenset[str]:
    """Host headers this server answers to, port included."""
    return frozenset(f"{host}:{port}" for host in LOOPBACK_HOSTS)


def allowed_origins(port: int) -> frozenset[str]:
    """Origins this server accepts when a browser declares one."""
    return frozenset(f"http://{host}:{port}" for host in LOOPBACK_HOSTS)


def check_request(
    host_header: str | None,
    origin_header: str | None,
    port: int,
) -> GuardVerdict:
    """Validate Host and Origin for one request against the loopback set.

    Order of answers matters for tests and logs: a bad Host fails first
    (it defeats DNS rebinding), then a bad Origin (it defeats cross-site
    fetches). A missing Origin is allowed, a missing Host is not.
    """
    if not host_header:
        return GuardVerdict(False, "missing Host header")
    if host_header.lower() not in {h.lower() for h in allowed_hosts(port)}:
        return GuardVerdict(False, f"Host not allowed: {host_header}")
    if origin_header is not None and origin_header not in allowed_origins(port):
        return GuardVerdict(False, f"Origin not allowed: {origin_header}")
    return GuardVerdict(True)
