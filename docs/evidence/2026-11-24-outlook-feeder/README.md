# Evidence: Outlook metadata feeder (I5, spec 024)

Date: 2026-11-24. Tree: branch `spec024/outlook-feeder`. Evidence run against commit `661c6fbb567279c12a6a9b153a878c9d4b421160` (the fix that surfaces the platform unavailable cause); the docs commit follows it.

This folder holds the docs and evidence pack for spec 024. It contains no product code change and no real mail. The synthetic fixtures use invented senders and subjects. The live Windows smoke prints counts and Outlook handler ids only and never selects a notification payload.

## Files

| File | What it is |
|---|---|
| `focused-tests.txt` | The two focused pytest commands and their output: the feeder suite and the mail/settings/route/IT-surface suite |
| `synthetic_stores.py` | Runs both readers over synthetic stores built from the test fixtures and writes no real data |
| `synthetic-stores.txt` | Output of the synthetic WPN and macOS runs: counts, message fields, file list, sentinel checks, rerun idempotence |
| `live_wpn_smoke.py` | Reads the real WPN store through the collector's read-only snapshot and prints counts and Outlook handler ids only |
| `live-wpn-smoke.txt` | Live output: `available=True`, one Outlook handler, 0 Outlook toast rows, 0 collected alerts |
| `capture_settings_snapshot.py` | Boots the real server over the test harness and captures the Settings alerts block, no browser |
| `settings-capture.txt` | Output of the two captures: feed off and injected manual fallback |
| `settings-widgets-off.json` | `/widgets/settings` payload with the feeder off (`mail_feeder: false`) |
| `settings-alerts-off.html` | The Settings Outlook alerts block with the feed off |
| `settings-fetch-manual.json` | `POST /settings/mail/fetch-now` response for the injected manual fallback |
| `settings-alerts-manual.html` | The Settings Outlook alerts block with the manual fallback and no alert count |
| `macos-manual-check.md` | Written macOS procedure, marked unverified; no Mac was used |

## Exact rerun commands

Run from the repository root on Windows with the app's Python environment:

```
python -m pytest tests/test_feeder_contract.py tests/test_feeder_writer.py tests/test_feeder_runner.py tests/test_feeder_platform.py tests/test_feeder_wpn.py tests/test_feeder_macos.py -q
python -m pytest tests/test_mail_core.py tests/test_mail_watcher.py tests/test_mail_store.py tests/test_mail_brief.py tests/test_server_mail_api.py tests/test_route_table.py tests/test_server_settings_api.py tests/test_server_it_surface.py tests/test_settings_concurrency.py -q
python docs/evidence/2026-11-24-outlook-feeder/synthetic_stores.py
python docs/evidence/2026-11-24-outlook-feeder/live_wpn_smoke.py
python docs/evidence/2026-11-24-outlook-feeder/capture_settings_snapshot.py
```

On a non-Windows machine, the live smoke has nothing to read; run it only on Windows. The synthetic script imports the test fixtures and runs on any platform that has the repository and pytest installed.

## Results recorded here

- Feeder suite: 66 passed, 1 skipped (the live macOS store check skips off macOS).
- Mail, settings, route and IT-surface suites: 160 passed.
- Synthetic WPN: 5 rows in, 3 Outlook messages out, preview sentinel absent, 3 files, 3 files after a rerun.
- Synthetic macOS: 3 records in, 2 Outlook messages out, all body sentinels absent, 2 files, 2 files after a rerun.
- Live WPN: 281 handlers, Outlook handler `RecordId=129`, `PrimaryId=Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows`, 71 notification rows (33 toast, 36 condensed, 2 badge), 0 Outlook toast rows, `available=True`, 0 collected alerts. This host has no Outlook alert, recorded honestly.
- Settings: feed off shows `mail_feeder: false` and "Not run yet"; manual fallback shows collector `manual`, result `unavailable`, the manual sentence and no alert count.

## Discrepancies found, not fixed

1. The Settings coverage paragraph says "On Windows that is about 20 per app" on every platform. See `src/agentdesk/server/settings_view.py:1101-1103`.
2. The runner comment references a nonexistent `mail_feeder_days` setting. See `src/agentdesk/feeder/runner.py:25`.
3. The WPN tests are gated by `sys.platform` even with an injected synthetic store, so they only pass on Windows; the current Linux CI subset excludes them.

A reader-cause propagation gap found while drafting this pack was fixed in review by commit `661c6fb`: the runner now records the reader's own unavailable cause and names the reader instead of replacing it with the generic manual sentence.
