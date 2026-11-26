# 05: Memory page waits light the face

**What to build:** the Memory page and the graph page are React islands inside the server-rendered shell. Their waits go through their own copies of the wait line and the wait button, which now report to the shared face store. This ticket makes sure every wait on those pages lights the shell's face: capture, review, sweep, recall, the embeddings backfill, and the graph's own loading.

**Blocked by:** 01: One face store, and every app wait drives it. 03: The shell on server-rendered pages.

**Status:** ready-for-agent

- [ ] An inventory of every wait in the two islands is written in the evidence: what starts it, its label, its mood option, and whether it sets `failed` or `quiet`. Nothing is left out; the contract test of ticket 01 covers both islands.
- [ ] Each wait has a unit test with fake timers that asserts after one press: the face state carries the island's mood and label for the length of the wait, and returns to idle when it ends.
- [ ] In the browser on an isolated desk with sample data, at least four waits on the Memory page show a non-idle face while they run, and the face returns to idle. One photograph per wait.
- [ ] The islands' own feedback is unchanged: their existing tests pass, and their timeline is still a button from a tenth of a second and a line from one second.
- [ ] `cd frontend && npm run check` prints `tsc --noEmit clean`; `npm test -- --run` passes; `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
