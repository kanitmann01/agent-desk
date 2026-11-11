"""Guard unit tests: the Origin/Host matrix, no server needed.

These are the rules research A9.2 rule 8 pins down. The HTTP tests then
prove the guard is actually wired in front of every route.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.server.guard import allowed_hosts, allowed_origins, check_request

PORT = 8765


def test_allowed_hosts_are_loopback_only_with_port():
    assert allowed_hosts(PORT) == frozenset({"127.0.0.1:8765", "localhost:8765"})


def test_allowed_origins_are_plain_http_loopback_only():
    assert allowed_origins(PORT) == frozenset(
        {"http://127.0.0.1:8765", "http://localhost:8765"}
    )


def test_missing_host_is_rejected():
    assert not check_request(None, None, PORT).allowed


def test_foreign_host_is_rejected():
    verdict = check_request("evil.example:80", None, PORT)
    assert not verdict.allowed
    assert "Host" in verdict.reason


def test_rebound_host_is_rejected():
    # The DNS-rebinding shape: an attacker hostname resolving to 127.0.0.1.
    assert not check_request("attacker.example:8765", None, PORT).allowed


def test_loopback_hosts_are_accepted():
    assert check_request(f"127.0.0.1:{PORT}", None, PORT).allowed
    assert check_request(f"localhost:{PORT}", None, PORT).allowed


def test_host_match_is_case_insensitive():
    assert check_request("LOCALHOST:8765", None, PORT).allowed


def test_missing_origin_is_allowed():
    # Plain navigations and non-browser local tools send no Origin; only a
    # wrong Origin is an attack signal.
    assert check_request(f"127.0.0.1:{PORT}", None, PORT).allowed


def test_allowed_origin_is_accepted():
    assert check_request(f"127.0.0.1:{PORT}", f"http://127.0.0.1:{PORT}", PORT).allowed
    assert check_request(f"127.0.0.1:{PORT}", f"http://localhost:{PORT}", PORT).allowed


def test_foreign_origin_is_rejected():
    verdict = check_request(f"127.0.0.1:{PORT}", "https://evil.example", PORT)
    assert not verdict.allowed
    assert "Origin" in verdict.reason


def test_https_self_origin_is_rejected():
    # Same host, wrong scheme: the dashboard is plain-http loopback, and an
    # https Origin is never one of ours.
    assert not check_request(f"127.0.0.1:{PORT}", f"https://127.0.0.1:{PORT}", PORT).allowed


def test_bad_origin_fails_even_with_a_good_host():
    assert not check_request(f"127.0.0.1:{PORT}", "http://evil.example:80", PORT).allowed
