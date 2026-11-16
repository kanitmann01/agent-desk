"""Policy matrix: every reason code, and no silent allow on unknown facts."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.marketplace.policy import (
    Policy,
    default_policy,
    evaluate,
    load_effective_policy,
    risk_rank,
)


def entry(**overrides):
    base = {
        "id": "sample-plugin",
        "name": "Sample",
        "version": "1.0.0",
        "publisher": "agent-desk",
        "category": "time",
        "riskTier": "T1",
        "source": "bundled",
        "signature": {"status": "signed"},
        "capabilities": {"network": []},
        "platforms": [],
    }
    base.update(overrides)
    return base


def codes(result):
    return {reason["code"] for reason in result["reasons"]}


def test_default_policy_is_curated_and_fail_closed():
    policy = default_policy()
    assert policy.mode == "curated"
    assert policy.riskCeiling == "T1"
    assert policy.requireSignatures is True
    assert "bundled" in policy.enabledSources
    assert len(policy.enabledSources) == 15
    assert policy.platforms == ["windows"]
    assert policy.retentionDays == 30


def test_risk_rank_contract():
    assert [risk_rank(tier) for tier in ("T0", "T1", "T2", "T3")] == [0, 1, 2, 3]
    assert risk_rank("low") == 1
    assert risk_rank("unknown") is None
    assert risk_rank(None) is None


def test_default_policy_allows_an_ordinary_signed_bundled_plugin():
    result = evaluate(entry(), default_policy())
    assert result == {"eligible": True, "reasons": []}


def test_kill_switch_blocks():
    policy = Policy(killSwitch=["sample-plugin"])
    result = evaluate(entry(), policy)
    assert result["eligible"] is False
    assert codes(result) == {"policy:kill-switch"}


def test_blocked_publisher():
    policy = Policy(allowedPublishers=["trusted-co"])
    result = evaluate(entry(publisher="rogue-co"), policy)
    assert codes(result) == {"policy:blocked-publisher"}


def test_blocked_category():
    policy = Policy(allowedCategories=["time"])
    result = evaluate(entry(category="finance"), policy)
    assert codes(result) == {"policy:blocked-category"}


def test_risk_ceiling_exceeded():
    policy = Policy(riskCeiling="T1")
    result = evaluate(entry(riskTier="T2"), policy)
    assert codes(result) == {"policy:risk-ceiling"}


def test_unknown_risk_never_silently_allowed():
    for missing in ("", None, "T9", "critical"):
        result = evaluate(entry(riskTier=missing), default_policy())
        assert result["eligible"] is False
        assert "policy:risk-ceiling" in codes(result)


def test_missing_risk_tier_is_a_reason():
    raw = entry()
    del raw["riskTier"]
    result = evaluate(raw, default_policy())
    assert result["eligible"] is False
    assert "policy:risk-ceiling" in codes(result)


def test_network_not_allowed_by_default_allowlist():
    raw = entry(
        riskTier="T2",
        capabilities={"network": ["api.example.com"]},
    )
    result = evaluate(raw, Policy(riskCeiling="T2"))
    assert codes(result) == {"policy:network-not-allowed"}


def test_network_allowed_host_passes():
    raw = entry(
        riskTier="T2",
        capabilities={"network": ["api.example.com"]},
    )
    policy = Policy(riskCeiling="T2",
                    networkAllowlist=["api.example.com"])
    assert evaluate(raw, policy) == {"eligible": True, "reasons": []}


def test_network_wildcard_allowlist_passes():
    raw = entry(
        riskTier="T2",
        capabilities={"network": ["api.example.com"]},
    )
    policy = Policy(riskCeiling="T2", networkAllowlist=["*.example.com"])
    assert evaluate(raw, policy)["eligible"] is True


def test_signature_required_blocks_unsigned():
    for status in ("missing", "unverified", ""):
        result = evaluate(
            entry(signature={"status": status}), default_policy())
        assert result["eligible"] is False
        assert "policy:signature-required" in codes(result)


def test_signature_requirement_can_be_switched_off():
    policy = Policy(requireSignatures=False)
    result = evaluate(entry(signature={"status": "missing"}), policy)
    assert result["eligible"] is True


def test_revoked_release_blocks():
    result = evaluate(entry(revoked=True), default_policy())
    assert codes(result) == {"policy:revoked"}


def test_revocation_epoch_blocks():
    policy = Policy(minRevocationEpoch=4)
    result = evaluate(entry(revocationEpoch=5), policy)
    assert codes(result) == {"policy:revoked"}


def test_private_mode_blocks_peer_unless_installed():
    policy = Policy(mode="private-only")
    blocked = evaluate(entry(source="peer"), policy)
    assert codes(blocked) == {"policy:mode-private"}
    allowed = evaluate(entry(source="peer"), policy, installed=True)
    assert allowed == {"eligible": True, "reasons": []}


def test_private_mode_allows_org_and_bundled():
    policy = Policy(mode="private-only")
    for source in ("org", "bundled"):
        assert evaluate(entry(source=source), policy)["eligible"] is True


def test_source_not_enabled():
    policy = Policy(enabledSources=["bundled"])
    result = evaluate(entry(source="peer"), policy)
    assert codes(result) == {"policy:source-not-enabled"}


def test_missing_source_is_not_enabled():
    raw = entry()
    del raw["source"]
    result = evaluate(raw, default_policy())
    assert codes(result) == {"policy:source-not-enabled"}


def test_platform_mismatch():
    policy = Policy(platforms=["windows"])
    result = evaluate(entry(platforms=["macos"]), policy)
    assert codes(result) == {"policy:platform"}


def test_platform_intersection_passes():
    policy = Policy(platforms=["windows", "macos"])
    assert evaluate(entry(platforms=["macos"]), policy)["eligible"] is True


def test_every_failing_rule_is_reported_together():
    raw = entry(
        publisher="rogue-co",
        category="finance",
        riskTier="T3",
        capabilities={"network": ["api.example.com"]},
        signature={"status": "missing"},
        revoked=True,
        source="peer",
        platforms=["macos"],
    )
    policy = Policy(
        mode="private-only",
        allowedPublishers=["trusted-co"],
        allowedCategories=["time"],
        enabledSources=["bundled"],
        platforms=["windows"],
    )
    result = evaluate(raw, policy)
    assert result["eligible"] is False
    assert codes(result) == {
        "policy:blocked-publisher",
        "policy:blocked-category",
        "policy:risk-ceiling",
        "policy:network-not-allowed",
        "policy:signature-required",
        "policy:revoked",
        "policy:mode-private",
        "policy:source-not-enabled",
        "policy:platform",
    }


def test_open_mode_skips_publisher_and_category_lists():
    policy = Policy(mode="open", allowedPublishers=["trusted-co"],
                    allowedCategories=["time"])
    result = evaluate(entry(publisher="rogue-co", category="finance"), policy)
    assert result["eligible"] is True


def test_missing_fields_never_silently_allow():
    result = evaluate({"id": "bare"}, default_policy())
    assert result["eligible"] is False
    assert {"policy:risk-ceiling", "policy:signature-required",
            "policy:source-not-enabled"} <= codes(result)


def test_non_dict_entry_is_ineligible():
    result = evaluate(None, default_policy())
    assert result["eligible"] is False
    assert result["reasons"]


def test_load_effective_policy_merges_local_admin_file(tmp_path):
    folder = tmp_path / "marketplace"
    folder.mkdir()
    (folder / "policy.json").write_text(json.dumps({
        "mode": "private-only",
        "riskCeiling": "T2",
        "allowedPublishers": ["agent-desk"],
        "killSwitch": ["bad-plugin"],
        "requireSignatures": False,
        "retentionDays": 7,
        "platforms": ["windows", "macos"],
    }), encoding="utf-8")
    policy, verification = load_effective_policy(tmp_path)
    assert policy.mode == "private-only"
    assert policy.riskCeiling == "T2"
    assert policy.allowedPublishers == ["agent-desk"]
    assert policy.killSwitch == ["bad-plugin"]
    assert policy.requireSignatures is False
    assert policy.retentionDays == 7
    assert policy.source == "local-admin"
    assert verification["warning"] is None


def test_load_effective_policy_invalid_json_falls_back_with_warning(tmp_path):
    folder = tmp_path / "marketplace"
    folder.mkdir()
    (folder / "policy.json").write_text("{not json", encoding="utf-8")
    policy, verification = load_effective_policy(tmp_path)
    assert policy.mode == "curated"
    assert policy.riskCeiling == "T1"
    assert verification["warning"]
    assert "could not be read" in verification["warning"]


def test_load_effective_policy_unknown_risk_ceiling_falls_back_to_t1(tmp_path):
    folder = tmp_path / "marketplace"
    folder.mkdir()
    (folder / "policy.json").write_text(
        json.dumps({"riskCeiling": "extreme"}), encoding="utf-8")
    policy, verification = load_effective_policy(tmp_path)
    assert policy.riskCeiling == "T1"
    assert verification["warning"]


def test_load_effective_policy_missing_file_is_quiet(tmp_path):
    policy, verification = load_effective_policy(tmp_path)
    assert policy.mode == "curated"
    assert verification["warning"] is None


def test_yanked_plugin_is_ineligible():
    result = evaluate(entry(yanked=True), default_policy())
    assert result["eligible"] is False
    assert "policy:yanked" in codes(result)


def test_quarantined_plugin_is_ineligible():
    result = evaluate(entry(quarantined=True), default_policy())
    assert result["eligible"] is False
    assert "policy:quarantined" in codes(result)


def test_deprecated_plugin_stays_eligible():
    result = evaluate(
        entry(deprecated={"version": "1.0.0", "reason": "superseded"}),
        default_policy())
    assert result["eligible"] is True
    assert codes(result) == set()
