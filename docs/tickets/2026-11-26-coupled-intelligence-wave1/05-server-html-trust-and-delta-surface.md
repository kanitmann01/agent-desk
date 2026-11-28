# 05: Server HTML trust and delta surface

**What to build:** Surface Wave 1 blocks cleanly on the server-rendered fallback dashboard without JavaScript: render any `"delta"` block at the top of each tile, render `"falsify"` and `"receipts"`/`"note"` blocks below elements, and render expandable `<details class="w-why"><summary>Why</summary>...</details>` drilldown for structured `"why"` provenance while keeping all HTML escaping and quiet-paragraph contracts intact.

**Build in:** `src/agentdesk/server/app.py` (`_delta_line` (new), `_receipt_line`, `_plugin_widget`), `src/agentdesk/server/pages.py` (minimal CSS rules in `STYLES` for `.w-delta` and `.w-why`), `tests/test_server_insight_html.py`, and `tests/test_server_insight_press_page.py`. Do not edit `src/agentdesk/insight/` or `frontend/`.

**Blocked by:** 01: Provenance contract and memory citations, 02: Last-seen snapshots and perceptual deltas, 04: Research falsification and counter-evidence press.

**Status:** ready-for-agent

- [ ] `_plugin_widget` renders any `"delta"` block at the top of the tile body (before elements, using `<p class="w-delta">` or quiet top line) so `"Since you last looked: ..."` is visible immediately above the tile's content on both fresh and attention tiles that carry a delta.
- [ ] `_receipt_line` skips `"delta"` blocks (preventing duplicate rendering), renders `<p class="w-note">` for `"receipts"`, `"falsify"`, and `"note"` blocks in order, and appends `<details class="w-why"><summary>Why</summary><ul>...</ul></details>` when a `"receipts"` block carries a non-empty `"why"` list.
- [ ] All strings inside `"delta"` and `"why"` (`claim`, `columns`, `cells`, `rule`, `facts` ID/source/entity) are strictly HTML-escaped, and no `<p class="w-note">` tag is used inside `<details class="w-why">` so `_quiet_lines` contracts in `tests/test_insight_blocks.py` remain green.
- [ ] `POST /insight/press` renders `"check-counter"` answers and refusals cleanly via the existing `render_press_page` flow without any raw identifier fallback.
- [ ] `tests/test_server_insight_html.py` and `tests/test_server_insight_press_page.py` cover top-of-tile deltas, falsification blocks, `"Why"` details markup and XSS escaping, and `"check-counter"` press page behaviour. All Python code parses under 3.10 and carries docstrings.
