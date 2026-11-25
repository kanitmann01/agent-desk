# 02: The dashboard fits its text

**What to build:** at 800, 1024, 1280 and 1920, with real and tripled strings and in all three themes, every dashboard tile keeps its text inside its own box. The Desk health table fits its tile with all four columns readable; its times and item counts never print over the tracker; the tracker's title and Set up button stay in their own tile; a plugin tile's title and header wrap instead of collapsing or pushing the menu button off the screen; the open overflow menu stays inside the viewport; the Decisions rows put their actions on their own line when the side column is narrow; and no compared value, stamp or mono cell shows a word broken inside the line.

**Blocked by:** 01.

**Status:** done (2026-11-24).

- [x] At 1024 and 1280 with plugins and full, the "Competitor Watch" title is readable on its own line and the tile header is inside the tile, with no one-character-per-line column and no broken word.
  - Verified, with one substitution: the bundled Competitor Watch card is no longer drawn, because the server drops a plugin that cannot run on this desk (fb56246), so that exact title cannot be measured. The same tile header is measured through the audit fixture's 71 character title (`tools/layout_fixtures/overflow-widget`) at 1024 and 1280 in `plugins` and `full`: no real-string finding in build/last-layout/20261124-211432, and no `broken-word` anywhere in that run.
- [x] The tile menu button's right edge is inside the viewport at 1024, and opening the menu does not widen the document.
  - Verified: build/final-layout/20261124-195742 measures overlay-widget-menu in plugins and full at 1024 and 1280 with no offscreen finding; frontend/src/test/text-fit-dashboard.test.ts pins the menu's absolute corner and calc(100vw - 32px) cap.
- [x] The Desk health table fits its tile at every condition and width: all four columns are visible, the "Items" header stays in its column, and the time and item cells never print over the tracker figure or its title.
  - Verified: build/final-layout/20261124-195742/findings.json has no real-string finding on the dashboard; frontend/src/test/text-fit-dashboard.test.ts pins the fixed four-column matrix, the titled rows and the numeric nowrap.
- [x] The tracker title and its Set up action stay inside the tracker tile, and the Set up button does not intrude into the health tile.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts pins .tracker-title wrapping and the title floor; frontend/src/test/review-dashboard.test.tsx keeps the amber tracker's Set up.
- [x] Decisions rows with data at 1024 keep their title and why line readable, put the actions on their own line when the side column is narrow, and keep the actions inside the card.
  - Verified: frontend/src/index.css gives .decision-text flex 1 1 220px and .decision-actions wrap with max-width 100%; build/final-layout/20261124-195742 has no real-string finding on the dashboard.
- [x] The hero and tracker figures, stamps and mono cells keep `white-space: nowrap`; a value too long for its column scrolls inside its own wrapper and never breaks inside a number.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts pins .figure and .figure-unit nowrap and no scroll well; the hero grid wraps the chart below the figure.
- [x] The `.kpi .value` rule is declared once with one behaviour (nowrap), and the earlier conflicting declaration is gone.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts asserts one .kpi block and one nowrap .kpi .value behaviour.
- [x] The dashboard stylesheet gives prose `overflow-wrap: anywhere` at the document root and gives the named text-holding flex and grid items `min-width: 0`; the change is selector by selector, not a universal reset.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts asserts body overflow-wrap:anywhere and the named min-width:0 items; the sheet has no universal wrap reset.
- [x] Under tripled strings, dashboard findings are gone or lie only inside a deliberate scroller (baseline: 170 stress findings).
  - Verified: build/last-layout/20261124-211432 has 20 tripled-string findings on the dashboard, all of them the 11px class, and none of any other kind; the main baseline with the same instrument had 97 outside the 11px class.
- [x] All three themes apply to the fixed dashboard, and `frontend/src/test/tokens.test.ts` still passes.
  - Verified: build/final-layout/20261124-195742 counts findings under coforge, momentuum and unkey with complete coverage; frontend/src/test/tokens.test.ts is read here (no frontend/node_modules).
