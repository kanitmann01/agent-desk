# Nexuus Bot: Plugin Portfolio, Marketplace, and Enterprise Plan

**Status:** Draft for approval · 2026-11-15
**Author:** CTO track (lead agent), for Ken
**Worktree:** `.worktrees/plugin-marketplace` · branch `feat/plugin-marketplace` (from `agent-desk` main `f811ac7`)
**Inputs read:** `research/2026-11-11-enterprise-personal-agent-research.md` (full), `product/PRD.md`, `DESIGN.md`, `.worktrees/enterprise-hardening/research/2026-11-12-enterprise-hardening/{REPORT,PRD-ADDENDUM}.md`, plus the live plugin platform code (`plugins/`, `registry/`, `server/`, `frontend/`).

---

## 1. Executive decision

Ship three things together, in this order, because none of them is worth much alone:

1. **A portfolio of 24 in-box plugins** that each answer one recurring question with one number and one next action. Without a portfolio the marketplace is an empty store; without the marketplace the portfolio is a fixed feature list.
2. **A marketplace with the DSH shape**: discover, inspect, consent, install, update, roll back, publish, share peer-to-peer. Declarative Class D only, signed, permission-diffed. This is where the product becomes a platform instead of an app.
3. **Enterprise governance on top**: signed policy bundle, org trust anchor, publisher verification, private catalog, kill switch, audit export, and a deployment story (signed Nuitka folder + AppLocker publisher rule). This is the difference between "a cool plugin app" and something IT will approve.

The strategic bet: **the moat is the portfolio plus the trust model, not the marketplace UI**. Anyone can draw a plugin store. Very few can prove a plugin cannot read your mail body, cannot phone home, and cannot change what it declared. We ship the proof in the product surface.

What we are **not** doing in this pass: arbitrary JS/HTML plugins, email body ingestion, auto-send, shell execution, mobile, cloud sync, paid plugins, star ratings. Those are either Class D red lines or trust theatre at our current volume.

---

## 2. Where we actually are

Verified against the code in `agent-desk`, not against the docs.

| Area | Today | Gap this plan closes |
|---|---|---|
| Manifest | v1, exact-key validation; unknown keys rejected | v2 with category, tags, summary, description, highlights, sample data, richer capabilities; validator accepts v1 and v2 |
| Data sources | executable: excel-watch, calendar-read, mail-digest, research-brief. json-watch/http-get pass lint but do not execute | 12 sources, each with a real executor, sample, and empty/error state |
| UI elements | metric and text only; unknown kinds silently dropped | 10 elements: metric, text, delta, progress, list, table, sparkline, status, timeline, checklist |
| Registry | 5 plugins, one publisher string, one release each, no signatures, no categories | v2 index with publishers, categories, tags, releases, changelogs, signatures, revocation |
| Marketplace | none. `/plugins` is a server-rendered admin-ish page; `/api/registry` returns a flat listing | SPA Discover / Search / Detail / Installed / Publisher Studio / Admin, backed by a marketplace API |
| Publishing | copy files + hand-edit `index.json` | in-app publisher studio: validate, preview, version, changelog, license grant, publish as pending review |
| Frontend | no router; deep links 404 because only `/` and `/static/spa/*` are served | small history router + server fallback for `/marketplace/*` |
| Enterprise | none of policy/signing/allowlists exists | signed policy, anchor pinning, private catalog, kill switch, admin posture, audit export |
| Testing | pytest server/package tests; vitest + testing-library component tests | same two seams plus a registry signing/verification seam |

**Honest read:** the runtime lifecycle (install, consent-on-widening, rollback, pilot, purge) is genuinely good and already tested. The gap is breadth (things plugins can do) and presentation/governance (how humans decide to trust them). We build on the lifecycle; we do not rewrite it.

---

## 3. The plugin portfolio

### 3.1 Portfolio rules

Every in-box plugin must satisfy all six rules, or it does not ship:

1. **One job, asked weekly.** It answers a question a manager actually asks on a Monday, not a capability demo.
2. **A real source.** Excel workbook, CSV export, calendar bridge, mail metadata bridge, research store, desk state, or a manual number. No mock-only plugins in the box.
3. **A lead number plus an action.** The first element is a metric, delta, or status that changes a decision. Lists are the second element, never the first.
4. **An honest empty state.** "Connect your workbook" with the exact setting name; never a fake zero or a plausible-looking placeholder.
5. **A failure mode we can name.** Every card carries an **as-of** stamp and one of four missing/partial states, so "no data" and "zero" are never confused:
   - `STALE`: freezes the last good value, greys it, stamps the date.
   - `BLANK`: renders no number, names the exact file or setting it needs.
   - `COARSE`: falls back to a weaker source and says which one.
   - `PARTIAL`: computes over the rows present and says "n of N".
6. **Retest is always one click.** Every non-ok state offers the same action, implemented once in the card frame.

### 3.2 Capability model v2 (what plugins can do)

This is the part that determines whether the portfolio is possible at all. The manifest is declarative; the host executes only known capability types. The compiler never emits executable code, and ui-schema is the only render path.

**Data sources**

| Type | Reads | Key options | Powers |
|---|---|---|---|
| `excel-watch` | one .xlsx under the workspace | sheet, headerRow, keyColumn, valueColumn, window, aggregate | sales, finance, renewals |
| `csv-watch` | one .csv under the workspace | delimiter, keyColumn, valueColumn, window | exports from Planner/Notion/ATS |
| `json-watch` | one .json under the workspace | mini-selectors `$.a.b`, `$.a[*].n` (no full JSONPath) | bridges, exports, config-driven metrics |
| `markdown-watch` | one .md/.txt under the workspace | heading filter, checkbox extraction, due: markers | notes, action items |
| `calendar-read` | calendar bridge JSON | window today/week, fields | today, load, prep |
| `mail-digest` | mail metadata bridge | window, VIP list, waiting threshold | digest, VIP, waiting-on-you |
| `research-brief` | research store | latest N | brief, source ledger |
| `manual-metric` | user-entered value + target + unit | cadence, history | anything not yet connected |
| `desk-state` | runtime, audit, policy | select: runtime/audit/policy | health, updates, audit, posture |
| `compare` | two local sources | keyColumn, emit left/right missing | reconciliation |
| `aggregate` | payloads of declared dependencies | sum/count/latest/min/max, requires[] | morning brief, weekly review |
| `http-get` | allowlisted HTTPS, GET only | host allowlist, selector, hash diff | competitor-watch only |

**Network rule (non-negotiable):** a plugin that declares `http-get` may not declare any filesystem read. The validator enforces mutual exclusion, so the lethal trifecta stays broken by construction. Network permission is optional, host-allowlisted, prompted once, and admin-policy gated.

**UI elements**

| Element | Shape | Example |
|---|---|---|
| `metric` | one number + unit + caption | "Pipeline delta, -$18k" |
| `text` | short prose | "Last brief: supplier consolidation" |
| `delta` | signed change + direction + window | "+12 rows added, 24h" |
| `progress` | value/target + threshold tone | "Budget burn 78% of Q4" |
| `list` | up to 8 rows, primary/secondary/meta | "5 invoices 90+ days" |
| `table` | up to 20 rows, column spec | A/R aging buckets |
| `sparkline` | 12-30 points, no axes | Weekly meeting hours |
| `status` | ok/attention/alarm + one line | "Bridge stale, last sync 3d" |
| `timeline` | ordered items with time | Next 3 meetings |
| `checklist` | items with done state | Notes action items |

**Manifest v2** (additive over v1): `schemaVersion: 2`, `category`, `tags`, `icon` (enum, no arbitrary SVG), `summary` (<=120 chars), `description` (plain text), `highlights` (3 bullets), `sample` (path to a packaged JSON fixture used for preview), `requires` (plugin ids, for aggregates), `minHost`. Everything else keeps the v1 shape. Validator: v1 stays valid unchanged, v2 additionally requires the new fields and rejects unknown keys; the runtime normalizes both.

### 3.3 The 24 in-box plugins

The jobs are grounded in what teams already pin, not invented: the weekly A/R review exists to answer "what changed and who do I call" (Monk, Helm Advisory); pipeline reviews are run to shorten the Monday spreadsheet ritual (Strkr); renewal trackers key on the **notice deadline**, not the renewal date (Termedora); access reviews still live in stale spreadsheets (Compyl); inbox tools are pinned as **classification**, not reading (Shortwave, Superhuman); meeting prep and calendar defence are separate jobs (Fathom/Granola, Reclaim). We take the job, not the vendor's feature list.

Sizes: S = one source + one element; M = two elements or a compare/bridge extension; L = aggregate or cross-source. "Pack" is the default role pack membership.

**Finance and numbers**

| # | id | Question it answers | Source | Lead element | Size | Pack |
|---|---|---|---|---|---|---|
| 1 | `sales-delta-widget` (Sales delta, 24h) | What changed in the pipeline since yesterday? | excel-watch | delta | S | Manager |
| 2 | `revenue-vs-target` | Are we ahead or behind the quarter? | excel-watch | metric + progress | S | CFO, Manager |
| 3 | `ar-aging` | How much cash is stuck, and how old? | excel-watch | table (0-30/31-60/61-90/90+) | M | CFO |
| 4 | `budget-burn` | Are we burning faster than plan? | excel-watch | progress + status | M | CFO |
| 5 | `kpi-scorecard` | Which four numbers are off target? | excel-watch | list of status rows | M | CFO, Manager |
| 6 | `reconciliation-watch` | What is in the ledger but not the bank? | compare (two sheets) | metric + list | M | CFO |

**Time and commitments**

| # | id | Question it answers | Source | Lead element | Size | Pack |
|---|---|---|---|---|---|---|
| 7 | `calendar-today` | What is left today? | calendar-read | metric + list | S | everyone |
| 8 | `week-load` | Is next week over-committed? | calendar-read | metric + sparkline | S | Manager, Ops |
| 9 | `meeting-prep` | What do I need before the next meeting? | calendar-read | timeline + checklist | M | Manager |
| 10 | `follow-up-watch` | Which promises are aging? | csv-watch (commitments) | list | M | Manager, Ops |
| 11 | `renewal-radar` | What hits its notice deadline in 30 days? | excel-watch | list (notice date, not renewal date) | S | CFO, Ops |

**Communication**

| # | id | Question it answers | Source | Lead element | Size | Pack |
|---|---|---|---|---|---|---|
| 12 | `outlook-digest` | How much mail, and from whom? | mail-digest | metric + list | S | Manager |
| 13 | `vip-watch` | Who important is still waiting on me? | mail-digest | list with ages | M | Manager |
| 14 | `waiting-on-you` | Which threads did I leave hanging? | mail-digest | list | M | Manager, Ops |

**Research and knowledge**

| # | id | Question it answers | Source | Lead element | Size | Pack |
|---|---|---|---|---|---|---|
| 15 | `research-brief` | What did we learn most recently? | research-brief | text + sources count | S | everyone |
| 16 | `source-ledger` | Where did the last answers come from? | research-brief | table | S | Ops |
| 17 | `competitor-watch` | Did a watched page change? | http-get | delta + list | M | Manager |
| 18 | `notes-actions` | What did I say I would do? | markdown-watch | checklist | M | Ops |

**Operations and governance**

| # | id | Question it answers | Source | Lead element | Size | Pack |
|---|---|---|---|---|---|---|
| 19 | `plugin-health` | Which plugins are stale, pilot, or awaiting consent? | desk-state | status + list | S | Ops, IT |
| 20 | `update-radar` | What updates exist, and do they widen scope? | desk-state | list + delta | S | Ops, IT |
| 21 | `audit-digest` | What left the machine this week? | desk-state | metric + table | M | CFO, IT |
| 22 | `compliance-posture` | Are we still inside policy? | desk-state | status + checklist | M | IT |

**Command and personal**

| # | id | Question it answers | Source | Lead element | Size | Pack |
|---|---|---|---|---|---|---|
| 23 | `morning-brief` | What are the four things that matter today? | aggregate | list of 4 metrics | L | everyone |
| 24 | `weekly-review` | What moved, what stalled, what is next? | aggregate | status + list | L | Manager, CFO |

Counts: 24 plugins, 6 categories, 3 role packs. 12 are S/M single-source (safe first batch), 8 need v2 sources, 4 are aggregates that degrade honestly when a dependency is missing.

**Migration:** the four existing bundled ids (`calendar-today`, `outlook-digest`, `research-brief`, `sales-delta-widget`) are kept byte-for-byte as ids so existing lockfiles and peer shares keep working. `excel-report` leaves the in-box set and becomes a reference plugin; nothing is silently uninstalled.

### 3.4 Reference set: 6 plugins published to the catalog, not bundled

These are the "how to build one" examples and double as QA fixtures. They install from the marketplace with the same consent path as community plugins.

| id | Demonstrates | Source |
|---|---|---|
| `hello-widget` | smallest valid manifest, install state | manual-metric |
| `csv-table` | CSV → table, column mapping | csv-watch |
| `json-bridge` | mini-selectors, sparkline | json-watch |
| `manual-metric` | user input, target, history | manual-metric |
| `page-watch` | allowlisted network read, hash diff, no FS | http-get |
| `notes-checklist` | markdown extraction | markdown-watch |

**Studied and deferred (v2.1), not cut for lack of value:** cash-runway-meter (needs balance + burn from two sheets), dso-trend (needs 12 weeks of consistent history), pipeline-cover (needs stage-weighted CSV), deal-slip-alert (needs repeated snapshots), approval-queue (mail metadata lacks approval state), attestation-clock (needs a control register export). Each is a real job; each needs a source shape we do not have yet. Keeping them out of v1 is why the 24 can all be honest.

### 3.5 Five ideas we are deliberately not shipping

| Idea | Why not |
|---|---|
| Inbox summarizer that reads email bodies | Breaks the DLP line and the lethal-trifecta break. Metadata-only is the product promise. |
| Auto-reply / auto-send agent | Outbound action needs per-action consent; a dashboard plugin cannot be trusted with it. Defer to an explicit agent action with approval UI. |
| Arbitrary URL scraper | SSRF, robots, and content injection. Only allowlisted hosts, GET, text hash. |
| Social/personal feeds | No stable API, privacy surface, and zero work value. |
| "AI trading signals" / prediction widgets | Unfalsifiable, regulatory smell, and it would poison the trust story. |

### 3.6 Role packs

Packs are curated collections, not new code: a name, a description, a plugin list, install-all with one consent sheet, and sample data for the demo.

- **Manager pack:** sales-delta-24h, revenue-vs-target, calendar-today, meeting-prep, follow-up-watch, vip-watch, waiting-on-you, morning-brief.
- **CFO pack:** revenue-vs-target, ar-aging, budget-burn, kpi-scorecard, reconciliation-watch, renewal-radar, audit-digest, weekly-review.
- **Ops / Chief of Staff pack:** week-load, follow-up-watch, notes-actions, plugin-health, update-radar, compliance-posture, morning-brief.

---

## 4. Marketplace redesign (the DSH shape)

### 4.1 Principles

1. **Inspect before install.** The detail page renders the plugin with its own sample data, in the real card frame, before anything is installed.
2. **Plain English over manifest.** Permissions are sentences: "Reads one Excel file you choose." "Can never: run code, send mail, open network connections, read files outside your workspace."
3. **One consent sheet.** Install shows every scope at once; updates show only the diff, and only widening requires a new consent.
4. **Signed, not trusted by vibes.** Publisher verification, release signature fingerprint, digest, license, and validator report are visible, not buried.
5. **No fake social proof.** No star ratings, no download counts invented. "Used by N desks in your org" only when the audit store has real numbers; otherwise omitted.
6. **Honest states.** Offline catalog, stale peer, revoked publisher, yanked release, missing dependency: each gets a specific message and a next action.
7. **No sponsored ranking.** Search order is relevance, then recency of a signed release. Nothing is promoted for money, and no engagement bait lives in results.

### 4.1.1 Trust signals that must be real

- **Publisher proof:** verification is a DNS TXT record on the publisher's domain or a GitHub org ownership proof, plus a manual review of the publisher's first release. "Verified" is not self-serve and is never granted by installing.
- **Capability diff on update:** the update sheet shows old scopes → new scopes, with added scopes highlighted; only widening re-prompts. Minor versions cannot silently expand.
- **Named, re-runnable scanner:** the validator report states validator version, rules count, date, and license scan result. Re-running it on the installed copy is a button, not a promise.
- **Pinned releases:** installs pin a version + digest; auto-update is a channel choice, staged (5% → 25% → 100% for org catalogs), with one-click rollback. A mutable branch is never an install source.
- **Review integrity:** v1 ships **no ratings and no reviews**. If reviews come later, they are verified-install only. We do not seed reviews, and we do not show download counts we cannot substantiate.
- **Deprecation with a migration path:** deprecated and quarantined plugins keep their detail page, state the reason, the advisory id, and the recommended replacement. Removal without a path is a last resort for malware-class findings only.

### 4.2 Surfaces and routes

The marketplace is SPA-owned. `/plugins` becomes a 302 to `/marketplace/installed` so old links and the rail keep working; the server page is removed after one release of overlap.

| Route | Surface | Job |
|---|---|---|
| `/marketplace` | Discover | search, categories, role packs, org picks, updates banner, trust strip |
| `/marketplace/search?q=&category=&source=&risk=` | Results | filters, honest zero state, "request a plugin" |
| `/marketplace/c/:category` | Category | six categories, curated order |
| `/marketplace/plugin/:id` | Detail | live sample render, permission sheet, version history, changelog, install/update |
| `/marketplace/collections/:slug` | Pack | install-all consent sheet |
| `/marketplace/installed` | My plugins | status, updates, pending consent diff, rollback, purge, share to peers |
| `/marketplace/publisher` | Studio | my plugins, new plugin, validation report, publish |
| `/marketplace/publisher/:id` | Manage | releases, changelog, deprecate, yank |
| `/marketplace/admin` | Admin | policy, pending publications, allowlist, kill switch, audit export |
| `/marketplace/trust` | Trust center | how verification works, what can never happen, report a plugin |

Marketplace has its own sub-navigation: **Discover** (featured, new, updated, collections) · **Browse** (six categories) · **Search** · **Installed** · **Publishers** · **Submit**. App nav: Dashboard, Inbox, **Marketplace**, My plugins, Team, Assistant, Memory, Activity, Settings, Admin (only when policy marks this desk as admin). Marketplace replaces the old Plugins rail entry; the devproxy route test is updated in the same ticket.

### 4.3 Detail page anatomy (the trust surface)

1. **Header:** name, one-line summary, publisher (verified badge or "Self-published, unverified"), version, category, license, risk.
2. **Preview:** real render with the packaged sample, `SAMPLE DATA` chip, same card frame as the dashboard.
3. **What it shows:** the three highlights, each tied to an element in the preview.
4. **What it reads:** sentence per scope, with the exact setting it depends on.
5. **What it can never do:** fixed list, generated from class + declared scopes, not authored by the publisher.
6. **Trust:** signature fingerprint, digest (short + copy full), validator report (pass, rule count), publisher key, release date.
7. **Versions:** table of version, date, changelog, capability diff, host range, yanked/quarantined flag.
8. **Alternatives:** up to three plugins that answer the same question, ranked by fit, never sponsored.
9. **Actions:** Install, or Open / Update / Roll back / Uninstall if installed. Sticky action bar on scroll.
10. **Report:** "Something wrong with this plugin?" writes an audit event and opens a prefilled report.

### 4.4 Publisher studio

Three entry points, one pipeline:

- **Start from installed:** clone a plugin you already use into a draft (the "fork" path).
- **Start from a folder:** point at a local folder that already has `plugin.json` + `ui-schema.json`.
- **Start from a template:** blank, manual metric, CSV table, JSON bridge, Excel delta. Plain-English wizard: "What do you want to track?" → pick source → map columns → pick element → preview → publish.

Pipeline: **validate** (same validator the client runs, byte-identical) → **preview** (sample render) → **version** (semver, auto-suggested bump from scope/fields) → **changelog** (required, plain text) → **license + distribution grant** (SPDX, permission to redistribute inside the org) → **publish** (writes a release into the org catalog as *pending review*; admin approves in Admin).

A failed validation shows a report, not a stack trace: rule id, field path, what to fix. The draft is kept; nothing half-published exists.

### 4.5 Catalog data model v2

`registry/index.json` (org/community catalog):

```json
{
  "schemaVersion": 2,
  "org": { "id": "acme", "name": "Acme", "anchorFingerprint": "SHA256:..." },
  "publishers": [
    { "id": "agent-desk", "name": "Nexuus Bot", "verified": true,
      "keys": [{ "fingerprint": "SHA256:...", "publicKey": "base64...", "validFrom": "2026-11-01", "revokedAt": null }] }
  ],
  "plugins": [
    { "id": "sales-delta-24h", "name": "Sales delta", "publisher": "agent-desk",
      "category": "finance", "tags": ["sales"], "summary": "Pipeline change since yesterday",
      "license": "Apache-2.0", "risk": "low", "class": "declarative", "latest": "1.2.0",
      "releases": [{ "version": "1.2.0", "sha256": "...", "tag": "v1.2.0",
                     "publishedAt": "2026-11-10", "changelog": "...", "signature": "base64...", "minHost": "0.1.0", "yanked": false }] }
  ]
}
```

Bundled catalog (`registry/bundled/index.json`) uses the same schema, generated at build time from `registry/plugins/` so it cannot drift. Sources are merged for the API with an explicit `source` field: `bundled | org | peer`.

**Signing:** Ed25519 detached signatures, minisign-style envelope, **pure-Python RFC 8032 implementation** in `registry/signing.py` verified against the RFC test vectors. Zero new dependencies is a hard constraint here (`pyproject.toml` has none). Trust chain: org anchor key (pinned in policy) signs publisher certs; publisher key signs release digests; client verifies chain before install. Open mode without a pinned anchor = TOFU + "unverified" badge; curated/private modes require a valid chain. Revocation list in the catalog; revoked publisher or yanked release fails closed with an explicit code.

**Why not Sigstore/TUF now:** both need network services or a second runtime. We keep the same interface (`verify_release`) so we can swap later. Documented as a known limitation, not hidden.

### 4.6 API v2

All under the existing session guard (session token, HttpOnly SameSite=Strict cookie), Origin/Host validation, JSON only, no PUT/PATCH/DELETE verbs (match the hand-rolled server; POST for mutations).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/marketplace/catalog?q=&category=&source=&risk=&sort=` | merged catalog + install state + update flags |
| GET | `/api/marketplace/plugins/:id` | manifest, publisher, releases, permission sentences, sample render |
| GET | `/api/marketplace/installed` | installed records, updates, pending consent diffs, graveyard |
| GET | `/api/marketplace/publishers/:id` | publisher profile + verification chain |
| POST | `/api/marketplace/install` | `{id, version?}` → consent requirements or installed |
| POST | `/api/marketplace/update` | `{id}` → apply or pending consent |
| POST | `/api/marketplace/consent` | `{id, decision}` |
| POST | `/api/marketplace/rollback`, `/uninstall`, `/purge-data`, `/enable`, `/disable`, `/retest` | lifecycle, mirrors runtime |
| POST | `/api/marketplace/publish` | draft validation + publish as pending |
| POST | `/api/marketplace/deprecate`, `/yank`, `/quarantine` | publisher + admin lifecycle controls, reason + replacement required |
| GET/POST | `/api/marketplace/policy` | read posture / import signed policy |
| GET | `/api/marketplace/audit?since=` | admin audit slice + CSV export |
| POST | `/api/marketplace/report` | trust report event |

Backward compatibility: the existing `/api/registry`, `/api/plugins`, `/api/plugins/install`, `/api/registry/install` stay for one release, deprecated in the OpenAPI-ish doc and in code comments. `/plugins` redirect does not break peer-sharing forms because those live in the SPA now; peer endpoints stay.

### 4.7 Frontend implementation shape

- **No new runtime dependency, no router library.** `src/marketplace/router.ts`: pure `parseRoute(pathname)` + `navigate(path)` wrapping `history.pushState`; `useRoute` subscribes to `popstate`. Unit-tested, so deep links and back/forward are not guesswork.
- **Server fallback:** `app.py` serves `index.html` for `/marketplace` and `/marketplace/*` (and only those), after the same auth gate as `/`. A test asserts 200 + SPA shell for a deep link and 404 for unknown non-SPA paths.
- **Data layer:** `src/marketplace/api.ts` typed fetchers; components under `src/marketplace/`; shared card renderer reused from the dashboard widget path so preview and live card cannot drift.
- **Design:** light warm-paper system per `DESIGN.md` (green #14594E, paper lift, Plus Jakarta Sans, mono numerals). The current dark-glass dashboard theme is drift; the marketplace ships on-system, and the dashboard theme is pulled back in the same phase (ticket T12), not silently mixed.
- **Accessibility:** real buttons/links, focus visible, route change announced via `aria-live`, permission tables as semantic tables, no color-only status.
- **States:** loading skeleton, empty (no catalog/no results/no installed), offline catalog, error with retry, revoked/yanked/pending, permission-denied. Each has a test.

---

## 5. Enterprise layer

### 5.1 Trust and policy

**Trust root (v1, offline-verifiable).** Ed25519 org root key held by IT (2-of-3 threshold, air-gapped or HSM), `trust.json` with root version + expiry, publisher keys signed by the root, and a signed revocation list with a **monotonic epoch** and short TTL. A client that sees a stale revocation epoch fails closed rather than installing. Rotation is signed by the old root; expiry bounds the compromise window. This is TUF-lite: root + targets + timestamp semantics, no snapshot/delegations until external publishers exist.

**Verification happens twice:** at install and at load/update. Digest pinning + monotonic version + metadata expiry block rollback and indefinite-freeze attacks. Never "warn and continue" on a desktop agent.

**Provenance:** every release records builder, source commit, and digest in the catalog (SLSA-shaped, without claiming a SLSA level we have not earned). Declarative bundles are JSON, so byte-identical rebuilds are cheap and testable.

**Signed policy bundle** `policy.json` + `policy.sig`, verified against the pinned org anchor:

| Field | Values | Default |
|---|---|---|
| `mode` | `open` / `curated` / `private-only` | `curated` |
| `allowedPublishers` | ids, or `["*"]` in open | org publisher only |
| `allowedCategories` | category list | all |
| `riskCeiling` | low / medium | low |
| `networkAllowlist` | hosts | empty |
| `sources` | bundled/org/peer enabled | bundled+org |
| `killSwitch` | plugin ids blocked on this desk | empty |
| `dlp` | `bodyIngest: false`, `retentionDays` | false, 30 |
| `updateChannel` | stable / pinned | stable |
| `requireSignatures` | bool | true in curated/private |
| `versionPolicy` | allow/block exact id@version ranges | all signed releases |
| `platforms` | windows / any | windows |
| `revocationEpoch` | minimum accepted epoch | catalog's current epoch |

Risk tiers drive review, not UI theatre: **T0** internal signed declarative; **T1** local files read-only; **T2** network or plugin-data write, needs admin; **T3** mail/calendar/credential-adjacent, needs security review. The detail page shows the tier and what it implies.

Precedence: signed policy > local admin setting > built-in default. Invalid/expired signature → safe default + visible amber banner + audit event. The client never trusts an unsigned policy in curated/private mode.

**Admin surface** shows: org name and anchor fingerprint, policy mode and last verification, pending publications with diff, publisher allowlist and revocations, network allowlist, kill switch, installed inventory with versions/digests, audit export, private catalog source (path/URL), and a "what this app touches" snapshot. Read-mostly by design; the mutation of record is the signed policy file, imported here, not hand-edited in the UI.

**No fake RBAC.** One Windows user runs the desk. "Admin" is a mode enabled by policy presence + a local confirmation, not a fake role system. Multi-user/SSO is explicitly deferred; saying so is better than shipping a permission checkbox that does nothing.

### 5.2 Deployment and licensing

- **Build:** Nuitka one-folder, signed executable; no bundled interpreter assumptions beyond the build. AppLocker/WDAC publisher rule is the real deployment gate, documented for IT.
- **Licensing:** open-core. Core EULA proprietary; plugin SDK Apache-2.0 so customers and partners can publish; bundled plugins Apache-2.0. CI gates: allowlist MIT/Apache-2.0/BSD/ISC (minisign is ISC, not MIT, so the allowlist must say ISC), block Commons Clause/SSPL/AGPL, regenerate `THIRD-PARTY.md` and a CycloneDX 1.6 SBOM on every build, fail on drift or unknown SPDX.
- **Landmines to clear before any external distribution:** react-bits Commons Clause vendored components, unlicensed teammate code, `agent-desk-registry` has no LICENSE. These are tickets, not footnotes.
- **Data:** per-plugin data dir under `pluginData`, purge with typed confirmation, audit of every install/consent/egress/denial, retention per policy, no telemetry by default.

### 5.3 What we explicitly defer

SSO, fleet management, central admin console, cloud sync, paid marketplace, Sigstore/TUF, mobile, email-body ingestion, autostart. Each is named in the IT one-pager as "not in this release," so the absence is a decision rather than an omission.

---

## 6. Architecture changes

New/changed modules (no code in this plan, just seams and ownership):

| Path | Change |
|---|---|
`registry/manifest.py` | v2 schema, normalization, v1 compatibility |
`registry/lint.py` | element-kind whitelist, source whitelist, network/FS mutual exclusion, sample fixture check |
`registry/executor.py` | 12 sources, 10 elements, binding resolver; unknown kind = hard error now |
`registry/signing.py` | RFC 8032 Ed25519 sign/verify, key encoding, envelopes, revocation |
`registry/index.py` | index v2 load/merge, publisher lookup, release resolution, verification chain |
`registry/install.py` | verify signature before extract, source-aware install, catalog sources |
`plugins_runtime/runtime.py` | manifest v2 normalization, dependency (aggregate) resolution, update diff display data |
`server/marketplace_view.py` (new) | JSON API handlers, permission sentence generator, eligibility |
`server/marketplace_publish.py` (new) | draft staging, validation report, publish-as-pending |
`server/policy.py` (new) | signed policy load/verify/precedence, kill switch |
`server/plugins_view.py` | shrink to redirect; keep legacy until T5 ships |
`server/app.py` | routes, SPA fallback, guards, deprecations |
`frontend/src/marketplace/*` (new) | router, api, pages, components, tests |
`registry/bundled/index.json` (generated) | bundled catalog |
`registry/plugins/*` | 24 + 6 manifests and samples |
`docs/` | spec, tickets, IT one-pager, plugin authoring guide |

**Compatibility:** manifest v1 plugins keep installing and rendering. Index v1 still loads (wrapped into v2 shape) so existing desks do not break on upgrade. `/plugins` redirect is one release; peer-sharing endpoints unchanged.

---

## 7. Delivery plan

Four phases, twelve tracer-bullet tickets, each independently demoable. Every ticket: TDD at the agreed seams, typecheck + targeted tests then full suite, subagent review, commit. Publishing to the tracker waits for Ken's seam answer and ticket quiz (to-spec / to-tickets gates).

**P0 — Platform v2 (must land first; everything else depends on it)**
- **T1 Manifest v2 + richer rendering.** v1/v2 validation, 10 elements, sample fixture rendering end to end, unknown kind = error. Demo: a v2 plugin with table + sparkline renders.
- **T2 Sources v2.** csv-watch, json-watch, markdown-watch, manual-metric, desk-state, compare, aggregate; http-get behind policy. Demo: one plugin per source with sample, empty, stale.
- **T3 Catalog + signing foundation.** index v2, bundled catalog generation, Ed25519, publisher chain, verification on install, revocation. Demo: tampered release fails closed.

**P1 — Marketplace core**
- **T4 Catalog API + eligibility.** merged sources, search/filter, permission sentences, install-state, policy gating. No UI.
- **T5 Discover / Search / Detail / Pack.** SPA routes, deep-link fallback, live preview, consent sheet, trust block, empty/offline states.
- **T6 Installed + Publisher Studio.** updates with scope diff, rollback, purge, share; draft → validate → preview → publish-as-pending; admin approval minimal. `/plugins` redirect.

**P2 — Portfolio**
- **T7 Finance + time batch (11 plugins).** Real workbooks/CSVs, samples, role-pack metadata.
- **T8 Communication + research + ops batch (9 plugins).** Bridges, desk-state, http-get reference, aggregates.
- **T9 Role packs + first-run.** three packs, install-all consent, onboarding empty states, demo data set.

**P3 — Enterprise**
- **T10 Policy + admin + trust center.** signed policy, anchor pinning, kill switch, admin surface, audit export.
- **T11 Packaging + license gates.** Nuitka profile, signing, SBOM/THIRD-PARTY CI, license landmine cleanup, IT one-pager.
- **T12 Hardening + design pull-back + demo walkthrough.** dark-glass drift fix, a11y, perf, full-flow e2e, docs, scripted demo.

Dependencies: T1→T2→T3→T4→T5/T6; T2→T7/T8; T5/T6→T9; T3→T10; T11 parallel from T6; T12 last.

**Testing seams (recommendation, needs Ken's one-line approval):**
1. **Server HTTP seam** (pytest, existing convention): routes, guards, consent codes, policy gating, SPA fallback.
2. **Registry package seam** (pytest): manifest/lint/executor/signing/index/install as pure functions, RFC vectors, tamper cases.
3. **SPA component seam** (vitest + testing-library + jsdom, existing convention): router, pages, consent diff, states, a11y roles.

No new e2e harness in this pass; a scripted walkthrough covers the demo.

---

## 8. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 24 plugins becomes 24 half-done plugins | High | High | Capability model first; batch by source; each plugin has a sample + empty-state test; cut to 18 if T2 slips |
| Validator/manifest churn breaks existing installs | Medium | High | v1 compatibility tests, normalize both, migration in T3, no silent key drops |
| Deep links 404 in the packaged app | Medium | Medium | Server fallback + test in T5; devproxy route test updated |
| Signature code is homegrown crypto | Medium | High | RFC 8032 vectors, verify-only in install path, pinned anchors, threshold root, documented limitation, swap interface for Sigstore later |
| Missing source renders as a confident zero | Medium | High | STALE/BLANK/COARSE/PARTIAL taxonomy enforced by the card frame, not by each plugin author |
| Fake trust signals creep in | Medium | High | No ratings/counts unless audit-backed; "can never" list generated, not authored |
| Publishing writes to a git checkout on a locked-down laptop | High | Medium | Enterprise mode publishes a signed release packet + pending review; no git required on the client |
| License landmines (Commons Clause, unlicensed code) | High | High | T11 gate blocks release before distribution; track as release blocker |
| Demo fails on a missing workbook | Medium | High | Bundled sample data + explicit "sample" labelling; demo script uses only shipped fixtures |
| Admin/auth overreach | Medium | Medium | No fake RBAC; signed policy is the control; defer SSO honestly |
| Trust theatre (badges without evidence) | Medium | High | Publisher proof is DNS/GitHub + manual review; validator report is dated and re-runnable; no reviews in v1 |
| Abandoned plugin left installed | Medium | Medium | Deprecation states with reason + replacement; update-radar surfaces age and yanked state |

---

## 9. Success metrics

- **Adoption:** 4/5 workdays with at least one plugin viewed by week 4; 60% of installs active within 3 days.
- **Portfolio:** 18 of 24 plugins used by at least one persona in the demo cohort; 6 with a real workbook connected.
- **Marketplace:** search→detail→install conversion tracked locally; publish-to-approval under 1 day; zero unsigned installs in curated mode.
- **Trust:** zero critical policy violations in audit; 100% of installs show permission sheet; 100% of cards carry an as-of stamp; all releases verified.
- **Quality:** full pytest + vitest green in CI; no P1 bug open at demo.

---

## 10. Open decisions for Ken (recommendations attached)

1. **Seam cut:** approve the three seams above? *Recommend yes.*
2. **http-get in v1:** ship `competitor-watch` now with allowlist + no-FS rule, or defer? *Recommend ship one reference plugin behind admin policy; it proves the network boundary.*
3. **Portfolio size:** 24 in-box vs 18? *Recommend 24 planned, first batch 11 finance/time, second 9, aggregates last. Cut the 4 aggregates first if time slips.*
4. **Admin model:** signed policy + local admin mode, no RBAC? *Recommend yes; document deferral.*
5. **Product name:** keep **Nexuus Bot**? *Recommend yes; marketplace is a surface, not a second brand.*
6. **Marketplace placement:** SPA `/marketplace`, `/plugins` redirects? *Recommend yes.*

---

## 11. What happens on approval

1. Write the spec with **to-spec** (seams section includes the three seams; no interview loop).
2. Publish the spec as an issue on `kanitmann01/agent-desk` (private, `ready-for-agent`), after the ticket quiz.
3. Write tickets with **to-tickets** (12 slices, blocking edges), publish them.
4. Implement T1–T3 in this worktree via **implement** + subagents, TDD, reviews; then T4 onward.
5. Commit and push to `kanitmann01/agent-desk` only after subagent review, per standing rule.

**The one thing I need from you:** a one-line answer on the seam cut (item 1). Everything else I will proceed on with the recommendations above unless you override.


---

## Appendix A: manifest v2, concretely

```json
{
  "schemaVersion": 2,
  "id": "ar-aging",
  "name": "A/R aging",
  "version": "1.0.0",
  "publisher": "agent-desk",
  "class": "declarative",
  "license": "Apache-2.0",
  "minHost": "0.2.0",
  "category": "finance",
  "tags": ["cash", "collections"],
  "icon": "table",
  "summary": "Overdue cash by age bucket, from one workbook.",
  "description": "Reads your A/R workbook, buckets open invoices by days past due, and names the largest overdue accounts. Metadata-only; the file never leaves the machine.",
  "highlights": [
    "Total overdue above 30 days",
    "0-30 / 31-60 / 61-90 / 90+ buckets",
    "Top five accounts to call"
  ],
  "sample": "sample.json",
  "permissions": {
    "filesystem": { "read": ["ar/*.xlsx"], "write": [] },
    "network": { "allow": [] },
    "desk": { "read": [] },
    "llm": "none",
    "shell": "none"
  },
  "contributes": {
    "widgets": [{
      "id": "aging",
      "title": "A/R aging",
      "size": "wide",
      "dataSource": {
        "type": "excel-watch",
        "file": "ar/aging.xlsx",
        "sheet": "Open",
        "headerRow": 1,
        "keyColumn": "Invoice",
        "valueColumn": "Amount",
        "dateColumn": "DueDate",
        "window": "all-open"
      },
      "render": { "type": "ui-schema", "file": "ui-schema.json" }
    }]
  }
}
```

`ui-schema.json` (abridged) uses only v2 elements and bindings the host resolves:

```json
{
  "schemaVersion": 2,
  "layout": { "columns": 1 },
  "elements": [
    { "kind": "metric", "bind": "overdue30", "label": "Overdue >30d", "unit": "USD", "tone": "alarm" },
    { "kind": "table", "bind": "buckets", "columns": ["Bucket", "Invoices", "Amount"] },
    { "kind": "list", "bind": "topAccounts", "primary": "account", "secondary": "amount", "meta": "daysLate" }
  ]
}
```

Every payload carries `{ value, asOf, source, state }` per element, so the card frame can render `STALE` / `BLANK` / `COARSE` / `PARTIAL` without the plugin author writing UI logic. That is the contract the portfolio depends on.
