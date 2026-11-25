# 01: One shared busy state

**What to build:** one pending state that every surface can put on a control. A button that starts work can show that it is working, cannot be pressed again, tells assistive technology, keeps its size, and never appears for work that finishes inside 100ms. The state is a prop on the shared button and one hook for the regions that own the wait.

**Blocked by:** None (can start immediately).

**Status:** done (2026-11-24).

- [x] `Button` accepts `pending` and `pendingLabel`; while pending it carries `aria-busy="true"`, shows `pendingLabel`, and a second click does not start the work again.
  - Verified: frontend/src/components/Button.tsx (pending, pendingLabel, aria-busy) and frontend/src/test/button-pending.test.tsx ('announces busy and stops accepting activation', 'exposes only the pending label').
- [x] A pending button's box does not change size: padding, font size, line height and width stay the same between the idle and pending labels.
  - Verified: this was not true of the first build (the dot sat in the flow and widened the button by about 16px; the ticket close-out caught it). Commit 838a540 takes the dot out of the flow and shifts the labels by the same amount; 0b39392 keeps a busy text button on one line; 2cbed99 does the same in the memory loop's own sheet. Measured in a real browser with the request held: primary, secondary and small buttons are 63.19 x 39, 63.19 x 39 and 56.81 x 30 idle and pending. The last pending walk measured the box of all 253 busy controls and reports `box-changed=0` (build/last-pending/20261124-212717): none moved in height, and none moved in width while keeping its label.
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
- [x] Component tests assert the label swap, the aria attribute, the ignored second press and the unchanged size class.
  - Verified: `frontend/src/test/button-pending.test.tsx` asserts the label stack, the hidden idle label, the aria attribute and the ignored second press; since 838a540 and 0b39392 `frontend/src/test/tokens.test.ts` pins the declarations that hold the box (the out-of-flow dot, the label shift, the text button's one row), and `frontend/src/test/setup-strip.test.tsx` pins the busy text button's markup. jsdom cannot measure layout, so the size itself is proven in the browser, under the item above.
- [x] `python tools/ci_local.py` passes 7/7 with the new tests.
  - Verified: `python tools/ci_local.py` passed 7/7 on `2d00540` (127 s) and again on the head that was pushed, 7/7 in 117 s (pytest 3520 passed, 1 skipped; vitest 596).
