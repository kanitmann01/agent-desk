CHANGES REQUIRED

Independent review of pull request 349 (`fix/audit-instruments-safe-b`, head `2fc3604`, base `main`), issue 346. Reviewed by reading `D:/20-projects/Personal Agents/.worktrees/audit-3a-instruments-b` (verified at head `2fc3604`, clean) and by running only what the brief permits in my own temporary worktree. I did not write this code. I ran no walk, no layout audit run, no pending pass against a desk, no local gate, no application, and no command in the founder's checkout.

## Remarks

### R1. P1: A planned page with no controls by design fails every pending walk as scheduled

- **File and lines:** `tools/layout_audit.py:3247-3260` (both zero-control branches record verdict `error`), `:4209-4212` (`_pending_fail` returns True for any `error` at every threshold, including `none`), `:4496-4521` (`_pending_coverage_failures` adds every `error` verdict to the exit-3 count), `:1840-1841` (the planned `error-page` view), `:1941-1962` (every condition's plan includes every view).
- **What:** The P5-03 fix makes "a page that should have controls yields none to click" an error that fails the run. The implementation has no way to tell such a page from a page with no controls by design. The `error-page` view (`/auth/not-a-real-token`) is planned in every condition and width, and the server renders it with `render_error_page` (`src/agentdesk/server/pages.py:1798-1811`): a title, a message and a skip link that is an `<a>`. The pending selector (`tools/layout_audit.py:60`: `button,[role="button"],input[type="submit"],input[type="button"]`) matches nothing on it. Every other planned server page uses `page_shell`, whose rail carries a visible collapse button (`src/agentdesk/server/pages.py:1502-1509`), so `error-page` is the only planned page with zero controls by design that I could find.
- **Why:** Ticket 04's pending walk (`docs/tickets/2026-11-25-main-audit/04-walk-passes-and-photographs.md:20-22, 26-28`) runs `--pending-audit --conditions fresh,plugins,full --widths 1280`. Each condition's child enumerates the error page, records `error: page yielded no controls to click`, and the parent then exits 3 (`COVERAGE INCOMPLETE ... pending error ...`), or exits 1 through `_pending_fail` under `--allow-partial` at any threshold above `none`. The walk schedule fails before it starts. This is the brief's P1 class: a verdict rule that will make a walk fail wrongly.
- **Evidence:** By reading (I ran no audit). The chain is complete: zero controls (`pages.py:1798-1811`, selector at `tools/layout_audit.py:60`), error record (`layout_audit.py:3253-3260`), exit-3 membership (`:4599-4619`), threshold-independent failure (`:4211-4212`). No exemption exists for `expected_error` views anywhere in `_run_pending_audit` or `_pending_coverage_failures`.
- **Fix:** Exempt views with `expected_error: True` (or a new explicit "no controls by design" flag) from the zero-control error: still record the page (so `_pending_coverage_failures` counts it as seen), but with verdict `skipped` and a reason naming the by-design absence. Keep the error for every other zero-control page. Add the negative test the criterion asks for: a planned page with no controls by design must not fail the run; a real page whose controls vanished must.

### R2. P2: The new-indicator rule's "appeared after the click" half ships without a pinning test

- **File and lines:** `tools/layout_audit.py:3146-3147` (the verdict keeps only indicators with both `inScope` and `appearedAfterClick`), `:199` and `:3039` (`window.__layoutPendingBefore` is captured in the page before activation, so the flag is computed in-browser).
- **What:** Every new unit test supplies indicators where either `inScope` is False (`test_pending_unrelated_busy_region_cannot_earn_meets`) or both flags are True (`test_pending_new_scoped_indicator_earns_meets`). No test feeds `inScope: True, appearedAfterClick: False`, so deleting the `appearedAfterClick` conjunct from the verdict, or breaking the pre-click snapshot that feeds it, still passes the suite.
- **Why:** Issue 346 requires a test that proves content present before the click cannot earn `meets`. The stale-wait-text and pre-existing-aria cases are pinned; a stale in-scope busy indicator is not.
- **Evidence:** Read of `tests/test_layout_audit.py:265-338`; no fixture combines the two flags.
- **Fix:** Add a case with an in-scope indicator that existed before the click and assert `silent`.

### R3. P3: The implementer's recorded GET finding is confirmed, with no effect on the planned walks

- **File and lines:** `tools/layout_audit.py:3305` (guard installed), `:3307-3315` (per-control `hold`, GET path `route.continue_()` at `:3310`, registered later at `:3363` so it runs first), versus `:2315-2326` (guard GET path `route.fallback()`), `:2288-2312` (the context API fixture route that `route.continue_()` bypasses), installed at `:3831`.
- **What:** Confirmed by reading. On pending fresh pages the per-control hold answers GETs with `route.continue_()`, which sends the request to the network and skips every other handler, including the context-level API fixture route. Matrix rows and enumeration pages reach fixtures because the guard uses `route.fallback()`. So with `--api-fixture` (or the `long-values` condition) combined with `--pending-audit`, fresh-page controls see the desk's live responses where the matrix saw fixture responses.
- **Effect on the evidence:** One line: the two passes would measure different page data, so fixture-fulfilled GET evidence is not comparable between matrix and pending rows in that combination. The planned audit-4 pending commands pass no `--api-fixture`, so no scheduled walk fires it; it is a latent trap for later combinations, disclosed by the implementer and left unfixed, which is acceptable for this ticket.

### R4. P3: Sibling tools still boot desks without inert runners (pre-existing, out of scope)

- **File and lines:** `tools/demo_readiness.py:210`, `tools/demo_walkthrough.py:174`, `tools/engine_sidecar_check.py:112`, `tools/smoke_first_plugin.py:51`, each calling `create_server` with no `gate_runners`.
- **What:** These four predate this PR (on main since commits `0af73fa`, `18f081c`, `3b4290c`), are not the audit's walk instruments, and issue 346 names only the matrix, the pending pass and the feedback walkthrough. The P0 hole is closed for the instruments; these remain as they were. Worth its own small ticket so the same escape does not resurface from a demo tool.

## The eleven checks

### 1. Every boot path, traced by me

`_boot_desk` (`tools/layout_audit.py:2139`) is the only desk factory in the walk instruments. It calls `server_app.create_server(..., gate_runners=_inert_gate_runners())` unconditionally at `:2160-2163`, takes no parameter a caller could use to override it, and `_inert_gate_runners` (`:2120-2136`) returns one closure per `GATES` key, each returning a `GateResult` with status `UNKNOWN`, evidence "injected audit runner: no probe ran", and no adapter, subprocess, network, or path effect.

Callers, all of them:

- Layout matrix and pending pass: `_condition_worker` at `:3797`. One desk serves both; the matrix drives `_measure_combo` (`:3870`) and the pending pass drives `_run_pending_audit` (`:3888`) on the same booted desk. There is no second boot for the pending pass and no other `_boot_desk` call in the file.
- Feedback walkthrough: `tools/feedback_walkthrough.py:702` calls `audit._boot_desk("full", tmp_root)`, so it inherits the same injection.
- The selftest (`:1438`) never boots a desk: it starts only `_selftest_server` (`:1393-1427`, a stdlib `ThreadingHTTPServer` on loopback serving two static in-memory fixture pages) and headless Chromium (`:1444`).
- `main` dispatches `--selftest` straight to `_selftest` at `:4688-4689` before any run logic.

No code path posts a capability retest any more: the only `retest` strings left in the instruments are `/api/plugins/audit-overflow/retest` (`tools/layout_audit.py:2419`), the instrument's own fixture widget endpoint inside the isolated desk. The old `POST /capabilities/<key>/retest` loop is gone. The instrument's other POSTs (`_seed`, `_seed_busy`, the walkthrough's deliberate submits) target the isolated desk, whose gate runners are inert even if a capability endpoint were hit: two independent layers. The module imports no `agentdesk` at top level; every agentdesk import is inside a function, so merely importing the instrument probes nothing.

Verdict on check 1: no path remains by which an instrument can run a production adapter. Cited line by line above.

### 2. The busy seeding

`_seed_busy` (`tools/layout_audit.py:2473`) fills the capability cards at `:2562-2573` by calling `server.capabilities_cache.save_result(result)` for the six `_busy_gate_results()` fixtures (`:2453-2470`). The interface is in-process: `capabilities_cache` is the server's own `CapabilitiesCache` (`src/agentdesk/server/app.py:861`), whose `save_result` writes the `gate_cache` SQLite table inside the desk's isolated data folder (`src/agentdesk/capabilities.py:98-110`). No endpoint is called and no adapter is touched: `_busy_gate_results` constructs `GateResult` dataclass values directly with fixed PASS/FAIL statuses and synthetic evidence text. The page link is by reading: `GET /capabilities` reads the same `server.capabilities_cache` (`app.py:5264`), so the seeded cards are what the page renders. On the proof that pages still show busy states: `test_busy_seeding_never_sends_a_capability_request` proves the six fixtures reach the cache and no capability request is sent, and the busy worker path is driven end to end by `test_every_walk_entry_point_injects_inert_gate_runners` (entry `busy`). No automated test renders a busy capability page; that link rests on the read above, and the audit-4 walk photographs will show it.

### 3. No test can start a real desk, and the runs

The harness replaces the factory: `_WalkRecorder.create_server` (`tests/test_layout_audit.py`) records the kwargs and returns a server that cannot listen; `_install_fake_desk` installs fake `agentdesk`, `agentdesk.server.app`, `agentdesk.keys.secrets`, `agentdesk.probe.core` and `agentdesk.capabilities` modules into `sys.modules`, and stubs `_pin_environment` and `_start_mock`; browsers and pages are fakes. `tests/test_feedback_walkthrough.py` contains only pure verdict and shape tests, no boot at all. No test reaches the real boot with real modules: the recorder stands between every boot and the factory, and `walk.audit is audit` plus the fake modules keep imports inert.

My run in the pull request worktree (head `2fc3604`, clean before and after):

```
python -m pytest -q tests/test_layout_audit.py tests/test_feedback_walkthrough.py
78 passed in 0.38s
python -m pytest -q tests/test_layout_audit.py
52 passed in 0.27s
```

This matches the implementer's recorded `instrument-tests-green.txt` (78 passed in 0.38s).

### 4. The mutation, repeated by me

In my temporary worktree (`D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr349`, detached at `2fc3604`) I removed `gate_runners=_inert_gate_runners()` from the `_boot_desk` call once and ran the file:

```
FAILED tests/test_layout_audit.py::test_every_walk_entry_point_injects_inert_gate_runners
AssertionError: matrix boot omitted gate_runners
1 failed, 51 passed in 0.47s
```

I then discarded the change with `git checkout -- tools/layout_audit.py`; `git status --porcelain` is empty and `git diff 2fc3604` is empty, so the worktree is identical to the pull request head again. This matches the implementer's `mutation-red.txt` (same failing test, `1 failed, 1 passed` there because it ran the two-test subset) and `p5-01-red.txt` (the busy-seeding test also fails when the seeding mutation is applied separately).

### 5. The selftest, read first, then run

Reading: `--selftest` dispatches to `_selftest` (`tools/layout_audit.py:4688-4689`). `_selftest` starts `_selftest_server`, a stdlib `ThreadingHTTPServer` bound to `127.0.0.1` port 0 (`:1424`) whose handler serves two static fixture pages from an in-memory dict and counts POSTs (`:1393-1427`), launches headless Chromium (`:1444`), drives only `base + "/"`, `base + "/offscreen"` and `base + "/form"` against its own fixture server, and shuts the browser and server down in `finally` (`:1691-1701`). Nothing in the path imports `agentdesk`, calls `create_server`, creates a temp folder, or writes a file: the screenshot helpers are called only from `_measure_combo` and the pending pass, not from `_selftest`. All network traffic is loopback to the fixture server itself. So it starts only the instrument's own fixture server and a browser and touches nothing outside itself. I ran it once, from the root of my temporary worktree:

```
uv run --no-project --with playwright --with keyring --with cryptography python tools/layout_audit.py --selftest
SELFTEST PASS 16 detector expectations, 4 box expectations, 10 pending expectations
```

Counts are unchanged from the pre-PR instrument, and the PR does not touch the selftest.

### 6. The guard for non-GET requests

`_install_request_guard` (`tools/layout_audit.py:2334-2342`) routes `**/*` through `_hold_route` (`:2315-2331`). Placement, verified against the first navigation on each entry point:

- Matrix: guard at `:3844`, first `goto` (auth) at `:3849`. The guard's `started` list is handed to `_measure_combo` as held-request evidence and cleared per combo at `:3860`, so one combo's held wizard submit cannot verify the next combo's broken Describe trigger (commit `3cbd19e`).
- Pending enumeration page: guard at `:3227`, `goto` at `:3229`, overlay opener after the guard at `:3237`.
- Pending fresh page: guard at `:3305`, `goto` at `:3339`, per-control hold at `:3363`, activation after both.
- Feedback walkthrough: context-level guard with `answered=True` at `tools/feedback_walkthrough.py:712-713`, before `new_page` at `:714` and the auth `goto` at `:717`.

What happens to a held POST, exactly: in the audit walks (`answered=False`, the default) the request's method and URL are recorded into `started`, the route object is parked in `held`, and nothing is called on the route, so the request stays pending and never reaches the desk; at cleanup `_abort_held` (`:2345-2351`) calls `route.abort()`, so the page sees a failed request. In the walkthrough (`answered=True`) the POST is recorded and then `route.fallback()` lets it proceed to the next handler and the network, so the isolated desk answers the walkthrough's own deliberate submits. GETs fall through the guard with `route.fallback()`; on pending fresh pages the per-control hold answers GETs with `route.continue_()` instead, which is R3. Tests proving placement: `test_pending_pages_install_the_guard_before_their_navigation`, `test_pending_fresh_page_guard_precedes_its_navigation`, `test_feedback_walkthrough_guards_its_context_before_navigation`, and the entry-point test's `page-route` before `page-goto` assertion.

### 7. The three verdict changes

- **P5-02** (`_pending_verdict`, `tools/layout_audit.py:3119-3195`): `meets` now requires one of: a new `aria-busy` (`ariaBusyChanged`, `:3149-3152`), a wait placeholder that is visible and whose target signature changed after the click (`waitChanged`, computed in `PENDING_STATE_JS` against the pre-click capture from `_pending_wait_target`, `:3208-3219`, taken at `:3360` before activation), a changed label, or a busy indicator that is both in scope (control, its form, declared target) and new (`:3146-3147`). Behaviour whose removal fails a test: revert `wait_changed` to `wait_visible` and `test_pending_stale_wait_text_cannot_earn_meets` fails; drop the `inScope` filter and `test_pending_unrelated_busy_region_cannot_earn_meets` fails; drop `ariaBusyChanged` and `test_pending_pre_existing_aria_busy_cannot_earn_meets` fails. The `appearedAfterClick` conjunct is the unpinned half: R2.
- **P5-03**: pages that yield no controls or fail before enumeration record an explicit `error` verdict with a reason (`:3247-3265`); `_pending_fail` fails on any `error` at every threshold (`:4211-4212`); a requested pass writes `pending.json` even when empty (`:4585`) and `_pending_coverage_failures` (`:4496-4521`) names every planned page with no record and every error; the total joins the exit-3 decision (`:4599-4619`); the summary says "Pending audit was requested but produced no control records." instead of "not requested" (`:4355-4357`). Behaviour whose removal fails a test: drop the error branch and `test_pending_page_with_no_controls_records_an_error` fails; drop the coverage join and `test_pending_page_error_is_incomplete_even_with_a_full_matrix` and `test_requested_pending_pass_with_no_files_is_incomplete` fail; drop the `_pending_fail` error branch and the new `test_pending_fail_thresholds` assertion fails.
  The over-strictness the brief asked about is real and is R1: the rule is "every planned pending page must present at least one visible control", with no by-design exemption, and the planned `error-page` page violates it, so as scheduled the pending walk fails on every run. Not safe for the walk schedule until R1 is fixed. The error verdict failing at any threshold is intentional and correct for genuine failures.
- **P5-04** (`_open_overlay`, `tools/layout_audit.py:3543-3646`): every opener now returns `(reason, failed)`. An absent trigger stays `(reason, False)`, an intentional skip. A present trigger whose dialog times out returns `(reason, True)`; the Describe opener additionally checks the held-request evidence and only stays a verified skip when a held `/wizard/...` request shows the documented plain-wizard fallback ran, naming the request in the reason (`:3633-3642`). `_measure_combo` maps `failed` to matrix status `error` (`:3712-3713`), which is failed coverage (`:4577-4578` counts anything outside `measured`/`skipped`), and the pending enumeration and fresh-page paths record `error` the same way (`:3241-3243`, `:3349`). Behaviour whose removal fails a test: make a present-trigger timeout a skip again and `test_present_overlay_trigger_without_dialog_is_an_error` and `test_matrix_maps_a_failed_opener_to_an_error_row` fail; drop the held-wizard verification and `test_describe_timeout_with_a_held_wizard_submit_is_a_verified_skip` fails; `test_matrix_maps_a_legitimate_opener_reason_to_a_skip_row` keeps absent triggers skips.

### 8. What the walks will see

- The `busy` condition is safe to use again: inert runners on the boot, six synthetic cache fixtures for the cards, no probe, no OneDrive write, no external call.
- `meets` is stricter on every run, but BEFORE and AFTER both use this same fixed instrument, so comparisons stay fair; expect fewer `meets` and more `silent` than the 2026-11-24 numbers.
- New messages and codes: `COVERAGE INCOMPLETE` can now name `pending error <condition> page <n>` and exit 3; `error` is a new pending verdict and a new matrix status; the summary can say "Pending audit was requested but produced no control records."
- A present overlay trigger that opens nothing is now an `error` row (failed coverage), not a skip; only an absent trigger or a held `/wizard/start` remains a skip, and the reason names the request.
- The feedback walkthrough records every page non-GET from before its first navigation and lets the isolated desk answer it; audit walks hold non-GETs and abort them at cleanup.

### 9. The implementer's new finding

Confirmed by reading, as R3: on pending fresh pages the per-control hold's `route.continue_()` for GETs (`tools/layout_audit.py:3310`) bypasses the context API fixture route (`:2296-2312`) that matrix GETs reach through the guard's `route.fallback()` (`:2325`). Effect in one line: with `--api-fixture` plus `--pending-audit`, fixture-fulfilled GET evidence differs between matrix rows and pending fresh-page rows. Not fired by the planned audit-4 pending commands (they pass no `--api-fixture`), so it does not affect the scheduled walks; leaving it unfixed and recorded is acceptable here.

### 10. Documents and hygiene

- Ticket hash: `sha256sum` of `docs/tickets/2026-11-25-main-audit/03a-safe-instruments-before-the-first-walk.md` in the worktree and of `.scratch/wave-2026-11-25/final/tickets/2026-11-25-main-audit/03a-safe-instruments-before-the-first-walk.md` are identical (`3e233d6911d5abe5...52d7c`).
- README paragraph (`README.md:119`): accurate. The condition list matches `ALL_CONDITIONS` (`tools/layout_audit.py:317-318`) exactly, and the busy claims match the code (synthetic cache fixtures, injected UNKNOWN runners, no retest, no external endpoint, no package install, no process listing, no OneDrive write).
- Evidence files: `git diff --name-status <merge-base 2b6de32>..2fc3604 -- docs/evidence` is empty; the PR changes exactly five files (README, the ticket, the test file, the two instruments).
- Dashes: a scan over every commit message in `f31582a..2fc3604` finds zero em dashes and zero en dashes; the PR title and body contain none. Subjects follow the repository's conventional style (`fix(tools):`, `docs(tickets):`, one plain `fix:` title).
- Merge commit `873356f` has parents `1ae8be5` (branch) and `2b6de32` (main); `git diff 873356f^1 873356f --name-only` shows it only brought main's new ticket documents in, no instrument files were touched by the merge, and no conflict markers exist in the head files. Nothing unexpected was resolved.
- Secrets: the diff contains no key, token or password. The only secret-shaped strings are fake test stand-ins ("test-token" in the recorder, "sk-local" only in unchanged seed code).

### 11. The issue, criterion by criterion

1. No entry point can run a production adapter; stand-in test on every boot path; mutation recorded. **Met.** My trace (check 1), my test run (check 3), my mutation (check 4), implementer's `p5-01-red`/`mutation-red`.
2. Busy still produces busy pages through fixtures, not real capability requests. **Met**, with the page-render link by reading (check 2); the walk photographs will close it.
3. Every non-GET held or answered from before the first navigation, in every walk; test for the earliest request. **Met** (check 6). The selftest's fixture pages navigate without a guard, but the selftest is not a walk.
4. `meets` only for content that appeared after the click; test proves it. **Met** for the wait-target, scoping and aria halves; the in-scope stale-indicator half ships without a pinning test (R2).
5. The pending pass fails and says why when a page that should have controls yields none. **Partly met.** The failure and reason exist, but the rule cannot tell "should have controls" from "none by design", so it also fails the one planned page with no controls by design (R1). Not met in the sense my brief and the walk schedule require.
6. A present trigger without its dialog is a finding; skip only when the fallback is legitimate; test for Describe. **Met** (check 7, P5-04).
7. No test in this ticket starts a real desk. **Met** (check 3).
8. Test files pass; selftest prints its PASS line; `ci_local` prints `7/7 gates passed` and `CI PASS` on the head. **Met on the first two by my own runs** (checks 3 and 5). The `ci_local` half rests on the implementer's `ci-local-final.txt` only (`7/7 gates passed in 113s`, `CI PASS`); my brief forbids me the local gate, so I could not repeat it.
9. The implementer ran no walk and not the layout audit itself. **Consistent with their records** (`boot-trace.txt` safety statement, selftest explicitly not run by them) but not independently verifiable by me; nothing I found suggests otherwise.
10. Merger merges only after an independent review and the founder's confirmation. **Pending by design**; this review is the independent review half. Not verifiable by me.

## Checked and found correct

- `_inert_gate_runners` builds one closure per real `GATES` key and answers UNKNOWN honestly; the test asserts the key set and the UNKNOWN statuses.
- `_seed_busy`'s other steps (workbook, calendar, connection, agent run, memory facts, mail) all target the isolated desk over loopback and keep their failure-tolerant note reporting; the cache block keeps the same shape.
- `_pending_coverage_failures` reconstructs planned pages per condition and names every page with no record, so an empty child file cannot inherit a clean run.
- The child still writes `pending.<condition>.json` only when records exist, but the merge now writes `pending.json` whenever the pass was requested, and coverage is computed from planned pages, not from file existence.
- The walkthrough's context guard with `answered=True` records each non-GET and lets the isolated desk answer deliberate submits; the test asserts `fallback` for a POST and a GET.
- The per-combo clearing of `guard_started` (`:3860`) prevents held-request evidence leaking between combos; the entry-point test asserts every combo starts empty.
- Overlay openers for all seven openers separate absent triggers from silent present triggers; `unknown overlay opener` is a failed opener.
- `PENDING_STATE_JS` now derives `waitVisible` from a visible pending placeholder inside the declared target, not from any text in it.
- `_pending_page_record` keeps error and skip records inside the same schema as control rows, so counts and the summary read uniformly.
- The selftest's fixture server refuses nothing external (loopback bind only) and its form-submit check still proves held submits never reach a server after abort.
- My temporary worktree was removed with `git worktree remove --force` exactly as the brief prescribes, `git worktree list` from `.worktrees/027-merge` afterwards still lists every other worktree, and no `git worktree prune` was run anywhere.
