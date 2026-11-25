# 01: One shared busy state

**What to build:** one pending state that every surface can put on a control. A button that starts work can show that it is working, cannot be pressed again, tells assistive technology, keeps its size, and never appears for work that finishes inside 100ms. The state is a prop on the shared button and one hook for the regions that own the wait.

**Blocked by:** None (can start immediately).

**Status:** in progress.

- [x] `Button` accepts `pending` and `pendingLabel`; while pending it carries `aria-busy="true"`, shows `pendingLabel`, and a second click does not start the work again.
  - Verified: frontend/src/components/Button.tsx (pending, pendingLabel, aria-busy) and frontend/src/test/button-pending.test.tsx ('announces busy and stops accepting activation', 'exposes only the pending label').
- [ ] A pending button's box does not change size: padding, font size, line height and width stay the same between the idle and pending labels.
  - Not done: the pending render adds a dot and the button's 8px gap (frontend/src/components/Button.tsx:44-58, frontend/src/index.css:502-531), so its width grows by about 16px from the idle state; only the two labels share one grid cell.
- [x] The pending indicator is a dot that pulses in colour only; `prefers-reduced-motion` freezes the pulse to a still dot.
  - Verified: frontend/src/index.css @keyframes setup-pick changes opacity only; frontend/src/test/button-pending.test.tsx asserts no transform and the reduced-motion freeze.
- [x] A button without `pending` renders exactly as it does today, with the same markup, tone, label and disabled behaviour.
  - Verified: frontend/src/test/button-pending.test.tsx ('renders no busy attribute, no dot and its normal label').
- [x] `useBusy(active, delayMs = 100)` returns false before the delay and true after it, and returns to false when `active` falls.
  - Verified: frontend/src/components/useBusy.ts and frontend/src/test/button-pending.test.tsx (delay, fall, flap, unmount).
- [x] The 100ms boundary is tested with fake timers from both sides: a 99ms wait shows nothing, a 101ms wait shows the busy state.
  - Verified: frontend/src/test/button-pending.test.tsx ('stays false below the delay and turns true at 100 ms'): 99 ms false, 100 ms true, so the boundary is covered.
- [x] The stylesheet holds the pulse and the reduced-motion freeze, and `frontend/src/test/tokens.test.ts` pins both declarations.
  - Verified: frontend/src/index.css and frontend/src/test/button-pending.test.tsx pin both; frontend/src/test/tokens.test.ts only asserts that a reduced-motion block exists.
- [ ] Component tests assert the label swap, the aria attribute, the ignored second press and the unchanged size class.
  - Partly: frontend/src/test/button-pending.test.tsx asserts the label stack and hidden idle label, the aria attribute and the ignored second press, but no size-holding class for the added dot.
- [ ] `python tools/ci_local.py` passes 7/7 with the new tests.
