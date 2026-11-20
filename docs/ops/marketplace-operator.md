# Marketplace operator guide

This is for the IT operator who runs Nexuus Bot for one person on a managed Windows laptop. It covers installs, publishing, policy, audit, the kill switch, the one-time retirement cleanup and recovery. Authoring is in `docs/design/plugin-authoring-v2.md`, the build and AppLocker story is in `docs/ops/distribution.md`, and licensing is in `docs/licensing.md`.

Nexuus Bot is a single-user, loopback-only app. The marketplace runs in the same process, reads local catalog files, and makes no marketplace network requests of its own. Everything below happens inside one Windows user profile.

## Where the marketplace keeps its state

The data folder defaults to `%LOCALAPPDATA%\AgentDesk` and can be moved with `AGENTDESK_DATA`. Marketplace state is in `<data folder>\workspace\marketplace`:

| File | What it holds |
| --- | --- |
| `policy.json` | The effective policy: either an unsigned field overlay or an imported signed bundle. |
| `anchor.json` | The pinned revocation epoch and the SHA-256 fingerprints of policy signing keys that have been imported. |
| `kill-switch.json` | Blocked plugin ids, including the wildcard `*`. Separate from `policy.json`. |
| `audit.json` | The local audit log, capped at the last 1000 events. |
| `governance.json` | Deprecate, yank and quarantine records written by the Admin page. |
| `org-catalog.json` | Releases approved after pending review. |
| `peer-catalog.json` | Catalogs shared by paired desks. |
| `pending\` | Submissions waiting for review, one JSON file each. |
| `reports.json` | Problem reports filed from plugin and publisher pages. |
| `validation.json` | The last validator run. |

Installed plugins live under `<data folder>\plugins`, and their data under `<data folder>\plugin-data`.

To back up, stop Nexuus Bot, copy the whole data folder, then start it again. To restore, stop it, put the copied folder back, start it. Do not copy `policy.json`, `anchor.json` or `kill-switch.json` between machines unless you mean to move the policy identity too.

## Turn on admin mode

Admin mode is off by default. Every admin request checks the environment variable on the running process, so set it before starting the server and restart to change it:

```powershell
$env:AGENTDESK_MARKETPLACE_ADMIN = "1"
python -m agentdesk.server --no-browser
```

Then open `/marketplace/admin` in the app. While the variable is not exactly `1`, the admin endpoints answer 403 with code `admin:disabled`, the Admin page says "Admin mode is off", and nothing is served there, not even the audit export.

Admin mode is not a role and does not add a second user. The app is still a single local session. Every audit event records the actor as `local-admin`.

What admin mode unlocks: the snapshot at `GET /api/marketplace/admin`, approval and rejection of pending publications, signed policy import, the kill switch, and the audit export.

## Install a plugin

1. Open `/marketplace`. Discover, Search and Category all read the same catalog.
2. Open a plugin's page and choose Install. The consent sheet lists the scopes the plugin asks for. Accept to install, Cancel to stop.
3. Check `/marketplace/installed` afterwards: pinned version, pinned digest, status, pilot views, data size and validated date.

The server resolves the requested source and version against the catalog entry. If the request carries a SHA-256, it must match the catalog pin. Before anything is written it recomputes the staged tree digest and compares it to the catalog pin; a missing pin or a mismatch is `409 install:digest-mismatch`. The install then runs the shared validator on the staged files and records their tree digest. Cryptographic publisher signatures are not re-verified at install: the signature status is a catalog label that policy checks. A refusal is a single policy reason, not a generic failure:

| Code | Meaning |
| --- | --- |
| `catalog:not-found` | No catalog entry for that id, source and version. |
| `install:digest-mismatch` | The digest offered does not match the catalog entry. |
| `install:source-unavailable` | The catalog entry exists but no plugin folder was found. |
| `policy:kill-switch` | The plugin, or `*`, is on the kill switch. |
| `policy:blocked-publisher` | The publisher is not in `allowedPublishers`. |
| `policy:blocked-category` | The category is not in `allowedCategories`. |
| `policy:risk-ceiling` | The release risk tier is above `riskCeiling`. |
| `policy:network-not-allowed` | A requested network host is not in `networkAllowlist`. |
| `policy:signature-required` | The release has no accepted signature status. |
| `policy:revoked` | The release is revoked, or its revocation epoch is above the policy's. |
| `policy:yanked` | The release was yanked by an administrator. |
| `policy:quarantined` | The release was quarantined by an administrator. |
| `policy:mode-private` | `mode` is `private-only` and the source is not org or bundled. |
| `policy:source-not-enabled` | The catalog or data source is not in `enabledSources`. |
| `policy:platform` | No platform in `platforms` matches the host. |

## Update, widen consent, roll back, uninstall

- An update appears on `/marketplace/installed` as "Review and update". If the new version adds scopes, the install waits on a consent sheet that marks "New in this version". Accept applies the update; Decline clears the pending update and keeps the installed version.
- "Roll back" returns to the previous recorded version. It does not touch plugin data.
- "Purge data" deletes the plugin's data folder after you type `delete-data:<plugin id>` exactly.
- "Uninstall" removes the plugin and keeps its data folder.
- Disable and Enable stop and start the plugin without removing it.

## Retired plugins and the one-time cleanup

The in-box catalog ships three plugins: `excel-report` (the Workbook tracker card), `competitor-watch` (the Page watch card), and `presentation-starter` (a neutral presentation template, not a dashboard card). The 23 plugins this desk used to carry are retired. Their trees are kept under `archive/plugins/` as a reference copy only; the app never reads that folder and it is not an import queue. No pack ships either: `registry/packs.json` carries an empty list, so there is no pack entry to open.

Nothing is removed automatically on upgrade. A desk set up before the retirement keeps its installed copies until the owner removes them: open `/marketplace/installed`, Uninstall each of the 23, and confirm. Uninstall keeps the plugin's data folder; Purge data deletes that folder only after the typed `delete-data:<plugin id>` confirmation, so do that only where the history is no longer needed. A fresh desk never sees the retired plugins, and no data or settings are migrated.

## Publish and review

Publishing starts in Studio at `/marketplace/studio`:

1. Start from a blank template or copy the descriptive fields of an installed plugin.
2. Fill the manifest, run the validator, and fix what it reports.
3. Add a changelog and tick the license grant.
4. Publish. The response is `202` with a pending id and status `pending-review`. Publishing never installs the plugin.

An administrator reviews it on the Admin page under "Pending publications". Approve runs the validator again, copies the validated tree to `marketplace/org/<id>/<version>`, pins its `tree_digest`, then writes the release to `org-catalog.json` with publisherVerified true and the signature status `org-approved` from key `local-admin`. Risk tier defaults to `T1` unless the manifest or the approval request sets another tier. Reject requires a reason.

The API also accepts a server-side folder: `POST /api/marketplace/publish` with `{"folder": "..."}`. The inline JSON form takes `manifest`, `widgetUi`, `sample`, `changelog` and `licenseGrant: true`.

Approval is not a security review. It records that a local administrator read the submission.

## Deprecate, yank, quarantine, revoke

The Admin page exposes three governance actions, and the API routes are `POST /api/marketplace/deprecate`, `/yank` and `/quarantine`. Each needs admin mode, `id`, `version` and `reason`; `replacement` is optional. Records go to `governance.json`, the catalog shows a Deprecated, Yanked or Quarantined chip with the advisory, and the action is audited. Yank and quarantine block new installs and updates with `policy:yanked` and `policy:quarantined`; they do not uninstall an existing plugin, and the kill switch remains the hard block.

Yank and quarantine block new installs and updates (`policy:yanked`, `policy:quarantined`); deprecation warns but stays installable. None of the three uninstalls an existing plugin, so use the kill switch for an immediate hard block. Revocation epochs in a signed policy remain the durable org-wide block: an entry whose `revocationEpoch` is above the policy's `minRevocationEpoch`, or one carrying `revoked`/`revokedAt`, is refused. This build has no route that sets those catalog fields; raise `minRevocationEpoch` in a signed policy instead.

## Kill switch

The kill switch is on the Admin page. Enter a plugin id and block it. The wildcard `*` blocks every plugin. The state is written to `kill-switch.json` and applied on top of whatever policy is active, so it survives a policy import, and it can be restored from the same page.

The kill switch blocks new installs. It does not uninstall, disable or delete data for a plugin that is already installed. Do those from `/marketplace/installed`.

## Signed policy

A signed policy bundle replaces `policy.json` and is the file of record after import. It can set these fields:

| Field | Type | Notes |
| --- | --- | --- |
| `mode` | string | `open`, `curated` or `private-only`. |
| `allowedPublishers` | list of strings | Empty means no publisher restriction. |
| `allowedCategories` | list of strings | Empty means no category restriction. |
| `riskCeiling` | string | `T0` to `T3`, or the registry aliases `internal`, `low`, `medium`, `high`. Default `T1`. |
| `networkAllowlist` | list of strings | Hosts a network plugin may reach. |
| `enabledSources` | list of strings | Catalog sources `bundled`, `org`, `peer`, plus data sources such as `excel-watch`, `json-watch`, `http-get`, `calendar-read`, `mail-digest`, `research-brief`, `csv-watch`, `markdown-watch`, `manual-metric`, `desk-state`, `compare`, `aggregate`. |
| `killSwitch` | list of strings | Plugin ids, or `*`. The separate kill-switch file is unioned on top. |
| `retentionDays` | integer | Data retention days. |
| `bodyIngest` | boolean | Whether message bodies may be ingested. |
| `updateChannel` | string | Default `manual`. |
| `versionPolicy` | string | Default `pinned`. |
| `platforms` | list of strings | Default `["windows"]`. |
| `minRevocationEpoch` | integer | Revocation floor. |
| `requireSignatures` | boolean | Default true. |

The bundle itself is JSON:

```json
{
  "schemaVersion": 1,
  "policy": { "mode": "curated", "riskCeiling": "T1" },
  "issuedAt": "2026-11-16T00:00:00Z",
  "expiresAt": "2027-02-14T00:00:00Z",
  "revocationEpoch": 1,
  "signer": { "keyId": "corp-2026", "publicKey": "<base64url 32 bytes>" },
  "signature": { "keyId": "corp-2026", "alg": "ed25519", "value": "<base64url 64 bytes>" }
}
```

The signed bytes are the canonical JSON of the bundle without the `signature` member. `signer.keyId` and `signature.keyId` must match, the public key must decode to 32 bytes and the signature to 64 bytes, and both use base64url. The signing key id is free text.

There is no bundle command in `scripts/`. Produce one with the helper the server uses:

```python
import json
from datetime import datetime, timedelta, timezone
from agentdesk.marketplace import signed_policy
from agentdesk.trust import generate_seed, public_key

seed = generate_seed()  # 32 bytes; keep it offline
bundle = signed_policy.sign_policy_bundle(
    {"mode": "curated", "riskCeiling": "T1",
     "networkAllowlist": ["example.com"]},
    seed=seed,
    key_id="corp-2026",
    issued_at=datetime.now(timezone.utc),
    expires_at=datetime.now(timezone.utc) + timedelta(days=90),
    revocation_epoch=1,
)
print("fingerprint", signed_policy.fingerprint(public_key(seed)))
with open("policy-bundle.json", "w", encoding="utf-8") as handle:
    json.dump(bundle, handle, indent=2)
```

To import it, open the Admin page, choose the JSON file under "Import a signed policy", review the diff and the verification details, then choose "Apply signed policy".

How the files win:

1. A `policy.json` that looks signed is verified against `anchor.json` before it is used. If it fails verification, the built-in curated default stays active with an amber warning, and the rejected attempt is audited.
2. An unsigned `policy.json`, written by hand, overlays its fields on the built-in defaults. It is not a signed artifact and Trust Center shows it as unsigned.
3. The kill-switch file is applied last, over either kind of policy.

The anchor never lowers the revocation epoch and never drops a fingerprint. A bundle whose epoch is below the pinned epoch is rejected with `policy:stale-epoch`, expired bundles with `policy:expired`, modified bundles with `policy:bad-signature`, and bundles whose signer is not pinned with `policy:unknown-key`, except that the first import on a machine trusts the key it is given.

Trust on first use is the important caveat. Importing a bundle accepts any well-formed Ed25519 key that the local admin presents, both on the preview and on apply, and then pins its fingerprint. The anchor constrains what loads later, not who may import next. Protect the admin surface and the account that can open it. The Ed25519 code is in this repository and has not been audited as a library.

## Audit export

With admin mode on, open `/marketplace/admin` and choose the audit log link, or request `GET /api/marketplace/audit/export`. The response is NDJSON with a `marketplace-audit.jsonl` attachment, one event per line, with exactly these fields:

```json
{"at": "2026-11-16T00:00:00Z", "action": "install", "pluginId": "excel-report", "actor": "local-admin", "outcome": "ok"}
```

The export does not include the internal detail field, so changelogs, rejection reasons and report notes are not in it. The local log holds the last 1000 events. Download and archive it before a policy change or a cleanup; there is no automatic rotation.

## Offline behavior and the catalog

The marketplace does not fetch a catalog from the internet. `/api/marketplace/catalog` merges three local inputs: the bundled catalog, `org-catalog.json`, and `peer-catalog.json`. Per plugin id, a locally approved org entry wins over a bundled entry, and a bundled entry wins over a peer entry. The bundled baseline is the committed `src/agentdesk/marketplace/bundled-catalog.json` (three plugins) with pinned tree digests; when a registry checkout also resolves, the API uses its releases for ids the bundle does not pin. The registry checkout is the path saved in Settings, then `AGENTDESK_REGISTRY`, then the app's own `registry` folder.

The packaged build ships the committed bundle but not the `registry` folder, so a copy with no registry checkout still shows those three plugins. An approved org release of a shipped id takes precedence over the bundled pin, so publish a version bump locally when you need to update one.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Admin page says "Admin mode is off" | Env var missing, not `1`, or the server was not restarted | Set `AGENTDESK_MARKETPLACE_ADMIN=1` before start, restart. |
| Audit export answers 403 | Admin mode off | Same as above. |
| Catalog did not load, or is empty | No registry checkout resolved | Set the registry path in Settings or `AGENTDESK_REGISTRY`, restart, retry. |
| Install refused `policy:network-not-allowed` | competitor-watch asks for example.com and the default allowlist is empty | Add the host to `networkAllowlist` in the policy and reload it. |
| Install refused `policy:signature-required` | Bundled registry releases default to unsigned | Approve the release into the org catalog, or import a policy that does not require signatures. |
| Policy import rejected | `policy:bad-signature`, `policy:expired`, `policy:stale-epoch` or `policy:unknown-key` | Re-sign with the pinned key, check the clock, raise the epoch. |
| A yanked release is still offered | The catalog has not reloaded since the yank | Reload the catalog; yank and quarantine block installs and updates while deprecate warns only. |
| A retired plugin is still installed | The desk was set up before the plugin set was retired; nothing migrates automatically | Uninstall it on `/marketplace/installed`; its data folder is kept until you purge it. |

Known gaps, including the ones above, are listed in `docs/known-limitations.md`.
