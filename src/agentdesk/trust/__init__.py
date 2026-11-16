"""Ed25519-based trust chain for the plugin marketplace.

Public surface:
- TrustError: fail-closed verification error with a stable code.
- ed25519: RFC 8032 signing primitives over 32-byte seeds.
- canonical_bytes / envelope / verify_envelope: deterministic signed envelopes.
- model: root metadata, publisher certificates, release statements,
  revocation lists and the TrustStore loader.
"""
from .canonical import (
    b64u_decode,
    b64u_encode,
    canonical_bytes,
    envelope,
    verify_envelope,
)
from .ed25519 import generate_seed, public_key, sign, verify
from .errors import TrustError
from .model import (
    PublisherCert,
    ReleaseStatement,
    RevocationList,
    RootMetadata,
    SignatureProof,
    TrustKey,
    TrustStore,
    parse_publisher_cert,
    parse_release_statement,
    parse_revocations,
    parse_root,
    release_pin_payload,
    verify_publisher_cert,
    verify_release,
    verify_release_pin,
    verify_revocations,
    verify_root,
)

__all__ = [
    "TrustError",
    "PublisherCert",
    "ReleaseStatement",
    "RevocationList",
    "RootMetadata",
    "SignatureProof",
    "TrustKey",
    "TrustStore",
    "b64u_decode",
    "b64u_encode",
    "canonical_bytes",
    "envelope",
    "generate_seed",
    "parse_publisher_cert",
    "parse_release_statement",
    "parse_revocations",
    "parse_root",
    "public_key",
    "release_pin_payload",
    "sign",
    "verify",
    "verify_envelope",
    "verify_publisher_cert",
    "verify_release",
    "verify_release_pin",
    "verify_revocations",
    "verify_root",
]
