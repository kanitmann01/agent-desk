# Spec 024: A platform-agnostic Outlook metadata feeder

Status: draft for review, 2026-11-24. Wayfinder map: docs/plans/2026-11-24-outlook-local-ingestion-map.md. Tickets: docs/tickets/2026-11-24/.

## Problem Statement

The desk reads mail only from a folder of exported `.eml` files. On a corporate laptop the tenant blocks app registration, Graph, IMAP, EWS, Power Automate and Outlook add-ins, so there is no connector path. Manual Save as is the only guaranteed feeder today, and it is labour the user will not keep doing. The app has no automatic way to pull Outlook metadata from the machine it runs on, and the current user may run the app on Windows or on a work Mac.

Two facts shape the solution:

- The app already has the right contract: `src/agentdesk/mail/core.py` parses header-only `.eml` files and nothing else. A feeder that writes that contract needs no parser, no plugin and no model.
- Both desktop platforms expose a local search index that already contains mail metadata: Windows Search on Windows, Spotlight on macOS. Both are readable in user space, with no tenant access and no admin rights. Neither is guaranteed to index Outlook, so the feeder must detect, report and fall back honestly.

## Solution

Add a host-side, opt-in Outlook feeder with one platform-agnostic Python core and pluggable read-only collectors.

The core owns the contract, the schedule and the truth:

- `MessageHeader` is the normalized record: message id, in-reply-to, sender, to, cc, subject, date, importance.
- `Collector` is a small protocol: `available()` says whether the platform source can run, `collect(window_days, limit)` returns normalized headers.
- The `.eml` writer turns headers into CRLF, UTF-8 without BOM files with a unique Message-ID and no body. Writes are atomic and old files are pruned inside the configured window.
- `OutlookFeeder` runs one collection pass before the existing mail poll and records the collector, time, count, and any honest failure. A lock prevents overlapping passes.

Collectors, in trust order:

1. `SpotlightCollector` on macOS: query Spotlight for mail items and read the header attributes with `mdls`. No tenant access, no admin.
2. `WindowsSearchCollector` on Windows: query the Windows Search index through `Search.CollatorDSO` and emit the same normalized headers. No COM, no profile required.
3. `ClassicComCollector` on Windows, optional: wrap the existing `tools/export-outlook.ps1` for richer headers when a classic Outlook profile exists.
4. `NotificationStoreCollector`, optional on both platforms: read the OS notification store for live Outlook alerts. This is a signal, not a mailbox mirror, and it never becomes the only source.
5. `ManualCollector`: the no-op state. The user keeps using Save as or drag-and-drop, and the app says so.

The feeder is not a plugin. It is a host capability, like the mail watcher or the calendar bridge. It makes no network call, calls no model, reads no body and stores no cloud copy.

### Collector matrix

| Platform | Primary | Optional richer | Optional signal | Guaranteed fallback |
|---|---|---|---|---|
| Windows | Windows Search index | classic COM export | WPN notification store | manual `.eml` folder |
| macOS | Spotlight | none in v1 | Notification Center store, if readable | manual `.eml` folder |

The collector matrix is the platform boundary. The core does not know which platform it is on; it asks each collector whether it is available and takes the first that can run. A platform with no working collector still has the manual path and an honest state.

The WPN store is deliberately not the primary source: it holds a short history of toasts, not a mailbox, and it cannot supply Message-ID, recipients or threads. The Windows Search index and Spotlight are the primary sources because they return the metadata the digest already consumes.

## User Stories

1. As a desk owner on Windows, I want the desk to pull Outlook headers from the local search index without a connector, so my mail digest is current without manual export.
2. As a desk owner on a Mac, I want the same behaviour through Spotlight, so the product is not tied to Windows.
3. As a desk owner whose machine does not index Outlook, I want an honest amber state that names the manual path, so I am not shown an invented zero.
4. As a privacy reviewer, I want a structural guarantee that the feeder writes headers only and never opens a network socket or a model client.
5. As an operator, I want to turn the feeder on and off in Settings and see the last collector, last run and last error.
6. As a reviewer, I want tests that fake every collector and every failure, so no CI run depends on a real mailbox.

## Acceptance Criteria

- G1 Core contract: a `MessageHeader` list always becomes valid `.eml` files that `parse_eml` reads with the expected fields, a unique Message-ID, RFC 2822 Date, CRLF, UTF-8 without BOM, and no bytes after the header terminator.
- G2 Windows collector: with a fake `Search.CollatorDSO` JSON response, the collector normalizes subject, sender, recipients, date and importance, and the app reaches the `watching` state with the generated messages.
- G3 macOS collector: with fake `mdfind` and `mdls` output, the collector normalizes the same fields and the app reaches `watching`. A manual Mac check is recorded as evidence, not claimed as a CI result.
- G4 Selection and honesty: the feeder picks the first available collector, names it in status, and falls back to the manual path with a plain sentence when none is available. No attention state shows a number.
- G5 Privacy: no feeder module imports an HTTP client or the model client; no generated file contains a body, an attachment or a preview line; a test scans the collectors and generated output.
- G6 Schedule: the feeder runs before the existing mail poll and once at startup, uses the app's timer, and creates no OS task, service or autostart entry.
- G7 Disclosure: `src/agentdesk/server/touches.py` and the settings copy say that the desk runs a local Outlook metadata collector while it is open. The existing "starts nothing by itself" statement is corrected.
- G8 Regression: the mail, calendar, settings, route and IT-surface tests pass, and a browser or API walkthrough shows the feeder on, a generated message and an honest off state.

## Non-Goals

- Microsoft Graph, IMAP, EWS, OAuth app registration, Power Automate, Outlook add-ins or tenant consent.
- Reading, storing or sending message bodies, attachments, previews or inline images.
- A cloud copy, a relay, a server-side component or telemetry.
- A Windows service, a machine-wide install, a login item or an autostart entry. The app runs the feeder only while it is open.
- A new shipped plugin. The plugin set was retired in spec 015; this is a host capability.
- Guaranteeing that any search index contains the user's mailbox. The app detects and reports.

## Implementation Decisions

- The feeder lives in a new `src/agentdesk/feeder/` package, with collectors in `src/agentdesk/feeder/collectors/`. It uses the existing `agentdesk.mail.core.Message` type, so the no-body invariant is inherited instead of restated.
- Settings: `mail_feeder` (bool, default false) and `mail_feeder_days` (choice, default 14). Reuse `mail_folder` as the drop folder. Do not add a second folder setting.
- The feeder runs inside `MailWatch` before the folder read, through an injected callable, so every existing mail test can fake it. A failed collection never stops the folder read. The feeder also has its own `start_polling`/`stop_polling` and status, so the Settings card can show last run and next run.
- Status is a read-only dict carried in `MailWatch.status()` and rendered by the Settings Sources card. It is not a setting and not a new store.
- The Windows collector calls a small PowerShell helper because `System.Data.OleDb` is the supported way to query `SYSTEMINDEX`; the helper returns JSON and the Python core owns parsing and writing.
- The macOS collector calls `mdfind` and `mdls` directly. No new dependency.
- The classic COM collector wraps the existing script only when it is present and a classic profile exists; it is not the default on a machine without a profile.
- The `.eml` writer prunes files older than the window and writes stable filenames from the message id, so reruns overwrite instead of duplicating.
- The IT statement and PRD copy are updated with the feature, because the app now starts a local read-only helper while it is open.

## Risks

- The corporate Windows image may disable Windows Search or exclude Outlook from the index; the corporate Mac may exclude Outlook from Spotlight. The app cannot fix that and must say so.
- The index may include mail from other accounts or clients. Collectors filter to the Outlook store where the platform exposes it; where it does not, the app names the source and the user can turn the feeder off.
- Indexed metadata may omit Message-ID, CC or In-Reply-To. The writer leaves those headers out rather than inventing them; threading degrades honestly.
- The full app has Windows packaging assumptions even though the Python core is portable. The macOS feeder is tested from source; a macOS package is a separate effort.
- Starting a helper changes the product's "starts nothing by itself" statement. The statement, its test and the PRD line must change in the same ticket.
- The Windows notification store is a real local signal but is not a mailbox mirror. It is deliberately not part of v1; it can become an optional live-signal collector later.

## Further Notes

- The existing `tools/export-outlook.ps1` remains a manual and demo helper. The product feeder does not require it.
- The existing `Message` contract has no body field. The feeder writer must not add one, and no test may pass a body through.
- The calendar contract is separate. A later spec can add a calendar collector that writes `calendar_sync.json`; v1 is mail only so the scope stays small and testable.
