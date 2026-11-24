# 09: Instruments and evidence

**What to build:** the instruments the wave is measured with, and the evidence pack that makes the claim checkable. The mock model gains a delay so a four-second wait is repeatable. The layout audit gains a pending-state pass that holds every non-GET request, presses every control and records whether anything visible changes, plus the committed long-values fixture. The seven feedback rules and the four number rules are in the design language, every pending state is photographed, and the evidence pack records the commands, counts and screenshots.

**Blocked by:** 02, 03, 04, 05, 06, 07, 08.

**Status:** queued.

- [ ] `tools/mock_endpoint.py` accepts `--delay-ms N`, defaults to 0, keeps its loopback-only bind and delays every response by N milliseconds.
- [ ] The layout audit has a pending-state pass that holds every non-GET request, presses each control, records whether anything visible changes, and reports `silent` and `disabled-only` counts for every page and overlay.
- [ ] The pending-state audit reports zero `silent` and zero `disabled-only` controls on every page and overlay.
- [ ] With the mock model delayed by 4 seconds, every model-backed action shows a busy control and a same-shape placeholder with a phase line, and each is photographed.
- [ ] The layout audit has a committed "long values" fixture, and that fixture produces zero findings on every numeric site.
- [ ] The layout audit still reports zero real-string findings except the 11px `tiny-type` class; the 12 expected runtime rows on `/marketplace/admin` are the only runtime rows.
- [ ] `docs/design-language.md` carries F1 to F7 and N1 to N4 in the document's voice.
- [ ] The committed SPA bundle is rebuilt once from the merged source and matches it.
- [ ] The full gate `python tools/ci_local.py` passes 7/7.
- [ ] `docs/evidence/2026-11-24-feedback/EVIDENCE.md` records the exact commands, the run folders, the OS, the Playwright and Chromium versions, the before and after counts and the screenshots.
- [ ] The pull request names this spec and ticket issues 02 to 09 and carries the failing-first evidence.
