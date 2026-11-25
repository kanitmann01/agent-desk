# 06: One clearing run, one bundle, one evidence pack

**What to build:** the four surface branches are merged into one integration branch, the SPA bundle is rebuilt once from the merged source, and the identical unfiltered audit is re-run on the merged tree. The after run clears every real-string finding except `tiny-type`, leaves tripled findings only inside deliberate scrollers, and shows all three themes with complete coverage. The evidence pack records the before and after counts and screenshots, and the full local gate passes 7/7. The pull request is opened from the integration branch.

**Blocked by:** 02, 03, 04, 05.

**Status:** in progress.

- [x] The four surface branches are merged with no unresolved conflict, and the audit tool from 01 is present.
  - Verified: git log shows 97ff44c, 3b3979e, 9cbfcc3 and 4b2a170 merging the four 026 surface branches into merge/026-text-fit, then ae85e8c into this tree; tools/layout_audit.py is present.
- [x] The committed SPA bundle is rebuilt once from the merged source and committed with the source change; the bundle matches the source.
  - Verified: 261d925 rebuilt src/agentdesk/server/static/spa from the fully merged source after b2ee1ca; frontend/src/test/tokens.test.ts checks the committed bundle against the shipped contract.
- [ ] The identical unfiltered audit command is run on the merged tree: 816 planned, 812 measured, 4 skipped, 0 failed, and no `COVERAGE INCOMPLETE`.
- [ ] After the merge, zero real-string layout findings of every kind except `tiny-type`; the 12 expected runtime 403s on `/marketplace/admin` are the only runtime rows.
- [ ] After the merge, the tripled-string findings that remain are only inside deliberate scrollers.
- [ ] No `broken-word` finding on a compared value, a stamp, code, a button or a mono cell.
- [x] The after run shows unkey, coforge and momentuum applying on the pages it measures.
  - Verified: build/final-layout/20261124-195742/summary.md counts findings under coforge, momentuum and unkey with every planned combination measured.
- [ ] `docs/evidence/2026-11-24-text-fit/EVIDENCE.md` records the before and after counts, the exact commands, the run folders, the OS, the Playwright version, the Chromium version and the screenshots; the before baseline is `20261124-150340`.
  - Not done: docs/evidence/2026-11-24-text-fit/EVIDENCE.md is not in this checkout; another writer owns docs/evidence/.
- [ ] The full gate `python tools/ci_local.py` passes 7/7 on the merged tree.
- [ ] The pull request is opened from the integration branch, names the spec and the ticket issues for 02 to 06, and carries the failing-first test evidence for the fixes.
