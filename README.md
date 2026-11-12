# Agent Desk

A no-code personal agent for a locked-down corporate Windows laptop. One double-click opens a local web dashboard: what changed in the sales file overnight, today's key commitment broken into subtasks, a research panel, and plugins described in plain English that the agent builds, previews, and installs after one consolidated approval. No admin rights, no terminal, no data leaving the machine except derived abstractions sent to the corporate LLM endpoint.

Status: the dashboard, the excel and calendar widgets, research and the assistant, the inbox, the repetition detector, briefs, settings, the plugin runtime, the internal registry and the English-to-plugin wizard are built (#2 to #7, #11 to #15, plus #9 and #10). The consolidation (#38) shipped the teammate's four surfaces on this chassis: approvals with the decision vocabulary and the decision log (`/activity`), persistent assistant memory with deterministic recall and no auto-capture (`/memory`), a capabilities panel for the environment gates, endpoint and sources (`/capabilities`), and a metadata-only mail digest with reply drafts (`/mail`, off by default: turn it on in Settings). The v2 loop is closed end to end: `registry/plugins/sales-delta-widget` is the first published plugin (the SDK proof the research named), the host executes its declarative excel-watch data source through the built-in pipeline and renders its ui-schema card, and the plugins page browses the registry and installs pinned releases in one click (`/plugins`). CI runs the Python test matrix on Windows and macOS, the frontend typecheck, and the license gate. 787 tests green. What came from where is recorded in `docs/merge/2026-11-12-consolidation.md`. The canonical spec lives in this repo's issue tracker (issue #1, labeled `ready-for-agent`).

## Start it

Double-click `tools/agent-desk.cmd`. It finds Python (falling back through `py`, then `uv` with the Windows trust store), starts the dashboard windowless, and opens your browser at a one-time start link that becomes your session cookie. No admin rights, no terminal. The server binds 127.0.0.1 only.

On macOS, run `chmod +x tools/*.command` once, then double-click `tools/agent-desk.command`. The server starts detached, so the Terminal window can close, and its output lands in `~/.agent-desk/agent-desk.log`. The calendar file lives under `~/Library/CloudStorage/OneDrive*/agent-desk/calendar_sync.json`; the walkthrough page shows the exact path your machine uses.

From a terminal instead: `python -m agentdesk.server` (add `--no-browser` to skip the browser open).

`tools/start.cmd` and `tools/start.command` start everything: double-click for the dashboard, or run with the `dev` argument from a terminal to bring up the development stack (the Python API plus the live-reloading UI server, node needed for dev only).

## Configure it

The app runs with zero configuration, and the two things you may ever need to set now have in-app surfaces:

- **LLM endpoint** (research and the assistant): Settings, then Endpoint. Works with any OpenAI-compatible endpoint: a company gateway, OpenAI, OpenRouter, LiteLLM, or Anthropic's OpenAI-compatible URL (`https://api.anthropic.com/v1` with a Claude model name). Save, Test connection, and Clear are right there; the API key is stored locally and never shown again, only its masked state. Saved settings apply without a restart.
- **Calendar file**: the calendar walkthrough page (`/walkthrough/calendar`, linked from Settings) shows the path the app watches and offers Pick file, Paste path, Upload the JSON by hand, and Reset to automatic discovery. The explicit choice wins over automatic discovery and survives restarts.

Text configuration still works: create a file at `%USERPROFILE%\.agent-desk\config.env` (`~/.agent-desk/config.env`):

```
# Agent Desk settings, KEY=VALUE lines, # comments
AGENTDESK_LLM_BASE=https://llm.yourcompany.example/v1
AGENTDESK_LLM_KEY=your-key
AGENTDESK_LLM_MODEL=gpt-4o-mini
AGENTDESK_CALENDAR_FILE=C:/Users/you/OneDrive/agent-desk/calendar_sync.json
AGENTDESK_DATA=D:/agent-desk-data
```

Recognized keys are the `AGENTDESK_` ones: `AGENTDESK_LLM_BASE`, `AGENTDESK_LLM_KEY` and `AGENTDESK_LLM_MODEL` for research and the assistant, `AGENTDESK_CALENDAR_FILE` for the calendar sync file, `AGENTDESK_DATA` for the data folder, `AGENTDESK_REGISTRY` for the plugin registry checkout. Precedence: settings saved in the app win over real environment variables, which win over the file, and a missing file is not an error: the app simply runs unconfigured, and the settings page says so.

## Plugins and the registry

The plugins page (`/plugins`, from the rail) is where plugins live: installed ones with their lifecycle actions (enable, disable, roll back, re-test, uninstall, the named data purge), and the registry's offerings with one-click installs. The registry is this repository's own `registry/` directory (or any local git checkout of it): a root `index.json` listing plugins with releases pinned by tree sha256 and git tag, published by a PR that CI checks with the same validator the app runs (`tools/registry_ci.py` locally). Installs are pinned: the tag is extracted, the hash is recomputed and compared, and the shared validator runs before anything is installed, in pilot mode with the badge. A plugin's widget declares its data source (`excel-watch` over a scoped glob today) and a ui-schema render; the host executes the pipeline and binds real numbers into the card, amber whenever the truth is unavailable. Which checkout the app browses resolves in this order: the path saved in Settings, `AGENTDESK_REGISTRY`, this app's own checkout; the settings page shows which one answered. `python tools/smoke_first_plugin.py` runs the whole loop end to end against this checkout.

## The dashboard UI

The dashboard is a React single-page app (source in `frontend/`, data from `GET /api/dashboard`); its build output is committed at `src/agentdesk/server/static/spa/`, so the double-click launcher serves it with no node involved. Rebuilding it needs node once: `npm ci`, then `npm run build` in `frontend/`, then commit the output. Every other page (inbox, assistant, settings, activity, memory, mail, capabilities, the calendar walkthrough, what-this-touches, the audit surfaces, the wizard) is server-rendered, and the dashboard itself falls back to that server rendering when the build output is not present in a checkout.

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
