# 02: The dashboard fits its text

**What to build:** at 800, 1024, 1280 and 1920, with real and tripled strings and in all three themes, every dashboard tile keeps its text inside its own box. The Desk health table fits its tile with all four columns readable; its times and item counts never print over the tracker; the tracker's title and Set up button stay in their own tile; a plugin tile's title and header wrap instead of collapsing or pushing the menu button off the screen; the open overflow menu stays inside the viewport; the Decisions rows put their actions on their own line when the side column is narrow; and no compared value, stamp or mono cell shows a word broken inside the line.

**Blocked by:** 01.

**Status:** in progress.

- [ ] At 1024 and 1280 with plugins and full, the "Competitor Watch" title is readable on its own line and the tile header is inside the tile, with no one-character-per-line column and no broken word.
- [ ] The tile menu button's right edge is inside the viewport at 1024, and opening the menu does not widen the document.
- [ ] The Desk health table fits its tile at every condition and width: all four columns are visible, the "Items" header stays in its column, and the time and item cells never print over the tracker figure or its title.
- [ ] The tracker title and its Set up action stay inside the tracker tile, and the Set up button does not intrude into the health tile.
- [ ] Decisions rows with data at 1024 keep their title and why line readable, put the actions on their own line when the side column is narrow, and keep the actions inside the card.
- [ ] The hero and tracker figures, stamps and mono cells keep `white-space: nowrap`; a value too long for its column scrolls inside its own wrapper and never breaks inside a number.
- [ ] The `.kpi .value` rule is declared once with one behaviour (nowrap), and the earlier conflicting declaration is gone.
- [ ] The dashboard stylesheet gives prose `overflow-wrap: anywhere` at the document root and gives the named text-holding flex and grid items `min-width: 0`; the change is selector by selector, not a universal reset.
- [ ] Under tripled strings, dashboard findings are gone or lie only inside a deliberate scroller (baseline: 170 stress findings).
- [ ] All three themes apply to the fixed dashboard, and `frontend/src/test/tokens.test.ts` still passes.
