# 05: Feedback on the dashboard

**What to build:** every dashboard control that starts async work tells the reader it started. The silent controls (Customize, "Not now") and the disabled-only controls (card-menu Re-test, Sales and Commitments Re-test, tracker Confirm, the press, the reply draft, a skills run) take the shared busy state. The answer regions show a same-shape placeholder with a phase line while the agent works, and a refetch keeps the bento on screen instead of flashing skeletons. The dashboard's first load is a bento-shaped skeleton, not a centered line of text.

**Blocked by:** 01, 02.

**Status:** queued.

- [ ] Every dashboard control that starts async work shows the F1 busy state on itself: it cannot be pressed twice, carries `aria-busy`, shows the continuous verb and keeps its size.
- [ ] Customize and "Not now" no longer start work with no visible change.
- [ ] The card-menu Re-test, the Sales Re-test, the Commitments Re-test and the tracker Confirm show progress instead of only disabling themselves.
- [ ] The research answer shows a placeholder shaped like the answer with a phase line, and the result replaces it in place without a jump.
- [ ] A skills run shows a placeholder in the same answer region with a phase line, and the result replaces it.
- [ ] "Explain this range" shows a placeholder shaped like the explanation, and its result replaces it in place.
- [ ] The reply draft shows a placeholder shaped like a draft, and a staged card or refusal replaces it in place.
- [ ] After 10 seconds without a change, the phase line says it is taking longer than usual and that the reader may leave the page.
- [ ] A failure names the cause and the next step where it happened; the question, the brief or the other typed words stay in the control.
- [ ] The dashboard's first load is a bento-shaped skeleton with the shell and the regions in place, not a centered text card.
- [ ] A poll or refetch keeps the bento on screen, dimmed, and never swaps in skeletons; one indicator is shown per region.
- [ ] The page does not block while any one region waits.
- [ ] Component tests cover the busies, the placeholders, the in-place replacement, the 10-second line, the kept input and the dim-and-keep refetch.
- [ ] `python tools/ci_local.py` passes 7/7.
