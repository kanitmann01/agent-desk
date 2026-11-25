# 05: The memory page fits its text

**What to build:** the memory graph and the memory loop keep their text inside their islands at 800, 1024, 1280 and 1920: the graph's picture no longer carries a 4px sideways scroll, the empty state's column titles stay in their ghost columns, and the graph's wide canvas is a deliberate full-bleed region rather than a child that spills out of the 720px text column. The `.mg` and `.ml` roots carry the wrap contract, and under tripled strings their findings are gone or inside a deliberate scroller.

**Blocked by:** 01.

**Status:** in progress.

- [x] `/memory/graph` with data has no 4px scroll overflow on the picture at any width.
  - Verified: build/final-layout/20261124-195742/findings.json has no real-string or stress finding on /memory/graph; frontend/src/test/text-fit-memory.test.ts pins the .mg-scroll margins and padding with no -4px.
- [x] The empty graph's column titles ("Entities", "Observations") stay inside their ghost columns at 800 and 1024; no title runs past its column.
  - Verified: frontend/src/test/text-fit-memory.test.ts pins .mg-empty-col flex-basis:auto and the clipped, titled column headings; the narrow media query hides the ghost column.
- [ ] The graph's wide canvas either fits the page's text column at 1280 and 1920 or is declared a full-bleed region that does not make the page report an overflow; the choice is recorded in the ticket and in the evidence.
  - Partly: the choice is the wide document column (.doc.doc-wide:has(> #memory-graph-root) padding 0, #memory-graph-root width 100% and max-width 1128px, in frontend/src/memory/memory-graph.css), now recorded here; docs/evidence/2026-11-24-text-fit/EVIDENCE.md is not in this checkout.
- [x] The `.mg` and `.ml` island roots carry `overflow-wrap: anywhere` for prose, and the named text-holding flex and grid items get targeted `min-width: 0`.
  - Verified: frontend/src/test/text-fit-memory.test.ts asserts overflow-wrap:anywhere on .mg and .ml and the named min-width:0 items.
- [x] Rows that put text beside controls wrap, and chips stay inside their tiles; a compared figure (`.ml-figure`) keeps `nowrap` and does not break inside a number.
  - Verified: frontend/src/test/text-fit-memory.test.ts pins the .ml-row wrapping, the entity chip cap and .ml-figure nowrap.
- [ ] Under tripled strings the memory pages' findings are gone or lie only inside a deliberate scroller (baseline: 238 stress findings).
- [x] The graph's keyboard path, focus and accessible names survive the fix, and all three themes apply.
  - Verified: frontend/src/test/memory-graph.test.tsx covers the arrow-key path, Enter selection, the one tab stop and the titled pipeline counts; build/final-layout/20261124-195742 measured the graph under all three themes.
