# Audit of the UI wave on main: review, walks and fixes (specs 026, 027, 029)

## Why this exists

Pull request #319 merged 154 commits into main on 2026-11-25 (213 files, 26194 lines added and 1500 removed). It carried spec 026 (text that fits every screen), spec 027 (one home screen and feedback on every wait) and spec 029 (the agent face). None of that code was reviewed by a reviewer who did not write it. The agent face has never been through a browser walk. The walks that did run stopped at `2d00540`, two merges before the final head, and the BEFORE walk with the final verdict set was never taken.

This issue tracks the audit of that merge, the fix round it produces, and the paperwork the wave left open. It is a quality gate: the next wave's feature work does not start on main until issues #327 and #328 close.

## Rules for every ticket here

1. Nobody reviews their own work. An agent that built the wave is not a reviewer, a walker or a fix reviewer on it.
2. Isolated desk only: a temporary data folder, the loopback mock model and a stand-in keychain. Never the real data folder, the real keychain or a real model key.
3. One worktree per concern under `.worktrees/`. Never run `git worktree prune`.
4. Walks run with the machine otherwise idle: no test run, no build and no second walk at the same time.
5. A finding is fixed only with a regression test that fails without the fix.
6. The local gate is `python tools/ci_local.py` and must print `7/7 gates passed` and `CI PASS`. Hosted CI runs a four-file pytest subset and no typecheck, so green hosted checks are not enough on their own.
7. A merge to main happens through a pull request, after green hosted checks, the local gate 7/7 on the pull request head, a clean review pass, and the founder's confirmation.

## Severity

| Level | Meaning |
| --- | --- |
| P0 | Loses or exposes data, breaks the isolation of the real data folder, or stops a main path from working. |
| P1 | A user-visible wrong behaviour on a main path, a page that fails with the script off, or a test that passes while the behaviour it names is broken. |
| P2 | A wrong behaviour on a rare path, or a departure from the spec that has a workaround. |
| P3 | Polish, wording, naming, documentation. |

P0 and P1 block the next wave's feature work. P2 and P3 are filed as issues.

## Tickets

| Ticket | Issue | Title | Blocked by |
| --- | --- | --- | --- |
| 01 | #323 | Small fixes before the audit, and the local checkout | none |
| 02 | #324 | Baseline numbers and the BEFORE walk | #323 |
| 03 | #325 | Code review by area, with a confirmed findings register | none |
| 04 | #326 | Walk passes on main, every photograph read | #323 |
| 05 | #327 | Fix round for P0 and P1 | #325, #326 |
| 06 | #328 | Triage of P2 and P3, and the closeout of the previous wave | #327 |

## Evidence

One evidence pack, `docs/evidence/2026-11-25-main-audit/`, holds the findings register, the walk numbers before and after, the photograph verdicts and the exact commands.
