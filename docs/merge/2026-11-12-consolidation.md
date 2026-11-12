# Consolidation merge record, 2026-11-12

## Context

This repo and the teammate's repo started from the same product brief and grew into two disjoint
implementations of a personal agent dashboard: this chassis (kanitmann01/agent-desk) and the
teammate's host app (dhyeyvipulbhaid/Personal-Agents). They share zero git history: no common
commit, no shared code, only the same spec. The consolidation ports what the teammate's app proved
out, onto this chassis, keeping this chassis's rules where the two disagree. The teammate's remote
(`teammate`) stays on the branch so every donor path below is checkable against the exact tree it
came from.

The six port-and-fix commits below are the consolidation's working history; the seventh and last
(this record: the rail links, the rebuilt bundle, the README status and this document) completes
the set. Each table row names its donor module and page, what was ported, and what was
deliberately diverged. One commit is a chassis fix, not a port.

## Provenance

| Commit | Donor (teammate repo) | Ported | Deliberate divergences |
| --- | --- | --- | --- |
| 2870292 | `.github/workflows/ci.yml` (checks job) | push/pull_request triggers, `contents:read`, fail-fast:false, windows-latest and macos-latest matrix; a stdlib TOML fallback so the license gate runs on the Python 3.10 floor | The packaging and e2e jobs are not ported (the Tauri shell is deferred); no shell step; the TOML fallback instead of a tomllib-only gate |
| d569373 | none (chassis fix) | see below | not a port |
| b6d1d82 | `packages/host/src/approvals/approvals.ts` + their approvals/activity pages | card drafts with edit, snooze with auto-return on evaluation (their tick), more-info with instruction, the decision vocabulary (approved, denied, edited, snoozed, more-info, pending), task-scoped consent allows keyed (plugin, scope) like their taskAllows, the activity page rendering the audit log newest first | Request-driven handlers instead of promise queues; SQLite card columns instead of in-memory items; audit rows through the append-only audit store, which also gained the previously missing plugin lifecycle actions; task-scoped consents stay process-lifetime in-memory (widened scopes always re-ask); snooze "tomorrow" means the next local 08:00 |
| 8ed9115 | `packages/host/src/memory/memory.ts` + their memory page | facts with source metadata, token-overlap recall ranking, the list/add/edit/delete/recall-preview page | Facts persist in SQLite (theirs loses everything on restart); no auto-capture of any kind: their "sentence containing is" heuristic is a poisoning vector, so facts are explicit adds and accepted inbox cards only; overlap-fraction scoring only, their cosine term dropped; the assistant prepends at most 5 facts / 500 characters, as derived abstractions only |
| 8b0f1ed | `packages/host/src/capabilities/probe.ts` + their capabilities page | status cards with plain causes for the five P0 environment gates (reusing the probe adapters with injectable runners), endpoint status from the health connection table, per-source health from the live-source records | Cache-then-retest instead of probe-on-render: results are shown with their age and the page never probes on view, re-test is a button; no model listing in v1 (the chat adapter is chat-only); their Ollama checks are not adopted, the chassis is bring-your-own OpenAI-compatible endpoint |
| dcb6563 | `packages/host/src/mail/mail.ts` + their mail page + 30 .eml fixtures | header-only message parsing (From, To, Cc, Subject, Date, Message-ID, In-Reply-To), threading by In-Reply-To, follow-ups for threads with no user action, a 24-hour digest, handled-thread persistence, a folder watcher on the calendar bridge's timer pattern, reply drafts as editable inbox cards whose acceptance writes a threaded .eml to the local outbox | Metadata-only by construction: the donor reads bodies into LLM prompts, which breaks this product's data-egress rule, so message bodies are discarded at parse time and no LLM call exists anywhere in the mail path (draft bodies come from the user); mail is a settings toggle defaulting to off; the fixtures live under tests only; a decide-once guard protects card acceptance for every kind; reply headers are guarded against line-break injection; one malformed .eml is skipped and counted instead of killing a poll |

### The chassis fix row

d569373 is not a port. The teammate's app did not have these bugs; this chassis did, and the
consolidation's server-rendered pages would have tripped them: the shared body parser now accepts
`application/x-www-form-urlencoded` (the wizard's HTML forms reach the JSON handlers), the server
constructs a default plugin runtime under the data dir (plugin endpoints and wizard approval no
longer 503), and oversized bodies are read and discarded up to a hard cap so keep-alive connections
survive them.

## Binding constraints honored

- Bring-your-own endpoint: any OpenAI-compatible base URL; the teammate's Ollama-specific checks
  were not adopted.
- No message bodies reach the LLM: the mail path is header-only by record shape and makes no
  model call at all.
- Permissive licenses only: the whole consolidation is stdlib Python plus server-rendered HTML;
  zero new runtime dependencies, and the license manifest is unchanged.
- The interruption budget: mail digests and snooze returns land as inbox cards under the same
  quiet-hours and daily-cap rules as everything else.
- Class D plugins only: nothing in the ports emits executable code.
- Localhost only: the server still binds 127.0.0.1, authenticates every request, and validates
  Origin/Host.
- Hermetic tests: the suite touches no network, no real mailbox, no real calendar.

## Out of scope, deferred

The Tauri desktop shell, the design reconciliation between the two UIs (the teammate's pages were
re-rendered in this chassis's server-rendered style, not merged visually with the SPA's),
the browser agent, the policy broker, the plugin management page (Plugins stays the disabled rail
entry), and streaming chat.

## Known follow-ups

Recorded in the mail commit (dcb6563), agreed acceptable for this app: the timer-toggle race
(start_polling replaces the stop Event, and the toggle-on immediate poll can fire just after a
toggle-off) and the check-then-act window in card deciding (two concurrent decisions on one
waiting card can both pass the waiting check). Neither is user-visible today: the mail timer runs
at a half-hour cadence under one toggle, and card decisions come from one user's clicks.

## Collaboration note

The teammate pulls from `kanitmann01/agent-desk`; the `teammate` remote
(`dhyeyvipulbhaid/Personal-Agents`) stays configured on the branch so the donor paths in the
table above remain directly checkable against the tree they came from.
