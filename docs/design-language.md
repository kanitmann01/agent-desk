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
