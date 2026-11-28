# P7 review: four direct commits to main

Review pinned to `0f622e3`, compared with `37515e9`. Code was read in the read-only worktree at `3540b9f`. No tests, gates, builds, walkthroughs, application, worktree operations, installs, or reads of the user's application data folder were performed.

## 1. Images

The Read tool was called on every PNG. This environment returned the image attachments without exposing their pixels to the reviewer, so the PNGs were also read with local OCR, including word coordinates and an enlarged crop of the dashboard's lower-right card. SVG files and embedded badge data were read as text. Searches covered person and organization names, employer and client context, email addresses and mail excerpts, calendar details, real workbook and sheet names, usernames in paths, token-bearing URLs, internal hostnames, and visible keys, tokens, passwords, or other secrets. The local brand gate was read, not run: `tools/ci_local.py:233-240,270` invokes `tools/brand_leak.py`, which hashes tokens and media bytes and scans only committed presentation pack roots, not README images. Its committed denylist is empty. It does not ban the retired working name. The images were therefore judged by the brief's stricter rule that no employer, client, or person is named.

### `docs/readme/dashboard.png`

- **What it shows:** The existing dashboard at 1280 by 800. It contains setup steps, workbook, calendar, decision, digest, and plugin entry points, plus sample-data labels. The Decisions area names an organization and a renewal deadline. The workbook label is an explicitly synthetic sample workbook name. The key control says to add a key but displays no key value.
- **What I searched for:** Full-image OCR and coordinates, followed by searches for names, email and URL syntax, path separators, hostnames, workbook and mail labels, calendar details, and secret-like terms. The lower-right card was enlarged and read again to distinguish a button label from a publisher name.
- **Screen existence:** Holds. The route and dashboard cards exist in `frontend/src/App.tsx:58-160`, `frontend/src/dashboard/Dashboard.tsx`, and the card components under `frontend/src/dashboard/`. The server route is backed by `src/agentdesk/server/app.py` and `/api/dashboard`.
- **Verdict:** **P0, P7-01.** A named organization in a client-style renewal context must not remain in a public image under the brief's rule, even though it comes from the repository's synthetic demo fixture. No person name, email, mail excerpt, real path, internal host, token URL, or visible secret was found. The wordmark uses the old product name, as expected for the pre-rename UI and not a defect of these commits.

### `docs/readme/marketplace.png`

- **What it shows:** The existing marketplace Discover screen with search, source and risk filters, bundled plugin entries, and publisher and verification notes. No selected plugin detail or organization publisher is visible.
- **What I searched for:** Full-image OCR and coordinates, searched for all disclosure categories above, including names, email, paths, URLs, workbook labels, and secret values.
- **Screen existence:** Holds. `/marketplace` is selected by `frontend/src/App.tsx:45-47,163-176`; navigation is in `frontend/src/marketplace/context.tsx:12-29`; the Discover implementation is under `frontend/src/marketplace/`, including `Discover.tsx`.
- **Verdict:** Clean for public display. No person, employer, client, email, mail excerpt, calendar entry, real workbook or sheet name, username path, token URL, internal hostname, or visible secret was found. The wordmark uses the old product name, as expected and not a defect.

### `docs/readme/memory.png`

- **What it shows:** The existing server-rendered Memory page with learning controls and empty review state. It contains explanatory text about facts, provenance, passwords, and email bodies but no actual fact, person, organization, message, or credential.
- **What I searched for:** Full-image OCR and coordinates, searched for all disclosure categories above. Mentions of passwords and email were read in context to distinguish explanatory copy from exposed values.
- **Screen existence:** Holds. The Memory page is server-rendered and the `/memory` loop island is mounted by `frontend/src/memory/loop/island.tsx:1-16`; the route and page templates are in `src/agentdesk/server/`.
- **Verdict:** Clean for public display. No prohibited name, address, path, host, workbook detail, calendar entry, mail excerpt, or secret was found. The wordmark uses the old product name, as expected and not a defect.

### `docs/readme/architecture.svg`

- **What it shows:** An original diagram of local workbook, calendar, and mail-header sources; React and Python; SQLite; the OS keychain; user-selected model, research, and paired-desk services; and plugin controls.
- **What I searched for:** All text nodes, title and description, SVG source, paths, URLs, and embedded data. The only network literal is the loopback address. No external image or font fetch is present.
- **Verdict:** Clean for public display. No person, employer, client, email, mail excerpt, real workbook or sheet name, username path, token URL, internal hostname, or secret was found. It uses the approved product name.

### `docs/readme/badges/python.svg`

- **What it shows:** Python 3.10+ badge with an inline icon.
- **What I searched for:** Text, accessibility labels, external references, URLs, paths, and embedded data.
- **Verdict:** Clean. The icon is an inline data URI, not a third-party request.

### `docs/readme/badges/react.svg`

- **What it shows:** React 19 badge with an inline icon.
- **What I searched for:** Text, accessibility labels, external references, URLs, paths, and embedded data.
- **Verdict:** Clean. The icon is an inline data URI, not a third-party request.

### `docs/readme/badges/network.svg`

- **What it shows:** Network: Loopback only badge.
- **What I searched for:** Text, accessibility labels, external references, URLs, paths, and embedded data.
- **Verdict:** Clean. No external reference is present.

### `docs/readme/badges/license.svg`

- **What it shows:** License: Proprietary badge.
- **What I searched for:** Text, accessibility labels, external references, URLs, paths, and embedded data.
- **Verdict:** Clean. No external reference is present.

## 2. README claims

All line references in this section are to `README.md` at `0f622e3`. Code references are to the read-only `3540b9f` worktree, which has the same code as the pinned commit because the four reviewed commits change only documentation, images, and the naming test.

| Claim | Where I checked it | Holds or finding |
|---|---|---|
| Line 3: local-first workspace for workbook, calendar, exported mail, memory, agents, and plugins | `src/agentdesk/excel/`, `calendar/`, `mail/`, `memory/`, `agents/`, `plugins/`, and `marketplace/` | Holds |
| Line 3: shows what changed | `src/agentdesk/excel/store.py:20-94`; `frontend/src/dashboard/briefModel.ts:1`; `Dashboard.tsx` | Holds |
| Line 3: answers work questions | `src/agentdesk/assistant/loop.py:69-133`; `server/research.py:40-70` | Holds |
| Line 3: records facts with sources | `src/agentdesk/memory/store.py:1043-1067,1301-1325`; `server/memory_api.py` | Holds |
| Line 3: keeps plugin actions behind visible controls | `src/agentdesk/plugins/runtime.py:289-364`; `frontend/src/marketplace/Installed.tsx:301-376` | Holds |
| Line 5: CI badge target exists | `.github/workflows/enterprise.yml:1-18` | Holds. The badge image is fetched from GitHub when the README is rendered. It is not a Shields request. GitHub receives that request, as it does for normal repository page views. |
| Line 6: Python badge target and 3.10+ value exist | `pyproject.toml:6`; `docs/readme/badges/python.svg` | Holds. Local inline SVG, no view-time third-party fetch. |
| Line 7: React badge target and React 19 value exist | `frontend/package.json:15-20`; `docs/readme/badges/react.svg` | Holds. Local inline SVG, no view-time third-party fetch. |
| Line 8: Network badge target exists and says loopback only | `docs/PRD.md:114-119`; `src/agentdesk/server/cli.py:8-10`; `server/app.py`; `docs/readme/badges/network.svg` | Holds for the HTTP server. LAN peer discovery is separately disclosed at line 93. Local SVG, no third-party fetch. |
| Line 9: License badge target and proprietary status exist | `LICENSE:1-12`; `docs/readme/badges/license.svg` | Holds. Local SVG, no third-party fetch. |
| Line 11: single-user evaluation software | `LICENSE:26-44`; `docs/licensing.md:9-22`; `docs/known-limitations.md:12-19` | Holds |
| Line 11: core uses a proprietary draft license | `LICENSE:1-12`; `LICENSE-SDK`; `docs/licensing.md:3-22` | Holds |
| Line 11: no signed installer exists | `.github/workflows/enterprise.yml:168-242`; `scripts/build_bundle.py:262-268`; `docs/ops/distribution.md:287-305` | Holds. CI can upload an unsigned one-folder bundle, not a signed installer. |
| Line 11: no released distribution exists | GitHub releases API at review time returned zero releases; the only workflow has no release publishing step | Holds |
| Line 14 alt: dashboard has workbook, calendar, decision, and plugin cards | `dashboard.png`; `frontend/src/dashboard/Brief.tsx`, `SalesCard.tsx`, `CommitmentsCard.tsx`; `server/dashboard_state.py:241-313` | Holds. The old wordmark is expected, not a defect. |
| Line 19: morning brief from workbook changes, calendar commitments, decisions, and desk health | `frontend/src/dashboard/briefModel.ts`; `Brief.tsx:129-190,313-320`; `server/dashboard_state.py:286-385` | Holds |
| Line 20: named OpenAI-compatible endpoints and per-job model routing | `src/agentdesk/keys/store.py:62-68,317-368`; `keys/resolve.py:94-121`; `llm.py` | Holds |
| Line 21: research questions and repeatable saved skills | `server/research.py`; `src/agentdesk/repetition/skills.py:1-3,124-125`; `server/app.py:4776-4816` | Holds |
| Line 22: local memory graph, sources, review, optional encryption, and graph view | `memory/store.py:953-1067,1414-1582,1813-1851,1945-1958`; `server/memory_api.py:537-580`; `server/graph_view.py` | Holds |
| Line 23: worksheet-brief and presentation agents with receipts and sources | `src/agentdesk/agents/registry.py:39-53`; `agents/runner.py:50-90`; `agents/store.py:24-100`; `server/agents_view.py:122-181,253` | Holds |
| Line 24: browse, validate, install, update, and roll back Class D plugins through one consent path | `marketplace/api.py:1183-1225,1395-1408,1515-1646`; `plugins/runtime.py:289-364,366-414,514-587`; `frontend/src/marketplace/` | Holds |
| Line 28: Python 3.10 or later | `pyproject.toml:6`; both launchers check 3.10; `tools/ci_local.py:70-96` parses under 3.10 grammar | Holds |
| Line 28: use Python 3.12 for the full development gate | `.github/workflows/enterprise.yml:20-242` uses 3.12 throughout | Holds as the hosted full-gate environment. The local gate itself uses the invoking interpreter. |
| Line 28: frontend development tools require Node | `frontend/package.json:8-33`; `.github/workflows/enterprise.yml:100-120` | P7-03. Node is required, but the minimum compatible version is omitted. |
| Lines 31-33: clone, enter repository, editable dev install | Public repository exists; `pyproject.toml:1-19` defines the package and `dev` extra | Holds. Commands exist and install runtime plus test dependencies. |
| Line 36: Windows double-click launcher exists and starts the server | `tools/agent-desk.cmd:1-45`; `src/agentdesk/server/cli.py:52-70` | Holds. It checks Python 3.10, uses windowless Python when available, and has a uv fallback. |
| Lines 38-42: macOS launcher exists and chmod command makes it executable | `tools/agent-desk.command:1-33`; `tools/*.command` | Holds. The launcher checks Python 3.10 and has a uv fallback. |
| Line 47: terminal server command exists | `src/agentdesk/server/__main__.py`; `server/cli.py:21-70` | Holds |
| Line 50: `--no-browser` skips browser open | `server/cli.py:38-42,68-69` | Holds |
| Line 50: server binds to 127.0.0.1 only | `server/cli.py:8-10`; `server/core.py:24-25`; `server/app.py` server construction | Holds |
| Line 50: one-time start link creates a local session | `server/auth.py:29-97`; `server/app.py:7281-7284` | Holds |
| Line 52: Settings is the normal configuration path | `server/settings_view.py`; Settings route in `server/routes.py` | Holds |
| Line 52: optional text config paths are correct | `src/agentdesk/config.py:1-15,41-60`; `Path.home()` resolves to the stated Windows and macOS profiles | Holds for paths. See P7-04 for the unqualified key-storage claim elsewhere. |
| Line 58 alt: memory image shows facts, sources, and graph controls | `memory.png`; `server/memory_view.py`; `frontend/src/memory/` | Holds for the page type and controls. The image is an empty sample state, not populated facts. |
| Line 60: edit, delete, merge, sweep, and encrypt memory | `memory/store.py:953-1023,1414-1582`; `server/memory_api.py` | Holds |
| Line 60: newer facts replace older values | `memory/store.py:2018-2039,2383`; `memory/loop.py` | Holds |
| Line 60: recall skips superseded values unless kept | `memory/store.py:1945-1958`; `server/memory_api.py:1023-1038` | Holds |
| Line 64 alt: marketplace image shows a sample plugin catalog | `marketplace.png`; `frontend/src/marketplace/Discover.tsx`; `marketplace/api.py:470` | Holds |
| Line 66: marketplace combines bundled, organization, and peer catalogs | `marketplace/api.py:228-236`; `marketplace/catalog.py:469-478` | Holds |
| Line 66: install verifies catalog pins and validates before writing plugin files | `marketplace/api.py:1104-1124,1183-1218`; `plugins/runtime.py:300-338` | Holds. The source tree is digest-checked, then validated, then staged and moved into place. |
| Line 70: `excel-report` is a working configurable workbook tracker | `registry/plugins/excel-report/manifest.json:3-32`; `widget.ui.json`; `plugins/execute.py`; `plugins/tracker.py` | Holds |
| Line 71: `competitor-watch` cannot run because production has no HTTP transport | `registry/plugins/competitor-watch/manifest.json:54-57`; `plugins/execute.py:237-253,400-407`; `docs/known-limitations.md:31-40` | Holds |
| Line 72: `presentation-starter` provides templates and tools but no dashboard card | `registry/plugins/presentation-starter/manifest.json:28-55`; `server/dashboard_state.py:241-253` | Holds |
| Line 74: updates show new permission scopes before applying | `plugins/runtime.py:366-414`; `marketplace/api.py:1515-1621`; `frontend/src/marketplace/Installed.tsx` | Holds |
| Line 74: rollback restores the previous release | `plugins/runtime.py:514-587`; `registry/install.py:311-340` | Holds |
| Line 74: uninstall keeps plugin data | `plugins/runtime.py:589-611`; `frontend/src/marketplace/Installed.tsx:354-356` | Holds |
| Line 74: purge requires typed `delete-data:<id>` | `plugins/runtime.py:614-630`; `frontend/src/marketplace/Installed.tsx:33-43,365-376` | Holds |
| Line 78 alt: architecture image shows the named layers and controls | `architecture.svg:18-102`; module inventory below | Holds, subject to P7-04 for the absolute keychain wording. |
| Line 80: loopback Python server with session, Host, and Origin guards | `server/core.py:16-25`; `server/auth.py`; `server/guard.py:67-90`; `server/app.py` | Holds |
| Line 81: committed React bundle serves dashboard and marketplace; other pages use server rendering | `frontend/src/App.tsx:1-10,163-176`; `server/static/spa/`; `server/pages.py`; `server/memory_view.py` | Holds |
| Line 82: SQLite stores source snapshots, memory, audit, plugin state, and run history | `excel/store.py:20-94`; `memory/store.py`; `ledger/store.py`; `plugins/runtime.py:190-219`; `agents/store.py:24-100` | Holds |
| Line 83: OS keychain stores model keys and SQLite keeps masked hints | `keys/store.py:1-5,99-111`; `keys/secrets.py`; `server/settings_view.py:965-980` | P7-04. This is the normal saved-connection path, not an absolute rule. |
| Line 84: OpenAI-compatible connections use chosen endpoint and model | `keys/store.py:317-338`; `keys/resolve.py`; `llm.py` | Holds |
| Line 85: optional sidecar calls only four desk-owned tools | `engine/vocab.py:61-90` defines exactly four; `engine/sidecar.py:202-221` constrains the child to the zero-tool safe toolset | Holds. The desk parses and executes only its four proposed actions. |
| Line 85: fixed loop remains the default | `engine/sidecar.py:21-23`; `server/app.py:809-812`; `agentloop/loop.py` | Holds |
| Line 89: raw workbook and mail files stay on the machine | `excel/shadow.py:1-7,23-54`; `mail/core.py:91-129`; `insight/workbook.py`; `mail/brief.py` | Holds for raw file bytes. Derived selected context can be sent as line 91 discloses. |
| Line 90: mail reads headers only and never parses bodies | `mail/core.py:1-13,91-129`; `mail/watcher.py:1-11` | Holds for stored and returned data. The stdlib parser sees the whole input string but only header values are copied out; no body field exists downstream. |
| Line 90: mail is off by default | `mail/__init__.py:1`; `server/app.py:870-882`; `_default_mail_watch` | Holds |
| Line 91: typed questions and selected context go to the configured model endpoint | `assistant/context.py`; `assistant/loop.py:108-133`; `keys/resolve.py` | Holds |
| Line 92: optional presentation research sends topics and section titles | `presentations/research.py:1-4,34-45`; `presentations/pipeline.py:118-130` | Holds |
| Line 93: peer discovery announces desk identity on the local network | `peers/discovery.py:1-17,66,117-125,210-220`; `server/app.py:1003-1023` | Holds. It starts only after a human opens the peers surface. |
| Line 93: sharing transfers only selected plugin bundles | `peers/store.py:325-342`; `peers/client.py:149-162`; `server/app.py:6518-6537` | Holds |
| Line 94: Class D plugins use manifests and declarative UI, with no shell or plugin HTML | `plugins/html.py:29-46` escapes schema values; `plugins/execute.py:1-20`; `registry/plugins/*/manifest.json` shell declarations | Holds |
| Line 95: audit ledger records actions | `ledger/store.py`; `assistant/audit.py`; marketplace and memory audit calls | Holds |
| Line 95: consent, undo, digest pins, rollback, and quarantine protect plugin changes | `plugins/runtime.py`; `ledger/undo.py`; `marketplace/api.py:1104-1124,1515-1646`; `marketplace/policy.py` | Holds |
| Line 96: memory encryption is optional and off by default | `server/app.py:7968-7990` loads a key only if the key file exists; `memory/store.py:23-47` | Holds |
| Lines 100-105: backend tests, demo readiness, and local gate commands exist | `tests/`; `tools/demo_readiness.py:1308-1312`; `tools/ci_local.py:274-317` | Holds. None was run in this review. |
| Lines 108-115: frontend directory and all four npm commands exist | `frontend/package.json:8-13`; `frontend/package-lock.json` | Holds, subject to P7-03 for the missing Node version. |
| Line 117: full gate runs Python tests, typecheck, Vitest, license gate, registry CI, and naming guards | `tools/ci_local.py:263-271`; naming tests run inside the pytest gate; `enterprise.yml:19-166` | Holds |
| Lines 123-130: every documentation link exists and its purpose matches | Pinned tree contains `docs/PRD.md`, `docs/design-language.md`, `docs/known-limitations.md`, `docs/ops/marketplace-operator.md`, `docs/ops/distribution.md`, `docs/licensing.md`, `DEMO.md`, and `docs/evidence/`; each was checked by path and topic | Holds |
| Line 132: `/what-this-touches` and `/audit/export.csv` exist | `server/routes.py:203-204`; `server/touches.py`; `server/app.py:4936` | Holds |
| Line 132: `/marketplace/trust` exists | `frontend/src/marketplace/context.tsx:12-29`; `frontend/src/marketplace/Trust.tsx` | Holds |
| Line 136: proprietary draft has not been reviewed by counsel | `LICENSE:8-12`; `docs/licensing.md:3-7` | Holds |
| Line 137: plugin SDK is Apache-2.0 | `LICENSE-SDK`; `LICENSE:79-82`; `docs/licensing.md:13-22` | Holds |
| Line 138: no signed release | Zero GitHub releases; bundle signing status is hardcoded unsigned | Holds |
| Line 138: no SSO, RBAC, multi-user, fleet management, or MCP server | `docs/known-limitations.md:12-19`; no such server modules or routes; `engine/sidecar.py:14-15` ignores user MCP configuration | Holds |
| Line 139: no working web-page monitor ships | `plugins/execute.py:400-407`; `docs/known-limitations.md:35-40` | Holds |
| Line 140: peer sharing works on one machine; LAN desks are discoverable but not connectable | `peers/discovery.py:13-17,250-276`; `peers/store.py:13-15` | Holds |
| Line 141: no autostart, Windows service, scheduled task, or tray helper | `server/touches.py:59`; `docs/known-limitations.md:79-84`; launcher scripts | Holds |

### Architecture drawing against the module layout

- Local sources: workbook shadow copying and snapshots are in `src/agentdesk/excel/`, calendar state is in `calendar/`, and header-only exported mail is in `mail/`. These match `architecture.svg:18-32`.
- Loopback application: the React SPA is under `frontend/src/`, the Python server under `src/agentdesk/server/`, and the fixed bind and guards are in `server/core.py`, `server/guard.py`, and `server/auth.py`. These match lines 34-43.
- SQLite: workbook snapshots, memory, ledger, plugin lock state, and agent runs have separate SQLite stores in the modules named above. These match lines 45-48.
- Keychain: `src/agentdesk/keys/secrets.py` and `store.py` implement the normal path drawn at lines 50-53, but P7-04 records the plaintext exceptions.
- User-chosen services: model routing is in `keys/resolve.py`, optional presentation research in `presentations/research.py`, and selected peer bundles in `peers/`. These match lines 66-83.
- Control plane: the Class D runner is in `plugins/execute.py`, consent and undo in `plugins/runtime.py` and `ledger/undo.py`, and policy and release controls in `marketplace/` and `registry/`. These match lines 85-100.
- The footer's raw-file locality statement matches `excel/shadow.py` and `mail/core.py`. Outbound model and research paths are user-selected.

### Image notes README

- `docs/readme/README.md:5-9` accurately identifies the three screenshot subjects, the original architecture image, and local Shields-style badges.
- Lines 13-17 identify the repository, source commit, capture date, theme, and viewport. The PNG dimensions are 1280 by 800.
- Lines 22-30 name real `tools/layout_audit.py` flags. P7-05 records that the command omits the browser-binary prerequisite on a fresh machine.
- Line 33's synthetic data, fake keychain, loopback mock model, fixed clocks, and temporary folder are consistent with `tools/layout_audit.py` and the demo fixture path. The named organization in the dashboard still violates the brief's public-image rule, P7-01.
- Lines 37-39 correctly say the screenshots are unedited current UI and warn against the `long-values` condition because its fixture carries a real local username and path. That condition was not used for the committed images.

## 3. The guard

### What it asserts now

At `0f622e3`, `tests/test_brand_naming.py:50-61` asserts only two exact positive strings:

1. The first README line is exactly `# Nexuus Bot`.
2. `frontend/src/face/name.ts` contains the exact canonical constant assignment for the approved agent-face name.

The retained test at lines 64-87 still rejects U+2014 in its configured live roots and files. `NAME_ROOTS` and `SCAN_FILES` are still used to build `LIVE_ROOTS` and `LIVE_FILES`. No constant or helper became unused because of this patch. `ARCHIVE_DIRS` was already redundant: the following `rel_posix.startswith("docs")` check skips every `docs/` path, while the archive prefixes do not match the actual `docs/...` layout. That is pre-existing, not a new regression.

### What it lost

The previous test walked `src`, `tools`, `scripts`, `docs/ops`, `frontend/src`, and the named manifest and README files, case-insensitively rejecting the retired working name `nexuus`. That walk is gone. The replacement does not assert that the retired working name is absent, does not assert that build metadata uses the approved product name, and does not scan the README beyond its first line.

The loss is observable at the pinned commit. `scripts/build_bundle.py:120-122,239` still stamps the Windows product, company, description, and manifest product with the old product name. `frontend/src/dashboard/Rail.tsx:81-134` still renders the old wordmark. The new tests pass regardless. The old wordmark in screenshots is expected input to the rename work, but the build metadata is shipped naming, not a screenshot. This is P7-02.

### Reading of whether it passes

It would pass at `0f622e3`, by reading:

- The pinned README's first line is exactly the expected approved title.
- The pinned face module at `frontend/src/face/name.ts:2` contains the exact expected constant.
- A read-only `git grep` for the UTF-8 bytes of U+2014 across `src`, `tools`, `scripts`, `docs/ops`, `frontend/src`, `tests`, `README.md`, `DEMO.md`, `frontend/README.md`, `frontend/package.json`, `frontend/index.html`, and `docs/docstrings.md` returned no matches.

I separately searched the complete new `README.md`, `docs/readme/README.md`, `docs/readme/architecture.svg`, and all four new badge SVGs for U+2014 and U+2013. Every count was zero. I also searched those complete files for an at-sign followed by a username; every at-sign count was zero. The new SVG directory is not covered by the retained test's roots, so these were separate source searches, not an assumption about the guard. No test was run.

## 4. Findings in full

### P7-01: P0: Public dashboard image names an organization in a client renewal context

- **File and line:** `docs/readme/dashboard.png`, Decisions card in the lower half of the image, around 72 percent of the image height.
- **What:** The public screenshot displays a named organization together with a renewal deadline and a statement that the user told the desk about it. The value is deliberately not reproduced here.
- **Why:** The brief's public-image rule forbids naming an employer, client, or person. A client-style organization and renewal detail must not remain public. The image's sample-data label and the fixture's synthetic origin do not change what a stranger can see.
- **Evidence:** Full-image local OCR located the organization and deadline in the Decisions card. The same organization is seeded by `src/agentdesk/server/demo_data.py:82,264,463-472` and appears in recommendation tests. `tools/brand_leak.py:27-40` scans only presentation pack roots and cannot protect README PNGs. Its committed hash denylist is empty.
- **Fix:** Remove or replace the current public PNG. Recapture with a public-safe fixture that contains no organization or person names and no client-style renewal detail, then review the replacement image before committing. Do not rely on the sample-data label or the presentation-pack gate.
- **Confidence:** High.

### P7-02: P1: The replacement naming guard passes while shipped naming still uses the old product name

- **File and line:** `tests/test_brand_naming.py:50-61`.
- **What:** The patch deletes the case-insensitive retired-working-name walk and replaces it with two exact positive assertions. It no longer guards the user-visible source tree, build scripts, operations guides, demo script, or frontend manifest against the retired working name.
- **Why:** A green naming test now means only that two strings exist. It can pass while shipped executable metadata and other live surfaces keep the old product name. That is the severity definition of a guard that passes while what it names is broken.
- **Evidence:** The compare patch removes `RETIRED_NAME` and `test_every_surface_says_agent_desk_not_the_retired_name`. At `0f622e3`, `scripts/build_bundle.py:120-122` passes the old name to Nuitka's Windows product, company, and description flags, and line 239 records it as the manifest product. `frontend/src/dashboard/Rail.tsx:81-134` also renders the old wordmark. Neither is read by the new assertions.
- **Fix:** Keep the two positive canonical-name tests, and restore a scoped negative walk for the retired working name across live shipped surfaces. Add explicit assertions for the bundle's product and company metadata. Define the intentional rename exceptions and screenshot policy separately rather than deleting the walk.
- **Confidence:** High.

### P7-03: P2: Frontend prerequisite says Node but omits the incompatible-version boundary

- **File and line:** `README.md:28`.
- **What:** The quick start says the frontend development tools require Node without giving a minimum. The pinned Vite dependency requires Node `^20.19.0` or `>=22.12.0`.
- **Why:** A new developer with an older Node 20 or Node 22 installation can follow every command and still fail during install or build. The hosted workflow's Node 22 choice does not tell a local reader which versions are supported.
- **Evidence:** `frontend/package.json:32` pins Vite 7.3.8. The installed package metadata at `frontend/node_modules/vite/package.json:56-58` declares `^20.19.0 || >=22.12.0`. `.github/workflows/enterprise.yml:105-108` uses Node 22.
- **Fix:** State the exact supported range in the README, for example Node 20.19 or later within 20.x, or Node 22.12 or later. Consider adding an `engines` field to `frontend/package.json` so package managers can enforce it.
- **Confidence:** High.

### P7-04: P2: The keychain claim is absolute although supported configuration paths can keep plaintext keys

- **File and line:** `README.md:83` and `docs/readme/architecture.svg:51-53`.
- **What:** The README and drawing say model keys live in the OS keychain and SQLite keeps only masked hints. That is true for the normal saved-connection path, but not for every supported path.
- **Why:** A reader could put a key in the documented text configuration or use a machine without a keychain while believing the key cannot exist in plaintext. The exception is security-relevant even though it is not the default path.
- **Evidence:** `src/agentdesk/config.py:18-38,41-60` accepts every nonempty `AGENTDESK_` key, including the model-key environment name. `tests/test_config.py:35-37` explicitly confirms that acceptance. `src/agentdesk/keys/migrate.py:120-136` leaves a legacy secret in the settings row when no usable keychain exists. `docs/known-limitations.md:73-77` documents the same fallback. No secret value is reproduced here.
- **Fix:** Qualify the claim: saved connections use the OS keychain when available, while environment or text-file configuration and legacy no-keychain fallback can retain plaintext outside SQLite's masked-hint field. Add a warning beside the config-file instructions not to place model keys there unless that risk is accepted.
- **Confidence:** High.

### P7-05: P2: The published screenshot capture command omits the Playwright browser prerequisite

- **File and line:** `docs/readme/README.md:22-30`.
- **What:** The command installs the Playwright Python package through uv but never installs a Chromium browser binary. On a fresh machine or CI runner without a cached browser, the audit reaches `playwright.chromium.launch()` and cannot launch.
- **Why:** The document presents this as the capture command for replacing public images. A reader can install every listed Python package and still be unable to reproduce the shots.
- **Evidence:** `tools/layout_audit.py:1399` and `:3602` call `playwright.chromium.launch(headless=True)` without an executable path or channel. The documented uv line lists only `playwright`, `keyring`, and `cryptography`; installing the Python package does not install its browser binary.
- **Fix:** Add a browser installation step before the audit, for example `python -m playwright install chromium`, and name any operating-system prerequisites. Keep the command copyable as one sequence.
- **Confidence:** High.

## 5. What I checked and found correct

- All five root README badge destinations exist at `0f622e3`. The four badge SVGs are local, self-contained, and make no Shields or other third-party view-time request. Only the CI badge image is remote, served by GitHub.
- The proprietary core, draft status, separate Apache-2.0 SDK boundary, and absence of counsel review match `LICENSE`, `LICENSE-SDK`, and `docs/licensing.md`.
- No GitHub release exists, no workflow publishes a release, and the bundle builder records unsigned status. The status paragraph's installer and released-distribution claims hold.
- Every quick-start command, script, launcher, and server flag exists. The editable install declares its runtime and dev dependencies. The server command has no host override and implements `--no-browser` and the one-time session link.
- The feature list, memory controls, agent receipts, plugin lifecycle, catalog merge, validation ordering, consent widening, rollback, uninstall, typed purge confirmation, and three named plugin behaviors are supported by the code.
- The architecture drawing matches the actual Excel, calendar, mail, frontend, server, SQLite, keychain, model, research, peer, and plugin modules, except for the keychain qualification in P7-04.
- The mail implementation returns and stores named headers only, with no downstream body field. Mail defaults off. Raw workbook and mail bytes stay local, while derived context is disclosed as outbound.
- The optional sidecar exposes exactly four desk-owned action names, ignores user MCP and tool configuration in the child, and is not required for the fixed default loop.
- The README's stated absences, including SSO, RBAC, multi-user support, fleet management, MCP server, working web monitor, LAN peer connections, autostart, service, scheduled task, and tray helper, match the code and known-limitations record.
- All documentation links and the three IT-review routes exist at the pinned commit.
- All screenshot routes exist in the code. The old screenshot wordmark is expected rename input, not a defect. The architecture image uses the approved name.
- No person name, email address, mail excerpt, real workbook or sheet name, username path, token URL, internal hostname, or visible secret was found in the three PNGs or five SVGs. The one organization in the dashboard is P7-01.
- No U+2014, U+2013, or at-sign occurs in the complete new README, image notes, architecture SVG, or badge SVGs.
- The review was read-only. No test, gate, build, walkthrough, application, install, fetch into a worktree, or worktree operation was performed. The user's application data folder was never read, listed, or touched.
