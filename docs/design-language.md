# Design language: Agent Desk

The previous warm-paper, deep-green, Plus Jakarta system read as a template. This file replaces it. `DESIGN.md` at the repo root is the token sheet. The target comps are the pull-request artifacts `dashboard-target-desktop` and `dashboard-target-narrow`, drawn from the Rosterline operations desk and adapted to this product.

## Thesis

A morning brief. Stone paper, black rules, a serif greeting, one figure, and a list of decisions. The work is louder than the chrome. Light mode only.

## Tokens

```css
:root {
  --bg: #F6F3EC;
  --surface: #FFFDF8;
  --ink-1: #141414;
  --ink-2: #3A3A3A;
  --ink-3: #5C5C5C;
  --ink-4: #8A8A8A;
  --hairline: #141414;
  --primary: #8C2F2F;      /* oxide: the action, and a number that went down */
  --primary-ink: #FFFDF8;
  --good: #1B6B3A;         /* fir: a number that went up, nowhere else */
  --shadow-frame: 8px 8px 0 #141414;
  --shadow-press: 4px 4px 0 #141414;
  --r-card: 0px;
  --r-control: 0px;
  --dur: 120ms;
}
```

## Type

- Greeting and section titles: **Source Serif 4** (560). The greeting is 56px, once.
- UI: **Source Sans 3**. Scale: 12, 14, 16, 20, 32.
- Figures, times, counts: **IBM Plex Mono**, tabular. The one KPI is 64px. Nothing else is.

## Components

- The app sits in a 2px black frame with one hard offset. Cards are the same 2px rule, square, and pick up a 4px offset only while the pointer is on them.
- Primary buttons are black squares. Secondary buttons are white squares with a black rule. The research action is oxide text, not a second filled button.
- The rail is words. The current page is an underline. No icon row.
- Color states status or the one action. It does not decorate.

## Motion

120ms, shadow and color only. Reduced motion is instant. No entrance, no stagger, no lift-on-scroll.

## What this refuses

Gradients, glass, glow, blurred shadows, emoji, filled icon tiles, identical card mosaics, and a second accent used as decoration.
