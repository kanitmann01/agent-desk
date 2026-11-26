# 02: One new slide role end to end

**What to build:** a tracer bullet through every layer, on one role, so the rest are a matter of adding rows. First the render pipeline is proved on this machine. Then the outline gains a slide role and a body in the shape that role takes, checked with a named refusal. The shell builder learns to read a layout table. The writer learns to draw a real table with a header row. The Executive review template, dark and light, gets its first three layouts (title, table, closing). A deck is created from a hand-written outline, inspected, and rendered.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The render pipeline is proved on this machine: a deck built by the tool renders to a PDF and to PNG files through PowerPoint, and again through LibreOffice. The commands and the output paths are recorded. If a renderer fails, the failure and its cause are recorded before any workaround.
- [ ] The outline carries a role and a body for each slide. `presentation_create` refuses a slide whose body does not match its role, and a slide over a cap, with status 422 and a named reason. One test for each kind of refusal.
- [ ] The builder produces the Executive review shell, dark and light, with the `title`, `table` and `closing` layouts read from a layout table. The bytes are pinned. The starter's two shells are byte for byte what they are on main.
- [ ] The writer writes a real table (a table object with a header row), and `presentation_inspect` reads the cells back in order. A round-trip test asserts that the text read back equals the outline's.
- [ ] A three-slide specimen deck is created, inspected and rendered for both variants. Each image is read by a reviewer that can see against the checklist: no clipped text, no overlapping boxes, nothing outside the half-inch margin, the type floors, and a contrast of at least 4.5 to 1 for body text. Each verdict is recorded.
- [ ] The Executive review palette and type scale are written down with the shell (five colour roles, the fonts of the spec, and the sizes inside the spec's limits), and a test fails if a colour outside the palette or a size below its floor appears.
- [ ] `python tools/docstring_gate.py` exits 0; the licence gate passes; `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
