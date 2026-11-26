# 06: The form path fills every role

**What to build:** a manager's one-line brief goes through the plan pass and the fill pass. The plan pass now chooses a slide role for each slide, and the fill pass returns slides in the shape of that role. The prompts carry the role catalogue with its caps and the rules of the spec. The mock model can answer with every role, so tests and walks reach every layout. The number guard covers cells and figures. A slide in the wrong shape is asked for once more and then shown as bullets, with a note.

**Blocked by:** 01: Workbook figures reach the deck. 02: One new slide role end to end.

**Status:** ready-for-agent

- [ ] The plan prompt and the fill prompt carry the role catalogue with its caps, the rule of one idea per slide, titles that state the conclusion, and the rule that a number needs a source. Both prompts are quoted in the evidence.
- [ ] The mock model returns a role-shaped fill for every recipe, the same answer for the same brief.
- [ ] For each recipe with each new template (nine runs) through the form path with the mock: a deck builds; every slide has a role the recipe asks for; every content slide's notes list its sources; the package checks are empty; the slide counts stay inside the recipe's limits.
- [ ] The number guard runs on titles, bullets, table cells, key figures and bar values: a planted unsourced number in each of those five places becomes "data needed", while a figure the workbook supplied survives. One test per place.
- [ ] The wrong-shape path: when the mock answers in the wrong shape, the slide is asked for once more, and if the second answer is still wrong it becomes a `bullets` slide with a fit note that names the slide. The test scripts both answers.
- [ ] The outline that needs no model (`presentation_outline`) covers every role the recipe uses, with neutral sample content in the right shape. One test per recipe.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
