INSTRUMENT FAULT

# Scope note

This classification is about the two pending-page errors, not about the separate old-main calendar crash. The pending errors are an instrument fault because the pending path does not reproduce the calendar page that the matrix path deliberately fixtures. The underlying `IndexError` is a real old-UI defect and is recorded separately below.

## 1. The two pages and the cause

The matrix has no field named `seed`; its `condition` selects the seed performed by `_seed`. Both affected rows are width `1280`, theme `unkey`, stress `false`, route `/walkthrough/calendar`, state `walkthrough-calendar`.

- Fresh: condition and seed `fresh`, with no sample-data seed (`tools/layout_audit.py:2396-2400`). Matrix evidence: `walks/before-pending/20261126-202440/matrix.json:533-545`. The matrix photograph `fresh/1280x800/unkey/walkthrough_calendar__walkthrough-calendar.png` shows the intended "Connect your calendar" page, including Power Automate instructions, the discovered `calendar_sync.json` path and sample JSON, "Pick a file", "Reset to automatic discovery", a path field, "Choose File", "Upload this file", "Use this path", and "Check for calendar data now". It is not a page with nothing to act on.
- Plugins: condition and seed `plugins`, with registry plugins installed but sample data still off (`tools/layout_audit.py:2401-2407`). Matrix evidence: `walks/before-pending/20261126-202440/matrix.json:1149-1161`. The matrix photograph `plugins/1280x800/unkey/walkthrough_calendar__walkthrough-calendar.png` shows the same intended setup page and the same visible controls, with the plugins-seeded rail and Inbox count.

There is no pending photograph for either failed page. The zero-control record has an empty screenshot field (`tools/layout_audit.py:3190-3201`), and the zero-control branches append that record without taking a screenshot (`tools/layout_audit.py:3263-3277`).

The emitting branch is explicit: `_pending_controls` enumerates visible `button`, `[role="button"]`, submit and button inputs (`tools/layout_audit.py:60,2824-2826`); `_pending_zero_control_record` treats every unmarked zero-control page as `error` with reason `page yielded no controls to click` (`tools/layout_audit.py:3204-3218`); `_pending_coverage_failures` turns that error into the reported coverage failure (`tools/layout_audit.py:4513-4536`). The branch itself does not establish that the intended page had no controls.

The cause is the fixture mismatch:

- `_pin_environment` pins `AGENTDESK_CALENDAR_FILE` to an empty value (`tools/layout_audit.py:2067-2081`).
- `_measure_combo` temporarily sets it to the audit calendar fixture for `calendar_fixture` views, then clears it (`tools/layout_audit.py:3679-3682,3784-3788`). That is why the matrix photographs show the full setup page.
- `_run_pending_audit` receives no calendar-fixture argument and navigates directly to the route (`tools/layout_audit.py:3221-3228,3243-3247`). `_condition_worker` passes the fixture only to `_measure_combo`, not to `_run_pending_audit` (`tools/layout_audit.py:3887-3906`).

With the environment still empty, fresh and plugins reach old main's calendar-hint bug. `default_calendar_candidates` returns an empty list for an explicitly empty environment value (`src/agentdesk/calendar/watcher.py:74-90`), and `default_calendar_hint` indexes `candidates[0]` (`src/agentdesk/server/app.py:8380-8395`). The server logs show that exact `IndexError` for fresh (`walks/before-pending/20261126-202440/server-stderr.fresh.log:56-72`) and plugins (`walks/before-pending/20261126-202440/server-stderr.plugins.log:1-17`). `do_GET` converts it to a 500 error page (`src/agentdesk/server/app.py:1350-1362`), and that page contains only a title and message, not controls (`src/agentdesk/server/app.py:6886-6895`). The pending enumeration therefore truthfully finds no buttons on the rendered 500 page, but it has failed to reproduce the intended matrix page. That is an instrument fault, not a legitimate old-UI zero-control state.

The full seed avoids the empty hint because sample data supplies an explicit sample calendar path. The full matrix photograph `full/1280x800/unkey/walkthrough_calendar__walkthrough-calendar.png` shows that sample path, and the full pending pass records six real controls (`walks/before-pending/20261126-202440/summary.md:1774-1779`). The photographed pending result `pending/full/1280x800/unkey/walkthrough_calendar__walkthrough-calendar__435.png` visibly shows "Pick a file" and "Back to automatic discovery", confirming that the selector can see controls on this page.

## 2. Validity of the remaining evidence

Yes, with a strict scope limit. The layout matrix remains valid evidence: 130 planned rows, 129 measured, one legitimate overlay skip and zero failed matrix rows (`walks/before-pending/20261126-202440/summary.md:7-12,43-49`). The other pending records, including the full calendar controls, remain evidence for the pages they actually rendered. The two affected pending combinations are not valid control-coverage evidence; they are evidence of the pending fixture omission and the resulting old-main 500. The pass as a whole is not a complete 130-page pending pass. The 1,328 photographs have been counted but not yet visually reviewed (`evidence/2026-11-25-main-audit/before-run-record.txt:73-77`), so final visual acceptance is still outstanding.

## 3. Runbook consequence and proposed narrower stop rule

Readiness met the exact gate, exit 0 with 27 passes and `METRIC ready=27` (`evidence/2026-11-25-main-audit/before-run-record.txt:27-38`), so command 2 was allowed to start and did start. A rerun is not allowed under the current hard stop, and the runbook also forbids rerunning merely for nicer numbers (`runbook/walk-before.md:183-195`). Photograph review is not another walk: it may and must proceed. Record the two pending errors as an instrument fault, and separately record old main's empty-candidate `IndexError` as a product defect. Do not record them as two genuine old-UI states with no controls.

Exact proposed replacement sentence for the pending-walk hard-stop bullet at `runbook/walk-before.md:190`:

> Stop and report without starting another walk when the pending walk exits 2, leaves a child failure, or prints `COVERAGE INCOMPLETE` for any reason other than a reviewer-confirmed finding about the audited application; for that exception, preserve the evidence, complete the photograph review, record the finding, and continue only under the audit coordinator's direction.

No runbook was changed.

## 4. Readiness traceback

Defect to triage, not a harmless message: `walks/before-ready/readiness.log:12-28` is the same old-main `default_calendar_hint` empty-candidate `IndexError` that produced the fresh and plugins 500 pages; 27 passing readiness checks do not erase that server defect.
