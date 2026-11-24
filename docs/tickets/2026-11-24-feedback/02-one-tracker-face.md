# 02: One tracker face

**What to build:** a live tracker tile that draws its reading once. The tile owns the value, the change, the workbook, the pace and the history. The reading the server appends (the findings, the chart sentence, the "Also in your desk" line) sits under the tile as one separated block: its first line visible, the rest behind a disclosure, and "Explain this range" still reachable. The payload, the insight pass and the card routing do not change.

**Blocked by:** 01.

**Status:** queued.

- [ ] On a live tracker, the value appears once, the change once, the workbook once, the pace once and the history once.
- [ ] The metric labelled Value, the delta labelled Change, the text labelled Workbook, the text labelled Pace and the sparkline labelled History are not drawn as separate rows under the figure.
- [ ] The remaining reading is drawn once as one block separated from the tile, with its first line visible and the rest behind a disclosure that names what it holds.
- [ ] "Explain this range" is still reachable on the tile, and pressing it starts the same request it starts today.
- [ ] A tracker with no live reading renders exactly as it does today: the setup card, the attention card with a moved workbook, and the wireframe all keep their shape and action.
- [ ] A card whose face was chosen by the wizard still draws its schema elements and does not take the classic tracker path.
- [ ] `_tracker_payload`, `_tracker_bindings` and the insight pass are unchanged; `tests/test_insight_seam.py`, `tests/test_plugin_setup_http.py`, `tests/test_plugin_config.py` and `tests/test_file_selection_chain.py` pass without changing a wire pin.
- [ ] The server-rendered dashboard still draws every element it draws today; only the SPA tracker tile changes.
- [ ] `PluginCardView` routing is unchanged for setup cards, classic tracker cards and the `excel-report` id clause.
- [ ] Component tests assert the single value, the single reading block, the disclosure and the press.
- [ ] `python tools/ci_local.py` passes 7/7.
