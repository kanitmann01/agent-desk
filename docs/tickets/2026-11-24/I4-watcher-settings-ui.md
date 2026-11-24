# I4: Watcher, settings, UI and disclosure

Part of specs/024-outlook-metadata-feeder.md (G4, G6, G7). Blocked by: I1.

## Context

The mail watcher polls every 30 minutes and once at startup. The feeder should run before that read, through an injected callable, so tests never touch a real index. The Settings Sources card is server-rendered; the route table and settings API tests pin every new key and route. The IT statement currently says the desk starts nothing by itself and creates no scheduled task; this feature starts a local read-only helper while the app is open, so the statement and its test must change.

## Scope

- `src/agentdesk/mail/watcher.py`: accept an optional `feeder` callable. In `poll()`, after the folder is resolved and before the read, call it once, catch every exception, and record `fetch` in `status()` and `view()`. A failed fetch never stops the folder read.
- `src/agentdesk/settings.py`: add `mail_feeder` (bool, default false) and `mail_feeder_days` (choice 7, 14, 30, default 14).
- `src/agentdesk/server/settings_view.py`: add a Fetch from Outlook block to the Sources card, with the toggle, the window choice, the active collector, last run, last result, last error, and a Fetch now button. Use the existing markup and `_agent_clock`.
- `src/agentdesk/server/app.py` and `routes.py`: construct the feeder only when mail and the feeder are on, wire it to the watcher, add the toggle to the settings whitelist, add `POST /settings/mail/fetch-now`, and audit `mail.fetch` with the folder basename only.
- `src/agentdesk/server/touches.py`: correct the persistence and "starts nothing" sentences. Update `tests/test_server_it_surface.py`, `tests/test_route_table.py`, and `tests/test_server_settings_api.py` expected dictionaries.
- Tests: fake feeder called before the read; failure leaves a readable folder; status shape; toggle and fetch-now routes; rendered copy; no number in an attention state; no model prompt; no network.
- Copy must be platform agnostic: name the collector, not Windows or macOS.

## Acceptance

The focused mail, settings, route and IT-surface tests pass; the settings page renders the block; the fetch-now route runs the injected feeder; the IT statement truthfully says the desk runs a local read-only Outlook metadata helper while it is open and creates no scheduled task or service.
