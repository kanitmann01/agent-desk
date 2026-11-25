# 01: A layout audit that measures text overflow on every screen

**What to build:** one command boots an isolated copy of the desk in a real browser, visits every screen under every condition, width and theme, measures how the text actually lays out, and writes findings, a root-cause summary, full-page screenshots and crops. A run is deterministic and comparable with a later run. A run under every string tripled is a separate, marked pass. Coverage is part of the answer: a planned combination that was not measured fails the run by name.

**Blocked by:** None (can start immediately).

**Status:** done (2026-11-24).

- [x] The audit boots an isolated desk with a temporary data folder, a file-backed keychain and a loopback mock model, and never touches the real data folder, the real keychain or a real AI.
  - Verified: tools/layout_audit.py (docstring, _pin_environment, FileKeychain, _start_mock) and the final run build/final-layout/20261124-195742.
- [x] One unfiltered run plans 816 combinations across the five conditions, four widths, three themes and the tripled-string pass; the baseline measured 812 and skipped the 4 overlay states that need an installed plugin.
  - Verified, with the plan as it ended: the first tool did plan 816 and the first baseline measured 812. Two conditions were added while the wave ran (long values and the legacy server dashboard) and overlays are now planned in every theme, so the final plan is 1,040 rows. The last run measured 1,028 and skipped 12 (build/last-layout/20261124-211432), all `overlay-widget-menu` in `fresh` and `data`, where nothing overflows.
- [x] Findings are JSON with the kind, the selector, the text, the measured geometry, the route, condition, width, theme and a crop; the summary groups them by root cause with the worst measurement and a source guess in the app.
  - Verified: tools/layout_audit.py findings carry kind, selector, text, metrics, rect, route, condition, width, theme and crop; build/final-layout/20261124-195742/crops holds the crops.
- [x] The kinds distinguish squeezed text, broken words, content spill, text overlap, control collision, offscreen content, unreachable ellipsis, type below 11px and runtime console errors, and runtime rows do not count as layout.
  - Verified: tools/layout_audit.py detectors; build/final-layout/20261124-195742/summary.md prints 824 layout and 12 runtime rows.
- [x] An unmeasured planned combination prints `COVERAGE INCOMPLETE` with the count and reasons and exits 3; explicitly unreachable overlay states are `skipped` and listed.
  - Verified: tools/layout_audit.py _merge_outputs; tests/test_layout_audit.py covers the exit and the skipped list.
- [x] A run under tripled strings is marked `stress`, starts from the same viewports and conditions, and is reported apart from the real-string findings.
  - Verified: tools/layout_audit.py STRESS_CONDITIONS, STRESS_WIDTHS, the stress flag, the stress crops and the separate stress counts; tests/test_layout_audit.py covers the plan.
- [x] The tool adds no product code and no runtime dependency to the app: Playwright is loaded from an ephemeral `uv` environment.
  - Verified: tools/layout_audit.py PLAYWRIGHT_HELP and the optional import; pyproject.toml lists no Playwright dependency.
