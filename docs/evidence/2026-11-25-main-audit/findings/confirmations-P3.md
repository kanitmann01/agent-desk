# P3 confirmations

Audit worktree: `D:/20-projects/Personal Agents/.worktrees/027-merge` at `3540b9fd5fd3f113901e5d3af4e5730d1374e44e`.

## P3-01: confirmed

**Methods:** reading, running.

**Reading evidence:** `frontend/src/marketplace/PluginDetail.tsx:532` computes `cannotRun` when the desk has no transport and the plugin asks for the web. The lifecycle control at `:219-224` hides `Re-test` when `cannotRun` is true. The validator panel at `:924-929` guards `Re-run validator` only with `installed`, and its click handler calls `lifecycle('retest', 'validate')`. That lifecycle posts to `/api/marketplace/retest` at `:626-631`. `src/agentdesk/marketplace/api.py:1686-1688` defines that endpoint as re-probing the installed data source, so it cannot supply the missing HTTP transport. The closest test, `frontend/src/test/marketplace-cannot-run.test.tsx:78-88`, waits for the cannot-run notice and queries only the exact button name `Re-test`; it never queries `Re-run validator`.

**Run evidence:** From the audit worktree's `frontend/` folder, `npx vitest run src/test/marketplace-cannot-run.test.tsx` reported `1 passed (1)` and `9 passed (9)`.

**Decision:** The second retest entry point remains visible on the main plugin detail path for an installed cannot-run plugin, and it cannot change the missing transport. This independently reproduces the finding.

**Severity:** P1 holds. It is a user-visible dead action on the main plugin detail path. It also contradicts `specs/027-one-home-screen-feedback.md:149`, which says the retest control is absent because retesting cannot change the transport, and ticket 04 at `docs/tickets/2026-11-24-feedback/04-honest-cards.md:13`, which says there is no Re-test.

**Mutation:** None required under the assigned P3-01 scope.

## P3-02: confirmed

**Methods:** reading, running, mutation.

**Reading evidence:** `frontend/src/test/feedback-marketplace.test.tsx:445-480` is named `names each plugin detail lifecycle action while it runs`, but it holds only `/enable` and `/retest`, then checks only `Enabling…` and `Re-testing…`. Install, update and consent reach `confirmConsent` at `frontend/src/marketplace/PluginDetail.tsx:563-597` through one `ConsentSheet` at `:992-1009`. `frontend/src/marketplace/ConsentSheet.tsx:110-113` has only a boolean `busy` prop, immediate generic `Working…` text, `disabled`, and `aria-busy`; it has no delayed pending state or action-specific continuous label. Ticket 06 at `docs/tickets/2026-11-24-feedback/06-marketplace-feedback.md:11-12` claims all eight named lifecycle buttons show F1 and cites this test as verification.

**Baseline run:** From the audit worktree's `frontend/` folder, `npx vitest run src/test/feedback-marketplace.test.tsx` reported `1 passed (1)`, `20 passed (20)`, and the named lifecycle test passed.

**Mutation:** In detached worktree `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/P3-02`, changed `frontend/src/marketplace/ConsentSheet.tsx:110-113`. Replaced the confirm button's `disabled={busy}`, `aria-busy`, and `Working…` branch with an always-enabled button that keeps `confirmLabel`. This removes all existing busy presentation from the shared install, update and consent confirm control. From that worktree's `frontend/` folder, `npx vitest run src/test/feedback-marketplace.test.tsx` still reported `1 passed (1)`, `20 passed (20)`, and the named lifecycle test passed.

**Decision:** The test cannot detect removal of the consent-sheet busy presentation for install, update or consent. It verifies Enable and Re-test only, while its name and ticket verification claim every lifecycle action. The missing F1 behavior is also present in the unmutated source.

**Severity:** P1 holds under the brief's test-quality definition: a test passes while the behavior it names is broken. Separately, the affected controls violate `docs/design-language.md:159-165`, which requires no visible busy state under 100 ms, followed by an action-specific continuous verb, `aria-busy="true"`, and a second-press guard.

**Cleanup:** The P3-02 temporary worktree was removed with `git worktree remove --force`, and a subsequent `git worktree list` confirmed it was gone.

## P3-05: confirmed

**Methods:** reading, running, mutation.

**Reading evidence:** `frontend/src/test/marketplace-cannot-run.test.tsx:196-206` waits for the installed heading, then uses `waitFor` only for the absence of `Cannot run on this desk`. It does not wait for the detail URL, release a held response, or otherwise establish that capability evaluation finished. `frontend/src/marketplace/Installed.tsx:111` starts `cannotRunIds` empty. The effect at `:183-191` fills it only after the detail promise settles and `asksForWeb` has been evaluated.

**Baseline run:** From the audit worktree's `frontend/` folder, `npx vitest run src/test/marketplace-cannot-run.test.tsx` reported `1 passed (1)` and `9 passed (9)`.

**Mutation:** In detached worktree `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/P3-05`, changed `frontend/src/marketplace/Installed.tsx:187` from `cache.set(entry.key, asksForWeb(data.plugin.capabilities));` to `cache.set(entry.key, true);`. This one-line mutation makes every fetched plugin web-dependent, including the non-web fixture.

**Mutation runs:**

- Full closest test file: `npx vitest run src/test/marketplace-cannot-run.test.tsx` reported `1 failed (1)`, `8 passed`, with the non-web case failing because the document contained `Cannot run on this desk`. In this full-file ordering, the incorrect state arrived soon enough for the negative `waitFor` to catch it.
- Named case alone from the same file: `npx vitest run src/test/marketplace-cannot-run.test.tsx -t 'shows no state when the plugin does not ask for the web'` reported `1 passed`, `8 skipped`, in 81 ms. The assertion completed before the mutated asynchronous capability result painted the incorrect badge.

**Decision:** The named test can pass while the production behavior is broken. The isolated run reproduces the reviewer's race directly. The full-file run also shows that current test ordering accidentally makes this particular mutation fail, so the coverage is timing- and order-dependent rather than reliably protective. The finding is confirmed with that limitation recorded.

**Severity:** P1 holds under the brief's test-quality definition because the named case passed while the behavior it names was broken. It is not a claim that every full-file run misses the regression.

**Cleanup:** The P3-05 temporary worktree was removed with `git worktree remove --force`, and a subsequent `git worktree list` confirmed it was gone. No P3 mutation worktree remains.
