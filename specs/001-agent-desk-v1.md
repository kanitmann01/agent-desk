# Spec: Agent Desk v1 and v2, no-code personal agent web app

Seams confirmed with the owner: primary seam is the local HTTP API; second seam is the plugin validator CLI (byte-identical to registry CI). Sources: docs/research.md (binding section A9), docs/PRD.md, docs/design-language.md, docs/design/dashboard.html.

## Problem Statement

A non-technical manager works on a locked-down corporate Windows laptop: no admin rights, no software installs, corporate LLM endpoint available. Every morning she manually opens the sales workbook and eyeballs what changed, scrolls the calendar and inbox for commitments, and repeats research questions by hand. Changes get noticed late, follow-ups drop, and she has no way to build or install anything to help herself. Consumer agent products are banned or blocked by IT, so the gap stays unfilled.

## Solution

Agent Desk: a local web app started with one double-click. It shows a widget dashboard (sales change over the last 24 hours, today's key commitment broken into checkable subtasks, a research panel), keeps every widget's freshness visible, and lets her grow the dashboard herself: she describes a plugin in plain English, the agent builds and previews it, and one consolidated approval installs it. The agent's own suggestions (skill proposals after repeated tasks, update re-consents, pre-meeting briefs) wait in an inbox under a strict interruption budget. Raw files never leave the machine; only derived abstractions go to the corporate LLM endpoint. Everything runs user-space, no admin, delete-folder uninstall.

## User Stories

1. As a manager, I want to start the app by double-clicking one shortcut, so that I never need admin rights or a terminal.
2. As a manager, I want the dashboard to open already showing demo widgets, so that I understand the product before connecting anything real.
3. As a manager, I want each data connection asked for in context at first use of its widget, so that every permission request has an obvious reason.
4. As a manager, I want to point the sales widget at my workbook with a file picker, so that I never type file paths.
5. As a manager, I want a guided walkthrough for connecting my calendar through Power Automate, so that I can do it myself in a browser.
6. As a manager, I want the app to confirm when my calendar data starts arriving, so that I know the bridge worked.
7. As a manager, I want the sales widget to show exactly what changed in the last 24 hours, so that I stop eyeballing the spreadsheet.
8. As a manager, I want every widget to show when it last updated, so that I can trust what I am reading.
9. As a manager, I want a failing widget to turn amber with a Re-test button and a plain-language cause, so that I can see and fix problems without logs.
10. As a manager, I want the widget to tell me when the workbook is locked because I have it open, so that I know the difference between blocked and broken.
11. As a manager, I want today's key commitment with an agent-generated breakdown into checkable subtasks, so that I walk into meetings prepared.
12. As a manager, I want follow-up chips with deadlines, so that promises do not evaporate.
13. As a manager, I want a research panel where I paste a question or context and get a sourced summary, so that research takes one step.
14. As a manager, I want the assistant chat to use my widgets' data when I ask, so that I never re-explain context.
15. As a manager, I want an Add-plugin button, so that I can grow the dashboard myself.
16. As a manager, I want to describe a plugin in plain English, so that no code is ever required from me.
17. As a manager, I want the wizard to ask at most a few multiple-choice questions with defaults, so that I am never stuck typing technical answers.
18. As a manager, I want a live preview of the widget with my real data before installing, so that I approve something I have seen.
19. As a manager, I want one consolidated approval stating what the plugin does, reads, and can never do, so that I understand what I am agreeing to.
20. As a manager, I want new plugins to carry a visible pilot badge for their first runs, so that new things are visibly new.
21. As a manager, I want the wizard to say honestly when it cannot build something and forward my request, so that dead ends still go somewhere.
22. As a manager, I want to remove a widget and get it back, so that experimenting is safe.
23. As a manager, I want one-click rollback when a plugin updates, so that updates cannot ruin my morning.
24. As a manager, I want the agent's suggestions to wait in an inbox, so that I am interrupted only when I choose to look.
25. As a manager, I want a skill proposal after I have done the same thing about five times, so that repetition turns into one click.
26. As a manager, I want Accept and Dismiss on every suggestion with a reason line, so that I can act in one glance.
27. As a manager, I want dismissed suggestions recoverable for thirty days, so that dismissing is safe.
28. As a manager, I want quiet hours and a daily notification cap, so that the agent never becomes a nag.
29. As a manager, I want a brief before meetings (attendees, open threads, my commitments), so that I am never blindsided.
30. As a manager, I want settings to be toggles only, so that configuration never needs documentation.
31. As the technical owner, I want the audit log exportable as CSV, so that Security can review what touched what.
32. As the technical owner, I want a one-page statement of what the app touches, so that IT review is trivial.
33. As the technical owner, I want to publish plugins to an internal git registry with CI validation, so that colleagues only install checked plugins.
34. As the technical owner, I want wizard feature requests queued, so that the declarative vocabulary grows where demand actually is.
35. As the technical owner, I want stable module interfaces (prompt, skills staging, cron, memory, health), so that the engine can be swapped later without touching the product.
36. As IT, I want no autostart persistence and a delete-folder uninstall, so that the tool's footprint is knowable.
37. As IT, I want a license manifest with only MIT, Apache-2.0, BSD, or ISC components, so that legal review has zero exceptions.
38. As IT, I want raw files to never leave the machine and every outbound call logged, so that DLP policy is respected.

## Implementation Decisions

Architecture (binding, from research section A9):

- Single-runtime pure-Python local web app (NiceGUI, or FastAPI plus a static bundle), serving the dashboard on 127.0.0.1. A WebView2 shell is optional polish; the browser is the default.
- Runtime delivery via uv with native TLS (Windows trust store), started by a plain .cmd entry. The Python embeddable zip is the airgapped fallback, not the primary.
- Localhost hardening: bind 127.0.0.1 only; on startup generate a 256-bit session token, open the browser at an auth URL, exchange it for an HttpOnly SameSite=Strict cookie; validate Origin and Host on every HTTP and WebSocket request.
- No autostart persistence in v1: on-demand shortcut, in-process scheduler, catch-up on next launch. Persistence only after Security sign-off.

Data sources:

- excel-watch: copy the workbook to a temp shadow file before parsing (Windows exclusive locks), parse the copy, snapshot parsed rows into SQLite, and compute the 24-hour delta as row-hash diffs against the T-24h snapshot. The workbook itself carries no timestamps; the snapshot store is the clock.
- Calendar: Power Automate bridge as rung zero (a personal recurrence flow writes a calendar JSON file to OneDrive, the built-in client syncs it locally, the app watches the folder). Fallbacks, in order: .ics subscription, classic Outlook COM, delegated Graph.
- Research and assistant: a thin agent loop against the corporate OpenAI-compatible endpoint; search through whatever endpoint IT sanctions; every outbound call logged.
- Memory: SQLite plus FTS5 plus sqlite-vec only. No external memory services, no telemetry-bearing dependencies.

Plugin system (Class D only):

- A plugin is a manifest, a declarative data source, a declarative UI schema, and optionally a SKILL.md. Plugins never ship HTML or JavaScript; the host renders the UI schema server-side.
- Manifest shape (from the research prototype; the decision-rich core):

```json
{
  "schemaVersion": 1, "id": "sales-delta-widget", "version": "1.2.0",
  "publisher": "acme-tools", "class": "declarative",
  "engines": { "dashboardHost": ">=1.0.0 <2.0.0" }, "license": "MIT",
  "permissions": {
    "filesystem": { "read": ["${workspace}/reports/*.xlsx"], "write": ["${pluginData}"] },
    "network": { "allow": [] }, "llm": { "allow": true, "maxTokensPerDay": 200000 },
    "shell": "none"
  },
  "optionalPermissions": { "network": { "allow": ["https://api.example.com/*"], "userPrompt": "..." } },
  "activationEvents": ["onWidget:sales-delta", "onSchedule:0 * * * *"],
  "contributes": {
    "widgets": [{ "id": "sales-delta", "size": "2x1",
                  "dataSource": { "type": "excel-watch", "deltaWindow": "24h" },
                  "render": { "type": "ui-schema", "file": "widget.ui.json" } }],
    "skills": ["skills/sales-summary/SKILL.md"],
    "preferences": [{ "name": "thresholdPct", "type": "number", "default": 5 }]
  }
}
```

- Validation before execution, always: JSON Schema, permission lint (rejects shell, unscoped filesystem, plugin HTML, unknown keys), over-permission diff, hash check. The client validator and registry CI validator are the same code.
- Registry: an internal git repo with a root index file (id, publisher, latest, risk, class, releases pinned by sha256 and git tag). Publishing is a PR that CI checks with the shared validator. The client keeps a lockfile, installs into versioned directories, and rolls back by repointing. Updates re-consent only when scopes widen.
- English-to-plugin compiler: spec interview (at most a handful of multiple-choice questions), capability planning mapped to broker scopes, Class D generation only, static gate, dry run with real or sample data, capped self-repair (three attempts against semantic assertions), and honest escalation: when it cannot build safely, it exports a feature request and preserves everything the user said.

Autonomy (v2 end, v3):

- Repetition detector: an activity log of user requests plus nightly clustering; at five similar requests, a skill proposal enters the staging queue.
- Interruption budget: quiet hours defaulting to 18:00-08:00, at most three proactive notifications per day, digest batching, and suppression when nothing is actionable. Suggestions queue; nothing expires silently.
- Pre-meeting briefs from calendar data in v3; mail-context briefs wait on an explicit DLP decision.

Engine posture: Hermes Agent patterns are ported (SKILL.md format, pending-staging approval queue, cron with missed-tick catch-up, memory discipline), but the Hermes runtime is not deployed. The module interfaces (prompt, skills staging, cron, memory, health) keep a future engine swap possible without touching the product.

Product and UX contract: personas, action inventory with reversibility, reachable states, and phase gates live in the PRD; visual tokens, type, spacing, and anti-slop commitments live in the design language. Both are binding inputs to the build: one primary action per surface, approvals consolidated and rare, freshness always visible, amber states with recovery, sample data labeled.

## Testing Decisions

A good test exercises external behavior through a seam and asserts on observable outcomes, never on internals. Two seams, confirmed with the owner:

- Seam 1, the local HTTP API (primary): tests boot the app, authenticate through the token bootstrap, and drive the product end to end without a browser. Covered here: first-run flow, widget refresh against fixture workbooks with known deltas, locked-workbook behavior (exclusive open produces the amber state and recovery), calendar ingestion by dropping a fixture calendar JSON into the watched folder, wizard happy path and dead-end path (feature request exported, user input preserved), plugin install, enable, disable, uninstall with data preserved, data deletion, update with identical scopes (auto-applies) versus widened scopes (re-consent required), rollback, inbox accept, dismiss, and thirty-day recovery, quiet-hours and notification-cap enforcement under a frozen clock, authentication rejection (missing token, invalid token, disallowed Origin), and audit CSV contents.
- Seam 2, the plugin validator CLI: property and fixture tests. Valid manifests pass. Shell permissions, unscoped filesystem globs, plugin-supplied HTML, unknown manifest keys, over-permission, and hash mismatch fail. The identity property is asserted directly: the same input yields the same verdict through the CLI and through the API.

Fixtures: sample workbooks with known 24-hour deltas, calendar JSON snapshots, frozen clock for refresh and budget logic. Prior art: none; this is a greenfield repo and these two seams establish the patterns. Rendered UI quality is covered by the separate ui-design audit pass, not by these tests.

## Out of Scope

- Class C code plugins, LLM-generated executable code, and sandboxed iframe visuals (a possible v3, behind its own approval class).
- Mail body ingestion and mail-context briefs (await an explicit DLP decision); any keystroke or screen observation.
- Autostart persistence before written Security sign-off.
- macOS, mobile, and messaging-channel integrations.
- Deploying the Hermes runtime (or any external agent binary).
- Multi-user or team deployment with shared registry permissions; v1 and v2 are single-user, with the registry model decided in v3.
- A public plugin marketplace; the internal git registry only.

## Further Notes

Open decisions, each with a recommended default. These are veto points: tickets may be cut against the defaults, and a decision changes here before it changes in code.

- Product name: default keeps the working name Agent Desk.
- Quiet hours: default 18:00-08:00 local, notification cap 3 per day.
- Assistant chat: default ships in v1 (the mockup and PRD already carry it).
- Dismissed-card retention: default 30 days.
- Registry model: default single-user now, interface ready for team sharing later.

Phase gates before build: the P0 environment probe on the real target laptop (unsigned user-space execution allowed, uv or mirror reachable under TLS inspection, personal Power Automate flows permitted, OneDrive client present and syncing, EDR identified). A no-go on any answer stops or reshapes the plan before code is written.

The issue body is canonical; a convenience snapshot lives at specs/ in the repo.
