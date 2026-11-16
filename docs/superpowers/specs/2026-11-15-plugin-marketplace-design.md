# Spec: plugin portfolio, marketplace, and enterprise governance

**Status:** Ready for agent · 2026-11-15
**Source plan:** `docs/plans/2026-11-15-plugin-portfolio-marketplace-enterprise.md`
**Seams:** confirmed by Ken, 2026-11-15 (server HTTP, registry package, SPA component)
**Tracker:** `kanitmann01/agent-desk` (private, issues enabled)

---

## Problem Statement

A manager at a locked-down enterprise laptop has a dashboard that can show a handful of widgets, a plugin runtime that can install declarative packages, and no way to find, judge, or safely adopt anything beyond the four plugins that shipped. The plugin page is an operator form, not a store: there is no catalog, no detail page, no permission explanation a non-technical person can read, no publisher identity, no signature, no category, and no publish path. Worse, the platform can only render a metric or a line of text, so most of the jobs a manager actually pins (aging cash, meeting load, promises, renewals, compliance posture) cannot be expressed at all.

At the same time the app cannot be sold to an enterprise: there is no signed policy, no org trust anchor, no publisher verification, no private catalog, no kill switch, and no audit export. A buyer's security team has no artifact to approve. The result is a demo that looks like a product and an architecture that cannot pass review.

## Solution

Three surfaces, one product:

1. **A portfolio of 24 in-box plugins** across finance, time, communication, research, operations, and command. Each answers one recurring question with one lead number and one action, reads a real local source, stamps every card with an as-of time, and renders an honest `STALE`, `BLANK`, `COARSE`, or `PARTIAL` state instead of a fake zero. Six reference plugins demonstrate the SDK; three role packs (Manager, CFO, Ops) install a coherent set with one consent sheet.

2. **A DSH-style marketplace** with Discover, Browse, Search, Detail, Installed, Publishers, and Submit. The detail page is the trust surface: a live render from the plugin's own sample data, plain-English permissions, a generated "can never" list, publisher proof, signature fingerprint, validator report, version history with capability diffs, and alternatives. Install is one consent sheet; updates show only the scope diff; widening re-prompts; rollback is one click. Publisher Studio turns a folder or an installed plugin into a validated, versioned, licensed release that publishes as pending review.

3. **Enterprise governance** as a signed policy bundle verified against a pinned org anchor: mode (open, curated, private-only), publisher and category allowlists, risk ceiling, network allowlist, version policy, kill switch, retention, and update channel. Publisher identity is proven by DNS or GitHub org ownership plus manual review, and every release is signed by a publisher key delegated by the org root. Admin shows posture, pending publications, revoked publishers, inventory, and an audit export.

The strategic rule: **the portfolio and the trust proof are the moat; the store UI is the shopfront.** Nothing ships that the product cannot prove.

## User Stories

1. As a manager, I want to browse plugins by the job I have (cash, meetings, promises, renewals, compliance), so that I do not have to know what a "data source" is.
2. As a manager, I want to see a plugin rendered with sample data before I install it, so that I know exactly what will appear on my dashboard.
3. As a manager, I want permissions written as sentences ("Reads one Excel file you choose"), so that I can make a consent decision without reading a manifest.
4. As a manager, I want a fixed "can never" list on every plugin, so that I know no plugin can run code, send mail, read message bodies, or reach the network unless it explicitly declares it.
5. As a manager, I want to install a whole role pack in one consent sheet, so that setting up my desk takes one decision, not eight.
6. As a manager, I want an update to show only what changed in its permissions, so that I am not re-reading the same five scopes.
7. As a manager, I want a widening update to require my consent again, so that a minor version cannot silently start reading a new folder.
8. As a manager, I want to roll back a bad update in one click, so that a broken release does not cost me a day.
9. As a manager, I want every card to show an as-of time, so that I can tell a fresh number from a stale one.
10. As a manager, I want a card with a missing file to say which file it needs, so that I can fix it without reading logs.
11. As a manager, I want a stale card to freeze its last good value, grey it, and stamp the date, so that I am not misled by an old number.
12. As a manager, I want a partial card to say "n of N rows", so that I know the number is computed from an incomplete export.
13. As a manager, I want to search by plain language ("invoices overdue"), so that discovery does not require knowing plugin names.
14. As a manager, I want to see a publisher's verification and a release's signature fingerprint, so that I can tell an org-published plugin from an anonymous one.
15. As a manager, I want to see a validator report with a date and a re-run button, so that "validated" is evidence, not a badge.
16. As a manager, I want to read a changelog for every version, so that I can decide whether to take an update.
17. As a manager, I want no star ratings and no invented download counts, so that I am not steered by fabricated social proof.
18. As a manager, I want to share a plugin with a paired teammate, so that my team can reuse a vetted plugin without a central server.
19. As a manager, I want to subscribe to a teammate's plugin and receive its updates, so that a shared plugin stays current without manual copying.
20. As a CFO, I want A/R aging, budget burn, and revenue-vs-target plugins sourced from my workbook, so that my Monday review is one screen.
21. As a CFO, I want a reconciliation plugin that names what is in the ledger but not the bank, so that I can chase the right items.
22. As a CFO, I want a renewal plugin keyed on notice deadlines, so that I do not miss the date that actually costs money.
23. As an ops lead, I want meeting load, follow-up aging, and note action items, so that commitments do not silently decay.
24. As an ops lead, I want plugin health, update radar, audit digest, and compliance posture, so that I can run the desk without reading the runtime.
25. As a security reviewer, I want a signed policy bundle with a pinned org anchor and a monotonic revocation epoch, so that a compromised publisher key can be cut off offline.
26. As a security reviewer, I want the client to verify signatures at install and at load, so that a tampered installed plugin fails closed on the next render.
27. As a security reviewer, I want an allowlist by publisher, plugin, and version range, so that a policy can be narrower than "all signed releases".
28. As a security reviewer, I want a kill switch per plugin, so that one bad release can be blocked without disabling the marketplace.
29. As a security reviewer, I want a CycloneDX SBOM and a license gate in CI, so that distribution does not ship a license landmine.
30. As an IT admin, I want to import a signed policy file and see whether it verified, so that control lives in change management, not in a UI checkbox.
31. As an IT admin, I want a private catalog source, so that internal plugins never appear in a public index.
32. As an IT admin, I want the app to run from a signed one-folder build with an AppLocker publisher rule, so that deployment works on a locked-down Windows laptop.
33. As an IT admin, I want an audit export of installs, consents, denials, and egress, so that I can feed the SIEM without telemetry.
34. As a publisher, I want to start from an installed plugin or a folder, so that I do not need to learn a new authoring tool to ship one.
35. As a publisher, I want a plain-English wizard that maps a spreadsheet or CSV column to a card, so that I can publish without writing code.
36. As a publisher, I want a validation report with a rule and a field, so that a rejection tells me what to fix.
37. As a publisher, I want a preview before publishing, so that I do not ship a card that renders empty.
38. As a publisher, I want a semver suggestion and a required changelog, so that consumers can judge the update.
39. As a publisher, I want to grant distribution rights explicitly, so that the org's legal position is recorded per release.
40. As a publisher, I want my release to enter as pending review, so that publishing cannot bypass admin approval.
41. As a publisher, I want to deprecate a plugin with a reason and a replacement, so that existing users get a migration path instead of a 404.
42. As a publisher, I want to yank a specific release, so that a bad build stops installing without erasing its history.
43. As a teammate, I want a peer's catalog to be marked as a peer source, so that I can tell org-reviewed from teammate-shared.
44. As a teammate, I want a stale peer catalog to degrade visibly, so that I do not install from a disconnected desk silently.
45. As a keyboard or screen-reader user, I want route changes announced and every action reachable by keyboard, so that the marketplace is usable without a mouse.
46. As a mobile-free desktop user, I want the app to work offline from the bundled and installed catalog, so that a network outage does not blank the marketplace.
47. As a technical owner, I want the old plugin page to redirect to the new Installed surface, so that existing links and the rail do not break.
48. As a technical owner, I want manifest v1 plugins to keep installing and rendering, so that an upgrade does not break the installed base.

## Implementation Decisions

### Capability model

- Manifest v2 is additive over v1: category, tags, icon enum, summary, description, highlights, sample fixture, requires, minHost. Unknown keys remain rejected. The validator accepts v1 unchanged and v2 with the new required fields; the runtime normalizes both.
- Twelve data sources execute: `excel-watch`, `csv-watch`, `json-watch` (mini-selectors only, no full JSONPath), `markdown-watch`, `calendar-read`, `mail-digest`, `research-brief`, `manual-metric`, `desk-state`, `compare`, `aggregate`, `http-get`.
- Ten render elements: metric, text, delta, progress, list, table, sparkline, status, timeline, checklist. An unknown element kind is a hard validation and execution error, never a silent drop.
- `http-get` requires network permission and is mutually exclusive with every filesystem read. The validator enforces the exclusion, so the lethal trifecta stays broken by construction. Network is GET-only, host allowlisted, and policy gated.
- Every element payload carries `{ value, asOf, source, state }` where state is `ok | stale | blank | coarse | partial`. The shared card frame, not the plugin, renders the state. Aggregates declare `requires` plugin ids and degrade to a named missing-dependency state.
- Existing lifecycle semantics are reused: install, pilot views, consent on widening, rollback, disable/enable, purge with typed confirmation, retest, peer sharing.

### Catalog and trust

- Registry index v2 adds org metadata, publishers with keys, categories, tags, releases with changelog, signature, digest, min host, yanked flag, plus a monotonic version counter and metadata expiry.
- Bundled catalog is generated at build time from the shipped plugins so it cannot drift. The marketplace merges `bundled`, `org`, and `peer` sources with an explicit source label.
- Trust chain is TUF-lite: org root (2-of-3 threshold, offline), publisher keys delegated by the root, release signatures over the canonical digest, signed revocation with a monotonic epoch and short TTL. Verification happens at install and at load; stale revocation epoch or expired metadata fails closed. Rotation is signed by the old root.
- Signing is Ed25519 per RFC 8032 with a minisign-style detached envelope, implemented in-repo with zero new runtime dependencies and verified against RFC test vectors. The verify interface is isolated so Sigstore or a native library can replace it later. Key material never enters the repo; test keys are fixtures only.
- Publisher verification is DNS TXT or GitHub org ownership plus manual review of the first release. Unverified publishers render as self-published. No verification is granted by installation or by popularity.
- Provenance records builder, source commit, and digest for every release. Declarative bundles make byte-identical rebuilds testable.
- Deprecation and quarantine keep the detail page alive with a reason, an advisory reference, and a recommended replacement. Yanking blocks a single release but keeps history.

### Marketplace surfaces and API

- The marketplace is SPA-owned. `/plugins` becomes a redirect to the Installed surface for one release; the rail entry points at the new location. Deep links are served the SPA shell after the same session gate.
- Routes: Discover, Search, Category, Plugin Detail, Collection/Pack, Installed, Publisher list, Publisher Studio, Plugin Manage, Admin, Trust Center.
- A small history router parses routes as a pure function and navigates with `pushState`; no router dependency is added. Back/forward and deep links are tested.
- JSON API (POST for mutations, matching the existing server): catalog, plugin detail, installed, publisher, install, update, consent, rollback, uninstall, purge-data, enable, disable, retest, publish, deprecate, yank, quarantine, policy read/import, audit slice, report. Every route is session- and Origin-guarded; the existing legacy endpoints stay for one release.
- Detail content is fixed: live sample render with a sample chip, plain-English scopes with the setting each depends on, a generated "can never" list, publisher proof, signature and digest, dated validator report with re-run, version history with capability diffs, alternatives, report action.
- Installed shows status, updates, pending consent diffs, pilot badge, rollback, purge, and share. Updates pin version + digest; auto-update is a channel choice, staged for org catalogs, with one-click rollback.
- Publisher Studio: start from installed plugin, folder, or template; validate; preview; semver suggestion; required changelog; SPDX license and distribution grant; publish as pending review; manage releases, deprecate, yank.
- Role packs are curated collections with a one-sheet install-all consent; packs are metadata, not new runtime behavior.
- v1 ships no ratings, no reviews, no download counts, and no sponsored ranking. If reviews arrive later they are verified-install only.
- Design follows the existing warm-paper system, one green, monospace numerals, compact density. The dashboard's dark-glass drift is pulled back in the hardening ticket rather than mixed into the marketplace.
- Accessibility: semantic tables, visible focus, keyboard reachability, route-change announcement, no color-only status.

### Enterprise policy

- Signed policy bundle fields: mode (open, curated, private-only), allowed publishers, allowed categories, risk ceiling, network allowlist, enabled sources, kill switch, retention, body-ingest flag, update channel, version policy, platform, minimum revocation epoch, signature requirement.
- Precedence: signed policy, then local admin setting, then built-in default. Invalid signature or expiry falls back to the curated default with a visible amber banner and an audit event.
- Risk tiers T0 to T3 drive review and default policy; the detail page shows the tier and its implication.
- Admin surface is read-mostly: posture, anchor fingerprint, policy verification, pending publications, allowlists, revocations, inventory, catalog source, audit export. The mutation of record is the signed policy file, not a UI field.
- No fake RBAC and no fake multi-user. One Windows user runs the desk; admin is a policy-gated mode. SSO, fleet management, and a central console are deferred explicitly.
- Distribution: signed one-folder build, AppLocker publisher rule documented for IT, private catalog on a file share, SBOM and license gate in CI, third-party notices regenerated, license landmines cleared before external distribution.

## Testing Decisions

Confirmed seams (Ken, 2026-11-15), highest available, no new harness:

1. **Server HTTP seam.** Drive the real server through its request handler: routes, session and Origin guards, consent codes, policy gating, deep-link fallback, redirect.
2. **Registry package seam.** Exercise manifest, lint, executor, signing, index, install, and publish as pure functions: RFC vectors, tamper cases, v1 compatibility, source merge, revocation.
3. **SPA component seam.** Vitest with testing-library and jsdom, rendering pages with a fetch stub: router, consent diffs, states, keyboard roles.

A good test asserts observable behavior at the seam: an HTTP status and body, a resolved payload and state, or a rendered role and text. It does not assert private helpers, internal call order, or class names. Existing fixtures and conventions are reused: server harness and fixtures for HTTP, registry fixtures for packages, component tests for the SPA.

Prior art: the existing registry install/index/hardening tests, plugin runtime and executor tests, validator schema/lint tests, server guard/auth/SPA tests, and the SPA shell/widget-card tests.

Required evidence per area: v1 manifests still pass and install; unknown element kinds are rejected; network plus filesystem is rejected; RFC 8032 vectors pass; a tampered digest or signature fails closed; a stale revocation epoch fails closed; deep link returns the shell and unknown path 404s; widening consent is required and narrowing is not; rollback restores the prior version; no route is reachable without the session; the marketplace renders sample, blank, stale, and missing-dependency states.

## Out of Scope

- Arbitrary JS/HTML plugins, install-time hooks, shell execution, and any executable plugin class.
- Email body ingestion, auto-send, mailbox write, and any credential-bearing connector beyond the existing metadata bridge.
- IMAP, COM, Graph write scopes, Teams presence, bank feeds, and live CRM tokens.
- SSO, SCIM, multi-user desks, fleet management, central admin console, cloud sync, and telemetry.
- Paid plugins, payments, ratings/reviews, and sponsored placement.
- Sigstore, Rekor, full TUF snapshot/delegation roles, and transparency logs.
- Mobile apps and a public community registry with open signup.
- Real code-signing certificates and AppLocker rollout; the build profile and IT documentation are in scope, the certificate procurement is not.

## Further Notes

- **Resolved decisions (Ken, 2026-11-15):** three seams approved; one allowlisted network plugin ships behind admin policy; 24 in-box plugins planned with 11 in the first batch; signed policy with no fake RBAC; product name stays Agent Desk; marketplace lives in the SPA with `/plugins` redirecting.
- **Open questions, recommended defaults, vetoable now:** whether the four aggregate plugins ship in the first batch (default: last, cut first if T2 slips); whether the dashboard theme pull-back lands in T12 or a separate ticket (default: T12); whether peer catalogs are enabled by default in curated mode (default: off until policy allows).
- **Known limitation:** the Ed25519 implementation is in-repo and verification-focused. It is tested against RFC vectors and pinned anchors, but it is not a substitute for an audited library; the interface is isolated for replacement.
- **Migration:** existing plugin ids and lockfiles are preserved; `excel-report` moves from the in-box set to the reference set without uninstalling; index v1 is wrapped into the v2 shape on load; legacy API routes remain for one release.
- **Reference:** the full portfolio, marketplace IA, capability model, delivery phases, risks, and metrics live in the source plan. The plan is the design record; this spec is the build contract.
