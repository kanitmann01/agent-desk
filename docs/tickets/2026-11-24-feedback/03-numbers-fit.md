# 03: Numbers fit

**What to build:** every number a person compares reads in full or gives way deliberately. Display grouping is added where a person reads a value, while the value a system reads keeps its exact digits. The headline figure and the tracker figure print in full and the layout makes room; a label on a narrow bar may be compact when the exact value is reachable; a timeline's time, date and title each get a column that fits its content.

**Blocked by:** 01.

**Status:** queued.

- [ ] With a 9,270,950 fixture, the headline figure prints in full at 1280 and at 1024, with no clipping and no sideways scroll inside the figure.
- [ ] At 1024, when the headline figure needs the row, the stage chart moves below it instead of squeezing the figure; at 1280 both remain readable.
- [ ] The tracker figure, its unit, its goal and its change print in full inside the tile at 36px; no value scrolls inside a dot, a chip or a narrow track.
- [ ] Compared values are grouped for display (9,270,950), and the system value is unchanged: progress and bar faces render correctly from 1,000 up, and `tests/test_file_selection_chain.py:46,290` still pins "186500".
- [ ] A stage bar's label may use compact notation, and the exact value is reachable through a `title` and the aria-label that already names it.
- [ ] The generic timeline gives its time, date or title a column that fits the content: the title no longer lands in the 44px column.
- [ ] The `.w-list-meta` rule is scoped so a plain list, a checklist and a timeline each keep their own columns; fixing the timeline does not move a list's meta.
- [ ] The server sheet carries the same timeline and list contract as the SPA sheet, and the token suite pins both.
- [ ] Desk health's numeric cells keep their counts and times grouped and inside their columns.
- [ ] The layout audit has a committed "long values" fixture that renders 9,270,950 and 1,234,567 on every numeric site, and the fixture produces zero findings.
- [ ] No page gains a horizontal scrollbar at 1024 or 1280.
- [ ] Component and token tests cover the figure, the stage layout, the timeline columns and the scoped meta rule.
- [ ] `python tools/ci_local.py` passes 7/7.
