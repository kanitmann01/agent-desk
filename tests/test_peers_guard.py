"""The guard's peer admission rule (ticket #67).

Peer paths are the one surface a browser session cannot cover: another
desk holds a channel token, not a cookie. The guard still applies to
them (research A9.2 rule 8: no second entry path), with one measured
extension: a request that carries a valid peer token is admitted even
when its Host names a LAN address, because the token answers both
concerns the Host check exists for (rebinding and cross-site riding)
for these read-only paths. Without a token the standard rules answer,
unchanged. The pairing path has no token (the code is the gate), so it
always takes the standard check.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.server.guard import check_peer_request, check_request  # noqa: E402

PORT = 8765


def test_valid_peer_token_admits_a_lan_host():
    verdict = check_peer_request("192.168.1.20:8765", None, PORT,
                                 token_ok=True)
    assert verdict.allowed


def test_valid_peer_token_admits_the_loopback_too():
    verdict = check_peer_request(f"127.0.0.1:{PORT}", None, PORT,
                                 token_ok=True)
    assert verdict.allowed


def test_no_token_keeps_every_standard_rule():
    # a foreign host without a token is refused with the guard's reason
    verdict = check_peer_request("evil.example:80", None, PORT, token_ok=False)
    assert not verdict.allowed
    assert "Host" in verdict.reason
    # exactly what check_request would have said, word for word
    assert verdict.reason == check_request("evil.example:80", None, PORT).reason


def test_no_token_missing_host_is_refused():
    assert not check_peer_request(None, None, PORT, token_ok=False).allowed


def test_wrong_origin_with_a_token_is_admitted_on_peer_paths():
    # the token is the authority on peer paths; a paired peer's client
    # never sends Origin, and a browser cannot forge one
    verdict = check_peer_request(f"127.0.0.1:{PORT}",
                                 "http://evil.example", PORT, token_ok=True)
    assert verdict.allowed


def test_standard_paths_still_take_the_plain_check():
    # the extension is scoped: without a token nothing changes anywhere
    assert check_peer_request(f"localhost:{PORT}", None, PORT,
                              token_ok=False).allowed
    assert not check_peer_request("attacker.example:8765", None, PORT,
                                  token_ok=False).allowed
