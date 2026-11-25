# 03: Numbers fit

**What to build:** every number a person compares reads in full or gives way deliberately. Display grouping is added where a person reads a value, while the value a system reads keeps its exact digits. The headline figure and the tracker figure print in full and the layout makes room; a label on a narrow bar may be compact when the exact value is reachable; a timeline's time, date and title each get a column that fits its content.

**Blocked by:** 01.

**Status:** in progress.

- [x] With a 9,270,950 fixture, the headline figure prints in full at 1280 and at 1024, with no clipping and no sideways scroll inside the figure.
  - Verified: tools/layout_fixtures/long-values.api.json carries 9,270,950 and 1,234,567; build/final-layout/20261124-195742 long-values has only tiny-type; frontend/src/test/tracker-cards.test.tsx prints 9,270,950 grouped.
- [x] At 1024, when the headline figure needs the row, the stage chart moves below it instead of squeezing the figure; at 1280 both remain readable.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts pins .hero-grid flex-wrap, .hero-figure flex 0 0 auto and .stage-chart flex 1 1 280px.
- [x] The tracker figure, its unit, its goal and its change print in full inside the tile at 36px; no value scrolls inside a dot, a chip or a narrow track.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts and tracker-cards.test.tsx pin the 36px .figure, the nowrap unit and the titled change chip.
- [x] Compared values are grouped for display (9,270,950), and the system value is unchanged: progress and bar faces render correctly from 1,000 up, and `tests/test_file_selection_chain.py:46,290` still pins "186500".
  - Verified: frontend/src/test/text-fit-dashboard.test.ts groups 9,270,950; tests/test_file_selection_chain.py passes and still pins "186500" at line 46 and the tracked metric at line 290.
- [x] A stage bar's label may use compact notation, and the exact value is reachable through a `title` and the aria-label that already names it.
  - Verified: frontend/src/test/review-dashboard.test.tsx titles the compact stage value with the exact signed figure and the figure's aria-label names it.
- [x] The generic timeline gives its time, date or title a column that fits the content: the title no longer lands in the 44px column.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts pins the .w-timeline max-content time column and the wide title column.
- [x] The `.w-list-meta` rule is scoped so a plain list, a checklist and a timeline each keep their own columns; fixing the timeline does not move a list's meta.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts pins .w-timeline .w-list-meta in column 1 while the base .w-list-meta stays in column 2.
- [ ] The server sheet carries the same timeline and list contract as the SPA sheet, and the token suite pins both.
  - Not done: src/agentdesk/server/pages.py has no .w-timeline or .w-list rules, while src/agentdesk/plugins/html.py:223-231 emits those classes on the server card.
- [x] Desk health's numeric cells keep their counts and times grouped and inside their columns.
  - Verified: frontend/src/test/cards.test.tsx and brief-decisions.test.tsx keep the health counts grouped and the numeric cells in .num.mono.
- [ ] The layout audit has a committed "long values" fixture that renders 9,270,950 and 1,234,567 on every numeric site, and the fixture produces zero findings.
- [x] No page gains a horizontal scrollbar at 1024 or 1280.
  - Verified: build/final-layout/20261124-195742 has no offscreen-content finding at 1024 or 1280 (or 800 and 1920).
- [x] Component and token tests cover the figure, the stage layout, the timeline columns and the scoped meta rule.
  - Verified: frontend/src/test/text-fit-dashboard.test.ts, cards.test.tsx, review-dashboard.test.tsx and tokens.test.ts cover the figure, stage, timeline and scoped meta.
- [ ] `python tools/ci_local.py` passes 7/7.
