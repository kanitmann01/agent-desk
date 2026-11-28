# P1 findings: agent face and its signals

## 1. Coverage

- Reviewed source files: 23.
- Generated files: 12 change entries under `src/agentdesk/server/static/spa/` (13 paths when the rename source and destination are counted separately).
- Documentation files: 0. Spec 029 and the naming guard were read as review context, not assigned to P1.
- Range confirmed: `git -C "D:/20-projects/Personal Agents/.worktrees/027-merge" rev-parse --short HEAD` returned `3540b9f` on `merge/027-feedback`.
- Partition diff: `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/review/P1.diff`.

Reviewed files:

1. `frontend/face-sheet.html`
2. `frontend/index.html`
3. `frontend/public/favicon.svg`
4. `frontend/src/App.tsx` (FaceProvider hunks only)
5. `frontend/src/components/CommandBar.tsx`
6. `frontend/src/face/AgentFace.tsx`
7. `frontend/src/face/FaceProvider.tsx`
8. `frontend/src/face/FaceSlot.tsx`
9. `frontend/src/face/brain.ts`
10. `frontend/src/face/config.ts`
11. `frontend/src/face/moods.ts`
12. `frontend/src/face/name.ts`
13. `frontend/src/face/sheet.css`
14. `frontend/src/face/sheet.tsx`
15. `frontend/src/face/useFaceActivity.ts`
16. `frontend/src/test/face-rail.test.tsx`
17. `frontend/src/test/face.test.ts`
18. `frontend/src/dashboard/Rail.tsx` (face-containing hunks only)
19. `frontend/src/index.css` (brand and face-containing hunks only)
20. `src/agentdesk/server/agents_view.py`
21. `src/agentdesk/server/dashboard_state.py`
22. `tests/test_server_agents.py`
23. `tests/test_server_dashboard_api.py`

Generated files listed as generated, not reviewed line by line:

- `src/agentdesk/server/static/spa/assets/index-B08QCR_p.css` (deleted)
- `src/agentdesk/server/static/spa/assets/index-BJj0XD89.js` (deleted)
- `src/agentdesk/server/static/spa/assets/index-Bf3o3Xx2.js`
- `src/agentdesk/server/static/spa/assets/index-D8rifP0q.css`
- `src/agentdesk/server/static/spa/assets/memory-graph-BGjeuZe0.js`
- `src/agentdesk/server/static/spa/assets/memory-graph.css`
- `src/agentdesk/server/static/spa/assets/memory-graph.js`
- `src/agentdesk/server/static/spa/assets/memory-loop.css`
- `src/agentdesk/server/static/spa/assets/memory-loop.js`
- `src/agentdesk/server/static/spa/assets/api-Df6KFqRi.js` renamed to `src/agentdesk/server/static/spa/assets/useBusy-BnHbzNUF.js`
- `src/agentdesk/server/static/spa/favicon.svg`
- `src/agentdesk/server/static/spa/index.html`

Odd fits and shared-file boundaries:

- `frontend/src/App.tsx`, `frontend/src/index.css`, and `frontend/src/dashboard/Rail.tsx` mix face work with feedback or text-fit work. P1 contains only the face-containing hunks. The Rail hunk also carries incidental title-attribute edits because they share one diff hunk.
- `frontend/src/test/tokens.test.ts` changed, but its changed block is pending-button feedback, not face coverage. It belongs with P2. Its missing face contracts are P1-06.
- Cross-partition context inspected for P1 behavior: `frontend/src/dashboard/Dashboard.tsx`, `frontend/src/dashboard/PluginCardView.tsx`, `frontend/src/dashboard/TrackerSetup.tsx`, `frontend/src/marketplace/DescribePlugin.tsx`, `frontend/src/marketplace/MarketplaceApp.tsx`, `frontend/src/types.ts`, `src/agentdesk/agentloop/loop.py`, `src/agentdesk/server/app.py`, `src/agentdesk/server/pages.py`, `tests/test_brand_naming.py`, `tests/test_server_agentloop_api.py`, `frontend/vite.config.ts`, `docs/design-language.md`, and `DESIGN.md`.

## 2. Findings

### P1-01

- **Severity:** P1
- **File:** `frontend/src/face/name.ts`
- **Line:** 2
- **Title:** Brand guard rejects the canonical agent name and the rebuilt bundle
- **What:** The new canonical constant is under `frontend/src`, which `tests/test_brand_naming.py` scans case-insensitively for `nexuus` with no allowlist. The test also scans the committed SPA bundle even though spec 029 requires that bundle to be skipped. The merged tree therefore fails its naming gate. The new face tests add further literal occurrences of the retired string.
- **Why:** Spec 029 lines 21 and 78 require exactly one canonical client line to be allowed, require the line to exist, require the static bundle to be skipped, and require every other live occurrence to fail. Leaving the guard unchanged makes main red; weakening it without the exact allowlist would lose the product-name guarantee.
- **Evidence:** By reading, `tests/test_brand_naming.py:22-28` includes both `ROOT / "src"` and `ROOT / "frontend" / "src"`, and lines 65-67 reject every case-insensitive hit. `frontend/src/face/name.ts:2` is `export const AGENT_NAME = 'Nexuus Bot';`. By running `python -m pytest -q tests/test_brand_naming.py`, the result was `1 failed, 1 passed in 0.42s`. The failure listed 12 hits, including `frontend/src/face/name.ts:2`, both face test files, and `src/agentdesk/server/static/spa/assets/index-Bf3o3Xx2.js:1`.
- **Fix:** Give the guard an exact path-and-line allowlist for `frontend/src/face/name.ts`, assert that the allowed line exists exactly once, skip `src/agentdesk/server/static/spa/`, and make tests refer to `AGENT_NAME` instead of embedding the literal name. Keep the case-insensitive rejection everywhere else.
- **Confidence:** high

### P1-02

- **Severity:** P1
- **File:** `src/agentdesk/server/dashboard_state.py`
- **Line:** 347
- **Title:** Server-driven face signals are not exposed or consumed
- **What:** The dashboard projection reduces the loop status to `lastRunTs`, `nextRunTs`, and `enabled`, dropping `running` and `lastSteps`; the loop still has no `currentStep` or `lastOk`. The SPA polls only `/api/dashboard` every 8 seconds and never requests `/api/agent-loop` on the required 2-second active-pass cadence. `Dashboard.tsx` reports request, inbox, and poll-failure activities but ignores `agentLoop`, fatal `deskCheck` findings, and waiting recommendations. Background passes, clean background completion, fatal desk checks, and recommendation waits therefore cannot drive the face.
- **Why:** Spec 029 line 139 explicitly requires `currentStep`, `lastOk`, the existing loop fields on both payloads, a 2-second active-pass poll, and mood mapping for passes, completion, fatal checks, broken loops, and waiting decisions. User stories 17 through 20 depend on this behavior.
- **Evidence:** By reading, `dashboard_state.py:344-351` builds only three keys from `full = loop.status()`. `frontend/src/types.ts:269-273` has the same three-field `AgentLoopSummary`. `frontend/src/App.tsx:55` sets `POLL_MS = 8000`, and lines 121-126 poll only `refetch()`. `frontend/src/dashboard/Dashboard.tsx:118-138` contains all four face activities and none reads `data.agentLoop`, `data.deskCheck`, or `data.recommendations`. The stale contract is pinned by `tests/test_server_agentloop_api.py:191-195`: `assert set(payload["agentLoop"]) == {"lastRunTs", "nextRunTs", "enabled"}`. By running that file, all 13 tests passed, so the suite is green while the spec-029 fields remain absent.
- **Fix:** Track `currentStep` and `lastOk` around `step.run` under the state lock without holding the lock during the step, expose them with `running` through `dashboard_state` and `/api/agent-loop`, poll loop status every 2 seconds while a pass is active, and map pass, completion, fatal, and recommendation state into scoped face activities. Replace the stale three-key assertion and add the specified deadlock test.
- **Confidence:** high

### P1-03

- **Severity:** P1
- **File:** `frontend/src/marketplace/DescribePlugin.tsx`
- **Line:** 136
- **Title:** Neither opt-in agent dialog mounts the face
- **What:** `DescribePlugin` opens `ModalSheet` with only a title and body. `TrackerSetup` opens `InstanceWalk` with only a title and callbacks. Neither file imports or renders `FaceSlot`, and neither reports modal-scoped face activity. The modal takeover primitive exists, but no production dialog uses it.
- **Why:** Spec 029 lines 30 and 137 require the face beside the heading in both agent-assisted dialogs, with listening/thinking/working/done/blocked states and rail hiding during takeover. These are main plugin and workbook setup flows.
- **Evidence:** By reading, `DescribePlugin.tsx:136-141` is `<ModalSheet open=... title=... busy=... onClose=...>` with no heading face. `TrackerSetup.tsx:263-272` is `<InstanceWalk title="Set up this tracker" ...>` with no face prop. The command `git grep -n "FaceSlot\|useFaceActivity" -- frontend/src/marketplace/DescribePlugin.tsx frontend/src/dashboard/TrackerSetup.tsx` returned no output. The only production `FaceSlot` mount is `frontend/src/dashboard/Rail.tsx:94`.
- **Fix:** Add a modal `FaceSlot` beside each dialog heading and report modal-scoped activities for typing, suggestion/fill work, completion, failure, and no-model idle. Preserve the existing focus trap, Escape handling, and Tab order. Add integration tests against the real dialogs, not only a synthetic `FaceSlot`.
- **Confidence:** high

### P1-04

- **Severity:** P1
- **File:** `frontend/src/test/face.test.ts`
- **Line:** 422
- **Title:** Click-to-squash test never observes a squash
- **What:** The component test named for click squash clicks the face and asserts only that `data-mood` is still `waiting`. It never observes a transform, frame, or brain call. The direct brain test calls `triggerSquash()` itself, so it does not cover the component's click wiring.
- **Why:** A test that passes while the behavior it names is broken is P1 under the brief. Deleting `onClick={() => brainRef.current?.triggerSquash()}` from `frontend/src/face/AgentFace.tsx:175` would leave this test, and the rest of the file, green.
- **Evidence:** By reading, `face.test.ts:422-424` is `fireEvent.click(face); expect(face).toHaveAttribute('data-mood', 'waiting');`. The implementation line that can be deleted without failing the suite is `AgentFace.tsx:175`. By running `npx vitest run src/test/face.test.ts`, all 19 tests passed.
- **Fix:** Inject the fake clock and capture the brain through `onBrainReady`, click the rendered face, advance a frame, assert the box transform changes, then advance past the squash and assert the mood is unchanged and the transform settles.
- **Confidence:** high

### P1-05

- **Severity:** P1
- **File:** `frontend/src/test/face.test.ts`
- **Line:** 260
- **Title:** Autonomous blink and drift test bypasses the wake scheduler
- **What:** The test advances the brain with direct `brain.step(...)` calls. That exercises `advanceAutonomousEvents`, but not the timer callback that wakes a sleeping browser face. The scheduler is therefore not responsible for the behavior the test names.
- **Why:** If the real wake path is broken, the face remains frozen at rest while this test stays green. Deleting `scheduleNextFrame()` from the timer callback at `frontend/src/face/brain.ts:465` would break autonomous animation in the browser but would not fail this test.
- **Evidence:** By reading, `face.test.ts:267-280` repeatedly calls `brain.step(50)` and `brain.step(15)`. The scheduler-aware `advanceTime` helper exists at lines 84-87, but this test does not use it. The deletable production line is `brain.ts:465`, inside the `clock.setTimer` callback at lines 459-466. By running the file, all 19 tests passed.
- **Fix:** Drive `sched.advanceTime(...)` so the scheduled wake timer fires, then flush frames and assert the drift/blink pose. Pin the 2 through 4 second drift and 3 through 6 second blink boundaries through the scheduler rather than manual integration.
- **Confidence:** high

### P1-06

- **Severity:** P2
- **File:** `frontend/src/test/tokens.test.ts`
- **Line:** 297
- **Title:** Face token and bundle contracts are absent
- **What:** The token suite has no face or agent-name assertions. Its changed block tests pending-button layout only. There is no face-specific pin for semantic-only colors, banned effects, reduced motion, review-sheet exclusion, written exceptions, or shipped bundle markers.
- **Why:** Spec 029 lines 153-155 make these tests part of acceptance. General stylesheet guards do not prove that the face stays within its narrow exception or that the review sheet cannot enter the committed bundle.
- **Evidence:** By reading, the changed block at `tokens.test.ts:297-329` is `describe('a pending button keeps its box', ...)`. The command `git grep -n -i "face\|nexuus" -- frontend/src/test/tokens.test.ts` returned no output. By running `npx vitest run src/test/tokens.test.ts`, all 56 tests passed.
- **Fix:** Add the specified face contract block: zero hex literals in face source, no banned effects or `transition: all`, reduced-motion behavior, exact written exceptions, absence of `face-sheet` from `static/spa`, and face markers in the rebuilt JS/CSS bundle.
- **Confidence:** high

### P1-07

- **Severity:** P2
- **File:** `frontend/src/face/brain.ts`
- **Line:** 132
- **Title:** Reduced-motion preference is sampled only at mount
- **What:** The brain reads `prefers-reduced-motion` once during creation and exposes `setReducedMotion`, but nothing subscribes to preference changes. Production `AgentFace` does not pass the optional `reducedMotion` prop, so changing the OS or browser setting while the page is open leaves JavaScript frames and timers running.
- **Why:** User story 29 requires zero frame-by-frame animation under reduced motion. The CSS reduced-motion block cannot stop inline transforms driven by `requestAnimationFrame`.
- **Evidence:** By reading, `brain.ts:132` is `let reducedMotion = options.reducedMotion ?? prefersReducedMotion();`. The command searching `frontend/src/face` for `matchMedia`, change listeners, and `setReducedMotion` found only the one-shot helper at `brain.ts:66-71`, the prop sync at `AgentFace.tsx:127-131`, and the brain setter at `brain.ts:699-714`. The test at `face.test.ts:377-404` forces `reducedMotion: true`; it does not test a live preference change.
- **Fix:** Subscribe to the `MediaQueryList` change event for the lifetime of the brain, call `setReducedMotion` on change, and remove the listener in `destroy`. Add a test that starts animated, changes the media query, and asserts frames and timers stop immediately.
- **Confidence:** high

## 3. Tests that can fail

| New or changed P1 test file | Behavior whose removal would fail it, or finding |
| --- | --- |
| `frontend/src/test/face.test.ts` | Priority resolution, activity cleanup, modal scope isolation, done decay, pointer subscription cleanup, token-only presets, and direct brain easing are exercised. Flagged by P1-04 and P1-05: component click wiring and the autonomous wake path are not. |
| `frontend/src/test/face-rail.test.tsx` | Removing the rail face, collapsed-face rule, phone-bar exclusion, App provider, command-bar listening/gaze cleanup, inbox waiting, research/skill/press/retest transitions, or poll-failure mood would fail these 11 tests. No false-positive finding in this file. |
| `tests/test_server_agents.py` | Changing the redirect away from `/agents`, or failing to record the run, would fail the updated path assertions and count check. Allowing a query string is intentional. |
| `tests/test_server_dashboard_api.py` | Removing `deskNetwork`, changing its first-run value from false, or breaking the top-level payload contract would fail. P1-02 notes that the nested `agentLoop` contract remains incomplete and is not covered by this change. |

Relevant unchanged tests inspected:

- `tests/test_brand_naming.py` is red by running, P1-01.
- `tests/test_server_agentloop_api.py:191-195` passes by running while pinning the stale three-field loop summary, P1-02.
- `frontend/src/test/tokens.test.ts` passes by running but contains no face contracts, P1-06.

Targeted runs performed, each against one allowed file:

- `npx vitest run src/test/face.test.ts`: 19 passed.
- `npx vitest run src/test/face-rail.test.tsx`: 11 passed.
- `npx vitest run src/test/tokens.test.ts`: 56 passed.
- `python -m pytest -q tests/test_brand_naming.py`: 1 failed, 1 passed.
- `python -m pytest -q tests/test_server_agents.py`: 34 passed.
- `python -m pytest -q tests/test_server_dashboard_api.py`: 15 passed.
- `python -m pytest -q tests/test_server_agentloop_api.py`: 13 passed.

## 4. Checked and found correct

- Face body and eye colors use semantic CSS custom properties. The face section of `frontend/src/index.css` has no hex literals, gradients, shadows, blur, `transition: all`, or `@keyframes`. The fixed-color SVG favicon is the documented image-asset exception.
- The eight moods and the priority order `request -> done -> blocked -> waiting -> pass -> listening -> idle` are implemented in `moods.ts` and exercised by provider tests.
- `useFaceActivity` removes entries when deactivated or unmounted. Provider pointer and visibility listeners have cleanup. Done timers are cleared on provider unmount.
- The animation uses exponential ease-out with no overshoot, sleeps after settling, stops frames and wake timers while hidden, and renders static poses when reduced motion is set at creation. P1-07 covers later preference changes only.
- The rail face is before the Agent Desk wordmark, remains visible when collapsed, is centered by the collapsed rule, and is absent from `.phone-bar`. The marketplace reuses this Rail.
- Command-bar focus reports listening, aims at the field center, updates on input and resize, and clears on blur and unmount. Resize listeners are removed.
- Research asks, saved-skill runs, press/draft/stage actions, and source re-tests report active and completion/failure moods through the shared provider.
- `AgentFace` is `aria-hidden="true"`, has no Tab stop, and does not alter modal focus behavior. The synthetic modal takeover test confirms rail hiding, modal isolation, and rail restoration.
- Server-rendered agent forms escape typed briefs and dynamic labels. `status_line` allowlists the role and escapes notice text, so crafted `notice_kind` values cannot inject markup.
- The generated bundle is consistent with source at the checked seams: source and bundled favicons are byte-identical, `static/spa/index.html` references the new hashed JS/CSS and favicon, the JS/CSS contain face markers, and no generated asset contains `face-sheet`.
- No new runtime dependency or face network call was introduced.
