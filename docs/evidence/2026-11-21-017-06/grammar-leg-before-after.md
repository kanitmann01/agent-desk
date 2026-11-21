# Evidence 017-06 6a/6b: the grammar gate sees worktree checkouts

The bug (tooling.md F3/F7): `_grammar_gate` in `tools/ci_local.py`
tested the absolute path's parts for `.worktrees`, so every checkout
under this repo's own `.worktrees/` convention walked zero files and
still printed PASS. The floor also skipped `scripts/`.

## Before (this ticket's worktree, at main 33470a1, before the fix)

```
$ cd "D:/20-projects/Personal Agents/.worktrees/017-06-gate"
$ python - <<'PY'
import sys
sys.path.insert(0, "tools")
import ci_local
print("checkout:", ci_local.ROOT)
ok, detail = ci_local._grammar_gate({})
print("BEFORE fix, grammar gate verdict:", ok, "|", detail)
PY
checkout: D:\20-projects\Personal Agents\.worktrees\017-06-gate
BEFORE fix, grammar gate verdict: True | 0 files parse under 3.10
```

This reproduces the audit baseline (tooling.md: "py-grammar reported
`0 files parse under 3.10` and PASSED").

## After (same worktree, with the fix)

```
$ python - <<'PY'
import sys
sys.path.insert(0, "tools")
import ci_local
ok, detail = ci_local._grammar_gate({})
print("AFTER fix, from the worktree:", ok, "|", detail)
PY
AFTER fix, from the worktree: True | 365 files parse under 3.10
```

365 = the 356 src/tests/tools files the gate always intended, plus the
nine `scripts/` files now inside the floor. The count is nonzero in
the very checkout whose path used to blank it. (Re-verified after the
rebase onto main 9418699; the before-run above re-reproduces against
the merge-base tool unchanged.)

The pinned regressions live in `tests/test_ci_local_tool.py`:

- `test_the_grammar_gate_covers_worktree_checkouts_and_the_scripts_tree`
  (a fake checkout under `.worktrees/` with a 3.11-only `except*` file
  in `scripts/` must FAIL the gate; before the fix it passed, having
  checked zero files)
- `test_the_grammar_gate_fails_when_it_finds_no_files` (an empty walk
  is a FAIL, never a green light)
