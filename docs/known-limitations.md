# Known limitations

Honest gaps in the marketplace branch as of 2026-11-16. Each item is verified in this tree or comes from the ticket reports. None of these is a promise of future work.

## Distribution and legal

- No Nuitka artifact exists. Nuitka is not installed in this environment, so `python scripts/build_bundle.py build` prints `SKIP: Nuitka is not installed` and exits 3. There is no `dist/agent-desk`, no `manifest.json`, no signature and no working AppLocker publisher rule. The rule in `docs/ops/distribution.md` is a template.
- There is no installer, no MSI and no per-machine deployment. The app is an on-demand executable launched from a folder.
- No legal review has happened. `LICENSE` is a draft with `[COUNSEL: ...]` placeholders, the plugin SDK boundary in `docs/licensing.md` is not counsel-approved, and the distribution grant in the draft is not implemented as an acceptance flow. The Apache-2.0 boundary mentions an `sdk/` directory that does not exist; the published boundary is the manifest schema and the files marked Apache-2.0.
- No SBOM ships yet because no build ships. `scripts/sbom.py` can generate one, and `scripts/license_gate.py` can check it, but there is no artifact to attach it to.

## Identity and administration

- Single user only. No SSO, no multi-user accounts, no RBAC, no fleet management and no remote configuration. Every audit event records the actor as `local-admin`.
- Admin mode is an environment variable, `AGENTDESK_MARKETPLACE_ADMIN=1`, read on each request. It needs a restart to change, has no UI toggle, and only proves that the local process was started with it. It is not a role and does not add authentication beyond the app's own session token.
- The deprecate, yank and quarantine routes require admin mode and answer 403 `admin:disabled` without `AGENTDESK_MARKETPLACE_ADMIN=1`. The check proves only that the local process was started with the variable set; it is not a role.
- Policy import uses trust on first use. `POST /api/marketplace/policy/import` verifies with no pinned keys both for the preview and for the apply, so any well-formed Ed25519 bundle that the local admin presents is accepted and its key is then pinned into `anchor.json`. The anchor constrains later loads, not later imports. There is no preconfigured corporate root key.
- The Ed25519 implementation in `src/agentdesk/trust/` is in-repo and has not been audited as a library. The spec called this out; it is still true.
- Publisher verification is a recorded claim. The publisher page shows a `publisherVerified` mark and a `publisherProof` value taken from the catalog entry. No live DNS or GitHub ownership check runs at install time.

## Marketplace behavior

- Yank and quarantine now block new installs and updates with `policy:yanked` and `policy:quarantined`. They do not uninstall, disable or purge an already installed plugin, and they are not the kill switch. There is no route that sets `revoked` or `revokedAt`, so the revocation-epoch path has no operator UI.
- The kill switch blocks eligibility only. It does not uninstall, disable or delete the data of an already installed plugin.
- Install and update now fail closed with `409 install:digest-mismatch` when the staged tree digest differs from the catalog pin, or when the catalog entry carries no pin. A pack, if a catalog ever carries one, is checked member by member before any member is installed. What is still missing is cryptographic publisher verification: `signatureStatus` is a catalog label checked by policy, and no trust store exists under `registry/`, so the marketplace cannot re-verify a release signature the way `src/agentdesk/registry/install.py:165` does when a `TrustStore` is supplied.
- The catalog's Source filter includes `installed`, but `/api/marketplace/catalog` merges only bundled, org and peer catalogs. Choosing Source: installed returns zero rows. Installed plugins are on `/marketplace/installed` instead.
- A packaged build ships `src/agentdesk/server/static` but not `registry/`. As built today, a packaged app with no registry path in Settings, no `AGENTDESK_REGISTRY`, and no workspace registry folder shows an empty catalog. `src/agentdesk/marketplace/bundled-catalog.json` is in the tree but the catalog API does not read it. Verify catalog population after the first signed build.
- The audit log keeps the last 1000 events in `audit.json` and does not rotate. The NDJSON export at `GET /api/marketplace/audit/export` includes only `at`, `action`, `pluginId`, `actor` and `outcome`; it drops the internal detail field, so changelog text, rejection reasons and report notes are not exportable. There is no SIEM forwarding.
- Reports from plugin and publisher pages are stored locally in `reports.json`. The Admin page has no report queue, and the Trust Center displays `reportPath` as `/marketplace/report` even though the SPA has no route at that path; it renders the marketplace 404.
- The Trust Center says nothing has been validated until a validator run is recorded, and a bundled registry release with no recorded run shows as not checked.
- competitor-watch is the only plugin that uses `http-get`, and it requests `example.com`. The default policy has an empty `networkAllowlist`, so it is refused with `policy:network-not-allowed` until an operator adds the host.
- There are no ratings, reviews, download counts or usage telemetry, by design. There is also no way to see which other desks use a plugin.

## Studio and publishing

- Studio has no folder import. It builds one manifest from form fields, a blank template, or the descriptive fields of an installed plugin. Permissions always start empty.
- Studio has no share or subscribe. There is no way to share a draft, follow a publisher, or subscribe to an update channel from the UI.
- Publishing always goes to pending review. There is no direct publish path for an admin, and approval records a local administrator's read, not a security review.
- Studio does not edit an existing published plugin. There is no draft list and no resubmission flow for the same plugin id beyond publishing again and replacing the org catalog release on approval.
- The approval risk tier defaults to `T1` when neither the request nor the manifest sets one.


## Coupled intelligence

- The six preferences in Settings are the only ones the readings use, and they are never inferred. There is no autopilot, no learned preference and no reset action on the save route (`PreferenceStore.reset()` exists but is unexposed).
- A workbook reading looks only at the rows the tracker already selected: at most 10 columns and 60 rows, and only the first five suggested row indices are exposed. It names a chart shape; it does not draw one.
- Digest readings and reply drafts work from message headers and the first line only. No message body is read, so a thread that buried its question is not recognised.
- A drafted reply is a skeleton or a single model output. It is never sent, never saved to the draft folder, and it carries no recipient, so the user must open it in the reply writer.
- No surface draws the press button yet. `payload["insight"]["press"]` carries the offer and `POST /api/insight/draft` answers it, but the dashboard and the SPA do not render a control for it.
- The built SPA's tracker card renders its own figure and ignores appended elements, so the workbook reading appears on the server-rendered dashboard only.
- Research suggestions are keyword-anchored: a focus topic named once in the stored answer counts as covered. The reading cannot judge depth, so it says "not named" rather than "not answered".
- The insight readings never write memory. Recall is read-only and a sealed or empty bank degrades to one sentence naming what was not consulted.
- The next meeting's reading knows its title, time and prep items, not its attendees, so no prompt names a person.

## Accessibility and UI

- The consent sheet traps Tab and Shift+Tab, closes on Escape and restores focus to its trigger. Initial focus lands on the close button, not the confirm button, so the first keypress cannot accidentally accept a widening.
- The source filter is supplied as described above, so one visible option can never produce results.

## Keys, connections and the legacy upgrade (spec 018)

- The legacy endpoint rows (`llm_base`, `llm_key`, `llm_model`, `research_provider_url`, `research_provider_key`) stay in the settings database forever: no surface removes them, and the migration keeps representing them as "Migrated endpoint" and "Migrated research provider" connections on every boot while their base/URL rows are non-empty. A desk that has fully moved on to its own connections still sees the migrated connections reappear in the list after a delete-plus-restart (that delete is the recovery path; see below). Only hand-editing the settings sqlite removes the fallback.
- Deleting a migrated connection never deletes its key: the keychain entry survives so the next boot can put the connection back without a retype. A user who wants the key truly gone from the keychain has no button for it while the legacy rows exist.
- On a machine with no usable keychain, the migrated connections are created disabled and unbound (masked hint only) and the legacy secret columns are NOT cleared, so the environment leg keeps serving exactly as before the upgrade. The connections stay disabled even if a keychain appears later; the user must edit the connection and paste the key (or delete it and hand-build their own).
- A recovery boot restores a migrated connection's binding only when that job is unbound and takes the default star only when no connection holds it. A user who deleted a migrated connection and bound the job elsewhere keeps their choice, but the migrated connection still reappears (unstarred, unbound) in the list.
- The migrated connections carry the custom preset and the legacy base URLs verbatim; nothing re-validates them at migration time, so a row that was already wrong (a portal URL, a dead key) migrates as a connection with an unknown badge, exactly as wrong as it was before.

## Operations

- No autostart, no Windows service, no scheduled task and no tray helper. The app starts when the user launches it.
- No auto-updater and no update check. Updates are a file-share procedure: publish a versioned folder and repoint the shortcut, as described in `docs/ops/distribution.md`.
- No telemetry, no crash reporting and no remote diagnostics. Support depends on the local data folder and the audit export.

The operator procedures that work around several of these gaps are in `docs/ops/marketplace-operator.md`.
