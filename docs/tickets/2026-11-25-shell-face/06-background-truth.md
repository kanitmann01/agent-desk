# 06: Background truth on every page

**What to build:** the face tells the truth about the desk itself on every page, not only on the Dashboard. The loop status endpoint reports the step that is running and whether the last step ended well, the two fields Spec 029 described and nobody built. The shell polls the loop status and the dashboard payload while the document is visible and maps them to moods: a running pass, items waiting in Inbox, a fatal check or a broken loop. A page that already polls the same payload passes its values down, so no page runs two polls.

**Blocked by:** 03: The shell on server-rendered pages.

**Status:** ready-for-agent

- [ ] `GET /api/agent-loop` carries the step running now and whether the last step ended well, correct while a step runs and after it ends. A step that asks for the status while it is running does not deadlock. A desk with no loop still gets the 503 it gets today.
- [ ] Mapping tests with fake timers: a running pass gives `working` at the pass rank; the last run time moving forward between two visible polls, with the last step ended well, gives one `done`; waiting Inbox items give `waiting`; a fatal check or a broken loop gives `blocked`; a loop that is off or absent gives no mood and logs no error.
- [ ] A wait the user started outranks the pass, and the pass mood returns when that wait ends.
- [ ] Polling: every eight seconds while visible with no pass, every two seconds while a pass runs, and not at all while the document is hidden. On the Dashboard route the shell adds no request: a test counts them.
- [ ] In the browser on an isolated desk: with the loop enabled, a running pass shows `working` on a server-rendered page (photograph); with the loop off, the face stays idle and the browser console shows no error.
- [ ] `cd frontend && npm run check` prints `tsc --noEmit clean`; `npm test -- --run` passes; `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
