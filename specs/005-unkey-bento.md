# 005 Unkey bento

## Problem Statement

The morning-brief desk is a light editorial page. The owner wants the Unkey bento: a near-black canvas, thin rules, and cells that show the actual data, not a repeated card with a title and a sentence.

## Solution

The dashboard, plugin cells, marketplace, and tracker setup sheet use one dark language. The dashboard is a 12-column bento. Each plugin kind has its own cell. Sample rows keep their real names and are not renamed when a number changes.

## User Stories

1. As Priya, I want the pipeline figure in a large mono cell with a bar of the real changes, so that I see the number before anything else.
2. As Priya, I want a separate decisions cell, so that connect actions are not mixed into the figure.
3. As Priya, I want a moves table with the deal, where it sits, and old to new, so that a changed deal is one row.
4. As Priya, I want a digest cell with a time, a watch cell with a diff, and a desk cell with a status matrix, so that those jobs do not look like the tracker.
5. As Priya, I want an unset plugin to show a dotted empty state and one Set up action, so that I am not shown a fake number.
6. As Priya, I want the tracker setup sheet in the same language, with the chosen column filled in the highlighter and row numbers in mono, so that the form does not look like a different product.
7. As Priya, I want the marketplace in the same canvas, with featured plugins given more room, so that the catalog matches the desk.
8. As Priya, I want the cells to stack on a phone without sideways scrolling, so that the first screen is the figure or the decisions.

## Implementation Decisions

- Canvas `#060609`, rule `#26272A`, text `#FBFBFB`, one highlighter `#E1F56A`. No second hue for up and down. Down is muted text. Up and live values use the highlighter.
- Geist for UI, Geist Mono for figures and tags. Tags are written in capitals. CSS does not uppercase them.
- Cells use a 1px rule, 8px radius, and no shadow. The hero cell carries a sparse dot texture.
- A deal is paired only when the workbook row name matches. The sample index suffix is hidden. A close date is appended so two deals with the same title stay distinct. A row is never shown as renamed because an index matched.
- Plugin ids map to tracker, digest, watch, or health. The dashboard also draws those four roles from the sales, calendar, and source payload when no plugin is installed.

## Testing Decisions

- Token tests assert the dark hexes, Geist, 8px radius, and the absence of a card shadow.
- Mover tests assert a same-name edit is one signed row, and two different names are not merged.
- Shell tests still require the decisions region and a single Connect link for the calendar walkthrough.

## Out of Scope

- A new data model for plugins.
- Marketing pages.
- GitHub Actions billing.
