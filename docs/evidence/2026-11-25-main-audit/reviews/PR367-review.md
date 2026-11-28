CLEAN WITH REMARKS

## Remark P3: the slow run needs one fixed exception, not a repeatable path language

**File and line:** `tools/layout_audit.py:2346-2387, 3277, 3373-3383, 4034-4035, 4751-4753`

**What:** The only current caller needs same-origin `POST /research`. A repeatable arbitrary-path option, generic path refusal helper, decoded-path normalization, per-value child forwarding, and repeatability tests are more surface than that job needs.

**Why:** A fixed `--continue-research` flag, or an exact `/research` branch enabled only for the slow run, would keep the same origin check and route ordering while making capability retest continuation impossible by construction. It would remove the path list and loop, `_validate_continue_request_paths`, the generic fresh-page path comparison, and the tests for arbitrary repeatability and capability-value rejection.

**Evidence:** README lines 123-130 say the slow run is the option's only current use and names only `/research`. The production request sites are `frontend/src/dashboard/Dashboard.tsx:278` and `src/agentdesk/server/pages.py:1355`; the route is `src/agentdesk/server/routes.py:226`.

**Fix:** Prefer one explicitly named research-only switch if the founder wants the smallest implementation. Keep the same-origin check, latest-route-first registration, default holding tests, and mutation proof. This is a P3 design remark, not a merge blocker, because the implemented generic option is narrowly checked and no defect was found in it.

## Checks

### 1. The default is unchanged: MET

Without the option, `_install_continue_routes` installs nothing (`tools/layout_audit.py:2367-2374`). The matrix page still installs `_install_request_guard` before navigation (`tools/layout_audit.py:3915-3925`), whose handler falls through only for GET and records and holds every other method (`tools/layout_audit.py:2316-2332`). The pending enumeration page installs that guard before `goto` (`tools/layout_audit.py:3292-3295`). Each control's fresh page installs the guard (`tools/layout_audit.py:3364-3372`), and with an empty path tuple it installs the per-control `hold` route (`tools/layout_audit.py:3277, 3435-3436`), which holds every non-GET (`tools/layout_audit.py:3373-3383`). Every parallel condition child receives the option only when values exist (`tools/layout_audit.py:4034-4035`), so the no-option child state is also empty. The focused default test proves a POST is held while GET falls through (`tests/test_layout_audit.py:712-727`).

### 2. With the option: MET

The comparison is exact membership, `urllib.parse.urlsplit(request.url).path in paths`, plus exact equality of the lowercased `(scheme, netloc)` tuple against the isolated desk base (`tools/layout_audit.py:2346-2364`). It is not a prefix match. Query strings do not affect the path comparison, as intended. `/research/child`, `/research/../wizard`, and a percent-encoded variant do not equal an accepted `/research`; browser canonicalization to `/research` would still reach only the named endpoint. A foreign scheme, host, or port fails the origin tuple. Userinfo or an explicit default port can cause a false negative, not a broader continuation. No crafted path or origin was found that continues a different endpoint or a foreign origin. The generic option does intentionally continue any explicitly named same-origin non-GET path, subject to the capability refusal in check 4.

### 3. Route order on a fresh pending page: MET

Playwright dispatches the most recently registered matching route first and `fallback()` advances to the previous route. The fake harness models that exact reverse order (`tests/test_layout_audit.py:508-530`). On the fresh page the code registers the holding guard first (`tools/layout_audit.py:3371`), then the per-control `hold` route (`tools/layout_audit.py:3401-3402`), then the continuation route (`tools/layout_audit.py:3403`). Dispatch is therefore continuation, then `hold`, then the guard. A named same-origin non-GET continues immediately. A named foreign-origin path falls through `hold` because that route checks only the path, then the guard holds it. A non-matching non-GET falls through continuation and `hold` holds it. GET falls through continuation and `hold` continues it. The test asserts those exact call sequences and the three route registrations before `goto` (`tests/test_layout_audit.py:692-709`). Enumeration and matrix pages register guard then continuation (`tools/layout_audit.py:3292-3293, 3917-3920`).

### 4. The refusal: MET

`_validate_continue_request_paths` percent-decodes each value, extracts its path, normalizes dot segments and repeated separators with `posixpath.normpath`, and refuses both the literal and normalized `/capabilities/` prefix (`tools/layout_audit.py:2377-2387`). `main` calls it immediately after argument parsing and returns 2 with the rejected value and reason (`tools/layout_audit.py:4766-4770`), before the Playwright availability check, selftest or child dispatch, and before run-folder creation (`tools/layout_audit.py:4771-4780`). The parameterized test covers `/capabilities/`, `/capabilities/exec-user-space`, `/capabilities/exec-user-space/retest`, and `/%63apabilities/exec-user-space/%72etest`, and proves no output folder or server-factory call (`tests/test_layout_audit.py:730-754`). The server's capability retest route requires the literal `/capabilities/` prefix and `/retest` suffix (`src/agentdesk/server/routes.py:264-265`); exact `/capabilities` without the slash has no POST route and cannot reopen it.

### 5. The boot is unchanged: MET

`_boot_desk` still has its single `server_app.create_server` call and unconditionally passes `gate_runners=_inert_gate_runners()` (`tools/layout_audit.py:2140-2164`). `_inert_gate_runners` returns UNKNOWN fixture runners that perform no probe (`tools/layout_audit.py:2121-2137`). The PR diff does not change either function or add a server-factory call. The temporary data directory and file-backed stand-in keychain also remain at `tools/layout_audit.py:2152-2155`.

### 6. No test starts a real desk: MET

The test module imports the instrument, not Playwright (`tests/test_layout_audit.py:1-24`). `_WalkRecorder.create_server` records the call and returns an inert server whose `serve_forever` cannot listen (`tests/test_layout_audit.py:1146-1180`). `_install_fake_desk` installs in-memory `agentdesk`, server, keychain, probe, and capability modules, replaces environment pinning, and replaces `_start_mock` (`tests/test_layout_audit.py:1194-1238`). Worker tests replace Playwright with a fake browser and context (`tests/test_layout_audit.py:1250-1345`). I ran the three instrument unit-test files once in the PR worktree with bytecode and pytest cache writes disabled:

`PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_layout_audit.py tests/test_face_walkthrough.py tests/test_feedback_walkthrough.py -q --no-header`

Last line: `126 passed in 0.69s`.

### 7. Mutation proofs: MET

I created the specified detached worktree at `fd4f5076a70be1a78bd8384f5de8bd93d987c157`. Removing only the matching handler's `route.continue_()` made `test_continue_request_path_continues_a_match_and_holds_every_other_non_get` fail at `tests/test_layout_audit.py:671` with `assert [] == ['continue']`; last line `1 failed in 0.33s`. Swapping the fresh-page `hold` and continuation registrations made the same order-sensitive test fail at `tests/test_layout_audit.py:701` with `['fallback', 'continue']` instead of `['continue']`; last line `1 failed in 0.33s`. Removing the `main` refusal block made all four capability cases fail at `tests/test_layout_audit.py:750` because the rejected value was absent from the Playwright-help output; last line `4 failed in 0.36s`. After each mutation I restored `tools/layout_audit.py` from HEAD, confirmed an empty diff, and confirmed its blob hash `23f7e5d898ba912e207d018b47421717b5c3a40f` equals `HEAD:tools/layout_audit.py`. I then removed exactly the temporary `mutation/pr3d` worktree with the prescribed command. The subsequent worktree-list comparison confirmed it is gone and all 61 other worktree paths are unchanged, including the founder checkout, `.worktrees/027-merge`, and the PR worktree. I did not run `git worktree prune`.

### 8. Does it do what it is for: MET by trace and unit proof

The parser stores every repeated path (`tools/layout_audit.py:4751-4753`), `_child_command` forwards every value to every condition child (`tools/layout_audit.py:4034-4035`), and the child passes it to the matrix guard and both pending-audit page paths (`tools/layout_audit.py:3917-3920, 3964-3966, 3292-3293, 3401-3403`). In `full`, `_condition_worker` starts the mock with `mock_delay_ms` (`tools/layout_audit.py:3863-3865`); `_start_mock` sets `DELAY_MS` (`tools/layout_audit.py:2090-2099`); and `_pin_environment` points the desk at that loopback `/v1` endpoint (`tools/layout_audit.py:2082-2085`). Both Research clients post to `/research` (`frontend/src/dashboard/Dashboard.tsx:278`, `src/agentdesk/server/pages.py:1355`), which maps to `_research_ask` (`src/agentdesk/server/routes.py:226`). That handler runs an assistant research turn (`src/agentdesk/server/app.py:2394-2409, 2604-2648`), whose client posts to `/chat/completions` (`src/agentdesk/llm.py:268-306`). The mock sleeps for the configured delay before the JSON body (`tools/mock_endpoint.py:384-411`). Therefore `--mock-delay-ms 4000 --continue-request-path /research` lets the audited `full` Research request reach the isolated desk and wait four seconds for the mock body. `fresh` and `plugins` also receive the continuation, but neither starts or pins the mock (`tools/layout_audit.py:3863-3865, 2082-2085`), so their Research requests reach their own isolated desks and degrade without a model rather than producing a delayed model answer. I did not boot a desk or run the walk, as required.

### 9. Documents and hygiene: MET

The PR ticket and workspace copy have the same SHA-256, `047c9ad466d5e2000baacaceeca5a5f6a768ea85052013cd2423b32fafc55fbf`. README lines 121-130 accurately document repeatability, exact same-origin non-GET continuation, the unchanged default, decoded capability refusal with exit 2 before side effects, the slow-run command, and that this is the only current use. `git diff --check` is clean. The commit message, PR title, and PR body contain no em dash, and the diff additions contain no em dash. Manual diff review and an added-line scan found no key, token, password, private key, or other secret. Hosted checks currently show six passes and the Nuitka build plus smoke still pending; I did not run the forbidden local gate.

### 10. Issue 366, criterion by criterion

1. **MET.** Repeatable append option, exact `urlsplit(...).path` match, same-origin continuation, guard-first installation, fresh-page fallthrough, latest-route-first order, default hold, all three page paths, and all-child forwarding are present. Evidence: checks 1-3 and `tests/test_layout_audit.py:639-709, 757-765`.
2. **MET.** Decoded and normalized capability paths are refused with exit 2 before any boot or run folder, and inert gate runners remain unconditional. Evidence: checks 4-5 and `tests/test_layout_audit.py:730-754`.
3. **MET by code trace.** The README slow-run command names `/research` and 4000 ms, both request sites and the server route agree, and only `full` among the three conditions starts and pins the delayed mock. Evidence: check 8 and README lines 123-130. No real walk was run by this reviewer.
4. **MET.** The four requested tests are present, use fake routes, recorder, fake desk, and fake browser modules, and the instrument suites pass. Evidence: check 6 and `tests/test_layout_audit.py:639-765, 1146-1238`.
5. **MET.** I independently reproduced the required failing continuation mutation and restored the exact head blob. I also reproduced the order and refusal mutations requested by this review. Evidence: check 7.
6. **MET.** README documents every requested behavior and the exact slow-run command. Evidence: check 9.
7. **NOT VERIFIABLE by this reviewer.** The changed tests pass, but the implementer's historical no-walk claim and the claimed local `tools/ci_local.py` output cannot be independently established without running the prohibited gate. PR 367's body reports `7/7 gates passed` and `CI PASS`; hosted checks are six pass and one pending at review time.
8. **NOT MET yet, procedural only.** PR 367 is open, the Nuitka hosted check is pending, and founder confirmation plus merger action have not occurred. This does not change the code verdict; those steps remain merge prerequisites.

### 11. The smallest complete change (ponytail): APPLIED

I loaded the ponytail instructions and reviewed the full diff at their default level. The P3 remark above is the complete finding: a single research-only switch would satisfy the slow-run job with less code and less risk than a repeatable arbitrary-path option plus a refusal list. The extra generic path list, percent-decoding/normalization refusal helper, arbitrary-path fresh-page branch, repeatability test, and general-path documentation could be deleted. The same-origin guard, default-hold tests, route-order proof, child forwarding, and delayed-mock trace must remain. No defect hidden by this extra surface was found, so the remark does not block merge.

## 2026-11-26 re-check after merging main

Merged main `0f290287b9c291f95fe7bbd1b8906b33db4b4c41` into `fix/audit-3d-slow-run` at `65c2e4e3502e9382df3f9badf3fce4a102ae984d`. The pull request diff against the new main is identical to the reviewed `fd4f507` against `b396694` diff, excluding line numbers and context. Local gate at the pushed head: `7/7 gates passed in 130s`; `CI PASS`. Verdict unchanged: `CLEAN WITH REMARKS`.
