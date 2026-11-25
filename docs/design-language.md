# Design language: Agent Desk

One bento language, three themes. This document describes the system the
code ships; when it disagrees with the code, the code wins and this file
gets fixed. The truth lives in three places, and the tests hold them
together:

- `frontend/src/index.css`: the SPA stylesheet, one semantic token set per
  theme. No component carries a hex.
- `src/agentdesk/server/pages.py` (`STYLES`): the server-rendered
  fallback's own statement of the same system (the same palette, radii and
  rules under the coarser bg/surface/ink names), so the no-JavaScript
  pages speak the same language. The token suite reads it out of the
  Python source and holds the two sheets to the same contract.
- `frontend/src/test/tokens.test.ts`: the design contract suite. It
  enforces the tokens, the banned effects and the interaction promises
  described below.

## Thesis

A quiet instrument, dark by default: near-black canvas, 1px rules, Geist
and Geist Mono, one accent per theme doing all the pointing. Hierarchy
comes from spacing, weight and a four-level ink ramp, never from shadow or
glass. The work is louder than the chrome.

## Shared tokens

```css
:root {
  --shadow-card: none;  --shadow-card-hover: none;
  --r-card: 8px;  --r-control: 6px;  --r-inner: 4px;  --r-pill: 6px;
  --dur: 120ms;
  --font-ui: "Geist", "Segoe UI", sans-serif;
  --font-mono: "Geist Mono", "Consolas", monospace;
}
```

## Themes

A theme is one token block; the user picks it in Settings from three
tiles, and `theme-boot.js` applies it before first paint (the server pages
carry a byte-identical copy of that script, pinned by a test).

- **Unkey** (default, dark): near-black canvas `#060609`, surfaces
  `#0C0C0F`/`#101014`/`#16161A`, text `#FBFBFB`, one yellow-green
  highlighter accent `#E1F56A`. The only theme with the dot cell texture
  and the radial light on the hero.
- **Coforge** (dark): navy canvas `#082340`, coral accent `#F15840`, the
  brand gray ramp for muted text. Flat.
- **Momentuum** (light): light canvas `#F3F6FA`, white cells, navy
  headings `#082340`, brand blue `#2470B0` as the one accent; orange
  `#F75C1F` appears only as the live dot.

Every theme declares its `color-scheme`; text, rules and focus are
readable by construction because components read only the semantic tokens
(canvas, surface, rule, text, muted, accent, focus, heading and their
derived steps).

## Type

- Words: **Geist** (self-hosted via Fontsource, 400 to 600); Momentuum
  headings switch to **Montserrat** 700. Fallbacks are local system faces
  (`Segoe UI`); nothing is fetched from the network.
- Numerals: **Geist Mono**, tabular, everywhere a value is compared
  (counts, times, deltas).
- Fixed sizes, no `clamp()`: the greeting is 40px, the one dashboard
  figure is 56px, and nothing else is bigger.

## Layout

A 200px word rail beside a content column capped at 1200px, on a
28/36/60px spacing rhythm. The rail is words: the current page carries the
accent edge and stays pinned and wrapping at every width. Cards are 8px
concentric radii (controls 6px, inner wells 4px, pill 6px) on `#26272A`
rules, with no shadow at rest and none on hover.

## Layout and text fit

Text fit is a contract, not a per-screen patch. Seven rules hold on every
surface, and the same declarations carry them in both sheets. The layout
audit measures them in a browser on every screen; `tokens.test.ts` holds
the declarations that express them.

- **R1. Prose breaks rather than overflows.** `overflow-wrap: anywhere` on
  each surface's root: `body` in `index.css`, `body` in the server
  `STYLES`, the marketplace roots in `marketplace.css`, and the `.mg` and
  `.ml` island roots. It is inherited and only breaks a word that would by
  itself overflow. Compared values (`.kpi .value`, `.figure`,
  `.hero-stats dd`, `.ml-figure`, numeric table cells), stamps in fixed
  tracks (`.stamp`, `.digest-src`, `.digest-time`, `.stage-axis small`),
  `pre` and code that must scroll (`overflow-wrap: normal` plus a wrapper
  that scrolls), and identifiers a person must match exactly (the calendar
  file name, spec 003) keep `white-space: nowrap` and are handled by R3 to
  R6.
- **R2. A flex or grid item that holds text can shrink.** `min-width: 0`
  on that item, paired with R1. Targeted, selector by selector, never a
  universal `* { min-width: 0 }`.
- **R3. A row that puts text beside controls wraps before it squeezes the
  text.** `flex-wrap: wrap` on the row, `flex: 1 1 220px` on the text
  (`flex: 1 1 120px` for a card title in a narrow card), `flex: none` on
  each control or control group. A wrapping text column never collapses
  below about 120px.
- **R4. A chip (pill, badge, tag, stamp) never leaves its card.** It drops
  to its own line before it is squeezed (`flex-wrap` on its row,
  `max-width: 100%` on the chip). A single token longer than the card
  breaks by R1. A short badge whose phrase must stay on one line gets
  `white-space: nowrap` and its container makes room for it.
- **R5. Truncation is absent or reachable.** Where an ellipsis or a line
  clamp hides part of a value, the full value is reachable (a `title`, an
  `aria-label`, or a focusable or titled ancestor). Wrap or scroll is
  preferred when the value matters.
- **R6. A table, `pre` or digest block that cannot fit its column scrolls
  inside its own wrapper.** `overflow-x: auto`, never the page, and its
  cells stay `white-space: nowrap`. A table that should fit its card
  instead uses `table-layout: fixed; width: 100%` with wrapping cells so
  every column stays visible.
- **R7. The wrap contract holds on the same selectors in both style
  sheets.** The SPA `index.css` and the server `STYLES`, including rules
  that exist in one sheet only today.

Both root overflow rules stay as they are: the SPA body hides horizontal
overflow, the server body does not. Causes are fixed, not masked.

### Numbers

A number a person compares is a reading, not a string. Four rules hold
wherever one appears, in the SPA and on the server pages.

- **N1. Every number a person compares is grouped for display
  (9,270,950), and the value a system reads is never altered to achieve
  it.** Grouping happens in the surface that prints the value. A binding,
  a progress bar, a chart point and a pinned payload keep their exact
  digits.
- **N2. A figure never breaks across lines, is never cut off and never
  scrolls.** The headline figure and the tracker figure print in full and
  the layout makes room: the chart beside the headline figure moves below
  it when the figure needs the width.
- **N3. A label on a bar or inside a narrow track may use compact
  notation (1.2M) when the full value would not fit, and then the exact
  value is reachable.** A `title`, an `aria-label` and the reading carry
  the full number.
- **N4. A time, a date or a title inside a timeline has a column that
  fits its content; a rule written for one list never moves another
  list's columns.** A timeline owns its own column contract, and a plain
  list or a checklist keeps its own.

The layout audit's "long values" fixture renders 9,270,950 and 1,234,567
at every numeric site, so a regression in fit fails a run rather than a
review.

## Feedback on every wait

A wait is part of the interface, not an absence of one. Seven rules hold
on every surface. They are enhancements where the browser has no script:
the server pages keep their normal navigation and every form still works.
The shared pending state on `Button` and the `useBusy` hook carry the
first second; the region that will receive the result owns the rest.

- **F1. Nothing shows under 100 ms.** From 100 ms to 1 s the control that
  started the work shows it on itself: it cannot be pressed again, it
  carries `aria-busy="true"`, its verb becomes the continuous form
  ("Saving...", "Asking your AI..."), and its box holds still: the same
  height, padding and type, and never narrower. A longer verb may make it
  wider, by exactly the difference between the two labels. A dot may
  pulse in colour only, and `prefers-reduced-motion` freezes it.
- **F2. From 1 s to 30 s the region that will receive the result shows a
  placeholder with the same shape as the incoming content** (a skeleton
  or the app's dotted wireframe) and one plain line naming the phase in
  the reader's words. Never a spinner over an empty panel; never a
  blocked page.
- **F3. While the agent chooses between outcomes, the region shows a
  mock-up of the outcome** with a status line, and the real result
  replaces it in place without a jump: the dashed chart sketches while
  the tracker's columns and chart are being picked, and on the server
  pages the dashed card sketch (a figure, five bars, two lines) while
  the plugin wizard fills the choices in from a description or writes
  the card.
- **F4. Labels are honest.** A phase is named only while it is really
  happening. After 10 seconds without a change the line says it is taking
  longer than usual and that the reader may leave this page.
- **F5. The result replaces the placeholder in place.** Success is said
  where the reader is looking, in a `role="status"` line. A failure is
  said where it happened, with the next step, and what the reader typed
  is kept.
- **F6. A refetch keeps what is on screen (dimmed) instead of swapping in
  skeletons.** One loading indicator per region. A page never waits on
  its slowest part: the shell and the other regions appear at once.
- **F7. Every surface obeys the same rules, including server-rendered
  pages, which keep their normal navigation:** a busy button on every
  form, and for a model-backed form a placeholder in the outgoing page
  while the request is in flight. Pages must keep working with the script
  off.

## Components and motion

- Buttons, wells and cards read only the semantic tokens; state copy is
  honest and specific, amber for attention with a named cause and a
  recovery action, never a false green.
- Motion is 120ms on color and background only, and
  `prefers-reduced-motion` freezes it to instant.
- Focus is always visible (`:focus-visible` 2px accent ring); every
  icon-only control carries an accessible name.

## What this refuses

Gradients (except the one monochrome radial light on the Unkey hero),
glass and blur, glow, text shadows, hard offset shadows, emoji in chrome,
filled icon tiles, a recorded drift palette of pastel dark-glass paints,
and any component hardcoding a hex the token set already names.

## Enforcement

`frontend/src/test/tokens.test.ts` fails the build when a drift color
survives in the stylesheet or the component sources, when a banned effect
(backdrop-filter, gradients, blur, text-shadow) reappears, when the fonts
stop being self-hosted, when the radii or the rail geometry move, or when
the server sheet and the SPA sheet drift apart. The CSP story (self-hosted
fonts and bundles, no inline script) is pinned by the same suite.
