# Nexuus Bot

A no-code personal agent for a locked-down corporate Windows laptop. One double-click opens a local web dashboard: what changed in the sales file overnight, today's key commitment broken into subtasks, a research panel, and plugins described in plain English that the agent builds, previews, and installs after one consolidated approval. No admin rights, no terminal, no data leaving the machine except derived abstractions sent to the corporate LLM endpoint.

Status: the marketplace is the shipped plugins product, and the in-box catalog is three plugins: `excel-report` (the Workbook tracker card), `competitor-watch` (the Page watch card), and `presentation-starter` (a neutral presentation template, not a dashboard card). The other 23 plugins the desk used to carry are retired; their trees live in `archive/plugins/` as a reference copy only, not as an import queue, and `registry/packs.json` no longer ships any pack. The marketplace single-page app lives at `/marketplace` with Discover, Search, Category, plugin Detail, Pack, Installed, Publishers, Studio, Admin and Trust Center; the old `/plugins` page now answers a 302 redirect to `/marketplace/installed`. This branch delivered tickets T1 to T15: the catalog, installs with a catalog pin and the shared validator, consent and scope widening, rollback, pending-review publishing, packs, publisher proof, quarantine and yank, the Trust Center, signed enterprise policy, audit export, and the closeout docs. The marketplace walkthrough is `python scripts/marketplace_walkthrough.py` (15 numbered steps, no server, exits non-zero on failure); the older desk demo is `python tools/demo_walkthrough.py`; the deterministic local gate is `python tools/ci_local.py`. Memory is now a knowledge graph that encrypts at rest (#89 to #94, spec #88): schema v2 with sources, entities and observations; deterministic hybrid recall (keyword and entity-graph legs fused by reciprocal rank fusion, recency, time-window queries); retain and reflect through approval cards (no auto-capture); and one action on the memory page converts the bank to field-level AES-256-GCM with blind indexes under a locally generated key file (`memory.key` in the app data folder), which brought the app its first third-party Python runtime dependency, `cryptography` (dual Apache-2.0 OR BSD-3-Clause, recorded in `THIRD-PARTY-NOTICES.md` and admitted by the local CI gate; every other runtime module stays standard library). The memory loop now follows what the desk does (#132): capture runs on the channels you leave on (assistant, research, workbook, and now agents), every candidate becomes a review card by default and automatic mode stores at once, a newer fact replaces an older one on the same subject while recall skips the superseded value, each entity named by two or more standing facts gets one consolidated observation that cites them, and the memory page carries the graph view, the sweep and the encryption action. The dashboard cards read the same bank through one coupled-intelligence seam (specs 009 and 010): a family attaches a reading to its card that states what it used, a pressed card answers on a page of its own with the disclosure above the answer, and a family that fails leaves the card exactly as it was. The newest surface is Agents (spec 012, done 2026-11-18): `/agents` lists the roster (Worksheet brief) with a run form and history; one runner owns the memory integration for every kind, recalling the same bounded facts block the assistant uses (at most five facts, five hundred characters, whole facts), printing on each run a receipt of exactly which facts shaped the artifact, recording a named degraded state when the endpoint is off or failing, and turning the run's feedback ("how did it land?") into a review card whose accepted fact the next run recalls; saved skills recall through the same block, and `tools/mock_endpoint.py` is the local OpenAI-compatible double (loopback only) the browser walkthrough ran against, with its evidence under `docs/evidence/2026-11-18-agents-memory/` and the merge records under `docs/merge/`. The local gate is green 6/6 on the current tree: 2524 pytest, tsc clean, 305 vitest, the license gate, and registry CI over both shipped plugins, and the release digests verify identically on every platform now (the tree walk was platform-dependent before, which failed pinned installs on Windows for mixed-case plugin trees).

## Start it

Double-click `tools/agent-desk.cmd`. It finds Python (falling back through `py`, then `uv` with the Windows trust store), starts the dashboard windowless, and opens your browser at a one-time start link that becomes your session cookie. No admin rights, no terminal. The server binds 127.0.0.1 only.

On macOS, run `chmod +x tools/*.command` once, then double-click `tools/agent-desk.command`. The server starts detached, so the Terminal window can close, and its output lands in `~/.agent-desk/agent-desk.log`. The calendar file lives under `~/Library/CloudStorage/OneDrive*/agent-desk/calendar_sync.json`; the walkthrough page shows the exact path your machine uses.

From a terminal instead: `python -m agentdesk.server` (add `--no-browser` to skip the browser open).

`tools/start.cmd` and `tools/start.command` start everything: double-click for the dashboard, or run with the `dev` argument from a terminal to bring up the development stack (the Python API plus the live-reloading UI server, node needed for dev only).

## Configure it

The app runs with zero configuration, and the two things you may ever need to set now have in-app surfaces:

- **LLM endpoint** (research and the assistant): Settings, then Endpoint. Works with any OpenAI-compatible endpoint: a company gateway, OpenAI, OpenRouter, LiteLLM, Azure AI Foundry, or Anthropic's OpenAI-compatible URL (`https://api.anthropic.com/v1` with a Claude model name). Save, Test connection, and Clear are right there; the API key is stored locally and never shown again, only its masked state. Saved settings apply without a restart.
- **Calendar file**: the calendar walkthrough page (`/walkthrough/calendar`, linked from Settings) shows the path the app watches and offers Pick file, Paste path, Upload the JSON by hand, and Reset to automatic discovery. The explicit choice wins over automatic discovery and survives restarts.

Text configuration still works: create a file at `%USERPROFILE%\.agent-desk\config.env` (`~/.agent-desk/config.env`):

```
# Nexuus Bot settings, KEY=VALUE lines, # comments
# Foundry example: AGENTDESK_LLM_BASE=https://<resource>.openai.azure.com/openai/v1
AGENTDESK_LLM_BASE=https://llm.yourcompany.example/v1
AGENTDESK_LLM_KEY=your-key
AGENTDESK_LLM_MODEL=gpt-4o-mini
AGENTDESK_CALENDAR_FILE=C:/Users/you/OneDrive/agent-desk/calendar_sync.json
AGENTDESK_DATA=D:/agent-desk-data
```

Recognized keys are the `AGENTDESK_` ones: `AGENTDESK_LLM_BASE`, `AGENTDESK_LLM_KEY` and `AGENTDESK_LLM_MODEL` for research and the assistant, `AGENTDESK_CALENDAR_FILE` for the calendar sync file, `AGENTDESK_DATA` for the data folder, `AGENTDESK_REGISTRY` for the plugin registry checkout. Precedence: settings saved in the app win over real environment variables, which win over the file, and a missing file is not an error: the app simply runs unconfigured, and the settings page says so.

## Marketplace

The marketplace is the plugins surface (`/marketplace`, from the rail). Discover lists the catalog with filters for source and risk and an only-available switch; Search and Category narrow it; each plugin has a Detail page; Pack pages show the no-pack empty state because no pack ships today; Installed is the local inventory; Publishers shows who published what and the proof on file; Studio is the create-to-publish path; Admin and Trust Center are the administrator surfaces. The old `/plugins` page answers a 302 redirect to `/marketplace/installed`.

The catalog is assembled at request time from the registry checkout this app resolves (its own `registry/`, a path saved in Settings, or `AGENTDESK_REGISTRY`), plus the organisation catalog written when a submission is approved, plus catalogs shared by paired desks. Every registry release records a tree digest. Eligibility is the policy decision: the release's recorded signature status, risk tier, publisher, category, kill switch and network allowlist. An install compares the staged tree digest to the catalog pin before anything is written (a missing pin or a mismatch is `409 install:digest-mismatch`), then runs the shared validator on the staged files and records the digest. The same check runs for every member of a pack and for every update. Publisher signatures are checked as a catalog status by policy; cryptographic signature verification needs a configured trust store, which the repository registry does not ship.

Installing opens one consent sheet that lists every scope the plugin asks for and what it can never do; nothing installs until you accept. Updates go through the same sheet when they add a scope (the new scopes are marked); an update that only narrows scopes applies without a second approval. A pending update can be declined. Roll back returns to the release you had before the update, Uninstall removes the plugin and keeps its data folder, and Purge data deletes that folder only after the typed `delete-data:<id>` confirmation. All of it lands in the local audit log.

Publishing starts in Studio: pick a blank template or copy the descriptive fields of an installed plugin, fill the manifest, run the validator, add a changelog and tick the license grant. Publish queues the submission as pending review; publishing never installs the plugin. An administrator approves or rejects it on the Admin page, and approval writes the release into the organisation catalog with the local-admin signature. A pack is a curated set of registry plugins in `registry/packs.json` (the set is empty today) and installs all or nothing: if one member is blocked by policy, the whole pack is refused and the blocked member is named.

The Trust Center states what the marketplace guarantees and what it cannot do, shows the pinned policy anchor and the last validator run, and shows the report path. Admin mode is off unless the server starts with `AGENTDESK_MARKETPLACE_ADMIN=1`; while it is off the admin endpoints answer 403 and nothing is served, including the audit export. With it on, Admin shows the posture and inventory, approves submissions, imports a signed policy bundle, and runs the kill switch. A policy bundle is canonical JSON signed with Ed25519 over every policy field, with issue and expiry times and a revocation epoch; the first import pins the signing key's fingerprint in the anchor, and the anchor never lowers the revocation epoch or drops a fingerprint. A policy file that no longer verifies (tampered, expired, or carrying an epoch below the pinned one) is not loaded, and the built-in curated policy stays active with an amber warning. Importing a bundle trusts the Ed25519 key the local admin presents at that moment, so the admin surface itself is the trust boundary. The kill switch is separate state, so it survives a policy import. Audit export is NDJSON at `/api/marketplace/audit/export`, one event per line with at, action, pluginId, actor and outcome.

## Licensing

The app's core is proprietary: `LICENSE` is a draft and still pending counsel review. The plugin SDK is Apache-2.0 under `LICENSE-SDK` (the manifest schema v2, the authoring guide, and files marked Apache-2.0 or under `sdk/`). In-box plugins declare MIT in their manifests; third-party components keep their own licenses, listed in `THIRD-PARTY-NOTICES.md` with the full texts under `licenses/`. The SBOM is CycloneDX 1.6 from `python scripts/sbom.py` (default `build/sbom.cdx.json`; a packaged build carries a copy), and `python scripts/license_gate.py build/sbom.cdx.json --report build/license-report.txt` fails on anything outside MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause and ISC, with a short named-exception list for fonts and the CPython runtime. `docs/licensing.md` has the full boundary and the open counsel questions.

## Peer sharing

The peers page (`/peers`, from the rail) shares plugins between desks with nothing centralized (#67). One desk generates a short single-use pairing code; the other enters it with that desk's address, and both pin each other's identity plus a channel token (verification compares only the token's hash; the token itself is kept so pairing works in both directions, like any API client credential). Desks find each other by UDP broadcast on the local network; nothing is announced until the peers page is opened, and the server still listens on loopback only, so pairing and sharing work between desks on one machine, while a desk elsewhere on the LAN can be discovered but not connected to (and says so, with the cause). A paired desk can read only the plugins you explicitly share: their manifest and bundle, over a token-gated read-only `/peer/` endpoint that passes the same Origin/Host guard. Installs from a peer download the bundle, recheck the publisher's tree digest, and run the same shared validator a registry install runs; the lockfile records the peer as the source. When the publisher's version bumps, the peers page shows update-available (only when the version or digest truly differs) and one click updates through the same consent path as every update.

## The dashboard UI

The dashboard is a React single-page app (source in `frontend/`, data from `GET /api/dashboard`); its build output is committed at `src/agentdesk/server/static/spa/`, so the double-click launcher serves it with no node involved. The marketplace is a second app in the same build (source in `frontend/src/marketplace/`); when that build output is missing, `/marketplace` answers 404 with "The marketplace interface is not built in this checkout." Rebuilding either needs node once: `npm ci`, then `npm run build` in `frontend/`, then commit the output. Every other page (inbox, assistant, agents, settings, activity, memory, mail, capabilities, peers, the calendar walkthrough, what-this-touches, the audit surfaces, the wizard) is server-rendered, and the dashboard itself falls back to that server rendering when the build output is not present in a checkout.

## Where things are

- `docs/research.md`: the full architecture research (v2, post-audit hardened). Licenses, plugin architecture, enterprise Windows mechanics, landscape. The binding decisions are in its section A9.
- `docs/PRD.md`: product requirements: personas, surfaces, the action inventory with reversibility, reachable-state matrix, phasing.
- `docs/design-language.md`: the visual contract (tokens, type, spacing, anti-slop commitments) every build consumes.
- `docs/design/dashboard.html`: the high-fidelity mockup; open it in any browser.
- `docs/design/plugin-authoring-v2.md`: the manifest v2 contract for an in-box plugin: files, schema, the ten element slots, bindings and data sources.
- `docs/licensing.md`: the licence boundary between the proprietary core, the Apache-2.0 plugin SDK and third-party components, plus the gate's rules.
- `docs/ops/marketplace-operator.md`: the IT operator guide for installs, publishing, policy import, audit export and the kill switch.
- `docs/ops/distribution.md`: the Nuitka build, the AppLocker publisher rule and the update channel.
- `docs/known-limitations.md`: the honest gaps in the current build.
- `docs/merge/` and `docs/evidence/`: one merge record per landed spec wave, and the dated evidence packs (screenshots, gate transcripts) behind the walkthrough claims.
- `specs/`: snapshot of the spec body as published to the tracker. The issue is canonical; this file is convenience.
- `src/agentdesk/probe/`: the P0 environment probe, run via `tools/probe.cmd`.
- `src/agentdesk/validator/`: the plugin validator, byte-identical to registry CI.
- `src/agentdesk/server/`: the hardened localhost web app: token bootstrap, Origin/Host guard, dashboard shell, health, and the marketplace shell at `/marketplace`.
- `src/agentdesk/excel/`: the excel-watch: shadow copy before parse, stdlib xlsx reader, SQLite row-hash snapshots, 24-hour delta, amber locked-file state.
- `src/agentdesk/calendar/`: the calendar bridge: reads the OneDrive-synced calendar JSON, picks today's key commitment, breakdowns over the corporate endpoint with a generic fallback, checks and breakdown cache in SQLite, the in-app walkthrough.
- `src/agentdesk/assistant/`: research and the assistant: one thin loop over the corporate endpoint, widget context attached so she never re-explains, and the audit store recording every outbound call.
- `src/agentdesk/agents/`: the agents layer: a registry where a task kind is one data entry (id, name, blurb, instructions, artifact kind, live context), a SQLite runs store with the harness's inert hermetic default, and one runner that owns recall, the endpoint call, honest degradation and the receipt, while the run and feedback handlers write the `agents.run` / `agents.feedback` audit rows for every kind; run feedback is offered to the memory loop's `agents` capture channel.
- `src/agentdesk/insight/`: coupled intelligence: one seam attaches readings to the dashboard cards, every reading carries the disclosure of what it used, a pressed card answers on a page of its own with the disclosure first, and a family that fails leaves its card untouched.
- `src/agentdesk/inbox/`: the inbox and interruption budget: suggestion cards with origin lines, quiet hours 18:00-08:00, a cap of three notifications a day, digest batching, and 30-day dismiss recovery.
- `src/agentdesk/repetition/`: the repetition detector and skills: app-mediated activity log, deterministic clustering, one proposal per pattern at the fifth similar ask, dismiss cooldowns, and versioned SKILL.md skills with honest undo.
- `src/agentdesk/briefs.py`: pre-meeting briefs: calendar-only, assembled from commitments and research history about the attendees, only when there is something to say, always inside the interruption budget.
- `src/agentdesk/settings.py`: settings: toggles plus the typed endpoint rows, defaults that need no documentation; the values the page shows are the values the inbox and the sources enforce.
- `src/agentdesk/wizard/`: the English-to-plugin wizard: at most five multiple-choice questions, a Class D compiler with capped self-repair, a dry-run preview, one consolidated approval that installs in pilot mode, and an honest feature-request dead-end.
- `src/agentdesk/plugins/`: the plugin runtime: lifecycle, pilot, scope-diff updates and rollback; `sources.py` executes the declarative data sources, `render.py` binds their output into the ui-schema card.
- `src/agentdesk/marketplace/`: the marketplace: `catalog.py` merges the bundled, organisation and peer catalogs, `policy.py` evaluates eligibility, `signed_policy.py` verifies the Ed25519 policy bundle and owns the anchor, kill switch and local audit, and `api.py` serves the `/api/marketplace` routes.
- `src/agentdesk/trust/`: the Ed25519 primitives and canonical JSON the policy bundle verification uses.
- `src/agentdesk/registry/`: the registry format, pinned install with hash verification and the shared validator, CI review, and the source resolution the marketplace browses.
- `src/agentdesk/peers/`: peer-to-peer plugin sharing: the sqlite peer store (identity, single-use pairing codes, shares, subscriptions), UDP announce/listen discovery that starts on the first peers page visit, the token-gated read-only `/peer/` endpoint surface, and the http client that pairs, reads and downloads from another desk, with installs verified against the publisher's digest before the shared validator runs.
- `src/agentdesk/memory/`: the knowledge-graph memory (#89 to #94, spec #88): schema v2 with sources, entities, edges and observations; deterministic hybrid recall (keyword and entity-graph legs fused by reciprocal rank fusion, recency weighting, time-window queries); retain and reflect through approval cards (no auto-capture); the capture loop (`loop.py`) following what the desk does on channels the user left on (assistant, research, workbook, agents), with newer-over-older supersession and one consolidated observation per multi-fact entity after every write; hygiene (write-time dedupe, entity merge, junk sweep); and encryption at rest: field-level AES-256-GCM envelopes bound to table, column and row, HMAC-SHA256 blind indexes for dedupe and entity lookup, a key-check marker in `schema_meta`, and the key in `memory.key` under the app data folder. The crypto rides on the `cryptography` package, the app's only third-party runtime dependency (Apache-2.0 OR BSD-3-Clause).
- `registry/`: the registry itself: `index.json`, `packs.json` (an empty list), and the three `plugins/<id>` directories that ship (`excel-report`, `competitor-watch`, `presentation-starter`). The 23 retired plugin trees are under `archive/plugins/`, kept as a reference copy. `python scripts/sync_registry.py` keeps the index in step with the folders; `python scripts/build_catalog.py` writes the build catalog.
- `frontend/src/marketplace/`: the marketplace app: router, catalog, plugin detail, pack, installed, publishers, Studio, Admin, Trust Center, consent sheet and client.
- `scripts/`: the build and licence tooling: `sync_registry.py`, `build_catalog.py`, `build_bundle.py` (Nuitka build, verify and smoke), `sbom.py`, `license_gate.py`, `third_party_notices.py`.
- `src/agentdesk/llm.py`: the shared OpenAI-compatible endpoint adapter (env-configured, one attempt, no telemetry).
- `tools/agent-desk.cmd`: the double-click launcher.
- `tools/mock_endpoint.py`: a local OpenAI-compatible endpoint double for demos and the walkthrough; it binds loopback only, the same rule as the desk itself.

## For IT review

- `/what-this-touches` in the running app: the one-page statement, generated from the audit event vocabulary.
- `/audit/export.csv`: the append-only app audit log as CSV (actor, action, target, timestamp).
- `/marketplace/trust`: the marketplace Trust Center: the policy anchor, the signature state, the last validator run, and the guarantees and non-guarantees.
- `/api/marketplace/audit/export`: the marketplace audit log as NDJSON, admin mode only.
- `docs/ops/marketplace-operator.md`: the operator runbook for everything above.
- `docs/ops/distribution.md`: the build, the AppLocker rule template and the file-share update channel.

## Distribution

The distribution target is a signed Nuitka one-folder build: `AgentDesk.exe` plus its dependencies, a `manifest.json` with a SHA-256 for every file, the SBOM and the license files. Nuitka is not installed in this environment, so no artifact, signature or working publisher rule is claimed here: `python scripts/build_bundle.py build` prints `SKIP: Nuitka is not installed` and exits 3. The AppLocker publisher rule stays a template until a code-signing certificate exists; `docs/ops/distribution.md` has the rule, the update channel and the versioned-folder rollback.

## Ground rules for anything built here

- Permissive licenses only for third-party code: MIT, Apache-2.0, BSD, ISC. No copyleft, no SSPL/BSL/fair-code, no restricted licenses. The core itself is proprietary (`LICENSE`) and the plugin SDK is Apache-2.0 (`LICENSE-SDK`); upstream LICENSE/NOTICE files ship inside the install folder.
- Class D plugins only: manifests and declarative UI schemas. The compiler never emits executable code.
- The local server binds 127.0.0.1 only, authenticates every request, and validates Origin/Host.
- No autostart persistence until Security signs off in writing.
- The UI is the log: every widget shows freshness, and failure is a designed, visible state.
