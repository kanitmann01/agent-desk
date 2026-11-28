---
version: 3
name: Nexuus Bot
description: One bento language, three themes. Near-black canvas by default, 1px rules, Geist and Geist Mono, one accent per theme doing all the pointing.
themes:
  unkey:
    scheme: dark
    canvas: "#060609"
    surface: "#0C0C0F"
    rule: "#26272A"
    text: "#FBFBFB"
    muted: "#8E8E93"
    accent: "#E1F56A"
  coforge:
    scheme: dark
    canvas: "#082340"
    surface: "#0C2A4A"
    rule: "#1E4472"
    text: "#FFFFFF"
    muted: "#A0A1A2"
    accent: "#F15840"
  momentuum:
    scheme: light
    canvas: "#F3F6FA"
    surface: "#FFFFFF"
    rule: "#D5DDE8"
    text: "#082340"
    muted: "#5B6B82"
    accent: "#2470B0"
typography:
  words: Geist (Momentuum headings: Montserrat 700)
  numerals: Geist Mono, tabular
  greeting: 40px
  figure: 56px
rounded:
  card: 8px
  control: 6px
  inner: 4px
  pill: 6px
spacing:
  rail: 200px
  content: 1200px
  rhythm: 28px 36px 60px
elevation: none
---

# Nexuus Bot

The desk is a quiet instrument, dark by default: near-black canvas, 1px rules, one accent per theme doing all the pointing. Hierarchy comes from spacing, weight and a four-level ink ramp, never from shadow or glass. The work is louder than the chrome. `docs/design-language.md` is the full statement of this system; `frontend/src/test/tokens.test.ts` enforces it.

## Rules

- Components read only the semantic tokens (canvas, surface, rule, text, muted, accent, focus, heading and their derived steps). No component carries a hex.
- The user picks one of three themes in Settings; `theme-boot.js` applies it before first paint. Unkey (default, dark) carries the dot cell texture and the one radial light on the hero. Coforge (dark) and Momentuum (light) are flat.
- Geist for words, Geist Mono tabular for every compared value. The greeting is 40px, the one dashboard figure is 56px, and nothing else is bigger. No `clamp()`.
- Concentric radii: cards 8px, controls 6px, inner wells 4px, pill 6px. No shadow at rest and none on hover.
- A 200px word rail beside a 1200px content column on a 28/36/60px rhythm.
- Motion is 120ms on color and background only; `prefers-reduced-motion` freezes it to instant.
- Focus is always visible; every icon-only control carries an accessible name.
- No gradients (except that one monochrome hero light), no glass, no blur, no glow, no text shadows, no emoji in chrome, no filled icon tiles, and none of the recorded dark-glass drift palette.
