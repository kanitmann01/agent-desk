# 03: The shell on server-rendered pages, with the no-script fallback held equal

**What to build:** every server-rendered page mounts the shell through the page shell. The page shell adds a mount element that carries the current path and the count of waiting Inbox items, and loads one script and one stylesheet with fixed names. The theme boot script, which every page already loads before first paint, marks the document as scripted; the page stylesheet then hides the rail markup it renders today and shows the mount, which reserves the same column. That markup stays as the fallback for a browser without scripting, reads the same navigation definition, and is held equal to the shell by a contract test.

**Blocked by:** 02: One shell component in the app.

**Status:** ready-for-agent

- [ ] Every page the page shell renders (Agents, Inbox, Assistant, Memory and its subpages, Mail, Settings and its subpages) contains the mount with the current path and the Inbox count, one script tag with a fixed name, one stylesheet link with a fixed name, and the fallback rail markup. The wizard and the error pages, which have no rail, are unchanged.
- [ ] The page tests that pin the exact list of scripts are changed once and assert the new list. Every one of those tests renders the page with and without the scripted mark.
- [ ] Without the mark, the fallback rail is the rail: the same eight entries, labels, current-page marker and Inbox count as on main. The existing page-shell tests on the current-page marker across nine pages pass against the fallback without being weakened.
- [ ] Contract test: for a fixture of inputs (each of the eight paths as the current page, an Inbox count of 0 and of 3, collapsed and expanded) the fallback markup and the shell's static markup are equal once whitespace is normalised. One command regenerates the golden file, and a difference fails the test.
- [ ] In the browser, on each server-rendered page exactly one rail is visible, in the same column as before (200 pixels wide, 68 collapsed), with no horizontal shift between first paint and the moment the shell mounts: the layout matrix shows no new rail finding, and a pair of photographs at 1280 shows the Agents page before and after.
- [ ] The mounted shell shows the page's own current-page marker and Inbox count on three pages (photographs).
- [ ] The two assets exist under their fixed names in the static bundle folder, the server serves them, the bundle marker test covers them, and two builds give the same tree.
- [ ] `cd frontend && npm run check` prints `tsc --noEmit clean`; `npm test -- --run` passes; `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
