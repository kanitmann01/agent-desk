---
version: 1
name: Nexuus Bot morning brief
description: A printed morning brief, not a card grid. Stone paper, black rules, one oxide action, fir only when a number is up.
colors:
  paper: "#F6F3EC"
  brief: "#FFFDF8"
  ink: "#141414"
  ink-secondary: "#3A3A3A"
  ink-muted: "#5C5C5C"
  oxide: "#8C2F2F"
  oxide-soft: "#F3E4E1"
  fir: "#1B6B3A"
typography:
  greeting:
    fontFamily: Source Serif 4
    fontSize: 56px
    fontWeight: 560
  section:
    fontFamily: Source Serif 4
    fontSize: 32px
    fontWeight: 560
  body:
    fontFamily: Source Sans 3
    fontSize: 14px
    fontWeight: 400
  label:
    fontFamily: Source Sans 3
    fontSize: 12px
    fontWeight: 600
  figure:
    fontFamily: IBM Plex Mono
    fontSize: 64px
    fontWeight: 500
rounded:
  card: 0px
  control: 0px
spacing:
  unit: 4px
  frame: 16px
  rail: 200px
elevation:
  frame: "8px 8px 0 #141414"
  card-hover: "4px 4px 0 #141414"
---

# Nexuus Bot

The desk is a morning brief for one manager. The first screen is a greeting, one question, one figure, and the decisions that are waiting. It is not a mosaic of equal cards.

## What it takes from the references

- Rosterline's brutalist operations desk: the greeting, the hard black rule, the offset shadow used once, and a list of things that need a decision with a square button.
- Linear, from awesome-design-md: hairline structure, type doing the hierarchy, color held back from decoration. The lavender accent and the dark canvas stay there.
- The Bruddle crypto dashboard: a black rail and a big figure beside a list. The purple, the gradient stage, and the coin icons do not come with it.
- Monty Hayton's command palette: one field that is the way you ask. It is light here, because the desk is a morning document, not a dark launcher.

## Rules

- Square corners. A 2px black rule. The only shadow is a hard offset.
- Source Serif 4 for the greeting and section titles. Source Sans 3 for everything else you read as UI. IBM Plex Mono for figures, times, and counts.
- Oxide `#8C2F2F` is the action and anything down. Fir `#1B6B3A` is only a number that went up.
- The rail is words. The current page is an underline. A letter shows only when the rail is collapsed.
- No gradients, no glass, no emoji, no filled icon tiles, no soft blurred shadows.
