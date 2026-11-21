"""Enterprise policy for the plugin marketplace.

A policy is an unsigned local admin document today (T13 adds signed
imports). Every decision fails closed: an entry whose risk tier or
signature status cannot be read is ineligible, with a reason that names
the missing fact, never silently allowed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlsplit

POLICY_FILE = "policy.json"

RISK_TIERS = ("T0", "T1", "T2", "T3")
RISK_RANK = {tier: rank for rank, tier in enumerate(RISK_TIERS)}
# Registry v1 indexes label risk low/medium/high; map them onto the tiers.
RISK_ALIASES = {"internal": "T0", "low": "T1", "medium": "T2", "high": "T3"}

# The twelve declarative data source types, plus the catalog source labels.
DATA_SOURCES = (
    "excel-watch",
    "json-watch",
    "http-get",
    "calendar-read",
    "mail-digest",
    "outlook-brief",
    "research-brief",
    "csv-watch",
    "markdown-watch",
    "manual-metric",
    "desk-state",
    "compare",
    "aggregate",
)
CATALOG_SOURCES = ("bundled", "org", "peer")
DEFAULT_SOURCES = CATALOG_SOURCES + DATA_SOURCES


@dataclass
class Policy:
    """The effective marketplace policy."""

    mode: str = "curated"
    allowedPublishers: list = field(default_factory=list)
    allowedCategories: list = field(default_factory=list)
    riskCeiling: str = "T1"
    networkAllowlist: list = field(default_factory=list)
    enabledSources: list = field(default_factory=lambda: list(DEFAULT_SOURCES))
    killSwitch: list = field(default_factory=list)
    retentionDays: int = 30
    bodyIngest: bool = False
    updateChannel: str = "manual"
    versionPolicy: str = "pinned"
    platforms: list = field(default_factory=lambda: ["windows"])
    minRevocationEpoch: int = 0
    requireSignatures: bool = True
    signatureStatus: str = "unsigned"
    source: str = "built-in"


def default_policy() -> Policy:
    """The built-in default: curated, T1 ceiling, signatures required."""
    return Policy()


def risk_rank(tier) -> int | None:
    """Rank a risk tier, or None when the tier is missing or unknown."""
    if not isinstance(tier, str):
        return None
    value = tier.strip()
    if value in RISK_RANK:
        return RISK_RANK[value]
    alias = RISK_ALIASES.get(value.lower())
    return RISK_RANK[alias] if alias else None


def _apply_kill_switch(policy: Policy, workspace_dir) -> Policy:
    """Union the administrator kill-switch overlay into a policy."""
    from agentdesk.marketplace import signed_policy
    return signed_policy.apply_kill_switch(policy, workspace_dir)


def _load_signed_policy(workspace_dir, raw: dict, path, verification: dict,
                        anchor: dict):
    """Verify a signed bundle and turn it into the effective policy."""
    from agentdesk.marketplace import signed_policy
    from agentdesk.trust import TrustError

    # A corrupt anchor means the pin list is required and empty: no key is
    # trusted, never a silent reset to trust-on-first-use for any signer.
    if anchor.get("corrupt"):
        trusted_keys: list = []
    else:
        trusted_keys = anchor["fingerprints"] or None
    try:
        result = signed_policy.verify_policy_bundle(
            raw,
            now=signed_policy.utc_now(),
            pinned_epoch=anchor["epoch"],
            trusted_keys=trusted_keys,
        )
    except TrustError as exc:
        verification.update(
            signed_policy.failure_verification(exc, anchor, path))
        if anchor.get("corrupt"):
            verification["warning"] = signed_policy.corrupt_anchor_warning()
        signed_policy.append_audit(
            workspace_dir, "policy.verify", "", "rejected", exc.code, dedupe=True)
        # Fail closed on the built-in curated default, never the rejected body.
        fallback = default_policy()
        fallback.signatureStatus = verification["signatureStatus"]
        return _apply_kill_switch(fallback, workspace_dir), verification

    policy = Policy(**{name: result[name] for name in signed_policy.POLICY_FIELDS})
    policy.signatureStatus = "signed"
    policy.source = "signed"
    verification.update(
        signed_policy.verified_verification(result["verification"], path))
    return _apply_kill_switch(policy, workspace_dir), verification


def load_effective_policy(workspace_dir) -> tuple[Policy, dict]:
    """Load <workspace>/marketplace/policy.json over the defaults.

    A document carrying schemaVersion and signature is a signed bundle and
    is verified before any field takes effect. Returns (policy,
    verification) where verification carries the fields the /policy route
    exposes: signatureStatus, warning, epoch, signerFingerprint, expiresAt.
    A missing file is not a warning; invalid JSON or a rejected bundle
    falls back to the built-in default with a warning and never raises.
    """
    policy = default_policy()
    verification = {
        "signatureStatus": policy.signatureStatus,
        "warning": None,
        "epoch": 0,
        "signerFingerprint": None,
        "expiresAt": None,
        "path": None,
    }
    if workspace_dir is None:
        return policy, verification
    from agentdesk.marketplace import signed_policy
    anchor = signed_policy.load_anchor(workspace_dir)
    if anchor.get("corrupt"):
        verification["warning"] = signed_policy.corrupt_anchor_warning()
    path = Path(workspace_dir) / "marketplace" / POLICY_FILE
    verification["path"] = str(path)
    if not path.is_file():
        return _apply_kill_switch(policy, workspace_dir), verification
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        verification["warning"] = (
            f"policy at {path} could not be read ({exc}); using the built-in default"
        )
        return _apply_kill_switch(policy, workspace_dir), verification
    if not isinstance(raw, dict):
        verification["warning"] = (
            f"policy at {path} must be a JSON object; using the built-in default"
        )
        return _apply_kill_switch(policy, workspace_dir), verification
    if signed_policy.looks_signed(raw):
        return _load_signed_policy(workspace_dir, raw, path, verification,
                                   anchor)

    # signatureStatus and source are loader-owned: an unsigned overlay
    # cannot claim a signature or a provenance nobody verified.
    for key, expected in (
        ("mode", str),
        ("riskCeiling", str),
        ("updateChannel", str),
        ("versionPolicy", str),
    ):
        if key in raw and isinstance(raw[key], expected):
            setattr(policy, key, raw[key])
    for key in ("allowedPublishers", "allowedCategories", "networkAllowlist",
                "enabledSources", "killSwitch", "platforms"):
        if key in raw and isinstance(raw[key], list) and all(
                isinstance(item, str) for item in raw[key]):
            setattr(policy, key, list(raw[key]))
    for key in ("retentionDays", "minRevocationEpoch"):
        if key in raw and isinstance(raw[key], int) and not isinstance(raw[key], bool):
            setattr(policy, key, raw[key])
    for key in ("bodyIngest", "requireSignatures"):
        if key in raw and isinstance(raw[key], bool):
            setattr(policy, key, raw[key])

    if policy.mode not in ("open", "curated", "private-only"):
        verification["warning"] = (
            f"unknown policy mode {policy.mode!r}; falling back to curated"
        )
        policy.mode = "curated"
    if risk_rank(policy.riskCeiling) is None:
        verification["warning"] = (
            f"unknown risk ceiling {policy.riskCeiling!r}; falling back to T1"
        )
        policy.riskCeiling = "T1"
    else:
        policy.riskCeiling = RISK_TIERS[risk_rank(policy.riskCeiling)]
    policy.source = "local-admin"
    return _apply_kill_switch(policy, workspace_dir), verification


def _reason(code: str, message: str) -> dict:
    """One ineligibility reason in the shape the UI renders."""
    return {"code": code, "message": message}


def _scope_host(value) -> str:
    """Reduce a network scope to its host.

    A URL, host/path and host:port all work; the result is lowercased, and an
    empty string means the scope named no host."""
    text = str(value).strip()
    if "://" in text:
        return (urlsplit(text).hostname or "").lower()
    return text.split("/")[0].split(":")[0].lower()


def _host_allowed(host: str, patterns) -> bool:
    """True when a host matches any allowlist pattern.

    A pattern may be a bare glob over the host or a URL, in which case only its
    hostname is matched; matching is case-insensitive."""
    for pattern in patterns or ():
        text = str(pattern)
        if "://" in text:
            if fnmatch(host, (urlsplit(text).hostname or "").lower()):
                return True
        elif fnmatch(host, text.lower()):
            return True
    return False


def _network_hosts(entry) -> list:
    """The hosts an entry would contact, from the most specific source available.

    A catalog capability list wins, then a top-level networkHosts list, then
    the manifest's optional network allow block; an entry that declares none
    is an empty list."""
    capabilities = entry.get("capabilities")
    if isinstance(capabilities, dict):
        network = capabilities.get("network")
        if isinstance(network, list):
            return [str(host) for host in network if str(host).strip()]
    network = entry.get("networkHosts")
    if isinstance(network, list):
        return [str(host) for host in network if str(host).strip()]
    permissions = entry.get("optionalPermissions")
    if isinstance(permissions, dict):
        block = permissions.get("network")
        if isinstance(block, dict) and isinstance(block.get("allow"), list):
            return [str(host) for host in block["allow"] if str(host).strip()]
    return []


def evaluate(entry, policy: Policy, *, installed: bool = False,
             network_hosts=None) -> dict:
    """Decide whether one catalog entry is eligible under the policy.

    Every failing rule contributes one reason, so the UI can explain all
    of them at once. Missing or unreadable facts always produce a reason.
    """
    reasons: list[dict] = []
    if not isinstance(entry, dict):
        return {"eligible": False, "reasons": [
            _reason("policy:source-not-enabled", "the catalog entry is unreadable")]}

    plugin_id = str(entry.get("id") or "")
    source = entry.get("source")
    publisher = str(entry.get("publisher") or "")
    category = str(entry.get("category") or "")

    if plugin_id in set(policy.killSwitch or ()) or "*" in set(policy.killSwitch or ()):
        reasons.append(_reason(
            "policy:kill-switch",
            f"{plugin_id or 'this plugin'} is disabled by the administrator kill switch"))

    # Yank and quarantine are governance records written by the admin routes.
    # Both stop installs and updates; deprecation is advisory and stays
    # eligible with its warning carried on the entry.
    if entry.get("yanked"):
        reasons.append(_reason(
            "policy:yanked",
            f"{plugin_id or 'this plugin'} was yanked by the administrator"))
    if entry.get("quarantined"):
        reasons.append(_reason(
            "policy:quarantined",
            f"{plugin_id or 'this plugin'} is quarantined pending review"))

    if policy.mode in ("curated", "private-only"):
        allowed = set(policy.allowedPublishers or ())
        if allowed and publisher not in allowed:
            reasons.append(_reason(
                "policy:blocked-publisher",
                f"publisher {publisher or '(missing)'} is not on the allowed list"))
        categories = set(policy.allowedCategories or ())
        if categories and category not in categories:
            reasons.append(_reason(
                "policy:blocked-category",
                f"category {category or '(missing)'} is not on the allowed list"))

    rank = risk_rank(entry.get("riskTier"))
    ceiling = risk_rank(policy.riskCeiling)
    if rank is None:
        reasons.append(_reason(
            "policy:risk-ceiling",
            "the entry does not declare a known risk tier (T0-T3)"))
    elif ceiling is None or rank > ceiling:
        reasons.append(_reason(
            "policy:risk-ceiling",
            f"risk tier {RISK_TIERS[rank]} exceeds the policy ceiling "
            f"{policy.riskCeiling or '(missing)'}"))

    hosts = list(network_hosts) if network_hosts is not None else _network_hosts(entry)
    for host_value in hosts:
        host = _scope_host(host_value)
        if not host or not _host_allowed(host, policy.networkAllowlist):
            reasons.append(_reason(
                "policy:network-not-allowed",
                f"network host {host or host_value!r} is not on the policy allowlist"))

    signature = entry.get("signature")
    status = signature.get("status") if isinstance(signature, dict) else None
    # An org publication the administrator approved in the admin surface is
    # the organization's own release: the approval event is its signature of
    # record, and only the org catalog can carry that status.
    signature_ok = status in ("signed", "bundled") or (
        source == "org" and status == "org-approved")
    if policy.requireSignatures and not signature_ok:
        reasons.append(_reason(
            "policy:signature-required",
            f"the entry signature is {status or 'missing'}; the policy requires "
            "a signed release"))

    revoked = bool(entry.get("revoked")) or bool(entry.get("revokedAt"))
    try:
        epoch = int(entry.get("revocationEpoch") or 0)
    except (TypeError, ValueError):
        revoked = True
        epoch = 0
    if epoch > int(policy.minRevocationEpoch or 0):
        revoked = True
    if revoked:
        reasons.append(_reason(
            "policy:revoked",
            "the release is revoked at or after the policy's revocation epoch"))

    if policy.mode == "private-only" and not installed and source not in ("org", "bundled"):
        reasons.append(_reason(
            "policy:mode-private",
            f"private-only mode serves org and bundled plugins, not {source or 'unknown'}"))

    enabled = set(policy.enabledSources or ())
    if source not in enabled:
        reasons.append(_reason(
            "policy:source-not-enabled",
            f"catalog source {source or '(missing)'} is not enabled"))

    platforms = entry.get("platforms")
    if isinstance(platforms, list) and platforms:
        wanted = {str(item).lower() for item in policy.platforms or ()}
        offered = {str(item).lower() for item in platforms}
        if not (wanted & offered):
            reasons.append(_reason(
                "policy:platform",
                f"the entry supports {sorted(offered)} but the policy platform is "
                f"{sorted(wanted) or '(none)'}"))

    return {"eligible": not reasons, "reasons": reasons}


def policy_payload(policy: Policy, verification: dict) -> dict:
    """The JSON body for GET /api/marketplace/policy."""
    payload = asdict(policy)
    payload["signatureStatus"] = verification.get(
        "signatureStatus", policy.signatureStatus)
    payload["warning"] = verification.get("warning")
    payload["epoch"] = verification.get("epoch", policy.minRevocationEpoch)
    payload["signerFingerprint"] = verification.get("signerFingerprint")
    payload["expiresAt"] = verification.get("expiresAt")
    return payload
