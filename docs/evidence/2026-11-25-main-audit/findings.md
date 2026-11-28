# Founder's decisions, 2026-11-25

- The re-triage below is accepted as proposed: the three moves to spec 030 (tickets 030-6 and 030-7) and spec 031 (ticket 031-1), and ticket 031-1 runs straight after the audit closes. Every destination below marked `proposed` is now `accepted`.
- The four commits pushed straight to main (0eeaa2e to 0f622e3) are the founder's, pushed at the founder's request.
- Pending the founder: the sample client name shown in a README screenshot is to be replaced by a fictional name.

---

# Findings register

Compiled from seven reviewers and the available confirmers. No finding was re-reviewed. Every destination below is proposed for orchestrator review.

## 1. Summary

Counts by final severity: P0: 1, P1: 16, P2: 19, P3: 18. Total: 54.

Counts by verdict: confirmed: 27, narrowed: 5, refuted: 0, unchecked: 22.

Counts by proposed destination:

- audit-3a (346): 4
- superseded on main: 2
- founder confirmation: 1
- spec 030, ticket 030-6 (334): 1
- spec 030, ticket 030-7 (335): 3
- spec 031, ticket 031-1 (337): 1
- rename spec 032: 1
- fix round (audit-5, 327): 8
- triage (audit-6, 328): 33

### P0 and P1 findings

| id | title | final severity | verdict | destination |
| --- | --- | --- | --- | --- |
| P1-01 | Brand guard rejects the canonical agent name and the rebuilt bundle | P1 | confirmed | superseded on main |
| P1-02 | Server-driven face signals are not exposed or consumed | P1 | confirmed | spec 030, ticket 030-6 (334) |
| P1-03 | Neither opt-in agent dialog mounts the face | P1 | confirmed | spec 030, ticket 030-7 (335) |
| P1-04 | Click-to-squash test never observes a squash | P1 | confirmed | fix round (audit-5, 327) |
| P1-05 | Autonomous blink and drift test bypasses the wake scheduler | P1 | confirmed | fix round (audit-5, 327) |
| P2-01 | A chosen tracker face still renders the classic face above it | P1 | confirmed | fix round (audit-5, 327) |
| P3-01 | A cannot-run plugin still offers the dead Re-run validator action | P1 | confirmed | fix round (audit-5, 327) |
| P3-02 | The lifecycle busy test passes while install, update and consent still bypass F1 | P1 | confirmed | fix round (audit-5, 327) |
| P3-05 | The non-web installed-plugin test asserts before the capability read can finish | P1 | confirmed | fix round (audit-5, 327) |
| P4-01 | Primary server actions remain inert with JavaScript off | P1 | narrowed | fix round (audit-5, 327) |
| P4-02 | A failed pairing puts the live pairing code in the URL | P1 | confirmed | fix round (audit-5, 327) |
| P4-03 | Workbook tracker selection never supplies the tracker figures to the deck | P1 | confirmed | spec 031, ticket 031-1 (337) |
| P5-01 | The default busy audit retests real machine gates and writes into real OneDrive | P0 | confirmed | audit-3a (346) |
| P5-02 | Pending verdicts accept stale or unrelated page content as proof of feedback | P1 | confirmed | audit-3a (346) |
| P5-03 | Pending audit failures disappear from coverage and can pass with zero controls checked | P1 | confirmed | audit-3a (346) |
| P5-04 | A present Describe control that fails to open its dialog is treated as an allowed skip | P1 | narrowed | audit-3a (346) |
| P7-02 | Replacement naming guard passes while shipped naming still uses the old product name | P1 | unchecked | rename spec 032 |

### P7 status

Five P7 findings are included. P7-01 uses the orchestrator's narrowed P3 disposition and is pending the founder. P7-02 through P7-05 have no confirmer and remain unchecked.

## 2. Fix round

### P1-04, P1

The click-to-squash component test clicks the face but checks only that its mood remains waiting. It never observes the squash transform or the brain call, so deleting the click handler leaves the suite green.

File and line: `frontend/src/test/face.test.ts:422`.

Regression recipe: mutation-backed. Delete only the `onClick` squash handler at `frontend/src/face/AgentFace.tsx:175`; `frontend/src/test/face.test.ts` must fail. Capture the brain through `onBrainReady`, click the rendered face, advance a frame, assert the box transform changes, then advance past the squash and assert the mood is unchanged and the transform settles.

### P1-05, P1

The autonomous blink and drift test advances the brain with direct `brain.step` calls. It bypasses the wake scheduler, so deleting the scheduled frame leaves autonomous browser animation broken while the test stays green.

File and line: `frontend/src/test/face.test.ts:260`.

Regression recipe: mutation-backed. Delete only `scheduleNextFrame()` from the wake timer callback at `frontend/src/face/brain.ts:465`; `frontend/src/test/face.test.ts` must fail. Use `sched.advanceTime` so the wake timer fires, flush frames, and assert drift and blink poses at the 2 through 4 second and 3 through 6 second boundaries.

### P2-01, P1

A live `excel-report` with `payload.face === 'ui-schema'` renders the classic tracker figure and then the chosen schema elements. The regression test checks only the chosen value, so the duplicate classic face remains unnoticed.

File and line: `frontend/src/dashboard/TrackerCard.tsx:76`.

Regression recipe: mutation-backed. Insert an extra `TrackerFigure` at the start of the wizard-face branch at `frontend/src/dashboard/TrackerCard.tsx:92`; `frontend/src/test/tracker-cards.test.tsx` must fail. Assert that a wizard-face card keeps its chosen Value and Edit control but has no `.figure` and no classic `.spark`.

### P3-01, P1

An installed plugin that cannot run still offers Re-run validator. That action re-probes the data source and cannot add the missing transport, while the existing test rejects only the Re-test label.

File and line: `frontend/src/marketplace/PluginDetail.tsx:924`.

Regression recipe: not backed by a mutation. From the reviewer evidence, remove the validator guard exemption for `cannotRun`; `frontend/src/test/marketplace-cannot-run.test.tsx` must fail if either retest label is exposed. Assert that a cannot-run detail exposes only Uninstall and Purge data actions.

### P3-02, P1

The lifecycle busy test holds only Enable and Re-test. Install, update and consent still use an immediate generic busy label with no 100 ms gate or action-specific continuous verb, so the named test passes with those paths broken.

File and line: `frontend/src/test/feedback-marketplace.test.tsx:445`.

Regression recipe: mutation-backed. Remove `disabled`, `aria-busy` and the Working branch from the shared confirm button at `frontend/src/marketplace/ConsentSheet.tsx:110-113`; `frontend/src/test/feedback-marketplace.test.tsx` must fail. Hold install, update and consent requests, assert no visible change before 100 ms, then assert the correct continuous label and `aria-busy=true`.

### P3-05, P1

The non-web installed-plugin test asserts that the cannot-run notice is absent before the asynchronous capability read can finish. The named case can pass before the evaluated result paints.

File and line: `frontend/src/test/marketplace-cannot-run.test.tsx:196`.

Regression recipe: mutation-backed. Replace `cache.set(entry.key, asksForWeb(data.plugin.capabilities))` with `cache.set(entry.key, true)` at `frontend/src/marketplace/Installed.tsx:187`; the named non-web case must fail when run alone. Defer the detail response, wait for its request, release a non-web payload, flush promises and effects, then assert no notice. Add the inverse web-capability case. The confirmer observed that the full file caught this mutation, but the named case alone passed before the badge appeared.

### P4-01, P1

With JavaScript off, ordinary inbox cards cannot be accepted or dismissed and dismissed cards cannot be restored because those controls are script-only buttons; update-consent cards retain one separate no-script Accept form. Sales and calendar Re-test and dashboard skill-run controls are also script-only. The no-script feedback tests cover settings toggles but not these actions. P1 holds because losing the ordinary inbox decision path is a user-visible failure on a main path.

File and line: `src/agentdesk/server/inbox_view.py:61`.

Regression recipe: mutation-backed. Delete the update-consent plain POST Accept form at `src/agentdesk/server/inbox_view.py:93-106`; `tests/test_ui_feedback.py` must fail. Add no-script form-submit tests for update-consent Accept, ordinary inbox Accept and Dismiss, dismissed-card Restore, and the named Re-test and skill-run actions, asserting the store change and notice.

### P4-02, P1

Pairing refusal redirects place the live pairing code in the query string. Code generation does the same, exposing a credential through the address bar, history and query logging. The current test requires URL-based retention and does not test secrecy.

File and line: `src/agentdesk/server/peers_api.py:404`.

Regression recipe: mutation-backed, but the observed failure tested the wrong property. Delete the refusal redirect lines at `src/agentdesk/server/peers_api.py:407-408`; replace the URL-retention assertion at `tests/test_ui_feedback.py:436` with tests requiring the pairing code to remain visible in the form while neither `Location` nor the final URL contains it. The secrecy regression must fail when query exposure is restored, without requiring URL-based retention.

## 3. Re-triage proposals

- P1-02 to spec 030, ticket 030-6 (334). Why: background truth on every page rebuilds the loop projection, active-pass polling and face signal mapping together. Until then: a person on main cannot see background passes, completion, fatal health or decision waits drive the face.
- P1-03 to spec 030, ticket 030-7 (335), with duplicates P2-07 and P3-06. Why: the face in both dialogs rebuilds the shared heading mount, modal activity scope and rail handoff. Until then: a person on main sees only the rail face while either agent-assisted dialog is open.
- P4-03 to spec 031, ticket 031-1 (337). Why: workbook figures reaching the deck belongs in the presentation-template source pipeline. Until then: a selected workbook tracker can produce a deck without its current total, change, goal, pace or row figures.
- P7-01 to founder confirmation. Why: the orchestrator's image inspection found only built-in sample data carrying a SAMPLE DATA label, with the displayed name present in source since 2026-11-17. Until then: this is a finding only if the founder says the name is a real client or employer.
- P7-02 to rename spec 032, sub-tag guard. Why: the spec's twelfth veto point covers restoring the scoped negative naming walk and shipped metadata assertions. Until then: the replacement guard can pass while the old product name remains on shipped surfaces.

## 4. Superseded on main

- P1-01: the founder replaced the brand guard in four direct commits on main and rewrote the README with the new product name. What the guard should pin is a decision for the rename spec.
- P6-01: duplicate of P1-01, also superseded by the replacement guard on main. The old spec claim is no longer the implementation target; what the guard should pin is a decision for the rename spec.

## 5. Triage

| id | title | final severity | verdict | sub-tag |
| --- | --- | --- | --- | --- |
| P1-06 | Face token and bundle contracts are absent | P2 | unchecked | none |
| P1-07 | Reduced-motion preference is sampled only at mount | P2 | unchecked | none |
| P2-02 | The slow-wait line promises a result that is not persisted | P2 | unchecked | none |
| P2-03 | The removal dialog loses its focus trap while removal is pending | P2 | unchecked | none |
| P2-04 | The removal-check skeleton is an unmanaged modal | P2 | unchecked | none |
| P2-05 | Memory refetch dimming animates opacity outside the motion rule | P3 | unchecked | none |
| P2-06 | A drag reorder shows the Move up pending verb on the dragged card | P3 | unchecked | none |
| P3-03 | The installed cannot-run cache is keyed by pinned version but reads the current catalog release | P2 | unchecked | none |
| P3-04 | A failed capability read is cached as proof that the plugin does not need the web | P2 | unchecked | none |
| P3-07 | The marketplace rail hardcodes the inbox waiting count to zero | P2 | unchecked | none |
| P3-08 | Dialog waits violate the 10 second F4 release contract | P2 | unchecked | none |
| P3-09 | Remaining marketplace async controls bypass the shared 100 ms busy contract | P2 | unchecked | none |
| P4-04 | Reset to automatic discovery cannot work while the empty calendar pin is active | P2 | unchecked | none |
| P4-05 | Invalid presentation form selections return raw JSON | P2 | unchecked | none |
| P4-06 | New server motion exceeds the colour-and-background-only rule | P3 | unchecked | none |
| P5-05 | Mixed valid and invalid condition filters silently drop the invalid condition | P2 | unchecked | none |
| P6-02 | The evidence gives instant a meaning the cited instrument did not implement | P3 | confirmed | closeout |
| P6-03 | README's current audit command and coverage claims do not match the tool | P3 | confirmed | closeout |
| P6-04 | The text-fit evidence says every state is stress-tested, but the plan is banded | P3 | confirmed | closeout |
| P6-05 | The second 7/7 gate result is not tied to a tree, and the final PR records 6/7 | P3 | narrowed | closeout |
| P6-06 | Spec 027 is marked done while its four-second model-wait acceptance item is explicitly incomplete | P3 | confirmed | closeout |
| P6-07 | The evidence pack does not contain the gate and readiness commands it is said to record | P3 | confirmed | closeout |
| P6-08 | Spec 029 has no filed issue or delivery record despite code being merged | P3 | narrowed | closeout |
| P6-09 | The shipped face has no written design-language exception | P3 | confirmed | closeout |
| P6-10 | F2's one-second placeholder boundary is not the behavior implemented or tested | P3 | confirmed | closeout |
| P6-11 | R6 says scrolling table cells stay nowrap, but the server cells deliberately wrap | P3 | confirmed | closeout |
| P6-12 | N1's every-compared-number grouping claim excludes real server-rendered values | P3 | confirmed | closeout |
| P6-13 | The claim that every redirect carries a status line is false | P3 | confirmed | closeout |
| P6-14 | The long-values fixture does not cover every numeric site and is not zero-finding | P3 | confirmed | closeout |
| P6-15 | Spec 027 still promises Remove as the only cannot-run action | P3 | confirmed | closeout |
| P7-03, P7-04, P7-05 | Three sentence-level corrections to README.md and docs/readme/README.md; one small documentation pull request | P2 | unchecked | closeout |

## 6. Duplicates

- Brand guard: P1-01 carries the work. P6-01 is a duplicate of P1-01. Both are superseded on main.
- Modal face: P1-03 carries the work. P2-07 and P3-06 are duplicates of P1-03. All three go to spec 030, ticket 030-7 (335).

## 7. Added after the re-triage (2026-11-26)

- PR349-R4, P3, confirmed by a second reading: four sibling demo and smoke tools (`tools/demo_readiness.py:210`, `tools/demo_walkthrough.py:174`, `tools/engine_sidecar_check.py:112`, `tools/smoke_first_plugin.py:51`) boot a desk without the inert runners. The server has one probing path, a capability retest, and none of the four sends one, so nothing has run from them; the protection is only that nothing pulls the trigger. Found by the independent review of pull request 349 (`review/PR349-review.md`, remark R4). Destination: audit-3b (350), filed by the orchestrator, blocked by 346 and 347. It merges before the BEFORE walk or after the last AFTER walk, never between them.

The counts in section 1 (54 findings) are as the founder accepted them on 2026-11-25. With this finding the register holds 55 (P3: 19).
