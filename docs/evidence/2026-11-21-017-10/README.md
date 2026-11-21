# 017-10 frontend fixes: evidence

Captured against the rebuilt SPA served by `python -m agentdesk.server` from
this branch, with a temp `AGENTDESK_DATA` directory, via playwright-cli.
The desk had the bundled `excel-report` (Workbook tracker) plugin installed
and unconfigured, so its card was on the dashboard.

## 10a: Customize hide applies to the normal view

- `10a-1-normal-view-plugin-card-present.png` - the normal dashboard (the
  Brief) with the Workbook tracker plugin cell visible.
- `10a-2-customize-before-hide.png` - Customize mode showing the card's
  controls (drag handle, Move, Rename, Hide).
- `10a-3-customize-card-hidden.png` - after pressing Hide: the card is gone
  from the grid and listed in the Hidden cards strip with Restore.
- `10a-4-normal-view-card-gone.png` - after Done customizing: the normal
  view no longer shows the card, and the "Add tracker" placeholder did not
  come back (a tracker exists, it is just hidden).

## 10b: the setup sheet degrades visibly when the server is unreachable

- `10b-setup-sheet-server-stopped.png` - the tracker setup sheet with the
  server process stopped and "Open a workbook" pressed: the error slot
  carries the honest sentence ("The dashboard could not reach its own
  server; the workbook was not opened.") and the sheet's buttons stayed
  operable instead of wedging disabled.

## 10c: the destructive dialogs carry the consent sheet focus contract

- `10c-dialog-first-control-focus.png` - the Uninstall dialog on the
  Installed page, focus (with ring, after keyboard use) on its first
  control, Cancel.
- `10c-dialog-transcript.txt` - the playwright transcript: Enter opens the
  dialog and focus moves in; Tab cycles inside and wraps at both ends;
  Escape closes it and focus returns to the Uninstall button that opened
  it.
