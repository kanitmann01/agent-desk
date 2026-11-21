# Evidence: ticket 017-05, sources correctness (spec 017 workstream 5)

Captured on 2026-11-21 from the ticket branch, on a machine whose local
zone was UTC-5. Every run below boots the real server over a fresh temp
`AGENTDESK_DATA` (hermetic: the real `~/.agent-desk` is never touched),
drives it exactly as a browser would (the bootstrap token exchange, then
real chromium for the screenshots), and serves the no-JS dashboard, the
server-rendered surface the fixed widgets live on (the same stance the
test suite's conftest takes).

## 1. Calendar: a UTC-written early meeting counts for today, at the local clock time

`calendar-utc-early-meeting-local-time.png`: the commitments card.

- The temp data dir carried a `calendar_sync.json` whose `generatedAt`
  and every event time use the UTC shape the sync flow writes (trailing
  `Z`).
- The seeded early meeting is at 00:30 local; the file stores it as
  `2026-11-21T05:30:00Z` (the same instant).
- The card shows the meeting as today's key commitment at `00:30`, the
  machine's local clock time, not `05:30` (the file's UTC hour). The
  widget payload recorded during the capture:
  `keyEvent.start = 2026-11-21T00:30:00-05:00`, `state = healthy`.
- Before the fix the same file rendered `05:30` and, east of UTC, the
  meeting dropped off today entirely.

## 2. Workbook: a malformed workbook lands in the amber state with a named cause

`workbook-amber-named-cause.png`: the sales card.

- A genuine fixture workbook whose first shared-string cell points past
  the table (`t="s"`, index 999) sat at the path the watch was
  registered against: zip-valid, parse-torn.
- `POST /sources/excel-watch` answered 200 with `state = unreadable`
  and the cause `Can't read the workbook: the worksheet could not be
  parsed: list index out of range. Check it is a valid .xlsx.`
- The dashboard renders that cause on the amber card with the Re-test
  button. No 500 page, no "Something broke".

## 3. Picker-only connect flow: the typed-path form is gone

`picker-only-transcript.txt` is the recorded transcript (plus
`picker-only-failure-note.png`, the live failure note). It shows:

- `GET /` carries the `data-pick` button and the `pick-note` amber slot,
  and contains no `manual-connect` form, no `workbook-path` input, no
  typed-path copy.
- `POST /sources/excel-watch/pick` (the native dialog standing in as
  one that did not open) answers `{"path": null}`.
- The page script's failure note is the honest one ("The file dialog
  did not open. Try Connect a workbook again; if it keeps failing,
  restart the app."), with no manual-connect handler and no
  "Type the workbook path" copy anywhere in `pages.APP_JS`.
- A live click on the connect button surfaced exactly that note on the
  card.

## Reproducing

1. `git checkout ticket/017-05-sources-correctness`.
2. Boot the server over a temp data dir
   (`AGENTDESK_DATA=<temp> python -m agentdesk.server --no-browser
   --port 8765`), open the start link from stdout.
3. For the calendar case, set `AGENTDESK_CALENDAR_FILE` to a
   `calendar_sync.json` whose event times carry the trailing `Z`.
4. For the workbook case, register a torn workbook (a zip-valid .xlsx
   with a shared-string index past the table) through
   `POST /sources/excel-watch`.
5. Screenshots: chromium over the token URL, element shot of the card
   (`[data-widget-id="key-commitment"]`, `[data-widget-id="sales-24h"]`).
