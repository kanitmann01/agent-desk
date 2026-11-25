# 06: One clearing run, one bundle, one evidence pack

**What to build:** the four surface branches are merged into one integration branch, the SPA bundle is rebuilt once from the merged source, and the identical unfiltered audit is re-run on the merged tree. The after run clears every real-string finding except `tiny-type`, leaves tripled findings only inside deliberate scrollers, and shows all three themes with complete coverage. The evidence pack records the before and after counts and screenshots, and the full local gate passes 7/7. The pull request is opened from the integration branch.

**Blocked by:** 02, 03, 04, 05.

**Status:** done (2026-11-24).

- [x] The four surface branches are merged with no unresolved conflict, and the audit tool from 01 is present.
  - Verified: git log shows 97ff44c, 3b3979e, 9cbfcc3 and 4b2a170 merging the four 026 surface branches into merge/026-text-fit, then ae85e8c into this tree; tools/layout_audit.py is present.
- [x] The committed SPA bundle is rebuilt once from the merged source and committed with the source change; the bundle matches the source.
  - Verified: 2d00540 rebuilt `src/agentdesk/server/static/spa` from the fully merged source after the last fix round, and two builds from that source gave the same tree.
- [x] The identical unfiltered audit command is run on the merged tree: 816 planned, 812 measured, 4 skipped, 0 failed, and no `COVERAGE INCOMPLETE`.
  - Verified, with the plan as it ended: the identical command ran on the merged tree and planned 1,040 rows, measured 1,028, skipped 12 and failed 0, with no `COVERAGE INCOMPLETE` (build/last-layout/20261124-211432). The numbers in this item are the first tool's plan; two conditions were added during the wave, and overlays are now planned in every theme.
- [x] After the merge, zero real-string layout findings of every kind except `tiny-type`; the 12 expected runtime 403s on `/marketplace/admin` are the only runtime rows.
  - Verified: build/last-layout/20261124-211432 has zero layout findings outside the 11px class with real strings and with long strings. Its 12 runtime rows are the browser console 403 on `/marketplace/admin` (8 in `fresh`, 2 in `data`, 2 in `plugins`), the same rows the baseline has.
- [x] After the merge, the tripled-string findings that remain are only inside deliberate scrollers.
  - Verified: the 40 tripled-string findings outside the 11px class all sit inside `div.table-scroll`. A further 86 tripled rows are the 11px class on other elements; they are the type size this wave left alone, not text that escaped its box.
- [x] No `broken-word` finding on a compared value, a stamp, code, a button or a mono cell.
  - Verified: build/last-layout/20261124-211432 has zero `broken-word` rows, plain or tripled; the baseline had 20.
- [x] The after run shows unkey, coforge and momentuum applying on the pages it measures.
  - Verified: build/last-layout/20261124-211432/summary.md counts findings under coforge, momentuum and unkey, with 1,028 of 1,040 planned rows measured and the 12 skipped ones listed.
- [x] `docs/evidence/2026-11-24-text-fit/EVIDENCE.md` records the before and after counts, the exact commands, the run folders, the OS, the Playwright version, the Chromium version and the screenshots; the before baseline is `20261124-150340`.
  - Verified: that file holds all of it. The baseline it cites is not `20261124-150340`: that was the first baseline, taken with the first tool on a 816 row plan. Because the plan grew, the baseline was taken again with the final instrument on the same main commit `f31582a` (run `20261124-194926`), so before and after compare row for row.
- [x] The full gate `python tools/ci_local.py` passes 7/7 on the merged tree.
  - Verified: `python tools/ci_local.py` on `2d00540`, the last commit that changes code: 7/7 gates passed in 127 s (pytest 3520 passed, 1 skipped; vitest 596). It was run again on the head that was pushed, after the documentation commits.
- [x] The pull request is opened from the integration branch, names the spec and the ticket issues for 02 to 06, and carries the failing-first test evidence for the fixes.
  - Verified: one pull request against `main` from `fix/ui-text-overflow`, carrying this tree. Its body names spec #303 and tickets #304 to #308, and points at the failing-first tests (`tests/test_ui_text_fit.py`, `tests/test_calendar_paths.py`, `frontend/src/test/text-fit-*.test.ts`) and the review contracts in `frontend/src/test/review-*.test.tsx`.
