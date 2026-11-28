# P1 confirmations

## P1-01: Brand guard rejects the canonical agent name and the rebuilt bundle

- Verdict: `confirmed`.
- Methods: reading, running.
- Reading: `tests/test_brand_naming.py:22-28` includes `frontend/src`, and `:65-67` rejects every case-insensitive `nexuus` hit without an allowlist. Because `src` is also scanned, `src/agentdesk/server/static/spa/` is included. `frontend/src/face/name.ts:2` is the required canonical `AGENT_NAME = 'Nexuus Bot'` line. Spec 029:21 and :78 require exactly that line to be allowed and present, the static bundle to be skipped, and all other occurrences to fail. `frontend/src/test/face.test.ts:151-165,415,584,667` and `frontend/src/test/face-rail.test.tsx:198,256,360` add literal occurrences.
- Running: from the read-only worktree root, `python -m pytest -q tests/test_brand_naming.py` produced `F.` and `1 failed, 1 passed in 0.86s`. The failure reported 12 hits, beginning with `src/agentdesk/server/static/spa/assets/index-Bf3o3Xx2.js:1` and `frontend/src/face/name.ts:2`, followed by both face test files.
- Mutation: null. This finding is a direct failing-test reproduction, not a false-positive test claim.
- Severity: P1 holds. The merged tree cannot pass its required naming acceptance gate on the main validation path, while the runtime product name remains correct. The failure needs the exact canonical-line exception and generated-bundle skip, not a broad allowlist.

## P1-02: Server-driven face signals are not exposed or consumed

- Verdict: `confirmed`.
- Methods: reading, running.
- Reading: `src/agentdesk/server/dashboard_state.py:344-353` projects `loop.status()` into only `lastRunTs`, `nextRunTs`, and `enabled`, dropping `running` and `lastSteps`. `src/agentdesk/agentloop/loop.py:447-469` returns those existing fields but no `currentStep` or `lastOk`. `frontend/src/types.ts:269-273` repeats the three-field client type. `frontend/src/App.tsx:50-55,84-88,121-126` polls only `/api/dashboard` every 8000 ms. `frontend/src/dashboard/Dashboard.tsx:118-138` registers only request, request-error, inbox-waiting, and poll-failure face activities; it has no `agentLoop`, `deskCheck`, or `recommendations` reference. `tests/test_server_agentloop_api.py:191-195` explicitly pins the incomplete three-key dashboard summary. Spec 029:139 requires `currentStep`, `lastOk`, and all existing loop fields on both payloads, a 2-second active-pass poll, and pass/completion/fatal/waiting mood mapping.
- Running: from the read-only worktree root, `python -m pytest -q tests/test_server_agentloop_api.py` produced `.............` and `13 passed in 7.12s`, including the stale three-key contract.
- Mutation: null. The requested reading plus closest single test file reproduces the missing contract and false-green coverage.
- Severity: P1 holds. The home dashboard's face cannot report active background work, clean completion, fatal health, broken-loop state, or recommendation waits on a main user path, even though the backend already has some of the raw signals.

## P1-03: Neither opt-in agent dialog mounts the face

- Verdict: `confirmed`.
- Methods: reading, running.
- Reading: `frontend/src/marketplace/DescribePlugin.tsx:7-11,136-141` imports no face API and opens `ModalSheet` with only `open`, `title`, `busy`, `onClose`, and children. `frontend/src/dashboard/TrackerSetup.tsx:7-18,263-272` imports no face API and opens `InstanceWalk` with only its walk props. Their shells also carry no face: `frontend/src/components/ModalSheet.tsx:7-14,88-94` renders the heading, close button, and children, while `frontend/src/components/InstanceWalk.tsx:99-129,143-147` has no face prop or mount. A production search found `FaceSlot` only in `frontend/src/dashboard/Rail.tsx:94`; the other mount is the dev-only `frontend/src/face/sheet.tsx:63`. Neither dialog registers `useFaceActivity`. Spec 029:30 and :137 require both dialogs to hold a modal face and report their agent-assisted states.
- Running: from the read-only worktree's `frontend` folder, `npx vitest run src/test/describe-plugin.test.tsx` produced `Test Files 1 passed (1)` and `Tests 4 passed (4)`. The closest dialog tests at `frontend/src/test/describe-plugin.test.tsx:78-144` assert the input, buttons, busy rows, filled labels, and failure alert, but no face or face mood. The run also emitted jsdom's expected `HTMLFormElement.prototype.submit` not-implemented warning in the no-AI fallback test; it did not fail the file.
- Mutation: null. Reading plus the closest single dialog test reproduces the missing production mount and missing assertions.
- Severity: P1 holds. Both are main opt-in agent-assisted flows, and the required persistent agent presence and state feedback are absent from their user-visible dialogs.

## P1-04: Click-to-squash test never observes a squash

- Verdict: `confirmed`.
- Methods: reading, running, mutation.
- Reading: `frontend/src/test/face.test.ts:408-424` names the component behavior, clicks `.face-box`, and asserts only that `data-mood` remains `waiting`. It never reads `style.transform`, advances a frame, or observes a brain call. The direct brain test at `:284-317` calls `brain.triggerSquash()` itself at `:312`, so it cannot cover the component's click wiring. The removable production behavior is `frontend/src/face/AgentFace.tsx:175`, `onClick={() => brainRef.current?.triggerSquash()}`.
- Running: `npx vitest run src/test/face.test.ts` in the read-only worktree's `frontend` folder produced `Test Files 1 passed (1)` and `Tests 19 passed (19)`.
- Mutation: in detached worktree `mutation/P1-04` at `3540b9f`, after its own `npm ci`, deleted only `frontend/src/face/AgentFace.tsx:175`, the `onClick` squash handler. The diff was a single removed line. `npx vitest run src/test/face.test.ts` still produced `Test Files 1 passed (1)` and `Tests 19 passed (19)`. The named click behavior was broken while the file stayed green.
- Severity: P1 holds under the brief's explicit rule for a test that passes while the behavior it names is broken.

## P1-05: Autonomous blink and drift test bypasses the wake scheduler

- Verdict: `confirmed`.
- Methods: reading, running, mutation.
- Reading: `frontend/src/test/face.test.ts:260-282` advances the brain only through direct `brain.step(...)` calls. The scheduler-aware helper at `:84-87` advances fake time and fires due timers, but this test never calls it. `frontend/src/face/brain.ts:459-466` is the sleeping brain's wake callback; after advancing autonomous events it calls `scheduleNextFrame()` at `:465`. Without that call, the timer can update internal event state but no frame renders the blink or drift.
- Running: the same read-only `npx vitest run src/test/face.test.ts` baseline used for P1-04 produced `Test Files 1 passed (1)` and `Tests 19 passed (19)`.
- Mutation: in detached worktree `mutation/P1-05` at `3540b9f`, after its own `npm ci`, deleted only `frontend/src/face/brain.ts:465`, `scheduleNextFrame()`, from the wake timer callback. The diff was a single removed line. `npx vitest run src/test/face.test.ts` still produced `Test Files 1 passed (1)` and `Tests 19 passed (19)`. Browser autonomous wake-to-frame behavior was broken while the file stayed green.
- Severity: P1 holds under the brief's explicit rule for a test that passes while the behavior it names is broken.
