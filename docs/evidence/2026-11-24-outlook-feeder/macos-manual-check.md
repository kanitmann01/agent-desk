# macOS manual check: Outlook alerts into the mail folder

Status: **UNVERIFIED procedure.** No Mac was used for this evidence pack. This file is a procedure to run later and record, not a result. Do not treat macOS automatic collection as verified until a dated transcript replaces this note.

Date written: 2026-11-24. Applies to: spec 028 (numbered 024 in the agent-desk-core sandbox when written), the macOS Notification Center reader in `src/agentdesk/feeder/collectors/mac_notifications.py`.

## What this check proves

- The macOS Notification Center reader can see Outlook alerts on a real Mac after Full Disk Access is granted.
- Only the title and subtitle lines reach the mail page and the generated `.eml` files.
- The body canary never appears in a file, a status or the app.
- A second Fetch now adds no duplicate.
- The Settings card tells the truth about the collector and the coverage window.

## Preconditions

- A work Mac with Outlook installed, signed in, and allowed to post notifications.
- Python 3.10 or newer, and the repository checked out. The macOS package is not built; run from source.
- Permission to change Full Disk Access for the terminal or launcher used to start the app. If MDM blocks the toggle, record that and stop; the manual `.eml` folder is the only path on that machine.

## Procedure

1. Record the client: open Outlook and note whether it is new Outlook or legacy Outlook for Mac, plus the version string. Record the macOS version.
2. Open System Settings > Privacy & Security > Full Disk Access. Add the terminal app or the Python launcher that starts the server, and switch it on.
3. From the repository root, start the app with `python -m agentdesk.server --no-browser`.
4. Open the dashboard, go to Settings, and set the mail folder to an empty local folder (for example `~/agent-desk-mail-test`). Turn on "Fetch Outlook alerts". That toggle also turns on the mail digest, because the alert files land in the same folder.
5. Send a self-addressed test message from another account or from Outlook on the web. Use a unique subject token such as `AGENTDESK-MAC-TEST-1` and a body canary such as `BODY-CANARY-DO-NOT-STORE`. Wait until the Outlook notification appears in Notification Center.
6. In Settings, press "Fetch now". Record the exact block text: the collector name, last run, result and any cause.
7. Open `/mail` and confirm the subject token appears. Confirm the body canary appears nowhere on the page.
8. In Terminal, run these checks against the mail folder and the status file:
   - `ls "<mail folder>"/feeder-*.eml` lists at least one file.
   - `grep -R "BODY-CANARY-DO-NOT-STORE" "<mail folder>"` prints nothing.
   - `grep -R "BODY-CANARY-DO-NOT-STORE" ~/.agent-desk/outlook-feeder.json` prints nothing.
9. Press "Fetch now" a second time. Confirm `ls "<mail folder>"/feeder-*.eml | wc -l` is unchanged and `/mail` shows no duplicate row.
10. Record in a new dated folder under `docs/evidence/`: the macOS and Outlook versions, the Settings block text, the file list, the grep output (empty), the file count before and after the second fetch, and the exact date and time.

## Expected result on a working Mac

- Collector `mac-notifications`, result `ok`, at least one alert for the subject token, and a coverage line from the oldest to the newest alert in the fetch.
- The generated file is header-only: `From`, `Subject`, `Date`, `Message-ID` and no bytes after the blank line.
- The body canary appears in no file, no status and no page.

## If it fails

Record the exact Settings sentence and the reader cause. Do not edit the reader to make the check pass. One known copy gap in the current build: the coverage paragraph in Settings always says "On Windows that is about 20 per app", including on macOS. Record it if it appears.
