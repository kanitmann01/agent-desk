# I4: Watcher, settings, UI and disclosure

Part of specs/024-outlook-metadata-feeder.md (G4, G6, G7). Blocked by: I1.

## Context

The mail watcher polls every 30 minutes and once at startup. The feeder should run before that read, through an injected callable, so tests never touch a real index. The Settings Sources card is server-rendered; the route table and settings API tests pin every new key and route. The IT statement currently says the desk starts nothing by itself and creates no scheduled task; this feature starts a local read-only helper while the app is open, so the statement and its test must change.

## Scope

- `src/agentdesk/mail/watcher.py`: accept an optional `feeder` callable. In `poll()`, after the folder is resolved and before the read, call it once, catch every exception, and record `fetch` in `status()` and `view()`. A failed fetch never stops the folder read.
- `src/agentdesk/settings.py`: add `mail_feeder` (bool, default false). Do not add a window setting; the notification stores have their own short retention.
- `src/agentdesk/server/settings_view.py`: add an Outlook alerts block to the Sources card, with the toggle, the active collector, last run, alert count, coverage window, last error, and a Fetch now button. Use the existing markup and `_agent_clock`. The copy says "alerts only, not a mailbox" and points at the manual folder for history.
- `src/agentdesk/server/app.py` and `routes.py`: construct the feeder only when mail and the feeder are on, wire it to the watcher, add the toggle to the settings whitelist, add `POST /settings/mail/fetch-now`, and audit `mail.fetch` with the folder basename only.
- `src/agentdesk/server/touches.py`: correct the persistence and "starts nothing" sentences. The truthful statement is that the desk reads the local OS notification store for Outlook alerts while it is open, creates no scheduled task, service or autostart entry, and keeps the manual `.eml` folder for history. Update `tests/test_server_it_surface.py`, `tests/test_route_table.py`, and `tests/test_server_settings_api.py` expected dictionaries.
- Tests: fake feeder called before the read; failure leaves a readable folder; status shape; toggle and fetch-now routes; rendered copy; no number in an attention state; no model prompt; no network.
- Copy must be platform agnostic: name the collector and its coverage, not Windows or macOS, except where the macOS Full Disk Access cause is the honest explanation.

## Acceptance

The focused mail, settings, route and IT-surface tests pass; the settings page renders the block; the fetch-now route runs the injected feeder; the IT statement truthfully says the desk reads the local OS notification store for Outlook alerts while it is open and creates no scheduled task or service.

## Resolution (2026-11-24)

Resolved. `MailWatch` accepts a `feeder` callable, calls it after folder resolution and before the read, catches every exception, records `fetch` in `status()` and `view()`, and audits `mail.fetch`. `mail_feeder` defaults to false and is accepted by the settings save route; turning it on also turns on the mail digest, because the alert files land in the same folder. The Sources card renders the alerts block with the toggle, collector, last run, result, count, coverage window, error and Fetch now. `POST /settings/mail/fetch-now` runs the injected feeder and answers `ran: false` when the feed is off. The IT statement now says the reader runs only while the app is open and starts no task, service or autostart entry. The focused suites are 160 passed. One copy gap remains recorded, not fixed: the coverage line says "On Windows" on every platform.
