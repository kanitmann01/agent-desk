# 05: Feedback on the dashboard

**What to build:** every dashboard control that starts async work tells the reader it started. The silent controls (Customize, "Not now") and the disabled-only controls (card-menu Re-test, Sales and Commitments Re-test, tracker Confirm, the press, the reply draft, a skills run) take the shared busy state. The answer regions show a same-shape placeholder with a phase line while the agent works, and a refetch keeps the bento on screen instead of flashing skeletons. The dashboard's first load is a bento-shaped skeleton, not a centered line of text.

**Blocked by:** 01, 02.

**Status:** in progress.

- [ ] Every dashboard control that starts async work shows the F1 busy state on itself: it cannot be pressed twice, carries `aria-busy`, shows the continuous verb and keeps its size.
  - Partly: the controls show the F1 state, stop a second press and carry aria-busy, but the shared Button's box grows by the added dot (see 01, item 2).
- [x] Customize and "Not now" no longer start work with no visible change.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx ('opens with its own pending control...', 'dismisses on the button...').
- [x] The card-menu Re-test, the Sales Re-test, the Commitments Re-test and the tracker Confirm show progress instead of only disabling themselves.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx (card menu, Sales, Commitments and tracker Confirm).
- [x] The research answer shows a placeholder shaped like the answer with a phase line, and the result replaces it in place without a jump.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx (research shaped placeholder and in-place replacement).
- [x] A skills run shows a placeholder in the same answer region with a phase line, and the result replaces it.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx ('runs a skill on its own row and fills the answer card with the same shaped placeholder').
- [x] "Explain this range" shows a placeholder shaped like the explanation, and its result replaces it in place.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx ('explains a range with its own verb...').
- [x] The reply draft shows a placeholder shaped like a draft, and a staged card or refusal replaces it in place.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx ('drafts the reply with a draft-shaped placeholder...').
- [x] After 10 seconds without a change, the phase line says it is taking longer than usual and that the reader may leave the page.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx (ten-second line in the research region).
- [x] A failure names the cause and the next step where it happened; the question, the brief or the other typed words stay in the control.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx (the research failure keeps the question; customize keeps the typed title; the tracker and manual forms keep their values).
- [x] The dashboard's first load is a bento-shaped skeleton with the shell and the regions in place, not a centered text card.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx ('draws the bento skeleton after 100 ms...').
- [ ] A poll or refetch keeps the bento on screen, dimmed, and never swaps in skeletons; one indicator is shown per region.
  - Partly: the poll keeps the bento and never swaps skeletons (frontend/src/test/dashboard-poll.test.tsx), and an in-place action dims its own region (feedback-dashboard.test.tsx); the 8-second background poll itself has no dimmed state (frontend/src/App.tsx, Dashboard.tsx).
- [x] The page does not block while any one region waits.
  - Verified: the dashboard renders the shell and other regions while a held request shows its placeholder (frontend/src/test/feedback-dashboard.test.tsx).
- [x] Component tests cover the busies, the placeholders, the in-place replacement, the 10-second line, the kept input and the dim-and-keep refetch.
  - Verified: frontend/src/test/feedback-dashboard.test.tsx and dashboard-poll.test.tsx cover the busies, placeholders, in-place replacement, ten-second line, kept input and the dimmed region.
- [ ] `python tools/ci_local.py` passes 7/7.
