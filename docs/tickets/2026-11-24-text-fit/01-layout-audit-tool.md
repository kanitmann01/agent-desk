# 01: A layout audit that measures text overflow on every screen

**What to build:** one command boots an isolated copy of the desk in a real browser, visits every screen under every condition, width and theme, measures how the text actually lays out, and writes findings, a root-cause summary, full-page screenshots and crops. A run is deterministic and comparable with a later run. A run under every string tripled is a separate, marked pass. Coverage is part of the answer: a planned combination that was not measured fails the run by name.

**Blocked by:** None (can start immediately).

**Status:** done (commit `3d942ed`).

- [x] The audit boots an isolated desk with a temporary data folder, a file-backed keychain and a loopback mock model, and never touches the real data folder, the real keychain or a real AI.
- [x] One unfiltered run plans 816 combinations across the five conditions, four widths, three themes and the tripled-string pass; the baseline measured 812 and skipped the 4 overlay states that need an installed plugin.
- [x] Findings are JSON with the kind, the selector, the text, the measured geometry, the route, condition, width, theme and a crop; the summary groups them by root cause with the worst measurement and a source guess in the app.
- [x] The kinds distinguish squeezed text, broken words, content spill, text overlap, control collision, offscreen content, unreachable ellipsis, type below 11px and runtime console errors, and runtime rows do not count as layout.
- [x] An unmeasured planned combination prints `COVERAGE INCOMPLETE` with the count and reasons and exits 3; explicitly unreachable overlay states are `skipped` and listed.
- [x] A run under tripled strings is marked `stress`, starts from the same viewports and conditions, and is reported apart from the real-string findings.
- [x] The tool adds no product code and no runtime dependency to the app: Playwright is loaded from an ephemeral `uv` environment.
