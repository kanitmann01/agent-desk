# 03: The marketplace fits its text

**What to build:** the marketplace's Discover, Search, Category, Detail, Pack, Installed, Publishers, Studio, Admin and Trust Center pages keep their text inside their cards and columns when the strings grow: a long plugin name, publisher, tag, version, scope, failure code or manifest line wraps or scrolls in a place the reader can reach, and the page never gains a sideways scrollbar. The marketplace uses the same wrap contract as the dashboard.

**Blocked by:** 01.

**Status:** in progress.

- [ ] The marketplace roots carry `overflow-wrap: anywhere` for prose, and the named text-holding flex and grid items get targeted `min-width: 0`.
- [ ] Rows that put text beside controls wrap before the text squeezes: text columns keep a basis of at least 120px, and controls do not shrink.
- [ ] Pills, badges, version chips and tags drop to their own line before leaving their card, and a single token longer than the card breaks by the root rule.
- [ ] A manifest `pre`, a digest block or any table that cannot fit its column scrolls inside its own wrapper and never the page.
- [ ] An ellipsis or line clamp on a plugin name, version, publisher or digest has a `title`, `aria-label` or focusable ancestor with the full value.
- [ ] Under tripled strings the marketplace findings are gone or lie only inside a deliberate scroller (baseline: 1,023 stress findings).
- [ ] No `broken-word` finding on a compared value, a stamp, code, a button or a mono cell.
- [ ] All three themes apply, and the page's focus order and reading order survive the wrapping.
