# 01: One shared busy state

**What to build:** one pending state that every surface can put on a control. A button that starts work can show that it is working, cannot be pressed again, tells assistive technology, keeps its size, and never appears for work that finishes inside 100ms. The state is a prop on the shared button and one hook for the regions that own the wait.

**Blocked by:** None (can start immediately).

**Status:** in progress (another builder owns this ticket).

- [ ] `Button` accepts `pending` and `pendingLabel`; while pending it carries `aria-busy="true"`, shows `pendingLabel`, and a second click does not start the work again.
- [ ] A pending button's box does not change size: padding, font size, line height and width stay the same between the idle and pending labels.
- [ ] The pending indicator is a dot that pulses in colour only; `prefers-reduced-motion` freezes the pulse to a still dot.
- [ ] A button without `pending` renders exactly as it does today, with the same markup, tone, label and disabled behaviour.
- [ ] `useBusy(active, delayMs = 100)` returns false before the delay and true after it, and returns to false when `active` falls.
- [ ] The 100ms boundary is tested with fake timers from both sides: a 99ms wait shows nothing, a 101ms wait shows the busy state.
- [ ] The stylesheet holds the pulse and the reduced-motion freeze, and `frontend/src/test/tokens.test.ts` pins both declarations.
- [ ] Component tests assert the label swap, the aria attribute, the ignored second press and the unchanged size class.
- [ ] `python tools/ci_local.py` passes 7/7 with the new tests.
