# 01: Small fixes before the audit, and the local checkout

**What to build:** four things, none of them a feature. First, the founder's own checkout moves to the merged main. Second, the one test in the local gate that depends on the wall clock stops doing so. Third, "Fill it in for me" in the plugin description dialog stops being a control that does nothing. Fourth, the brand-naming guard makes room for the agent's name: the founder confirmed on 2026-11-25 that the agent is called Nexuus Bot, and the guard as written bans that string on every surface. The three code fixes land through one small pull request so the audit starts from a main whose gate is green at any hour.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The checkout `D:/20-projects/Personal Agents/agent-desk` is on `main` at or after the merge commit `37515e9`, moved only by `git pull --ff-only origin main`. Before the pull an agent listed the running processes and confirmed that none was started from that checkout. Its tracked files were clean before and after, and every untracked file it had before is still there after.
- [ ] `tests/test_plugin_update_modes.py::test_a_scheduled_tile_refreshes_when_its_clock_comes_due` no longer reads the wall clock. The due time is the first 08:00 at or after the stored reading, and the test asserts that with fixed times (at least 00:00, 07:59 and 08:00) instead of "a day after the stored reading".
- [ ] `python -m pytest -q tests/test_plugin_update_modes.py` passes, and the evidence line records the local time of the run.
- [ ] If the fixed test exposes a product bug, no product code changes in this ticket. The bug is reported as a finding with a severity from P0 to P3.
- [ ] In the plugin description dialog, "Fill it in for me" is disabled while the description is empty, enables once text is typed, and starts exactly one request when pressed with text.
- [ ] The tests assert after each press: one test presses with an empty description and asserts that no request starts; one test types, presses once and asserts one request. Each fails if the guard is inverted (the inverted run is recorded).
- [ ] `cd frontend && npm run check` prints `tsc --noEmit clean`, and `npm test -- --run` passes.
- [ ] `python -m pytest -q tests/test_brand_naming.py` fails on main as it stands, naming the line that defines the agent's name and the committed bundle. That failing run is recorded. If it passes, stop and report; do not change the guard.
- [ ] The guard then allows the agent's name on exactly one line of the one module that defines it, asserts that line exists, skips the committed static bundle, and still fails for the name anywhere else on a live surface (a planted copy in a second file fails the test; that run is recorded, and the copy is removed).
- [ ] The product is still named Agent Desk everywhere else, and the em-dash ban in the same test file still holds.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS` on the pull request head.
- [ ] The pull request is merged by a merger agent only after the founder's confirmation.
