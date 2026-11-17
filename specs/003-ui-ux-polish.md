# Spec: morning brief redesign

Replaces the warm-paper polish. The owner rejected that system as templated. Seam: the frontend vitest suite and the server UI pytest modules that read the served stylesheet.

## Problem Statement

Priya opens a desk that looks like every other soft SaaS card grid: one green, one humanist sans, blurred shadows, an icon rail, and a marketplace of identical tiles. The previous polish stayed inside that system, so the product still did not have a point of view.

## Solution

Redraw the desk as a morning brief. Stone paper, a black frame with one hard offset, a serif greeting, one large figure, oxide only for the action and for numbers that went down, fir only for numbers that went up, and a rail of words. The server-rendered pages use the same rules. The type scale is 12, 14, 16, 20, 32, 56, and 64.

## User Stories

1. As a manager, I want the first thing I read to be the greeting in a serif, so that the page feels like a brief and not a template.
2. As a manager, I want one large figure for sales, so that the number is the point of the page.
3. As a manager, I want up and down to be different colors, so that green is not also the button.
4. As a manager, I want the navigation to be words, so that I am not decoding icons.
5. As a manager, I want the current page underlined, so that I know where I am without a tinted pill.
6. As a manager, I want square buttons with a hard edge, so that a press has a shape.
7. As a manager, I want the research field to be a ruled box with the word Research in oxide, so that asking is obvious.
8. As a manager, I want the same frame on inbox, settings, and the assistant, so that leaving the dashboard does not change the product.
9. As a manager, I want marketplace titles in the same serif, so that the catalog belongs to the desk.
10. As a manager, I want plugin cards ruled in black, not floating on a soft shadow, so that the catalog is a list of objects.
11. As a manager, I want loading and failure to stay announced, so that the redesign does not drop the recovery.
12. As a manager, I want the calendar file name to stay whole, so that I can match it in OneDrive.
13. As a manager on a phone, I want the words of the navigation, so that the strip is not anonymous marks.
14. As a manager, I want focus to stay visible and clear of the sticky strip, so that the keyboard path survives the new frame.
15. As a manager, I want no gradient, no glass, and no second decorative accent, so that the brief stays a document.

## Implementation Decisions

- Tokens live in `DESIGN.md` and `docs/design-language.md`. Both stylesheets (the SPA and the server sheet) use them.
- The frame is a 2px black border and an 8px hard offset on the app shell. Cards are 2px rules. Hover adds a 4px offset. There is no blurred shadow.
- The rail drops its icons. A one-letter mark is only for the collapsed desktop rail. Narrow widths keep the words and still wrap instead of scrolling sideways.
- Greeting is Source Serif 4 at 56px. The sales figure is IBM Plex Mono at 64px in fir. Oxide is the action color.
- Marketplace titles are Source Serif 4 at 40px. Catalog cards lose the soft shadow and the pill radius.
- Server pages get the same tokens, the word rail, the black primary button, and the 64px figure. Uppercase label transforms come off.
- Font packages: Source Serif 4 and Source Sans 3 replace Plus Jakarta Sans. IBM Plex Mono stays. License records follow the packages.
- The image-to-code comp is the layout source for the dashboard. It is adapted from the Rosterline reference, not from the Bruddle marketing stage.

## Testing Decisions

Tests assert observable text, roles, and the stylesheet contract. The contract is updated to the new tokens, the 200px rail, the 56/64 type, the hard offset, and the square radii. Server tests that read `--primary` and the entry-card chrome are updated to the new primary and still require a real card rule (background, the shadow token, radius token). The shadow token is now the hard offset.

## Out of Scope

- Turning the desk into a marketing site with photographs, shaders, or a hero entrance.
- Copying Linear's dark theme or Bruddle's purple.
- A new information architecture. Sales, commitments, research, and the inbox stay the same objects. The chrome around them changes.
- Inventing a skill file for awesome-design-md.

## Further Notes

Taste-skill marketing rules that do not apply to an internal desk are listed, with reasons, in `docs/design/ui-audit-2026-11-16.md`.
