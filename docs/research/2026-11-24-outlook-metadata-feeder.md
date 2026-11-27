# Outlook metadata feeder: OS alerts plus manual history

Status: research and evidence note for spec 024, 2026-11-24. Host: Windows 11 (Chibi). The macOS path was exercised against a synthetic store only; no Mac was used in this session. Every macOS procedure below is a written check, marked unverified.

Verification key: **[V]** measured on this Windows host in this session or recorded in the tree. **[S]** measured against a synthetic store built from the live schema, with invented senders and subjects. **[D]** a vendor or forensic documentation claim, not measured here. **[U]** unverified, needs a Mac or another machine.

## Bottom line

1. The only automatic local Outlook source that works with both the classic and the new Outlook clients on both platforms is the operating system notification store: Windows Push Notification (WPN) toasts on Windows, Notification Center on macOS. It yields a live alert signal only: sender and subject, no Message-ID, no folder, no read state, no recipients, no calendar.
2. The only guaranteed history source is the manual `.eml` folder the app already reads. Save as, Download from Outlook on the web, or drag and drop, on any client, with no admin and no tenant consent.
3. Everything else (Graph, IMAP, EWS, Power Automate, add-ins) is blocked by the tenant or needs consent the user cannot grant. Windows Search, classic COM, Spotlight and AppleScript remain future options, each with a gate the app cannot control, and none is a v1 promise.
4. The feeder is off by default, runs inside the app while the app is open, reads no body and no preview, writes header-only `.eml` files, and creates no OS task, service or autostart entry.

## Ranked mechanisms

| Rank | Mechanism | Platform and client | What it gives | Gate | v1 verdict |
|---|---|---|---|---|---|
| 1 | Windows WPN toast store, `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db` plus `-wal` and `-shm` | Windows, classic and new Outlook | Sender and subject from the Outlook toast XML, arrival time, stable notification id | Store readable in user space; Outlook handler registered; notifications enabled | **Automatic collector** |
| 2 | macOS Notification Center store, `~/Library/Group Containers/group.com.apple.usernoted/db2/db` plus WAL sidecars | macOS, new and legacy Outlook | Title and subtitle from the record's binary plist, delivery time, record uuid | Full Disk Access (per-app user consent); store present; Outlook records present | **Automatic collector** |
| 3 | Manual `.eml` folder, Save as / Download / drag and drop | Every platform and client | Full header set from the exported file; the app parses headers only | User effort; freshness is manual | **History source and fallback** |
| 4 | Windows Search index (`SYSTEMINDEX` over `Search.CollatorDSO`) | Windows, classic Outlook mailbox only | Headers for an indexed mailbox | `mapi16` handler and index healthy; no Message-ID; not proven on this host to include mailbox rows | Future, not v1 |
| 5 | Classic Outlook COM export (`tools/export-outlook.ps1`) | Windows, classic Outlook only | Rich headers including Message-ID | Configured profile; Object Model Guard depends on antivirus health and Trust Center policy; no COM in new Outlook | Dev and demo helper, not the product path |
| 6 | Spotlight (`mdfind`, `mdls`) | macOS, legacy Outlook for Mac only | Headers and some Outlook attributes | Legacy importer, indexing enabled, Spotlight Privacy; new Outlook for Mac is not indexed by Spotlight | Future, legacy only |
| 7 | AppleScript to Outlook for Mac | macOS, legacy Outlook for Mac only | Mail and calendar objects | Automation consent; new Outlook for Mac has no AppleScript support | Future, legacy only |
| 8 | Outlook for Mac `Outlook.sqlite` read-only snapshot | macOS, legacy and possibly new | Whatever the undocumented schema exposes | Undocumented, schema drift, app-container access | Not a source in v1 |

The order inside the product is only ranks 1 or 2, then rank 3. The platform list is built in `src/agentdesk/feeder/platform.py`: `win32` gets `WpnCollector` alone, `darwin` gets `MacNotificationCollector` alone, and every other label gets the manual fallback alone. When the platform reader is unavailable, the runner records that reader's own cause (no Outlook handler, a missing store, Full Disk Access) and names the reader in the status. The generic manual Save as sentence is the fallback only when no reader supplied a cause, or on a platform with no reader.

## Coverage matrix

| Platform | Automatic | History | Fallback |
|---|---|---|---|
| Windows, classic Outlook | WPN alerts | manual `.eml` | manual `.eml` |
| Windows, new Outlook | WPN alerts | manual `.eml` | manual `.eml` |
| macOS, new Outlook | Notification Center alerts with Full Disk Access | manual `.eml` | manual `.eml` |
| macOS, legacy Outlook | Notification Center alerts with Full Disk Access | manual `.eml` | manual `.eml` |

The alert feed is a signal, not a mailbox. The manual folder is the history source on every platform and the only history source on macOS with new Outlook.

## What the feeder reads and writes

- Reads: only the notification record for an Outlook alert. On Windows, the first two `<text>` nodes of the toast XML (sender, subject). On macOS, the title and subtitle keys of the record's plist. The preview node, the body and every other payload key are dropped before a record is built.
- Writes: one header-only `.eml` per alert into the configured `mail_folder`: `From`, `To`, `Cc`, `Subject`, `Date` (RFC 2822 GMT), `Message-ID`, `In-Reply-To`, `Importance`, CRLF, UTF-8 without BOM, and no bytes after the blank line. Missing fields are omitted rather than invented.
- Keeps: one status dict with collector, platform, last run, result, error, written count and coverage window. It is read-only state, not a setting, and holds no message content.
- Never: no network call, no model call, no cloud copy, no send, no body, no attachment, no OS scheduler, no admin.

Turning it on: choose the mail folder first, then turn on "Fetch Outlook alerts". The alerts are written into that same folder, so turning them on also turns on the mail digest and the digest will show the alert headers. Turning mail off stops both. Nothing is fetched while the app is closed.

## Verified local facts

Measured on the Windows host in this session:

- The live WPN store exists at `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db` (1,048,576 bytes) with a `-wal` sidecar (3,745,112 bytes) and a `-shm` sidecar (32,768 bytes).
- The store has 281 notification handlers and 71 notification rows: 33 `toast`/`Xml`, 36 `toastCondensed`/`Xml`, 2 `badge`/`Xml`.
- Exactly one handler is an Outlook handler: `RecordId=129`, `PrimaryId=Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows`, `HandlerType=app:immersive`.
- There are 0 Outlook toast rows and 0 Outlook rows with a non-empty payload. `WpnCollector.available()` is `(True, "")`; `collect(since=14 days, limit=100)` returns 0 messages. This host has no Outlook alert to read. That is recorded honestly, not worked around.
- The macOS reader treats a readable store with an Outlook app row but zero records as available and collects 0. Only a store with no Outlook app row is unavailable, with the no-Outlook cause. A `PermissionError` while copying the store maps to the Full Disk Access cause. The runner carries the reader's own unavailable cause into the status and names the reader, so the card does not replace it with the generic manual sentence.
- The final focused run over the feeder, mail, settings, route and IT-surface suites is 201 passed, 1 skipped (the live macOS store check skips off macOS). See `docs/evidence/2026-11-24-outlook-feeder/final-tests.txt`.
- Synthetic WPN store: 5 rows in, 3 Outlook messages out (two mail toasts sharing text but with distinct notification ids, one reminder), the non-Outlook toast and the condensed row filtered out, the preview sentinel absent from every field and every file, 3 files written, 3 files after a rerun.
- Synthetic macOS store: 3 records in, 2 Outlook messages out (mail with a body, reminder), the non-Outlook chat filtered out, all three body sentinels absent from every file, 2 files written, 2 files after a rerun.
- Settings capture, feed off: `/widgets/settings` returns `mail_feeder: false`; the alerts block says "Not run yet" and carries the manual folder as the history source. Settings capture, injected manual fallback: the block names collector `manual`, result `unavailable`, shows the manual sentence, and shows no alert count.

Recorded on this host before this session (from a machine-local research note, `outlook-ingestion-research.md`, kept outside the repo, verified there):

- Classic Outlook is installed at `C:\Program Files\Microsoft Office\Root\Office16\OUTLOOK.EXE` but `%LOCALAPPDATA%\Microsoft\Outlook` is absent, so there is no classic profile and COM export cannot work here.
- The new Outlook package exists but has no signed-in account and an essentially empty local cache.
- Windows Search answers queries but its sample email rows are `.msg` files, so mailbox indexing is not proven on this host.

## Documentation and forensic claims, not local facts

- **WPN schema and per-app cap.** The `Notification` and `NotificationHandler` schema and the claim that Windows keeps about 20 toasts per app come from forensic research and the O1 probe. The 20-toast cap was not independently re-measured in this session. **[D]**
- **macOS store schema.** The `app` and `record` tables, `record.data` as a binary property list, and the title/subtitle layout are documented by forensic research, not by Apple as a public API. The reader is verified against a synthetic store built from that shape. **[D][S]**
- **Full Disk Access.** macOS TCC blocks a third-party process from reading the usernoted group container until the user grants Full Disk Access. Corporate MDM may refuse the consent. **[D]**
- **New Outlook for Mac.** No AppleScript support (the roadmap item was cancelled in August 2026), server-side Microsoft Search instead of Spotlight, no documented local history API. **[D]**
- **Legacy Outlook for Mac.** Spotlight and AppleScript exist, but support ended in October 2026 for Microsoft 365 and Exchange Online accounts. **[D]**
- **EWS.** Microsoft blocks EWS requests from non-Microsoft apps to Exchange Online from 2026-10-01. **[D]**
- **IMAP.** OAuth IMAP requires tenant admin consent per Microsoft's own documentation; basic auth is disabled. **[D]**
- **Graph.** Delegated `Mail.Read` can be blocked by tenant user-consent policy and returns full messages, including body and preview. **[D]**
- **Power Automate and add-ins.** Personal flows can be blocked by connector action control or DLP, and add-in deployment is tenant-admin controlled. Both are connectors by another name. **[D]**
- **Classic COM.** `SaveAs` and address reads are guarded by the Object Model Guard; prompt-free operation depends on antivirus health and Trust Center policy, which a non-admin cannot change. **[D]**
- **Windows Search.** Microsoft documents Outlook adding synced mail to the index and documents `System.Message.Store`, but no Exchange/Outlook mailbox store value is documented and no Message-ID is exposed. **[D]**

## Rejected paths

- **Microsoft Graph.** App registration plus delegated consent; tenant policy can disable user consent; the API returns full messages, which is the DLP surface the product excludes.
- **IMAP.** Tenant admin consent is required per Microsoft documentation; basic auth is disabled; IMAP can be disabled per mailbox.
- **EWS.** Retired for non-Microsoft apps in Exchange Online from 2026-10-01.
- **Power Automate.** No admin consent on paper, but a tenant can block flows, connector actions or the connector pair, and it creates a second cloud copy. It is also not a local source.
- **Outlook add-ins / Office JS.** Tenant-admin deployment, hosting and an app registration. A connector by another name.
- **Windows Search, classic COM, Spotlight and AppleScript as v1 promises.** Each has a gate the app cannot control: index health and mapi16 on Windows, the Object Model Guard and a configured profile for COM, legacy-only support and Spotlight Privacy on macOS, Automation consent for AppleScript. None is proven on the user's machines, and shipping all four would be four unproven promises. They remain documented future options with their own probes and specs.
- **PST/OST/MSG parsing.** Copyleft or C-toolchain dependencies, bodies and attachments by construction, and new Outlook has no usable OST. The `.eml` path already covers the need.
- **New Outlook local cache (`Olk`, `EBWebView`).** Undocumented Chromium and IndexedDB cache, unstable, and indistinguishable from forensic scraping to EDR.
- **WinRT `Windows.ApplicationModel.Email`.** Package identity and Microsoft approval; Windows Mail was retired.
- **OWA browser automation.** Conditional access, MFA, UI churn and terms-of-service risk.
- **Third-party archivers.** Install, licence and full-message copies.
- **Task Scheduler, launchd, cron, login items.** The PRD and the IT statement forbid autostart persistence, and the app already has a cross-platform timer. Closed-app collection would be a separate Security decision.

## macOS manual check procedure

Status: **UNVERIFIED**. No Mac was used for this note. Run this on the work Mac and record the output before claiming macOS support.

1. Confirm the client: open Outlook and check whether it is new Outlook or legacy. Record the version.
2. Open System Settings > Privacy & Security > Full Disk Access. Add the terminal or the Python launcher used to start the app, and switch it on. This is a user consent, not an admin step. If MDM refuses the toggle, record that and stop: the manual folder is the only path on that machine.
3. Start the app from source with `python -m agentdesk.server --no-browser`, open Settings, choose a mail folder, and turn on "Fetch Outlook alerts". That toggle also turns on the mail digest, because the alert files land in the same folder.
4. Send a self-addressed test message from another account or from Outlook on the web with a unique subject token (for example `AGENTDESK-MAC-TEST-1`) and a body canary (for example `BODY-CANARY-DO-NOT-STORE`). Wait for the Outlook notification to appear in Notification Center.
5. Press "Fetch now". Then open `/mail` and confirm the subject token appears. Confirm the body canary appears nowhere: not on the mail page, not in any file in the mail folder, not in `~/.agent-desk/outlook-feeder.json`.
6. In Terminal, list the generated files and search them:
   `grep -R "BODY-CANARY-DO-NOT-STORE" "<mail folder>"` must print nothing.
   `ls "<mail folder>"/feeder-*.eml` must list at least one file.
7. Press "Fetch now" again. Confirm the file count is unchanged and no duplicate row appears on `/mail`.
8. Record the Settings block text, the file list, the grep result and the client version in a new dated evidence folder, replacing this procedure's unverified status.

If any step fails, record the exact Settings sentence and the collector cause. Do not edit the reader to make the check pass.

## Exact user-facing states

The Settings Sources card renders these strings from `src/agentdesk/server/settings_view.py`. Collector causes come from `src/agentdesk/feeder/collectors/` and the runner.

| State | What the card shows | Count shown |
|---|---|---|
| Feed off, never run | "Not run yet. The first pass runs with the next mail poll, or press Fetch now." | No |
| Healthy pass | "Collector **wpn** or **mac-notifications**", last run, result **ok**, "N alerts written into the mail folder in this fetch.", coverage "oldest to newest alert in this fetch" | Yes, N |
| Busy | "Another pass is already running; nothing new ran." | No |
| Reader unavailable (no store, no Outlook handler, Full Disk Access denied, unreadable store) | Collector **wpn** or **mac-notifications**, result **unavailable**, the reader's own cause, "No alert count is shown while the fetch is not working.", "No automatic collector is available on this machine, so the manual .eml folder above is the mail source." | No |
| No reader on this platform (manual fallback only) | Collector **manual**, result **unavailable**, the manual Save as sentence, "No alert count is shown while the fetch is not working.", "No automatic collector is available on this machine, so the manual .eml folder above is the mail source." | No |
| Collector error | The collector name, result **error**, the plain cause in an alert block, "No alert count is shown while the fetch is not working." | No |
| No mail folder | "No mail folder is configured, so the feeder has nowhere to write. Choose the mail folder in Settings." as the error | No |
| Windows, not Windows | Reader cause: "The Windows notification store is only available on Windows." | No |
| Windows, store absent | Reader cause: "No Windows notification store was found on this machine." | No |
| Windows, no Outlook handler | Reader cause: "No Outlook notification handler is registered in the Windows notification store." | No |
| Windows, store unreadable | Reader cause: "The Windows notification store could not be read." | No |
| macOS, not macOS | Reader cause: "The macOS Notification Center reader only runs on macOS. Save messages into the .eml folder instead." | No |
| macOS, store absent | Reader cause: "The macOS Notification Center database is not on this Mac, so there are no Outlook alerts to read. Save messages into the .eml folder instead." | No |
| macOS, Full Disk Access denied | Reader cause: "macOS is blocking access to the Notification Center database. Give Agent Desk Full Disk Access in System Settings > Privacy & Security > Full Disk Access, or save messages into the .eml folder instead." | No |
| macOS, store unreadable | Reader cause: "The macOS Notification Center database could not be read. Save messages into the .eml folder instead." | No |
| macOS, no Outlook app row | Reader cause: "No Outlook notifications are in the macOS Notification Center store yet. Save messages into the .eml folder instead." | No |
| macOS, Outlook app row but zero alerts | Result **ok** with 0 alerts written; the coverage line stays absent | Yes, 0 |
| Fetch wiring breaks | "The Outlook alert fetch failed: {detail}." or "The Outlook alert fetch returned no status." | No |

No gap remains in the cause path: the runner records the reader's own unavailable cause and names the reader, and the card renders that cause in its alert block. The generic manual sentence still appears alongside it as the folder fallback, which is intended. A cause-propagation gap found while drafting this note was fixed in review by commit `661c6fb` before this pack was committed.

## Discrepancies found while writing this note

Reported, not fixed, because this change is docs and evidence only.

1. **Platform-specific coverage copy on every platform.** The Settings coverage paragraph says "On Windows that is about 20 per app" unconditionally, including on macOS, against I4's rule that copy is platform agnostic except for the macOS Full Disk Access cause. File: `src/agentdesk/server/settings_view.py:1101-1103`.
2. **Comment drift in the runner.** `DEFAULT_WINDOW_DAYS = 14` is commented "# the settings choice's default, mail_feeder_days", but spec 024 says not to add a window setting and no `mail_feeder_days` exists. File: `src/agentdesk/feeder/runner.py:25`.
3. **WPN tests are platform-gated by the host, not the fixture seam.** `WpnCollector.available()` checks `sys.platform != "win32"` before looking at an injected `store_path`, so the synthetic WPN tests can only pass on Windows. The current Linux CI job runs a named subset that excludes them, so there is no live CI break, but the fixture seam is not usable off Windows the way the macOS reader's `platform=` seam is.

## Evidence and rerun commands

Evidence lives in `docs/evidence/2026-11-24-outlook-feeder/`. Run from the repository root.

```
python -m pytest tests/test_feeder_contract.py tests/test_feeder_writer.py tests/test_feeder_runner.py tests/test_feeder_platform.py tests/test_feeder_wpn.py tests/test_feeder_macos.py -q
python -m pytest tests/test_mail_core.py tests/test_mail_watcher.py tests/test_mail_store.py tests/test_mail_brief.py tests/test_server_mail_api.py tests/test_route_table.py tests/test_server_settings_api.py tests/test_server_it_surface.py tests/test_settings_concurrency.py -q
python docs/evidence/2026-11-24-outlook-feeder/synthetic_stores.py
python docs/evidence/2026-11-24-outlook-feeder/live_wpn_smoke.py
python docs/evidence/2026-11-24-outlook-feeder/capture_settings_snapshot.py
```

The expected results are in `focused-tests.txt`, `synthetic-stores.txt`, `live-wpn-smoke.txt` and `settings-capture.txt` in the same folder. The live smoke reads the real store through the collector's snapshot path, prints counts and the Outlook handler ids only, and never selects a payload. On this host it records `available=True` and 0 Outlook alerts.

## Sources

- Spec 024: `specs/024-outlook-metadata-feeder.md`.
- Wayfinder map and tickets: `docs/plans/2026-11-24-outlook-local-ingestion-map.md`, `docs/tickets/2026-11-24/`.
- Earlier repo research: `docs/research/2026-11-18-outlook-without-connector.md`.
- Local swarm notes (machine-local, outside the repo): `outlook-ingestion-research.md`, `macos-outlook-research.md`.
- Microsoft and Apple documentation links are carried in those notes; this note cites them as documentation claims rather than re-verifying them here.
