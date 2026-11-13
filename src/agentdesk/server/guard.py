"""Origin and Host validation applied to every request.

A localhost app is reachable by any page the work browser has open: a
cross-site fetch would otherwise ride the user's session cookie, and a
DNS-rebinded hostname would let an internet page talk to 127.0.0.1. The
guard closes both (research A9.2 rule 8). Every HTTP and WebSocket request
must pass through check_request; nothing may grow a second entry path.

The function stays pure: callers resolve the allowed set (loopback, plus
the user-sanctioned extra hosts from Settings) and hand it in, so the
guard itself never reads a store or a clock.

The peer-to-peer surface (issue #67) adds no second path either: its
requests go through check_peer_request, which answers with check_request
plus one measured token-scoped extension, documented there.
"""

from dataclasses import dataclass

from agentdesk.server.core import LOOPBACK_HOSTS

# Browsers omit Origin on plain navigations, and non-browser local tools
# omit it too. A missing Origin is therefore not an attack signal; a wrong
# one always is. Host, by contrast, is mandatory on HTTP/1.1.
MISSING = object()


@dataclass(frozen=True)
class GuardVerdict:
    """The guard's answer: allow, or the plain-language reason it did not.

    ``rejected`` carries the offending Host or Origin value so the
    refusal page can name where the app was opened instead; it is empty
    on allow and on a missing Host header (there is no value to name).
    """

    allowed: bool
    reason: str = ""
    rejected: str = ""


def allowed_hosts(port: int, extra_hosts: frozenset[str] = frozenset()) -> frozenset[str]:
    """Host headers this server answers to, port included.

    ``extra_hosts`` are exact host[:port] entries the user sanctioned in
    Settings (a projected screen, a forwarded port); they are admitted
    as given, lowercased, and change nothing about the loopback set.
    """
    return frozenset(f"{host}:{port}" for host in LOOPBACK_HOSTS) | {
        host.lower() for host in extra_hosts if host
    }


def allowed_origins(port: int, extra_hosts: frozenset[str] = frozenset()) -> frozenset[str]:
    """Origins this server accepts when a browser declares one."""
    return frozenset(f"http://{host}:{port}" for host in LOOPBACK_HOSTS) | {
        f"http://{host.lower()}" for host in extra_hosts if host
    }


def check_request(
    host_header: str | None,
    origin_header: str | None,
    port: int,
    extra_hosts: frozenset[str] = frozenset(),
) -> GuardVerdict:
    """Validate Host and Origin for one request against the loopback set
    plus any extra hosts the caller resolved from Settings.

    Order of answers matters for tests and logs: a bad Host fails first
    (it defeats DNS rebinding), then a bad Origin (it defeats cross-site
    fetches). A missing Origin is allowed, a missing Host is not.

    The opaque origin "null" counts as missing: sandboxed frames and
    some embedded browsers send that literal string on native form
    posts, and like an absent header it carries no origin information
    to check. It is not an attack signal: the session cookie is
    SameSite=Strict, and a cross-site requester cannot present it, so a
    null-origin POST carrying a live session can only come from the
    user's own page in such a browser. Every real origin is still
    checked strictly.
    """
    if not host_header:
        return GuardVerdict(False, "missing Host header")
    if host_header.lower() not in {h.lower() for h in allowed_hosts(port, extra_hosts)}:
        return GuardVerdict(False, f"Host not allowed: {host_header}",
                            rejected=host_header)
    if origin_header is not None and origin_header.lower() != "null" \
            and origin_header not in allowed_origins(port, extra_hosts):
        return GuardVerdict(False, f"Origin not allowed: {origin_header}",
                            rejected=origin_header)
    return GuardVerdict(True)


def check_peer_request(
    host_header: str | None,
    origin_header: str | None,
    port: int,
    token_ok: bool,
) -> GuardVerdict:
    """The same rules, with one measured extension for /peer/ paths.

    Another desk holds a channel token, not a browser session, so the
    Host it sends may name this machine's LAN address rather than the
    loopback. A valid peer token answers both concerns the Host check
    exists for (DNS rebinding and cross-site riding) on these
    read-only paths, so it admits the request where the plain check
    would refuse. Without a token the answer is exactly what
    check_request says, so nothing outside a paired peer changes. The
    pairing path itself sends no token (its code is the gate) and
    therefore always takes the plain check.
    """
    verdict = check_request(host_header, origin_header, port)
    if verdict.allowed:
        return verdict
    if token_ok:
        return GuardVerdict(True)
    return verdict
