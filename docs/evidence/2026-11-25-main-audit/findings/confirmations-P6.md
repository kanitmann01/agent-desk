# P6 confirmations

Review worktree: `D:/20-projects/Personal Agents/.worktrees/027-merge` at `3540b9f`.
The worktree was treated as read-only. No gate, walk, application, mutation worktree, or real data folder was used.

## P6-01

- Verdict: confirmed.
- Methods: reading, running.
- Evidence: `specs/029-nexuus-bot-agent-face.md:78` requires one allowed canonical line, an existence assertion, a bundle skip, and a scan of the review sheet. `tests/test_brand_naming.py:22-39` instead scans `src`, `frontend/src`, tools, scripts, ops docs, and listed live files with no allowlist or bundle exclusion; `:57-71` rejects every matching line. `frontend/src/face/name.ts:2` is the required canonical line, and `frontend/src/test/face.test.ts:151-165` and `frontend/src/test/face-rail.test.tsx:198,256,360` contain legitimate test expectations. The review sheet is not in the scan list.
- Run: `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_brand_naming.py`, from the worktree root, exited 1. Relevant output: `F.`, `1 failed, 1 passed in 0.51s`; the failure listed the committed bundle, canonical name module, and both face test files. `git status --short` was empty afterward.
- Severity: P2 in my view. The spec requirement is unimplemented and the named test is red, but no user-visible main path is broken and this is not a test that passes over broken behavior. It is a spec departure with the straightforward guard fix as a workaround, rather than the reviewer's P1 under the supplied definitions.
- Mutation: null.

## P6-02

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/evidence/2026-11-24-feedback/EVIDENCE.md:118,133,172-181` ties the run to `2d00540`, defines `instant` as an immediate page change, and generalizes all 955 to visible feedback. In `git show 2d00540:tools/layout_audit.py`, `_pending_verdict` at `2557-2584` returns `instant` solely on `if not started`, with no before/after page comparison. The current code at `tools/layout_audit.py:2996-3039` confirms that the page-change versus dead distinction was added later.
- Severity: P3 holds. This is an overstated historical evidence claim, not a current product-path failure.
- Mutation: null.

## P6-03

- Verdict: confirmed.
- Methods: reading.
- Evidence: `README.md:7` promises six verdicts, all seven conditions across four widths and three themes, and a selftest for every detector. `tools/layout_audit.py:3002-3051` returns eight verdicts, adding `native-validation` and `dead`. `:268-276,1887-1917` limits base rows to 1024 and 1280, themes and extremes to fresh/full, and stress to fresh/full at 1024 and 1280; `:1888-1895` further limits the legacy dashboard. `tests/test_layout_audit.py:91-101` pins the long-values restriction. The selftest expectations at `:1408-1422` and the checks through `:1646` contain no runtime detector expectation, although `:3307-3355` implements one; `:1662-1663` reports 16 detector expectations.
- Severity: P3 holds. These are command, coverage, and documentation inaccuracies.
- Mutation: null.

## P6-04

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/evidence/2026-11-24-text-fit/EVIDENCE.md:37-41` says every state is measured with real strings and again with every string tripled, presenting 1,040 rows as a full cross-product. `tools/layout_audit.py:275-276` restricts stress to fresh/full at 1024/1280; `:1901-1903` applies that rule, while theme, extreme, overlay, and legacy rows at `:1888-1895,1904-1931` are non-stress. `tests/test_layout_audit.py:91-101` pins the separate bands and the narrower long-values plan.
- Severity: P3 holds. The defect is overstated coverage documentation, not a broken runtime path.
- Mutation: null.

## P6-05

- Verdict: narrowed.
- Methods: reading.
- Evidence: `docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md:25-26` marks the gate complete and reports 7/7 on `2d00540` plus 7/7 on an unidentified pushed head. The same unbound wording appears in feedback tickets 01 through 08 and text-fit ticket 06. Read-only history shows later code changes after `2d00540`, including `71d90e7` (face) and `986a558` (bundle), before merge `3540b9f`, so the earlier result cannot establish the final tree's status. No local record found in the searched docs, specs, or README states the PR body's final 6/7 result or its clock-dependent cause; that external part was not run or fetched under the reading-only scope.
- Restated: Ticket 09's second 7/7 claim is not tied to a commit, and later face and bundle commits mean it is not evidence for `3540b9f`; the tree does not independently establish the PR's reported 6/7 result or cause.
- Severity: P3 holds for the unbound closeout claim. This is evidence traceability, not a demonstrated product failure.
- Mutation: null.

## P6-06

- Verdict: confirmed.
- Methods: reading.
- Evidence: `specs/027-one-home-screen-feedback.md:3` marks the spec done, and `:69` says every model-backed action was photographed with a four-second mock delay. `docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md:7,15-16` remains in progress and explicitly says no `--mock-delay-ms 4000` run is present. The capability exists in `tools/mock_endpoint.py:430-434` and `tools/layout_audit.py:4409-4410`, so the contradiction is the missing acceptance run, not a missing flag.
- Severity: P3 holds. This is an inaccurate completion and evidence claim.
- Mutation: null.

## P6-07

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/tickets/2026-11-24-feedback/09-instruments-and-evidence.md:27-28` marks exact command evidence complete. `docs/evidence/2026-11-24-feedback/EVIDENCE.md:111-114` and `docs/evidence/2026-11-24-text-fit/EVIDENCE.md:176-179` state the gate and readiness results only in prose. The feedback file's sole command fence is the pending audit at `:147-154`; the text-fit fences are browser install and layout audit at `:21-34`. A read-only search found no `python tools/ci_local.py` or `python tools/demo_readiness.py` invocation, exit code, or transcript in either file.
- Severity: P3 holds. This is incomplete reproducibility documentation.
- Mutation: null.

## P6-08

- Verdict: narrowed.
- Methods: reading.
- Evidence: `specs/029-nexuus-bot-agent-face.md:3` says ready-for-agent and carries no issue number. All six face tickets say ready-for-agent and their checkboxes are open, including ticket 06's evidence and PR items at `docs/tickets/2026-11-24-nexuus-face/06-gate-evidence-and-pr.md:9-14`. Read-only history shows `71d90e7` added the face implementation, tests, spec, and tickets, and `3540b9f` merged that branch. The required `docs/evidence/nexuus-face` directory is absent. The repository therefore lacks a local delivery closeout. External issue existence and PR 319's Closes list were not fetched under the reading-only scope, so those parts are not independently confirmed.
- Restated: Spec 029 and all six tickets remain open and ready-for-agent locally even though the face implementation was merged, and the required evidence directory is absent; external issue filing and PR closeout coverage were not verified.
- Severity: P3 holds for the missing local delivery record.
- Mutation: null.

## README at 0f622e3

- P6-03: The same claim does not appear in `README.md` at `0f622e3`. A read-only `gh api` fetch of that file shows a rewritten product README titled `Nexuus Bot` with no layout-audit paragraph, six-verdict list, matrix claim, or `--selftest` coverage claim. The P6-03 verdict remains about `3540b9f` only.

## P6-09

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/design-language.md:199-200,204-209` and `DESIGN.md:58,60` still impose the color/background-only motion rule and ban filled icon tiles. `specs/029-nexuus-bot-agent-face.md:24,84` requires both narrow exceptions to be written into both documents. A whole-file search found no face, Nexuus Bot, exception, filled-mark, or shape-motion entry in those documents, `GLOSSARY.md`, or `frontend/src/test/tokens.test.ts`. The shipped component does use a token fill at `frontend/src/face/AgentFace.tsx:50-60` and frame-driven shape changes through the brain at `:92-125`, so the undocumented exceptions are real.
- Severity: P3 holds. This is a missing design exception and glossary record.
- Mutation: null.

## P6-10

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/design-language.md:166-170` says the result placeholder starts at 1 s. `frontend/src/components/feedback.tsx:13-19` defaults `usePhase` to 100 ms, and `frontend/src/test/feedback-dashboard.test.tsx:227-253` expects both the busy control and shaped result placeholder at exactly 100 ms. `src/agentdesk/server/pages.py:575,830-834` uses the same 100 ms timer for the button and placeholder. Conversely, `frontend/src/memory/feedback.tsx:15-27` starts the memory region phase at 1,000 ms, and `frontend/src/test/feedback-memory.test.tsx:269-283` checks the placeholder only after that cumulative second.
- Severity: P3 holds. The written boundary does not match the deliberately tested implementation, and the surfaces are inconsistent.
- Mutation: null.

## P6-11

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/design-language.md:112-116` says a scrolling table's cells stay `white-space: nowrap`. `src/agentdesk/server/pages.py:354-362` instead applies `overflow-wrap: break-word` to both `table.rows th` and `td`, reserving nowrap for numeric cells. `tests/test_ui_text_fit.py:244-249` explicitly pins break-word on both. `docs/evidence/2026-11-24-text-fit/EVIDENCE.md:100-105` calls one-word-per-line wrapping inside `.table-scroll` deliberate R6 behavior, directly contradicting the document's nowrap sentence.
- Severity: P3 holds. This is a design-contract wording mismatch with a tested implementation.
- Mutation: null.

## P6-12

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/design-language.md:126-133` requires every compared number to be grouped in both SPA and server surfaces, and `specs/027-one-home-screen-feedback.md:159` repeats the universal display claim. `src/agentdesk/plugins/html.py:73-75` formats whole values as plain integer strings, and `:100-121` concatenates them into the server progress note, so 1234567 and 9876543 render without separators. `frontend/src/dashboard/cells.tsx:203-218` does apply `formatGrouped` to the SPA tracker, confirming the surface split while leaving wire values unchanged.
- Severity: P3 holds. The unmet rule is display-number polish plus an overstated universal contract, not loss of data or a broken main path.
- Mutation: null.

## P6-13

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/evidence/2026-11-24-feedback/EVIDENCE.md:75-78` claims every redirect carries a status line. `src/agentdesk/server/app.py:4507-4509,4523-4525` redirects both unbind and bind form posts to `/settings#connections` without notice parameters. Wizard redirects at `:6866-6870,6880-6889` likewise carry no outcome notice. `tests/test_ui_feedback_review.py:496-591` covers nine named redirect families but neither binding nor wizard-step redirects, so the tested subset does not support the universal claim.
- Severity: P3 holds. The missing outcome line is feedback polish on specific redirect paths, and the finding is an overstated evidence guarantee rather than a broken main path.
- Mutation: null.

## P6-14

- Verdict: confirmed.
- Methods: reading.
- Evidence: `docs/tickets/2026-11-24-feedback/03-numbers-fit.md:27-28` claims both long values render on every numeric site with zero findings, while its own verification narrows zero to outside the 11px class. `tools/layout_fixtures/long-values.api.json` has only five top-level GET `/api` keys: dashboard, catalog, and three plugin details. Its sole `9270950` value is the tracker chart point at `:348-350`, not the headline figure at `:344`. `tools/layout_audit.py:2223-2247` replaces only matching GET `/api` responses and cannot replace server-rendered page data. `docs/evidence/2026-11-24-text-fit/EVIDENCE.md:73-75` records 44 under-11px findings for after long strings and 40 other layout findings for tripled strings.
- Severity: P3 holds. This is an overstated fixture-coverage and acceptance claim.
- Mutation: null.

## P6-15

- Verdict: confirmed.
- Methods: reading.
- Evidence: `specs/027-one-home-screen-feedback.md:63,84,87` still promises Remove as the only cannot-run action. `frontend/src/marketplace/PluginDetail.tsx:162-170` renders Uninstall plus Purge data, and `frontend/src/marketplace/Installed.tsx:476-490` renders the same two actions. The updated closeout tickets agree with the code at `docs/tickets/2026-11-24-feedback/04-honest-cards.md:13-18` and `06-marketplace-feedback.md:23-24`. The spec is the outlier.
- Severity: P3 holds. This is stale requirement wording that could mislead a follow-up implementer.
- Mutation: null.
