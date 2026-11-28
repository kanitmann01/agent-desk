"""Trust fixtures: generated keys and signed metadata for tests.

Private key material is generated deterministically inside tmp_path and
never committed. The registry's shipped trust directory (if any) holds
public metadata only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from nexuusbot.trust.canonical import b64u_encode, canonical_bytes
from nexuusbot.trust.ed25519 import public_key, sign

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()
FUTURE = (NOW + timedelta(days=365)).isoformat()
PAST = (NOW - timedelta(days=1)).isoformat()
NOT_BEFORE = "2026-01-01T00:00:00+00:00"


@dataclass(frozen=True)
class Key:
    key_id: str
    seed: bytes

    @property
    def public(self) -> bytes:
        return public_key(self.seed)

    @property
    def public_b64(self) -> str:
        return b64u_encode(self.public)

    def sign(self, data: bytes) -> bytes:
        return sign(data, self.seed)


def make_key(key_id: str) -> Key:
    seed = hashlib.sha256(f"agentdesk-test-key:{key_id}".encode("utf-8")).digest()
    return Key(key_id=key_id, seed=seed)


def make_keys(count: int) -> list[Key]:
    return [make_key(f"root-{i}") for i in range(1, count + 1)]


def _write_json(path: Path, document: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return raw


def signatures(payload: dict, signers: list[Key]) -> list[dict]:
    data = canonical_bytes(payload)
    return [{"keyId": key.key_id, "signature": b64u_encode(key.sign(data))}
            for key in signers]


def root_payload(keys: list[Key], *, threshold: int = 2, epoch: int = 1,
                 expires_at: str = FUTURE) -> dict:
    return {
        "threshold": threshold,
        "keys": [{"keyId": key.key_id, "publicKey": key.public_b64}
                 for key in keys],
        "epoch": epoch,
        "expiresAt": expires_at,
    }


def write_root(trust_dir: Path, keys: list[Key], *, signers: list[Key] | None = None,
               threshold: int = 2, epoch: int = 1,
               expires_at: str = FUTURE) -> dict:
    payload = root_payload(keys, threshold=threshold, epoch=epoch,
                           expires_at=expires_at)
    signers = signers if signers is not None else keys[:threshold]
    document = {"payload": payload, "signatures": signatures(payload, signers)}
    raw = _write_json(trust_dir / "root.json", document)
    _write_json(trust_dir / "anchor.json", {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "epoch": epoch,
    })
    return document


def publisher_payload(publisher_id: str, key: Key, *, provenance: tuple[str, str] = ("manual", "test"),
                      not_before: str = NOT_BEFORE, expires_at: str = FUTURE) -> dict:
    return {
        "publisherId": publisher_id,
        "keyId": key.key_id,
        "publicKey": key.public_b64,
        "provenance": {"kind": provenance[0], "value": provenance[1]},
        "notBefore": not_before,
        "expiresAt": expires_at,
    }


def write_publisher(trust_dir: Path, publisher_id: str, key: Key,
                    root_keys: list[Key], *, signers: list[Key] | None = None,
                    provenance: tuple[str, str] = ("manual", "test"),
                    not_before: str = NOT_BEFORE,
                    expires_at: str = FUTURE) -> dict:
    payload = publisher_payload(publisher_id, key, provenance=provenance,
                                not_before=not_before, expires_at=expires_at)
    signers = signers if signers is not None else root_keys[:2]
    document = {"payload": payload, "signatures": signatures(payload, signers)}
    _write_json(trust_dir / "publishers" / f"{publisher_id}.json", document)
    return payload


def revocation_payload(*, epoch: int = 1, issued_at: str = NOW_ISO,
                       expires_at: str = FUTURE,
                       revoked: dict | None = None) -> dict:
    return {
        "epoch": epoch,
        "issuedAt": issued_at,
        "expiresAt": expires_at,
        "revoked": {
            "publishers": list((revoked or {}).get("publishers", [])),
            "keys": list((revoked or {}).get("keys", [])),
            "releases": [dict(item) for item in (revoked or {}).get("releases", [])],
        },
    }


def write_revocations(trust_dir: Path, root_keys: list[Key], *,
                      signers: list[Key] | None = None, epoch: int = 1,
                      issued_at: str = NOW_ISO, expires_at: str = FUTURE,
                      revoked: dict | None = None) -> dict:
    payload = revocation_payload(epoch=epoch, issued_at=issued_at,
                                 expires_at=expires_at, revoked=revoked)
    signers = signers if signers is not None else root_keys[:2]
    document = {"payload": payload, "signatures": signatures(payload, signers)}
    _write_json(trust_dir / "revocations.json", document)
    return document


def release_payload(plugin_id: str, version: str, digest: str, *,
                    category: str = "demo", changelog: str = "test release",
                    min_host: str = "0.1.0", released_at: str = NOW_ISO,
                    expires_at: str = FUTURE) -> dict:
    return {
        "pluginId": plugin_id,
        "version": version,
        "digest": digest,
        "category": category,
        "changelog": changelog,
        "minHost": min_host,
        "releasedAt": released_at,
        "expiresAt": expires_at,
    }


def write_release(trust_dir: Path, plugin_id: str, version: str, payload: dict,
                  publisher_key: Key, *, tamper: bool = False) -> dict:
    from nexuusbot.trust.canonical import envelope

    envelope_doc = envelope(payload, publisher_key.key_id, publisher_key.seed,
                            signed_at=NOW_ISO)
    if tamper:
        from nexuusbot.trust.canonical import b64u_decode, b64u_encode

        raw = bytearray(b64u_decode(envelope_doc["signature"]))
        raw[0] ^= 1
        envelope_doc["signature"] = b64u_encode(bytes(raw))
    document = {"payload": payload, "signature": envelope_doc}
    _write_json(trust_dir / "releases" / plugin_id / f"{version}.json", document)
    return document


def pin_payload(plugin_id: str, version: str, digest: str) -> dict:
    return {"pluginId": plugin_id, "version": version, "digest": digest}


def pin_signature(plugin_id: str, version: str, digest: str, key: Key) -> str:
    return b64u_encode(key.sign(canonical_bytes(pin_payload(plugin_id, version, digest))))


def policy_bundle_fields(**overrides) -> dict:
    """A complete signed-policy policy block, starting from the built-in posture."""
    from dataclasses import asdict

    from nexuusbot.marketplace.policy import default_policy

    fields = {name: value for name, value in asdict(default_policy()).items()
              if name not in ("signatureStatus", "source")}
    fields.update(overrides)
    return fields


def policy_bundle(signer: Key, *, fields: dict | None = None, issued_at=NOW,
                  expires_at: str = FUTURE, revocation_epoch: int = 0,
                  key_id: str | None = None) -> dict:
    """A signed policy bundle for the test signer (deterministic Ed25519)."""
    from nexuusbot.marketplace.signed_policy import sign_policy_bundle

    return sign_policy_bundle(
        fields if fields is not None else policy_bundle_fields(),
        seed=signer.seed,
        key_id=key_id or signer.key_id,
        issued_at=issued_at,
        expires_at=expires_at,
        revocation_epoch=revocation_epoch,
    )


def write_policy_bundle(workspace: Path, signer: Key, *, fields: dict | None = None,
                        issued_at=NOW, expires_at: str = FUTURE,
                        revocation_epoch: int = 0, key_id: str | None = None) -> dict:
    """Write a signed bundle to <workspace>/marketplace/policy.json."""
    from nexuusbot.marketplace.signed_policy import sign_policy_bundle

    bundle = sign_policy_bundle(
        fields if fields is not None else policy_bundle_fields(),
        seed=signer.seed,
        key_id=key_id or signer.key_id,
        issued_at=issued_at,
        expires_at=expires_at,
        revocation_epoch=revocation_epoch,
    )
    _write_json(Path(workspace) / "marketplace" / "policy.json", bundle)
    return bundle
