# I3: The macOS Notification Center reader

Part of specs/028-outlook-metadata-feeder.md (G3, G4, G5). Blocked by: I1.

## Context

macOS stores delivered notifications in a per-user SQLite database at `~/Library/Group Containers/group.com.apple.usernoted/db2/db` plus WAL sidecars. The `app` table holds `app_id` and `identifier` (bundle id); the `record` table holds `uuid`, `app_id`, `data` (a binary property list), and delivery dates. Outlook alerts appear there like any other app's. New Outlook for Mac has no AppleScript support and is not indexed by Spotlight, so this is the only automatic local source for it. Reading the database requires Full Disk Access, a per-app user consent.

## Scope

- Add `src/agentdesk/feeder/collectors/mac_notifications.py`.
- Copy `db`, `db-wal` and `db-shm` together to a temporary directory and open the copy read-only. Never open the live file for writing.
- Join `record` to `app`, filter `app.identifier` to the Outlook bundle id or ids the research note confirms, and order by delivery time.
- Parse `record.data` with `plistlib`. Keep the title and subtitle only; drop the body and every other key. Flatten, strip CR/LF, and cap each field.
- Map to `agentdesk.mail.core.Message`: the title is the sender when it looks like a sender, the subtitle is the subject. If the layout is ambiguous, keep the two lines and mark the record as an alert so the card does not overclaim. Synthesize a stable id from the bundle id and record uuid. Set `date_ts` from the delivery date. Leave `to`, `cc` and `in_reply_to` empty.
- Dedupe on the bundle id and record uuid. A second pass writes nothing.
- `available()` is false off macOS, when the store is absent, or when the process cannot read it. The cause distinguishes "Full Disk Access not granted" from "no Outlook notifications yet".
- Tests in `tests/test_feeder_macos.py` build a synthetic `db2/db` with the `app` and `record` tables, three records (Outlook mail with a body sentinel, Outlook calendar reminder, non-Outlook chat), and parse the plists with `plistlib`. Assert mapping, the body sentinel absent, the second pass empty, the permission cause, and the no-Outlook-records cause. Tests skip on non-darwin only where a platform call is required; the parser tests run everywhere.
- A manual Mac check is recorded in I5 as a procedure, not as a claimed result.

## Acceptance

The focused tests pass; a synthetic store produces header-only messages; the body sentinel never reaches a file; a missing Full Disk Access returns an honest cause; the reader contains no AppleScript, no network and no model import.

## Resolution (2026-11-24)

Resolved against synthetic stores. `src/agentdesk/feeder/collectors/mac_notifications.py` copies `db`, `db-wal` and `db-shm` together, opens the copy read-only, joins `record` to `app`, filters the Outlook bundle ids, and reads only the title and subtitle keys from the plist. Body, preview and unknown keys are never read. The synthetic suite maps 2 Outlook records out of 3, keeps all three body sentinels out of every file, returns the Full Disk Access cause on `PermissionError`, treats a readable store with an Outlook app row and zero records as available with an empty collect, and proves rerun stability. A real Mac was not used; the manual procedure is recorded as unverified in `docs/evidence/2026-11-24-outlook-feeder/macos-manual-check.md`. A cause-propagation gap in the runner was fixed in review by commit `661c6fb`, so this reader's Full Disk Access cause now reaches the status.
