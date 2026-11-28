DIFFERENCES FOUND

## Difference 1

- Runbook: `runbook/walk-after.md`
- Line: 185-211, especially 205 and 209
- What: The slow-run paragraph is accurate about why the command is blocked on `b396694`, but it is not unambiguous about the post-366 evidence scope.
- Why: The command selects `fresh,plugins,full`, but only `full` starts and pins the four-second loopback mock. Without that caveat, a walk agent could treat `fresh` or `plugins` controls as delayed-model evidence or as failures under the four-second delay.
- Evidence: `b396694:tools/layout_audit.py:3807-3809` starts the mock only for `data`, `full`, `long-values` and `busy`. Issue 366 explicitly says that only `full` has delayed-model evidence and that the other two conditions must not be described that way. The absent `--continue-request-path` option on `b396694` is expected and is not this difference.
- Fix: After line 205 or line 209, add: "Only the `full` condition starts and pins the four-second loopback mock. `fresh` and `plugins` remain undelayed, so do not label their controls as delayed-model evidence." Keep the existing issue 366 merge and repin guards.

## Earlier differences

1. Resolved: stale pins and the obsolete face overlay are corrected at `runbook/walk-before.md:5-7,42` and `runbook/walk-after.md:5-7,45-55,251-263`.
2. Resolved: the slow command is blocked until issue 366 merges and the worktree is repinned at `runbook/walk-after.md:185-211`; the remaining scope ambiguity is Difference 1 above.
3. Resolved: both runs require all nine pending verdict categories, with zero for absent categories, at `runbook/walk-before.md:161` and `runbook/walk-after.md:174,348-349`.
4. Resolved: face exit 2 is split into early failures with no artifacts and startup failures with artifacts at `runbook/walk-after.md:325-326`.
5. Resolved: feedback exit 1 and face exit 1 are hard stops at `runbook/walk-after.md:385-386`.
6. Resolved: layout acceptance names `findings.json`, the normal and stress filters, and the scroller exception at `runbook/walk-after.md:151`.
