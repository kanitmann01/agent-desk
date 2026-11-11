# PRD: Enterprise Personal Agent (working name TBD, "the Agent")

Status: draft v1.0 for review
Date: 2026-11-11
Owner: [the user's team]
Inputs: research/2026-11-11-enterprise-personal-agent-research.md (v2, post-audit hardened). All architecture constraints in this PRD trace to that document; this PRD owns product and interaction decisions on top of it.

---

## 1. Internal brief

| Field | Value |
|---|---|
| User | A non-technical manager ("Priya") on a locked-down corporate Windows laptop. She uses Outlook, Excel, and a browser all day. She cannot code, cannot open a terminal, and cannot get software installed by IT on request. |
| Job | "Keep on top of my numbers, my calendar, and my follow-ups without doing the same tedious clicking every morning, and have the agent flag what I'm missing before someone else does." |
| Current behavior | She opens the sales Excel daily and eyeballs changes; she scrolls Outlook before meetings; she keeps follow-ups in her head or sticky notes. It fails silently: changes get noticed late, commitments get dropped. |
| Desired outcome | She double-clicks one shortcut. A dashboard shows what changed in her sales file in the last 24h, today's most important commitment broken into subtasks, and a research panel she can feed a question. The agent proactively files suggestions she can accept or dismiss in one click. When she wants a new widget, she describes it in plain English and the agent builds, previews, and installs it after one approval. |
| Success signal | Week 4: Priya opens the Agent unprompted on 4 of 5 workdays; at least one self-built plugin exists; zero IT incidents. |
| Non-goals | No executable plugin code generated for users (Class D only, research A9.2 rule 9). No mobile app. No messaging-channel integrations in v1-v2. No reading of mail bodies (metadata + user-pasted content only until DLP sign-off). No autostart persistence until Security approves. No macOS in v1. |
| Object | Widgets, plugins, skills, suggestions, briefings, data sources. |
| Permissions | Priya: full user surface. The technical owner: install, registry admin. IT/Security: read-only posture docs and audit export. |
| Open decisions | See section 11. |

## 2. Personas

- **Priya (primary, no-code)**: the manager. Every surface must be operable by her with zero training: no file paths typed manually (file pickers), no jargon, no logs.
- **The technical owner (secondary)**: Priya's report who set the Agent up. Comfortable with scripts, owns the internal plugin registry, approves feature requests the wizard cannot build.
- **IT/Security reviewer (gatekeeper)**: never a daily user; reads the one-page "what this touches" doc, the audit export, and the license manifest. The product must make their review trivial or it dies at the gate.

## 3. Product principles

1. **No terminal, ever.** If a flow would require a command, file path typed by hand, or config edit, it is not shipped (user constraint; authority level 1).
2. **Approvals are scarce and real.** Users rubber-stamp ~97% of prompts (research A8.2); therefore the product asks rarely, each ask is consolidated, and each names object, scope, and consequence (`rule/name-object-scope-consequence`, `rule/destructive-proportional`).
3. **The agent suggests; the user decides.** Every agent-initiated action lands as a card with Accept/Dismiss, governed by an interruption budget (quiet hours, daily caps, only-when-actionable). Nothing is installed or sent without a click in v1-v2.
4. **Degrade visibly, never silently.** Every widget permanently shows its freshness; a dead watcher turns amber with a recovery action (`rule/cover-reachable-states`; non-coders cannot read logs, so the UI is the log).
5. **Smallest intervention.** A better default beats a setting; a setting beats a wizard (`rule/smallest-intervention`).

## 4. Surfaces and requirements

### S0. Install and first run

- R0.1 One double-clickable shortcut installs (if needed) and opens the Agent in the default browser at a token-authenticated localhost URL. No admin, no PowerShell visible, no reboot (research A9.2 rules 5-6).
- R0.2 First run reaches the dashboard with the three starter widgets visible in a sample/demo state before any permission or data-source ask (`rule/value-before-interruption`). Each data-source connection (Excel file, calendar bridge) is requested in context, at first use of its widget, with the benefit stated first (`rule/permission-benefit-first`).
- R0.3 Data-source setup is file-picker and button based. The Power Automate calendar bridge is set up by a guided browser task with a printable one-page walkthrough; the app detects `calendar_sync.json` arriving in OneDrive and confirms with a success state that names what now works (`rule/success-state-specific`).

### S1. Dashboard

- R1.1 A grid of widget cards (2x1, 2x2). Add, remove, and reorder widgets via visible buttons and a Move menu; no drag-only reordering, and drag remains an accelerator with the menu as the accessible path (`rule/gesture-has-control-alternative`).
- R1.2 Every widget permanently renders: title, freshness stamp ("updated 3 min ago"), status (healthy, stale-amber with Re-test, error with plain-language cause and recovery), and an overflow menu (Configure, Remove, About this plugin).
- R1.3 Widget content is rendered from the declarative ui-schema only; plugins cannot ship HTML/JS into the dashboard origin (research A9.2 rule 7).
- R1.4 The three v1 widgets: Sales delta (24h, snapshot-diffed from local SQLite), Today's commitments (top calendar item decomposed into subtasks), Research panel (paste a question or "what I did", get a sourced summary).
- R1.5 Long or extreme values (0, negative, huge numbers, long product names) are designed states, not overflow accidents (resilience, `rule/cover-reachable-states`).

### S2. Assistant (in-app chat)

- R2.1 A chat surface inside the app; Priya's familiar paradigm. It can read her widgets' data on request and run approved skills; it cannot install plugins or widen permissions from chat.
- R2.2 When the LLM endpoint is unreachable, the assistant region degrades alone ("The AI service is not responding; widgets keep working") and never takes the dashboard down with it (degraded dependency).
- R2.3 Busy state keeps the send control's label stable (`rule/loading-stable-labels`); response streaming has a specific loading indicator.

### S3. Plugin wizard ("Describe a plugin")

- R3.1 Entry: "Add a plugin" button on the dashboard. The wizard is a guided conversation, not a form: Priya types what she wants in plain English.
- R3.2 The agent asks at most 3-5 clarifying questions, each multiple-choice with sensible defaults; it never asks for file paths as text (file picker), never shows JSON, and never uses code vocabulary (`rule/no-redundant-entry`: answers carry forward; the review step shows what was understood).
- R3.3 Output is Class D only: manifest + declarative data source + ui-schema + optional SKILL.md. If the request exceeds the declarative vocabulary, the wizard ends in a designed terminal state: "I can't build this automatically yet. I've sent it as a feature request to [owner]" with the request text preserved and visible (`rule/preserve-user-input`, `rule/empty-state-action` for the dead end).
- R3.4 Dry-run before commit: the wizard renders the actual widget with sample or real data and asks "This is what you'll see every morning. Correct?" (review step, `rule/irreversible-action-safeguard`).
- R3.5 One consolidated approval closes the wizard: what it does, what it reads, what it can never do (no internet, no email, read-only), refresh cadence, and how to remove it. One primary action ("Add widget"), one escape ("Not right; go back", which preserves every answer). No nested dialogs (`rule/no-nested-modals`), no second confirmation after this one (`rule/destructive-proportional`).
- R3.6 Failure states: generation fails after 3 internal attempts (honest escalation, research A8.2 step 6); validation fails (plain language: "the file you picked has no numbers in it; pick the sales workbook"); a needed scope is unavailable (the wizard offers the closest buildable variant and names what it dropped).
- R3.7 New plugins install in pilot mode with a visible "pilot" badge for the first 5 runs.

### S4. Inbox (suggestions and approvals)

- R4.1 One inbox for everything the agent initiates: skill proposals ("You've asked for this report 5 times; make it one click?"), plugin updates needing re-consent, data-source problems, and meeting briefs. Cards, newest first, each with Accept / Dismiss and a plain-language origin line ("why I'm suggesting this").
- R4.2 Dismiss is reversible: a Dismissed view retains cards for 30 days. No confirmation on dismiss (reversible act, `rule/destructive-proportional`).
- R4.3 Accepting a skill proposal activates the skill and offers undo; skills keep version history and archive, so undo is honest (`rule/undo-only-when-honest`).
- R4.4 Interruption budget: max 3 proactive notifications per day outside the inbox, quiet hours default 18:00-08:00, digest batching, and only-when-actionable suppression. Notifications are browser/WebView toasts that deep-link to the card; nothing requires the app to be foreground (`rule/time-limit-adjustable` does not apply to notifications; they queue, never expire silently).
- R4.5 Empty inbox is a good empty: "Nothing needs your attention" plus a link to the Agent's activity log summary (`rule/empty-state-action`).

### S5. Settings

- R5.1 Toggle-only surface: data sources on/off, quiet hours, notification budget, LLM endpoint status (read-only indicator, not a field), "What this app touches" (the IT-facing doc, always reachable).
- R5.2 No setting exists whose default would do (principle 5); each toggle earns its place.
- R5.3 "Export audit log" produces a plain-CSV activity record (plugin, action, target, time) for the Security persona.

## 5. Action inventory (object, scope, consequence, reversibility)

| # | Action | Object | Scope | Consequence | Reversible | Pattern (rules) |
|---|---|---|---|---|---|---|
| A1 | Add plugin (wizard commit) | plugin | 1 plugin | gains exactly the declared read-only capabilities; runs on cadence | Yes (disable/uninstall) | Review step + one consolidated approval; no second confirm (`rule/name-object-scope-consequence`, `rule/irreversible-action-safeguard`, `rule/destructive-proportional`) |
| A2 | Remove widget | widget instance | 1 card | hidden; config and data kept | Yes | Act immediately + undo toast; honest because widget config is recoverable in the widget library (`rule/undo-only-when-honest`) |
| A3 | Uninstall plugin | plugin | 1 plugin | code and schedules removed; plugin data kept | Yes | No confirm; data preserved |
| A4 | Delete plugin data | plugin data | 1 plugin's stored data | permanent loss | No | Named confirmation, Verb+Noun button ("Delete sales history") (`rule/destructive-names-action`, `rule/no-confirm-ok-labels`, `rule/irreversible-action-safeguard`) |
| A5 | Update plugin | plugin | 1 plugin | new version; identical or narrower scopes auto-apply; wider scopes re-consent | Yes (one-click rollback to prior version) | Re-validation + capability diff; approval only on widening (`rule/name-object-scope-consequence`) |
| A6 | Accept skill proposal | skill | 1 skill | skill becomes active | Yes | Act + undo via version history (`rule/undo-only-when-honest`) |
| A7 | Dismiss card | suggestion | 1 card | to Dismissed view, 30 days | Yes | Act, no confirm |
| A8 | Toggle data source | source | 1 source | ingestion stops/starts now | Yes | Switch (immediate binary) per control-selection table |
| A9 | Re-test widget | widget | 1 widget | immediate re-run | Trivial | Button with stable label while busy (`rule/loading-stable-labels`) |
| A10 | Export feature request | request | 1 request | queued to owner | n/a | Wizard terminal state; content preserved and shown |

## 6. Reachable-state coverage (per surface, key states)

| Surface | Loading | Empty | Sparse/partial | Stale/amber | Error | Offline/degraded | Permission/disabled |
|---|---|---|---|---|---|---|---|
| S0 Install | setup progress, specific copy | first-run demo widgets | partial sources connected | n/a | install blocked (WDAC): plain-language stop + IT letter | no network: defer, retry | n/a |
| S1 Dashboard | per-widget skeletons | "No sales data yet" + point-to-file action | 1 row, 1 widget: grid holds | freshness stamp + amber + Re-test | file locked / parse failed: cause + auto-retry note | widgets live, assistant degraded | source off: widget explains how to reconnect |
| S2 Assistant | stable send label, streaming | greeting + 3 starter prompts | n/a | n/a | endpoint down: degrade region only | same as error | n/a |
| S3 Wizard | per-step busy, stable labels | n/a (entry is the empty) | partial answers carried forward | n/a | cannot-build terminal state with export | mid-wizard offline: answers preserved | scope unavailable: nearest variant offered |
| S4 Inbox | card skeletons | "Nothing needs your attention" + activity link | 1 card | aged cards marked | n/a | queued, not lost | n/a |
| S5 Settings | n/a | defaults shown | n/a | n/a | endpoint status indicator | n/a | toggles disabled say why |

Coverage gap (proposed) `rule/suggestion-entrance-states`: every agent-initiated card renders with an origin reason line and both Accept and Dismiss reachable by keyboard. Category: State coverage. Governed in this PRD by R4.1 until promoted.

## 7. Security, privacy, and licensing constraints (binding, from research A9)

- Class D plugins only; compiler never emits executable code; ui-schema rendering only.
- Localhost server: 127.0.0.1 bind, 256-bit session token bootstrap, HttpOnly SameSite=Strict cookie, Origin/Host validation on HTTP and WebSocket.
- Lethal trifecta broken structurally: file-reading widgets get no network; watched content is data, never instructions.
- Data egress: only derived abstractions (topics, counts, commitments) go to the corporate LLM endpoint; raw mail/file bytes stay local; every outbound call is in the audit log.
- No autostart persistence until Security sign-off; on-demand shortcut in v1.
- Licenses: MIT/Apache-2.0/BSD/ISC only; upstream LICENSE/NOTICE files ship inside the install folder; zero exceptions (pywin32 eliminated; SQLite/FTS5/sqlite-vec stack).

## 8. Accessibility requirements

- Primary flows (add plugin, accept card, read dashboard) complete by keyboard with visible focus (`rule/keyboard-complete-flow`); focus moves into overlays and returns on close.
- Every icon-only control (widget overflow, card dismiss) has an accessible name (`rule/accessible-name-required`).
- Wizard never re-asks answered questions (`rule/no-redundant-entry`); nothing already typed is lost on error (`rule/preserve-user-input`).
- All state copy works when heard via screen reader: errors read sensibly after the widget title (`rule/reads-without-seeing`).
- The token-auth URL flow must allow paste and password-manager style autofill of nothing secret from memory; the token arrives via the launched browser, never typed by hand (`rule/auth-allows-assistance`).
- Localization headroom: dashboard verbs and card labels designed for 200-300% string growth; no fixed-width segmented controls on translated strings.

## 9. Success metrics

- Activation: first real (non-demo) widget live within 10 minutes of first launch, on the manager's actual laptop, with no technical-owner intervention.
- Habit: 4 of 5 workdays opened unprompted by week 4 (proxy: session count).
- Self-service: >= 1 plugin built by a no-code user per active user per month by week 8; wizard completion rate >= 60%; wizard cannot-build rate <= 20% and falling.
- Trust: suggestion acceptance rate >= 30% with notification opt-out < 10%; approval click-through time p50 < 15s (they read them, or they are too rare).
- Safety: zero EDR alerts, zero DLP incidents, audit export accepted by Security.
- Reliability: widget amber-state mean time to recovery < 1 workday (the UI is the log).

## 10. Phases and gates

| Phase | Scope | Exit gate |
|---|---|---|
| P0 Probe (week 0) | Environment probe script on the real laptop: unsigned-user-space execution, package install path (uv/mirror/CA), PA personal flows allowed, OneDrive sync present, EDR identified | All five answers known; go/no-go recorded |
| P1 v1 (weeks 1-4) | S0, S1 (3 hardcoded widgets), S2, minimal S5; on-demand launch; no plugin system; no persistence | Priya uses it 4/5 days; IT doc accepted in review |
| P2 v2 (weeks 5-10) | S3 wizard (Class D), S4 inbox, internal git registry, first plugin extracted from the sales widget | 1 self-built plugin by Priya; 60% wizard completion |
| P3 v3 | Repetition detector and skill proposals; people memory with commitment extraction; pre-meeting briefs (calendar-only context); optional persistence after Security sign-off; email digest | Suggestion acceptance >= 30%; Security approves or rejects persistence in writing |

## 11. Open product decisions

1. Product name (blocking nothing; needed before P2 registry naming).
2. Default quiet hours (proposed 18:00-08:00 local) and daily notification cap (proposed 3): confirm with Priya's actual day.
3. Whether the assistant chat is present in v1 or deferred to v2 (it adds surface; the widgets may carry P1 alone).
4. Meeting briefs in P3: calendar-only context confirmed; mail-context briefs need an explicit DLP decision from IT (separate review).
5. Multi-user story: is this Priya's tool, or a team deployment with a shared registry from day one (affects registry permissions model in P2).
6. Dismissed-cards retention (proposed 30 days) and whether dismissed skill proposals can resurface with new evidence.

## 12. Follow-on routing

- Exact strings for all buttons, errors, empty and loading states: `copywriting` (this PRD fixes the decisions; the verb table lives there: Add, Remove, Delete, Accept, Dismiss, Re-test, Export).
- Visual design of dashboard, cards, wizard, and inbox; component build; rendered accessibility and layout audits: `ui-design` (build + Audit mode).
- Toast entrances, wizard step transitions, amber-state attention motion: `ui-animation`, after `ui-design` settles the states.
