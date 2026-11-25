# Spec 026: Text that fits every screen

**Status:** done (2026-11-24); evidence in `docs/evidence/2026-11-24-text-fit/EVIDENCE.md`. Filed as #303. Tickets: #304, #305, #306, #307, #308.
Ticket 01 landed at `3d942ed` and has no issue.
`GLOSSARY.md` is the vocabulary.
The layout audit's browser probe and the two stylesheets are the seams; no new product seam.

## Problem Statement

A manager on a corporate Windows laptop reads the desk at 1024 or 1280,
often with the browser at half the screen. On those widths the desk's text
does not fit. The layout audit measured 812 of 816 planned combinations on
main at `f31582a` (the four overlay states that need an installed plugin
are skipped), across fresh, data, plugins, full and legacy-dashboard; at
800, 1024, 1280 and 1920; in unkey, coforge and momentuum; with real
strings and with every string tripled.

The run found 2,596 findings: 2,584 layout and 12 runtime. The 12 runtime
rows are expected console 403s on `/marketplace/admin` when admin mode is
off. With real strings, 621 layout findings remain: 458 are `tiny-type`
(text under 11px, out of scope for this wave) and 163 sit in 16 root-cause
groups. Under tripled strings there are 1,963 findings in 97 stress-only
groups, by route: marketplace 1,023, server pages 532, memory pages 238,
dashboard 170.

The defects are not one bug repeated. A tile title loses its width to the
badges beside it, a four-column table is drawn wider than its card, a row
of text and buttons wraps without giving the buttons a line of their own,
a decorative stamp is squeezed into a 77px track, and a memory canvas
breaks out of its text column. The earlier waves fixed single symptoms and
left no rule, so the next surface repeated the defect. This wave writes
the rule and applies it everywhere.

### The sixteen real-string groups

The sixteen groups, with the worst measurement and the condition and
width where it was seen:

1. `squeezed-text` on `/what-this-touches`: the "not observed yet" badge
   wraps to 3 lines in a 78px cell in all four data conditions and at
   every width (`table.rows.touches > tbody > tr > td`;
   `src/agentdesk/server/touches.py:34`,
   `src/agentdesk/server/pages.py:250`).
2. `content-spill` in Desk health: the table runs about 130px past its
   tile at 1024 with plugins, and the tile overflows in all four
   conditions at 1024 and 1280 (`article.cell.cell-health.span-4`;
   `frontend/src/index.css:709-715`, `frontend/src/dashboard/cells.tsx:325-350`,
   `frontend/src/dashboard/Brief.tsx:284-289`).
3. `squeezed-text`: with plugins, the "Competitor Watch" tile title
   collapses to 0px wide and 15 line tops at 1024 and 1280
   (`div.w-head > h2`; `frontend/src/components/WidgetCard.tsx:201-205`,
   `frontend/src/index.css:305-306`).
4. `text-overlap`: the health table's time cells print over the Tracker
   tile's figure at 1024 (`td.num.mono`;
   `frontend/src/dashboard/cells.tsx:344`, `frontend/src/index.css:710`).
5. `offscreen-content`: the tile menu button's right edge sits at 1032px
   in a 1024 viewport with plugins (`button.icon-btn`;
   `frontend/src/components/WidgetCard.tsx:116-126`,
   `frontend/src/index.css:327-330`).
6. `text-overlap`: the tracker title prints under the health table's
   "Last run" column at `full`, 1024 (`div.tracker-title > h3`;
   `frontend/src/index.css:721-722`,
   `frontend/src/dashboard/cells.tsx:332`).
7. `text-overlap`: the health table's "Items" header prints over
   "Workbook tracker" at 1024 (`thead th.num`;
   `frontend/src/dashboard/cells.tsx:333`).
8. `offscreen-content`: the open tile menu widens the document to 1032px
   with plugins at 1024 (`button.w-menuitem`;
   `frontend/src/index.css:336-341`).
9. `squeezed-text`: the legacy server dashboard's "No calendar data"
   stamp wraps to 3 lines in a 77px header at 1024 (`span.stamp`;
   `src/agentdesk/server/pages.py:240-242`).
10. `broken-word`: "Competitor" splits across 10 lines in the same
    squeezed title (`frontend/src/components/WidgetCard.tsx:202`,
    `frontend/src/index.css:306`).
11. `content-spill`: decisions rows spill 28px at 1024 with data
    (`ul.decisions > li`; `frontend/src/index.css:643-646`,
    `frontend/src/dashboard/Brief.tsx:537-546`).
12. `content-spill`: the tile header overflows by 104px at 1024 with
    plugins (`div.w-head`; `frontend/src/index.css:305`,
    `frontend/src/components/WidgetCard.tsx:201`).
13. `content-spill`: `/memory/graph`, `div.mg-picture` has a 4px scroll
    overflow at every width with data
    (`frontend/src/memory/memory-graph.css:45,49`,
    `frontend/src/memory/MemoryGraph.tsx:403-411`).
14. `content-spill`: `/memory/graph` empty state, the column title
    "Observations" runs up to 10px past its ghost column at 800 and 2px
    at 1024 (`span.mg-col-title`;
    `frontend/src/memory/memory-graph.css:47-48,131`,
    `frontend/src/memory/MemoryGraph.tsx:191`).
15. `content-spill`: `/memory/graph`, the graph section is 974px wide
    inside a 720px text column at 1280 and 1128px at 1920 (`div.doc`;
    `frontend/src/memory/memory-graph.css:13-15`). The stylesheet makes
    this a deliberate full-bleed canvas, so ticket 05 keeps that intent
    without a page overflow.
16. `control-collision`: the tracker's "Set up" button intrudes into the
    health tile at 1024 with plugins (`td.num.mono` and
    `button.btn.btn-primary.btn-sm`; `frontend/src/dashboard/cells.tsx:344,355-371`).

Groups 2, 4, 6, 7 and 16 share one cause, the Desk health table.

### The drift the wave closes

The server sheet in `src/agentdesk/server/pages.py` (`STYLES`) is behind
the SPA sheet in `frontend/src/index.css` on the same contract:

- `.decisions li` has the spec 020 `flex-wrap: wrap` only in the SPA
  sheet (`pages.py:292`, `index.css:643`), and the server sheet's
  `.decision-text` has no `flex: 1 1 220px` and `.decision-actions` has
  no `flex-wrap: wrap` (`pages.py:294,297` versus `index.css:645-646`).
- `.btn` has `white-space: nowrap` only in the SPA sheet
  (`pages.py:228`, `index.css:480-484`).
- `table.rows td` has `overflow-wrap: anywhere` only in the SPA sheet
  (`pages.py:252`, `index.css:389`).
- `.well-input` has `min-width: 0` only in the SPA sheet
  (`pages.py:271`, `index.css:453-456`).
- The server sheet has no `.nowrap` helper (`index.css:956`).
- The server sheet's `.kpi .value` still carries
  `overflow-wrap: anywhere` (`pages.py:246`), while the SPA sheet's later
  rule is `white-space: nowrap` (`index.css:575`).

`.kpi .value` is also declared twice in `index.css`: the rule at
`index.css:370-374` carries `overflow-wrap: anywhere`, and the later rule
at `index.css:573-576` carries `white-space: nowrap`. The later rule wins
today; the wave leaves one rule with one behaviour. Both root overflow
rules stay as they are: the SPA `body` hides horizontal overflow
(`index.css:121-129`), the server `body` does not (`pages.py:77`). Causes
are fixed, not masked.

### The calendar walkthrough defect

`/walkthrough/calendar` answers HTTP 500 when `AGENTDESK_CALENDAR_FILE`
is pinned to an empty string, which is the documented demo and test boot.
`default_calendar_hint` falls back to `candidates[0]`, and
`default_calendar_candidates()` returns an empty list for that pin
(`src/agentdesk/server/app.py:8380-8395`,
`src/agentdesk/calendar/watcher.py:74-94`). The handler is
`app.py:1557-1568`; the empty pin is already pinned at the candidates
level by `tests/test_calendar_paths.py:59-67`.

## Solution

The fix has two layers. First, one rule set is applied to every surface:
the SPA document root, the server sheet's document root, the marketplace
roots, and the `.mg` and `.ml` memory islands. That layer clears the
tripled-string class, where the defect is not a particular table but prose
that cannot break, a flex item that cannot shrink, a row that cannot wrap,
or a chip that cannot drop. Second, targeted fixes close the 16
real-string groups: eleven on the dashboard, two on the server-rendered
pages, three on the memory pages.

The server sheet catches up to the SPA sheet on the four rules it missed,
gains the `.nowrap` helper, and stops breaking a compared value. The
calendar walkthrough answers 200 with no calendar when its file is pinned
empty.

Type sizes do not change. No page gains `overflow-x: hidden`; the SPA
root keeps the one it has, and the server root keeps not having one.

After the wave the identical audit on the merged tree reports zero
real-string layout findings of every kind except `tiny-type` (the 12
expected runtime rows on `/marketplace/admin` are unchanged); tripled
findings remain only inside deliberate scrollers; no compared value,
stamp, code, button or mono cell shows a broken word; all three themes
apply; coverage is complete; the committed SPA bundle is rebuilt from the
merged source; the local gate passes 7/7; and the before and after
evidence is under `docs/evidence/2026-11-24-text-fit/`.

## User Stories

1. As a manager at 1024 with plugins installed, I want the "Competitor Watch" title to read as words, so that I can tell which plugin the tile belongs to.
2. As a manager, I want a tile title beside its badge, stamp and menu to wrap onto a second line rather than collapse to one character per line, so that the title is still a title.
3. As a manager, I want a tile's menu button to stay inside the window, so that the control I need is not past the edge.
4. As a manager, I want an open tile menu to stay inside the window too, so that the page does not gain a sideways scrollbar when I open it.
5. As a manager, I want the Desk health table to fit inside its tile with all four columns, so that I can read which source is live without the table running under the next tile.
6. As a manager, I want the "Items" header to stay over its own column, so that the count is not read as part of the tracker's title.
7. As a manager, I want the health table's times and counts to stay in the health tile, so that they do not print over the pipeline figure.
8. As a manager, I want the tracker's title and Set up action to stay in the tracker tile, so that the two tiles do not read as one.
9. As a manager, I want the Set up button to stay away from the health table, so that I do not click the wrong surface.
10. As a manager with data at 1024, I want the Decisions rows to put their buttons on a new line instead of pushing the text out of the card, so that I can read the decision and still act on it.
11. As a manager, I want a decision's title and reason to keep a readable measure, so that the side column is not one word per line.
12. As a manager reading `/what-this-touches`, I want the "not observed yet" badge on one line and its table inside the page, so that the IT statement is readable at a glance.
13. As a manager on the legacy server dashboard, I want "No calendar data" to stay whole in its header, so that the fallback page does not turn a stamp into three lines.
14. As a manager reading the memory graph, I want the picture to stop moving by 4px sideways, so that the graph feels still.
15. As a manager looking at an empty memory graph, I want the ghost column titles to stay over their columns, so that the empty state explains the layout it is about to fill.
16. As a manager, I want the wide memory graph to keep its deliberate full-bleed shape without making the page scroll sideways, so that the graph is wide because it is the point, not because it escaped its column.
17. As a manager with a long plugin name, publisher, version or tag on the marketplace, I want the words to wrap inside the card, so that no card grows a sideways scrollbar.
18. As a manager with a long plugin description in Detail or Pack, I want the text column to keep a readable width while the actions wrap below, so that an action never squeezes the description to one word per line.
19. As a manager with a long scope, failure code or manifest line, I want that block to scroll inside its own box, so that the page never scrolls sideways to reach it.
20. As a manager, I want every ellipsis on a marketplace value to have a title or accessible name with the full value, so that a shortened plugin id or digest is recoverable.
21. As a manager, I want the same wrapping behaviour on the server-rendered settings, agents, assistant, inbox, mail, capabilities and walkthrough pages as on the SPA, so that the product does not change its rules when JavaScript is unavailable.
22. As a manager, I want prose to break rather than overflow on every surface, so that a long unbroken word does not push a tile wider than the page.
23. As a manager, I want a flex or grid item that holds text to shrink, so that one stubborn item does not force its row wider than the card.
24. As a manager, I want a row of text beside controls to wrap before it squeezes the text, so that the words stay readable and the controls stay whole.
25. As a manager, I want a chip, pill, badge or stamp to drop to its own line before it leaves the card, so that a short state word is not cut off.
26. As a manager, I want a compared value, a stamp, a code token, a button label and a mono table cell to stay whole, so that I never read a number or an identifier that was broken inside the line.
27. As a manager, I want a table that cannot fit its column to scroll inside its own wrapper, so that the page itself never scrolls sideways.
28. As a manager, I want a table that should fit its tile to use a fixed layout with wrapping cells, so that all columns stay visible and the tile keeps its shape.
29. As a manager, I want the calendar walkthrough to open even when the calendar is pinned empty, so that the documented demo and test boot do not show a server error.
30. As a manager, I want all three themes to keep the fixed text readable, so that a fix in Unkey does not fail in Coforge or Momentuum.
31. As a maintainer, I want the seven text-fit rules written in the design language, so that the next wave starts from a rule and not from a screenshot.
32. As a maintainer, I want the layout audit to be one command that reports coverage and writes pictures, so that before and after are comparable.
33. As a security reviewer, I want the audit to stay out of the gate and add no runtime dependency to the app, so that the 7/7 gate stays deterministic and the product's dependency surface does not grow.
34. As a maintainer, I want the committed SPA bundle rebuilt from the merged source, so that the shipped dashboard is the one the audit measured.
35. As a maintainer, I want the before and after evidence in one folder, so that the wave's claim is checkable without rerunning the audit.

## Implementation Decisions

### Two layers, and what a fix may not do

The rule set is applied to every surface and clears the tripled-string
class. The targeted fixes close the 16 real-string groups. A fix may not
trade overflow for words broken inside a line: the audit has a
`broken-word` detector, and a compared value, a stamp, code, a button or a
mono table cell may never show one. `min-width: 0` is targeted, selector
by selector, not a universal reset: an advisor reviewed the code and
found that non-text items rely on the automatic minimum.

### The rule set

R1. Prose breaks rather than overflows. `overflow-wrap: anywhere` on each
surface's root: `body` in `index.css`, `body` in the server `STYLES`, the
marketplace roots in `marketplace.css`, and the `.mg` and `.ml` island
roots. It is inherited and only breaks a word that would by itself
overflow. Compared values (`.kpi .value`, `.figure`, `.hero-stats dd`,
`.ml-figure`, numeric table cells), stamps in fixed tracks (`.stamp`,
`.digest-src`, `.digest-time`, `.stage-axis small`), `pre` and code that
must scroll (`overflow-wrap: normal` plus a wrapper that scrolls), and
identifiers a person must match exactly (the calendar file name, spec 003)
keep `white-space: nowrap` and are handled by R3 to R6.

R2. A flex or grid item that holds text can shrink: `min-width: 0` on that
item, paired with R1. Targeted, selector by selector, never a universal
`* { min-width: 0 }`.

R3. A row that puts text beside controls wraps before it squeezes the
text: `flex-wrap: wrap` on the row, `flex: 1 1 220px` on the text
(`flex: 1 1 120px` for a card title in a narrow card), `flex: none` on
each control or control group. A wrapping text column never collapses
below about 120px.

R4. A chip (pill, badge, tag, stamp) never leaves its card: it drops to
its own line before it is squeezed (`flex-wrap` on its row,
`max-width: 100%` on the chip). A single token longer than the card breaks
by R1. A short badge whose phrase must stay on one line gets
`white-space: nowrap` and its container makes room for it.

R5. Truncation is absent or reachable: where an ellipsis or a line clamp
hides part of a value, the full value is reachable (a `title`, an
`aria-label`, or a focusable or titled ancestor). Wrap or scroll is
preferred when the value matters.

R6. A table, `pre` or digest block that cannot fit its column scrolls
inside its own wrapper (`overflow-x: auto`), never the page, and its cells
stay `white-space: nowrap`. A table that should fit its card instead uses
`table-layout: fixed; width: 100%` with wrapping cells so every column
stays visible.

R7. The wrap contract holds on the same selectors in both style sheets,
the SPA `index.css` and the server `STYLES`, including rules that exist in
one sheet only today.

Both root overflow rules stay as they are (the SPA body hides horizontal
overflow; the server body does not): causes are fixed, not masked.

### Dashboard

- `body` in `index.css` gains `overflow-wrap: anywhere` and keeps its
  existing `overflow-x: hidden` (`index.css:121-129`).
- The tile header row (`.w-head`, `index.css:305`) becomes a wrapping flex
  row. The title gets `flex: 1 1 120px` and keeps `min-width: 0`; the
  badge, stamp and overflow menu are `flex: none` and may drop to their
  own line. The badge and stamp get `max-width: 100%`. The title stops
  collapsing to 0px and the menu button stays inside the viewport; the
  open menu keeps `right: 0` and no longer widens the document.
- The health matrix (`.matrix`, `index.css:709-715`) changes from an auto
  table with `white-space: nowrap` on every cell to a fixed-layout table
  that fits its tile, with named column widths for source, status, last
  run and items. The source and status cells wrap; the two numeric columns
  keep `white-space: nowrap` and get enough width for a whole time and a
  whole count. The table sits inside the tile, not in a scroller. This one
  fix clears the table spill, the two overlaps and the control collision
  (groups 2, 4, 6, 7 and 16).
- The tracker title and the wire card's Set up action stay inside the
  tracker tile once the health table stops extending into it. The tracker
  title row wraps, and its text gets the R3 basis.
- The Decisions row keeps the spec 020 wrap (`index.css:643-646`). In the
  narrow side column the actions get their own line, the action group can
  wrap its buttons, and neither the group nor the text goes below the
  120px floor. The title and reason stay readable.
- `.kpi .value` is one rule with `white-space: nowrap`, not a duplicate
  with `overflow-wrap: anywhere` and a later `nowrap`. `.figure` and
  `.hero-stats dd` get `white-space: nowrap`. A compared value that cannot
  fit its track under the tripled pass scrolls inside a small wrapper; it
  is never broken inside the number.
- The hero and tracker figures keep their existing grid tracks, which
  already allow the text column to shrink (`index.css:570-571`).

### Marketplace

- `.mkt-main` and `.mkt-page` (`marketplace.css:5,52`) carry the R1 root
  rule for prose.
- Text-holding flex and grid items get R2's `min-width: 0` one at a time:
  the card identity block, the detail title, the sample block, the
  installed head and the pack member rows.
- Rows that put text beside controls follow R3, including the detail head,
  the actions row, the installed head and the update row. Chips and tags
  follow R4, including the tag row, the version chip and the scope chips.
- `.mkt-manifest` already scrolls (`marketplace.css:550-552`); any other
  table or block that cannot fit follows R6 with its own wrapper.
- Every existing ellipsis on a marketplace value gets a `title` or an
  accessible full value per R5.

### Server pages

- `body` in the server `STYLES` (`pages.py:77`) gains
  `overflow-wrap: anywhere` and does not gain `overflow-x: hidden`.
- `.touch-badge` (`pages.py:313`) gets `white-space: nowrap` and
  `max-width: 100%`; the touches table (`pages.py:250-255`) gets a fixed
  layout with wrapping prose cells and a column wide enough for the badge.
- The server `.w-head` (`pages.py:240-241`) wraps; its title gets the R3
  basis and the R1 break; `.stamp` (`pages.py:242`) gets
  `white-space: nowrap`, `flex: none` and `max-width: 100%`. The legacy
  dashboard's "No calendar data" stamp stays whole.
- `.decisions li`, `.decision-text` and `.decision-actions` get the same
  wrap contract as the SPA (`pages.py:292-298`).
- `.btn` gains `white-space: nowrap`; `table.rows td` gains
  `overflow-wrap: anywhere`; `.well-input` gains `min-width: 0`; the sheet
  gains `.nowrap`.
- `.kpi .value` (`pages.py:246`) becomes `white-space: nowrap`, matching
  the SPA sheet; it is a compared value under R1.
- `default_calendar_hint` returns no path, not `candidates[0]`, when the
  candidate list is empty (`app.py:8380-8395`). The walkthrough page
  renders its no-calendar state and answers 200 (`app.py:1557-1568`).

### Memory

- `#memory-graph-root .mg` and `#memory-loop-root .ml` carry the R1 root
  rule (`memory-graph.css:20`, `memory-loop.css:7`).
- `.mg-picture` loses its 4px sideways bleed: the picture is clamped to
  its canvas and the scroll gutter no longer extends the parent
  (`memory-graph.css:45,49`).
- The empty-state ghost columns keep their titles inside their columns,
  either by giving the title an R1 break with a sensible floor or by
  hiding the decorative ghost at the width where it no longer fits
  (`memory-graph.css:47-48,129-131`).
- The wide graph canvas keeps its deliberate full-bleed shape without
  being a child that spills out of the 720px text column. Ticket 05
  records which of the two ways it took: the graph stays full-bleed as a
  sibling of the text column, or it fits the text column.
- The memory loop's figures (`.ml-figure`) keep `white-space: nowrap` and
  the surrounding rows follow R3 and R4.

### The audit stays out of the gate

The layout audit is not wired into `tools/ci_local.py` in this wave and
Playwright is not added to `pyproject.toml`. The local gate's contract is
`7/7` (`tools/ci_local.py:241-249`); server pages use the operating
system's fonts, so Windows and macOS would measure differently; the
browser build is not pinned; and there is no committed findings baseline
yet. Those four conditions are the follow-up work, not this wave's work.

### The clearing run

Ticket 06 merges the four surface branches, rebuilds the SPA bundle once
from the merged source, and re-runs the identical unfiltered audit:

    uv run --no-project --with playwright --with keyring --with cryptography python tools/layout_audit.py

It needs a one-time `uv run --no-project --with playwright python -m
playwright install chromium`. A full run takes about 10 minutes. The
evidence pack is `docs/evidence/2026-11-24-text-fit/EVIDENCE.md` with the
before and after counts, the commands, the run folders and the
screenshots. The before baseline is the run folder `20261124-150340`
under the layout audit's output directory.

### Ticket 01 is done

Ticket 01, the layout audit tool, landed at `3d942ed` and has no issue.
The tool is 2,407 lines and is the only file that commit adds.

## Testing Decisions

A good test asserts what a person sees: which text stays whole, which row
wraps, which table stays in its card, which control stays inside the
window. It does not assert private helper names, computed pixel widths in
the SPA, or a screenshot as the only proof. The browser audit measures
pixels; the test suite pins declarations and observable structure.

- The CSS contract suite is the model. `frontend/src/test/tokens.test.ts`
  reads the style source and asserts exact declarations; its `decl()`
  helper (`tokens.test.ts:288-292`) reads only the first rule matching a
  selector, and `onGrid()` (`tokens.test.ts:294-298`) checks the 4px
  rhythm. Extend it with the declarations this wave adds:
  `overflow-wrap` on the two document roots and the island roots;
  `min-width` on the named text-holding items; `flex-wrap` and `flex` on
  the named rows; `white-space` on the compared values, stamps, code and
  numeric cells; `table-layout` and `width` on the health matrix and the
  touches table. The existing server-sheet contract in the same suite
  reads `pages.py` and must pin the same selectors, so R7 is a test and
  not a review note.
- Component tests use `@testing-library/react` with role and behaviour
  assertions; `frontend/src/test/brief-decisions.test.tsx` is the prior
  art. A Decisions test renders a narrow side column and asserts the
  actions are in the row and the text is not clipped; a tile-header test
  renders a long title beside a badge, a stamp and a menu and asserts the
  menu button is present and named. These tests drive the public
  component, not its CSS.
- Server tests read rendered HTML and the served stylesheet through
  `tests/server_harness.py`, which never touches the real data folder or
  the real keychain; `tests/test_server_shell.py` and
  `tests/test_ui_wave2.py` are the prior art. Add assertions that
  `/what-this-touches` renders the badge as one element inside its table
  cell, that the served server sheet carries the R7 declarations, and that
  `/walkthrough/calendar` answers 200 with an empty calendar pin.
- The calendar fix gets a failing-first test through the route, not only
  the candidate helper: the empty pin answers 200 with the no-calendar
  sentence. The existing candidate test at
  `tests/test_calendar_paths.py:59-67` stays green.
- Every fix ships with a failing-first test; the red evidence is kept in
  the pull request.
- Hosted CI already checks that the committed bundle matches the source
  in `.github/workflows/enterprise.yml:100-117` (the `frontend-build` job).
  Ticket 06 runs that check on the merged tree.

## Out of Scope

- Type sizes, including the 458 `tiny-type` findings. They are a candidate
  next wave, not this wave's work.
- Wiring the layout audit into `tools/ci_local.py` or adding Playwright to
  `pyproject.toml`. The four conditions are recorded in Implementation
  Decisions as follow-up work.
- The 12 runtime 403s on `/marketplace/admin` when admin mode is off.
  They are expected and are not layout findings.
- The 4 skipped overlay states that need an installed plugin. They are
  listed as skipped, not as a coverage failure.
- A visual redesign of the bento, the marketplace, the memory graph or the
  server pages. This wave fixes fit, not composition.
- Changing the SPA body's `overflow-x: hidden` or adding one to the server
  body.
- Fixing the 23 retired plugin trees under `archive/plugins/`.
- A second browser engine, a hosted audit job, or a macOS pixel baseline.
- Product copy changes beyond the no-calendar sentence the walkthrough
  already has.

## Further Notes

### The full-bleed memory graph

The 974px and 1128px measurements are not an accident:
`#memory-graph-root` sets `width: min(1128px, calc(100vw - 306px))` and
centres itself out of the doc column (`memory-graph.css:13-15`). The
screenshot confirms the intent. The open question is how the wave keeps
it without a page overflow: the graph can stay full-bleed as a sibling of
the 720px text column (it fits the 1,008px content box at 1280 and the
1,128px content box at 1920), or it can fit the text column and lose the
full-bleed look. Recommendation: keep the full-bleed look by moving the
graph out of the narrow column, not by adding an audit exemption. An
exemption would hide a real page overflow at another width.

### The after run's platform

The audit runs in Chromium through Playwright on this Windows machine.
Server pages use the operating system's fonts, so a macOS run would
measure different widths. Recommendation: record the OS, the Playwright
version and the Chromium version in `EVIDENCE.md`, and treat the Windows
corporate laptop as the acceptance platform. A second platform is a
follow-up, not a second acceptance gate.

### The follow-up gate work

The audit stays manual until four conditions hold: the local gate's
contract stops being `7/7`, or the audit joins it as an eighth gate; the
font measurement is pinned across platforms; the browser build is pinned;
and a findings baseline is committed. Until then, the audit is a tool a
person runs, and ticket 06 records its output.

### The tiny-type candidate

The 458 real-string `tiny-type` findings split 74 at 10px and 384 at
10.5px. They cluster on tags, stamps and field hints, with 118 on the
dashboard and 180 on the memory pages, plus the marketplace plugin pages.
They are a legibility issue, not an overflow issue, and they get their own
wave.

### What the audit's expected rows mean

The 12 runtime rows are console 403s from `/marketplace/admin` when admin
mode is off. The 4 skipped states are `overlay-widget-menu` on fresh and
data at 1024 and 1280, which need an installed plugin. Neither is a defect
and neither may be quoted as a fix.

### The health table's shape

The health table is the one table in this wave that should fit its card
rather than scroll. Its four columns are short, and a scroller would hide
the "Last run" and "Items" comparison the tile exists to show. The fixed
layout with named widths is the decision; the numeric columns keep
`nowrap` and the prose columns wrap. The audit's `table-layout` check and
the browser measurement are the proof.
