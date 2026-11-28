"""Signed policy bundles: verification, precedence, fallback and diff."""

import copy
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from trust_fixtures import (
    FUTURE,
    NOW,
    PAST,
    make_key,
    policy_bundle,
    policy_bundle_fields,
    write_policy_bundle,
)

from nexuusbot.marketplace import signed_policy
from nexuusbot.marketplace.policy import (
    default_policy,
    evaluate,
    load_effective_policy,
    policy_payload,
)
from nexuusbot.marketplace.signed_policy import (
    PolicyBundleError,
    fingerprint,
    load_anchor,
    policy_diff,
    sign_policy_bundle,
    verify_policy_bundle,
    write_anchor,
)

SIGNER = make_key("policy-signer")
OTHER = make_key("policy-other")
PIN = fingerprint(SIGNER.public)


def signed_bundle(**fields):
    fields.setdefault("mode", "open")
    fields.setdefault("riskCeiling", "T2")
    fields.setdefault("allowedPublishers", ["zeta", "acme"])
    fields.setdefault("killSwitch", ["bad-plugin"])
    fields.setdefault("retentionDays", 7)
    return policy_bundle(SIGNER, fields=policy_bundle_fields(**fields),
                         revocation_epoch=4)


def write_anchor_file(workspace, epoch, fingerprints):
    folder = Path(workspace) / "marketplace"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "anchor.json").write_text(json.dumps(
        {"epoch": epoch, "fingerprints": list(fingerprints)}), encoding="utf-8")


def write_raw_policy(workspace, document):
    folder = Path(workspace) / "marketplace"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "policy.json").write_text(json.dumps(document), encoding="utf-8")


def bundled_entry(**overrides):
    entry = {
        "id": "sample-plugin",
        "publisher": "agent-desk",
        "category": "time",
        "riskTier": "T1",
        "source": "bundled",
        "signature": {"status": "bundled"},
        "capabilities": {"network": []},
    }
    entry.update(overrides)
    return entry


# -- bundle verification ---------------------------------------------------


def test_signed_bundle_round_trips_and_reports_verification():
    bundle = signed_bundle()
    verified = verify_policy_bundle(bundle, now=NOW, pinned_epoch=4)

    assert verified["mode"] == "open"
    assert verified["riskCeiling"] == "T2"
    assert verified["allowedPublishers"] == ["zeta", "acme"]
    assert verified["killSwitch"] == ["bad-plugin"]
    assert verified["retentionDays"] == 7
    verification = verified["verification"]
    assert verification["signatureStatus"] == "signed"
    assert verification["signerFingerprint"] == PIN
    assert verification["epoch"] == 4
    assert verification["expiresAt"] == FUTURE
    assert verification["keyId"] == "policy-signer"
    assert verification["warning"] is None
    assert "signature" not in signed_policy.bundle_payload(bundle)


def test_tampered_bundle_is_rejected():
    bundle = copy.deepcopy(signed_bundle())
    bundle["policy"]["riskCeiling"] = "T3"

    with pytest.raises(PolicyBundleError) as caught:
        verify_policy_bundle(bundle, now=NOW, pinned_epoch=0)

    assert caught.value.code == "policy:bad-signature"


def test_tampered_signature_is_rejected():
    bundle = copy.deepcopy(signed_bundle())
    value = bundle["signature"]["value"]
    bundle["signature"]["value"] = ("B" if value[0] != "B" else "C") + value[1:]

    with pytest.raises(PolicyBundleError) as caught:
        verify_policy_bundle(bundle, now=NOW, pinned_epoch=0)

    assert caught.value.code == "policy:bad-signature"


def test_expired_bundle_is_rejected():
    bundle = signed_bundle()
    expired = sign_policy_bundle(
        policy_bundle_fields(), seed=SIGNER.seed, key_id=SIGNER.key_id,
        issued_at=NOW - timedelta(days=30), expires_at=PAST, revocation_epoch=0)

    assert bundle["expiresAt"] == FUTURE
    with pytest.raises(PolicyBundleError) as caught:
        verify_policy_bundle(expired, now=NOW, pinned_epoch=0)

    assert caught.value.code == "policy:expired"


def test_bundle_issued_in_the_future_is_rejected():
    bundle = sign_policy_bundle(
        policy_bundle_fields(), seed=SIGNER.seed, key_id=SIGNER.key_id,
        issued_at=NOW + timedelta(hours=1), expires_at=FUTURE, revocation_epoch=0)

    with pytest.raises(PolicyBundleError) as caught:
        verify_policy_bundle(bundle, now=NOW, pinned_epoch=0)

    assert caught.value.code == "policy:bad-signature"


def test_lower_revocation_epoch_than_the_anchor_is_rejected():
    bundle = signed_bundle()
    with pytest.raises(PolicyBundleError) as caught:
        verify_policy_bundle(bundle, now=NOW, pinned_epoch=5)

    assert caught.value.code == "policy:stale-epoch"
    equal = verify_policy_bundle(bundle, now=NOW, pinned_epoch=4)
    assert equal["verification"]["pinnedEpoch"] == 4


def test_unknown_signing_key_is_rejected():
    bundle = signed_bundle()
    pinned = [{"keyId": OTHER.key_id, "publicKey": OTHER.public_b64}]

    with pytest.raises(PolicyBundleError) as caught:
        verify_policy_bundle(bundle, now=NOW, pinned_epoch=0, trusted_keys=pinned)

    assert caught.value.code == "policy:unknown-key"
    assert verify_policy_bundle(
        bundle, now=NOW, pinned_epoch=0,
        trusted_keys=[{"keyId": "policy-signer", "publicKey": SIGNER.public_b64}],
    )["verification"]["signatureStatus"] == "signed"
    assert verify_policy_bundle(
        bundle, now=NOW, pinned_epoch=0, trusted_keys=[PIN],
    )["verification"]["signerFingerprint"] == PIN


def test_structure_errors_fail_closed():
    bundle = signed_bundle()
    for name in ("schemaVersion", "policy", "issuedAt", "expiresAt",
                 "revocationEpoch", "signer", "signature"):
        broken = copy.deepcopy(bundle)
        broken.pop(name)
        with pytest.raises(PolicyBundleError) as caught:
            verify_policy_bundle(broken, now=NOW, pinned_epoch=0)
        assert caught.value.code == "policy:bad-signature"

    bad_mode = copy.deepcopy(bundle)
    bad_mode["policy"]["mode"] = "anarchy"
    # A copied bundle no longer verifies, so re-sign the bad content.
    resigned = sign_policy_bundle(bad_mode["policy"], seed=SIGNER.seed,
                                  key_id=SIGNER.key_id, issued_at=NOW,
                                  expires_at=FUTURE)
    with pytest.raises(PolicyBundleError) as caught:
        verify_policy_bundle(resigned, now=NOW, pinned_epoch=0)
    assert caught.value.code == "policy:bad-signature"


def test_sign_policy_bundle_rejects_unknown_fields():
    with pytest.raises(ValueError):
        sign_policy_bundle({**policy_bundle_fields(), "telemetry": True},
                           seed=SIGNER.seed, key_id=SIGNER.key_id,
                           issued_at=NOW, expires_at=FUTURE)


# -- effective policy precedence ------------------------------------------


def test_signed_bundle_takes_effect_over_built_in(tmp_path):
    write_policy_bundle(tmp_path, SIGNER, fields=policy_bundle_fields(
        mode="open", riskCeiling="T2", allowedPublishers=["acme"]),
        revocation_epoch=3)
    write_anchor_file(tmp_path, 3, [PIN])

    policy, verification = load_effective_policy(tmp_path)

    assert policy.mode == "open"
    assert policy.riskCeiling == "T2"
    assert policy.allowedPublishers == ["acme"]
    assert policy.source == "signed"
    assert policy.signatureStatus == "signed"
    assert verification["signatureStatus"] == "signed"
    assert verification["epoch"] == 3
    assert verification["signerFingerprint"] == PIN
    assert verification["warning"] is None

    payload = policy_payload(policy, verification)
    assert payload["signerFingerprint"] == PIN
    assert payload["expiresAt"] == FUTURE
    assert payload["epoch"] == 3


def test_signed_bundle_beats_unsigned_local_admin(tmp_path):
    write_policy_bundle(tmp_path, SIGNER, revocation_epoch=1)
    policy, verification = load_effective_policy(tmp_path)
    assert policy.source == "signed"

    write_raw_policy(tmp_path, {"mode": "private-only", "riskCeiling": "T0"})
    policy, verification = load_effective_policy(tmp_path)
    assert policy.source == "local-admin"
    assert policy.signatureStatus == "unsigned"
    assert policy.mode == "private-only"


def test_unsigned_local_policy_still_loads(tmp_path):
    write_raw_policy(tmp_path, {
        "mode": "private-only", "riskCeiling": "high",
        "allowedPublishers": ["acme"], "killSwitch": ["legacy-plugin"]})

    policy, verification = load_effective_policy(tmp_path)

    assert policy.mode == "private-only"
    assert policy.riskCeiling == "T3"
    assert policy.allowedPublishers == ["acme"]
    assert policy.killSwitch == ["legacy-plugin"]
    assert policy.source == "local-admin"
    assert verification["signatureStatus"] == "unsigned"
    assert verification["signerFingerprint"] is None


def test_unsigned_overlay_cannot_set_signature_status_or_source(tmp_path):
    write_raw_policy(tmp_path, {"source": "signed",
                                "signatureStatus": "signed"})

    policy, verification = load_effective_policy(tmp_path)

    assert policy.source == "local-admin"
    assert policy.signatureStatus == "unsigned"
    assert verification["signatureStatus"] == "unsigned"


def test_tampered_bundle_falls_back_to_curated_default_and_audits(tmp_path):
    bundle = signed_bundle()
    bundle["policy"]["riskCeiling"] = "T3"
    write_raw_policy(tmp_path, bundle)
    policy, verification = load_effective_policy(tmp_path)

    assert policy.source == "built-in"
    assert policy.mode == "curated"
    assert policy.riskCeiling == "T1"
    assert policy.signatureStatus == "tampered"
    assert verification["rejectedCode"] == "policy:bad-signature"
    assert "amber" not in verification["warning"]  # plain text, UI renders amber
    assert "rejected" in verification["warning"]

    events = signed_policy.read_audit(tmp_path)
    assert [event["action"] for event in events] == ["policy.verify"]
    assert events[0]["outcome"] == "rejected"
    assert events[0]["detail"] == "policy:bad-signature"

    # A second load of the same invalid bundle does not duplicate the event.
    load_effective_policy(tmp_path)
    assert len(signed_policy.read_audit(tmp_path)) == 1


def test_float_in_a_signed_bundle_falls_back_to_curated_and_audits(tmp_path):
    bundle = signed_bundle()
    bundle["policy"]["retentionDays"] = 30.5
    write_raw_policy(tmp_path, bundle)

    policy, verification = load_effective_policy(tmp_path)

    assert policy.source == "built-in"
    assert policy.mode == "curated"
    assert policy.riskCeiling == "T1"
    assert policy.signatureStatus == "tampered"
    assert verification["rejectedCode"] == "policy:bad-signature"
    assert "rejected" in verification["warning"]

    events = signed_policy.read_audit(tmp_path)
    assert [event["action"] for event in events] == ["policy.verify"]
    assert events[0]["outcome"] == "rejected"
    assert events[0]["detail"] == "policy:bad-signature"


def test_expired_bundle_leaves_the_default_active(tmp_path):
    write_raw_policy(tmp_path, sign_policy_bundle(
        policy_bundle_fields(mode="open"), seed=SIGNER.seed,
        key_id=SIGNER.key_id, issued_at=NOW - timedelta(days=60),
        expires_at=PAST, revocation_epoch=0))

    policy, verification = load_effective_policy(tmp_path)

    assert policy.source == "built-in"
    assert policy.mode == "curated"
    assert verification["signatureStatus"] == "expired"
    assert verification["rejectedCode"] == "policy:expired"


def test_anchor_epoch_from_state_rejects_lower_bundle(tmp_path):
    write_policy_bundle(tmp_path, SIGNER, revocation_epoch=1)
    write_anchor_file(tmp_path, 4, [PIN])

    policy, verification = load_effective_policy(tmp_path)

    assert policy.source == "built-in"
    assert verification["signatureStatus"] == "stale-epoch"
    assert verification["epoch"] == 4
    assert signed_policy.read_audit(tmp_path)[0]["detail"] == "policy:stale-epoch"


def test_anchor_fingerprint_pins_the_signer(tmp_path):
    write_policy_bundle(tmp_path, SIGNER)
    write_anchor_file(tmp_path, 0, [fingerprint(OTHER.public)])

    policy, verification = load_effective_policy(tmp_path)

    assert policy.source == "built-in"
    assert verification["signatureStatus"] == "unknown-key"
    assert verification["rejectedCode"] == "policy:unknown-key"


def test_anchor_never_lowers_its_epoch_and_unions_fingerprints(tmp_path):
    write_anchor(tmp_path, epoch=2, fingerprints=[PIN])
    anchor = write_anchor(tmp_path, epoch=1, fingerprints=[fingerprint(OTHER.public)])

    assert anchor["epoch"] == 2
    assert anchor["fingerprints"] == sorted([PIN, fingerprint(OTHER.public)])
    assert load_anchor(tmp_path) == anchor


def test_missing_anchor_means_epoch_zero(tmp_path):
    assert load_anchor(tmp_path) == {"epoch": 0, "fingerprints": []}


def test_corrupt_anchor_is_answered_differently_from_a_missing_one(tmp_path):
    write_anchor_file(tmp_path, 7, [PIN])
    (Path(tmp_path) / "marketplace" / "anchor.json").write_text(
        "{broken", encoding="utf-8")

    corrupt = load_anchor(tmp_path)
    assert corrupt == {"epoch": 0, "fingerprints": [], "corrupt": True}

    # With no policy file at all, the corrupt anchor still warns: the pins
    # this desk once had are gone and nobody knows which key was pinned.
    policy, verification = load_effective_policy(tmp_path)
    assert policy.mode == "curated"
    assert verification["signatureStatus"] == "unsigned"
    assert "anchor" in verification["warning"]

    (Path(tmp_path) / "marketplace" / "anchor.json").unlink()
    policy, verification = load_effective_policy(tmp_path)
    assert verification["warning"] is None


def test_corrupt_anchor_fails_closed_instead_of_trusting_any_key(tmp_path):
    write_anchor_file(tmp_path, 7, [PIN])
    (Path(tmp_path) / "marketplace" / "anchor.json").write_text(
        "{broken", encoding="utf-8")
    write_policy_bundle(tmp_path, SIGNER, revocation_epoch=7)

    policy, verification = load_effective_policy(tmp_path)

    assert policy.source == "built-in"
    assert policy.mode == "curated"
    assert verification["signatureStatus"] == "unknown-key"
    assert verification["rejectedCode"] == "policy:unknown-key"
    assert "anchor" in verification["warning"]
    assert signed_policy.read_audit(tmp_path)[0]["detail"] == "policy:unknown-key"


def test_a_crash_mid_write_leaves_the_prior_state_intact(tmp_path, monkeypatch):
    import os as os_module

    signed_policy.set_kill_switch(tmp_path, "blocked-plugin", True)
    signed_policy.write_anchor(tmp_path, epoch=3, fingerprints=[PIN])
    signed_policy.append_audit(tmp_path, "policy.verify", "", "rejected",
                               "policy:bad-signature")
    market = Path(tmp_path) / "marketplace"
    names = ("kill-switch.json", "anchor.json", "audit.json")
    before = {name: (market / name).read_text(encoding="utf-8")
              for name in names}

    def crash(src, dst):
        raise OSError("the process died between the temp write and the replace")

    monkeypatch.setattr(os_module, "replace", crash)
    with pytest.raises(OSError):
        signed_policy.set_kill_switch(tmp_path, "another-plugin", True)
    with pytest.raises(OSError):
        signed_policy.write_anchor(tmp_path, epoch=9, fingerprints=[PIN])
    with pytest.raises(OSError):
        signed_policy.append_audit(tmp_path, "install", "sample", "ok")

    after = {name: (market / name).read_text(encoding="utf-8")
             for name in names}
    assert after == before
    assert {item.name for item in market.iterdir()} == set(names)


# -- diff, kill switch and payload ----------------------------------------


def test_diff_shape_is_sorted_and_copies_arrays():
    before = default_policy()
    after = policy_bundle_fields(mode="open", riskCeiling="T2",
                                 allowedPublishers=["zeta", "acme"],
                                 networkAllowlist=["api.example.com"])
    from nexuusbot.marketplace.policy import Policy

    diff = policy_diff(before, Policy(**after))

    fields = [change["field"] for change in diff]
    assert fields == sorted(fields)
    assert "mode" in fields and "riskCeiling" in fields
    by_field = {change["field"]: change for change in diff}
    assert by_field["mode"] == {"field": "mode", "before": "curated", "after": "open"}
    assert by_field["riskCeiling"]["after"] == "T2"
    assert by_field["allowedPublishers"]["after"] == ["acme", "zeta"]
    assert by_field["allowedPublishers"]["before"] == []
    assert all(set(change) == {"field", "before", "after"} for change in diff)
    assert "signatureStatus" not in fields and "source" not in fields


def test_kill_switch_makes_an_entry_ineligible(tmp_path):
    plugin = bundled_entry(id="sample-plugin")
    policy = default_policy()

    before = evaluate(plugin, policy)
    assert before["eligible"] is True

    signed_policy.set_kill_switch(tmp_path, "sample-plugin", True)
    policy = signed_policy.apply_kill_switch(policy, tmp_path)
    after = evaluate(plugin, policy)

    assert after["eligible"] is False
    assert [reason["code"] for reason in after["reasons"]] == ["policy:kill-switch"]

    signed_policy.set_kill_switch(tmp_path, "sample-plugin", False)
    restored = evaluate(plugin, signed_policy.apply_kill_switch(default_policy(), tmp_path))
    assert restored["eligible"] is True


def test_kill_switch_overlay_applies_over_signed_bundle(tmp_path):
    write_policy_bundle(tmp_path, SIGNER)
    signed_policy.set_kill_switch(tmp_path, "sample-plugin", True)

    policy, verification = load_effective_policy(tmp_path)

    assert verification["signatureStatus"] == "signed"
    assert policy.source == "signed"
    assert "sample-plugin" in policy.killSwitch
    assert evaluate(bundled_entry(), policy)["eligible"] is False


def test_wildcard_kill_switch_disables_everything(tmp_path):
    signed_policy.set_kill_switch(tmp_path, "*", True)
    policy = signed_policy.apply_kill_switch(default_policy(), tmp_path)

    assert evaluate(bundled_entry(), policy)["eligible"] is False


def test_org_approved_release_satisfies_signature_policy():
    entry = bundled_entry(source="org", signature={"status": "org-approved"})
    assert evaluate(entry, default_policy())["eligible"] is True

    unsigned = bundled_entry(source="org", signature={"status": "unsigned"})
    result = evaluate(unsigned, default_policy())
    assert "policy:signature-required" in [reason["code"] for reason in result["reasons"]]
