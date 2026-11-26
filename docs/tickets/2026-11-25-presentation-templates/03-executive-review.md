# 03: Executive review: fourteen roles, rendered and checked

**What to build:** the Executive review template complete: the twelve shared slide roles and its own two (`bignum` and `pillars`), in a dark and a light shell. Clean and corporate: titles state the conclusion, the accent is used on one element per slide, figures stand large, a table carries a takeaway line, and the roadmap reads left to right. Every layout is rendered and looked at.

**Blocked by:** 02: One new slide role end to end.

**Status:** ready-for-agent

- [ ] The shell holds fourteen layouts, one per role, in both variants. For each layout a structural test holds: every box inside the half-inch margin, no type below its floor, no gradient, no underlined title, colours only from the palette, and dark and light differing only in colour.
- [ ] Each role is laid out to its cap from the spec (a table of six rows, a strip of four figures, a bar exhibit of eight values, a timeline of six milestones, a matrix of six items, three columns of four points): a specimen slide at the cap renders with every item visible.
- [ ] A specimen deck with one slide per role is created, inspected (every text read back in order) and rendered through both renderers for both variants: 56 images. Each has a verdict by a reviewer that can see, with zero clipped text and zero overlapping boxes.
- [ ] Fit for the roles added here: a table one row too long moves its last rows to a continuation slide with the same header; text roles shorten once and then continue; an exhibit over its cap drops its last item. The fit notes name the slide and what moved. One test per rule.
- [ ] Thumbnails for the dark and the light variant, 320 by 180, are renders of a real content slide. One command regenerates them, and a test fails when a committed thumbnail differs from a fresh render.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
