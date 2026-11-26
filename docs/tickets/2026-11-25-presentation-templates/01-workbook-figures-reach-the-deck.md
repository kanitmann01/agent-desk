# 01: Workbook figures reach the deck

**What to build:** the presentation form offers the workbook tracker as a source, and today its figures never reach the model. The code that gathers sources expects rows of one shape and a timestamp key, and the watcher returns rows of another shape and a time under a different name, so the model learns only the workbook's name and its row count. This ticket makes the gathering read what the watcher returns and turn each figure into a labelled fact (label, value, period, and target where there is one) that the model can cite. The number guard then lets those figures through.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A test with a fixture workbook asserts that the source text given to the model contains the workbook's figures, each with its label, its value and its period, and each carrying a citation the model can use. The test fails on main's code; that failing run is recorded.
- [ ] A deck built through the form path with the mock model, where the mock quotes one of those figures, keeps the figure. A figure no source supplied still becomes "data needed".
- [ ] With the tracker box unticked, or with no workbook connected, no figure is supplied, and the page says so in the words it uses today.
- [ ] No figure is invented: every existing test of the number guard stays green, and one new case plants an unsourced figure in a cell of the outline and asserts "data needed".
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
