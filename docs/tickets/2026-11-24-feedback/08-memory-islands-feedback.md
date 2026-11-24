# 08: Feedback on the memory islands

**What to build:** the memory pages show their waits like every other surface. "Ask AI for observations" takes the busy state and ignores a repeat click, the learning switches show that they are saving, "Approve all" shows progress, the first load is a skeleton shaped like the page, and a failed refetch keeps the page on screen and says what went wrong in place.

**Blocked by:** 01.

**Status:** queued.

- [ ] "Ask AI for observations" shows the F1 busy state while the reflection runs, and a second click does not start a second run.
- [ ] The observation region shows a placeholder shaped like observation rows with a phase line while the AI works, and the result replaces it in place.
- [ ] After 10 seconds without a change, the phase line says it is taking longer than usual and that the reader may leave the page.
- [ ] Each learning switch shows its own pending state while its setting is saved, and a second click is ignored.
- [ ] "Approve all" shows progress while the queue is being accepted, and a second press is ignored.
- [ ] The memory page's first load is a skeleton shaped like the page, not a single line of text.
- [ ] A failed refetch keeps the current page and its data, and says in place what could not be re-read; it does not replace the page with an alert.
- [ ] A failed switch or reflection keeps the switch or the page state that was there, and names the cause and the next step.
- [ ] Component tests cover the busies, the placeholder, the 10-second line, the kept page on a failed refetch and the first-load skeleton.
- [ ] `python tools/ci_local.py` passes 7/7.
