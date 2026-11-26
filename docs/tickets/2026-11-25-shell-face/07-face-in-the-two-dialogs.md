# 07: The face in the two working dialogs

**What to build:** Spec 029 said the face moves beside the heading of the plugin description dialog and of the tracker setup dialog. On main it does not. This ticket builds it: each dialog mounts a face slot beside its heading; while either is open the shell's face hides and only that dialog's work drives the face; and each shows the moods Spec 029 listed for it.

**Blocked by:** 01: One face store, and every app wait drives it.

**Status:** ready-for-agent

- [ ] Both dialogs render a compact face slot beside the heading, and while either is open the shell's face slot is not in the document. A test covers each dialog and the moment it closes.
- [ ] Plugin description: typing gives `listening`; filling gives `working` with the row index stepping as the fields fill; filled gives `done`; a refused fill gives `blocked` with the cause. One test per mood.
- [ ] Tracker setup: choosing the columns gives `thinking`; a ready proposal gives `done`; a failure gives `blocked`; no model configured gives `idle` with the hint shown. One test per case.
- [ ] Background activity does not change a dialog's face while the dialog is open, and the shell face returns on close with its own state intact.
- [ ] The consent review, uninstall, rollback, purge and memory-removal dialogs mount no face and leave the shell face alone: the existing tests plus one new assertion for each.
- [ ] The face is hidden from assistive technology and cannot take focus. Every existing focus-trap, Escape and focus-return test for the two dialogs passes unchanged.
- [ ] Photographs of both dialogs in each of their moods at 1280 in the three themes.
- [ ] `cd frontend && npm run check` prints `tsc --noEmit clean`; `npm test -- --run` passes; `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
