# 03: Code review by area, with a confirmed findings register

**What to build:** the merged diff is reviewed by agents that did not write it, in six partitions small enough for one fresh context each, and the result is one findings register. Every P0 and P1 is then reproduced by a second agent before anyone fixes it, so the fix round spends its time on real defects. Reviewers change nothing.

**Blocked by:** None (can start immediately). It reviews `f31582a..<audited commit>` once ticket 01 merges.

**Status:** ready-for-agent

The six partitions:

1. The agent face and its tests: `frontend/src/face`, the face test files, and the face sections of the token suite.
2. The dashboard, the shared components and the memory islands, with their tests.
3. The marketplace, with its tests.
4. The server-rendered pages and the other changed server modules, with the Python tests.
5. The instruments: the layout audit, the feedback walkthrough, the mock endpoint, the local gate, and the fixtures.
6. The claims: README, both `docs/evidence/2026-11-24-*/EVIDENCE.md` files, specs 026, 027 and 029, and the three ticket sets. Every claim is checked against the code. Known already: README names six pending verdicts while the instrument has seven; the evidence files do not hold the gate commands that ticket 09 of the feedback set says they hold; spec 029 is unfiled and its ticket boxes are all unchecked although its code is on main.

Known starting points. Earlier read-only exploration surfaced these. Reviewers confirm or refute each with file and line; they are starting points, not conclusions.

- The agent's name constant in the face module (`Nexuus Bot`) sits under a source root that the brand-naming test scans for the retired product name, case-insensitively, with no allowlist. This was read from the test file, not run. If the gate shows it, main's local gate is red for a second reason, and hosted CI does not run that file.
- The two dialogs that spec 029 says hold the face (plugin description, tracker setup) mount no face on main. The commit message says they do.
- The background loop signal of spec 029 is not built: the dashboard payload has no running-step fields, and the app never requests the loop status. The background-pass and broken-desk moods are unwired.
- The two rails differ in five places: the face, the theme control, the active-marker rule, the inbox badge fixed to zero on the marketplace, and the toggle state and link ink.
- README names six pending verdicts; the instrument has seven.
- The evidence files do not hold the gate commands that ticket 09 of the feedback set says they hold.
- Spec 029 is unfiled and its ticket boxes are unchecked although its code is on main.
- The workbook tracker checkbox on the presentation form promises figures that never reach the deck: the gathering code expects rows and a timestamp key that the watcher does not return, so the model receives only the workbook's name and its row count. The number guard then replaces every figure with "data needed".
- The recipe limits the presentation guidance cites (bullets per slide, characters per bullet) are documentation only; the code reads just the region and the font floor.
- The template thumbnails in the picker are drawn stand-ins, not renders of a slide.
- The readiness walk has no presentation step, and the repository holds no rendered deck.
- A template pack installed from the marketplace is not discovered by the deck builder; only the bundled pack and the user's template folder are.

What each reviewer looks for:

- Correctness: wrong logic, races, stale state after a sheet closes, an event listener or timer that is never released.
- Security: escaping of every dynamic value in the server-rendered pages, path confinement and command handling in the instruments, and anything that could reach the real data folder, the real keychain or a real model key.
- Tests that can fail: for each new test, the behaviour whose removal would fail it. A test that still passes with the behaviour broken is a finding.
- Spec compliance: the acceptance criteria of specs 026, 027 and 029.
- Accessibility: names, roles, focus order, and `prefers-reduced-motion`.
- The design language: motion of 120 ms on colour and background only, no filled tiles, no hard-coded colour outside the token set, with the face as the only exception.

- [ ] Coverage: every file in the diff is in exactly one partition and has a disposition (reviewed, generated bundle, or documentation). The register gives the counts per partition.
- [ ] Every finding has an id, a severity, a partition, a file and line, what is wrong, why it matters, the evidence (quoted code or command output), and a proposed fix.
- [ ] Every P0 and P1 carries an independent confirmation: a second agent reproduced it or refuted it, and the evidence of that attempt is in the register.
- [ ] For every new test file, the register names at least one behaviour whose removal fails it, or flags the file.
- [ ] The register exists as `findings.md` and `findings.json` in the evidence pack, with counts by severity, and lists what was checked and found correct in one section, so a later reader knows the coverage.
- [ ] No repository file was changed by any reviewer.
