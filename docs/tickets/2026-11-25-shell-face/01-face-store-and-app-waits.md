# 01: One face store, and every app wait drives it

**What to build:** the face's activity registry becomes a store in the shared chunk that every island on a page already loads, so the provider at the app root goes and the hooks keep their names. The shared busy primitives (the busy gate, the phase hook, the phase line, the pending shape and the shared button's pending state) register an activity themselves once a wait has lasted a tenth of a second, with the phase line's label, and take three options: `mood`, `failed` and `quiet`. Every call site in the app sets `failed` or `quiet`. The four waits that were wired to the face by hand move to the primitives. On the Dashboard and the Plugins pages, every wait then puts its mood and its label on the rail face with no wiring of its own.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The store lives in the shared chunk, and two React roots in one document share it: a test mounts two roots and asserts that the second sees the first's activity. The app root mounts with no provider, and `useFaceState` returns the same shape as before.
- [ ] Primitive tests with fake timers: an active wait registers after the tenth of a second and not before, with the phase label; `mood` is honoured for `thinking` and `reading`; `failed` holds `blocked` with the failure text until it is cleared; without `quiet` the end gives `done` for 1.6 seconds; with `quiet` it gives nothing; unmounting withdraws the activity. Each test fails when its behaviour is inverted, and those runs are recorded.
- [ ] Contract test: every call site of `useBusy(`, `usePhase(`, `PhaseLine`, `PendingBody` or `PendingShape`, and of the shared button's pending state, under `frontend/src` with the tests excluded, sets `failed` or `quiet`. A planted call site that sets neither fails it (recorded, then removed).
- [ ] The four hand-wired waits (the research and saved asks, the press and the reply draft, the source re-test) go through the primitives with `thinking` or `reading`, and no wait registers twice (a test asserts one activity per wait).
- [ ] The Memory islands' wait line and wait button register through the same store with their own timeline unchanged (a button from a tenth of a second, a line from one second); each test asserts after one press.
- [ ] `cd frontend && npm run check` prints `tsc --noEmit clean`, and `npm test -- --run` passes.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
- [ ] The committed bundle is rebuilt once from the branch, and two builds give the same tree.
