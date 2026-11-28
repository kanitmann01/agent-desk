# P2 review: dashboard, shared components and memory islands

## 1. Coverage

- Worktree: `D:/20-projects/Personal Agents/.worktrees/027-merge`
- Confirmed head: `3540b9f` from `git -C "<worktree>" rev-parse --short HEAD`.
- Range reviewed: `f31582a..3540b9f`.
- Partition diff: `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/review/P2.diff`.
- Disposition: **45 reviewed, 0 generated, 0 documentation**.
- All 45 files in the partition diff were read in full. Specs 026, 027 and 029 were read for acceptance criteria.
- Boundary context reviewed but not counted in P2: `frontend/src/index.css`, `frontend/src/App.tsx`, `frontend/src/components/CommandBar.tsx`, `frontend/src/types.ts`, the server rail in `src/agentdesk/server/pages.py`, and the dashboard payload filter in `src/agentdesk/server/dashboard_state.py`. Face-owned lines remain P1; marketplace-owned behavior remains P3.

Files reviewed:

1. `frontend/src/components/Button.tsx`
2. `frontend/src/components/InstanceWalk.tsx`
3. `frontend/src/components/Stamp.tsx`
4. `frontend/src/components/WidgetCard.tsx`
5. `frontend/src/components/feedback.tsx`
6. `frontend/src/components/useBusy.ts`
7. `frontend/src/dashboard/Brief.tsx`
8. `frontend/src/dashboard/CommitmentsCard.tsx`
9. `frontend/src/dashboard/CustomizeCell.tsx`
10. `frontend/src/dashboard/Dashboard.tsx`
11. `frontend/src/dashboard/DashboardSkeleton.tsx`
12. `frontend/src/dashboard/PluginCardView.tsx`
13. `frontend/src/dashboard/Rail.tsx`
14. `frontend/src/dashboard/ResearchCard.tsx`
15. `frontend/src/dashboard/SalesCard.tsx`
16. `frontend/src/dashboard/SetupStrip.tsx`
17. `frontend/src/dashboard/SkillsCard.tsx`
18. `frontend/src/dashboard/TrackerCard.tsx`
19. `frontend/src/dashboard/TrackerSetup.tsx`
20. `frontend/src/dashboard/briefModel.ts`
21. `frontend/src/dashboard/cells.tsx`
22. `frontend/src/dashboard/pending.tsx`
23. `frontend/src/dashboard/pluginKind.ts`
24. `frontend/src/dashboard/useWorkbookConnect.ts`
25. `frontend/src/memory/MemoryGraph.tsx`
26. `frontend/src/memory/feedback.tsx`
27. `frontend/src/memory/loop/MemoryLoop.tsx`
28. `frontend/src/memory/loop/memory-loop.css`
29. `frontend/src/memory/memory-graph.css`
30. `frontend/src/test/brief-decisions.test.tsx`
31. `frontend/src/test/button-pending.test.tsx`
32. `frontend/src/test/cards.test.tsx`
33. `frontend/src/test/customize.test.tsx`
34. `frontend/src/test/dashboard-poll.test.tsx`
35. `frontend/src/test/feedback-dashboard.test.tsx`
36. `frontend/src/test/feedback-memory.test.tsx`
37. `frontend/src/test/memory-graph.test.tsx`
38. `frontend/src/test/memory-loop.test.tsx`
39. `frontend/src/test/review-dashboard.test.tsx`
40. `frontend/src/test/setup-strip.test.tsx`
41. `frontend/src/test/shell.test.tsx`
42. `frontend/src/test/text-fit-dashboard.test.ts`
43. `frontend/src/test/text-fit-memory.test.ts`
44. `frontend/src/test/tracker-cards.test.tsx`
45. `frontend/src/test/widget-card.test.tsx`

## 2. Findings

### P2-01, P1: A chosen tracker face still renders the classic face above it

- **File:** `frontend/src/dashboard/TrackerCard.tsx`
- **Line:** 76
- **What:** For a live `excel-report` instance with `payload.face === 'ui-schema'`, `TrackerCard` renders `TrackerFigure` and then renders the chosen schema elements. The manager sees the classic value, delta, workbook, trend and pace plus the face they chose. The new wizard-face test only checks that the chosen `Value` exists, so it passes with the duplicate classic face still present.
- **Why:** Spec 025 requires that a workbook plugin which asked for a big number does not render the classic tracker face. Spec 027 requires one tracker tile with one face. This is a user-visible duplicate on the custom-tracker path, and the test gives false confidence that the chosen-face contract is held.
- **Evidence:** By reading `frontend/src/dashboard/TrackerCard.tsx:76-90`, the live branch always renders `<TrackerFigure ... />` before the `wizardFace` branch renders `faceElements`. By reading `frontend/src/dashboard/PluginCardView.tsx:385-388`, every `excel-report` id is still routed to `TrackerCard` even when `face` is `ui-schema`. The added test at `frontend/src/test/tracker-cards.test.tsx:250-266` sets `face: 'ui-schema'` and `elements: [{ kind: 'metric', label: 'Value', value: '42' }]`, then asserts only:

  ```tsx
  expect(screen.getByText('42')).toBeInTheDocument();
  expect(screen.getByText('Value')).toBeInTheDocument();
  ```

  It never asserts that `.figure` is absent. By running `cd frontend && npx vitest run src/test/tracker-cards.test.tsx`, all 9 tests passed while the classic figure remains mounted by reading.
- **Fix:** Render exactly one face. Keep `TrackerFigure` only when `face` is not `ui-schema`, and render the chosen elements plus an Edit action when it is. Add a regression assertion that a wizard-face `excel-report` has no `.figure` and no classic `.spark`, while retaining the chosen Value and Edit control.
- **Confidence:** high.

### P2-02, P2: The slow-wait line promises a result that is not persisted

- **File:** `frontend/src/components/feedback.tsx`
- **Line:** 10
- **What:** After ten seconds the shared phase line says the reader may leave and that the result will be here when they return. The SPA has no job object or result store. A research answer is returned only by the in-flight POST and is not restored into the answer panel after a reload, so leaving can lose the visible result even though the request may finish.
- **Why:** F4 promises only that the line names a long wait and says the reader may leave. The extra return promise is false for main asks and can cause a manager to abandon a long request believing the answer is safely waiting.
- **Evidence:** By reading `frontend/src/components/feedback.tsx:9-10`, `SLOW_SUFFIX` is `This is taking longer than usual. You may leave this page; the result will be here when you return.` By reading `frontend/src/dashboard/Dashboard.tsx:1493-1531`, the research result is placed only in component state through `showAnswer`. By reading `src/agentdesk/server/app.py:2394-2409`, the server returns the answer in the POST response and captures memory, but does not persist a dashboard answer to replay. Spec 027 lines 195-197 explicitly excludes a job object and streaming result storage.
- **Fix:** Remove the return promise and use the F4 wording: `This is taking longer than usual. You may leave this page.` If a durable result is wanted, add a job/result store as separate work before promising it.
- **Confidence:** high.

### P2-03, P2: The removal dialog loses its focus trap while removal is pending

- **File:** `frontend/src/memory/loop/MemoryLoop.tsx`
- **Line:** 1279
- **What:** When confirmation starts, Cancel and the removal button both become disabled. The Tab handler queries only enabled buttons and returns when there are none, so the next Tab moves focus into the page behind the `aria-modal` dialog.
- **Why:** A keyboard user can reach and activate background controls during a destructive wait. The dialog still claims `aria-modal="true"`, so assistive technology is told the background is inert when it is not.
- **Evidence:** By reading `frontend/src/memory/loop/MemoryLoop.tsx:1275-1283`, the handler does `const stops = ...('button:not(:disabled)'); if (stops.length === 0) return;`. By reading lines 1320-1334, `working` disables Cancel through `disabled={working}` and `WaitButton` disables itself through `disabled={disabled || active}`. The existing Tab test at `frontend/src/test/memory-loop.test.tsx:360` exercises the idle dialog only. The new pending test at `frontend/src/test/feedback-memory.test.tsx:320-339` checks busy text and failure recovery but never presses Tab. Both files passed when run.
- **Fix:** Keep a focus target inside the dialog while working, for example a `tabIndex=-1` dialog container focused on confirm, and prevent Tab or Shift+Tab from escaping when no enabled button remains. Add a pending-state Tab regression test.
- **Confidence:** high.

### P2-04, P2: The removal-check skeleton is an unmanaged modal

- **File:** `frontend/src/memory/loop/MemoryLoop.tsx`
- **Line:** 1241
- **What:** After one second of a removal preview request, `RemovePreviewSkeleton` renders a `role="dialog" aria-modal="true"` scrim. It has no initial focus, no focus trap, no Escape handling and does not make the background inert. Keyboard focus remains on the Forget button behind the scrim and can walk through the page.
- **Why:** The placeholder introduces a modal state on a rare but destructive path without the focus contract of the real `RemoveDialog`. Keyboard and screen-reader users can interact with content that the dialog declares unavailable.
- **Evidence:** By reading `frontend/src/memory/loop/MemoryLoop.tsx:1236-1254`, `RemovePreviewSkeleton` returns only static markup and a `WaitLine`. Unlike `RemoveDialog` at lines 1264-1290, it has no refs, effect, keydown listener or focus restoration. The feedback-memory suite passed, but its removal tests resolve the preview before the one-second skeleton appears and therefore never exercise this dialog.
- **Fix:** Use the same modal shell/focus helper as `RemoveDialog`, or make the preview skeleton non-modal and keep focus on the invoking control until the real dialog opens. Add a test that holds the preview past one second and asserts focus stays in the dialog and Tab does not escape.
- **Confidence:** high.

### P2-05, P3: Memory refetch dimming animates opacity outside the motion rule

- **File:** `frontend/src/memory/memory-graph.css`
- **Line:** 196
- **What:** The new refetch states fade the graph body and memory grid with opacity transitions. The design language permits 120 ms motion on color and background only, so opacity animation is outside the written exception budget.
- **Why:** This is a strict design-language departure introduced by the feedback wave. The dimmed refetch state itself is required by F6, but it does not need a fade.
- **Evidence:** By reading `frontend/src/memory/memory-graph.css:196`, the rule is `.mg.is-refreshing .mg-body{opacity:.55;transition:opacity var(--dur) ease}`. By reading `frontend/src/memory/loop/memory-loop.css:233`, the loop grid has the same opacity transition. `docs/design-language.md:199-200` states `Motion is 120ms on color and background only`. The reduced-motion blocks disable these transitions, but the normal-motion rule still exceeds the stated property set.
- **Fix:** Keep the opacity change instant by removing the opacity transition from both refetch rules, or explicitly amend the design language and token tests if opacity fades are intended.
- **Confidence:** high.

### P2-06, P3: A drag reorder shows the Move up pending verb on the dragged card

- **File:** `frontend/src/dashboard/CustomizeCell.tsx`
- **Line:** 230
- **What:** `Dashboard.dropCard` records the generic action `move`, but `CustomizeCell` maps `move` only to the Move up control. If the dragged card moves down, its Move up control shows `Moving up` while the save is in flight.
- **Why:** The control that started the save reports the wrong direction. The phase line is generic and correct, but the per-control continuous verb required by F1 is false.
- **Evidence:** By reading `frontend/src/dashboard/Dashboard.tsx:507-521`, `dropCard` saves with `action: 'move'` regardless of direction. By reading `frontend/src/dashboard/CustomizeCell.tsx:227-245`, `pending === 'move-up' || pending === 'move'` selects Move up, while Move down accepts only `move-down`. The customize suite passed but contains no held drag-save assertion for the pending verb.
- **Fix:** Give `LayoutPending` an explicit direction for drag moves, or use a neutral `Moving...` control state for `move`. Add a held drag-down test that asserts the dragged card does not claim `Moving up`.
- **Confidence:** high.

### P2-07, P2: The tracker setup dialog does not mount the agent face

- **File:** `frontend/src/dashboard/TrackerSetup.tsx`
- **Line:** 264
- **What:** Spec 029 names workbook tracker setup as one of the two opt-in agent dialogs. `TrackerSetup` renders `InstanceWalk`, whose `ModalSheet` heading contains only the title and Close button. No `FaceSlot` is mounted, so the rail face remains visible and the dialog's suggestion lifecycle does not drive a modal face.
- **Why:** The modal takeover and single-visible-face contract is not implemented for this P2 dialog. The existing chart sketch and `Choosing the columns` line remain useful feedback, which is the workaround, but the specified agent presence is absent.
- **Evidence:** By reading `frontend/src/dashboard/TrackerSetup.tsx:263-272`, the component returns `InstanceWalk` with no face-related prop or child. By reading `frontend/src/components/ModalSheet.tsx:88-93`, the heading is fixed to `<h2>` plus Close and the shell exposes no heading adornment slot. Spec 029 lines 27-31 and 137 require `TrackerSetup` to mount a modal `FaceSlot` beside its heading and hide the rail face. The tracker setup tests in `frontend/src/test/feedback-dashboard.test.tsx` exercise Confirm and close behavior but never assert a modal face.
- **Fix:** Add an optional heading adornment to the shared dialog shell, mount `FaceSlot slot="modal"` in `TrackerSetup`, and register suggestion states as thinking, done, blocked or idle. Add integration assertions for one visible face, rail hiding, and rail restoration on close.
- **Confidence:** high.

## 3. Tests that can fail

All 16 changed P2 test files were run individually from `frontend/`. All passed: 314 tests total. No whole gate, server, walk or layout audit was run.

| Test file | Behaviour whose removal would fail it, or finding |
|---|---|
| `frontend/src/test/brief-decisions.test.tsx` | Grouped headline and stats, source/plugin health counts, `never` for an unrun plugin, one tag per kind, full-row health/tracker spans, and an unreadable digest date rendering without a time. |
| `frontend/src/test/button-pending.test.tsx` | Pending buttons are disabled, expose only the continuous label, carry `aria-busy`, preserve submit type, and keep both labels; `useBusy` holds the 100 ms boundary, resets and clears timers; CSS pulses by opacity and freezes under reduced motion. |
| `frontend/src/test/cards.test.tsx` | Research shows an answer-shaped pending region, health rows have a separate plugin group/count, stage labels expose full values, and a malformed digest date does not throw. |
| `frontend/src/test/customize.test.tsx` | Hidden built-in cells disappear while health remains, renamed built-in titles appear with fixed kind tags, columns follow saved order, and skills sort among lower cells. |
| `frontend/src/test/dashboard-poll.test.tsx` | Eight-second visible polling, hidden-tab pause, last-screen retention on failure, and rejection of a late stale response. The merge change itself only adapts the layout fixture. |
| `frontend/src/test/feedback-dashboard.test.tsx` | The 100 ms control/placeholder gate, ten-second line, in-place research result, kept question on failure, customize/skill/workbook/press/manual/tracker waits, closed-sheet announcement, first-load skeleton and quiet failed poll. |
| `frontend/src/test/feedback-memory.test.tsx` | One-second memory skeletons, stale refetch retention, busy controls, approve-all partial counts, blocked double switches, reflection placeholder/result, kept edits, failed removal recovery and failed undo recovery. It does not cover pending-modal focus, see P2-03 and P2-04. |
| `frontend/src/test/memory-graph.test.tsx` | Graph rendering, keyboard selection/provenance, lineage dimming, empty/locked states, and full titles for fixed labels and counts. |
| `frontend/src/test/memory-loop.test.tsx` | Candidate approve/reject/edit routes, both review-mode directions, typed fact add, fact edit/cancel, removal preview/Escape/idle Tab trap, and graph focus handoff. The idle Tab trap does not cover the pending state in P2-03. |
| `frontend/src/test/review-dashboard.test.tsx` | The 100 ms layout-save gate, exact stage-value title, refused research error instead of a blank answer, ten-second save lines, hidden-research answer region, dropped-plugin grid gaps, and no-transport Page watch honesty. |
| `frontend/src/test/setup-strip.test.tsx` | Setup step states, sample toggle outcomes, and the sample switch's dot plus both labels in one row container. |
| `frontend/src/test/shell.test.tsx` | Rail entries/count/collapse persistence, avatar title, blank-question guards, Enter behavior, answer clearing, bento skeleton and session-expired recovery copy. |
| `frontend/src/test/text-fit-dashboard.test.ts` | Exact CSS contracts for roots, rail, command bar, widget header/menu, figures, wrapping rows, tables, timeline, scrollers, health matrix, tracker reading, spans, grouped numbers and plugin tags. |
| `frontend/src/test/text-fit-memory.test.ts` | Exact CSS contracts for both island roots, wrapping rows, fixed values, reachable truncation, wide graph containment, pending-button geometry and responsive memory layouts. |
| `frontend/src/test/tracker-cards.test.tsx` | Classic tracker duplicate-element filtering, grouped figures, one reading block/disclosure, and chosen schema elements. **Flagged by P2-01:** the wizard-face case passes while the forbidden classic face is still rendered. |
| `frontend/src/test/widget-card.test.tsx` | Header/menu structure, named menu trigger, menu gutter only when needed, stamp color/title/focus and empty-stamp handling. |

## 4. Checked and found correct

- **Shared pending primitive.** `Button` preserves submit type through prop spread order, disables immediately when pending, exposes the continuous label, hides the idle label from assistive technology, and marks `aria-busy`. `useBusy` clears timers on unmount and resets when activity stops. The design language explicitly allows a longer pending verb to widen the box by the label difference, so the grid-label implementation is not treated as a defect.
- **Dashboard truthfulness.** Desk health counts exactly its three source rows and gives plugin rows a separate count. A missing `checkedAt` renders `never`. Unknown plugin kinds render `PLUGIN`, not `DIGEST`. The client no-transport guard reads the real `payload.source.reason` emitted by the runner, and the server filters the top-level `sourceReason` before serialization.
- **Tracker de-duplication for the classic face.** The five restating element kinds and labels are filtered, the remaining reading is one separated block with a native disclosure, and the press remains. The separate chosen-face defect is P2-01.
- **Numbers.** Display grouping preserves sign and decimals, leaves nonnumeric and already-grouped strings alone, and does not alter workbook bindings. Compact stage values expose the exact signed value through `title`.
- **Digest resilience.** An invalid calendar start leaves the event title and detail visible and omits only the time instead of throwing.
- **Dashboard loading and polling.** The first load has bento geometry, `aria-busy`, a phase line and reduced-motion-safe feedback. The polling suite proves a late response cannot overwrite a newer payload and a failed poll keeps the last screen.
- **Memory stale-refetch behaviour.** Both islands keep prior content on a failed refresh, identify it as previous content, and offer retry. Successful writes keep typed input on failure and report outcomes in place.
- **Memory write guards.** Approve-all counts partial failures, candidate edits survive failed saves, switches reject a second toggle while pending, reflection ignores a repeat click, and removal/undo failures keep their recovery controls.
- **Text fit.** The dashboard and memory CSS suites pin the intended wrap, shrink, nowrap, scroller, fixed-table and responsive declarations. The wide graph is contained by a wide document column rather than an overflowing transform.
- **Accessibility outside the findings.** Rail links retain accessible names when collapsed, the inbox name includes its count, icon-only controls are named, the normal removal dialog focuses Cancel and traps Tab while idle, and the shared `ModalSheet` has a robust focus trap with a no-focusable fallback.
- **Security.** P2 introduces no filesystem path handling, keychain access, model-key access or network destination. Dynamic React values are rendered as text. No key, token or password was copied into this report.
- **Known starting points in P2.** The missing tracker-setup face is confirmed as P2-07. Rail divergence is confirmed in part: the SPA alone mounts the face and theme picker (`frontend/src/dashboard/Rail.tsx:93-130`), marketplace fixes the inbox badge to zero (`frontend/src/marketplace/MarketplaceApp.tsx:142`), and the SPA marks Plugins current for deep marketplace routes while the server uses exact href equality (`frontend/src/dashboard/Rail.tsx:108`, `src/agentdesk/server/pages.py:1520`). The claimed toggle-state mismatch is refuted: both rails update `aria-expanded`, label and title (`frontend/src/dashboard/Rail.tsx:65-75`, `src/agentdesk/server/pages.py:1400-1406`). The background-loop signal and plugin-description dialog belong to P1/P3 and were not duplicated here.
- **Generated bundle.** No generated file is assigned to P2. Bundle consistency remains a whole-merge check outside this partition.
