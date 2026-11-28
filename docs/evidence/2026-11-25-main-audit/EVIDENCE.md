# Evidence pack: audit of the UI wave on main (specs 026, 027, 029)

Parent issue: #320. This pack commits the audit's written records: the findings
register, its per-partition findings and confirmations, the BEFORE and AFTER
walk records, and the reviews of every fix pull request. Photographs and raw
walk JSON trees stay in the off-repository audit workspace; only their text
records (counts, verdicts, photograph listings, nonpass reviews) are committed.

## Pinned commits

| What | Commit |
| --- | --- |
| Audited application commit (BEFORE, old main) | `f31582a2591e1c860ec5aadf5e0ff3878d77cc49` |
| Audit instrument commit (AFTER, main at audit time) | `b39669491b965ef6c6624903db30e0b9df552004` |
| Slow run main (later main during the audit) | `3f099e0` |
| Audited worktree | `.worktrees/before-main` (BEFORE), `.worktrees/audit-after-main-b396694` (AFTER) |

BEFORE is old main measured by the new instrument. The three instrument paths
(`tools/layout_audit.py`, `tools/mock_endpoint.py`, `tools/layout_fixtures/`)
were copied into the BEFORE worktree uncommitted; `git status` there showed
exactly those three paths (`before-run-record.txt`, PREPARATION section). Nothing
in that worktree was committed or pushed.

## Gate and walk numbers, one table (from the closeout record)

| Pass | BEFORE, f31582a | AFTER, b396694 |
| --- | --- | --- |
| Readiness | `METRIC ready=27`, 0 FAIL | `METRIC ready=27`, 0 FAIL |
| Layout matrix | 130 rows in the pending matrix, 129 measured, 1 overlay skip, 0 failed | 1,040 planned, 1,028 measured, 12 overlay skips, 0 failed; 0 findings outside the 11px class; 0 broken words; 40 stress findings all table cells in their own scroller; 0 rejected |
| Pending | 129 of 130 pages; 1,299 controls; dead 194, silent 188, disabled-only 49, meets 6, instant 558, skipped 280, native-dialog 11, native-validation 11, error 2, box-changed 3 | 129 of 130 pages; 1,255 controls; dead 6, silent 15, disabled-only 0, meets 207, instant 733, skipped 270, native-dialog 13, native-validation 11, error 0, box-changed 3 |
| Feedback | not run | 7 actions; met 4, not-met 1, absent 2; 15 of 21 photographs; exit 1 |
| Face | not run | 72 of 108 planned photographs; 8 moods; two themes; exit 1 |
| Slow run | not run | exit 0 at 3f099e0; 129 of 130 combinations; 0 failed |
| Selftest | `SELFTEST PASS 16 detector expectations, 4 box expectations, 10 pending expectations` | same instrument |

Key files: `before-run-record.txt`, `before-selftest.txt`,
`before-pending-metric.txt`, `before-pending-coverage.txt`,
`before-pending-skipped.txt`, `before-readiness-metric.txt`,
`after-run-record.txt`, `after-pending-metric.txt`,
`after-pending-verdicts.txt`, `after-pending-nonpass.json`,
`after-layout-*.txt`, `after-feedback-*.txt`, `after-face-*.txt`,
`after-slow-*.txt`, `after-readiness-*.txt`.

## The findings register (issue #325)

`findings.md` and `findings.json` are the register, compiled from seven
reviewer partitions (P1 to P7) with independent confirmations for the P0 and P1
findings where a confirmer was available. No repository file was changed by any
reviewer; reviewers were read-only and their outputs are these files.

- Counts by final severity: P0: 1, P1: 16, P2: 19, P3: 18. Total: 54.
- Counts by verdict: confirmed 27, narrowed 5, refuted 0, unchecked 22.
- Per-partition files in `findings/`: `P1` to `P7` findings and
  `confirmations-P1` to `confirmations-P6`.
- Nonpass reviews of every walk in `reviews/`: pending, pending rerun, layout
  groups, feedback, face; plus the BEFORE exit-3 analysis.

### Where each finding went

| Destination | Findings | PR |
| --- | --- | --- |
| audit-3a instrument safety (#346) | P5-01 (P0), P5-02, P5-03, P5-04 | #349 |
| audit-3b inert runners (#350) | PR349-R4 | #369 |
| audit-3c face walk script (#351) | instrument | #352 |
| audit-3d slow run delay (#366) | instrument | #367 |
| audit-1 small fixes (#323) | pre-audit small fixes | #345 |
| Sample client name (founder item P7-01) | settled | #348 |
| New P1 F1 and F3 (marketplace search, disabled primary) | fixed | #370 |
| Stale stamp, day name | fixed | #371, #372 |
| spec 030 ticket 030-6 (#334) | P1-02 | in flight |
| spec 030 ticket 030-7 (#335) | P1-03, P2-07, P3-06 | in flight |
| spec 031 ticket 031-1 (#337) | P4-03 | in flight |
| rename spec 032 | P7-02 | #381-#390 |
| Superseded on main | P1-01, P6-01 | on main |
| audit-5 fix round (#327) | P1-04, P1-05, P2-01, P3-01, P3-02, P3-05, P4-01, P4-02 | see #327 |
| Triage, issue #328 | 33 findings | closed 2026-11-27 |

The feedback review's three items became: `dashboard-research` instrument
verdict fix, `dashboard-reply` fixture gap, and `inbox-draft`, filed as #380.
The BEFORE exit-3 fixture fault was filed as #368.

## Issue mapping

- Issue #324 (audit-2): the pinned commits, the gate numbers, the BEFORE walk
  record and the copied-paths statement are in this pack.
- Issue #325 (audit-3): `findings.md`, `findings.json`, the seven partitions,
  the confirmations and the coverage counts are in this pack.
- Issue #327 (audit-5): the fix round's own record lives with that issue; the
  register's destination column and the PR table above are the index.
