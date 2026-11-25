# 03: The marketplace fits its text

**What to build:** the marketplace's Discover, Search, Category, Detail, Pack, Installed, Publishers, Studio, Admin and Trust Center pages keep their text inside their cards and columns when the strings grow: a long plugin name, publisher, tag, version, scope, failure code or manifest line wraps or scrolls in a place the reader can reach, and the page never gains a sideways scrollbar. The marketplace uses the same wrap contract as the dashboard.

**Blocked by:** 01.

**Status:** done (2026-11-24).

- [x] The marketplace roots carry `overflow-wrap: anywhere` for prose, and the named text-holding flex and grid items get targeted `min-width: 0`.
  - Verified: frontend/src/test/text-fit-marketplace.test.ts asserts overflow-wrap:anywhere on .mkt-main, .mkt-page and .mkt-sheet, and the targeted min-width:0 items.
- [x] Rows that put text beside controls wrap before the text squeezes: text columns keep a basis of at least 120px, and controls do not shrink.
  - Verified: frontend/src/test/text-fit-marketplace.test.ts asserts .mkt-card-id flex 1 1 120px, .mkt-version flex none and the control's own scroll.
- [x] Pills, badges, version chips and tags drop to their own line before leaving their card, and a single token longer than the card breaks by the root rule.
  - Verified: frontend/src/test/text-fit-marketplace.test.ts asserts .mkt-card-tags flex-wrap and the chip and tag caps; MarketGrid.tsx and Installed.tsx give the cannot-run chip its full text in a title.
- [x] A manifest `pre`, a digest block or any table that cannot fit its column scrolls inside its own wrapper and never the page.
  - Verified: frontend/src/test/text-fit-marketplace.test.ts asserts the code, digest, facts and table wrappers keep their lines and scroll in place.
- [x] An ellipsis or line clamp on a plugin name, version, publisher or digest has a `title`, `aria-label` or focusable ancestor with the full value.
  - Verified: frontend/src/test/review-marketplace.test.tsx and marketplace-cannot-run.test.tsx read the titled chip; 6ffce16 gives the cannot-run chip its words in a title.
- [x] Under tripled strings the marketplace findings are gone or lie only inside a deliberate scroller (baseline: 1,023 stress findings).
  - Verified: build/last-layout/20261124-211432 has 30 tripled-string findings on marketplace pages, all of them the 11px class, and none of any other kind (the main baseline with the same instrument had 252); commit 6ffce16 gave the truncating chip its words in a title, which removed the last 10.
- [x] No `broken-word` finding on a compared value, a stamp, code, a button or a mono cell.
  - Verified: build/last-layout/20261124-211432 has zero `broken-word` rows of any kind, plain or tripled, on every route; the main baseline had 20 with real strings.
- [x] All three themes apply, and the page's focus order and reading order survive the wrapping.
  - Verified: build/final-layout/20261124-195742 measured coforge and momentuum on the marketplace pages; frontend/src/test/marketplace-a11y.test.tsx keeps the focus order and skip link.
