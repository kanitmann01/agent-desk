# Wayfinder map: Outlook data into the desk without tenant access

Status: charting, 2026-11-24. Local-markdown tracker: this file is the map, child tickets live in `docs/tickets/2026-11-24/`.

## Destination

A decision-ready spec for `agent-desk-core` that lets a corporate laptop, on Windows or macOS, feed Outlook mail metadata, and calendar where possible, into the desk on a schedule with no admin rights, no tenant consent, no Graph, no IMAP, no EWS, no Power Automate and no Outlook add-in. The spec must settle a platform-agnostic feeder core with pluggable collectors, the schedule, the privacy contract, the setup and failure states, and the test and evidence plan.

## Notes

- Hard constraints: no tenant admin, no app registration, no Graph, no IMAP, no EWS, no Power Automate, no Outlook add-in, no machine-wide install, no OS service, no admin rights, no cloud copy, header-only mail.
- Platform agnostic: the feeder core, settings and output contract work on Windows and macOS. The user may run the app on a work Mac. No Windows COM, PowerShell, Task Scheduler or Windows Search dependency in the core. Platform collectors sit behind one Python interface: Spotlight on macOS, the Windows Search index or classic COM on Windows, and the manual folder everywhere. Scheduling is the app's own timer, not an OS scheduler.
- The app already reads RFC 822 `.eml` files from a watched folder (`src/agentdesk/mail/`) and calendar data from a JSON file (`src/agentdesk/calendar/`). The feeder is host-side, not a plugin. The plugin set was retired; do not add a plugin for this.
- Research lives in `D:/20-projects/Personal Agents/.scratch/outlook-ingest-swarm`. The synthesis will be linked from this map.
- Skills every session consults: `wayfinder` (this map), `ponytail` (smallest complete change), `implement-spec` (ticket graph plus TDD subagents), `tdd`, `code-review`.
- The product repo is `D:/20-projects/Personal Agents/agent-desk-core`. Implementation happens in a worktree branched from `main`.

## Open tickets

The frontier is the two research tickets. The contract and proof tickets are blocked until the research answers land.

- [Which local Outlook data sources actually work here?](docs/tickets/2026-11-24/O1-local-outlook-sources.md): research, frontier.
- [How does the feeder run without admin?](docs/tickets/2026-11-24/O2-feeder-scheduling.md): research, frontier.
- [What is the feeder's privacy, consent and failure contract?](docs/tickets/2026-11-24/O3-feeder-contract.md): grilling, blocked by O1 and O2.
- [What is the proof plan?](docs/tickets/2026-11-24/O4-proof-plan.md): task, blocked by O1, O2 and O3.

## Decisions so far

<!-- one line per closed ticket, with a link and a gist -->

- None yet.

## Not yet specified

- Which local Outlook data source is reliable on the corporate client, classic Outlook or new Outlook, on Windows and on macOS, and what evidence proves it.
- Whether the feeder is an app-owned background loop, an OS scheduler, or both, and why the cross-platform answer wins.
- The privacy and consent contract for a feeder that reads from a local Outlook store rather than an exported folder.
- The setup, verification, staleness and failure states the user sees, and the exact copy.
- Calendar parity: the same feeder, a separate file contract, or explicitly out of scope.
- The test and evidence plan that proves the mechanism on this machine without touching real mail.

## Out of scope

- Microsoft Graph, IMAP, EWS, OAuth app registration, Power Automate, Outlook add-ins or tenant consent. These are the access paths the user has ruled out.
- Reading, storing or sending message bodies or attachments. The mail path stays header-only.
- Machine-wide installation, an OS service, drivers, or admin rights.
- A Windows-only core. Windows COM, PowerShell and the Windows Search index may be optional collectors, never the only path.
- Sending mail from the app. Drafts stay local and explicit.
