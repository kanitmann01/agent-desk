# I2: The Windows notification-store reader

Part of specs/028-outlook-metadata-feeder.md (G2, G4, G5). Blocked by: I1.

## Context

Windows persists every toast in the per-user WPN store at `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db` plus `-wal` and `-shm`. Both Outlook clients raise new-mail and reminder alerts through it. The live probe on this machine found 33 toast rows, 36 condensed rows with null payloads, a 20-toast cap per app, and the new Outlook handler `Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows`. The toast XML carries sender, subject and a preview line. This is a live-alert source, not a mailbox mirror.

## Scope

- Add `src/agentdesk/feeder/collectors/wpn.py`.
- Snapshot the live store with the `sqlite3` backup API; if that fails, copy `db`, `-wal` and `-shm` together and open the copy. Never write the live store.
- Keep rows where the handler `PrimaryId` starts with `microsoft.outlookforwindows` or `microsoft.office.outlook.exe`, `Type` is `toast`, and `PayloadType` is `Xml`.
- Parse the toast XML, keep at most the first two `<text>` nodes, and drop every later node. Flatten, strip CR/LF, and cap each field.
- Map to `agentdesk.mail.core.Message`: sender is the first line, subject is the second when present. Synthesize a stable id from the handler and notification id. Set `date_ts` from the FILETIME arrival. Leave `to`, `cc` and `in_reply_to` empty; set `thread` from the subject.
- Dedupe on the source app and notification id. A second pass over the same store writes nothing.
- `available()` is false off Windows, when the store is absent, or when no Outlook handler exists. The cause names the missing piece.
- Tests in `tests/test_feeder_wpn.py` build a synthetic store with the real schema, with one Outlook mail toast carrying a sentinel preview, one Outlook reminder, one non-Outlook toast, one condensed row, and one duplicate. Assert the mail and reminder mapping, the preview sentinel absent from every output, the second pass empty, the FILETIME conversion, and the no-Outlook-handler cause. No test touches the live store.
- Optional live smoke: run the reader against the real store and record counts and handler ids only, never payload text.

## Acceptance

The focused tests pass; a synthetic store produces header-only messages; the preview line never reaches a file; the reader contains no COM, no network and no model import.

## Resolution (2026-11-24)

Resolved. `src/agentdesk/feeder/collectors/wpn.py` snapshots the live store with the SQLite backup API and falls back to copying `db`, `-wal` and `-shm` together. It filters to Outlook handler rows, `Type = "toast"` and `PayloadType = "Xml"`, keeps at most the first two text nodes, drops the preview, and maps the FILETIME arrival. The synthetic suite covers the mapping, the preview sentinel, the handler filter, the limit, stable reruns and the no-handler cause: 3 Outlook messages from 5 rows, 3 files, 3 after a rerun. The live smoke on this host records one Outlook handler and 0 Outlook toast rows, so there is no live alert to read; `available=True` and `collect` returns 0. Tests are Windows-gated by `sys.platform` even with an injected store, which is recorded as a discrepancy.
