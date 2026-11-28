"""The memory crypto box: the donor's src/crypto.ts on the cryptography
package (ticket #94).

The envelope replicates the donor byte for byte: version byte 0x01, a
12-byte random IV, the AES-256-GCM ciphertext and its 16-byte tag, with
associated data binding table, column and row id so a ciphertext moved
between fields fails to open. Keys derive through HKDF-SHA256 with an
empty salt and the donor's two info strings; blind indexes are
HMAC-SHA256 over the normalized text, keyed separately. The marker is
the donor's key check: the constant string sealed under the schema-meta
aad, stored base64 in schema_meta.
"""

import base64
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.memory.crypto import (
    KEY_CHECK,
    CryptoBox,
    MemoryEncryptedError,
    aad,
    check_marker,
    derive_keys,
    load_key,
    make_marker,
)


KEY = bytes(range(32))
OTHER_KEY = bytes(range(32, 64))


def test_derive_keys_is_deterministic_and_separates_the_infos():
    first = derive_keys(KEY)
    second = derive_keys(KEY)
    assert first == second
    enc_key, mac_key = first
    assert enc_key != mac_key, "the two info strings must derive different keys"
    assert len(enc_key) == 32 and len(mac_key) == 32
    assert derive_keys(OTHER_KEY) != first


def test_envelope_round_trip_and_layout():
    box = CryptoBox(KEY)
    value = "the revenue total is 220"
    envelope = box.seal(value, "facts", "text", 7)
    assert envelope[0] == 1, "the donor's version byte"
    assert len(envelope) == 1 + 12 + len(value.encode("utf-8")) + 16
    assert box.open(envelope, "facts", "text", 7) == value


def test_sealing_the_same_value_twice_differs_by_iv():
    box = CryptoBox(KEY)
    assert box.seal("same", "facts", "text", 1) != box.seal("same", "facts", "text", 1)


def test_aad_binds_table_column_and_row_id():
    box = CryptoBox(KEY)
    envelope = box.seal("revenue is 220", "facts", "text", 1)
    assert box.open(envelope, "facts", "text", 1) == "revenue is 220"
    with pytest.raises(MemoryEncryptedError, match=r"Ciphertext failed authentication"):
        box.open(envelope, "facts", "text", 2)
    with pytest.raises(MemoryEncryptedError, match=r"Ciphertext failed authentication"):
        box.open(envelope, "sources", "text", 1)
    assert aad("facts", "text", 1) == "facts|text|1"


def test_tampering_fails_authentication():
    box = CryptoBox(KEY)
    envelope = bytearray(box.seal("revenue is 220", "facts", "text", 1))
    envelope[20] ^= 0xFF  # a byte inside the ciphertext
    with pytest.raises(MemoryEncryptedError, match=r"Ciphertext failed authentication"):
        box.open(bytes(envelope), "facts", "text", 1)
    truncated = bytes(envelope[:-1])
    with pytest.raises(MemoryEncryptedError, match=r"Ciphertext failed authentication"):
        box.open(truncated, "facts", "text", 1)
    wrong_version = bytes([2]) + box.seal("x", "facts", "text", 1)[1:]
    with pytest.raises(MemoryEncryptedError, match=r"Ciphertext failed authentication"):
        box.open(wrong_version, "facts", "text", 1)


def test_blind_index_is_stable_hex_and_key_separated():
    box = CryptoBox(KEY)
    first = box.blind("revenue is 220")
    assert first == box.blind("revenue is 220")
    assert first != box.blind("revenue is 480")
    assert len(first) == 64 and int(first, 16) >= 0  # hex
    assert first != CryptoBox(OTHER_KEY).blind("revenue is 220")


def test_marker_round_trips_and_rejects_a_wrong_key():
    marker = make_marker(KEY)
    decoded = base64.b64decode(marker)
    assert KEY_CHECK == "memory-bank-ok"
    check_marker(marker, KEY)  # must not raise
    with pytest.raises(MemoryEncryptedError, match=r"Wrong encryption key"):
        check_marker(marker, OTHER_KEY)
    with pytest.raises(MemoryEncryptedError, match=r"Wrong encryption key"):
        check_marker("not base64 at all!!", KEY)


def test_box_refuses_a_key_that_is_not_32_bytes():
    with pytest.raises(ValueError):
        CryptoBox(KEY[:-1])
    with pytest.raises(ValueError):
        CryptoBox(KEY + b"x")


def test_load_key_demands_exactly_32_bytes_and_names_the_key_file():
    assert load_key(KEY) == KEY
    with pytest.raises(ValueError, match=r"32 bytes"):
        load_key(KEY[:31])
    with pytest.raises(ValueError, match=r"32 bytes"):
        load_key(b"")
    with pytest.raises(ValueError, match=r"memory\.key"):
        load_key(KEY + b"x")


# -- byte envelopes (ticket #95: the facts.embedding blob) --------------------


def test_byte_envelope_round_trips_and_matches_the_text_layout():
    box = CryptoBox(KEY)
    blob = bytes(range(12))
    envelope = box.seal_bytes(blob, "facts", "embedding", 3)
    assert envelope[0] == 1
    assert len(envelope) == 1 + 12 + len(blob) + 16
    assert box.open_bytes(envelope, "facts", "embedding", 3) == blob


def test_byte_envelope_binds_the_destination_like_the_text_one():
    box = CryptoBox(KEY)
    envelope = box.seal_bytes(b"\x01\x02", "facts", "embedding", 3)
    with pytest.raises(MemoryEncryptedError):
        box.open_bytes(envelope, "facts", "embedding", 4)
    with pytest.raises(MemoryEncryptedError):
        box.open_bytes(envelope, "facts", "text", 3)
