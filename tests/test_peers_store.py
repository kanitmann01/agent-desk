"""The peer store (ticket #67): identity, pairing codes, shares.

Everything peer-related persists in one sqlite store with an injectable
clock: the desk's own identity, short-lived single-use pairing codes,
paired peers (verification compares only the token's hash; the token
itself is kept so pairing works in both directions, like any API client
credential), the plugin ids this desk publishes, and per-peer
subscription snapshots. Wrong or expired codes are named refusals,
never silent failures.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.peers.store import (  # noqa: E402
    CODE_TTL_S,
    MAX_PAIRING_MISSES,
    PeerError,
    PeerStore,
    derive_token,
    hash_token,
)


@pytest.fixture()
def store():
    return PeerStore(sqlite3.connect(":memory:", check_same_thread=False),
                     clock=lambda: 1000.0)


def test_desk_identity_is_created_once_and_stable(store):
    first = store.desk()
    assert first["peer_id"]
    assert first["name"]
    again = store.desk()
    assert again == first


def test_pairing_code_exchange_persists_peer_with_hashed_token(store):
    code = store.create_pairing_code()["code"]
    out = store.exchange_pairing_code(
        code, peer_id="peer-b", name="Desk B", base_url="127.0.0.1:8802")
    assert out["ok"] is True
    peer = store.peer("peer-b")
    assert peer["name"] == "Desk B"
    assert peer["base_url"] == "127.0.0.1:8802"
    # verification compares a hash of the derived token; the token
    # itself is also kept (in the row's token column) so pairing works
    # in both directions
    assert peer["token_hash"] == hash_token(derive_token(code))
    assert derive_token(code) not in peer["token_hash"]
    assert peer["token_hash"] != code


def test_valid_token_is_accepted_and_wrong_token_is_not(store):
    code = store.create_pairing_code()["code"]
    store.exchange_pairing_code(code, peer_id="peer-b", name="B",
                                base_url="127.0.0.1:8802")
    token = derive_token(code)
    assert store.token_valid(token) is True
    assert store.token_valid("not-the-token") is False
    assert store.token_valid("") is False


def test_wrong_code_is_a_named_refusal(store):
    store.create_pairing_code()
    with pytest.raises(PeerError) as excinfo:
        store.exchange_pairing_code("ZZZZZZZZ", peer_id="p", name="n",
                                    base_url="127.0.0.1:1")
    assert excinfo.value.code == "pairing:unknown-code"


def test_code_expires_with_the_injected_clock(tmp_path):
    import sqlite3 as s3

    path = tmp_path / "peers.sqlite3"
    conn = s3.connect(path)
    now = {"t": 5000.0}
    timed = PeerStore(conn, clock=lambda: now["t"])
    code = timed.create_pairing_code()["code"]
    now["t"] += CODE_TTL_S + 1
    with pytest.raises(PeerError) as excinfo:
        timed.exchange_pairing_code(code, peer_id="p", name="n",
                                    base_url="127.0.0.1:1")
    assert excinfo.value.code == "pairing:expired"


def test_code_is_single_use(store):
    code = store.create_pairing_code()["code"]
    store.exchange_pairing_code(code, peer_id="peer-b", name="B",
                                base_url="127.0.0.1:8802")
    with pytest.raises(PeerError) as excinfo:
        store.exchange_pairing_code(code, peer_id="peer-c", name="C",
                                    base_url="127.0.0.1:8803")
    assert excinfo.value.code == "pairing:used"
    # and the replay did not create the second peer
    assert store.peer("peer-c") is None


def test_add_peer_records_the_other_side_with_hashed_token(store):
    store.add_peer(peer_id="peer-a", name="Desk A",
                   base_url="127.0.0.1:8801", token="channel-token-a")
    peer = store.peer("peer-a")
    assert peer["token_hash"] == hash_token("channel-token-a")
    assert "channel-token-a" not in peer["token_hash"]
    assert [p["peer_id"] for p in store.peers()] == ["peer-a"]


def test_the_subscribing_side_keeps_the_channel_token_for_outbound_reads(store):
    """One row serves both directions: the desk that typed the code must
    present the token later, so it keeps the credential (like any API
    client), while the verifying comparison still uses only the hash."""
    code = store.create_pairing_code()["code"]
    store.exchange_pairing_code(code, peer_id="peer-b", name="B",
                                base_url="127.0.0.1:8802")
    # the desk that generated the code also ends up holding the token
    assert store.channel_token("peer-b") == derive_token(code)
    store.add_peer(peer_id="peer-a", name="A", base_url="127.0.0.1:8801",
                   token="channel-token-a")
    assert store.channel_token("peer-a") == "channel-token-a"
    # but the token never rides along in the listing rows
    assert "token" not in store.peer("peer-a")
    assert all("token" not in row for row in store.peers())
    assert store.channel_token("ghost") is None


def test_repairing_the_same_peer_updates_it_in_place(store):
    code = store.create_pairing_code()["code"]
    store.exchange_pairing_code(code, peer_id="peer-b", name="Old",
                                base_url="127.0.0.1:9000")
    code2 = store.create_pairing_code()["code"]
    store.exchange_pairing_code(code2, peer_id="peer-b", name="New",
                                base_url="127.0.0.1:9001")
    peers = store.peers()
    assert len(peers) == 1
    assert peers[0]["name"] == "New"
    assert peers[0]["base_url"] == "127.0.0.1:9001"
    assert store.token_valid(derive_token(code2)) is True


def test_shares_toggle_and_listing(store):
    assert store.shared_ids() == set()
    store.set_shared("sales-delta-widget", True)
    assert store.shared_ids() == {"sales-delta-widget"}
    store.set_shared("sales-delta-widget", False)
    assert store.shared_ids() == set()


def test_subscription_snapshot_and_install_state(store):
    store.record_seen("sales-delta-widget", "peer-a", "1.2.0", "ab" * 32)
    snap = store.subscriptions()[0]
    assert snap["plugin_id"] == "sales-delta-widget"
    assert snap["peer_id"] == "peer-a"
    assert snap["seen_version"] == "1.2.0"
    assert snap["installed_version"] is None

    store.set_installed("sales-delta-widget", "peer-a", "1.2.0")
    snap = store.subscriptions()[0]
    assert snap["installed_version"] == "1.2.0"

    store.record_seen("sales-delta-widget", "peer-a", "1.2.1", "cd" * 32)
    snap = store.subscriptions()[0]
    assert snap["seen_version"] == "1.2.1"
    assert snap["installed_version"] == "1.2.0"


def test_pairing_code_shape_is_short_and_unambiguous(store):
    code = store.create_pairing_code()["code"]
    assert 6 <= len(code) <= 8
    assert all(c in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" for c in code)
    out = store.create_pairing_code()
    assert out["code"] != code
    assert out["expires_at"] == 1000.0 + CODE_TTL_S


def test_wrong_code_attempts_burn_the_live_code(store):
    """Five wrong submissions invalidate the live code: pairing has no
    rate limit otherwise, so the counter is the throttle."""
    code = store.create_pairing_code()["code"]
    for attempt in range(MAX_PAIRING_MISSES - 1):
        with pytest.raises(PeerError) as excinfo:
            store.exchange_pairing_code(f"WRONG{attempt:02d}", peer_id="p",
                                        name="n", base_url="127.0.0.1:1")
        assert excinfo.value.code == "pairing:unknown-code"
    # four misses so far: the right code still works
    out = store.exchange_pairing_code(code, peer_id="peer-b", name="B",
                                      base_url="127.0.0.1:8802")
    assert out["ok"] is True


def test_five_wrong_codes_invalidate_the_live_code(store):
    code = store.create_pairing_code()["code"]
    for attempt in range(MAX_PAIRING_MISSES):
        with pytest.raises(PeerError):
            store.exchange_pairing_code(f"MISS{attempt:02d}", peer_id="p",
                                        name="n", base_url="127.0.0.1:1")
    # the live code is dead: even the right one is refused by name
    with pytest.raises(PeerError) as excinfo:
        store.exchange_pairing_code(code, peer_id="p", name="n",
                                    base_url="127.0.0.1:1")
    assert excinfo.value.code == "pairing:unknown-code"
    # and nothing was paired
    assert store.peers() == []


def test_a_fresh_code_resets_the_attempt_counter(store):
    code = store.create_pairing_code()["code"]
    for attempt in range(MAX_PAIRING_MISSES):
        with pytest.raises(PeerError):
            store.exchange_pairing_code(f"MISS{attempt:02d}", peer_id="p",
                                        name="n", base_url="127.0.0.1:1")
    fresh = store.create_pairing_code()["code"]
    assert store.exchange_pairing_code(fresh, peer_id="peer-b", name="B",
                                       base_url="127.0.0.1:8802")["ok"] is True
    assert code != fresh


def test_peer_refresh_state_records_the_honest_cause(store):
    store.add_peer(peer_id="peer-a", name="A", base_url="127.0.0.1:8801",
                   token="t")
    # nothing recorded yet: unknown, not invented
    assert store.peer_state("peer-a")["last_refresh"] is None
    # a failed refresh names its cause
    store.record_peer_refresh("peer-a", ok=False,
                              cause="The desk could not be reached: refused")
    state = store.peer_state("peer-a")
    assert state["ok"] is False
    assert "refused" in state["cause"]
    assert state["last_refresh"] == 1000.0
    # a later good refresh clears it
    store.record_peer_refresh("peer-a", ok=True, cause="")
    state = store.peer_state("peer-a")
    assert state["ok"] is True
    assert state["cause"] == ""
