# 02: Baseline numbers and the BEFORE walk

**What to build:** one pinned starting point for the whole audit. The audited commit is named, the gate numbers are recorded once, and the BEFORE walk that the previous wave never takes is taken: the pending walk with the final instrument, run against main as it was before the wave (`f31582a`), so BEFORE and AFTER compare one for one with the same seven verdicts.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] The audited commit hash is written at the top of the evidence file.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS` on the audited commit, with its counts (pytest passed and skipped, vitest passed).
- [ ] From the audited commit, `cd frontend && npm run build` run twice leaves the committed bundle unchanged (`git diff --exit-code -- src/agentdesk/server/static/spa` is clean after each build).
- [ ] `python tools/demo_readiness.py` prints `METRIC ready=27` with 0 FAIL.
- [ ] The instrument's selftest prints `SELFTEST PASS` for every expectation group (16 detector, 4 box, 10 pending).
- [ ] BEFORE is taken from the existing worktree at `f31582a` (`.worktrees/before-main`) after copying in, uncommitted, the final `tools/layout_audit.py`, `tools/mock_endpoint.py` and `tools/layout_fixtures/`. The pending walk command below completes with no planned combination unmeasured, and its METRIC line and verdict table are recorded: controls, instant, meets, native-dialog, silent, disabled-only, skipped, dead, box-changed.

```bash
uv run --no-project --with playwright --with keyring --with cryptography \
  python tools/layout_audit.py --pending-audit \
  --conditions fresh,plugins,full --widths 1280 --themes <default-theme-id> \
  --no-stress --fail-on none --jobs 3 --out <dir>
```

- [ ] The evidence file states that BEFORE is old main measured by the new instrument, and names the three copied paths.
- [ ] Nothing in the `f31582a` worktree is committed or pushed. `git status` there shows only the three copied paths.
