# P6 findings: the claims

Review root: `D:/20-projects/Personal Agents/.worktrees/027-merge`.
Confirmed with `git -C "D:/20-projects/Personal Agents/.worktrees/027-merge" rev-parse --short HEAD`: `3540b9f`.

Repository and worktree reads were read-only. No full gate, walk, layout audit, server, or build was run. Single test files were run only where the brief permits them. The worktree remained clean after testing.

## 1. Coverage

P6 contains 43 changed files: 29 textual documents and 14 PNG evidence images. Disposition: 43 documentation, 0 generated, 0 test files assigned to P6. All 29 textual documents were read. All 14 PNGs were opened and their dimensions checked with `ffprobe`; the dimensions match the documented crops. The review model cannot visually inspect image input, so pixel-level screenshot content was not independently confirmed. The committed SPA bundle is generated and is not assigned to this documentation partition. P6's bundle-consistency claims were checked against history and source markers where possible, not by rebuilding, because the brief forbids a build.

Partition diff: `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/review/P6.diff`. Its 2,430 textual lines were read in full. Binary PNG hunks carry no visual content, so the images were checked directly as described above.

Files reviewed:

- `README.md`
- `docs/design-language.md`
- `docs/evidence/2026-11-24-feedback/EVIDENCE.md`
- `docs/evidence/2026-11-24-feedback/after-first-load.png`
- `docs/evidence/2026-11-24-feedback/after-home.png`
- `docs/evidence/2026-11-24-feedback/after-marketplace-disabled.png`
- `docs/evidence/2026-11-24-feedback/after-press-wait.png`
- `docs/evidence/2026-11-24-feedback/after-research.png`
- `docs/evidence/2026-11-24-feedback/after-server-working.png`
- `docs/evidence/2026-11-24-text-fit/EVIDENCE.md`
- `docs/evidence/2026-11-24-text-fit/after-dashboard-1024.png`
- `docs/evidence/2026-11-24-text-fit/after-dashboard-1280.png`
- `docs/evidence/2026-11-24-text-fit/after-memory-graph.png`
- `docs/evidence/2026-11-24-text-fit/after-what-this-touches.png`
- `docs/evidence/2026-11-24-text-fit/before-dashboard-1024.png`
- `docs/evidence/2026-11-24-text-fit/before-dashboard-1280.png`
- `docs/evidence/2026-11-24-text-fit/before-memory-graph.png`
- `docs/evidence/2026-11-24-text-fit/before-what-this-touches.png`
- `docs/known-limitations.md`
- `docs/tickets/2026-11-24-feedback/01-shared-busy-state.md`
- `docs/tickets/2026-11-24-feedback/02-one-tracker-face.md`
- `docs/tickets/2026-11-24-feedback/03-numbers-fit.md`
- `docs/tickets/2026-11-24-feedback/04-honest-cards.md`
- `docs/tickets/2026-11-24-feedback/05-dashboard-feedback.md`
- `docs/tickets/2026-11-24-feedback/06-marketplace-feedback.md`
- `docs/tickets/2026-11-24-feedback/07-server-pages-feedback.md`
- `docs/tickets/2026-11-24-feedback/08-memory-islands-feedback.md`
- `docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md`
- `docs/tickets/2026-11-24-nexuus-face/01-face-brain-sheet-favicon.md`
- `docs/tickets/2026-11-24-nexuus-face/02-rail-and-user-waits.md`
- `docs/tickets/2026-11-24-nexuus-face/03-background-moods-and-loop-signal.md`
- `docs/tickets/2026-11-24-nexuus-face/04-face-in-modals.md`
- `docs/tickets/2026-11-24-nexuus-face/05-written-rules-and-brand-guard.md`
- `docs/tickets/2026-11-24-nexuus-face/06-gate-evidence-and-pr.md`
- `docs/tickets/2026-11-24-text-fit/01-layout-audit-tool.md`
- `docs/tickets/2026-11-24-text-fit/02-dashboard-text-fit.md`
- `docs/tickets/2026-11-24-text-fit/03-marketplace-text-fit.md`
- `docs/tickets/2026-11-24-text-fit/04-server-sheet-text-fit.md`
- `docs/tickets/2026-11-24-text-fit/05-memory-islands-text-fit.md`
- `docs/tickets/2026-11-24-text-fit/06-clearing-run-bundle-and-evidence.md`
- `specs/026-text-fit-every-screen.md`
- `specs/027-one-home-screen-feedback.md`
- `specs/029-nexuus-bot-agent-face.md`

`DESIGN.md` is named by the brief but has no change in this range. It was read separately to check spec 029's claim that it carries both face exceptions. `GLOSSARY.md` was also read for the required agent-name entry.

Odd fits: none inside P6. `scripts/marketplace_walkthrough.py` is an instrument outside the literal `tools/` rule; it belongs nearest P5 and is not counted here.

## 2. Findings

### P6-01, P1, specs/029-nexuus-bot-agent-face.md:78

**Title:** Spec 029 claims a narrowed brand guard that was not implemented.

**What:** The spec says the Python brand test allows the agent name on exactly one canonical line, skips the committed bundle, scans the face sheet, and rejects the name elsewhere. The merged test has no allowlist and scans `src`, `frontend/src`, tools, scripts, docs/ops, README, DEMO, frontend/README, package.json and frontend/index.html. It therefore rejects the canonical name, the face tests and the generated bundle.

**Why:** The required guard is a merge acceptance condition, and the actual test fails on the reviewed head. A reader is told the naming boundary is enforced when the gate is red.

**Evidence:** By reading, `specs/029-nexuus-bot-agent-face.md:78` states the allowlist and bundle skip. `tests/test_brand_naming.py:22-39` defines scan roots and files without exclusions; lines 57-71 assert that no scanned line contains the retired name. `frontend/src/face/name.ts:2` is the canonical `Nexuus Bot` line. By running, from the review worktree, `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_brand_naming.py` exited 1 with `1 failed, 1 passed`. The failure listed `src/agentdesk/server/static/spa/assets/index-Bf3o3Xx2.js:1`, `frontend/src/face/name.ts:2`, `frontend/src/test/face-rail.test.tsx` and `frontend/src/test/face.test.ts` among 22 hits.

**Fix:** Implement the spec's exact allowlist and required canonical-line assertion, exclude only the committed generated bundle, scan `frontend/face-sheet.html` explicitly, and keep the name forbidden in product surfaces. Run the single brand test again before changing the spec status.

**Confidence:** high.

### P6-02, P3, docs/evidence/2026-11-24-feedback/EVIDENCE.md:133

**Title:** The evidence gives `instant` a meaning the cited instrument did not implement.

**What:** The evidence table defines `instant` as the page changing at once and then treats all 955 after controls as proof that every press changed the page, showed busy state, or opened a dialog. At the cited tree `2d00540`, `_pending_verdict` returned `instant` whenever no request started, without comparing the page before and after. A control that did nothing was therefore counted as a success.

**Why:** The central no-silent-controls conclusion is stronger than the historical measurement supports. The merged pull request itself says the page-change check was a follow-up and that `instant` only meant no request started.

**Evidence:** By reading, `docs/evidence/2026-11-24-feedback/EVIDENCE.md:118` cites tool version `2d00540`, line 133 defines `instant`, and lines 177-181 draw the universal conclusion. `git show 2d00540:tools/layout_audit.py` at lines 2557-2584 defines `_pending_verdict` and returns `instant` at line 2584 solely on `if not started`. By command, `gh pr view 319 --repo kanitmann01/agent-desk --json body` says `instant only means the control started no request` and that a follow-up adds the changed-page versus did-nothing check.

**Fix:** Either rerun and replace the pending evidence with the current instrument, or relabel the historical row as `no-request` and remove the claim that those controls visibly changed the page. Keep the later dead-control fix out of the historical totals.

**Confidence:** high.

### P6-03, P3, README.md:7

**Title:** README's current audit command and coverage claims do not match the tool.

**What:** The README says the pending pass has six verdicts, while the merged tool can return eight: `instant`, `meets`, `silent`, `disabled-only`, `native-dialog`, `native-validation`, `dead` and `skipped`. It also says `--selftest` checks every detector, but the selftest's 16 detector expectations do not include the runtime detector. Its matrix wording implies all seven conditions use all four widths and themes, while long-values is restricted to 1024 and 1280 in Unkey, themes run only for fresh and full, and stress runs only for fresh and full at 1024 and 1280.

**Why:** A maintainer using the README will misunderstand both the command's result vocabulary and what coverage a clean run actually proves.

**Evidence:** By reading, `README.md:7` names six verdicts and says `--selftest` checks every detector. `tools/layout_audit.py:3002-3051` returns the eight verdicts. Lines 1408-1420 list detector expectations with no runtime expectation; lines 1662-1663 print 16 detector, 4 box and 10 pending expectations. Lines 1887-1917 restrict base, theme, extreme and stress bands. `tests/test_layout_audit.py:91-101` explicitly asserts that long-values has only widths `{1024, 1280}` and theme `{unkey}`.

**Fix:** Update the README to the eight current verdicts, state the actual condition/width/theme bands, and say the selftest covers the planted layout and pending expectations but not the runtime console detector.

**Confidence:** high.

### P6-04, P3, docs/evidence/2026-11-24-text-fit/EVIDENCE.md:39

**Title:** The text-fit evidence says every state is stress-tested, but the plan is banded.

**What:** The evidence says every state is measured with real strings and then again with every string tripled. The merged planner marks stress only for fresh and full at 1024 and 1280. Other conditions, themes, widths, overlays and the legacy dashboard have no tripled row.

**Why:** The 1,040-row plan is presented as a full cross-product. It is not, so the evidence overstates the stress coverage behind the done status.

**Evidence:** By reading, `docs/evidence/2026-11-24-text-fit/EVIDENCE.md:38-41` says every state is measured twice. `tools/layout_audit.py:275-276` defines `STRESS_CONDITIONS = (fresh, full)` and `STRESS_WIDTHS = (1024, 1280)`; lines 1901-1903 set the stress flag only when all three tests pass. Lines 1904-1917 add non-stress theme and extreme rows. `tests/test_layout_audit.py:91-101` documents the separate bands and restricted long-values plan.

**Fix:** Describe the real banded matrix in the evidence and spec, or extend the planner and rerun both sides before claiming every state has a tripled measurement.

**Confidence:** high.

### P6-05, P3, docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md:25

**Title:** The second 7/7 gate result is not tied to a tree, and the final PR records 6/7.

**What:** Ticket 09 is checked and says the full gate passed 7/7 on `2d00540` and again on the head that was pushed, but it does not identify that second head. Later face code and bundle changes were merged, and the merged PR's final-tree section says the gate on the merge head was 6 of 7 because `tests/test_plugin_update_modes.py` uses the real clock.

**Why:** A reader cannot tell which tree the second green result covers. The closeout does not record a green result for the final merged tree, while the PR discloses a red gate and says the final layout and pending walks were also still owed.

**Evidence:** By reading, `docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md:25-26` reports 7/7 on `2d00540` and an unidentified pushed head. The same wording appears in feedback tickets 01-08 and text-fit ticket 06. `git log --oneline 2d00540..3540b9f` shows later code changes including `71d90e7` (face) and `986a558` (bundle). By command, `gh pr view 319 --repo kanitmann01/agent-desk --json body` says `The local gate on the merge head is 6 of 7` and names the clock-dependent test.

**Fix:** Replace the final-head claim with the actual 6/7 result and link the failing test, or record a new successful run on the exact merged head. Do not reuse the `2d00540` gate result for later code.

**Confidence:** medium, because the PR body and tickets may have been written at different moments, but no later final-head green result is present in P6.

### P6-06, P3, specs/027-one-home-screen-feedback.md:3

**Title:** Spec 027 is marked done while its four-second model-wait acceptance item is explicitly incomplete.

**What:** The spec status is done and its outcome paragraph says every model-backed action was photographed with the mock model delayed by four seconds. Ticket 09 remains in progress and the corresponding checkbox is unchecked, stating that no `--mock-delay-ms 4000` run is present.

**Why:** The spec's completion state contradicts its own ticket and evidence. This acceptance path is the proof that real model-backed waits show both the control and region feedback, rather than only held generic requests.

**Evidence:** By reading, `specs/027-one-home-screen-feedback.md:3` says done; line 69 says every model-backed action is photographed under a four-second delay. `docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md:7` says in progress, lines 15-16 leave the item unchecked and say no 4,000 ms run is present. `tools/mock_endpoint.py:430` and `tools/layout_audit.py:4409` provide the delay options, so the missing item is the run and photographs, not the flag.

**Fix:** Run the documented isolated four-second model pass and commit its photographs and counts, or change the spec to an accurate partial/done-with-exception state and narrow the outcome claim.

**Confidence:** high.

### P6-07, P3, docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md:27

**Title:** The evidence pack does not contain the gate and readiness commands it is said to record.

**What:** Ticket 09 says the feedback evidence records the exact commands. The file records the pending-audit command, but its gate and readiness results are prose only. Neither evidence file contains the `python tools/ci_local.py` or `python tools/demo_readiness.py` invocation, environment, exit code or transcript.

**Why:** The evidence pack is not independently reproducible for two of its headline results, even though the ticket marks the evidence item complete.

**Evidence:** By reading and search, `docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md:27-28` marks exact commands complete. `docs/evidence/2026-11-24-feedback/EVIDENCE.md:111-114` states the gate and readiness results; its only fenced command at lines 147-154 is the pending audit. `docs/evidence/2026-11-24-text-fit/EVIDENCE.md:176-179` states the same results; its fenced commands at lines 22-26 and 29-34 are browser install and layout audit. `rg -n 'ci_local|demo_readiness|pytest|vitest'` over both evidence files finds prose references but no gate or readiness command block.

**Fix:** Add the exact gate and readiness commands, tree SHA, environment, exit status and result summary to the evidence pack, or narrow ticket 09 to the audit commands actually present.

**Confidence:** high.

### P6-08, P3, specs/029-nexuus-bot-agent-face.md:3

**Title:** Spec 029 has no filed issue or delivery record despite code being merged.

**What:** Unlike specs 026 and 027, spec 029 has no issue number. It and all six tickets remain ready-for-agent with every checkbox open, while commit `71d90e7` merged the face, rail integration, tests and bundle into PR 319. The required `docs/evidence/nexuus-face` folder is absent, and ticket 06's issue/PR closeout is unchecked.

**Why:** The repository gives no reliable way to tell what part of spec 029 shipped, what remains, or where its acceptance evidence lives. The merged PR title and Closes list cover only 026 and 027.

**Evidence:** By reading, `specs/029-nexuus-bot-agent-face.md:3` says ready-for-agent and carries no issue number. All six `docs/tickets/2026-11-24-nexuus-face` files say ready-for-agent and contain unchecked boxes. `git show --stat --oneline 71d90e7` lists the face implementation and tests; `git log --oneline 2d00540..3540b9f` shows it merged after the 026/027 evidence tree. `test -d docs/evidence/nexuus-face` returned absent. By command, `gh issue list --repo kanitmann01/agent-desk --state all --search '"Spec 029"'` returned audit issues and spec 030 items, but no spec 029 issue. `gh pr view 319` lists Closes #303-#308, #309-#317 and #318 only.

**Fix:** File spec 029 and its six tickets, record the exact shipped subset, close only the items supported by code and evidence, and link the remaining work to the existing follow-up issues.

**Confidence:** high.

### P6-09, P3, docs/design-language.md:199

**Title:** The shipped face has no written design-language exception.

**What:** The design language still says motion is 120 ms on color and background only and refuses filled icon tiles. `DESIGN.md` repeats both rules. Neither document mentions the face, its shape motion or its filled mark, and `GLOSSARY.md` has no Nexuus Bot entry. Spec 029 says both documents carry both exceptions.

**Why:** The face is now the only shipped exception to two explicit design rules, but the governing documents do not record it. Future work cannot distinguish the bounded face exception from banned motion or filled tiles.

**Evidence:** By reading, `docs/design-language.md:199-200` limits motion to color/background and lines 204-209 refuse filled icon tiles. `DESIGN.md:58` and 60 repeat those rules. `rg -n 'Nexuus|nexuus|face|exception|filled mark|shape motion'` over `DESIGN.md`, `docs/design-language.md`, `GLOSSARY.md` and `frontend/src/test/tokens.test.ts` finds no face exception or glossary entry. `specs/029-nexuus-bot-agent-face.md:24` and 84 explicitly require both written exceptions.

**Fix:** Add the two narrow face exceptions to both design documents, add the glossary entry, and pin the exception boundary in the token suite without relaxing the rules for other components.

**Confidence:** high.

### P6-10, P3, docs/design-language.md:166

**Title:** F2's one-second placeholder boundary is not the behavior implemented or tested.

**What:** F2 says the result region shows its placeholder from 1 s to 30 s. The shared `usePhase` default is 100 ms, the dashboard test expects the control and shaped placeholder at 100 ms, and the server submit timer creates both at 100 ms. Some memory call sites pass a 1,000 ms delay, so the surfaces are also inconsistent with each other.

**Why:** The written contract does not describe the shipped timing. A future regression test can follow the document and fail correct code, or follow the code and drift further from the contract.

**Evidence:** By reading, `docs/design-language.md:166` says `From 1 s to 30 s`. `frontend/src/components/feedback.tsx:13-19` defaults `usePhase` to 100 ms. `frontend/src/test/feedback-dashboard.test.tsx:227-265` expects the shaped placeholder at the 100 ms boundary. `src/agentdesk/server/pages.py:831-834` creates the button and placeholder in the same 100 ms timer. `frontend/src/test/feedback-memory.test.tsx:269-283` checks the memory placeholder only after a cumulative 1,000 ms.

**Fix:** Choose the intended boundary and make all surfaces and tests obey it. If 100 ms is intended, rewrite F2 to say the control and region may appear together after the 100 ms gate; if 1 s is intended, delay region placeholders on dashboard and server pages.

**Confidence:** high.

### P6-11, P3, docs/design-language.md:112

**Title:** R6 says scrolling table cells stay nowrap, but the server cells deliberately wrap.

**What:** R6 says a table that cannot fit scrolls in its own wrapper and its cells stay `white-space: nowrap`. The server sheet instead uses `overflow-wrap: break-word` on `table.rows td` and `th`. The evidence describes tripled words wrapping one word per line inside those scrollers as deliberate behavior.

**Why:** R6 is a written universal contract, and the implementation plus tests enforce the opposite cell behavior. The evidence's deliberate-scroller explanation does not make the declarations match.

**Evidence:** By reading, `docs/design-language.md:112-116` requires nowrap cells. `src/agentdesk/server/pages.py:359-362` comments that words still wrap and applies `overflow-wrap:break-word` to `table.rows td` and `th`. `tests/test_ui_text_fit.py:244-249` asserts break-word on both. `docs/evidence/2026-11-24-text-fit/EVIDENCE.md:98-101` says tripled words wrap one word per line inside the scroller.

**Fix:** Rewrite R6 to distinguish horizontal scrollers with wrapping prose cells from numeric or identifier cells that stay nowrap, or change the CSS and tests if nowrap is truly required.

**Confidence:** high.

### P6-12, P3, docs/design-language.md:129

**Title:** N1's every-compared-number grouping claim excludes real server-rendered values.

**What:** N1 says every number a person compares is grouped for display in both the SPA and server pages. The SPA dashboard groups its figures and counts, but server plugin progress notes still use `_format_number`, which returns plain integer strings. For example, a progress value of 1234567 with target 9876543 renders `1234567 of 9876543`.

**Why:** The design contract and spec 027's every-other-compared-value statement are broader than the code. The unchanged wire-value rule is correctly implemented, but display grouping is not universal.

**Evidence:** By reading, `docs/design-language.md:129-133` says every compared number is grouped in SPA and server surfaces. `specs/027-one-home-screen-feedback.md:159` says every other compared value is grouped. `src/agentdesk/plugins/html.py:73-75` returns `str(int(value))` without separators, and lines 108-121 concatenate that display note. `frontend/src/dashboard/cells.tsx:203-218` does apply `formatGrouped` to the SPA tracker, showing the surface split.

**Fix:** Format server-rendered numeric notes for display without changing payload values or bindings, or narrow N1 and spec 027 to the SPA dashboard values actually converted.

**Confidence:** high.

### P6-13, P3, docs/evidence/2026-11-24-feedback/EVIDENCE.md:75

**Title:** The claim that every redirect carries a status line is false.

**What:** Several form handlers redirect without a notice. The job-binding form redirects to `/settings#connections` after both bind and unbind, and wizard step redirects return to the session without an outcome notice. The new page's generic `role="status"` container exists, but no outcome text is supplied for these paths.

**Why:** The evidence turns a tested set of named redirects into a universal guarantee. Users of the untested settings and wizard paths do not receive the promised outcome line.

**Evidence:** By reading, `docs/evidence/2026-11-24-feedback/EVIDENCE.md:75` says every redirect carries a status line. `src/agentdesk/server/app.py:4507-4509` and 4523-4525 redirect binding form posts to `/settings#connections` with no notice. Lines 6866-6870 and 6880-6889 redirect wizard posts without a notice. `tests/test_ui_feedback_review.py:496-591` covers assistant, agents, memory, capabilities, mail, endpoint, update, loop and inbox redirects, but not binding or wizard-step redirects.

**Fix:** Add outcome notices to the remaining form redirects and tests, or narrow the evidence and F5 wording to the routes that actually carry a notice.

**Confidence:** high.

### P6-14, P3, docs/tickets/2026-11-24-feedback/03-numbers-fit.md:27

**Title:** The long-values fixture does not cover every numeric site and is not zero-finding.

**What:** The checked ticket says the fixture renders both long values on every numeric site and produces zero findings. The fixture maps only five GET `/api` paths: dashboard, catalog and three plugin details. It does not replace server-rendered page data, and 9,270,950 appears only as a chart point, not as the headline figure. The evidence table also records 44 tiny-type findings for the long-values condition, so the unqualified zero-finding claim is false even on its own plan.

**Why:** The acceptance item overstates both coverage and result. A regression on a server page or an unrepresented numeric site would not be exercised by this fixture.

**Evidence:** By reading, `docs/tickets/2026-11-24-feedback/03-numbers-fit.md:27-28` makes the claim, while its verification quietly qualifies zero as outside the 11px class. `tools/layout_fixtures/long-values.api.json` has top-level keys only for `/api/dashboard`, `/api/marketplace/catalog` and three `/api/marketplace/plugin` routes. The only `9270950` value is the tracker points array at line 349. `docs/evidence/2026-11-24-text-fit/EVIDENCE.md:73-75` records 44 under-11px findings in the after long-string condition and 40 additional layout findings under tripled strings. `tools/layout_audit.py:2223-2240` fulfils only matching GET `/api` paths.

**Fix:** Say exactly which numeric sites the fixture covers, add server-rendered fixtures if universal coverage is required, put 9,270,950 in an actual displayed figure, and qualify the acceptance as zero findings outside tiny-type.

**Confidence:** high.

### P6-15, P3, specs/027-one-home-screen-feedback.md:63

**Title:** Spec 027 still promises Remove as the only cannot-run action.

**What:** The spec's solution and user stories say a network-only plugin offers Remove as its only action. The shipped detail and Installed surfaces offer Uninstall and Purge data. The closeout tickets correctly describe those two actions, so the spec contradicts both code and its own updated tickets.

**Why:** The spec is the durable requirement record and still names the old action and the wrong action count. A follow-up implementer could remove the data-deletion path while trying to comply.

**Evidence:** By reading, `specs/027-one-home-screen-feedback.md:63`, 84 and 87 promise Remove alone. `frontend/src/marketplace/PluginDetail.tsx:162-170` renders Uninstall and Purge data for cannot-run plugins. `frontend/src/marketplace/Installed.tsx` uses the same two-action closeout. `docs/tickets/2026-11-24-feedback/04-honest-cards.md:11-13` and `06-marketplace-feedback.md:21-22` say Uninstall and Purge data.

**Fix:** Update the spec solution, user stories and implementation decision to Uninstall plus Purge data, keeping the distinction that Uninstall preserves the data folder.

**Confidence:** high.

## 3. Tests that can fail

No new or changed test file is assigned to P6. The tests below belong to P1, P2, P3, P4 or P5. They were inspected only because P6 documents use them as evidence.

| Test file | Behavior whose removal would fail it, or finding |
| --- | --- |
| `tests/test_brand_naming.py` | The scan must reject a planted retired-name line and a planted em dash. P6-01 flags the implementation, not test blindness: the naming test currently fails because the required allowlist is absent. |
| `tests/test_layout_audit.py` | Removing the page-signature check, native-validation classification, selected/drag skips, late-signature window, box delta rule or coverage exit would fail specific tests. Run result: 29 passed. |
| `frontend/src/test/button-pending.test.tsx` | Removing the 100 ms gate, delayed reset, unmount cleanup, pending label/ARIA state, second-press guard, label stack, opacity-only pulse or reduced-motion freeze would fail specific tests. Run result: 16 passed. |
| `tests/test_ui_text_fit.py` | Named tests pin root wrapping, targeted shrink, decision/header wrap, badge whole, scrollers, timeline parity, empty calendar behavior, no-widget/no-transport filtering and source-only health counts. |
| `tests/test_ui_feedback.py` | Named tests pin skip links, one delegated listener, success-only reload, model-form wait targets, widget sketch, result status/focus, retained invalid input and no-script settings posts. |
| `tests/test_ui_feedback_review.py` | Named tests pin notice escaping, duplicate-submit guard, watchdog unlock, shown-notice removal, network/card filtering, specific redirect notices and query-before-fragment ordering. P6-13 notes that these named redirect tests do not prove every redirect. |
| `frontend/src/test/text-fit-dashboard.test.ts` | Removing display grouping, hero wrap, figure nowrap, timeline columns, scoped meta placement or named min-width rules would fail its declaration/behavior tests. |
| `frontend/src/test/text-fit-marketplace.test.ts` | Removing root wrapping, targeted shrink, control no-shrink, chip caps or inner scrollers would fail its source-contract tests. |
| `frontend/src/test/text-fit-memory.test.ts` | Removing island root wrapping, graph canvas/margins, empty-column behavior, row wrap or figure nowrap would fail its source-contract tests. |
| `frontend/src/test/feedback-dashboard.test.tsx` | Removing the 100 ms gate, shaped research/skill/press/draft placeholders, ten-second line, retained input, in-place replacement, first-load bento or keep-and-dim refetch would fail specific tests. |
| `frontend/src/test/feedback-marketplace.test.tsx` | Removing lifecycle busy labels, filter keep-and-dim, 401 notice without retry, shaped first loads, single-row lock or watchdog/late-outcome handling would fail specific tests. |
| `frontend/src/test/feedback-memory.test.tsx` | Removing switch double-press guards, observation placeholder, ten-second line, kept failed edit/page, approve progress or first-load skeleton would fail specific tests. Its placeholder test checks 1,000 ms, which conflicts with the universal F2 wording in P6-10. |

## 4. Checked and found correct

- Worktree head is `3540b9f`, as the brief requires. The partition diff covers exactly 43 P6 files. `DESIGN.md` is unchanged and was checked separately.
- README's three shipped plugin directories, 23 archived plugin directories and empty pack list match the tree. `/plugins` has a 302 to `/marketplace/installed`, the missing-build 404 message exists, and the app and mock endpoint enforce loopback binds.
- The historical spec 026 ticket 01 claim is exact: commit `3d942ed` adds only `tools/layout_audit.py`, 2,407 lines.
- The empty calendar pin is fixed: `default_calendar_hint` no longer indexes an empty candidate list, and `tests/test_calendar_paths.py` covers the helper and route behavior.
- The shared dashboard seam filters no-widget and no-transport plugin cards once in `dashboard_state.py`, so the SPA and legacy page use the same filtered list. The closeout tickets' Uninstall plus Purge data wording matches the marketplace code.
- `Button` preserves a caller-supplied submit type through prop spread, disables while pending, exposes only the pending label to assistive technology, and keeps both labels in one grid cell. The 16 pending-button tests passed.
- `useBusy` has a real 100 ms boundary, resets on inactive, ignores short flaps and clears its timer on unmount. The shared pulse uses opacity only and has a reduced-motion freeze.
- The layout audit unit suite passed all 29 tests. Its current code does distinguish dead controls, native validation, selected/drag skips, late page changes and box movement. The problem is that the committed evidence predates those fixes.
- The server page script has one capture-phase submit listener, a synchronous duplicate guard, a 100 ms visual delay, a 10-second honesty line and a 180-second watchdog. Inputs are not disabled. Named server tests cover the no-script settings path, blank fact/brief retention, invalid timeout retention and notice escaping.
- Marketplace purge, uninstall and rollback sheets keep failures in the open sheet and announce late failures after watchdog release. The code and `review-marketplace.test.tsx` support the known-limitations wording.
- The timeline columns are `max-content minmax(0,1fr)` in both SPA and server sheets, and `.w-timeline .w-list-meta` is scoped to column 1 while the base list meta stays in column 2.
- Tracker display grouping does not mutate the wire value. `formatGrouped` is applied in the SPA surface, and the raw payload/binding pins remain the documented guardrail.
- The face implementation is present in the rail and app provider, the phone strip has no face slot, and the favicon is linked. Spec 029's background-loop and modal tickets remain openly unchecked, and the code confirms those items are not built: `agentloop.status()` has no `currentStep` or `lastOk`, `dashboard_state` omits them, the dashboard does not poll `/api/agent-loop`, and `ModalSheet`, `DescribePlugin` and `TrackerSetup` have no modal face slot. These were treated as open scope, not as false done claims.
- The evidence PNG dimensions match every documented crop. Pixel content could not be independently inspected with the available model input, so no screenshot caption is presented as visually verified.
- The historical evidence files explicitly say their full run folders are not committed. Their counts and photographs therefore remain author-reported rather than independently reproducible from this repository. This is disclosed by the documents and was not treated as a defect by itself.

Commands run, all within the brief's limits:

- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_brand_naming.py`: 1 failed, 1 passed, P6-01.
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_layout_audit.py`: 29 passed.
- `npx vitest run src/test/button-pending.test.tsx`: 16 passed.
- Read-only `git`, `rg`, `gh issue list`, `gh pr view`, and `ffprobe` inspection. No gate, walk, audit, server, build, real data folder or real keychain was touched.
