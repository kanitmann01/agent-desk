"""Canonical bytes and detached signature envelopes.

Canonical JSON is UTF-8, sorted keys, compact separators, no ASCII escaping.
Floats are rejected so the bytes cannot drift across platforms.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from . import ed25519
from .errors import TrustError


def _reject_floats(value: Any, path: str = "") -> None:
    """Reject floats anywhere in a JSON value before it is serialised.

    Float formatting is the one part of JSON that implementations do not agree
    on, and integer-valued floats (1.0) do not serialise like the integers they
    denote. Keeping signed metadata to ints and strings is what makes the bytes
    identical on every platform. Non-string object keys are rejected too: json
    would silently stringify them and change the document.

    ValueError names the path of the first offending value.
    """
    if isinstance(value, float):
        raise ValueError(f"floats are not allowed in canonical JSON at {path or '<root>'}")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON object keys must be strings")
            _reject_floats(item, f"{path}.{key}" if path else key)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def canonical_bytes(value: Any) -> bytes:
    """Serialise a JSON-compatible value to stable UTF-8 bytes."""
    _reject_floats(value)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def b64u_encode(data: bytes) -> str:
    """Encode bytes as unpadded base64url.

    The alphabet is URL- and filename-safe ('-' and '_' in place of '+' and
    '/') and no '=' padding is written, so the value can go straight into
    canonical JSON. b64u_decode restores the padding when reading it back.
    """
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    """Decode base64url into bytes, tolerating a missing '=' padding.

    The alphabet is validated: a corrupted or truncated field raises ValueError
    here instead of silently yielding the wrong bytes. The standard '+' and '/'
    characters decode as well, because base64.b64decode translates them first.
    Correctly padded input is accepted, so callers need not strip '='.
    """
    if not isinstance(text, str):
        raise ValueError("base64url value must be a string")
    padded = text + "=" * (-len(text) % 4)
    return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)


def _utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Always with an explicit +00:00 offset, which is what makes the default
    envelope signedAt compare cleanly against timestamps read from another host.
    """
    return datetime.now(timezone.utc).isoformat()


def envelope(payload: Any, key_id: str, seed: bytes, *, signed_at: str | None = None) -> dict:
    """Build a detached Ed25519 envelope over the canonical payload bytes."""
    data = canonical_bytes(payload)
    return {
        "keyId": key_id,
        "algorithm": "ed25519",
        "signature": b64u_encode(ed25519.sign(data, seed)),
        "digest": hashlib.sha256(data).hexdigest(),
        "signedAt": signed_at or _utc_now(),
    }


def verify_envelope(payload: Any, envelope: dict, public_key: bytes) -> None:
    """Raise TrustError('trust:bad-signature') unless digest and signature match."""
    if not isinstance(envelope, dict):
        raise TrustError("trust:bad-signature", "malformed envelope")
    if envelope.get("algorithm") != "ed25519":
        raise TrustError("trust:bad-signature", "unsupported envelope algorithm")
    data = canonical_bytes(payload)
    expected = hashlib.sha256(data).hexdigest()
    claimed = envelope.get("digest")
    if not isinstance(claimed, str) or not hmac.compare_digest(claimed.lower(), expected):
        raise TrustError("trust:bad-signature", "envelope digest does not match payload")
    try:
        signature = b64u_decode(envelope.get("signature"))
    except (ValueError, TypeError) as exc:
        raise TrustError("trust:bad-signature", "envelope signature is not base64url") from exc
    if not ed25519.verify(public_key, data, signature):
        raise TrustError("trust:bad-signature", "envelope signature does not verify")
