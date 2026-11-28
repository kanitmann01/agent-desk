# Audit closeout record, 2026-11-26

Repository `kanitmann01/agent-desk`. Audit parent is issue 320. This record states the audit's result, where each finding went, and the criteria of issues 326 and 328 one by one. It changes no code, starts no test, gate, build or instrument, and touches no pull request.

## 1. The numbers

| Pass | BEFORE, f31582a | AFTER, b396694 |
| --- | --- | --- |
| Readiness | `METRIC ready=27`, 0 FAIL | `METRIC ready=27`, 0 FAIL |
| Layout matrix | not run; the pending command's matrix recorded 130 rows, 129 measured, 1 overlay skip, 0 failed | 1,040 planned, 1,028 measured, 12 overlay skips, 0 failed; 0 normal findings outside the 11px class, 0 broken words, 40 stress findings all `td` or `th` inside `div.table-scroll`, 0 rejected |
| Pending | 129 of 130 pages; 1,299 controls; dead 194, silent 188, disabled-only 49, meets 6, instant 558, skipped 280, native-dialog 11, native-validation 11, error 2, box-changed 3 | 129 of 130 pages; 1,255 controls; dead 6, silent 15, disabled-only 0, meets 207, instant 733, skipped 270, native-dialog 13, native-validation 11, error 0, box-changed 3 |
| Feedback | not run | 7 actions; met 4, not-met 1, absent 2; 15 of 21 photographs; exit 1 |
| Face | not run | 72 of 108 planned photographs; 8 moods; theme one 36, theme two 36, theme three 0; 4 failed rail reading captures; exit 1; no visual verdicts |
| Slow run | not run | exit 0 at 3f099e0, a later main than b396694; 129 of 130 combinations measured, 1 overlay skip, 0 failed; 1,261 controls; dead 6, silent 15, disabled-only 0; METRIC recorded; the four-second delay configured but not exercised |

BEFORE is old main measured by the new instrument. The 2 missing pages are fresh page 36 and plugins page 36, an instrument fixture fault recorded as issue 368. BEFORE produced 1,328 photographs. They were counted and listed, and not read except the pages the exit 3 analysis examined, by the founder's cost decision.

Pending side by side: dead 194 to 6; silent 188 to 15; disabled-only 49 to 0; meets 6 to 207. Of the 6 dead, 3 are the empty marketplace Search and 3 repeat the same watch query and result, which is expected. The 15 silent are expected feedback from themes, a dismissed setup, dialogs, menus and validation, per the photograph review. None of the 15 is recorded as a product defect.

## 2. Where each finding went

| Destination | Findings |
| --- | --- |
| audit-3a, issue 346, merged | P5-01 (P0), P5-02, P5-03, P5-04 (P1). The instrument now injects inert runners and holds every non-GET; PR 349 |
| P0 and P1 round, issue 327, open | P1-04, P1-05, P2-01, P3-01, P3-02, P3-05, P4-01, P4-02, plus new P1 F1 (empty marketplace Search, rows 13, 305 and 714) and new P1 F3 (disabled `Fill it in for me` looks enabled, row 1245). F2 is P3-01 |
| spec 030 | P1-02 to 030-6, issue 334; P1-03, P2-07 and P3-06 to 030-7, issue 335 |
| spec 031 | P4-03 to 031-1, issue 337 |
| rename spec 032 | P7-02 |
| superseded on main | P1-01 and P6-01 |
| founder | P7-01, settled by issue 347 |
| audit-3b, issue 350 | PR349-R4; PR 369 merged as `0132531` and issue 350 closed |
| triage, issue 328 | 33 findings: P1-06, P1-07, P2-02 to P2-06, P3-03, P3-04, P3-07 to P3-09, P4-04 to P4-06, P5-05, P6-02 to P6-15, P7-03 to P7-05 |

The feedback review adds three items. `dashboard-research` is an instrument mislabel: the result verdict must require `not result.busy`, not `result.idle`. `dashboard-reply` is an instrument fixture gap: the full seed installs no digest card with a reply-draft press. `inbox-draft` is an unbuilt feature: no waiting card offers a model-backed draft, so it needs a ticket or a change to the seven-action acceptance.

The triage list also holds these items found after the register was compiled. Issue 368, the pending calendar fixture. The PR 367 ponytail remark: a research-only flag would be smaller than the repeatable path option. The readiness tool's extra desk boots: the two readiness tests boot three desks on every gate run. The `Fill it in for me` wording conflict: issue 326 says `skipped`, its newer comment says the disabled reading, and the instrument emits `skipped`. The instrument limits in section 6. The old UI's empty-calendar crash, fixed on main by f134f89dc in PR 319. Main moving during the audit by PR 365 (merge 0f290287) and PR 367 (merge 3f099e0), while the AFTER evidence stayed pinned at b396694 and the slow run moved to 3f099e0.

## 3. The criteria of issue 326, one by one

1. Layout matrix: met. 1,028 of 1,040 combinations measured, 12 overlay skips, 0 failed. Zero findings outside the 11px class with real and long strings, zero broken words, 40 stress findings all table cells inside their own scroller, 0 rejected. The photograph review read 167 files, accepted all 45 groups and confirmed all 12 skip reasons.
2. Pending walk: not met. The METRIC line ends `dead=6` and the table shows `silent=15`; `disabled-only=0` passes. Three dead are F1; three are same-query repeats; all 15 silent are expected.
3. The four named controls: `Ask me first` is met (meets, fresh page 22, request started). Research with no question is met (already disabled, four records). `Fill it in for me` with an empty description is met as recorded (skipped, reason already disabled, never dead), with the wording conflict above and the P1 styling defect F3 in issue 327. Copy digest is not met: 12 instant and 2 skipped, automatic clipboard copy fails in the walk, and the photographed fallback gives manual-copy instructions, so success is not recorded.
4. Feedback walk exits 0 with all seven actions and three photographs each: not met. Exit 1, four met, one not-met (an instrument mislabel), two absent (one fixture gap, one unbuilt feature), 15 of 21 photographs.
5. Slow run: met as written, with the delay limit. Exit 0 at 3f099e0; 129 of 130 combinations measured, 1 overlay skip, 0 failed; the run folder and METRIC line are recorded; dead=6 and silent=15 are the same findings as the normal pending pass. No control met the four-second delay, because the full dashboard's Research is disabled without a question and no research request was sent, so the run does not evidence delayed behaviour.
6. Face walk: not met. 72 of 108 planned photographs; eight moods in the first two themes only; the run's third theme name did not match the product's theme id, so that theme produced zero captures; four rail reading captures failed because no non-fresh plugin card offered `Re-test now`; no visual verdicts.
7. Every photograph produced has a verdict in `photographs.md`: not met. No `photographs.md` exists. The 1,328 BEFORE photographs are unread by the founder's cost decision; the reads cover 167 layout, 144 pending and 15 feedback files; 943 layout, 1,256 pending, 72 face and 1,262 slow-run photographs are not all read.
8. Every visible defect seen in a photograph is a finding: not met as a whole. The reads recorded F1, F2 and F3 and no layout defect, but the unread photographs mean completeness cannot be claimed.
9. The AFTER numbers stand next to BEFORE in one table: met in section 1 of this record. The evidence pack on main still does not carry it.

## 4. The criteria of issue 328, one by one

1. Every P2 and P3 finding is a GitHub issue with its severity, evidence and one label: not met. The 33 P2 and P3 findings are only in the register and none has an issue. F1 and F3 (P1) and the three feedback items have no issue either.
2. README describes seven pending verdicts: not met. The root README at b396694 has no pending verdict list at all, and P6-03 still stands.
3. Both `docs/evidence/2026-11-24-*/EVIDENCE.md` files carry the exact commands: not met. Both summarize counts and name `tools/ci_local.py`, but neither carries the exact typecheck, vitest, bundle rebuild, readiness and gate commands. P6-07 still stands.
4. Ticket 09 is closed, its `Partly` line resolved by the slow run, status `done`, every box ticked with a `Verified:` line: not met, no longer waiting. The slow run is recorded, so the `Partly` line can be resolved; ticket 09 is still `in progress`, its `Partly` line unresolved, and its boxes not ticked.
5. Spec 029 has its issue, its status names that issue and this audit, and its six tickets are ticked or re-triaged: not met. There is no spec 029 issue; the status is `ready-for-agent (2026-11-24)` with no audit record; the six ticket files under `docs/tickets/2026-11-24-nexuus-face/` are `ready-for-agent` with every box unchecked.
6. The status lines of specs 026 and 027 name the audited commit: not met. 026 names `3d942ed`; 027 names no commit; neither names the audited commit.
7. `docs/design-language.md` and `DESIGN.md` carry the two face exceptions and the token suite pins them: not met. Neither file carries the shape-motion exception or the face-as-the-one-filled-mark exception.
8. `GLOSSARY.md` has the agent's name entry: not met. There is no `Nexuus Bot` entry.
9. `docs/licensing.md` states the presentation plugin's Apache-2.0 licence: not met. The file still says the in-box plugins are MIT; `registry/plugins/presentation-starter/manifest.json` and its `LICENSE` are Apache-2.0.
10. The evidence pack is complete and linked from the parent issue: not met. `docs/evidence/2026-11-25-main-audit/` is absent from main, and the pack exists only in the scratch workspace.

## 5. What stays open, and why

Issue 323 was already done before this record. No other audit issue qualifies.

- Issue 320 closed on 2026-11-27 with its `CLOSED ON THE RECORD (2026-11-27)` comment: it is the parent, and children 324, 325 and 327 stay open.
- Issue 324 stays open: the BEFORE pending pass measured 129 of 130 pages; the two page errors are the fixture fault in issue 368; the pack holds no gate and no two-build baseline record for the audited commit.
- Issue 325 stays open: P7-02 (P1) has no independent confirmation; the compiled register has no per-partition coverage counts and no checked-and-found-correct section that the criterion names; the register is not in the evidence pack.
- Issue 326 stays open: criteria 2, 4, 6, 7 and 8 are not met.
- Issue 327 stays open: the re-walk has dead=6 and silent=15, F1 and F3 are new, and the feedback walk exits 1.
- Issue 328 stays open: criteria 1, 2, 3, 5, 6, 7, 8, 9 and 10 are not met, and 4 is no longer waiting on the slow run but is still not met.

This record closes no issue and no pull request, and it changes no file in the repository.

## 6. Instrument limits, and what cannot be met as written

- Native dialogs: the picker is outside the screenshot; the visible `Opening` or `Working` feedback is the evidence. 13 records.
- Clipboard: automatic copy fails in the walk; the fallback selects the digest with manual instructions. Copy success is not recorded.
- Drag handles: the click audit cannot drag. The grip is visible and the reorder is not performed.
- Native validation, covered targets and the absent overflow state are listed as expected or instrument limits in the pending review.
- Issue 326 Copy digest cannot be met as written by this instrument: it asks for a check on success, and the pending pass does not record the clipboard.
- Issue 326, every photograph has a verdict, cannot be met as written while the founder's cost decision leaves the 1,328 BEFORE photographs unread. Either the criterion counts the photographs read, or the decision changes.
- Issue 326, the `Fill it in for me` control, cannot meet both readings in the issue: the body asks for `skipped`, the newer comment asks for the disabled reading, and the instrument emits `skipped` with reason `already disabled`. One reading has to be chosen.
- Issue 326, feedback exits 0 with seven actions, cannot be met while `inbox-draft` is unbuilt and `dashboard-reply` has no fixture. A product ticket or an acceptance change is needed.
- The face run's zero captures for the third theme are an input error, not a product defect: the run's theme name did not match the product's theme id. A corrected face run can still meet criterion 6.
- Issue 328 criterion 1 is meetable by filing the 33 findings; it is not impossible, only not done.

## 7. What this record does not claim

It does not claim the audit is finished. The photographs are not all read, and the triage and paperwork of issues 326 and 328 are not done. Both the slow run and the face walk are recorded, in section 8. The slow run updates section 1, criterion 5 and the criterion 7 count of issue 326, and lifts the waiting from criterion 4 of issue 328; nothing else in the criteria changes.

## 8. The last two passes, 2026-11-26

Read from `evidence/2026-11-25-main-audit/after-face-run-record.txt`, `after-slow-run-record.txt` and their sibling records.

**Face run, `b396694`.** `tools/face_walkthrough.py --routes sheet,rail,rail-collapsed,phone-strip,dialog,server --themes unkey,coforge,momentum --widths 1280,800 --mock-delay-ms 12000`. Exit 1 in 63 seconds. 72 of 108 planned captures: 68 passed, 4 failed, 0 missing. Themes unkey 36 and coforge 36; the momentum theme produced no capture, because the run's theme name did not match the product's theme id, which is an input error and not a product defect. The 4 failures are the rail in the reading state, unkey and coforge, face and page, each `FaceWalkError: no non-fresh plugin card offers Re-test now`. The faceless surfaces are dialog-describe, dialog-tracker, phone-strip and server-inbox, each observed with zero face nodes; these are instrument observations, not visual verdicts. `missing=0` covers the 72 attempted captures, not the 108 capture full plan. The 72 PNGs were counted and signature-checked, and not reviewed.

**Slow run, `3f099e0`.** `tools/layout_audit.py --pending-audit --conditions fresh,plugins,full --widths 1280 --themes unkey --no-stress --fail-on none --jobs 3 --mock-delay-ms 4000 --continue-request-path /research`. Exit 0 in 710 seconds. 129 pages measured of 130 planned, 1 overlay skip, 0 failed. `METRIC findings=96 groups=18 pages=129 skipped=1 box-changed=3 dead=6`. Pending: 1,261 controls, dead=6, silent=15, disabled-only=0, meets=210, instant=736, skipped=270, native-dialog=13, native-validation=11, error=0, box-changed=3, the same counts as the normal pending pass. The 6 dead and 15 silent rows are the same findings already recorded from that pass; nothing new failed. The four-second wait was not observed: the full dashboard's Research is disabled without a question, row 6 was skipped `already disabled`, no POST /research request appears in `pending.json` or `pending.full.json`, and no mock endpoint line was printed. The delay was configured, but no control was subjected to it. The 1,262 PNGs were counted and signature-checked, and not reviewed.

Criteria updated in this record: issue 326 criterion 5 is now met as written, with the delay limit stated in section 3, and its criterion 7 count adds the 1,262 slow-run photographs; issue 328 criterion 4 is no longer waiting on the slow run, and stays not met until ticket 09 is closed. The slow run adds one triage item: it needs a question typed before Research, so the delay can reach a request.

## 9. The founder's closeout decision, 2026-11-27

Ken decided on 2026-11-27, verbatim:

> Close #326 and #328 on the record; then post RENAME WINDOW OPEN on #353

Both issues close with `--reason completed`, each carrying a `CLOSED ON THE RECORD (2026-11-27)` comment that states the delivered numbers and the dropped criteria below. Issue 353 receives `RENAME WINDOW OPEN (2026-11-27)`, which opens the rename window for the ten tickets of spec 032 under `GEMINI-SWARM-SLICE-2.md`.

**Dropped by this decision, issue 326.**

- Criterion 2, the pending walk at `dead=0`, `silent=0` and `disabled-only=0`: the re-walk ends dead=6, silent=15, disabled-only=0, with three dead in F1 (issue 327), three same-query repeats, and all 15 silent expected.
- Criterion 3, the Copy digest clause, impossible as written: the instrument does not record the clipboard, the walk shows 12 instant and 2 skipped, and the fallback photographs manual instructions. The other three controls in criterion 3 are met.
- Criterion 4, the feedback walk exits 0 with seven actions and three photographs each, impossible as written: exit 1, four met, one instrument mislabel, two absent, with `inbox-draft` unbuilt and `dashboard-reply` without a fixture.
- Criterion 6, the face walk: 72 of 108 planned photographs, the third theme at zero captures from a theme-name input error, four rail reading captures failed, no visual verdicts.
- Criterion 7, a verdict for every photograph, impossible as written: no `photographs.md`, and the founder's cost decision leaves the 1,328 BEFORE photographs unread.
- Criterion 8, every visible defect seen in a photograph is a finding: dropped as a whole, because the unread photographs leave completeness unclaimable. F1, F2 and F3 are the findings the reads produced.

**Dropped by this decision, the ten paperwork criteria of issue 328.**

- Criterion 1: the 33 P2 and P3 findings stay in the register; none is filed as an issue.
- Criterion 2: the README has no pending verdict list.
- Criterion 3: the two `docs/evidence/2026-11-24-*` files carry no exact commands.
- Criterion 4: ticket 09 stays `in progress` with its `Partly` line unresolved.
- Criterion 5: there is no spec 029 issue; its six ticket files stay `ready-for-agent` and unticked.
- Criterion 6: spec 026 names `3d942ed`, spec 027 names no commit.
- Criterion 7: neither `docs/design-language.md` nor `DESIGN.md` carries the two face exceptions.
- Criterion 8: there is no `Nexuus Bot` entry in `GLOSSARY.md`.
- Criterion 9: `docs/licensing.md` still calls the in-box plugins MIT.
- Criterion 10: the evidence pack is not on main and not linked from the parent.

**What stays alive.**

- The fix round on issue 327, open, with its P0 and P1 findings.
- The triage list, kept as the 2026-11-26 comment on issue 328: the 33 register findings, the three feedback items, issue 368, the PR 367 remark, the readiness desk boots, the `Fill it in for me` wording conflict, the instrument limits, the old UI crash, and the two main moves.
- Issue 368, the pending calendar fixture.
- The swarm lines: the fix-round merges set by `GEMINI-SWARM.md` and the rename tickets set by `GEMINI-SWARM-SLICE-2.md`, each under its own window and bar. Ken's standing-permission line in slice 2 is blank, so each of the three merges to main waits for his confirmation.

Where this section differs from section 5, this section governs: issues 326 and 328 are closed, issue 320 is closed on 2026-11-27 as the dated close line below records, and issues 324, 325 and 327 stay open.
2026-11-27: Closed issue 320 on Ken's instruction of today (its passes are recorded in section 1, issue 326 and issue 328 are closed on the record by section 9, and the follow-ups live on issue 327 and issue 353). Kept open on this instruction: issue 321 and issue 322 (spec 030 and spec 031 deliverables, the record shows nothing meeting their criteria and their tickets 329 to 344 stay open), issue 324 (section 5: no gate and no two-build baseline record for the audited commit, page fixture fault on issue 368), issue 325 (section 5: P7-02 has no independent confirmation, the register lacks per-partition coverage counts and the checked-and-found-correct section, and it is not in the evidence pack), issue 327 (fix round, window open), issues 329 to 344 (specs 030 and 031), issues 353 to 363 (the rename, window open), issue 368 (the instrument fault, analysis and filing complete, the fix triaged and not built), and issue 380 (the inbox draft-a-reply ticket filed today).
2026-11-27: The pending re-run proves the search fix only; the fill-button dimming is test-verified and mutation-verified but not photograph-proven (`review/AFTER-pending-rerun-review.md` is INCOMPLETE by design of the photographs).

## 10. The merge and close list, 2026-11-27 (merges executed 2026-11-28 02:15 to 04:38 UTC, 18:15 to 20:38 EST)

Recorded by the merger under the runbook `runbook/merger.md` and the bar of `GEMINI-SWARM.md` section 5. Ken authorized the same day: "if all the PRs look good, start merging and closing, whatever is open". Every pull request merged with a merge commit (`gh pr merge --merge`), never squash or rebase, no branch deletion, no force push, no `git worktree prune`. The swarm's worktrees, branches and locks were untouched beyond the lock protocol (no `BROWSER-RUN.LOCK` appeared during the window; `SWARM-HEAVY-RUN.LOCK` was held for every install and gate run and deleted after each, including on the one failed run).

### Merges, in order

| PR | Ticket | Head merged | Merge commit | Bar evidence |
| --- | --- | --- | --- | --- |
| 375 (032-1a) | #354 | 1d063475 (the reviewed head, third review record) | `141a9435` | CLEAN WITH REMARKS (P3 only), all 7 hosted checks green, gate 7/7 + CI PASS in a clean temp worktree, origin/main ancestor |
| 382 (032-1b) | #355 | ca97d09a (main-sync of reviewed b6477631) | `51a1ef71` | CLEAN WITH REMARKS; its P2 (body record correction) was resolved by the 20:13:48Z body edit exactly as prescribed; main-sync merge added no content; gate 7/7 + CI PASS on ca97d09a; all 7 checks green |
| 387 (032-2) | #356 | d9ab772a (main-sync of reviewed 55fd5364) | `f8c568ee` | CLEAN WITH REMARKS (P3 only); main-sync added no content; gate 7/7 + CI PASS; all 7 checks green; the review's integration note governed PR 384's conflict resolution |
| 384 (032-3) | #357 | 689a134 (main-sync of reviewed c81c59c6) | `3b2cce21` | CLEAN WITH REMARKS (P3 + info); one conflict resolved to PR 387's body per the integration note; one reconciliation commit (689a134) dropped ticket 01b's stale avatar-entry completeness pin in tests/test_brand_naming.py (both avatar surfaces renamed by tickets 02 and 03; coverage kept by initials_contract_violations, the synthetic broken-expectation test and the classification sweep); gate 7/7 + CI PASS (3794 passed); all 7 checks green |
| 385 (032-4) | #358 | 1ba9bb56 (main-sync of reviewed 4a7d5c55) | `5a09b3ec` | CLEAN WITH REMARKS (P3/info); the review's open Nuitka check verified green on the head; no conflict; gate 7/7 + CI PASS (3866 passed); all 7 checks green |
| 386 (032-5) | #359 | c88e34c1 (main-sync of reviewed da4b0bf5) | `e2dd9ec9` | CLEAN WITH REMARKS (four LOW, none blocking); no conflict; naming suites 50 passed; gate 7/7 + CI PASS (3881 passed); all 7 checks green |
| 383 (032-6) | #360 | 447dc460 (two main-syncs of reviewed b536b724) | `0c0f4da8` | CLEAN WITH REMARKS (refreshed after the R1 body correction); the merged allowlist needed ticket 06's own generator rerun (commit 207ecc3, table 102 rows) because ticket 05's four glossary entries postdated the committed table; gate 7/7 + CI PASS twice (207ecc3 and 447dc460, 3903 and 3904 passed); all 7 checks green on 447dc460 |

Every merge was preceded by a dated RE-CHECK BLOCK comment on the pull request recording the main-sync, resolutions, new head, gate lines and check plan. Main moved under the reviews repeatedly (the wave-1 series and the guard stage itself); each pull request's ancestry item was re-established by merging `origin/main` in before its merge, with the smallest correct result and both sides kept in source files. The committed SPA bundle never needed a rebuild in any sync: no frontend source change reached the merges except through PR 384's own rebuild and PR 378's own rebuild, each of which arrived with its bundle consistent.

### Hosted checks on main

- After each merge the newest runs on the new main head were waited for up to 15 minutes: all seven green on 141a9435, 51a1ef71, f8c568ee, 3b2cce21.
- Two intermediate main heads had their Nuitka build + smoke run cancelled by GitHub's concurrency cancel-in-progress when a newer main push started 12 to 13 minutes into the build: 5a09b3ec (run 46103925652, cancelled by run 46104366939 on a34175c9, which succeeded) and e2dd9ec9 (run 46105360044, cancelled by the run on c3ebb3e0). No main head was left without a deciding green run: the heads whose runs survived are a34175c9 and the final head.
- Final main head: `0c0f4da8` (PR 383's merge). All seven hosted checks green, Nuitka build + smoke success at 04:38:30Z, within 15 minutes of the merge.

### Closes (all auto-closed by their pull requests, verified, none needed a manual close)

- Issue 354 closed 02:15:09Z by PR 375 (merge 141a9435).
- Issue 355 closed 02:34:16Z by PR 382 (merge 51a1ef71).
- Issue 356 closed 02:52:50Z by PR 387 (merge f8c568ee).
- Issue 357 closed 03:21:44Z by PR 384 (merge 3b2cce21).
- Issue 358 closed 03:39:49Z by PR 385 (merge 5a09b3ec).
- Issue 359 closed 03:58:43Z by PR 386 (merge e2dd9ec9).
- Issue 360 closed 04:24:33Z by PR 383 (merge 0c0f4da8).

### Kept open, with reasons

- Issue 353 (rename parent): seven of ten rename tickets closed; the surface stage's ticket 07 (issue 361) has pull request 388, opened by the swarm during this window, which is OPEN, CONFLICTING against main, with no independent review comment and no hosted checks, so it does not meet the bar; tickets 08 and 09 (issues 362, 363) have no pull request.
- Issue 337: no pull request exists for the workbook-figures work, so it has no merge evidence and cannot close via its pull request.
- Issue 327 (fix round): no fix-round pull request was open at snapshot time. Of the fix round's scope only PR 370 (the two new findings F1 and F3) was already merged before this window, and PRs 371 and 372 carry the triage-round items. The findings P1-04, P1-05, P2-01, P3-01, P3-02, P3-05, P4-01 and P4-02 have no pull request, so the issue stays open and they are named here.
- Issues 321 and 322 (the spec 030 and 031 parents), 324, 325, 368 and 380 stay open per the standing closeout instruction; nothing in this window met their criteria.
- The wave-1 series (PRs 373, 374, 376, 381, 377, 379, 378, spec 033) merged into main during this window by the swarm's own sessions; they were outside this merger's brief (not against main when opened, not in the fix-round or rename merge order) and are recorded here as observed main movement, not as merges by this window. PR 388 is the swarm's in-flight work and stays with it.

### Hygiene

Every temporary gate worktree created by this window (`merge-check/pr375` through `merge-check/pr383`) was removed with `git worktree remove --force` and confirmed gone; `git worktree list` shows all swarm worktrees still present and no merge-check entries. No `git worktree prune` was run, no branch was deleted, no command ran in the founder's checkout.

## 11. Post-merge verification of the swarm's own merges, 2026-11-27

Recorded under Ken's standing rule: when a merge happens outside the merger brief, the post-merge checks are recorded as the cover. This section read the hosted checks on each merge commit and applied the section 5 rule: for each check name the newest run on that commit decides, and `success` or `skipped` with a completion time is a pass. No instrument, test, gate or build was run for this verification. Scope: the PRs numbered 373 to 381 that are pull requests (PR 375 is the merger's own 032-1a merge, excluded by this verification's brief; issue 380 is an issue, not a pull request), plus the other pull requests merged in the same day that are not the merger's seven (375, 382 to 387): PRs 370, 371 and 372. PR 388 is open and unmerged and stays as section 10 records it. PRs 364, 365, 367 and 369 also merged inside the same UTC day but on the orchestrator's line; they are not swarm merges and are named only as observed context.

### The wave-1 series, merged 2026-11-28 03:12 to 04:03 UTC (2026-11-27 22:12 to 23:03 EST)

| PR | State | Merged at (UTC) | Merge commit | Checks on the merge commit, newest run per name | Review comment first line (author) | Body closes |
| --- | --- | --- | --- | --- | --- | --- |
| 373 | merged | 03:12:41 | `a33ed136` | 6 success; `Nuitka build + smoke` cancelled 03:13:52Z by the next push: no deciding pass on 1 name | none on the page (the body reports a verifier pass that returned CHANGES REQUIRED, applied; no such comment exists) | none |
| 374 | merged | 03:13:44 | `cd2d4815` | all 7 cancelled 03:13:57 to 03:14:00Z by the next pushes: no deciding pass | `CLEAN WITH REMARKS` (kanitmann01) | none |
| 376 | merged | 03:13:52 | `52ddc77d` | all 7 cancelled 03:14:05 to 03:19:03Z by later pushes: no deciding pass | `CLEAN WITH REMARKS` (kanitmann01) | none |
| 381 | merged | 03:14:00 | `bcfa581a` | 0 check runs; the Actions suite was cancelled whole (the page's `7 checks passed` belongs to the branch head): no deciding pass on any name | `CLEAN WITH REMARKS` (kanitmann01) | none |
| 377 | merged | 03:14:08 | `65d38e97` | 6 success; `Nuitka build + smoke` cancelled 03:21:58Z by the PR 384 push: no deciding pass on 1 name | `CLEAN WITH REMARKS` (kanitmann01) | none |
| 379 | merged | 03:45:27 | `a34175c9` | all 7 success (`Nuitka build + smoke` completed 03:56:35Z): pass | `CLEAN WITH REMARKS` (kanitmann01) | none |
| 378 | merged | 04:03:43 | `c3ebb3e0` | all 7 success (`Nuitka build + smoke` completed 04:17:10Z): pass | `CLEAN WITH REMARKS` (kanitmann01) | none |

No body in the series carries a closing keyword, so the series closes no issue.

### The fix-round and triage-round pull requests merged the same day, also outside the merger brief

| PR | State | Merged at (UTC) | Merge commit | Checks on the merge commit, newest run per name | Review comment first line (author) | Body closes |
| --- | --- | --- | --- | --- | --- | --- |
| 371 | merged | 2026-11-27 04:41:18 (2026-11-26 23:41 EST) | `3165c559` | `Registry CI` success 04:41:29Z; the other 6 cancelled 04:41:37 to 04:41:39Z by the PR 369 push: no deciding pass on 6 names | none | none (references the issue 326 finding F-AFTER-FACE-6) |
| 370 | merged | 2026-11-27 06:23:52 (01:23 EST) | `91d34c71` | all 7 success (`Nuitka build + smoke` completed 06:35:05Z): pass | none | none; the body states issue 327 is deliberately left open, and it delivers the two new findings F1 and F3 |
| 372 | merged | 2026-11-27 19:22:26 (14:22 EST) | `c6aeb3d6` | all 7 success (`Nuitka build + smoke` completed 19:36:54Z): pass | none | none (carries PR 371's review remark 1) |

### The cover

Four of the ten merge commits carry their own deciding pass on every check name: PRs 370, 372, 378 and 379. On the other six (PRs 371, 373, 374, 376, 377, 381) the rapid push sequence cancelled the runs on the merge commit itself within seconds to minutes. The deciding green runs exist on descendant main heads, each ancestry verified with the compare API: `c3ebb3e0` (all 7 success here) contains the merge commits of PRs 371, 373, 374, 376, 377 and 381, and the final main head `0c0f4da8` (all 7 green per section 10) contains all ten merge commits of this section. Recorded as the cover under Ken's standing rule; on the six merge commits themselves the section 5 rule returns no deciding pass.

### The finding map

| Finding | Delivered by a merged pull request |
| --- | --- |
| P1-04 | none; no pull request exists |
| P1-05 | none; no pull request exists |
| P2-01 | none; no pull request exists |
| P3-01 | none; no pull request exists |
| P3-02 | none; no pull request exists |
| P3-05 | none; no pull request exists |
| P4-01 | none; no pull request exists |
| P4-02 | none; no pull request exists |
| P4-03 (shared with issue 337) | none; issue 337 has no linked pull request and no comment |
| issue 337's workbook figure flow | none; no pull request exists |

The wave-1 series delivers spec 033 and its six tickets; no body names a finding of issue 327 or issue 337. The only fix-round delivery merged today is PR 370, which carries the two new findings F1 and F3, outside the mapped list. Section 10 already named P1-04 to P4-02 as having no pull request, and this verification confirms it on the issue and pull request pages today.

### Decision

No finding of the mapped set is delivered by a merged pull request, so no close follows: issue 327 and issue 337 stay open, no evidence comment was posted on GitHub, and the close list of section 10 stands for them.

2026-11-27: Ken's merge-grant line in `GEMINI-SWARM.md` stands unfilled, verbatim: `Ken may merge these tickets or finding IDs without asking again: ____________________`. Nothing is written on it, so the swarm merged the ten outside-brief pull requests above without it; recorded for Ken's decision.
