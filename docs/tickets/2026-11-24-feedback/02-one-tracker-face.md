# 02: One tracker face

**What to build:** a live tracker tile that draws its reading once. The tile owns the value, the change, the workbook, the pace and the history. The reading the server appends (the findings, the chart sentence, the "Also in your desk" line) sits under the tile as one separated block: its first line visible, the rest behind a disclosure, and "Explain this range" still reachable. The payload, the insight pass and the card routing do not change.

**Blocked by:** 01.

**Status:** done (2026-11-24).

- [x] On a live tracker, the value appears once, the change once, the workbook once, the pace once and the history once.
  - Verified: frontend/src/dashboard/TrackerCard.tsx restatesTile filters the five; frontend/src/test/tracker-cards.test.tsx ('draws the value once and skips the elements that restate the tile').
- [x] The metric labelled Value, the delta labelled Change, the text labelled Workbook, the text labelled Pace and the sparkline labelled History are not drawn as separate rows under the figure.
  - Verified: frontend/src/test/tracker-cards.test.tsx asserts no Value, Change, Workbook, Pace and no History sparkline row under the figure.
- [x] The remaining reading is drawn once as one block separated from the tile, with its first line visible and the rest behind a disclosure that names what it holds.
  - Verified: frontend/src/test/tracker-cards.test.tsx ('draws the reading once, as one separate block with a native disclosure').
- [x] "Explain this range" is still reachable on the tile, and pressing it starts the same request it starts today.
  - Verified: frontend/src/test/press.test.tsx and frontend/src/test/feedback-dashboard.test.tsx exercise 'Explain this range' on the tile and the same press route.
- [x] A tracker with no live reading renders exactly as it does today: the setup card, the attention card with a moved workbook, and the wireframe all keep their shape and action.
  - Verified: frontend/src/test/tracker-cards.test.tsx ('leaves an attention card exactly as it was') and frontend/src/test/review-dashboard.test.tsx (the amber tracker keeps its Set up).
- [x] A card whose face was chosen by the wizard still draws its schema elements and does not take the classic tracker path.
  - Verified: frontend/src/test/tracker-cards.test.tsx (excel-report and kpi-scorecard wizard faces).
- [x] `_tracker_payload`, `_tracker_bindings` and the insight pass are unchanged; `tests/test_insight_seam.py`, `tests/test_plugin_setup_http.py`, `tests/test_plugin_config.py` and `tests/test_file_selection_chain.py` pass without changing a wire pin.
  - Verified: python -m pytest tests/test_insight_seam.py tests/test_plugin_setup_http.py tests/test_plugin_config.py tests/test_file_selection_chain.py passed; TRACKED_SUM "186500" is unchanged.
- [x] The server-rendered dashboard still draws every element it draws today; only the SPA tracker tile changes.
  - Verified: bb653bc changed only frontend/; the server card path still draws every element through _plugin_widget.
- [x] `PluginCardView` routing is unchanged for setup cards, classic tracker cards and the `excel-report` id clause.
  - Verified: frontend/src/dashboard/PluginCardView.tsx keeps the setup, classic tracker and excel-report id branches; frontend/src/test/tracker-cards.test.tsx covers them.
- [x] Component tests assert the single value, the single reading block, the disclosure and the press.
  - Verified: frontend/src/test/tracker-cards.test.tsx and press.test.tsx cover the single value, the reading block, the disclosure and the press.
- [x] `python tools/ci_local.py` passes 7/7.
  - Verified: `python tools/ci_local.py` on `2d00540`, the last commit that changes code: 7/7 gates passed in 127 s (pytest 3520 passed, 1 skipped; vitest 596). It was run again on the head that was pushed, after the documentation commits.
