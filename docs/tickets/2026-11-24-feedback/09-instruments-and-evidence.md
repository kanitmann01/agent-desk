# 09: Instruments and evidence

**What to build:** the instruments the wave is measured with, and the evidence pack that makes the claim checkable. The mock model gains a delay so a four-second wait is repeatable. The layout audit gains a pending-state pass that holds every non-GET request, presses every control and records whether anything visible changes, plus the committed long-values fixture. The seven feedback rules and the four number rules are in the design language, every pending state is photographed, and the evidence pack records the commands, counts and screenshots.

**Blocked by:** 02, 03, 04, 05, 06, 07, 08.

**Status:** in progress.

- [x] `tools/mock_endpoint.py` accepts `--delay-ms N`, defaults to 0, keeps its loopback-only bind and delays every response by N milliseconds.
  - Verified: tools/mock_endpoint.py (--delay-ms default 0, loopback-only bind, time.sleep before every chat-completion answer).
- [x] The layout audit has a pending-state pass that holds every non-GET request, presses each control, records whether anything visible changes, and reports `silent` and `disabled-only` counts for every page and overlay.
  - Verified: tools/layout_audit.py --pending-audit (_run_pending_audit, _pending_verdict) holds non-GET requests, clicks every visible control, records the verdict and writes pending.json; tests/test_layout_audit.py::test_pending_verdicts.
- [x] The pending-state audit reports zero `silent` and zero `disabled-only` controls on every page and overlay.
  - Verified: build/last-pending/20261124-212717 walks 1,245 controls over 129 measured pages and overlays: `silent` 0, `disabled-only` 0. The main baseline with the same instrument had 199 and 74 (run `20261124-194926`). The one state it skips is the widget menu in `fresh`, where nothing overflows.
- [ ] With the mock model delayed by 4 seconds, every model-backed action shows a busy control and a same-shape placeholder with a phase line, and each is photographed.
  - Partly: build/final-pending/20261124-200831 holds every non-GET request and photographs each control's pending state, but no run with --mock-delay-ms 4000 is present.
- [x] The layout audit has a committed "long values" fixture, and that fixture produces zero findings on every numeric site.
  - Verified: `tools/layout_fixtures/long-values.api.json`, served in the `long-values` condition. build/last-layout/20261124-211432 has zero findings outside the 11px class in that condition; the baseline had 51.
- [x] The layout audit still reports zero real-string findings except the 11px `tiny-type` class; the 12 expected runtime rows on `/marketplace/admin` are the only runtime rows.
  - Verified: build/last-layout/20261124-211432 has zero real-string layout findings outside the 11px class, and its only runtime rows are the 12 console 403s on `/marketplace/admin`.
- [x] `docs/design-language.md` carries F1 to F7 and N1 to N4 in the document's voice.
  - Verified: docs/design-language.md (N1 to N4 at lines 129-146, F1 to F7 at lines 159-185).
- [x] The committed SPA bundle is rebuilt once from the merged source and matches it.
  - Verified: 2d00540 rebuilt `src/agentdesk/server/static/spa` from the fully merged source, and two builds from that source gave the same tree.
- [x] The full gate `python tools/ci_local.py` passes 7/7.
  - Verified: `python tools/ci_local.py` on `2d00540`, the last commit that changes code: 7/7 gates passed in 127 s (pytest 3520 passed, 1 skipped; vitest 596). It was run again on the head that was pushed, after the documentation commits.
- [x] `docs/evidence/2026-11-24-feedback/EVIDENCE.md` records the exact commands, the run folders, the OS, the Playwright and Chromium versions, the before and after counts and the screenshots.
  - Verified: that file holds the commands, the run folders, Windows 10.0.26300, Playwright 1.65.2, Chromium 1255, the before and after verdict counts, and the screenshots.
- [x] The pull request names this spec and ticket issues 02 to 09 and carries the failing-first evidence.
  - Verified: the same pull request names spec #318 and tickets #309 to #317, and points at the failing-first tests (`tests/test_ui_feedback.py`, `tests/test_ui_feedback_review.py`, `frontend/src/test/feedback-*.test.tsx`, `frontend/src/test/review-*.test.tsx`) and at the two evidence documents.
