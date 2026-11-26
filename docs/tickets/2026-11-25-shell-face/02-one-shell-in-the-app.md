# 02: One shell component in the app

**What to build:** one shell component (the brand row with the face slot, the eight rail entries, the collapse control, the count of waiting Inbox items, the theme control, the user block, and the phone bar with its menu) replaces the app's own rail. The entries live in one navigation definition. One rule marks the current page. The Plugins pages show the real count of waiting Inbox items instead of zero. The shell has its own stylesheet under its own class prefix and reads its colours through local tokens that fall back from the app's token names to the server stylesheet's.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The app renders the shell on the Dashboard and on every Plugins route. The shell tests pass against it: eight entries in today's order with today's labels, the collapse state kept under the existing storage key, the face slot first in the brand row, and no face in the phone bar.
- [ ] The navigation definition is one data file. A test fails if the shell and the definition disagree, and if the definition does not hold exactly the eight entries of today's rail.
- [ ] The current-page rule marks the entry for a nested path (a deep link into the Plugins pages marks Plugins). One test covers a nested path and one the root.
- [ ] On the Plugins pages the rail shows the real count of waiting Inbox items, read from the dashboard payload: a test with a mocked count of 3 shows 3.
- [ ] The theme control works from the rail on both routes and writes the stored theme that the theme boot script reads.
- [ ] The shell stylesheet carries no literal colour (a test refuses a hex value and an `rgb()` call), and every local token resolves against a fixture that defines only the server stylesheet's token names.
- [ ] The rail at 1280 and at 1024 in the three themes shows no new layout finding in the layout matrix, and its column keeps today's widths.
- [ ] `cd frontend && npm run check` prints `tsc --noEmit clean`, and `npm test -- --run` passes.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`; the bundle is rebuilt once and two builds give the same tree.
