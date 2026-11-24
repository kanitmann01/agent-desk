# 04: Server pages fit their text, and the calendar walkthrough survives an empty pin

**What to build:** the server-rendered pages use the same text-fit contract as the SPA sheet: prose breaks rather than overflowing, text-holding items can shrink, rows wrap before they squeeze, chips stay in their cards, and tables or code scroll in their own wrapper. The `/what-this-touches` badge stays on one line and its table stays inside its column, and the legacy server dashboard's "No calendar data" stamp no longer wraps to three lines. Separately, `/walkthrough/calendar` answers 200 with an empty calendar when `AGENTDESK_CALENDAR_FILE` is pinned to an empty string, which is the documented demo and test boot; it no longer answers 500.

**Blocked by:** 01.

**Status:** in progress.

- [ ] `/what-this-touches` renders the "not observed yet" badge whole and inside its column at 800, 1024, 1280 and 1920; it no longer wraps to three lines in a 78px cell.
- [ ] With no plugins, the legacy server dashboard's stamp reads whole in its header at 1024; the header row wraps rather than squeezing it to three lines.
- [ ] The server sheet and the SPA sheet agree on `.decisions li`, `.decision-text`, `.decision-actions`, `.btn`, `table.rows td`, `.well-input`, `.kpi .value` and the `.nowrap` helper; the server sheet has the wrap fixes the SPA sheet already has, and the shared contract test reads both sheets.
- [ ] The server body's root overflow stays as it is (no horizontal overflow hidden), because the causes are fixed and not masked.
- [ ] At 800, 1024, 1280 and 1920 the server pages' text stays inside its columns; a table that cannot fit scrolls inside its own wrapper and not the page.
- [ ] Under tripled strings the server pages' findings are gone or lie only inside a deliberate scroller (baseline: 532 stress findings).
- [ ] `/walkthrough/calendar` answers 200 with `AGENTDESK_CALENDAR_FILE=""` and says there is no calendar; the hint never indexes an empty candidate list.
- [ ] A failing-first test pins the empty pin through the route, and the existing candidate test that an empty override means no calendar stays green.
- [ ] All three themes apply to the fixed server pages.
