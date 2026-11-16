# Agent Desk

A no-code personal agent for a locked-down corporate Windows laptop. One double-click opens a local web dashboard: what changed in the sales file overnight, today's key commitment broken into subtasks, a research panel, and plugins described in plain English that the agent builds, previews, and installs after one consolidated approval. No admin rights, no terminal, no data leaving the machine except derived abstractions sent to the corporate LLM endpoint.

Status: the dashboard, the excel and calendar widgets, research and the assistant, the inbox, the repetition detector, briefs, settings, the plugin runtime, the internal registry and the English-to-plugin wizard are built (#2 to #7, #11 to #15, plus #9 and #10). The consolidation (#38) shipped the teammate's four surfaces on this chassis: approvals with the decision vocabulary and the decision log (`/activity`), persistent assistant memory with deterministic recall and no auto-capture (`/memory`), a capabilities panel for the environment gates, endpoint and sources (`/capabilities`), and a metadata-only mail digest with reply drafts (`/mail`, off by default: turn it on in Settings). The v2 loop is closed end to end: `registry/plugins/sales-delta-widget` is the first published plugin (the SDK proof the research named), the host executes its declarative excel-watch data source through the built-in pipeline and renders its ui-schema card, and the plugins page browses the registry and installs pinned releases in one click (`/plugins`); four more shipped plugins joined it (calendar-today, excel-report, outlook-digest, research-brief). The create-to-publish loop is closed (#63): a locally installed plugin publishes to the resolved registry as a digest-pinned local release from the plugins page or the wizard's approved screen. The demo-completeness set closed the rest: labelled sample data behind a settings switch (#68), peer-to-peer plugin sharing with pairing codes and one-click updates (`/peers`, #67), a personal dashboard layout with reorder, rename, hide and restore (#66), strict endpoint saves with honest Test-connection causes, and the extra-hosts guard setting (#61). The whole story is one scripted walkthrough, `python tools/demo_walkthrough.py`, that boots two real desks and passes 21 steps or exits non-zero; `DEMO.md` is the presenter's script for the same path. CI is the deterministic local gate: `python tools/ci_local.py` runs the 3.10 grammar check, the full pytest suite over a fresh pinned data dir, the frontend typecheck and vitest suite, the license manifest gate and the registry CI over every committed plugin, then exits non-zero on any failure (zero GitHub minutes; the hosted matrix was dropped when Actions billing broke on 2026-11-13). 1078 backend tests plus 138 frontend tests green. Memory now encrypts at rest (#94): one action on the memory page converts the bank to field-level AES-256-GCM with blind indexes under a locally generated key file (`memory.key` in the app data folder), and that conversion brought the app its first third-party Python runtime dependency, `cryptography` (dual Apache-2.0 OR BSD-3-Clause, recorded in `THIRD-PARTY-LICENSES.md` and admitted by the local CI gate; every other runtime module stays standard library). What came from where is recorded in `docs/merge/2026-11-12-consolidation.md`. The canonical spec lives in this repo's issue tracker (issue #1, labeled `ready-for-agent`).

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
# Agent Desk settings, KEY=VALUE lines, # comments
# Foundry example: AGENTDESK_LLM_BASE=https://<resource>.openai.azure.com/openai/v1
AGENTDESK_LLM_BASE=https://llm.yourcompany.example/v1
AGENTDESK_LLM_KEY=your-key
AGENTDESK_LLM_MODEL=gpt-4o-mini
AGENTDESK_CALENDAR_FILE=C:/Users/you/OneDrive/agent-desk/calendar_sync.json
AGENTDESK_DATA=D:/agent-desk-data
```

Recognized keys are the `AGENTDESK_` ones: `AGENTDESK_LLM_BASE`, `AGENTDESK_LLM_KEY` and `AGENTDESK_LLM_MODEL` for research and the assistant, `AGENTDESK_CALENDAR_FILE` for the calendar sync file, `AGENTDESK_DATA` for the data folder, `AGENTDESK_REGISTRY` for the plugin registry checkout. Precedence: settings saved in the app win over real environment variables, which win over the file, and a missing file is not an error: the app simply runs unconfigured, and the settings page says so.

## Plugins and the registry

The plugins page (`/plugins`, from the rail) is where plugins live: installed ones with their lifecycle actions (enable, disable, roll back, re-test, publish, uninstall, the named data purge), the Share toggle for peer sharing, and the registry's offerings with one-click installs. The registry is this repository's own `registry/` directory (or any local git checkout of it): a root `index.json` listing plugins with releases pinned by tree sha256, published by a PR that CI checks with the same validator the app runs (`tools/registry_ci.py` locally) or published straight from the app: the Publish button on the plugins page and on the wizard's approved screen copies the installed plugin into the registry's `plugins/<id>/<version>/` folder and appends a `source: "local"` release to the index, digest-pinned with no git tag; installs of a local release verify that digest against that versioned directory itself, earlier local releases keep resolving after a new publish, and the same CI checks run green over the mutated index. Installs are pinned: the content is fetched (git archive at the tag, or the plugins directory for a local release), the hash is recomputed and compared, and the shared validator runs before anything is installed, in pilot mode with the badge. A plugin's widget declares its data source (`excel-watch` over a scoped glob today) and a ui-schema render; the host executes the pipeline and binds real numbers into the card, amber whenever the truth is unavailable; when the workbook lands after the amber install, Re-test attaches the pipeline and binds the values. Which checkout the app browses resolves in this order: the path saved in Settings, `AGENTDESK_REGISTRY`, this app's own checkout; the settings page shows which one answered. `python tools/smoke_first_plugin.py` runs the whole loop end to end against this checkout.

## Peer sharing

The peers page (`/peers`, from the rail) shares plugins between desks with nothing centralized (#67). One desk generates a short single-use pairing code; the other enters it with that desk's address, and both pin each other's identity plus a channel token (verification compares only the token's hash; the token itself is kept so pairing works in both directions, like any API client credential). Desks find each other by UDP broadcast on the local network; nothing is announced until the peers page is opened, and the server still listens on loopback only, so pairing and sharing work between desks on one machine, while a desk elsewhere on the LAN can be discovered but not connected to (and says so, with the cause). A paired desk can read only the plugins you explicitly share: their manifest and bundle, over a token-gated read-only `/peer/` endpoint that passes the same Origin/Host guard. Installs from a peer download the bundle, recheck the publisher's tree digest, and run the same shared validator a registry install runs; the lockfile records the peer as the source. When the publisher's version bumps, the peers page shows update-available (only when the version or digest truly differs) and one click updates through the same consent path as every update.
## The dashboard UI

The dashboard is a React single-page app (source in `frontend/`, data from `GET /api/dashboard`); its build output is committed at `src/agentdesk/server/static/spa/`, so the double-click launcher serves it with no node involved. Rebuilding it needs node once: `npm ci`, then `npm run build` in `frontend/`, then commit the output. Every other page (inbox, assistant, settings, activity, memory, mail, capabilities, plugins, peers, the calendar walkthrough, what-this-touches, the audit surfaces, the wizard) is server-rendered, and the dashboard itself falls back to that server rendering when the build output is not present in a checkout.

## Where things are

- `docs/research.md`: the full architecture research (v2, post-audit hardened). Licenses, plugin architecture, enterprise Windows mechanics, landscape. The binding decisions are in its section A9.
- `docs/PRD.md`: product requirements: personas, surfaces, the action inventory with reversibility, reachable-state matrix, phasing.
- `docs/design-language.md`: the visual contract (tokens, type, spacing, anti-slop commitments) every build consumes.
- `docs/design/dashboard.html`: the high-fidelity mockup; open it in any browser.
- `specs/`: snapshot of the spec body as published to the tracker. The issue is canonical; this file is convenience.
- `src/agentdesk/probe/`: the P0 environment probe (issue #2), run via `tools/probe.cmd`.
- `src/agentdesk/validator/`: the plugin validator CLI (issue #8), byte-identical to registry CI.
- `src/agentdesk/server/`: the hardened localhost web app (issue #3): token bootstrap, Origin/Host guard, dashboard shell, health.
- `src/agentdesk/excel/`: the excel-watch (issue #4): shadow copy before parse, stdlib xlsx reader, SQLite row-hash snapshots, 24-hour delta, amber locked-file state.
- `src/agentdesk/calendar/`: the calendar bridge (issue #5): reads the OneDrive-synced calendar JSON, picks today's key commitment, breakdowns over the corporate endpoint with a generic fallback, checks and breakdown cache in SQLite, the in-app walkthrough.
- `src/agentdesk/assistant/`: research and the assistant (issue #6): one thin loop over the corporate endpoint, widget context attached so she never re-explains, and the audit store recording every outbound call.
- `src/agentdesk/inbox/`: the inbox and interruption budget (issue #12): suggestion cards with origin lines, quiet hours 18:00-08:00, a cap of three notifications a day, digest batching, and 30-day dismiss recovery.
- `src/agentdesk/repetition/`: the repetition detector and skills (issue #13): app-mediated activity log, deterministic clustering, one proposal per pattern at the fifth similar ask, dismiss cooldowns, and versioned SKILL.md skills with honest undo.
- `src/agentdesk/briefs.py`: pre-meeting briefs (issue #14): calendar-only, assembled from commitments and research history about the attendees, only when there is something to say, always inside the interruption budget.
- `src/agentdesk/settings.py`: settings (issue #15): toggles plus the typed endpoint rows, defaults that need no documentation; the values the page shows are the values the inbox and the sources enforce.
- `src/agentdesk/wizard/`: the English-to-plugin wizard (issue #11): at most five multiple-choice questions, a Class D compiler with capped self-repair, a dry-run preview, one consolidated approval that installs in pilot mode, and an honest feature-request dead-end.
- `src/agentdesk/plugins/`: the plugin runtime (issue #9) plus the widget runner: lifecycle, pilot, scope-diff updates, rollback, and host-side execution of declarative data sources (the excel pipeline per plugin, over the plugin's own data dir) bound into the ui-schema card.
- `src/agentdesk/registry/`: the internal registry (issue #10): the index format, pinned install with hash verification and the shared validator, CI review, and the source resolution the plugins page browses.
- `src/agentdesk/peers/`: peer-to-peer plugin sharing (issue #67): the sqlite peer store (identity, single-use pairing codes, shares, subscriptions), UDP announce/listen discovery that starts on the first peers page visit, the token-gated read-only `/peer/` endpoint surface, and the http client that pairs, reads and downloads from another desk, with installs verified against the publisher's digest before the shared validator runs.
- `src/agentdesk/memory/`: the knowledge-graph memory (issues #89 to #94): schema v2 with sources, entities, edges and observations, deterministic hybrid recall, retain through approval cards, and encryption at rest (#94): field-level AES-256-GCM envelopes bound to table, column and row, HMAC-SHA256 blind indexes for dedupe and entity lookup, a key-check marker in `schema_meta`, and the key in `memory.key` under the app data folder. The crypto rides on the `cryptography` package, the app's only third-party runtime dependency (Apache-2.0 OR BSD-3-Clause).
- `registry/`: the registry itself: `index.json` plus `plugins/<id>` directories; `sales-delta-widget` 0.1.0 is the first published plugin, pinned to tag `sales-delta-widget-0.1.0`.
- `src/agentdesk/llm.py`: the shared OpenAI-compatible endpoint adapter (env-configured, one attempt, no telemetry).
- `tools/agent-desk.cmd`: the double-click launcher.
- `tools/license_manifest.py`: the license gate (issue #7): fails on any dependency outside MIT/Apache-2.0/BSD/ISC; writes `THIRD-PARTY-LICENSES.md`.

## For IT review

- `/what-this-touches` in the running app: the one-page statement, generated from the audit event vocabulary.
- `/audit/export.csv`: the append-only audit log as CSV (actor, action, target, timestamp).

## Ground rules for anything built here

- Permissive licenses only: MIT, Apache-2.0, BSD, ISC. No copyleft, no SSPL/BSL/fair-code, no restricted licenses. Upstream LICENSE/NOTICE files ship inside the install folder.
- Class D plugins only: manifests and declarative UI schemas. The compiler never emits executable code.
- The local server binds 127.0.0.1 only, authenticates every request, and validates Origin/Host.
- No autostart persistence until Security signs off in writing.
- The UI is the log: every widget shows freshness, and failure is a designed, visible state.
