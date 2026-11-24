# Wayfinder map: Outlook data into the desk without tenant access

Status: charting, 2026-11-24. Local-markdown tracker: this file is the map, child tickets live in `docs/tickets/2026-11-24/`.

## Destination

A decision-ready spec for `agent-desk-core` that lets a corporate laptop, on Windows or macOS, feed Outlook alerts and manual `.eml` history into the desk with no admin rights, no tenant consent, no Graph, no IMAP, no EWS, no Power Automate and no Outlook add-in. The spec must settle a platform-agnostic feeder core with one automatic collector and one manual fallback, the schedule, the privacy contract, the setup and failure states, and the test and evidence plan.

## Notes

- Hard constraints: no tenant admin, no app registration, no Graph, no IMAP, no EWS, no Power Automate, no Outlook add-in, no machine-wide install, no OS service, no admin rights, no cloud copy, header-only mail.
- Platform agnostic: the feeder core, settings and output contract work on Windows and macOS. The user may run the app on a work Mac. No Windows COM, PowerShell, Task Scheduler or Windows Search dependency in the core. Platform collectors sit behind one Python interface: Spotlight on macOS, the Windows Search index or classic COM on Windows, and the manual folder everywhere. Scheduling is the app's own timer, not an OS scheduler.
- The app already reads RFC 822 `.eml` files from a watched folder (`src/agentdesk/mail/`) and calendar data from a JSON file (`src/agentdesk/calendar/`). The feeder is host-side, not a plugin. The plugin set was retired; do not add a plugin for this.
- Research lives in `D:/20-projects/Personal Agents/.scratch/outlook-ingest-swarm`. The synthesis will be linked from this map.
- Skills every session consults: `wayfinder` (this map), `ponytail` (smallest complete change), `implement-spec` (ticket graph plus TDD subagents), `tdd`, `code-review`.
- The product repo is `D:/20-projects/Personal Agents/agent-desk-core`. Implementation happens in a worktree branched from `main`.

## Open tickets

All four decision tickets are resolved. The frontier is now the implementation tickets.

- [Which local Outlook data sources actually work here?](docs/tickets/2026-11-24/O1-local-outlook-sources.md): resolved.
- [How does the feeder run without admin?](docs/tickets/2026-11-24/O2-feeder-scheduling.md): resolved.
- [What is the feeder's privacy, consent and failure contract?](docs/tickets/2026-11-24/O3-feeder-contract.md): resolved.
- [What is the proof plan?](docs/tickets/2026-11-24/O4-proof-plan.md): resolved.
- [The feeder core and header-only writer](docs/tickets/2026-11-24/I1-feeder-core.md): writer and contract complete; runner and platform seam in progress.
- [The Windows notification-store reader](docs/tickets/2026-11-24/I2-windows-wpn-reader.md): in progress.
- [The macOS Notification Center reader](docs/tickets/2026-11-24/I3-macos-notification-reader.md): in progress.
- [Watcher, settings, UI and disclosure](docs/tickets/2026-11-24/I4-watcher-settings-ui.md): in progress.
- [Docs, walkthrough and evidence](docs/tickets/2026-11-24/I5-docs-evidence.md): blocked by I2 to I4.

## Decisions so far

<!-- one line per closed ticket, with a link and a gist -->

- [Which local Outlook data sources actually work here?](docs/tickets/2026-11-24/O1-local-outlook-sources.md): one automatic source, the OS notification store, WPN on Windows and Notification Center on macOS, plus the manual `.eml` folder for history. New Outlook for Mac has no AppleScript and no Spotlight indexing; Windows Search, COM, Spotlight and AppleScript are future options, not v1 promises.
- [How does the feeder run without admin?](docs/tickets/2026-11-24/O2-feeder-scheduling.md): the app's own daemon timer on both platforms, plus a startup pass. No OS task, service or autostart entry, because the PRD and the IT statement forbid persistence and the existing watchers already use cross-platform timer chains. Closed-app collection is deferred to a separate Security decision.
- [What is the feeder's privacy, consent and failure contract?](docs/tickets/2026-11-24/O3-feeder-contract.md): read the two alert lines, drop the preview and body, write header-only `.eml`, keep read-only status, off by default, name the collector and coverage, never a number in an attention state.
- [What is the proof plan?](docs/tickets/2026-11-24/O4-proof-plan.md): synthetic WPN and Notification Center stores, a writer round-trip, a no-leak sentinel test, idempotence, honest states, a metadata-only Windows live smoke, and a written manual Mac procedure.

## Not yet specified

None. The way to the spec is clear. Calendar parity is explicitly out of scope for this spec and becomes a separate effort if the user wants it.

## Out of scope

- Microsoft Graph, IMAP, EWS, OAuth app registration, Power Automate, Outlook add-ins or tenant consent. These are the access paths the user has ruled out.
- Reading, storing or sending message bodies or attachments. The mail path stays header-only.
- Machine-wide installation, an OS service, drivers, or admin rights.
- A Windows-only core. Windows COM, PowerShell and the Windows Search index may be optional future collectors, never the only path.
- Windows Search, classic COM, Spotlight and AppleScript in v1. Each has an uncontrolled gate and none is proven on the user's machines.
- Calendar export in v1. The calendar contract still assumes a synced JSON file.
- Sending mail from the app. Drafts stay local and explicit.
