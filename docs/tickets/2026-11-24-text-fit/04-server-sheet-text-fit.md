# 04: Server pages fit their text, and the calendar walkthrough survives an empty pin

**What to build:** the server-rendered pages use the same text-fit contract as the SPA sheet: prose breaks rather than overflowing, text-holding items can shrink, rows wrap before they squeeze, chips stay in their cards, and tables or code scroll in their own wrapper. The `/what-this-touches` badge stays on one line and its table stays inside its column, and the legacy server dashboard's "No calendar data" stamp no longer wraps to three lines. Separately, `/walkthrough/calendar` answers 200 with an empty calendar when `AGENTDESK_CALENDAR_FILE` is pinned to an empty string, which is the documented demo and test boot; it no longer answers 500.

**Blocked by:** 01.

**Status:** done (2026-11-24).

- [x] `/what-this-touches` renders the "not observed yet" badge whole and inside its column at 800, 1024, 1280 and 1920; it no longer wraps to three lines in a 78px cell.
  - Verified: tests/test_ui_text_fit.py::test_the_touches_badge_phrase_is_rendered_whole; build/final-layout/20261124-195742 has no real-string finding on /what-this-touches at any width.
- [x] With no plugins, the legacy server dashboard's stamp reads whole in its header at 1024; the header row wraps rather than squeezing it to three lines.
  - Verified: build/final-layout/20261124-195742/findings.legacy-dashboard.json is empty at 1024 and 1280; the server sheet wraps .w-head and keeps .stamp in its own scroller.
- [x] The server sheet and the SPA sheet agree on `.decisions li`, `.decision-text`, `.decision-actions`, `.btn`, `table.rows td`, `.well-input`, `.kpi .value` and the `.nowrap` helper; the server sheet has the wrap fixes the SPA sheet already has, and the shared contract test reads both sheets.
  - Verified: tests/test_ui_text_fit.py::test_the_server_sheet_matches_the_spa_wrap_contract reads both pages.STYLES and the SPA sheet; the named selectors are present in both.
- [x] The server body's root overflow stays as it is (no horizontal overflow hidden), because the causes are fixed and not masked.
  - Verified: src/agentdesk/server/pages.py body has no overflow-x:hidden; the table and identifier scrollers carry the long content.
- [x] At 800, 1024, 1280 and 1920 the server pages' text stays inside its columns; a table that cannot fit scrolls inside its own wrapper and not the page.
  - Verified: build/final-layout/20261124-195742 has no real-string finding on the server pages at 800, 1024, 1280 and 1920; the stress squeeze is inside .table-scroll.
- [x] Under tripled strings the server pages' findings are gone or lie only inside a deliberate scroller (baseline: 532 stress findings).
  - Verified: build/last-layout/20261124-211432 has 40 tripled-string findings on server pages, all `squeezed-text` in table cells inside their own `div.table-scroll` wrapper on `/settings/activity` (20) and `/what-this-touches` (20): a tripled word wraps one word per line inside the table that scrolls, and the page does not scroll (rule R6). The main baseline with the same instrument had 70 outside the 11px class.
- [x] `/walkthrough/calendar` answers 200 with `AGENTDESK_CALENDAR_FILE=""` and says there is no calendar; the hint never indexes an empty candidate list.
  - Verified: tests/test_calendar_paths.py::test_the_walkthrough_says_reading_is_off_when_the_calendar_is_pinned_off and test_an_empty_pin_names_no_hint.
- [x] A failing-first test pins the empty pin through the route, and the existing candidate test that an empty override means no calendar stays green.
  - Verified: tests/test_calendar_paths.py (16 passed) pins the route, and test_an_empty_override_means_no_calendar stays green.
- [x] All three themes apply to the fixed server pages.
  - Verified: build/final-layout/20261124-195742 measured coforge, momentuum and unkey on the server pages with complete coverage.
