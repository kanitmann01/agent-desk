# Spec 031: Three presentation templates, and slides that carry more than bullets

**Status:** ready-for-agent (2026-11-25). Filed as #322. Tickets: #337, #338, #339, #340, #341, #342, #343, #344
`GLOSSARY.md` is the vocabulary.
Builds on Spec 021 (agent-callable presentation tools).
The host tool surface (outline, create, inspect, render), the shell builder, the pack validator, the mock model and the readiness walk are the seams. No new product seam.

## Problem Statement

A manager gives the desk a one-line brief and gets the same slide every time: a thin bar, a title and a list of sentences. There is one template. It has four layouts (title, divider, bullets, closing) and nothing else: no table, no figure, no shape, no footer, no page number. A quarterly review has nowhere to put its numbers. A comparison has nowhere to put two options side by side. Whatever the topic, the deck looks the same.

Three things make it worse.

- The form offers the workbook tracker as a source, and the figures never reach the model. The code that gathers sources expects a shape the watcher does not return, so the model learns only the workbook's name and its row count. The rule that a number must come from a source then does its job and replaces every figure with "data needed". The one kind of deck that needs numbers is the one that cannot have them.
- The picker shows two drawn bars as the template's thumbnail. Nobody can see what a template looks like before choosing it.
- Nothing proves a deck. The readiness walk has no presentation step, and the repository holds no rendered slide.

## Solution

Three templates, each in a dark and a light variant, each with its own type, palette and character, and none with a logo or a company name:

- **Executive review.** Clean and corporate. Titles state the conclusion. A quiet accent. Numbers get a strip of their own, a table carries a takeaway line, options sit side by side, and a roadmap shows the way there.
- **Working session.** Dense and structured, for taking a team through an analysis. A 2x2 matrix, pillars, a chain of steps, a table of owners.
- **Minimal.** Large type and white space, for a talk. A statement cover, a section divider with one oversized number, one figure that fills the slide, a quote.

Every template implements the same twelve slide roles, so any recipe works with any template, and adds two more.

Slides carry more than bullets. A slide can be columns, a comparison, a table, a strip of key figures, one big number, a bar exhibit, a timeline, a 2x2 matrix, a chain of steps, a set of pillars or a quote. Exhibits are drawn from shapes (rectangles, lines and text): no pictures and no chart objects in this wave. Every number on a slide comes from a cited source, in a table cell as much as in a sentence.

The workbook tracker source is fixed, so its figures reach the deck as labelled facts. The thumbnails in the picker become renders of a real slide. One readiness check builds a deck from each template. A render pass through PowerPoint and LibreOffice looks at every layout of every template and variant, and the contact sheets go into the evidence.

## User Stories

### Choosing

1. As a manager, I want three templates to choose from beside the starter, so that the deck can match the room I am presenting in.
2. As a manager, I want a thumbnail that shows a real slide of each template, so that I know what I am choosing.
3. As a manager, I want a dark and a light variant of each template, so that the deck works on a projector and on paper.
4. As a manager, I want the templates to carry no logo and no company name, so that I can present them anywhere.
5. As a manager, I want any recipe to work with any template, so that I never pick a template and find my recipe refused.
6. As a manager choosing with the keyboard, I want each template tile reachable and named, so that the picker works without a mouse.
7. As a manager, I want the starter to stay as it is, so that the decks I already built still open the same way.

### What a deck can hold

8. As a manager, I want a cover with a title and a subtitle, so that the first slide says what the deck is about.
9. As a manager, I want an agenda, so that the reader knows where the deck is going.
10. As a manager, I want section dividers that carry the section's title, so that a long deck keeps its shape.
11. As a manager, I want a bullets slide when bullets are right (one idea, two to five points), so that a simple point stays simple.
12. As a manager, I want two or three columns side by side, so that options, a before and after, or three streams can be compared at a glance.
13. As a manager, I want a comparison of two or three options against three to five criteria, so that a decision has its grid.
14. As a manager, I want a table of three to six rows and two to five columns, so that detail has a place that is not a bullet.
15. As a manager, I want a strip of two to four key figures, each with its label and its change against target or last period, so that the numbers are seen before they are read.
16. As a manager, I want a slide for one figure and the sentence that says why it matters, so that a single result can carry a slide.
17. As a manager, I want a bar exhibit for one measure across three to eight categories or periods, so that a trend is visible and not described.
18. As a manager, I want a timeline of three to six milestones, so that a plan has an order.
19. As a manager, I want a 2x2 matrix with three to six items placed on it, so that a positioning can be shown.
20. As a manager, I want a chain of three to six steps, so that a process reads left to right.
21. As a manager, I want three or four pillars, each with a heading and two or three lines, so that a strategy has its structure.
22. As a manager, I want a quote with its attribution, so that a customer's words can open a section.
23. As a manager, I want a closing slide that carries the asks, so that the deck ends with what I need.
24. As a manager, I want a quiet footer with the page number, so that nobody has to ask which slide we are on.
25. As a manager, I want the speaker notes to list the sources of every content slide, so that I can answer "where does this come from".

### Numbers

26. As a manager, I want every number on a slide to come from a source the desk read, so that I never present a figure nobody can stand behind.
27. As a manager, I want a number with no source to read "data needed", in a table cell as much as in a sentence, so that a gap is visible and not filled.
28. As a manager who ticks the workbook tracker, I want the tracker's figures to reach the deck, with their label, their period and their target where there is one, so that a quarterly review has the quarter in it.
29. As a manager, I want facts from memory that carry numbers to reach the deck with their citation, so that the deck can quote what the desk knows.

### The look

30. As a manager, I want titles that state the conclusion, so that a reader who reads only the titles still gets the argument.
31. As a manager, I want one focal point on each slide, so that the eye knows where to land.
32. As a manager, I want type that is large enough to read across a room, so that nobody squints: titles 28 pt and up, body 16 pt and up, nothing below 12 pt.
33. As a manager, I want fonts that are on every corporate Windows laptop, so that the deck does not reflow on another machine.
34. As a manager, I want the accent on a small share of each slide, so that the deck looks calm and not decorated.
35. As a manager, I want no title underlines, no edge bars, no gradients and no emoji bullets, so that the deck does not look machine-made.
36. As a manager, I want body text with a contrast of at least 4.5 to 1 against its background in both variants, so that it is readable in a bright room.
37. As a manager, I want a margin of half an inch that nothing crosses, so that nothing is cut off by a projector.
38. As a manager, I want the dark and the light variant of a template to differ only in colour, so that switching variant never moves a thing.

### The build

39. As a manager, I want a slide that does not fit to be shortened once and then continued, and the fit notes to say so, so that nothing is silently cut.
40. As a manager, I want a slide that the model fills in the wrong shape to be asked for once more and then shown as bullets, with a note, so that one bad answer does not fail the deck.
41. As an agent with my own slide text, I want to create a deck with a table or a strip of key figures from an outline, so that I can use the templates without a model endpoint.
42. As an agent, I want to read a deck back as text, cells and figures included, so that I can check it before handing it over.
43. As an agent, I want a refusal with a named reason when my outline has a slide in the wrong shape, so that I can fix the outline and not guess.
44. As an agent, I want the outline tool to cover every slide role a recipe uses, so that I can see each layout before I write content.
45. As a manager, I want a preview (a PDF and slide images) of a deck built from any template, so that I can look before I open PowerPoint.

### Proof

46. As a manager, I want every layout of every template to have been rendered and looked at before it shipped, so that no slide arrives with clipped text or overlapping boxes.
47. As a founder, I want the readiness walk to build a deck from each template, so that a broken template is caught before a demo.
48. As a reviewer, I want the evidence to hold a contact sheet per template and variant, and a before-and-after for one brief, so that the improvement can be seen and not argued.

### Maintainers

49. As a developer, I want every shell to come from one builder that reads a layout table, so that a new layout is a row and not a hand-built file.
50. As a reviewer, I want a test to fail when a recipe uses a slide role its template does not have, so that a template and a recipe cannot drift apart.
51. As a reviewer, I want a test to fail when a layout puts a box outside the margin, uses a type size below its floor, or fills a shape with a gradient, so that the rules are checked and not remembered.
52. As a developer, I want the mock model to answer with every slide role, so that tests and walks exercise every layout.
53. As a security reviewer, I want the new plugin to stay declarative, with no network, no file write and no shell, so that installing it grants nothing.
54. As a licence reviewer, I want ideas taken from other deck skills to be ideas only, with any adapted text carrying its notice, so that the licence gate stays clean.
55. As a reviewer, I want a stale thumbnail to fail a test, so that the picker never shows an old slide.

## Implementation Decisions

### The pack

- One new bundled plugin, declarative, from the desk's own publisher, holding the three templates and declaring the same four host tools the starter declares. The starter plugin is not modified, so the registry's append-only history stays clean.
- A template declares an id and name, a dark and a light shell, the recipes it serves (the three that exist), a thumbnail per variant, a guidance text, and its fonts (heading and body).
- The validator now reads two things it used to ignore. It checks that a recipe uses only slide roles the template has. It checks that each declared font is on the allow-list of fonts that ship with Windows or with Office.
- A change under a bundled plugin goes through the registry sync and the catalog rebuild, and passes the registry check, the licence gate and the brand check.

### Slide roles

- Twelve shared roles, which every template implements: `title`, `agenda`, `section`, `bullets`, `columns`, `comparison`, `table`, `metrics`, `bars`, `timeline`, `matrix`, `closing`.
- Two more per template: Executive review adds `bignum` and `pillars`; Working session adds `steps` and `pillars`; Minimal adds `bignum` and `quote`.
- A slide in the outline has a role and exactly one body in the shape that role takes:
  - `title`: a title and a subtitle. `section`: a section title. `closing`: a closing line and up to three asks.
  - `agenda`: three to eight items.
  - `bullets`: two to five points. `columns`: two or three columns, each with a heading and two to four points. `pillars`: three or four, each with a heading and two or three lines.
  - `comparison`: two or three options against three to five criteria.
  - `table`: three to six rows and two to five cells per row, with a header row.
  - `metrics`: two to four figures, each with a label, a value, a unit, and an optional change against a target or the last period. `bignum`: one figure with its label and one sentence.
  - `bars`: three to eight labelled values for one measure. `timeline`: three to six milestones with a date and a line.
  - `matrix`: three to six items, each with a label and a position on two named axes.
  - `steps`: three to six steps in order. `quote`: a quote and its attribution.
- Every slide carries its citations and its notes.

### The outline and its validation

- The outline gains the role and the body. The limits above are caps, checked in three places: when an agent submits an outline to the tool (refused with a status of 422 and a named reason), after each model call on the form path, and when a pack loads (recipe against template).
- The deterministic outline, which needs no model, covers every role the recipe uses with neutral sample content in the right shape. The thumbnails, the readiness check and the render pass are built from it.
- On the form path a slide that comes back in the wrong shape is asked for once more. If it is still wrong it becomes a `bullets` slide with whatever text the model produced, and the fit notes say so.

### The pipeline

- The plan pass chooses the sections and, for each slide, its role and a working title, within the recipe's limits.
- The fill pass returns slides in the shape of their role. Its prompt carries the role catalogue with the caps, the rule of one idea per slide, titles that state the conclusion, and the rule that a number needs a source.
- The number guard runs on every text field and every cell, and again after any shortening. A number that no cited source contains becomes "data needed".
- Fit is computed per role from the boxes the layout gives it. Text roles shorten once and continue on a new slide. A table that does not fit moves its last rows to a continuation slide with the same header. Exhibit roles drop their last item and say so in the fit notes.
- The writer learns four things it could not do: a real table with a header row; rectangles and lines, for the exhibits; text placed where the layout says, for key figures; and slide numbers and a footer from the master. Speaker notes are written as today. The theme of each shell carries the template's fonts and colours, and the writer does not restyle a master.

### The workbook tracker source

- The gathering reads what the watcher returns: its rows and the time of its last good read. Each figure becomes a labelled fact with its label, its value, its period and its target where there is one, and each fact is citable. Memory facts pass through as today.

### Shells and the builder

- One committed builder produces every shell from a layout table (the boxes of each role, in inches) and a theme (palette and fonts). Its output is byte for byte reproducible and pinned by tests. The starter's shells keep coming from the same builder.
- A template's palette has five roles: background, text, accent, muted, and two tints of the accent. Dark and light are two sets of values for the same roles.
- Type per template, all from fonts that ship with Windows or with Office: Executive review uses Segoe UI, with Consolas for figures; Working session uses Franklin Gothic Medium for headings, Arial for body text and Georgia for quotes; Minimal uses Segoe UI Light for display and Segoe UI for text.
- Sizes, the same limits for every template, with each template stating its own scale inside them: titles 28 pt and up; prose 16 pt and up; table cells, captions and footers 12 pt and up; nothing below 12 pt.
- The rules a test can measure are tested: nothing outside the half-inch margin, no type below the floor, no gradient, no underline on a title, colours only from the palette, and dark and light differing only in colour. The rules a test cannot measure are written in the guidance text.
- Thumbnails are a render of a content slide of each variant at 320 by 180, committed, and regenerated by one command.

### Picker, readiness and evidence

- The picker on the Agents page shows one tile per template with its two thumbnails. The form, its sources and its waits do not change.
- The readiness walk gains one numbered check: a deck builds from each template through the tool path and passes the package checks. It needs no renderer. The readiness count moves from 27 to 28.
- Evidence is collected in one folder of the evidence tree: a contact sheet per template and variant, the render pass results, and a before-and-after for one brief (the starter and each new template).

### Licensing

- Layout ideas are taken from the deck skills installed on the build machine. No code, text or asset is copied from them. The new plugin's guidance is the desk's own text, or an adaptation that carries the upstream notice as the starter's does. The notices file is regenerated by its script and never edited by hand.

## Testing Decisions

A good test drives a public seam and checks what comes out: a deck the tool wrote, the text the inspect tool reads back, the bytes of a shell, the verdict on a rendered image. It never asserts a private helper or a wall-clock time.

1. The tool surface (pytest): a deck created from a hand-written outline that uses every role passes the package checks; the inspect tool returns exactly the outline's text, cells and figures included; no number is in the deck that is not in the outline; a slide in the wrong shape is refused with a named reason. Prior art: `tests/test_presentation_tools.py`, `tests/test_server_presentation_tools.py`, `tests/test_presentation_cli.py`.
2. The shell builder (pytest): the bytes are pinned; each layout's role exists; every box is inside the margin; no type size is below the template's floor; no gradient; colours from the palette only; dark and light differ only in colour; the starter's shells are unchanged. Prior art: `tests/test_presentation_packs.py`, `tests/test_presentation_writer.py`.
3. The form path through the mock model (pytest): every recipe with every template builds a deck; each slide has the role the recipe asks for; every content slide's notes carry sources; the number guard runs on cells; the wrong-shape path asks once and then degrades with a note; fit shortens and continues as described. Prior art: `tests/test_presentation_pipeline.py`, `tests/test_presentation_fit.py`, `tests/test_presentation_research.py`.
4. The source seam (pytest): with a fixture workbook, the model receives labelled figures with label, value, period and target, each citable; with no workbook, the deck says "data needed" and nothing else.
5. The render pass (not a unit test): every layout of every template and variant is rendered through PowerPoint and through LibreOffice. A reviewer that can see gives each image a verdict against a checklist: no clipped text, no overlapping boxes, nothing outside the margin, the type floor, the contrast, one focal point. Every verdict is recorded under `docs/evidence/2026-11-25-presentation-templates/`. Prior art for the renderer call: `tests/test_presentation_render.py`.
6. The picker (pytest and the layout audit): four tiles, each named, the thumbnails are the committed renders, and the long template names fit at the audited widths.
7. The gates: the readiness walk prints 28; the registry check, the catalog bundle, the licence gate, the brand check, the docstring gate and the local gate pass; two builds give the same bundle.

## Out of Scope

1. Native chart objects (bar, line and pie charts as chart parts with their own data).
2. Pictures, icons and stock art. Plugins cannot reach the network, and none ships.
3. New recipes. The three that exist stay: briefing, quarterly review, competitor brief.
4. Changing the starter's look or layouts.
5. Discovering template packs installed from the marketplace. Filed separately.
6. Templates that carry a company's name or colours. Those stay on the manager's machine, as the pack install document says.
7. A token-scoped tool route for outside agents, already a follow-up of Spec 021.

## Further Notes

### Decisions the founder took on 2026-11-25

- The three template directions: executive review, working session (consulting-style), minimal.
- One new bundled plugin beside the untouched starter.
- Twelve shared slide roles plus two per template, with shape-drawn exhibits and no chart objects.
- The three existing recipes stay.
- One committed builder, real thumbnails, one readiness check, and the workbook tracker source fixed.
- Layout ideas come from the deck skills installed on the build machine.

### What this spec depends on

- The audit of the UI wave on main closes its P0 and P1 findings, and the shell and face spec lands, before this one starts.
- Spec 032 completes the rename before presentation work starts: the product and the agent are Nexuus Bot on every live surface, and the naming guard holds the line.

### Risks and mitigations

- The model answers in the wrong shape. Mitigation: validation after every call, one retry, then a bullets slide with a note.
- The two renderers disagree. Mitigation: the render pass runs both and records every verdict.
- A viewer lacks a font. Mitigation: fonts come only from the allow-list of those shipped with Windows or Office, and the validator enforces it.
- The registry history is append-only. Mitigation: a new plugin, and the starter is not edited.
- The readiness list was frozen by Spec 022. Mitigation: this spec adds one check by the founder's decision, and its status line says so.
- Nothing has rendered a desk deck on this machine yet. Mitigation: the first ticket proves the render pipeline end to end (PowerPoint, LibreOffice, rasterizing the PDF) before any template is built.

### Follow-ups to file

- Native chart objects.
- Discovering template packs installed from the marketplace.
