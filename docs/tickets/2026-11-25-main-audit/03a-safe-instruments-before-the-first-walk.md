# 03a: The walk instruments are safe before the first walk

**What to build:** four fixes to the repository's own browser instruments, found by the audit's code review and confirmed by a second agent, so that the audit's walks touch nothing outside an isolated desk and report only what they can show. The layout audit's `busy` condition seeds plugins into a busy state through a desk booted without the protection the local gate uses, so production capability adapters ran on 2026-11-24: 27 probe files were found in the founder's OneDrive root, and by reading the code the same path can also reach an external host, install a package and list processes. Three verdict defects let the pending walk report success it did not earn. No walk runs until this ticket merges, and the BEFORE and AFTER walks both use the fixed instrument.

**Blocked by:** None (it can start now; 04 is blocked by it).

**Status:** ready-for-agent

- [ ] No entry point of the instruments (the layout matrix, the pending pass, the feedback walkthrough) can run a production capability adapter. Every path that boots a desk passes the same protection the local gate uses. A test drives each entry point's boot path and the busy seeding against a stand-in that stands in for the server and records every call, starts no real desk, and asserts two things: the protection is passed on every path, and no capability request leaves un-intercepted. The mutation that removes the protection fails that test; that failing run is recorded.
- [ ] The `busy` condition still produces its busy pages, seeded through fixtures or an intercepted route rather than real capability requests. If it cannot be made safe, it is removed and the README and the evidence files say so.
- [ ] Every non-GET request is held or answered from before the first navigation, in every walk. Today the routes go in after navigation, and the Describe control can send a wizard start before anything intercepts it. A test proves it for the earliest request.
- [ ] A pending verdict of `meets` is given only for content that appeared after the click. Content that was on the page before the click cannot earn it. A test proves it.
- [ ] The pending pass fails, and says why, when a page that should have controls yields none to click.
- [ ] A control that should open a dialog and does not is a finding, never an allowed skip. A skip is allowed only when the walk can show the fallback is legitimate. A test proves it for the Describe control.
- [ ] No test in this ticket starts a real desk.
- [ ] The instrument's test files pass, the selftest prints its PASS line (its counts updated if they change), and `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS` on the pull request head.
- [ ] The implementer runs no walk and not the layout audit itself. The walks belong to ticket 04.
- [ ] The pull request is merged by a merger agent only after a review by an agent that did not write the code and the founder's confirmation.
