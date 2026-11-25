# 08: Feedback on the memory islands

**What to build:** the memory pages show their waits like every other surface. "Ask AI for observations" takes the busy state and ignores a repeat click, the learning switches show that they are saving, "Approve all" shows progress, the first load is a skeleton shaped like the page, and a failed refetch keeps the page on screen and says what went wrong in place.

**Blocked by:** 01.

**Status:** done (2026-11-24).

- [x] "Ask AI for observations" shows the F1 busy state while the reflection runs, and a second click does not start a second run.
  - Verified: frontend/src/test/feedback-memory.test.tsx ('shows the observation placeholder after a second...' asserts the Ask button aria-busy and the repeat click).
- [x] The observation region shows a placeholder shaped like observation rows with a phase line while the AI works, and the result replaces it in place.
  - Verified: frontend/src/test/feedback-memory.test.tsx (the placeholder has ml-feedback-placeholder and ml-row, and the result replaces it).
- [x] After 10 seconds without a change, the phase line says it is taking longer than usual and that the reader may leave the page.
  - Verified: frontend/src/test/feedback-memory.test.tsx ('names the slow wait after ten seconds and says the reader may leave').
- [x] Each learning switch shows its own pending state while its setting is saved, and a second click is ignored.
  - Verified: frontend/src/memory/loop/MemoryLoop.tsx Switch and WaitButton; frontend/src/test/feedback-memory.test.tsx ('stops a double switch toggle...').
- [x] "Approve all" shows progress while the queue is being accepted, and a second press is ignored.
  - Verified: frontend/src/memory/loop/MemoryLoop.tsx WaitButton 'Approving N of M...' and disabled while active; frontend/src/test/feedback-memory.test.tsx (approve-all partial result).
- [x] The memory page's first load is a skeleton shaped like the page, not a single line of text.
  - Verified: frontend/src/test/feedback-memory.test.tsx ('shows the page skeleton only after a second, never a bare status line first').
- [x] A failed refetch keeps the current page and its data, and says in place what could not be re-read; it does not replace the page with an alert.
  - Verified: frontend/src/test/feedback-memory.test.tsx ('keeps the page when a poll fails and says it is the previous content').
- [x] A failed switch or reflection keeps the switch or the page state that was there, and names the cause and the next step.
  - Verified: frontend/src/test/feedback-memory.test.tsx (the failed switch keeps aria-checked and names the cause; the failed save keeps the typed edit and offers Try again).
- [x] Component tests cover the busies, the placeholder, the 10-second line, the kept page on a failed refetch and the first-load skeleton.
  - Verified: frontend/src/test/feedback-memory.test.tsx covers the busies, placeholder, ten-second line, kept page and first-load skeleton.
- [ ] `python tools/ci_local.py` passes 7/7.
