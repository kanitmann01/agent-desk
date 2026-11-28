# P3 findings: the marketplace

All repository paths below are relative to `D:/20-projects/Personal Agents/.worktrees/027-merge`. The worktree head was confirmed as `3540b9f`; `git status --short` remained empty after review and test runs.

## 1. Coverage

- Reviewed: 29 changed files.
- Generated: 0.
- Documentation: 0.
- Odd fits: none. `scripts/marketplace_walkthrough.py` belongs to P5 under the explicit `tools/` rule, and `src/agentdesk/marketplace/` belongs to P4 under the explicit Python rule.

Reviewed source files:

- `frontend/src/marketplace/Admin.tsx`
- `frontend/src/marketplace/CatalogPage.tsx`
- `frontend/src/marketplace/ConsentSheet.tsx`
- `frontend/src/marketplace/DescribePlugin.tsx`
- `frontend/src/marketplace/Installed.tsx`
- `frontend/src/marketplace/MarketGrid.tsx`
- `frontend/src/marketplace/MarketplaceApp.tsx`
- `frontend/src/marketplace/PluginDetail.tsx`
- `frontend/src/marketplace/Publishers.tsx`
- `frontend/src/marketplace/Sample.tsx`
- `frontend/src/marketplace/Studio.tsx`
- `frontend/src/marketplace/Trust.tsx`
- `frontend/src/marketplace/admin-trust.css`
- `frontend/src/marketplace/client.ts`
- `frontend/src/marketplace/marketplace.css`
- `frontend/src/marketplace/permissions.ts`
- `frontend/src/marketplace/types.ts`
- `frontend/src/marketplace/useBusyWatchdog.ts`

Reviewed test and test-support files:

- `frontend/src/test/feedback-marketplace.test.tsx`
- `frontend/src/test/marketplace-admin.test.tsx`
- `frontend/src/test/marketplace-cannot-run.test.tsx`
- `frontend/src/test/marketplace-detail.test.tsx`
- `frontend/src/test/marketplace-digest.test.tsx`
- `frontend/src/test/marketplace-discover.test.tsx`
- `frontend/src/test/marketplace-fixtures.ts`
- `frontend/src/test/marketplace-installed.test.tsx`
- `frontend/src/test/marketplace-manage-instances.test.tsx`
- `frontend/src/test/review-marketplace.test.tsx`
- `frontend/src/test/text-fit-marketplace.test.ts`

The complete partition diff is `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/review/P3.diff`.

## 2. Findings

### P3-01, P1: A cannot-run plugin still offers the dead Re-run validator action

- **file:** `frontend/src/marketplace/PluginDetail.tsx`
- **line:** 924
- **title:** A cannot-run plugin still offers the dead Re-run validator action
- **what:** The detail page hides the action labelled `Re-test` when `cannotRun` is true, but the validator panel still renders `Re-run validator` for every installed plugin. That button calls the same `retest` lifecycle and posts to `/api/marketplace/retest`, which only re-probes the data source. It cannot add the missing HTTP transport.
- **why:** This is a user-visible dead end on the plugin detail path and contradicts spec 027's requirement that a re-test appear only where it can change something. The cannot-run test is green while this second entry point to the same dead action remains.
- **evidence:** By reading, `frontend/src/marketplace/PluginDetail.tsx:924-929` renders `Re-run validator` with only `installed` as its guard, while `:532` computes `cannotRun` and `:626-631` sends the shared `retest` action. `src/agentdesk/marketplace/api.py:1686-1688` describes that endpoint as re-probing the data source. The test at `frontend/src/test/marketplace-cannot-run.test.tsx:78-88` checks only `queryByRole('button', { name: 'Re-test' })`. By running, `npx vitest run src/test/marketplace-cannot-run.test.tsx` passed all 9 tests despite the `Re-run validator` button in the source.
- **fix:** Guard the validator button with `installed && !cannotRun`, and extend the test to reject both labels, for example with `/re-test|re-run validator/i`. Add one assertion that the cannot-run detail exposes only Uninstall and Purge data actions.
- **confidence:** high

### P3-02, P1: The lifecycle busy test passes while install, update and consent still bypass F1

- **file:** `frontend/src/test/feedback-marketplace.test.tsx`
- **line:** 445
- **title:** The lifecycle busy test passes while install, update and consent still bypass F1
- **what:** The test named `names each plugin detail lifecycle action while it runs` drives only Enable and Re-test. It never holds an install, update or consent request. Those three actions still use `ConsentSheet`'s boolean `busy` prop, which immediately renders the generic label `Working…` and has no 100 ms gate or action-specific continuous verb.
- **why:** Ticket 06 explicitly claims install, update, consent, disable, retest, rollback, purge and uninstall all show the F1 busy state. This test passes with half of that named behaviour absent or broken, which is the P1 test-quality failure defined by the brief.
- **evidence:** By reading, `frontend/src/test/feedback-marketplace.test.tsx:445-480` defines deferred responses only for `/enable` and `/retest`, then asserts only `Enabling…` and `Re-testing…`. `frontend/src/marketplace/ConsentSheet.tsx:110-113` renders `disabled={busy}` and `{busy ? 'Working…' : confirmLabel}` without `pending` or `useBusy`. By running, `npx vitest run src/test/feedback-marketplace.test.tsx` passed all 20 tests, including this overclaiming test.
- **fix:** Add held-request cases for install, update and consent that assert no visible change before 100 ms, then the correct continuous label and `aria-busy="true"`. Give `ConsentSheet` a delayed `pending` state and an action-specific `pendingLabel` supplied by each caller.
- **confidence:** high

### P3-03, P2: The installed cannot-run cache is keyed by pinned version but reads the current catalog release

- **file:** `frontend/src/marketplace/Installed.tsx`
- **line:** 185
- **title:** The installed cannot-run cache is keyed by pinned version but reads the current catalog release
- **what:** The effect keys its capability cache by `<plugin id>\0<pinned version>`, but fetches `/api/marketplace/plugin/<id>` without a version. The server returns `detail(entry)` for the current catalog entry. Its `requested` version is validated but never used to select detail. The installed DTO also carries no capabilities from the active installed manifest.
- **why:** After an update or rollback, the Installed page can attribute the latest release's web requirement to a different pinned release. It can therefore hide usable controls or offer retest/update controls for a release that cannot run. The regression test mocks the detail response using an external `pinned` variable, so it does not exercise the real API contract.
- **evidence:** By reading, `frontend/src/marketplace/Installed.tsx:164-187` builds the pinned-version key and makes the unversioned detail request. `src/agentdesk/marketplace/api.py:501-512` reads and validates `query.get('version')`, but `:539-542` still sends `detail(entry)`. `_installed_summary` at `:393-416` contains no capability block. `frontend/src/test/review-marketplace.test.tsx:487-531` changes its mock's `pinned` variable and returns capabilities from that variable, masking the server behaviour.
- **fix:** Return the active installed manifest's capabilities in `InstalledSummary`, or implement and call a detail endpoint that actually selects the requested pinned version. Key the cache by id plus digest as well as version. Add a server-contract test where the catalog version and pinned version differ.
- **confidence:** high

### P3-04, P2: A failed capability read is cached as proof that the plugin does not need the web

- **file:** `frontend/src/marketplace/Installed.tsx`
- **line:** 189
- **title:** A failed capability read is cached as proof that the plugin does not need the web
- **what:** The detail-read catch writes `false` into `webUse`. The effect treats any present cache key as resolved and does not retry until the installed id/version set or `deskNetwork` changes. A transient failed request therefore becomes a durable non-web answer for that sitting.
- **why:** The source comment says a failed read claims nothing, but the implementation makes the opposite claim. The cannot-run notice can stay absent and dead controls can remain available even though the plugin's capabilities were never read.
- **evidence:** By reading, `frontend/src/marketplace/Installed.tsx:158` says `A failed read claims nothing`, while `:183-190` catches the failure and executes `cache.set(entry.key, false)`. `:178-180` then considers that key complete because `cache.has(entry.key)` is true.
- **fix:** Do not cache failures. Keep the entry unknown, allow a later list reload or explicit retry to read it again, and add a test whose first detail request fails and whose second request supplies web capabilities.
- **confidence:** high

### P3-05, P1: The non-web installed-plugin test asserts before the capability read can finish

- **file:** `frontend/src/test/marketplace-cannot-run.test.tsx`
- **line:** 196
- **title:** The non-web installed-plugin test asserts before the capability read can finish
- **what:** The test waits for the installed heading, then uses `waitFor` only to assert that the notice is absent. `cannotRunIds` starts empty and the detail request is asynchronous, so the negative assertion can pass before `asksForWeb` is evaluated. A regression that marks every plugin as web-dependent can still leave this test green.
- **why:** This is a test that passes while the behaviour it names is broken: showing no cannot-run state for a plugin that does not ask for the web.
- **evidence:** By reading, `frontend/src/test/marketplace-cannot-run.test.tsx:196-205` never holds, releases or awaits the detail response. `frontend/src/marketplace/Installed.tsx:111` initializes `cannotRunIds` to an empty set, and `:183-191` fills it only after the detail promise settles. By running, the file passed all 9 tests; the negative `waitFor` has no positive synchronization condition.
- **fix:** Make the detail response deferred, wait until its URL has been requested, release a non-web capability payload, flush the promise and effects, and only then assert the notice is absent. Add the inverse case where the same delayed read returns web capabilities and the notice appears.
- **confidence:** high

### P3-06, P2: DescribePlugin does not mount the spec-required modal face

- **file:** `frontend/src/marketplace/DescribePlugin.tsx`
- **line:** 136
- **title:** DescribePlugin does not mount the spec-required modal face
- **what:** The plain-English plugin description dialog renders `ModalSheet` with a text heading and no `FaceSlot` or scoped face activity. Spec 029 names this dialog as one of the two opt-in agent modals and requires the rail face to hand off to the modal while its work drives the face.
- **why:** The merged code omits an explicit acceptance criterion. The rail face remains the only visible face, and listening, working, done and blocked states are not reflected in the dialog.
- **evidence:** By reading, `frontend/src/marketplace/DescribePlugin.tsx:7-11` imports no face modules and `:136-195` renders the modal without a face slot. `specs/029-nexuus-bot-agent-face.md:30` requires the face in plain-English plugin description, and `:137` repeats the modal placement and state mapping. A repository search for `slot="modal"` under `frontend/src` returned only `frontend/src/test/face.test.ts`, no production mount.
- **fix:** Add a modal `FaceSlot` beside the dialog heading and scoped `useFaceActivity` entries for writing, asking, filled and failed phases. Add an integration test that opens this actual dialog, verifies one visible face, and verifies the rail handoff and cleanup.
- **confidence:** high

### P3-07, P2: The marketplace rail hardcodes the inbox waiting count to zero

- **file:** `frontend/src/marketplace/MarketplaceApp.tsx`
- **line:** 142
- **title:** The marketplace rail hardcodes the inbox waiting count to zero
- **what:** The marketplace shell renders `<Rail inboxWaiting={0} ...>`. The dashboard passes `data.inbox.waiting`, and `Rail` omits both the visible badge and the accessible waiting count when the value is zero.
- **why:** Inbox items that need attention disappear from navigation while a manager browses plugins. This confirms the marketplace half of the known rail inconsistency.
- **evidence:** By reading, `frontend/src/marketplace/MarketplaceApp.tsx:142` passes zero, while `frontend/src/dashboard/Dashboard.tsx:680` passes `data.inbox.waiting`. `frontend/src/dashboard/Rail.tsx:40` renders no badge for zero and `:52` changes the accessible name to plain `Inbox`.
- **fix:** Lift the inbox waiting count into the shared shell or provide the marketplace with the same lightweight count source, then pass that value to `Rail`. Add a marketplace-shell test with a nonzero count.
- **confidence:** high

### P3-08, P2: Dialog waits violate the 10 second F4 release contract

- **file:** `frontend/src/marketplace/useBusyWatchdog.ts`
- **line:** 7
- **title:** Dialog waits violate the 10 second F4 release contract
- **what:** The new locked-dialog watchdog is 180,000 ms, not 10 seconds. It is used only by purge and rollback/uninstall confirmations. Consent and describe dialogs have no watchdog at all: their close/cancel callbacks refuse to run while busy, so a request that never settles can keep the reader in the modal indefinitely.
- **why:** Spec 027 user story 36 and design-language F4 require a line after 10 seconds saying the wait is longer than usual and that the reader may leave. The current implementation withholds that line for three minutes on some dialogs and forever on others.
- **evidence:** By reading, `frontend/src/marketplace/useBusyWatchdog.ts:7` sets `BUSY_WATCHDOG_MS = 180_000`; `docs/design-language.md:178-180` requires 10 seconds. `frontend/src/marketplace/ConsentSheet.tsx:109-112` leaves Cancel enabled-looking but the parent guards at `frontend/src/marketplace/PluginDetail.tsx:1007` refuse it while `busy` is nonempty. `frontend/src/marketplace/DescribePlugin.tsx:139-140` similarly refuses `onClose` while busy. Neither dialog imports the watchdog or `PhaseLine`.
- **fix:** Use the shared 10 second phase contract in every busy marketplace dialog. Let Cancel, Escape and Close dismiss the dialog while the request continues, and route the late result through the existing announcement channel. Keep destructive confirmation text if the dialog remains open, but do not trap the reader.
- **confidence:** high

### P3-09, P2: Remaining marketplace async controls bypass the shared 100 ms busy contract

- **file:** `frontend/src/marketplace/Studio.tsx`
- **line:** 412
- **title:** Remaining marketplace async controls bypass the shared 100 ms busy contract
- **what:** Studio's Run validator, Install on this desk and Publish for review controls use immediate ternary labels with `disabled`, but no `useBusy`, `pending`, or `aria-busy`. Plugin and publisher report submissions do the same. Catalog, detail and publisher retry buttons simply increment an attempt with no pending state at all.
- **why:** Spec 027 requires every wait to follow F1: nothing visible under 100 ms, then a continuous verb and `aria-busy` on the control. These paths flash busy text for fast requests, omit the screen-reader busy state, and allow repeated retry presses to start overlapping reads.
- **evidence:** By reading, `frontend/src/marketplace/Studio.tsx:412-414`, `:437-439` and `:455-458` render immediate labels without the shared busy props. `frontend/src/marketplace/PluginDetail.tsx:331` and `frontend/src/marketplace/Publishers.tsx:206` do the same for report submission. `frontend/src/marketplace/CatalogPage.tsx:285`, `:300` and `:307` render retry buttons that only call `setAttempt`.
- **fix:** Route these controls through `useBusy` and `Button pending` with action-specific labels. Track retry state so a second press is ignored, and add fake-timer boundary tests for one Studio action and one catalog retry.
- **confidence:** high

## 3. Tests that can fail

| Test file | Behaviour whose removal would fail it, or finding id |
|---|---|
| `frontend/src/test/feedback-marketplace.test.tsx` | Removing the 100 ms gate, action label, row locking, shaped placeholders, dim-and-keep refetch, same-query retry, or session notice would fail its assertions. P3-02 flags the lifecycle test's untested install/update/consent branches. P3-09 notes additional async controls outside this file's coverage. |
| `frontend/src/test/marketplace-admin.test.tsx` | Removing the digest/environment-code focus and title attributes, or the policy-diff scroll wrapper, would fail it. |
| `frontend/src/test/marketplace-cannot-run.test.tsx` | Removing the detail/consent notices or the installed two-action state would fail its positive assertions. P3-01 flags the missed validator retest, and P3-05 flags the unsynchronized non-web assertion. |
| `frontend/src/test/marketplace-detail.test.tsx` | Removing the fact-value focus/title attributes or digest focus/title would fail it. |
| `frontend/src/test/marketplace-digest.test.tsx` | Removing the two-second copied state, clipboard fallback, selected full digest, or fallback layout rules would fail it. |
| `frontend/src/test/marketplace-discover.test.tsx` | Removing server-side filtering or the category tag's focus/title would fail it. |
| `frontend/src/test/marketplace-fixtures.ts` | Test support, not a test. Removing the optional `deskNetwork` fixture field would break the cannot-run and feedback tests that pass it. |
| `frontend/src/test/marketplace-installed.test.tsx` | Removing the pilot title or purge confirmation code focus/title would fail it. |
| `frontend/src/test/marketplace-manage-instances.test.tsx` | Removing instance loading state or changing the existing setup/edit behaviour would fail the helper or workflow assertions. |
| `frontend/src/test/review-marketplace.test.tsx` | Removing cross-row locking, detail caching, dialog failure retention, retry feedback, late outcome announcements, cannot-run notices, or watchdog release would fail its assertions. P3-03 flags the mocked pinned-version premise. |
| `frontend/src/test/text-fit-marketplace.test.ts` | Removing any pinned wrap, shrink, nowrap, cap, or scroller declaration would fail it. |

All ten actual test files were run individually from `frontend/`, never as a whole gate. The combined result was 96 passed tests:

- `marketplace-cannot-run.test.tsx`: 9 passed.
- `feedback-marketplace.test.tsx`: 20 passed.
- `review-marketplace.test.tsx`: 20 passed.
- `marketplace-digest.test.tsx`: 4 passed.
- `text-fit-marketplace.test.ts`: 11 passed.
- `marketplace-manage-instances.test.tsx`: 15 passed.
- `marketplace-admin.test.tsx`: 3 passed.
- `marketplace-detail.test.tsx`: 3 passed.
- `marketplace-discover.test.tsx`: 8 passed.
- `marketplace-installed.test.tsx`: 3 passed.

## 4. Checked and found correct

- **Diff and scope:** The head is `3540b9f`, all 29 P3 changed files were read in the partition diff, and the worktree stayed clean. No generated or documentation files fall in P3.
- **Escaping and confinement:** Dynamic catalog, policy, digest, publisher and report values are rendered through React text nodes or attributes, not raw HTML. Plugin and publisher ids are encoded before being placed in client routes. The new policy import and purge controls retain server-side confirmation and do not introduce a real-data or keychain path.
- **Session expiry:** `onSessionExpired` returns an unsubscriber, `MarketplaceApp` uses it in an effect cleanup, and the notice focuses its heading, names the next step and offers no futile retry.
- **Busy serialization:** Installed and admin rows disable all competing row actions while one mutation is in flight. The rollback/uninstall and purge dialogs retain failures, keep typed confirmation, and release after their watchdog. The digest copy timer and watchdog timers are cleared on cleanup.
- **Request staleness:** Catalog, detail, publisher and manage-instance reads use cancellation flags or request-keyed effects to avoid painting stale responses. Catalog refetches keep and dim prior results rather than flashing skeletons.
- **Cannot-run presentation:** Catalog cards, publisher grids, detail and install consent show the web-transport limitation before install. Missing `deskNetwork` or missing card capabilities are treated as unknown, not as proof of inability. Non-agent consent, rollback, uninstall and purge dialogs do not mount a face, as spec 029 requires.
- **Destructive confirmation:** Purge still requires the exact `delete-data:<id>` token on both Installed and Detail, and the client sends that token to the server. Uninstall keeps the data folder and is described that way.
- **Accessibility and text fit:** The new CSS uses semantic tokens, adds no literal hex colours and no new transitions. Skeletons are hidden from assistive technology while a status line names the phase, reduced motion freezes skeleton animation, long code and table cells scroll inside bounded wrappers, and shortened values gain titles or focusable full-value access. Dialog focus traps and Escape handlers remain in place.
- **Starting points:** The missing face in DescribePlugin is confirmed by P3-06. The marketplace inbox badge fixed to zero is confirmed by P3-07. The tracker-setup face belongs to P2; the background loop signal belongs to P1. No P3 evidence was found for the other starting points outside this partition.
- **Contradictions worth carrying into the fix round:** The detail page hides `Re-test` but leaves the same operation as `Re-run validator`; the installed cache comments promise pinned-version and failed-read safety that the code does not provide; the lifecycle test claims every action but covers two; and the dialog watchdog is three minutes while the written F4 rule is ten seconds.
