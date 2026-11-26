# 04: Declared waits on server-rendered pages

**What to build:** the page script announces a declared wait at the one place where it becomes visible: a start event with the label (in the script's existing order of precedence) and the position of the placeholder, and an end event with the note's words when its watchdog unlocks a stuck form. The outcome line that a form post lands on carries an explicit outcome. The shell listens: it shows working and looks toward the placeholder during the wait; it shows done or blocked from the outcome line when the page loads; it holds blocked while a stuck-form note is shown; and it shows listening while a text field in the main region has focus. Pressing Run on the Agents page then lights the face for the whole run.

**Blocked by:** 01: One face store, and every app wait drives it. 03: The shell on server-rendered pages.

**Status:** ready-for-agent

- [ ] A form that declares its wait sends the start event after the tenth of a second and not before, carrying the label in the existing order of precedence (the button's label, then the form's, then the wait label, then the default). Tests use fake timers.
- [ ] The outcome line is rendered with an explicit outcome, `success` for a status and `failure` for an alert. The Python page tests assert it on a landing page for both kinds.
- [ ] The stuck-form watchdog sends the end event with the note's words (a test with fake timers at its timeout).
- [ ] The shell maps each signal, with a test for each and the inverted run recorded: start gives `working` with the label and a look target at the placeholder's centre; outcome success gives `done` for 1.6 seconds and then idle; outcome failure holds `blocked` while the line is in the document; a stuck note gives `blocked` with the note's words; focus in a text field gives `listening` aimed at the field, and blur ends it.
- [ ] In the browser on an isolated desk with the mock model: pressing Run on the worksheet brief shows the face `working` with the declared label during the wait and `done` on the page the run lands on; a refused run lands with `blocked`. Photographs of both.
- [ ] Forms on Memory, Inbox and Settings that declare a wait behave the same: in the pending pass, every one of them that meets its feedback rule has a lit face.
- [ ] `cd frontend && npm run check` prints `tsc --noEmit clean`; `npm test -- --run` passes; `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
