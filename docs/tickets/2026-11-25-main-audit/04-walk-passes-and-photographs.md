# 04: Walk passes on main, every photograph read

**What to build:** the merged main is driven in a real browser, with the machine otherwise idle, and every photograph it produces is looked at by a reviewer that can see. Five passes: the layout matrix, the pending walk, the feedback walk, the slow run that the previous wave left untaken (the mock model delayed by four seconds), and the face walk that has never been taken. The result is a set of numbers and a verdict for every photograph.

**Blocked by:** 01.

**Status:** ready-for-agent

Commands, run from Git Bash at the repository root of the audited worktree:

```bash
# Layout matrix
uv run --no-project --with playwright --with keyring --with cryptography \
  python tools/layout_audit.py \
  --conditions fresh,data,plugins,full,legacy-dashboard,long-values,busy \
  --fail-on none --jobs 2 --out <dir>

# Pending walk
uv run --no-project --with playwright --with keyring --with cryptography \
  python tools/layout_audit.py --pending-audit \
  --conditions fresh,plugins,full --widths 1280 --themes <default-theme-id> \
  --no-stress --fail-on none --jobs 3 --out <dir>

# Slow run: the pending walk with the mock model delayed by four seconds
uv run --no-project --with playwright --with keyring --with cryptography \
  python tools/layout_audit.py --pending-audit \
  --conditions fresh,plugins,full --widths 1280 --themes <default-theme-id> \
  --no-stress --fail-on none --jobs 3 --mock-delay-ms 4000 --out <dir>

# Feedback walk
uv run --no-project --with playwright --with keyring --with cryptography \
    python tools/feedback_walkthrough.py
```

`<default-theme-id>` is the first theme the audit's help lists for `--themes`. The previous wave's pending walk used that theme alone, and BEFORE and AFTER must use the same one.

The face walk uses the same isolated desk and the instrument's options (`--routes`, `--themes`, `--widths`, `--record-api`), plus the dev-only face sheet for moods that no real action reaches in a fresh desk.

- [ ] Layout matrix: no planned combination is unmeasured (no `COVERAGE INCOMPLETE`). With real strings and with long strings there are zero findings outside the 11px class and zero broken words. With tripled strings, every finding outside the 11px class is a table cell inside its own scroller (40 at `2d00540`); any other is a finding.
- [ ] Pending walk: the METRIC line ends `dead=0`, and the verdict table shows `silent` 0 and `disabled-only` 0. The counts of controls, instant, meets, native-dialog and skipped are recorded next to the BEFORE row from ticket 02.
- [ ] Four controls the previous wave named are read in the photographs: the memory review setting set to "Ask me first" reads `meets`; Research with no question typed is already disabled; "Fill it in for me" with an empty description reads `skipped`, never `dead`; Copy digest shows a check on success and a manual path on refusal.
- [ ] Feedback walk exits 0 with all seven actions present, and each action's three photographs (early wait, after ten seconds, result) are in its run folder.
- [ ] Slow run: completes with no planned combination unmeasured; its run folder and METRIC line are recorded, and any control that fails the first-second rule under the delay is a finding.
- [ ] Face walk: at least one photograph for each of the eight moods in each of the three themes at 1280 (24 in all), plus the collapsed rail, the phone strip, the two dialogs that hold the face, and the reduced-motion poses for the eight moods. Each photograph is listed with its verdict.
- [ ] Every photograph produced by these runs has a verdict in `photographs.md` of the evidence pack: clean, or a finding id. The number of verdicts equals the number of photographs produced.
- [ ] Every visible defect seen in a photograph is a finding in the register with a severity.
- [ ] The AFTER numbers stand next to BEFORE in one table.
