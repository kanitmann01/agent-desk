"""Signed enterprise policy bundles for the plugin marketplace.

A bundle is the mutation of record for the effective policy: canonical
JSON over every policy field plus an Ed25519 envelope, an issue and
expiry time, and a revocation epoch. Verification fails closed with a
TrustError whose code names the failed check, and the caller keeps the
built-in default rather than trusting unverified content.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from agentdesk.marketplace.policy import (
    POLICY_FILE,
    RISK_TIERS,
    Policy,
    default_policy,
    risk_rank,
)
from agentdesk.trust import (
    TrustError,
    b64u_decode,
    b64u_encode,
    canonical_bytes,
    public_key,
    sign,
    verify,
)

SCHEMA_VERSION = 1
ANCHOR_FILE = "anchor.json"
AUDIT_FILE = "audit.json"
KILL_SWITCH_FILE = "kill-switch.json"

# The fields a bundle carries: the effective policy minus the fields the
# loader itself supplies (signature status) and the provenance label.
POLICY_FIELDS = tuple(
    name for name in asdict(Policy()) if name not in ("signatureStatus", "source")
)
LIST_FIELDS = (
    "allowedPublishers",
    "allowedCategories",
    "networkAllowlist",
    "enabledSources",
    "killSwitch",
    "platforms",
)
INT_FIELDS = ("retentionDays", "minRevocationEpoch")
BOOL_FIELDS = ("bodyIngest", "requireSignatures")
TEXT_FIELDS = ("mode", "riskCeiling", "updateChannel", "versionPolicy")
MODES = ("open", "curated", "private-only")

STATUS_BY_CODE = {
    "policy:bad-signature": "tampered",
    "policy:expired": "expired",
    "policy:stale-epoch": "stale-epoch",
    "policy:unknown-key": "unknown-key",
}


class PolicyBundleError(TrustError):
    """A TrustError raised for a policy bundle check."""

    def __init__(self, code: str, message: str, details=None):
        """Keep the rejection code and the details a caller may forward."""
        super().__init__(code, message)
        self.details = dict(details or {})


def utc_now() -> datetime:
    """The verification clock, always timezone aware."""
    return datetime.now(timezone.utc)


def parse_timestamp(value) -> datetime | None:
    """Parse an ISO 8601 timestamp into an aware datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def isoformat(value: datetime) -> str:
    """Render an aware datetime as a second-precision ISO 8601 string."""
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def fingerprint(public_key_bytes: bytes) -> str:
    """The signer fingerprint: SHA-256 hex over the raw public key."""
    return hashlib.sha256(public_key_bytes).hexdigest()


def bundle_payload(bundle: dict) -> dict:
    """The bytes-covered part of a bundle: everything but the signature."""
    return {key: value for key, value in bundle.items() if key != "signature"}


def sign_policy_bundle(
    policy_fields: dict,
    *,
    seed: bytes,
    key_id: str,
    issued_at: datetime,
    expires_at: datetime,
    revocation_epoch: int = 0,
) -> dict:
    """Build and sign a schemaVersion 1 bundle from raw policy fields."""
    unknown = sorted(set(policy_fields) - set(POLICY_FIELDS))
    if unknown:
        raise ValueError(f"unknown policy fields: {unknown}")
    issued = issued_at if isinstance(issued_at, datetime) else parse_timestamp(issued_at)
    expires = expires_at if isinstance(expires_at, datetime) else parse_timestamp(expires_at)
    if issued is None or expires is None:
        raise ValueError("issued_at and expires_at must be ISO 8601 timestamps")
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "policy": {name: policy_fields[name] for name in POLICY_FIELDS
                   if name in policy_fields},
        "issuedAt": isoformat(issued),
        "expiresAt": isoformat(expires),
        "revocationEpoch": int(revocation_epoch),
        "signer": {
            "keyId": key_id,
            "publicKey": b64u_encode(public_key(seed)),
        },
    }
    signature = sign(canonical_bytes(payload), seed)
    payload["signature"] = {
        "keyId": key_id,
        "alg": "ed25519",
        "value": b64u_encode(signature),
    }
    return payload


def looks_signed(bundle) -> bool:
    """True when the document claims to be a signed policy bundle."""
    return (
        isinstance(bundle, dict)
        and isinstance(bundle.get("schemaVersion"), int)
        and isinstance(bundle.get("signature"), dict)
    )


def _bad(message: str, details=None):
    """A policy:bad-signature rejection, the code every shape failure carries."""
    return PolicyBundleError("policy:bad-signature", message, details)


def _structure(bundle) -> dict:
    """Validate the bundle shape and return its parts, or raise."""
    if not isinstance(bundle, dict):
        raise _bad("the policy bundle must be a JSON object")
    if bundle.get("schemaVersion") != SCHEMA_VERSION:
        raise _bad(
            "the policy bundle schemaVersion must be "
            f"{SCHEMA_VERSION}, not {bundle.get('schemaVersion')!r}")
    policy = bundle.get("policy")
    if not isinstance(policy, dict):
        raise _bad("the policy bundle has no policy object")
    for name in ("issuedAt", "expiresAt"):
        if parse_timestamp(bundle.get(name)) is None:
            raise _bad(f"the policy bundle {name} is not an ISO 8601 timestamp")
    epoch = bundle.get("revocationEpoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise _bad("the policy bundle revocationEpoch must be a non-negative integer")
    signer = bundle.get("signer")
    if not isinstance(signer, dict) or not isinstance(signer.get("publicKey"), str):
        raise _bad("the policy bundle has no signer public key")
    signature = bundle.get("signature")
    if not isinstance(signature, dict) or not isinstance(signature.get("value"), str):
        raise _bad("the policy bundle has no signature value")
    if signature.get("alg") != "ed25519":
        raise _bad("the policy bundle signature algorithm must be ed25519")
    if not isinstance(signer.get("keyId"), str) or not signer["keyId"].strip():
        raise _bad("the policy bundle signer has no keyId")
    if signature.get("keyId") != signer.get("keyId"):
        raise _bad("the signature keyId does not match the signer keyId")
    try:
        key_bytes = b64u_decode(signer["publicKey"])
        signature_bytes = b64u_decode(signature["value"])
    except ValueError as exc:
        raise _bad(f"the policy bundle key or signature is not base64url ({exc})")
    if len(key_bytes) != 32:
        raise _bad("the policy bundle signer public key must be 32 bytes")
    if len(signature_bytes) != 64:
        raise _bad("the policy bundle signature must be 64 bytes")
    return {
        "policy": policy,
        "key_bytes": key_bytes,
        "signature_bytes": signature_bytes,
        "key_id": signer["keyId"],
    }


def _trusted(signer_key_id: str, signer_fingerprint: str, trusted_keys) -> bool:
    """Decide whether the signer is pinned, when a pin list is supplied."""
    if trusted_keys is None:
        return True
    if isinstance(trusted_keys, dict):
        candidates = trusted_keys
    else:
        candidates = {}
        for item in trusted_keys:
            if isinstance(item, dict):
                candidates[str(item.get("keyId") or "")] = item.get("publicKey") or ""
            else:
                candidates[str(item)] = str(item)
    for key, value in candidates.items():
        text = str(value or "").strip()
        if key == signer_key_id and not text:
            return True
        if text and text.lower() == signer_fingerprint.lower():
            return True
        if text:
            try:
                if fingerprint(b64u_decode(text)) == signer_fingerprint:
                    return True
            except ValueError:
                continue
    return False


def coerce_policy(raw: dict) -> Policy:
    """Turn verified policy fields into a Policy, rejecting bad values."""
    policy = default_policy()
    for name in TEXT_FIELDS:
        value = raw.get(name)
        if value is None:
            continue
        if not isinstance(value, str):
            raise _bad(f"the policy field {name} must be a string")
        setattr(policy, name, value)
    for name in LIST_FIELDS:
        value = raw.get(name)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise _bad(f"the policy field {name} must be a list of strings")
        setattr(policy, name, list(value))
    for name in INT_FIELDS:
        value = raw.get(name)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _bad(f"the policy field {name} must be a non-negative integer")
        setattr(policy, name, value)
    for name in BOOL_FIELDS:
        value = raw.get(name)
        if value is None:
            continue
        if not isinstance(value, bool):
            raise _bad(f"the policy field {name} must be a boolean")
        setattr(policy, name, value)
    if policy.mode not in MODES:
        raise _bad(f"the policy mode {policy.mode!r} is not one of {list(MODES)}")
    rank = risk_rank(policy.riskCeiling)
    if rank is None:
        raise _bad(f"the policy risk ceiling {policy.riskCeiling!r} is not T0-T3")
    policy.riskCeiling = RISK_TIERS[rank]
    return policy


def _canonical_covered_bytes(bundle) -> bytes:
    """The signed bytes, rejecting a body canonical JSON cannot carry.

    canonical_bytes refuses floats with a plain ValueError; a hand-edited
    bundle carrying one takes the same policy:bad-signature rejection as a
    tampered body instead of crashing every route that loads the policy."""
    try:
        return canonical_bytes(bundle_payload(bundle))
    except ValueError as exc:
        raise PolicyBundleError(
            "policy:bad-signature",
            f"the policy bundle body is not canonical JSON ({exc})") from exc


def verify_policy_bundle(bundle, *, now: datetime, pinned_epoch: int,
                         trusted_keys=None) -> dict:
    """Verify a signed bundle and return its policy fields plus verification.

    Raises PolicyBundleError (a TrustError) with one of the fail-closed
    codes policy:bad-signature, policy:expired, policy:stale-epoch or
    policy:unknown-key.
    """
    parts = _structure(bundle)
    signer_fingerprint = fingerprint(parts["key_bytes"])
    if not _trusted(parts["key_id"], signer_fingerprint, trusted_keys):
        raise PolicyBundleError(
            "policy:unknown-key",
            f"the policy bundle signer {parts['key_id']} is not a pinned key",
            {"signerFingerprint": signer_fingerprint})
    covered = _canonical_covered_bytes(bundle)
    if not verify(parts["key_bytes"], covered, parts["signature_bytes"]):
        raise PolicyBundleError(
            "policy:bad-signature",
            "the policy bundle signature does not cover its content",
            {"signerFingerprint": signer_fingerprint})

    expires_at = parse_timestamp(bundle.get("expiresAt"))
    issued_at = parse_timestamp(bundle.get("issuedAt"))
    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if moment > expires_at:
        raise PolicyBundleError(
            "policy:expired",
            f"the policy bundle expired at {isoformat(expires_at)}",
            {"expiresAt": isoformat(expires_at)})
    if issued_at > moment:
        raise PolicyBundleError(
            "policy:bad-signature",
            f"the policy bundle is not valid before {isoformat(issued_at)}",
            {"issuedAt": isoformat(issued_at)})
    epoch = int(bundle["revocationEpoch"])
    pinned = max(int(pinned_epoch or 0), 0)
    if epoch < pinned:
        raise PolicyBundleError(
            "policy:stale-epoch",
            f"the policy bundle revocation epoch {epoch} is below the pinned "
            f"epoch {pinned}",
            {"epoch": epoch, "pinnedEpoch": pinned})

    policy = coerce_policy(parts["policy"])
    result = asdict(policy)
    result["verification"] = {
        "signatureStatus": "signed",
        "signerFingerprint": signer_fingerprint,
        "warning": None,
        "epoch": epoch,
        "expiresAt": isoformat(expires_at),
        "issuedAt": isoformat(issued_at),
        "keyId": parts["key_id"],
        "pinnedEpoch": pinned,
    }
    return result


def policy_diff(before: Policy, after: Policy) -> list[dict]:
    """The field-by-field difference between two policies, sorted."""
    changes = []
    for name in sorted(POLICY_FIELDS):
        old = getattr(before, name)
        new = getattr(after, name)
        if isinstance(old, list):
            old = sorted(str(item) for item in old)
        if isinstance(new, list):
            new = sorted(str(item) for item in new)
        if old != new:
            changes.append({"field": name, "before": old, "after": new})
    return changes


# -- anchor, kill switch and audit state ---------------------------------


def _marketplace_dir(workspace_dir) -> Path | None:
    """This desk's marketplace state folder, or None when there is no workspace."""
    if workspace_dir is None:
        return None
    return Path(workspace_dir) / "marketplace"


def read_json(path, fallback):
    """Parse a JSON file, returning the fallback for any read or parse failure."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return fallback


def write_json(path, document) -> None:
    """Write a document as pretty, key-sorted JSON, atomically.

    The body is written to a temp file beside the target and replaced into
    place, so a crash mid-write leaves the prior content intact instead of
    truncating state like the kill switch, the anchor or the audit log. This
    is the marketplace's one JSON writer: every state file goes through it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".",
        suffix=".tmp", delete=False)
    temp = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def load_anchor(workspace_dir) -> dict:
    """Read the pinned anchor: the highest revocation epoch and key pins.

    A missing anchor is trust-on-first-use (epoch 0, no pins). An anchor
    that exists but cannot be parsed is answered differently: corrupt is
    set and no key may be trusted, because this desk had pins and nobody
    knows which key was pinned."""
    root = _marketplace_dir(workspace_dir)
    fallback = {"epoch": 0, "fingerprints": []}
    if root is None:
        return fallback
    path = root / ANCHOR_FILE
    if not path.exists():
        return fallback
    raw = read_json(path, None)
    if not isinstance(raw, dict):
        return {**fallback, "corrupt": True}
    epoch = raw.get("epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        epoch = 0
    fingerprints = [
        str(item) for item in raw.get("fingerprints") or ()
        if isinstance(item, str) and item.strip()
    ]
    return {"epoch": epoch, "fingerprints": fingerprints}


def corrupt_anchor_warning() -> str:
    """The amber warning for an anchor that exists but cannot be read."""
    return (
        "the trust anchor exists but cannot be read; no signing key is "
        "trusted and signed policies are rejected until the anchor file is "
        "repaired or removed. The built-in curated policy stays active.")


def write_anchor(workspace_dir, *, epoch: int, fingerprints) -> dict:
    """Persist the anchor, never lowering the pinned epoch."""
    root = _marketplace_dir(workspace_dir)
    if root is None:
        return {"epoch": int(epoch), "fingerprints": sorted(set(fingerprints))}
    current = load_anchor(workspace_dir)
    anchor = {
        "epoch": max(int(epoch), int(current["epoch"])),
        "fingerprints": sorted(set(current["fingerprints"]) | set(fingerprints)),
    }
    write_json(root / ANCHOR_FILE, anchor)
    return anchor


def load_kill_switch(workspace_dir) -> list:
    """The administrator kill-switch overlay, which survives a signed bundle."""
    root = _marketplace_dir(workspace_dir)
    if root is None:
        return []
    raw = read_json(root / KILL_SWITCH_FILE, None)
    if isinstance(raw, list):
        return [str(item) for item in raw if isinstance(item, str) and item.strip()]
    if isinstance(raw, dict):
        return [str(item) for item in raw.get("plugins") or ()
                if isinstance(item, str) and item.strip()]
    return []


def set_kill_switch(workspace_dir, plugin_id: str, enabled: bool) -> list:
    """Turn the kill switch on or off for one plugin (or every plugin)."""
    root = _marketplace_dir(workspace_dir)
    plugin_id = str(plugin_id).strip()
    if not plugin_id:
        raise ValueError("a plugin id is required")
    current = set(load_kill_switch(workspace_dir))
    if enabled:
        current.add(plugin_id)
    else:
        current.discard(plugin_id)
    plugins = sorted(current)
    if root is not None:
        write_json(root / KILL_SWITCH_FILE, {"plugins": plugins,
                                              "updatedAt": isoformat(utc_now())})
    return plugins


def read_audit(workspace_dir) -> list:
    """Read the local audit log, most recent last."""
    root = _marketplace_dir(workspace_dir)
    if root is None:
        return []
    raw = read_json(root / AUDIT_FILE, [])
    return raw if isinstance(raw, list) else []


def append_audit(workspace_dir, action: str, plugin_id: str = "",
                 outcome: str = "", detail: str = "", *, dedupe: bool = False) -> dict:
    """Append one audit event and return it (dedupe skips an exact repeat)."""
    event = {
        "at": isoformat(utc_now()),
        "action": action,
        "pluginId": plugin_id,
        "actor": "local-admin",
        "outcome": outcome,
        "detail": detail,
    }
    root = _marketplace_dir(workspace_dir)
    if root is None:
        return event
    events = read_audit(workspace_dir)
    if dedupe and events:
        last = events[-1]
        if isinstance(last, dict) and all(
                last.get(key) == event[key]
                for key in ("action", "pluginId", "outcome", "detail")):
            return last
    events.append(event)
    write_json(root / AUDIT_FILE, events[-1000:])
    return event


def apply_kill_switch(policy: Policy, workspace_dir) -> Policy:
    """Union the administrator kill-switch overlay into the policy.

    The overlay is separate state, so the switch keeps working while a
    signed bundle is active without editing the signed document.
    """
    overlay = load_kill_switch(workspace_dir)
    if overlay:
        policy.killSwitch = sorted(set(policy.killSwitch or ()) | set(overlay))
    return policy


def failure_verification(exc: TrustError, anchor: dict, path) -> dict:
    """The verification block for a rejected bundle (curated default stays)."""
    details = getattr(exc, "details", {}) or {}
    status = STATUS_BY_CODE.get(exc.code, "tampered")
    warning = (
        f"the imported policy bundle was rejected ({exc.code}): {exc.message}. "
        "The built-in curated policy stays active."
    )
    return {
        "signatureStatus": status,
        "warning": warning,
        "epoch": anchor.get("epoch", 0),
        "signerFingerprint": details.get("signerFingerprint"),
        "expiresAt": details.get("expiresAt"),
        "path": str(path) if path is not None else None,
        "rejectedCode": exc.code,
    }


def verified_verification(verification: dict, path) -> dict:
    """The verification block for an accepted bundle."""
    result = dict(verification)
    result["path"] = str(path) if path is not None else None
    return result
