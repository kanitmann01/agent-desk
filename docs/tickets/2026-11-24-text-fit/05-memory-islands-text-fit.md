# 05: The memory page fits its text

**What to build:** the memory graph and the memory loop keep their text inside their islands at 800, 1024, 1280 and 1920: the graph's picture no longer carries a 4px sideways scroll, the empty state's column titles stay in their ghost columns, and the graph's wide canvas is a deliberate full-bleed region rather than a child that spills out of the 720px text column. The `.mg` and `.ml` roots carry the wrap contract, and under tripled strings their findings are gone or inside a deliberate scroller.

**Blocked by:** 01.

**Status:** in progress.

- [ ] `/memory/graph` with data has no 4px scroll overflow on the picture at any width.
- [ ] The empty graph's column titles ("Entities", "Observations") stay inside their ghost columns at 800 and 1024; no title runs past its column.
- [ ] The graph's wide canvas either fits the page's text column at 1280 and 1920 or is declared a full-bleed region that does not make the page report an overflow; the choice is recorded in the ticket and in the evidence.
- [ ] The `.mg` and `.ml` island roots carry `overflow-wrap: anywhere` for prose, and the named text-holding flex and grid items get targeted `min-width: 0`.
- [ ] Rows that put text beside controls wrap, and chips stay inside their tiles; a compared figure (`.ml-figure`) keeps `nowrap` and does not break inside a number.
- [ ] Under tripled strings the memory pages' findings are gone or lie only inside a deliberate scroller (baseline: 238 stress findings).
- [ ] The graph's keyboard path, focus and accessible names survive the fix, and all three themes apply.
