# Spec 024: A platform-agnostic Outlook alert feeder

Status: draft for review, 2026-11-24. Wayfinder map: docs/plans/2026-11-24-outlook-local-ingestion-map.md. Tickets: docs/tickets/2026-11-24/.

## Problem Statement

The desk reads mail only from a folder of exported `.eml` files. On a corporate laptop the tenant blocks app registration, Graph, IMAP, EWS, Power Automate and Outlook add-ins, so there is no connector path. Manual Save as is the only guaranteed feeder today, and it is labour the user will not keep doing. The user may run the app on Windows or on a work Mac, so a Windows-only answer is not acceptable.

The research found one local automatic source that works with the new Outlook clients on both platforms: the operating system notification store. Outlook raises a desktop alert for each new message, and the OS persists that alert in a per-user database. The alert carries the sender and the subject, not the mailbox. That is enough for a live signal, not for a mailbox mirror.

Two facts shape the solution:

- The app already has the right contract: `src/agentdesk/mail/core.py` parses header-only `.eml` files and nothing else. A feeder that writes that contract needs no parser, no plugin and no model.
- The notification stores are readable in user space with no tenant access and no admin rights. On Windows the store is readable directly; on macOS it needs Full Disk Access, a per-app user consent.

## Solution

Add a host-side, opt-in Outlook alert feeder with one platform-agnostic Python core, one logical automatic collector and one manual fallback.

The core owns the contract, the schedule and the truth:

- `Message` is the existing `agentdesk.mail.core.Message` type. It has no body field, so the no-body rule is inherited rather than restated.
- `AlertCollector` is a small protocol: `name`, `available() -> tuple[bool, str]`, `collect(now, limit) -> list[Message]`.
- The `.eml` writer turns messages into CRLF, UTF-8 without BOM files with a unique Message-ID and no body. Writes are atomic and deterministic, so reruns overwrite rather than duplicate.
- `OutlookFeeder` runs one collection pass, records the collector, time, count and any honest failure, and never raises into the caller. A lock prevents overlapping passes.

The collectors:

1. `NotificationStoreCollector`: the only automatic collector.
   - On Windows it snapshots `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db` plus `-wal` and `-shm`, keeps the toast rows whose handler is an Outlook client, parses the toast XML, and keeps at most the first two text lines: sender and subject. The preview line is dropped and never written.
   - On macOS it snapshots `~/Library/Group Containers/group.com.apple.usernoted/db2/db` plus its WAL sidecars, keeps the records whose app identifier is Outlook, parses the binary property list, and keeps the title and subtitle only. The body and preview are dropped. This requires Full Disk Access; without it the collector is unavailable with that exact cause.
   - Both readers return the same `Message` records. This is a live-alert source, not a mailbox mirror.
2. `ManualCollector`: the no-op state. The user exports `.eml` files with Save as or drag-and-drop. This is the history source on both platforms, and the only history source on macOS with new Outlook.

The feeder is not a plugin. It is a host capability, like the mail watcher or the calendar bridge. It makes no network call, calls no model, reads no body and stores no cloud copy.

### Coverage matrix

| Platform | Automatic | History | Fallback |
|---|---|---|---|
| Windows, classic Outlook | WPN alerts | manual `.eml` | manual `.eml` |
| Windows, new Outlook | WPN alerts | manual `.eml` | manual `.eml` |
| macOS, new Outlook | Notification Center alerts, Full Disk Access | manual `.eml` | manual `.eml` |
| macOS, legacy Outlook | Notification Center alerts, Full Disk Access | manual `.eml` | manual `.eml` |

Future, not v1: the Windows Search index for history on a machine that indexes a classic Outlook profile; the classic COM export for richer headers; Spotlight for legacy Outlook for Mac only. Each has a gate the app cannot control, and none is proven on the user's machines. They are named in the research note, not promised here.

### Why not the history collectors in v1

- New Outlook for Mac has no AppleScript support. Microsoft cancelled that roadmap item in August 2026. New Outlook for Mac also uses server-side search and is not indexed by Spotlight. There is no supported local history API for it.
- The Windows Search index may include a classic Outlook mailbox only when the mapi16 handler and the index are healthy, and it does not expose Message-ID. The app's threading would fall back to the subject.
- Classic COM is protected by the Object Model Guard; prompt-free operation depends on antivirus health and Trust Center policy, which a non-admin cannot change.
- Each of these is a platform-specific gate. Shipping all three in v1 would be three unproven promises. The alert feeder plus the manual folder is smaller, cross-platform and honest.

## User Stories

1. As a desk owner on Windows, I want the desk to show the Outlook alerts it can see locally without a connector, so new mail is visible without manual export.
2. As a desk owner on a Mac, I want the same alert feed through Notification Center, so the product is not Windows-only.
3. As a desk owner who has not granted Full Disk Access on macOS, I want a plain explanation and the manual path, not a silent empty card.
4. As a privacy reviewer, I want a structural guarantee that the feeder writes headers only and never opens a network socket or a model client.
5. As an operator, I want to turn the feeder on and off in Settings and see the last collector, last run, alert count and last error.
6. As a reviewer, I want tests that fake both notification stores, so no CI run depends on a real mailbox or a real notification database.
7. As a reader, I want the card to say "alerts, not a mailbox" and to show the coverage window, so I never mistake a signal for a full inbox.

## Acceptance Criteria

- G1 Core contract: a `Message` list always becomes valid `.eml` files that `parse_eml` reads with the expected fields, a unique Message-ID, RFC 2822 Date, CRLF, UTF-8 without BOM, and no bytes after the header terminator.
- G2 Windows reader: with a synthetic WPN store (schema copied from the live probe), only Outlook toast rows become messages; the preview line is counted and absent from every output file; a second pass writes nothing new.
- G3 macOS reader: with a synthetic Notification Center store, only Outlook records become messages; the body and preview are absent; a missing Full Disk Access state is reported with its exact cause. The reader is not claimed as verified on a real Mac until a manual check is recorded.
- G4 Selection and honesty: the feeder picks the one automatic collector when available, names it and its coverage in status, and falls back to the manual path with a plain sentence otherwise. No attention state shows a number.
- G5 Privacy: no feeder module imports an HTTP client or the model client; no generated file contains a body, an attachment or a preview line; a test scans the readers and the generated output.
- G6 Schedule: the feeder runs before the existing mail poll and once at startup, uses the app's timer, and creates no OS task, service or autostart entry.
- G7 Disclosure: `src/agentdesk/server/touches.py` and the settings copy say that the desk reads local Outlook alerts while it is open, that it creates no scheduled task or service, and that the feed is alerts only. The existing "starts nothing by itself" statement is corrected.
- G8 Regression: the mail, settings, route and IT-surface tests pass, and an API walkthrough shows the feeder on with a synthetic alert, the manual fallback, and the macOS permission state.

## Non-Goals

- Microsoft Graph, IMAP, EWS, OAuth app registration, Power Automate, Outlook add-ins or tenant consent.
- Reading, storing or sending message bodies, attachments, previews or inline images.
- A cloud copy, a relay, a server-side component or telemetry.
- A Windows service, a machine-wide install, a login item or an autostart entry. The app runs the feeder only while it is open.
- A new shipped plugin. The plugin set was retired in spec 015; this is a host capability.
- Windows Search, classic COM, Spotlight or AppleScript collectors in v1. They remain future options with their own probes and specs.
- Calendar export in v1. The calendar contract is separate and still assumes a synced JSON file.
- Guaranteeing that any notification store contains the user's mail. The app detects and reports.

## Implementation Decisions

- The feeder lives in a new `src/agentdesk/feeder/` package, with the platform readers in `src/agentdesk/feeder/collectors/`. It uses the existing `agentdesk.mail.core.Message` type.
- Settings: `mail_feeder` (bool, default false). Reuse `mail_folder` as the drop folder. Do not add a second folder setting and do not add a window-days setting: the notification stores have their own short retention.
- The feeder runs inside `MailWatch` before the folder read, through an injected callable, so every existing mail test can fake it. A failed collection never stops the folder read.
- The feeder also has its own status dict, carried in `MailWatch.status()` and rendered by the Settings Sources card. It is not a setting and not a new store.
- The Windows reader snapshots the live WPN database with the SQLite backup API, then falls back to copying `db`, `-wal` and `-shm` together. It never writes the live store.
- The macOS reader copies the Notification Center database plus its WAL sidecars, never opens the live file for writing, and parses `record.data` with `plistlib`. It reads the `app.identifier` to filter Outlook. Full Disk Access is a user consent, not an admin step.
- The `.eml` writer uses a deterministic filename from the alert's stable id, a temp file and `os.replace`. Alerts have no Message-ID in the source, so the writer synthesizes one from the source app, the source id and the arrival time.
- The IT statement and PRD copy are updated with the feature, because the app now reads a local notification store while it is open.
- The status says the coverage window and "alerts only". It never calls the feed a mailbox, a sync or a mirror.

## Risks

- Notification stores keep a short history. Windows keeps about 20 toasts per app, and macOS retention is short. A quiet app or a long sleep leaves gaps. The card must show the coverage window and never imply completeness.
- The macOS reader needs Full Disk Access. A user who cannot grant it gets the manual path and a plain cause. Corporate MDM may block the consent.
- The alert layout is app-provided. Sender and subject can swap, truncate or be absent. The writer leaves missing headers out rather than inventing them; the card labels the source as an alert.
- The preview line is present in the OS payload. The reader must drop it before writing, and a test must prove a sentinel preview never reaches any output.
- Duplicate alerts (banner and condensed toast) can describe one message. The reader dedupes on the source app and the notification id, and the writer overwrites the same filename on a rerun.
- Starting a reader changes the product's "starts nothing by itself" statement. The statement, its test and the PRD line must change in the same ticket.
- The full app has Windows packaging assumptions even though the Python core is portable. The macOS feeder is tested from source; a macOS package is a separate effort.

## Further Notes

- The Windows WPN schema and the macOS Notification Center schema are documented by forensic research, not by Microsoft or Apple as public APIs. Both can change between OS builds. The readers must fail closed and report a schema cause.
- The Windows Search index, classic COM and Spotlight remain the future history path for a machine where the user wants more than alerts. They are not part of v1.
- The existing `tools/export-outlook.ps1` remains a manual and demo helper. The product feeder does not require it.
- The existing `Message` contract has no body field. The feeder writer must not add one, and no test may pass a body through.
