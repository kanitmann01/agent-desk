"""Memory encryption primitives: the donor's src/crypto.ts ported onto
the `cryptography` package (ticket #94), the app's first third-party
runtime dependency (Apache-2.0 OR BSD-3-Clause, inside the license
manifest's allowlist).

The design replicates the donor exactly:

- One 32-byte key (the memory.key file's contents) is the input; HKDF-
  SHA256 with an empty salt derives an encryption key (info
  "memory-bank:enc:v1") and a MAC key (info "memory-bank:mac:v1"),
  32 bytes each.
- Every sealed value is one envelope: version byte 0x01, a 12-byte
  random IV, the AES-256-GCM ciphertext and its 16-byte tag appended by
  the library. Associated data binds the destination: ``table|column|
  row_id``, so a ciphertext pasted into another field (or another row)
  fails to open.
- Blind indexes are HMAC-SHA256 (keyed by the MAC key) over a
  normalized string, stored as hex: equality lookups compare the blind,
  never the text.
- The key-check marker is the constant "memory-bank-ok" sealed under
  the aad "schema_meta|encryption|v1" and stored base64 in the
  schema_meta table under the key "encryption"; opening it with the
  wrong key is how a database says "wrong key".

Every failure at this boundary raises MemoryEncryptedError (a
subclass carries the authentication wording), never a silent fallback.
"""

import base64
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_BYTES = 32
VERSION = 1
IV_BYTES = 12
TAG_BYTES = 16
KEY_CHECK = "memory-bank-ok"
ENC_INFO = b"memory-bank:enc:v1"
MAC_INFO = b"memory-bank:mac:v1"
MARKER_AAD = "schema_meta|encryption|v1"
KEY_FILE_NAME = "memory.key"


class MemoryEncryptedError(Exception):
    """The encryption boundary refused an operation: a locked store, a
    missing ciphertext, a failed authentication. Plain-language message,
    never a silent plaintext fallback."""


class AuthenticationFailed(MemoryEncryptedError):
    """An envelope did not open under this key and aad."""


def aad(table: str, column: str, row_id) -> str:
    """The donor's aad: the destination a ciphertext is bound to."""
    return f"{table}|{column}|{row_id}"


def load_key(raw: bytes) -> bytes:
    """Validate raw key-file bytes: exactly 32, nothing else.

    The wording names the key file (memory.key) so the message stays
    actionable when it surfaces on the memory page."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != KEY_BYTES:
        raise ValueError(
            f"encryptionKey must be 32 bytes; the {KEY_FILE_NAME} file"
            f" holds {len(raw) if raw is not None else 0}."
        )
    return bytes(raw)


def derive_keys(key: bytes) -> tuple[bytes, bytes]:
    """The donor's HKDF-SHA256 derivations: empty salt, the two info
    strings, 32 bytes each."""
    enc_key = HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=b"", info=ENC_INFO,
    ).derive(key)
    mac_key = HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=b"", info=MAC_INFO,
    ).derive(key)
    return enc_key, mac_key


def _random_iv() -> bytes:
    return os.urandom(IV_BYTES)


class CryptoBox:
    """The donor's CryptoBox: seal, open and blind over one key.

    `open` is a method name here (the builtin stays untouched), so the
    donor's verb survives the port.
    """

    def __init__(self, key: bytes) -> None:
        self.enc_key, self.mac_key = derive_keys(load_key(key))
        self._aead = AESGCM(self.enc_key)

    def seal(self, value: str, table: str, column: str, row_id) -> bytes:
        """One envelope: version byte, IV, ciphertext with its tag, all
        bound to the destination by the associated data."""
        iv = _random_iv()
        ciphertext = self._aead.encrypt(
            iv, value.encode("utf-8"), aad(table, column, row_id).encode("utf-8")
        )
        return bytes([VERSION]) + iv + ciphertext

    def open(self, envelope: bytes, table: str, column: str, row_id) -> str:
        """Open an envelope; any failure (truncated, wrong version, tag
        or aad mismatch) raises the donor's authentication wording."""
        envelope = bytes(envelope)
        header = 1 + IV_BYTES + TAG_BYTES
        if len(envelope) < header or envelope[0] != VERSION:
            raise AuthenticationFailed("Ciphertext failed authentication.")
        iv = envelope[1:1 + IV_BYTES]
        # The library's decrypt takes the ciphertext with the tag already
        # appended, exactly the tail the seal produced.
        ciphertext = envelope[1 + IV_BYTES:]
        try:
            plaintext = self._aead.decrypt(
                iv, ciphertext,
                aad(table, column, row_id).encode("utf-8"),
            )
        except InvalidTag as exc:
            raise AuthenticationFailed("Ciphertext failed authentication.") from exc
        return plaintext.decode("utf-8")

    def blind(self, normalized: str) -> str:
        """The keyed blind index of a normalized string, hex-encoded so
        TEXT columns and hex scope keys compare the same way."""
        return hmac.new(
            self.mac_key, normalized.encode("utf-8"), "sha256"
        ).hexdigest()


def make_marker(key: bytes) -> str:
    """The key-check envelope, base64: the value the marker row stores."""
    box = CryptoBox(key)
    return base64.b64encode(
        box.seal(KEY_CHECK, "schema_meta", "encryption", "v1")
    ).decode("ascii")


def check_marker(marker_b64: str, key: bytes) -> None:
    """Raise MemoryEncryptedError("Wrong encryption key.") unless the
    marker opens under this key to exactly the key-check string.

    Every failure mode (undecodable base64, a truncated envelope, a
    failed tag, a different plaintext) lands on the same message, the
    donor's assertKeyCheck as its callers rewrite it."""
    try:
        envelope = base64.b64decode(marker_b64, validate=True)
        opened = CryptoBox(key).open(envelope, "schema_meta", "encryption", "v1")
    except (ValueError, MemoryEncryptedError) as exc:
        raise MemoryEncryptedError("Wrong encryption key.") from exc
    if opened != KEY_CHECK:
        raise MemoryEncryptedError("Wrong encryption key.")
