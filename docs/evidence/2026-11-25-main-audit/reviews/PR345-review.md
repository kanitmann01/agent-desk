CLEAN

## Remarks

None.

## Scope and identity

- Pull request: `kanitmann01/agent-desk#345`, branch `fix/pre-audit-small-fixes`.
- Reviewed head: `b458316e7b27539aeca8178d94ff8bbf30cb4140`. The read-only pull request worktree reported `b458316` and a clean status.
- Base: `origin/main` at `0f622e3fc88b6611265ce8cca6771414a76171ab`, which is also the merge base.
- `git diff --stat origin/main...HEAD` reports 32 changed paths: 25 added documents, the marketplace component and its test, the clock test, two face test files, one renamed JavaScript bundle asset, and `index.html`. No extra path was found.
- Merge commit `c40a93c` has parents `e862d39` and `0f622e3`. Its combined diff names only `tests/test_brand_naming.py`.
- `tests/test_brand_naming.py` has the same Git blob hash in the pull request and `origin/main`: `6f40b4e5cee91af200ea0b2dc82ece04da8396e2`.

## Mutation record 1: clock boundary

Baseline command, run in the detached temporary worktree:

```text
cd "D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr345"
python -m pytest -q tests/test_plugin_update_modes.py
.........                                                                [100%]
9 passed in 0.21s
```

The test file contains no call to `datetime.now`, `date.today`, `time.time`, `utcnow`, or another wall-clock read. The scheduled case injects a fixed `ReadingStore` clock and covers stored readings at 00:00, 07:59, and exactly 08:00. The 08:00 case expects the following day, matching the issue comment's correction to strictly after.

Mutation: in `src/agentdesk/plugins/refresh.py:110`, changed

```python
cursor = since.replace(second=0, microsecond=0) + timedelta(minutes=1)
```

to

```python
cursor = since.replace(second=0, microsecond=0)
```

This makes a reading stored at exactly 08:00 count as due at that same 08:00.

Mutation command and result:

```text
python -m pytest -q tests/test_plugin_update_modes.py
....F....                                                                [100%]
E       AssertionError: assert ['sales'] == []
tests\test_plugin_update_modes.py:144: AssertionError
FAILED tests/test_plugin_update_modes.py::test_a_scheduled_tile_refreshes_when_its_clock_comes_due[stored2-not_due2-expected_due2]
1 failed, 8 passed in 0.27s
```

The change was discarded with `git restore --source=HEAD -- src/agentdesk/plugins/refresh.py`. `git diff --exit-code b458316 -- src/agentdesk/plugins/refresh.py` produced no output.

## Mutation record 2: fill control

Baseline command:

```text
cd "D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr345/frontend"
npx vitest run src/test/describe-plugin.test.tsx
Test Files  1 passed (1)
Tests       6 passed (6)
```

Mutation: in `frontend/src/marketplace/DescribePlugin.tsx:153-154`, removed `disabled={empty}` so the control could be pressed while the description was empty.

Mutation command and result:

```text
npx vitest run src/test/describe-plugin.test.tsx
FAIL  src/test/describe-plugin.test.tsx > describing a plugin (spec 024) > disables the fill for an empty description and starts no request when pressed
Error: expect(element).toBeDisabled()
Received element is not disabled
src/test/describe-plugin.test.tsx:98:18
Test Files  1 failed (1)
Tests       1 failed | 5 passed (6)
```

The run failed at the disabled-state assertion before reaching that test's press. The post-press zero-request assertion is present at test lines 100 to 103. The typed test still passed, including its post-press assertion of exactly one `/wizard/start` request.

The change was discarded with `git restore --source=HEAD -- frontend/src/marketplace/DescribePlugin.tsx`. `git diff --exit-code b458316 -- frontend/src/marketplace/DescribePlugin.tsx src/agentdesk/plugins/refresh.py` produced no output.

## Fill control review

- `frontend/src/marketplace/DescribePlugin.tsx:61` computes emptiness with `description.trim() === ''`. Empty and whitespace-only descriptions are disabled.
- Typing non-whitespace text enables the native button. The visible name remains `Fill it in for me` in both states.
- `Button` forwards `disabled` to a native `<button>` at `frontend/src/components/Button.tsx:62`, so assistive technology receives the native disabled state.
- `onFill` trims again and independently returns without a request for empty text at lines 94 to 100. With text it calls `postJson('/wizard/start', ...)` once and immediately changes phase to `asking`, removing the writing-phase button.
- The tests at `frontend/src/test/describe-plugin.test.tsx:91-122` press empty and typed states and place the request-count assertions after each press.
- This matches commit `7277bce`: trimmed emptiness, native `disabled`, a retained handler guard, and tests that preserve the accessible name.

## Bundle check

Commands were run only in the detached temporary worktree:

```text
cd "D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr345/frontend"
npm ci
npm run build
git -C "D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr345" status --porcelain
```

`npm ci` added 168 packages and audited 169. It printed 3 dependency vulnerabilities, 1 moderate and 2 critical. The pull request does not change the lockfile, and no dependency audit or remediation was run.

`npm run build` reported 108 modules transformed, emitted `assets/index-DIKt6BjX.js` at 249.41 kB, and completed in 831 ms.

The first literal `git status --porcelain` after the build was not empty:

```text
 M src/agentdesk/server/static/spa/assets/index-D8rifP0q.css
 M src/agentdesk/server/static/spa/assets/index-DIKt6BjX.js
 M src/agentdesk/server/static/spa/assets/memory-graph-BGjeuZe0.js
 M src/agentdesk/server/static/spa/assets/memory-graph.css
 M src/agentdesk/server/static/spa/assets/memory-graph.js
 M src/agentdesk/server/static/spa/assets/memory-loop.css
 M src/agentdesk/server/static/spa/assets/memory-loop.js
 M src/agentdesk/server/static/spa/assets/useBusy-BnHbzNUF.js
```

This was a Windows Git stat-cache and line-ending false positive, not a content difference. For all eight files, the fresh working bytes equaled the committed blob bytes, the raw Git hash equaled the `HEAD` blob hash, and `git diff` was already empty. After refreshing only those identical index entries and repeating the build, the LF-preserving check and then the literal check produced:

```text
git -c core.autocrlf=false status --porcelain
<empty>

git status --porcelain
<empty>

git diff --exit-code
<empty>

git diff --cached --exit-code
<empty>
```

The committed bundle therefore matches a fresh build byte for byte.

`frontend/src/test/face-rail.test.tsx` and `frontend/src/test/face.test.ts` only replace repeated agent-name literals with the imported `AGENT_NAME`. They do not pin bundle filenames, contrary to the brief's wording. At the bundle file level, the pull request only renames the content-hashed JavaScript asset and updates its `index.html` reference.

## Document comparison and public hygiene

The pull request adds 25 documents: 23 ticket files and 2 specs. Every added file was compared by SHA-256 with its source under `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/final/`. All 25 matched. There were 0 mismatches.

Hygiene scan over those 25 files:

| Check | Occurrences | Lines |
| --- | ---: | ---: |
| Em dash | 0 | 0 |
| En dash outside a numeric range | 0 | 0 |
| At-sign followed by a username | 0 | 0 |
| Any of the three desk theme names | 0 | 0 |
| Employer or client name, manual review | 0 | 0 |
| Secret patterns in the pull request diff | 0 | 0 |

The three theme names were read from `frontend/src/theme/theme.ts` without copying them into this report. A manual review of capitalized terms found only product, technology, font, and generic terms.

Limitation: the employer and client check is manual, not gate-proven. `tools/ci_local.py:233-240` runs `tools/brand_leak.py`, which scans only presentation pack roots under `registry` and compares lower-cased token hashes or file-byte hashes. The committed hash list is empty and `tools/brand_leak.local.txt` is absent. The gate does not scan `specs/` or `docs/tickets/` and supplies no plaintext employer or client denylist.

The scratch `final/tickets/` tree contains one additional ticket file beyond the 23 specified by the brief. It is not referenced by the added documents and was not added. The pull request matches the specified 23 ticket files.

## Issue 323 criteria as amended

| Criterion | Status | Evidence |
| --- | --- | --- |
| 1. Founder checkout moved to `main` at or after `37515e9`, only by `git pull --ff-only origin main`, with no checkout process and unchanged tracked and untracked state | Met, recorded evidence only | Before head `f31582a`, after head `37515e9`. The latter is a two-parent merge commit. Before and after status files are identical and list the same 10 untracked paths. The three recorded process lists have 0 exact checkout-path hits and 0 repository-identifier hits. The exact pull command and its timing cannot be independently repeated. |
| 2. Clock test reads no wall clock and uses fixed 00:00, 07:59, and 08:00 cases with the corrected strictly-after rule | Met | Test lines 117 to 149 inject a fixed clock. Wall-clock search found no calls. The independent inclusive-boundary mutation failed the 08:00 case. |
| 3. Clock test file passes and evidence records local run time | Met | `rework/clock-after-boundary-correction.txt` records `9 passed`. The pull request body records local time `2026-11-25 21:24:17 -0500`. The raw transcript itself has no timestamp. |
| 4. If the fixed test exposes a product bug, make no product change and report it with severity | Met | The issue comment corrected the expectation. No backend product bug remained. `git diff origin/main...HEAD -- src/agentdesk ':(exclude)src/agentdesk/server/static/spa'` is empty. |
| 5. Fill is disabled while empty, enables with text, and starts exactly one request with text | Met | Component lines 61 and 94 to 100, native disabled at lines 153 to 154, and the two request-count tests. The independent guard-removal mutation failed. |
| 6. Empty press and typed press tests assert after each press and fail under an inverted guard | Met | Test lines 91 to 122. `fill-guard-inverted-red.txt` records 2 failures, one per press test. The reviewer's separate guard-removal mutation also failed the file. |
| 7. Frontend type check and full frontend tests pass | Met, recorded evidence | `rework/frontend-check.txt` exits 0 after `tsc --noEmit`. `rework/frontend-tests.txt` records 43 files and 646 tests passed. The reviewer ran only the permitted single frontend test file. |
| 8 to 10. Brand guard narrowing, planted-copy failure, and product naming criteria | Withdrawn | The issue comment withdraws all three. Main's `tests/test_brand_naming.py` is byte-identical in the pull request. Earlier recorded brand runs were read but are not acceptance criteria. |
| 11. Local gate prints `7/7 gates passed` and `CI PASS` on the head | Met, recorded evidence | `rework/ci-local.txt` records 3561 passed, 1 skipped, all 7 gates passed, and `CI PASS`. The reviewer did not run the local gate, as the brief forbids it. |
| 12. Merger agent merges only after independent review and founder confirmation | Not verifiable | The pull request is open and unmerged. The future merge and founder confirmation are outside this review. |

No active criterion is not met. Criterion 12 is pending and not verifiable at review time.

## Commit hygiene and checks found correct

- All 7 pull request commit subjects match `type(scope): subject`.
- Commit subjects and bodies contain 0 em dashes and 0 en dashes.
- The diff scan found 0 private-key, cloud-key, GitHub-token, Slack-token, JWT, bearer-token, assigned-secret, or token-in-URL hits. No sensitive value was copied into this report.
- The merge brought in main and resolved only `tests/test_brand_naming.py`.
- The backend product boundary is unchanged. The only product source change is the marketplace guard.
- The two approved specs and 23 approved ticket files are unchanged copies.
- The fresh bundle is byte-identical to the committed bundle.
- No application was started. No command was run in the founder's checkout. No real data folder, keychain, or model key was accessed. No gate, walk, layout audit, force push, history rewrite, merge, issue edit, or worktree prune was run.

## Limits and surprises

- The employer and client hygiene result is a manual finding because the public gate has no usable plaintext denylist for documents.
- The first post-build porcelain output showed eight false modifications under this Windows Git configuration. Byte hashes and diffs proved the bundle was already identical; the final literal porcelain output is empty.
- The brief describes the two face test files as pinning bundle filenames. Their actual change is only to derive expected face titles from `AGENT_NAME`.
- The scratch ticket source has one extra file beyond the specified 23. It is not referenced by the added ticket set and was correctly excluded under the brief's count.

## Temporary worktree cleanup

Created exactly:

```text
D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr345
```

Detached at `b458316`. Removed exactly with:

```text
git -C "D:/20-projects/Personal Agents/.worktrees/027-merge" worktree remove --force "D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr345"
```

The worktree list went from 56 registrations to 55. A sorted comparison showed only the temporary worktree block removed: its path, `HEAD b458316e7b27539aeca8178d94ff8bbf30cb4140`, and `detached`. Every other worktree remains listed, including the founder's checkout and the pull request worktree. The temporary directory no longer exists. `git worktree prune` was never run.
