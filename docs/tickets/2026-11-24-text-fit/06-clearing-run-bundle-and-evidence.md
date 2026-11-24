# 06: One clearing run, one bundle, one evidence pack

**What to build:** the four surface branches are merged into one integration branch, the SPA bundle is rebuilt once from the merged source, and the identical unfiltered audit is re-run on the merged tree. The after run clears every real-string finding except `tiny-type`, leaves tripled findings only inside deliberate scrollers, and shows all three themes with complete coverage. The evidence pack records the before and after counts and screenshots, and the full local gate passes 7/7. The pull request is opened from the integration branch.

**Blocked by:** 02, 03, 04, 05.

**Status:** queued.

- [ ] The four surface branches are merged with no unresolved conflict, and the audit tool from 01 is present.
- [ ] The committed SPA bundle is rebuilt once from the merged source and committed with the source change; the bundle matches the source.
- [ ] The identical unfiltered audit command is run on the merged tree: 816 planned, 812 measured, 4 skipped, 0 failed, and no `COVERAGE INCOMPLETE`.
- [ ] After the merge, zero real-string layout findings of every kind except `tiny-type`; the 12 expected runtime 403s on `/marketplace/admin` are the only runtime rows.
- [ ] After the merge, the tripled-string findings that remain are only inside deliberate scrollers.
- [ ] No `broken-word` finding on a compared value, a stamp, code, a button or a mono cell.
- [ ] The after run shows unkey, coforge and momentuum applying on the pages it measures.
- [ ] `docs/evidence/2026-11-24-text-fit/EVIDENCE.md` records the before and after counts, the exact commands, the run folders, the OS, the Playwright version, the Chromium version and the screenshots; the before baseline is `20261124-150340`.
- [ ] The full gate `python tools/ci_local.py` passes 7/7 on the merged tree.
- [ ] The pull request is opened from the integration branch, names the spec and the ticket issues for 02 to 06, and carries the failing-first test evidence for the fixes.
