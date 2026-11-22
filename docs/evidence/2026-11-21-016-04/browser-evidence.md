# Browser evidence: 016-04 supervised agent loop

Every user-visible surface of ticket #194, captured from the branch head
(ticket/016-04-agentloop at 850b45b) booted from a fresh temp
`AGENTDESK_DATA` (`PYTHONPATH=<worktree>/src python -m agentdesk.server
--port 8766 --no-browser`), the browser signed in through the server's
own start link. Chrome 1440x900 (playwright 1.64), Node script.

Verification method: one script drove every pass (26 named checks, all
26 passed) and, at each capture, read the same-instant DOM text of the
element in the PNG, so each claim below is tied to the exact render
shown, not to a later re-reading of a changed page. The script's own
result table is summarised at the end; the API answers quoted below are
in `api-agent-loop-status.json.txt`, and the boot transcript (start-link
token redacted) is `boot-log.txt`.

## Captures

### Settings > Agent

- `settings-agent-empty-state.png`: before any pass. The same-instant
  `#agent` text contains the verbatim spec 9.3 empty state "The agent
  hasn't run yet. It runs about an hour after the app opens, or now.",
  plus "Act on its own / On" and "Check every / 1 hour".
- `settings-agent-after-runnow.png`: after pressing Run now. The pass ran
  for real: `lastRunTs` moved 1795323190.242 (startup desk check) to
  1795323190.298, and the section reads "Last pass 2026-11-21 23:53 .
  next 2026-11-22 00:53." with the lastSteps row "deskcheck ok 3ms
  failed 0, findings 1, fixed 0".
- `settings-agent-after-runnow-coforge.png` and
  `settings-agent-after-runnow-momentuum.png`: the same section and
  pass state in the other two themes (data-theme=coforge, momentuum;
  localStorage `agentdesk.theme`). With the default Unkey capture above,
  all three themes are covered on the ticket's own surface.
- `settings-agent-off.png`: after cycling Check every (1 hour -> 30 min
  -> 4 hours -> Off, each click observed). The section reads "Check every
  / Off" and "Automatic checks are off."; `/api/agent-loop` confirms
  enabled=false, intervalMinutes=0, nextRunTs=null.

### Dashboard (SPA)

- `dashboard-spa-health-line.png`: the DESK HEALTH cell (element
  capture). Its foot line reads "Agent checked at 23:53", matching the
  Run now pass.
- `dashboard-spa-coforge.png` and `dashboard-spa-momentuum.png`: the same
  cell in the Coforge and Momentuum themes, line present in both.
- `dashboard-spa-health-line-off.png`: the same cell after Check every
  Off. The "Agent checked at" line is gone while `/api/agent-loop` still
  reports lastRunTs=1795323190.298; this is ticket acceptance item 2
  ("the dashboard health line drops the 'Agent checked' text"), captured
  as-is. (Spec 9.1's literal wording says the line shows when lastRunTs
  is set; the ticket's acceptance wins. Noted under DEFAULTs in the PR.)

### Decisions empty state on a configured desk

A bare data folder shows the setup rows (Connect a workbook, Connect
your calendar, Ask your first question), not the empty state, so the
script configured the desk through the app's own routes first: a fixture
workbook via POST /sources/excel-watch (plus retest), a fresh calendar
document via POST /sources/calendar-bridge/path (state healthy), and one
research question via POST /research against an in-process mock OpenAI
compatible endpoint. The desk reached that endpoint through its normal
research path; nothing about it ships in the product.

- `dashboard-spa-decisions-empty-off.png`: the DECISIONS cell (element
  capture) with Check every Off. Same-instant text: "DECISIONS 3/3
  sources Automatic checks are off."
- `dashboard-spa-decisions-empty-on.png`: the same cell after turning
  checks back on (1 hour). Same-instant text: "DECISIONS 3/3 sources
  Nothing needs a decision. The desk checks again at 12:53 AM." The
  health line also returns on the dashboard, and `/api/agent-loop`
  reports enabled=true, intervalMinutes=60, nextRunTs=1795326790.298.

## Anomalies / notes

- The loop's startup desk check fires about 5 s after boot
  (`STARTUP_DELAY = 5.0`), so the true empty state exists only in that
  window. It was captured by racing a fresh boot: sign-in and the
  /settings request completed ~1.5 s after the start link printed, and
  the same-instant DOM text proves no pass had run yet.
- A full pass in this bare environment runs exactly one step: deskcheck.
  Other steps are simply not registered/enabled yet, not failing.
- The SPA logs one console error, a 404 on /favicon.ico (cosmetic,
  unrelated to this ticket).
- The dashboard is a React SPA; `dashboard-spa-*` captures are element
  screenshots of the cell that carries the changed text, so the on/off
  pair differs exactly by the intended line (341 px vs 299 px tall).
