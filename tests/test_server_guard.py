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

from nexuusbot.server.guard import allowed_hosts, allowed_origins, check_request

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


# -- the settings-controlled extension (issue #61) -----------------------
#
# extra_allowed_hosts admits exact host[:port] entries the user sanctioned
# in Settings, on top of the loopback set; the default stays loopback-only.


def test_extra_hosts_extend_the_allowed_sets():
    extra = frozenset({"mymachine:8765", "192.168.1.20:8765"})
    assert allowed_hosts(PORT, extra) == frozenset({
        "127.0.0.1:8765", "localhost:8765", "mymachine:8765", "192.168.1.20:8765",
    })
    assert allowed_origins(PORT, extra) == frozenset({
        "http://127.0.0.1:8765", "http://localhost:8765",
        "http://mymachine:8765", "http://192.168.1.20:8765",
    })


def test_check_request_admits_extra_hosts_and_their_origins():
    extra = frozenset({"mymachine:8765"})
    assert check_request("mymachine:8765", None, PORT, extra_hosts=extra).allowed
    assert check_request(
        "127.0.0.1:8765", "http://mymachine:8765", PORT, extra_hosts=extra
    ).allowed


def test_check_request_still_refuses_everything_else_with_extras():
    extra = frozenset({"mymachine:8765"})
    assert not check_request("other.example:8765", None, PORT, extra_hosts=extra).allowed
    # An extra Host does not open the door to foreign Origins.
    assert not check_request(
        "mymachine:8765", "http://evil.example", PORT, extra_hosts=extra
    ).allowed
    # A different port on the same name is a different address.
    assert not check_request("mymachine:9999", None, PORT, extra_hosts=extra).allowed


def test_extra_host_matching_is_case_insensitive():
    # DNS names are case-insensitive; entries are lowered on admission.
    assert check_request(
        "MyMachine:8765", None, PORT, extra_hosts=frozenset({"mymachine:8765"})
    ).allowed
    assert check_request(
        "mymachine:8765", None, PORT, extra_hosts=frozenset({"MyMachine:8765"})
    ).allowed


def test_default_call_stays_loopback_only():
    # No extras passed: today's behaviour, byte for byte.
    assert not check_request("mymachine:8765", None, PORT).allowed
    assert allowed_hosts(PORT) == frozenset({"127.0.0.1:8765", "localhost:8765"})
    assert allowed_origins(PORT) == frozenset(
        {"http://127.0.0.1:8765", "http://localhost:8765"}
    )


def test_rejected_verdict_carries_the_offending_value():
    # The refusal page names what was rejected; the verdict carries it.
    verdict = check_request("evil.example:80", None, PORT)
    assert verdict.rejected == "evil.example:80"
    verdict = check_request(f"127.0.0.1:{PORT}", "https://evil.example", PORT)
    assert verdict.rejected == "https://evil.example"
    assert check_request(f"127.0.0.1:{PORT}", None, PORT).rejected == ""


def test_an_opaque_null_origin_is_no_origin_information():
    """Embedded browsers (sandboxed frames, webviews) send the literal
    string "null" as the Origin of a native form post. Like a missing
    Origin, it carries nothing to check, so it is not an attack signal:
    the session cookie is SameSite=Strict, and a cross-site requester
    cannot present it, so a null-origin POST with a live session can
    only come from the user's own page in such a browser. A real origin
    is still checked strictly."""
    verdict = check_request("127.0.0.1:8765", "null", 8765)
    assert verdict.allowed is True

    verdict = check_request("localhost:8765", "NULL", 8765)
    assert verdict.allowed is True  # case-insensitive

    # every real origin keeps the strict check, byte for byte
    verdict = check_request("127.0.0.1:8765", "http://evil.example", 8765)
    assert verdict.allowed is False
    assert verdict.rejected == "http://evil.example"
