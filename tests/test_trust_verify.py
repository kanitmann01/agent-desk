"""Trust chain verification and fail-closed install behaviour."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta

import pytest

from nexuusbot.registry.install import install_from_registry, read_lock, tree_digest
from nexuusbot.trust import TrustError
from nexuusbot.trust.canonical import canonical_bytes
from nexuusbot.trust.model import (
    TrustStore,
    release_pin_payload,
    verify_publisher_cert,
    verify_release,
    verify_revocations,
    verify_root,
)

from plugins_fixtures import VALID_PLUGIN_DIR
from trust_fixtures import (
    FUTURE,
    NOW,
    NOW_ISO,
    PAST,
    make_key,
    make_keys,
    pin_payload,
    pin_signature,
    release_payload,
    write_publisher,
    write_release,
    write_revocations,
    write_root,
)

PLUGIN_ID = "sales-delta-widget"
VERSION = "1.2.0"


def _tamper_b64(value: str) -> str:
    table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    first = table[(table.index(value[0]) + 1) % len(table)]
    return first + value[1:]


def make_scene(
    tmp_path,
    *,
    schema_version: int = 2,
    signed: bool = True,
    pinned_signature: str | None = None,
    no_statement: bool = False,
    statement_tamper: bool = False,
    statement_digest: str | None = None,
    statement_expires_at: str = FUTURE,
    cert_expires_at: str = FUTURE,
    revoked: dict | None = None,
    root_epoch: int = 1,
    revocations_epoch: int | None = None,
    revocations_expires_at: str = FUTURE,
    publisher_id: str = "acme-tools",
):
    root_keys = make_keys(3)
    publisher_key = make_key("publisher")
    trust_dir = tmp_path / "trust"
    write_root(trust_dir, root_keys, threshold=2, epoch=root_epoch)
    write_publisher(trust_dir, publisher_id, publisher_key, root_keys,
                    expires_at=cert_expires_at)
    write_revocations(
        trust_dir,
        root_keys,
        epoch=root_epoch if revocations_epoch is None else revocations_epoch,
        expires_at=revocations_expires_at,
        revoked=revoked,
    )

    registry = tmp_path / "registry"
    plugin_dir = registry / "plugins" / PLUGIN_ID / VERSION
    shutil.copytree(VALID_PLUGIN_DIR, plugin_dir)
    digest = tree_digest(plugin_dir)

    if not no_statement:
        payload = release_payload(
            PLUGIN_ID,
            VERSION,
            statement_digest or digest,
            expires_at=statement_expires_at,
        )
        write_release(trust_dir, PLUGIN_ID, VERSION, payload, publisher_key,
                      tamper=statement_tamper)

    release = {
        "version": VERSION,
        "sha256": digest,
        "source": "local",
        "changelog": "test release",
        "minHost": "0.1.0",
        "yanked": False,
    }
    if schema_version >= 2:
        release["digest"] = digest
        if signed:
            signature = pinned_signature or pin_signature(
                PLUGIN_ID, VERSION, digest, publisher_key
            )
            release["signature"] = signature
        plugin = {
            "id": PLUGIN_ID,
            "name": "Sales 24h Delta",
            "publisher": publisher_id,
            "category": "demo",
            "tags": ["sales", "demo"],
            "latest": VERSION,
            "risk": "low",
            "class": "declarative",
            "releases": [release],
        }
        index_document = {
            "schemaVersion": 2,
            "version": 7,
            "generatedAt": NOW_ISO,
            "publishers": {
                publisher_id: {
                    "keyId": publisher_key.key_id,
                    "provenance": {"kind": "manual", "value": "test"},
                }
            },
            "plugins": [plugin],
        }
    else:
        plugin = {
            "id": PLUGIN_ID,
            "publisher": publisher_id,
            "latest": VERSION,
            "risk": "low",
            "class": "declarative",
            "releases": [release],
        }
        index_document = {"schemaVersion": 1, "plugins": [plugin]}

    registry.mkdir(parents=True, exist_ok=True)
    (registry / "index.json").write_text(
        json.dumps(index_document, indent=2, sort_keys=True), encoding="utf-8"
    )
    store = TrustStore.from_directory(trust_dir, now=NOW)
    return registry, store, {
        "root_keys": root_keys,
        "publisher_key": publisher_key,
        "trust_dir": trust_dir,
        "digest": digest,
        "plugin_dir": plugin_dir,
        "index": index_document,
    }


def install(scene, tmp_path, *, trust=True):
    registry, store, info = scene
    return install_from_registry(
        registry,
        PLUGIN_ID,
        version=VERSION,
        destination=tmp_path / "installed",
        trust=store if trust else None,
        now=NOW,
    )


# --- root metadata -------------------------------------------------------


def test_root_threshold_verifies(tmp_path):
    root_keys = make_keys(3)
    write_root(tmp_path, root_keys, threshold=2)
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    raw = (tmp_path / "root.json").read_bytes()
    metadata = verify_root(raw, anchor, now=NOW)
    assert metadata.epoch == 1
    assert metadata.threshold == 2
    assert [key.key_id for key in metadata.keys] == [key.key_id for key in root_keys]


def test_root_below_threshold_fails_closed(tmp_path):
    root_keys = make_keys(3)
    write_root(tmp_path, root_keys, threshold=2, signers=[root_keys[0]])
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    with pytest.raises(TrustError) as excinfo:
        verify_root((tmp_path / "root.json").read_bytes(), anchor, now=NOW)
    assert excinfo.value.code == "trust:bad-signature"


def test_root_without_anchor_fails_closed(tmp_path):
    root_keys = make_keys(3)
    write_root(tmp_path, root_keys)
    with pytest.raises(TrustError) as excinfo:
        verify_root((tmp_path / "root.json").read_bytes(), None, now=NOW)
    assert excinfo.value.code == "trust:no-anchor"


def test_root_digest_mismatch_fails_closed(tmp_path):
    root_keys = make_keys(3)
    write_root(tmp_path, root_keys)
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    anchor["sha256"] = "0" * 64
    with pytest.raises(TrustError) as excinfo:
        verify_root((tmp_path / "root.json").read_bytes(), anchor, now=NOW)
    assert excinfo.value.code == "trust:bad-signature"


def test_root_epoch_mismatch_is_stale(tmp_path):
    root_keys = make_keys(3)
    write_root(tmp_path, root_keys, epoch=1)
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    anchor["epoch"] = 2
    with pytest.raises(TrustError) as excinfo:
        verify_root((tmp_path / "root.json").read_bytes(), anchor, now=NOW)
    assert excinfo.value.code == "trust:stale-epoch"


def test_expired_root_fails_closed(tmp_path):
    root_keys = make_keys(3)
    write_root(tmp_path, root_keys, expires_at=PAST)
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    with pytest.raises(TrustError) as excinfo:
        verify_root((tmp_path / "root.json").read_bytes(), anchor, now=NOW)
    assert excinfo.value.code == "trust:expired"


def test_root_unknown_signer_fails_closed(tmp_path):
    root_keys = make_keys(3)
    outsider = make_key("outsider")
    write_root(tmp_path, root_keys, signers=[root_keys[0], outsider])
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    with pytest.raises(TrustError) as excinfo:
        verify_root((tmp_path / "root.json").read_bytes(), anchor, now=NOW)
    assert excinfo.value.code == "trust:bad-signature"


def test_root_unknown_key_is_rejected(tmp_path):
    root_keys = make_keys(3)
    write_root(tmp_path, root_keys)
    document = json.loads((tmp_path / "root.json").read_text(encoding="utf-8"))
    document["payload"]["unexpected"] = True
    (tmp_path / "root.json").write_text(json.dumps(document), encoding="utf-8")
    anchor = {"sha256": __import__("hashlib").sha256(
        (tmp_path / "root.json").read_bytes()
    ).hexdigest(), "epoch": 1}
    with pytest.raises(TrustError) as excinfo:
        verify_root((tmp_path / "root.json").read_bytes(), anchor, now=NOW)
    assert excinfo.value.code == "trust:bad-signature"
    assert "malformed" in str(excinfo.value)


# --- publisher certificates ---------------------------------------------


def test_publisher_cert_verifies():
    root_keys = make_keys(3)
    root_payload = {
        "threshold": 2,
        "keys": [{"keyId": key.key_id, "publicKey": key.public_b64}
                 for key in root_keys],
        "epoch": 1,
        "expiresAt": FUTURE,
    }
    root_signatures = [
        {"keyId": key.key_id,
         "signature": __import__("base64").urlsafe_b64encode(
             key.sign(canonical_bytes(root_payload))
         ).decode().rstrip("=")}
        for key in root_keys[:2]
    ]
    root_doc = {"payload": root_payload, "signatures": root_signatures}
    raw = json.dumps(root_doc).encode("utf-8")
    from nexuusbot.trust.model import parse_root

    root = parse_root(raw)

    publisher = make_key("publisher")
    payload = {
        "publisherId": "acme-tools",
        "keyId": publisher.key_id,
        "publicKey": publisher.public_b64,
        "provenance": {"kind": "manual", "value": "test"},
        "notBefore": "2026-01-01T00:00:00+00:00",
        "expiresAt": FUTURE,
    }
    cert_raw = json.dumps({
        "payload": payload,
        "signatures": [
            {"keyId": key.key_id,
             "signature": __import__("base64").urlsafe_b64encode(
                 key.sign(canonical_bytes(payload))
             ).decode().rstrip("=")}
            for key in root_keys[:2]
        ],
    }).encode("utf-8")
    cert = verify_publisher_cert(cert_raw, root, now=NOW)
    assert cert.publisher_id == "acme-tools"
    assert cert.key_id == publisher.key_id


def test_expired_publisher_cert_fails(tmp_path):
    with pytest.raises(TrustError) as excinfo:
        make_scene(tmp_path, cert_expires_at=PAST)
    assert excinfo.value.code == "trust:expired"


def test_cert_signed_by_unlisted_key_fails(tmp_path):
    root_keys = make_keys(3)
    publisher = make_key("publisher")
    trust_dir = tmp_path / "trust"
    write_root(trust_dir, root_keys)
    write_publisher(trust_dir, "acme-tools", publisher, root_keys,
                    signers=[make_key("outsider")])
    with pytest.raises(TrustError) as excinfo:
        TrustStore.from_directory(trust_dir, now=NOW)
    assert excinfo.value.code == "trust:bad-signature"


# --- release statements --------------------------------------------------


def test_release_statement_verifies(tmp_path):
    scene = make_scene(tmp_path)
    registry, store, info = scene
    cert = store.cert_for("acme-tools", now=NOW)
    raw = (info["trust_dir"] / "releases" / PLUGIN_ID / f"{VERSION}.json").read_bytes()
    statement = verify_release(raw, cert, now=NOW)
    assert statement.plugin_id == PLUGIN_ID
    assert statement.version == VERSION
    assert statement.digest == info["digest"]


def test_release_statement_expired_fails(tmp_path):
    scene = make_scene(tmp_path, statement_expires_at=PAST)
    registry, store, info = scene
    cert = store.cert_for("acme-tools", now=NOW)
    raw = (info["trust_dir"] / "releases" / PLUGIN_ID / f"{VERSION}.json").read_bytes()
    with pytest.raises(TrustError) as excinfo:
        verify_release(raw, cert, now=NOW)
    assert excinfo.value.code == "trust:expired"


def test_release_statement_tampered_fails(tmp_path):
    scene = make_scene(tmp_path, statement_tamper=True)
    registry, store, info = scene
    cert = store.cert_for("acme-tools", now=NOW)
    raw = (info["trust_dir"] / "releases" / PLUGIN_ID / f"{VERSION}.json").read_bytes()
    with pytest.raises(TrustError) as excinfo:
        verify_release(raw, cert, now=NOW)
    assert excinfo.value.code == "trust:bad-signature"


def test_missing_release_statement_is_unsigned(tmp_path):
    scene = make_scene(tmp_path, no_statement=True)
    registry, store, info = scene
    cert = store.cert_for("acme-tools", now=NOW)
    with pytest.raises(TrustError) as excinfo:
        store.verify_release(PLUGIN_ID, VERSION, cert, now=NOW)
    assert excinfo.value.code == "trust:unsigned"


# --- revocations ---------------------------------------------------------


def test_revocation_list_verifies(tmp_path):
    root_keys = make_keys(3)
    trust_dir = tmp_path / "trust"
    write_root(trust_dir, root_keys)
    write_revocations(trust_dir, root_keys)
    anchor = json.loads((trust_dir / "anchor.json").read_text(encoding="utf-8"))
    root = verify_root((trust_dir / "root.json").read_bytes(), anchor, now=NOW)
    revocations = verify_revocations(
        (trust_dir / "revocations.json").read_bytes(), root, now=NOW
    )
    assert revocations.epoch == 1
    assert revocations.releases == ()


def test_revocation_epoch_mismatch_is_stale(tmp_path):
    with pytest.raises(TrustError) as excinfo:
        make_scene(tmp_path, root_epoch=2, revocations_epoch=1)
    assert excinfo.value.code == "trust:stale-epoch"


def test_expired_revocations_fail_closed(tmp_path):
    with pytest.raises(TrustError) as excinfo:
        make_scene(tmp_path, revocations_expires_at=PAST)
    assert excinfo.value.code == "trust:expired"


def test_metadata_outliving_the_revocation_ttl_is_stale(tmp_path):
    short_ttl = (datetime.fromisoformat(NOW_ISO) + timedelta(days=30)).isoformat()
    scene = make_scene(tmp_path, revocations_expires_at=short_ttl)
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:stale-epoch"


# --- install path --------------------------------------------------------


def test_v2_signed_release_installs(tmp_path):
    scene = make_scene(tmp_path)
    result = install(scene, tmp_path)
    assert result["ok"] is True
    assert result["sha256"] == scene[2]["digest"]
    entry = read_lock(tmp_path / "installed", PLUGIN_ID)
    assert entry["publisher"] == "acme-tools"
    assert entry["category"] == "demo"
    assert entry["sha256"] == scene[2]["digest"]


def test_v2_unsigned_with_trust_fails(tmp_path):
    scene = make_scene(tmp_path, signed=False)
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:unsigned"


def test_v2_unsigned_without_trust_still_installs(tmp_path):
    scene = make_scene(tmp_path, signed=False)
    result = install(scene, tmp_path, trust=False)
    assert result["ok"] is True


def test_v1_with_trust_requires_statement_and_verifies(tmp_path):
    scene = make_scene(tmp_path, schema_version=1)
    result = install(scene, tmp_path)
    assert result["ok"] is True
    assert read_lock(tmp_path / "installed", PLUGIN_ID)["publisher"] == "acme-tools"


def test_v1_without_trust_keeps_legacy_behaviour(tmp_path):
    scene = make_scene(tmp_path, schema_version=1, no_statement=True)
    result = install(scene, tmp_path, trust=False)
    assert result["ok"] is True


def test_v1_with_trust_and_no_statement_is_unsigned(tmp_path):
    scene = make_scene(tmp_path, schema_version=1, no_statement=True)
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:unsigned"


def test_revoked_publisher_fails_install(tmp_path):
    scene = make_scene(tmp_path, revoked={"publishers": ["acme-tools"]})
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:revoked"


def test_revoked_key_fails_install(tmp_path):
    scene = make_scene(tmp_path, revoked={"keys": [make_key("publisher").key_id]})
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:revoked"


def test_revoked_release_fails_install(tmp_path):
    scene = make_scene(
        tmp_path,
        revoked={"releases": [{"id": PLUGIN_ID, "version": VERSION}]},
    )
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:revoked"


def test_unknown_publisher_fails_install(tmp_path):
    scene = make_scene(tmp_path, publisher_id="ghost")
    # Build a store that has no cert for "ghost": rewrite certs to acme-tools.
    registry, store, info = scene
    from nexuusbot.trust.model import TrustStore

    bare_dir = tmp_path / "bare-trust"
    root_keys = make_keys(3)
    write_root(bare_dir, root_keys)
    write_revocations(bare_dir, root_keys)
    ghost_store = TrustStore.from_directory(bare_dir, now=NOW)
    with pytest.raises(TrustError) as excinfo:
        install_from_registry(
            registry,
            PLUGIN_ID,
            version=VERSION,
            destination=tmp_path / "installed",
            trust=ghost_store,
            now=NOW,
        )
    assert excinfo.value.code == "trust:unknown-publisher"


def test_tampered_pin_signature_fails_install(tmp_path):
    scene = make_scene(tmp_path)
    signature = scene[2]["index"]["plugins"][0]["releases"][0]["signature"]
    scene[2]["index"]["plugins"][0]["releases"][0]["signature"] = _tamper_b64(signature)
    (scene[0] / "index.json").write_text(
        json.dumps(scene[2]["index"], indent=2), encoding="utf-8"
    )
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:bad-signature"


def test_tampered_statement_signature_fails_install(tmp_path):
    scene = make_scene(tmp_path, statement_tamper=True)
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:bad-signature"


def test_statement_digest_mismatch_fails_install(tmp_path):
    scene = make_scene(tmp_path, statement_digest="0" * 64)
    with pytest.raises(TrustError) as excinfo:
        install(scene, tmp_path)
    assert excinfo.value.code == "trust:bad-signature"


def test_missing_anchor_fails_from_directory(tmp_path):
    trust_dir = tmp_path / "trust"
    root_keys = make_keys(3)
    write_root(trust_dir, root_keys)
    (trust_dir / "anchor.json").unlink()
    with pytest.raises(TrustError) as excinfo:
        TrustStore.from_directory(trust_dir, now=NOW)
    assert excinfo.value.code == "trust:no-anchor"


def test_pin_payload_is_canonical_and_stable():
    first = pin_payload(PLUGIN_ID, VERSION, "a" * 64)
    second = release_pin_payload(PLUGIN_ID, VERSION, "a" * 64)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert canonical_bytes(first) == b'{"digest":"' + b"a" * 64 + b'","pluginId":"sales-delta-widget","version":"1.2.0"}'
