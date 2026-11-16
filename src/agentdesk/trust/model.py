"""TUF-lite trust metadata: roots, publisher certs, releases, revocations.

Parsing is strict: unknown keys are malformed metadata and fail closed with
trust:bad-signature. Verification checks signatures, expiry and epochs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import ed25519
from .canonical import b64u_decode, canonical_bytes, verify_envelope
from .errors import TrustError

_HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")
_PROVENANCE_KINDS = {"dns", "github", "manual"}


# --- dataclasses ---------------------------------------------------------


@dataclass(frozen=True)
class TrustKey:
    key_id: str
    public_key: bytes


@dataclass(frozen=True)
class SignatureProof:
    key_id: str
    signature: bytes


@dataclass(frozen=True)
class RootMetadata:
    threshold: int
    keys: tuple[TrustKey, ...]
    epoch: int
    expires_at: str
    signatures: tuple[SignatureProof, ...] = ()

    def key_for(self, key_id: str) -> TrustKey | None:
        for key in self.keys:
            if key.key_id == key_id:
                return key
        return None

    def payload(self) -> dict:
        return {
            "threshold": self.threshold,
            "keys": [
                {"keyId": key.key_id, "publicKey": _b64u(key.public_key)}
                for key in self.keys
            ],
            "epoch": self.epoch,
            "expiresAt": self.expires_at,
        }


@dataclass(frozen=True)
class PublisherCert:
    publisher_id: str
    key_id: str
    public_key: bytes
    provenance: dict
    not_before: str
    expires_at: str
    signatures: tuple[SignatureProof, ...] = ()

    def payload(self) -> dict:
        return {
            "publisherId": self.publisher_id,
            "keyId": self.key_id,
            "publicKey": _b64u(self.public_key),
            "provenance": dict(self.provenance),
            "notBefore": self.not_before,
            "expiresAt": self.expires_at,
        }


@dataclass(frozen=True)
class ReleaseStatement:
    plugin_id: str
    version: str
    digest: str
    category: str
    changelog: str
    min_host: str
    released_at: str
    expires_at: str
    envelope: dict | None = None

    def payload(self) -> dict:
        return {
            "pluginId": self.plugin_id,
            "version": self.version,
            "digest": self.digest,
            "category": self.category,
            "changelog": self.changelog,
            "minHost": self.min_host,
            "releasedAt": self.released_at,
            "expiresAt": self.expires_at,
        }


@dataclass(frozen=True)
class RevocationList:
    epoch: int
    issued_at: str
    expires_at: str
    publishers: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    releases: tuple[tuple[str, str], ...] = ()
    signatures: tuple[SignatureProof, ...] = ()

    def payload(self) -> dict:
        return {
            "epoch": self.epoch,
            "issuedAt": self.issued_at,
            "expiresAt": self.expires_at,
            "revoked": {
                "publishers": list(self.publishers),
                "keys": list(self.keys),
                "releases": [
                    {"id": plugin_id, "version": version}
                    for plugin_id, version in self.releases
                ],
            },
        }

    def is_revoked(
        self,
        publisher_id: str | None = None,
        key_id: str | None = None,
        plugin_id: str | None = None,
        version: str | None = None,
    ) -> bool:
        if publisher_id is not None and publisher_id in self.publishers:
            return True
        if key_id is not None and key_id in self.keys:
            return True
        if plugin_id is not None and version is not None:
            return (plugin_id, version) in self.releases
        return False


# --- parsing helpers -----------------------------------------------------


def _malformed(what: str, detail: str = "") -> TrustError:
    message = f"malformed {what}"
    if detail:
        message = f"{message}: {detail}"
    return TrustError("trust:bad-signature", message)


def _raw_bytes(value: Any, what: str) -> bytes:
    if isinstance(value, Path):
        return value.read_bytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise _malformed(what, "expected JSON bytes")


def _load_document(value: Any, what: str) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    raw = _raw_bytes(value, what)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _malformed(what, "invalid JSON") from exc
    if not isinstance(document, dict):
        raise _malformed(what, "document must be an object")
    return document


def _as_mapping(value: Any, what: str) -> dict:
    if not isinstance(value, Mapping):
        raise _malformed(what, "expected an object")
    return dict(value)


def _reject_unknown(value: Mapping, allowed: set[str], what: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _malformed(what, f"unknown key {unknown[0]}")


def _string(value: Any, what: str, detail: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise _malformed(what, detail)
    return value


def _integer(value: Any, what: str, detail: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _malformed(what, detail)
    if minimum is not None and value < minimum:
        raise _malformed(what, detail)
    return value


def _parse_time(value: Any, what: str, detail: str) -> datetime:
    text = _string(value, what, detail)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _malformed(what, detail) from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _now(now: Any = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        moment = now
    elif isinstance(now, str):
        try:
            moment = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _malformed("now", "expected ISO 8601") from exc
    else:
        raise _malformed("now", "expected datetime or ISO 8601")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _fresh(expires_at: str, now: datetime, what: str) -> None:
    if now > _parse_time(expires_at, what, "expiresAt"):
        raise TrustError("trust:expired", f"{what} expired at {expires_at}")


def _not_before(not_before: str, now: datetime, what: str) -> None:
    if now < _parse_time(not_before, what, "notBefore"):
        raise TrustError("trust:expired", f"{what} is not valid before {not_before}")


def _b64u(data: bytes) -> str:
    from .canonical import b64u_encode

    return b64u_encode(data)


def _b64_field(value: Any, length: int, what: str, detail: str) -> bytes:
    text = _string(value, what, detail)
    try:
        data = b64u_decode(text)
    except (ValueError, TypeError) as exc:
        raise _malformed(what, detail) from exc
    if len(data) != length:
        raise _malformed(what, detail)
    return data


def _sha256_field(value: Any, what: str, detail: str) -> str:
    text = _string(value, what, detail)
    if not _HEX_64.match(text):
        raise _malformed(what, detail)
    return text.lower()


def _parse_signatures(value: Any, what: str) -> tuple[SignatureProof, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise _malformed(what, "signatures must be a non-empty list")
    proofs = []
    for item in value:
        entry = _as_mapping(item, f"{what} signature")
        _reject_unknown(entry, {"keyId", "signature"}, f"{what} signature")
        proofs.append(
            SignatureProof(
                key_id=_string(entry.get("keyId"), f"{what} signature", "keyId"),
                signature=_b64_field(
                    entry.get("signature"), 64, f"{what} signature", "signature"
                ),
            )
        )
    return tuple(proofs)


def _parse_envelope(value: Any, what: str) -> dict:
    entry = _as_mapping(value, f"{what} envelope")
    _reject_unknown(
        entry,
        {"keyId", "algorithm", "signature", "digest", "signedAt"},
        f"{what} envelope",
    )
    if entry.get("algorithm") != "ed25519":
        raise _malformed(f"{what} envelope", "algorithm must be ed25519")
    _string(entry.get("keyId"), f"{what} envelope", "keyId")
    _b64_field(entry.get("signature"), 64, f"{what} envelope", "signature")
    _sha256_field(entry.get("digest"), f"{what} envelope", "digest")
    _parse_time(entry.get("signedAt"), f"{what} envelope", "signedAt")
    return entry


# --- parsers -------------------------------------------------------------


def parse_root(value: Any) -> RootMetadata:
    document = _load_document(value, "root")
    _reject_unknown(document, {"payload", "signatures"}, "root")
    payload = _as_mapping(document.get("payload"), "root payload")
    _reject_unknown(
        payload, {"threshold", "keys", "epoch", "expiresAt"}, "root payload"
    )
    threshold = _integer(payload.get("threshold"), "root payload", "threshold", minimum=1)
    raw_keys = payload.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise _malformed("root payload", "keys must be a non-empty list")
    keys = []
    seen = set()
    for item in raw_keys:
        entry = _as_mapping(item, "root key")
        _reject_unknown(entry, {"keyId", "publicKey"}, "root key")
        key_id = _string(entry.get("keyId"), "root key", "keyId")
        if key_id in seen:
            raise _malformed("root key", f"duplicate keyId {key_id}")
        seen.add(key_id)
        keys.append(
            TrustKey(
                key_id=key_id,
                public_key=_b64_field(entry.get("publicKey"), 32, "root key", "publicKey"),
            )
        )
    if threshold > len(keys):
        raise _malformed("root payload", "threshold exceeds the key count")
    epoch = _integer(payload.get("epoch"), "root payload", "epoch", minimum=1)
    expires_at = _string(payload.get("expiresAt"), "root payload", "expiresAt")
    _parse_time(expires_at, "root payload", "expiresAt")
    return RootMetadata(
        threshold=threshold,
        keys=tuple(keys),
        epoch=epoch,
        expires_at=expires_at,
        signatures=_parse_signatures(document.get("signatures"), "root"),
    )


def parse_publisher_cert(value: Any) -> PublisherCert:
    document = _load_document(value, "publisher certificate")
    _reject_unknown(document, {"payload", "signatures"}, "publisher certificate")
    payload = _as_mapping(document.get("payload"), "publisher certificate payload")
    _reject_unknown(
        payload,
        {"publisherId", "keyId", "publicKey", "provenance", "notBefore", "expiresAt"},
        "publisher certificate payload",
    )
    provenance = _as_mapping(
        payload.get("provenance"), "publisher certificate provenance"
    )
    _reject_unknown(
        provenance, {"kind", "value"}, "publisher certificate provenance"
    )
    kind = _string(
        provenance.get("kind"), "publisher certificate provenance", "kind"
    )
    if kind not in _PROVENANCE_KINDS:
        raise _malformed("publisher certificate provenance", "unknown provenance kind")
    value_ = _string(
        provenance.get("value"), "publisher certificate provenance", "value"
    )
    not_before = _string(
        payload.get("notBefore"), "publisher certificate payload", "notBefore"
    )
    expires_at = _string(
        payload.get("expiresAt"), "publisher certificate payload", "expiresAt"
    )
    _parse_time(not_before, "publisher certificate payload", "notBefore")
    _parse_time(expires_at, "publisher certificate payload", "expiresAt")
    return PublisherCert(
        publisher_id=_string(
            payload.get("publisherId"), "publisher certificate payload", "publisherId"
        ),
        key_id=_string(
            payload.get("keyId"), "publisher certificate payload", "keyId"
        ),
        public_key=_b64_field(
            payload.get("publicKey"),
            32,
            "publisher certificate payload",
            "publicKey",
        ),
        provenance={"kind": kind, "value": value_},
        not_before=not_before,
        expires_at=expires_at,
        signatures=_parse_signatures(
            document.get("signatures"), "publisher certificate"
        ),
    )


def parse_release_statement(value: Any) -> ReleaseStatement:
    document = _load_document(value, "release statement")
    _reject_unknown(document, {"payload", "signature"}, "release statement")
    payload = _as_mapping(document.get("payload"), "release statement payload")
    _reject_unknown(
        payload,
        {
            "pluginId",
            "version",
            "digest",
            "category",
            "changelog",
            "minHost",
            "releasedAt",
            "expiresAt",
        },
        "release statement payload",
    )
    released_at = _string(
        payload.get("releasedAt"), "release statement payload", "releasedAt"
    )
    expires_at = _string(
        payload.get("expiresAt"), "release statement payload", "expiresAt"
    )
    _parse_time(released_at, "release statement payload", "releasedAt")
    _parse_time(expires_at, "release statement payload", "expiresAt")
    return ReleaseStatement(
        plugin_id=_string(
            payload.get("pluginId"), "release statement payload", "pluginId"
        ),
        version=_string(
            payload.get("version"), "release statement payload", "version"
        ),
        digest=_sha256_field(
            payload.get("digest"), "release statement payload", "digest"
        ),
        category=_string(
            payload.get("category"),
            "release statement payload",
            "category",
            allow_empty=True,
        ),
        changelog=_string(
            payload.get("changelog"),
            "release statement payload",
            "changelog",
            allow_empty=True,
        ),
        min_host=_string(
            payload.get("minHost"),
            "release statement payload",
            "minHost",
            allow_empty=True,
        ),
        released_at=released_at,
        expires_at=expires_at,
        envelope=_parse_envelope(document.get("signature"), "release statement"),
    )


def parse_revocations(value: Any) -> RevocationList:
    document = _load_document(value, "revocation list")
    _reject_unknown(document, {"payload", "signatures"}, "revocation list")
    payload = _as_mapping(document.get("payload"), "revocation list payload")
    _reject_unknown(
        payload, {"epoch", "issuedAt", "expiresAt", "revoked"}, "revocation list payload"
    )
    revoked = _as_mapping(payload.get("revoked"), "revocation list revoked")
    _reject_unknown(revoked, {"publishers", "keys", "releases"}, "revocation list revoked")

    def identifiers(name: str) -> tuple[str, ...]:
        items = revoked.get(name, [])
        if not isinstance(items, list):
            raise _malformed("revocation list revoked", f"{name} must be a list")
        return tuple(
            _string(item, "revocation list revoked", f"{name} entry") for item in items
        )

    raw_releases = revoked.get("releases", [])
    if not isinstance(raw_releases, list):
        raise _malformed("revocation list revoked", "releases must be a list")
    releases = []
    for item in raw_releases:
        entry = _as_mapping(item, "revocation release")
        _reject_unknown(entry, {"id", "version"}, "revocation release")
        releases.append(
            (
                _string(entry.get("id"), "revocation release", "id"),
                _string(entry.get("version"), "revocation release", "version"),
            )
        )
    issued_at = _string(payload.get("issuedAt"), "revocation list payload", "issuedAt")
    expires_at = _string(
        payload.get("expiresAt"), "revocation list payload", "expiresAt"
    )
    _parse_time(issued_at, "revocation list payload", "issuedAt")
    _parse_time(expires_at, "revocation list payload", "expiresAt")
    return RevocationList(
        epoch=_integer(payload.get("epoch"), "revocation list payload", "epoch", minimum=1),
        issued_at=issued_at,
        expires_at=expires_at,
        publishers=identifiers("publishers"),
        keys=identifiers("keys"),
        releases=tuple(releases),
        signatures=_parse_signatures(document.get("signatures"), "revocation list"),
    )


# --- verification --------------------------------------------------------


def _threshold_count(
    payload: dict,
    signatures: tuple[SignatureProof, ...],
    key_source: RootMetadata,
    what: str,
) -> int:
    data = canonical_bytes(payload)
    seen = set()
    for proof in signatures:
        key = key_source.key_for(proof.key_id)
        if key is None:
            raise TrustError(
                "trust:bad-signature",
                f"{what} signed by unlisted key {proof.key_id}",
            )
        if proof.key_id in seen:
            continue
        if ed25519.verify(key.public_key, data, proof.signature):
            seen.add(proof.key_id)
    return len(seen)


def verify_root(root_file_bytes: Any, anchor: Any, now: Any = None) -> RootMetadata:
    raw = _raw_bytes(root_file_bytes, "root")
    if anchor is None:
        raise TrustError("trust:no-anchor", "no pinned root anchor supplied")
    if isinstance(anchor, (str, Path)):
        path = Path(anchor)
        try:
            anchor = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TrustError("trust:no-anchor", "pinned root anchor is unreadable") from exc
    if not isinstance(anchor, Mapping):
        raise TrustError("trust:no-anchor", "pinned root anchor is malformed")
    digest = anchor.get("sha256")
    epoch = anchor.get("epoch")
    if not isinstance(digest, str) or not digest:
        raise TrustError("trust:no-anchor", "pinned root anchor has no sha256")
    if isinstance(epoch, bool) or not isinstance(epoch, int):
        raise TrustError("trust:no-anchor", "pinned root anchor has no epoch")
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, digest.lower()):
        raise TrustError(
            "trust:bad-signature", "root metadata does not match the pinned anchor"
        )
    root = parse_root(raw)
    moment = _now(now)
    _fresh(root.expires_at, moment, "root metadata")
    count = _threshold_count(root.payload(), root.signatures, root, "root metadata")
    if count < root.threshold:
        raise TrustError(
            "trust:bad-signature",
            f"root metadata has {count} valid signatures, needs {root.threshold}",
        )
    if epoch != root.epoch:
        raise TrustError(
            "trust:stale-epoch",
            f"anchor epoch {epoch} does not match root epoch {root.epoch}",
        )
    return root


def verify_publisher_cert(cert: Any, root: RootMetadata, now: Any = None) -> PublisherCert:
    if not isinstance(root, RootMetadata):
        raise TrustError("trust:bad-signature", "malformed root metadata")
    document = cert if isinstance(cert, PublisherCert) else parse_publisher_cert(cert)
    moment = _now(now)
    _fresh(document.expires_at, moment, "publisher certificate")
    _not_before(document.not_before, moment, "publisher certificate")
    count = _threshold_count(
        document.payload(), document.signatures, root, "publisher certificate"
    )
    if count < root.threshold:
        raise TrustError(
            "trust:bad-signature",
            f"publisher certificate has {count} valid signatures, needs {root.threshold}",
        )
    return document


def release_pin_payload(plugin_id: str, version: str, digest: str) -> dict:
    return {"pluginId": plugin_id, "version": version, "digest": digest}


def verify_release_pin(
    plugin_id: str,
    version: str,
    digest: str,
    signature: str | None,
    cert: PublisherCert,
    now: Any = None,
) -> None:
    if not signature:
        raise TrustError(
            "trust:unsigned",
            f"release {plugin_id}@{version} has no signature",
        )
    _fresh(cert.expires_at, _now(now), "publisher certificate")
    try:
        raw_signature = b64u_decode(signature)
    except (ValueError, TypeError) as exc:
        raise TrustError(
            "trust:bad-signature", "release signature is not base64url"
        ) from exc
    message = canonical_bytes(release_pin_payload(plugin_id, version, digest))
    if not ed25519.verify(cert.public_key, message, raw_signature):
        raise TrustError(
            "trust:bad-signature",
            f"release signature does not verify for {plugin_id}@{version}",
        )


def verify_release(value: Any, cert: PublisherCert, now: Any = None) -> ReleaseStatement:
    if not isinstance(cert, PublisherCert):
        raise TrustError("trust:bad-signature", "malformed publisher certificate")
    statement = value if isinstance(value, ReleaseStatement) else parse_release_statement(value)
    if statement.envelope is None:
        raise TrustError(
            "trust:unsigned",
            f"release {statement.plugin_id}@{statement.version} has no signature",
        )
    envelope = statement.envelope
    if envelope.get("keyId") != cert.key_id:
        raise TrustError(
            "trust:unknown-publisher",
            f"release {statement.plugin_id}@{statement.version} is signed by an unknown key",
        )
    verify_envelope(statement.payload(), envelope, cert.public_key)
    _fresh(statement.expires_at, _now(now), "release statement")
    return statement


def verify_revocations(value: Any, root: RootMetadata, now: Any = None) -> RevocationList:
    if not isinstance(root, RootMetadata):
        raise TrustError("trust:bad-signature", "malformed root metadata")
    revocations = value if isinstance(value, RevocationList) else parse_revocations(value)
    count = _threshold_count(
        revocations.payload(), revocations.signatures, root, "revocation list"
    )
    if count < root.threshold:
        raise TrustError(
            "trust:bad-signature",
            f"revocation list has {count} valid signatures, needs {root.threshold}",
        )
    if revocations.epoch != root.epoch:
        raise TrustError(
            "trust:stale-epoch",
            f"revocation epoch {revocations.epoch} does not match root epoch {root.epoch}",
        )
    _fresh(revocations.expires_at, _now(now), "revocation list")
    return revocations


# --- store ---------------------------------------------------------------


@dataclass
class TrustStore:
    root: RootMetadata
    certs_by_publisher: dict[str, PublisherCert]
    revocations: RevocationList
    anchor: dict
    releases: dict[tuple[str, str], ReleaseStatement] = field(default_factory=dict)

    @classmethod
    def from_directory(
        cls,
        path: Any,
        *,
        now: Any = None,
        anchor_path: Any = None,
    ) -> "TrustStore":
        base = Path(path)
        anchor_file = Path(anchor_path) if anchor_path is not None else base / "anchor.json"
        if not anchor_file.is_file():
            raise TrustError(
                "trust:no-anchor", f"no pinned anchor at {anchor_file.as_posix()}"
            )
        try:
            anchor = json.loads(anchor_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TrustError("trust:no-anchor", "pinned root anchor is unreadable") from exc
        root_file = base / "root.json"
        if not root_file.is_file():
            raise TrustError("trust:no-anchor", "root metadata is missing")
        root = verify_root(root_file.read_bytes(), anchor, now=now)

        certs: dict[str, PublisherCert] = {}
        by_key: dict[str, PublisherCert] = {}
        publishers_dir = base / "publishers"
        if publishers_dir.is_dir():
            for file_path in sorted(publishers_dir.glob("*.json")):
                cert = verify_publisher_cert(file_path.read_bytes(), root, now=now)
                if cert.publisher_id in certs:
                    raise _malformed(
                        "publisher certificate",
                        f"duplicate publisher {cert.publisher_id}",
                    )
                if cert.key_id in by_key:
                    raise _malformed(
                        "publisher certificate", f"duplicate keyId {cert.key_id}"
                    )
                certs[cert.publisher_id] = cert
                by_key[cert.key_id] = cert

        revocations_file = base / "revocations.json"
        if revocations_file.is_file():
            revocations = verify_revocations(revocations_file.read_bytes(), root, now=now)
        else:
            revocations = RevocationList(
                epoch=root.epoch,
                issued_at="",
                expires_at=root.expires_at,
            )

        store = cls(root=root, certs_by_publisher=certs, revocations=revocations, anchor=anchor)

        # Release statements are parsed here but not enforced: the store is
        # an index of signed material, and every consumer verifies the
        # statement for the exact release it is about to install. That
        # keeps revocation and expiry checks on the install path where the
        # publisher, key and release are all known.
        releases: dict[tuple[str, str], ReleaseStatement] = {}
        releases_dir = base / "releases"
        if releases_dir.is_dir():
            for file_path in sorted(releases_dir.glob("*/*.json")):
                statement = parse_release_statement(file_path.read_bytes())
                key = (statement.plugin_id, statement.version)
                if key in releases:
                    raise _malformed(
                        "release statement",
                        f"duplicate release {statement.plugin_id}@{statement.version}",
                    )
                releases[key] = statement
        store.releases = releases
        return store

    # -- lookups ------------------------------------------------------

    def check(self, now: Any = None) -> None:
        moment = _now(now)
        _fresh(self.root.expires_at, moment, "root metadata")
        self._check_revocations(moment)
        self._assert_within_revocation_ttl(
            self.root.expires_at, "root metadata", moment)
        for cert in self.certs_by_publisher.values():
            verify_publisher_cert(cert, self.root, now=moment)
            self._assert_within_revocation_ttl(
                cert.expires_at, "publisher certificate", moment)
            if self.revocations.is_revoked(cert.publisher_id, cert.key_id):
                raise TrustError(
                    "trust:revoked",
                    f"publisher {cert.publisher_id} or its key is revoked",
                )

    def _check_revocations(self, now: datetime) -> None:
        if self.revocations.epoch != self.root.epoch:
            raise TrustError(
                "trust:stale-epoch",
                f"revocation epoch {self.revocations.epoch} is stale for root epoch {self.root.epoch}",
            )
        if self.revocations.expires_at:
            _fresh(self.revocations.expires_at, now, "revocation list")

    def _assert_within_revocation_ttl(self, expires_at: str, what: str,
                                      now: datetime) -> None:
        """Metadata may not outlive the revocation snapshot that covers it.

        A certificate or release that stays valid longer than the signed
        revocation list would let a revoked publisher survive until the
        next refresh, so the mismatch fails closed as a stale epoch.
        """
        self._check_revocations(now)
        if not self.revocations.expires_at:
            return
        if _parse_time(expires_at, what, "expiresAt") > _parse_time(
                self.revocations.expires_at, "revocation list", "expiresAt"):
            raise TrustError(
                "trust:stale-epoch",
                f"{what} expires after the revocation list; refresh revocations",
            )

    def cert_for(
        self, publisher_id: str, key_id: str | None = None, now: Any = None
    ) -> PublisherCert:
        cert = self.certs_by_publisher.get(publisher_id)
        if cert is None:
            raise TrustError(
                "trust:unknown-publisher",
                f"no publisher certificate for {publisher_id}",
            )
        if key_id is not None and key_id != cert.key_id:
            raise TrustError(
                "trust:unknown-publisher",
                f"publisher {publisher_id} has no key {key_id}",
            )
        verify_publisher_cert(cert, self.root, now=now)
        self._assert_within_revocation_ttl(
            cert.expires_at, "publisher certificate", _now(now))
        self.assert_not_revoked(publisher_id, cert.key_id, now=now)
        return cert

    def assert_not_revoked(
        self,
        publisher_id: str | None,
        key_id: str | None,
        plugin_id: str | None = None,
        version: str | None = None,
        now: Any = None,
    ) -> None:
        self._check_revocations(_now(now))
        if self.revocations.is_revoked(publisher_id, key_id, plugin_id, version):
            detail = plugin_id or publisher_id or key_id or "release"
            if plugin_id and version:
                detail = f"{plugin_id}@{version}"
            raise TrustError("trust:revoked", f"{detail} is revoked")

    def has_release(self, plugin_id: str, version: str) -> bool:
        return (plugin_id, version) in self.releases

    def verify_release(
        self,
        plugin_id: str,
        version: str,
        cert: PublisherCert | None = None,
        *,
        now: Any = None,
    ) -> ReleaseStatement:
        if cert is None:
            raise TrustError(
                "trust:unknown-publisher",
                f"no publisher certificate supplied for {plugin_id}@{version}",
            )
        cert = self.cert_for(cert.publisher_id, cert.key_id, now=now)
        statement = self.releases.get((plugin_id, version))
        if statement is None:
            raise TrustError(
                "trust:unsigned",
                f"no signed release statement for {plugin_id}@{version}",
            )
        verify_release(statement, cert, now=now)
        self._assert_within_revocation_ttl(
            statement.expires_at, "release statement", _now(now))
        if statement.plugin_id != plugin_id or statement.version != version:
            raise TrustError(
                "trust:bad-signature",
                f"release statement does not describe {plugin_id}@{version}",
            )
        self.assert_not_revoked(
            cert.publisher_id, cert.key_id, plugin_id, version, now=now
        )
        return statement

    def verify_pin(
        self,
        plugin_id: str,
        version: str,
        digest: str,
        signature: str | None,
        cert: PublisherCert,
        *,
        now: Any = None,
    ) -> None:
        cert = self.cert_for(cert.publisher_id, cert.key_id, now=now)
        verify_release_pin(plugin_id, version, digest, signature, cert, now=now)
        self.assert_not_revoked(
            cert.publisher_id, cert.key_id, plugin_id, version, now=now
        )
