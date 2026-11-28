CLEAN

Remarks: none.

Review basis: PR 369, head `878c2bf5c771544edd77503efb27599e163d7229`, base `0f290287b9c291f95fe7bbd1b8906b33db4b4c41`. Repository paths below are relative to `D:/20-projects/Personal Agents/.worktrees/audit-3b-inert-tools`. I read issue 350 and its comment, the implementer brief, every file in `audit-3b-evidence/`, the complete PR diff, the six instruments, the four changed test files, the excluded harness, the factory and retest handler.

## 1. Every desk boot receives the inert runners

Met. Each tool has exactly one server-factory call, and every constructor or main path that boots a desk reaches it.

- `tools/demo_readiness.py:107` imports `_inert_gate_runners`; `tools/demo_readiness.py:211-214` passes `gate_runners=_inert_gate_runners()`. Both walk boots at `:1279` and `:1287`, and the direct test boot at `tests/test_demo_readiness.py:288-289`, use this constructor.
- `tools/demo_walkthrough.py:40` imports it; `tools/demo_walkthrough.py:176-178` passes it. Desk A at `:352-354` and Desk B at `:782` use this constructor.
- `tools/engine_sidecar_check.py:42` imports it; `tools/engine_sidecar_check.py:114-116` passes it. The only boot caller is `main` at `:277`.
- `tools/smoke_first_plugin.py:23` imports it; `tools/smoke_first_plugin.py:53` passes it in `main`.

A search for `create_server(` in the four tools found only these four calls. There is no uninjected boot path.

## 2. One definition, in the required place

Met. The definition remains at `tools/layout_audit.py:2120-2136`. It builds one closure per entry in `agentdesk.capabilities.GATES`, returning `UNKNOWN` without a probe at `:2125-2136`.

The four imports are `tools/demo_readiness.py:107`, `tools/demo_walkthrough.py:40`, `tools/engine_sidecar_check.py:42`, and `tools/smoke_first_plugin.py:23`. `tools/feedback_walkthrough.py:702` still boots through `audit._boot_desk`, whose factory call at `tools/layout_audit.py:2160-2163` injects the same function.

Searching all six named instruments for `def _inert_gate_runners` found exactly one definition, in `tools/layout_audit.py:2120`. No new module appears in the nine-file diff. The only other definition is the explicitly excluded `tests/server_harness.py:134-148`, used at `:265`; it is unchanged.

## 3. Nothing else changed

Met. The diff touches only the ticket, four tools and four test files. `git diff --name-only` for `tools/layout_audit.py`, `tools/feedback_walkthrough.py`, `src/agentdesk/server/app.py`, `tests/server_harness.py`, `README.md`, `tools/ci_local.py`, and the BEFORE ticket returned no paths.

The factory still defaults to production runners only when `gate_runners is None` at `src/agentdesk/server/app.py:7395-7396`, and still passes the selected map to the server at `:7458`. The retest handler still selects and calls exactly the requested runner at `:5305-5324`. The four production diffs add only the tools import path, the shared import and the factory keyword.

## 4. Readiness remains in its existing runs

Met. `tests/test_demo_readiness.py` remains in the suite. `tools/ci_local.py:119` runs `pytest tests`, and `tools/ci_local.py:263-271` keeps pytest as one of the seven gates. The BEFORE ticket still names `python tools/demo_readiness.py` at `docs/tickets/2026-11-25-main-audit/02-baseline-and-before-walk.md:12`. `README.md:106` still documents the readiness command.

The implementer's `audit-3b-evidence/ci-local-final.txt` records local and remote head `878c2bf5c771544edd77503efb27599e163d7229`, `3727 passed, 3 skipped`, `7/7 gates passed in 128s`, `CI PASS`, and exit 0. I did not rerun the gate because this review must not start a real desk.

## 5. Tests, harness and retest reachability

Met for the issue's clarified rule: no test added by this ticket starts a real desk, and no test I ran starts one. The existing readiness tests do start isolated desks and remain intentionally in the gate.

The harness is real-socket infrastructure: `tests/server_harness.py:1-7`, factory call and listener at `:327-333`. It defaults to inert runners at `:265`; the issue explicitly excludes this copy.

Each added recorder test replaces the complete `agentdesk.server.app` module with a factory that records kwargs and raises before returning, so no listener or thread can start:

- `tests/test_demo_readiness.py:50-56,59-93,96-109`.
- `tests/test_demo_walkthrough_exists.py:55-61,64-87,92-109`.
- `tests/test_engine_sidecar_smoke.py:46-52,55-94,97-113`.
- `tests/test_smoke_first_plugin.py:27-33,36-62,65-80`.

Each asserts one factory call, a non-None map, equality with all six gate keys, and `UNKNOWN` from every runner. The fake gate table matches the real table at `src/agentdesk/capabilities.py:48-55`; the existing capability store tests pin that real table.

Existing real-desk inventory:

- `tests/test_demo_readiness.py:118-138` calls `readiness.main()` at `:123`; the walk boots at `tools/demo_readiness.py:1279,1287`. No capability retest is sent.
- `tests/test_demo_readiness.py:276-303` constructs a real readiness desk at `:288-289`. It toggles sample data and reads the dashboard; no capability retest is sent.
- `tests/test_demo_walkthrough_exists.py:26-36` parses source only and boots no desk.
- `tests/test_engine_sidecar_smoke.py:116-130` runs with an absent sidecar. `tools/engine_sidecar_check.py:195-206` returns before the boot at `:277`.
- The first-plugin smoke had no existing test; its added recorder test stops at the fake factory.

The retest route is `POST /capabilities/<key>/retest` at `src/agentdesk/server/routes.py:264-265`. None of the four tools constructs that route. The readiness tool merely checks for a `/capabilities` link at `tools/demo_readiness.py:600`, and the demo walkthrough only GETs `/capabilities` at `tools/demo_walkthrough.py:58`. Even an unexpected retest reaches only the injected UNKNOWN closures.

I ran the four added recorder tests once in the PR worktree, not the full readiness file, to honor the no-real-desk rule:

```text
$ python -m pytest tests/test_demo_readiness.py::test_desk_boot_passes_every_inert_gate_runner tests/test_demo_walkthrough_exists.py::test_desk_boot_passes_every_inert_gate_runner tests/test_engine_sidecar_smoke.py::test_temp_desk_boot_passes_every_inert_gate_runner tests/test_smoke_first_plugin.py::test_boot_passes_every_inert_gate_runner -q --no-header
....                                                                     [100%]
4 passed in 0.17s
```

Current hosted checks also report pass for all seven listed jobs.

## 6. Independent mutations

All mutations were made only in detached temporary worktree `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr3b`. Each argument was removed alone, its recorder test failed, and the file was restored from HEAD. Blob hashes matched `HEAD:<path>` after every restore.

- Readiness: removal of `gate_runners` from `tools/demo_readiness.py:214` produced `AssertionError: assert None is not None` at `tests/test_demo_readiness.py:106`; last line `1 failed in 0.32s`. Restored blob `4423bdcedf17a432ae66b0abd3babf1ae3d99eb1` equals HEAD.
- Demo walkthrough: removal from `tools/demo_walkthrough.py:178` produced the same assertion at `tests/test_demo_walkthrough_exists.py:105`; last line `1 failed in 0.27s`. Restored blob `5633e375d515ac3a27e960f34483f23644805f2f` equals HEAD.
- Sidecar: removal from `tools/engine_sidecar_check.py:116` produced the same assertion at `tests/test_engine_sidecar_smoke.py:110`; last line `1 failed in 0.24s`. Restored blob `d3e429885633bddfd06e1d4b590e1110a0d1a6f5` equals HEAD.
- First-plugin smoke: removal from `tools/smoke_first_plugin.py:53` produced the same assertion at `tests/test_smoke_first_plugin.py:78`; last line `1 failed in 0.25s`. Restored blob `fa304bbfbf077ada4fb16da9fd80bd3e364c93b0` equals HEAD.

Cleanup: I removed exactly `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr3b` with `git worktree remove --force`. A before/after comparison of `git worktree list --porcelain`, excluding only that path, was identical. The final list has 73 worktrees, does not list the temporary path, and still lists both the PR worktree and the admin worktree. I did not run `git worktree prune`.

## 7. Documents and hygiene

Met. The PR ticket and workspace copy both have SHA-256 `f9f42936be69fdc0cf1cd2351fba9079fc8bd554aa98ede236455a8f6f88763c`.

The README remains accurate: its readiness command is still valid, its layout-audit description at `:119-123` is unchanged, and it does not claim that these four tools lack the new protection.

The PR title, body and sole commit message contain no em dash or en dash. `git diff --check` is clean. Manual diff review and a secret-pattern scan of added lines found no secret candidate, so there is no file or line to report.

## 8. Issue 350, criterion by criterion

1. Met: all four factory calls inject the shared runners, the one definition stays in `tools/layout_audit.py:2120-2136`, all four import it, and the six-instrument search finds no second copy outside the excluded harness. Evidence in checks 1 and 2.
2. Met: four recorder tests cover the four boot paths, assert one call, all six gates and UNKNOWN, and all four independent mutations fail. Evidence in checks 5 and 6.
3. Met: the only production changes are the required imports and keywords; no existing assertion changed. The implementer's gate evidence records the existing suite passing. Evidence in checks 3 and 4 and `audit-3b-evidence/changed-assertions.txt`.
4. Met: the two existing real-desk readiness tests are inventoried in check 5; neither sends a capability retest, so no reachability fix is needed.
5. Met for the observable requirements: no added test starts a real desk, readiness remains in pytest and the BEFORE step, and the recorded gate output is green at the PR head. The claim that the implementer ran no tool by hand is supported by the PR body and evidence but is not independently observable by this reviewer.
6. Met on recorded evidence: the four changed test files' new tests pass in my run, and `audit-3b-evidence/ci-local-final.txt` records `7/7 gates passed` and `CI PASS` on the exact head. I did not rerun the gate under this review's no-real-desk rule.
7. Met: the ticket is present and hash-identical to the workspace copy.
8. Not verifiable by me: merger identity, the independent-review condition and founder confirmation are future merge controls. This review supplies the independent review, but does not merge or confirm for the founder.

No acceptance criterion is found not met.

## 9. Smallest complete change, ponytail

No unneeded production code found. The four import-path additions, four imports and four factory keywords are the minimum needed to satisfy the issue. The feedback walk, layout audit, factory, harness, README, gate and BEFORE ticket correctly remain untouched.

The recorder scaffolding is substantial but each file is a required, independently mutation-sensitive test with a closed fake module boundary. A shared test helper would add cross-test coupling and a new module contrary to the ticket's explicit scope. There is nothing I recommend deleting. This remark does not hide a defect and does not block.

## Re-check after merging main, 2026-11-26

Merged `origin/main` at `3f099e0b6240cb97b72359afdaf0cb1366b3b4ea` into `fix/audit-3b-inert-tools` with one merge commit; new head `98f62d58d2464da5b0e18e4bb75347768435b6cc`. Diff against the new main is the reviewed diff in substance: same nine files, same 353 insertions and 7 deletions, and the patch is identical after index lines and hunk headers are removed. Local gate in a clean temporary worktree at the pushed head: `7/7 gates passed in 129s` and `CI PASS` (exit 0). Verdict unchanged: CLEAN.

## Process breach, 2026-11-27

Found by the GLM 5.4 advisor. PR 369 (head `98f62d58`, built on `3f099e0`) and PR 371 merged 12 seconds apart from the GitHub UI at 04:41 UTC on 2026-11-27, so the merger's main-moved check and branch re-gate did not run for either pull request. Containment: main `0132531` (the combined tree) passed all seven hosted checks, and PR 370's gate log `merge-check/pr370-ci-local.log` gates the combined tree. No merger gate log exists for PR 371 on disk. Going forward: when Ken merges from the GitHub UI, the orchestrator records the post-merge checks as the cover in the PR's review file.
