"""UDP discovery between desks (ticket #67): announce, listen, TTL.

Two services on one announce port with different HTTP ports must hear
each other through the real socket path (loopback broadcast covers the
same-machine case; the listener also accepts recorded announcements so
the bookkeeping rules are testable deterministically). Threads are
daemons with a clean stop, following the watcher-thread patterns.
"""
import socket
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.peers.discovery import DiscoveryService  # noqa: E402


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def announce_port():
    return free_udp_port()


def test_two_services_on_one_machine_discover_each_other(announce_port):
    a = DiscoveryService(peer_id="desk-aaa", name="Desk A", http_port=8801,
                         announce_port=announce_port, interval=0.2, ttl=30.0)
    b = DiscoveryService(peer_id="desk-bbb", name="Desk B", http_port=8802,
                         announce_port=announce_port, interval=0.2, ttl=30.0)
    a.start()
    b.start()
    try:
        deadline = time.monotonic() + 10.0
        seen = []
        while time.monotonic() < deadline:
            seen = [d["peer_id"] for d in a.discovered()]
            if "desk-bbb" in seen:
                break
            time.sleep(0.1)
        assert "desk-bbb" in seen, f"A never discovered B; saw {seen}"
        entry = next(d for d in a.discovered() if d["peer_id"] == "desk-bbb")
        assert entry["name"] == "Desk B"
        assert entry["port"] == 8802
        assert entry["host"] == "127.0.0.1"
        assert entry["pairing_required"] is True
        assert entry["last_seen"] > 0
        # and the mirror image
        assert "desk-aaa" in [d["peer_id"] for d in b.discovered()]
        # a desk never lists itself
        assert "desk-aaa" not in [d["peer_id"] for d in a.discovered()]
    finally:
        a.stop()
        b.stop()


def test_announce_payload_names_the_app_and_the_desk():
    a = DiscoveryService(peer_id="desk-aaa", name="Desk A", http_port=8801)
    payload = a.announce_payload()
    assert payload["app"] == "agent-desk"
    assert payload["peer_id"] == "desk-aaa"
    assert payload["name"] == "Desk A"
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 8801
    assert payload["pairing_required"] is True


def test_recorded_announcements_expire_with_the_ttl():
    a = DiscoveryService(peer_id="desk-aaa", name="Desk A", http_port=8801,
                         ttl=10.0)
    a.record_announcement(
        {"app": "agent-desk", "peer_id": "desk-bbb", "name": "Desk B",
         "host": "127.0.0.1", "port": 8802, "pairing_required": True},
        source_addr="127.0.0.1")
    assert [d["peer_id"] for d in a.discovered()] == ["desk-bbb"]
    # push last_seen past the TTL, exactly like a clock would
    a._peers["desk-bbb"]["last_seen"] -= 11.0
    assert a.discovered() == []


def test_junk_announcements_are_ignored_not_fatal():
    a = DiscoveryService(peer_id="desk-aaa", name="Desk A", http_port=8801)
    a.record_announcement({"nonsense": True}, source_addr="127.0.0.1")
    a.record_announcement(
        {"app": "agent-desk", "nonsense": True},
        source_addr="127.0.0.1")
    a.record_announcement(
        {"app": "agent-desk", "peer_id": "desk-aaa", "name": "myself",
         "host": "127.0.0.1", "port": 1, "pairing_required": True},
        source_addr="127.0.0.1")  # self, must not appear
    assert a.discovered() == []


def test_stop_ends_the_threads_and_frees_the_socket(announce_port):
    a = DiscoveryService(peer_id="desk-aaa", name="Desk A", http_port=8801,
                         announce_port=announce_port, interval=0.2)
    a.start()
    listener = a._listener_thread
    announcer = a._announcer_thread
    assert listener.is_alive() and announcer.is_alive()
    a.stop()
    listener.join(timeout=5)
    announcer.join(timeout=5)
    assert not listener.is_alive()
    assert not announcer.is_alive()
    # the port is free again: another listener can bind it
    b = DiscoveryService(peer_id="desk-bbb", name="Desk B", http_port=8802,
                         announce_port=announce_port, interval=0.2)
    b.start()
    try:
        assert b._listener_thread.is_alive()
    finally:
        b.stop()
