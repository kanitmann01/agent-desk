# P2 confirmations

## P2-01: A chosen tracker face still renders the classic face above it

- **Verdict:** `confirmed`
- **Methods:** reading, running, mutation
- **Severity:** `P1` holds. This is a user-visible duplicate on the custom-tracker path. It also meets the explicit P1 condition that a test passes while the behaviour it names is broken.
- **Restated finding:** Not needed.

### Independent reading evidence

At `frontend/src/dashboard/TrackerCard.tsx:56`, `wizardFace` is true for a fresh card whose payload face is `ui-schema`. The live branch at lines 76-80 nevertheless always renders `TrackerFigure`. The wizard branch at lines 90-100 then renders `faceElements` and blocks. `TrackerFigure` draws `.figure` at `frontend/src/dashboard/cells.tsx:218` and the trend `.spark` through `SeriesChart` at lines 176-198 and 225-239. A wizard-face tracker therefore gets both the classic face and the chosen schema face.

`frontend/src/dashboard/PluginCardView.tsx:385-388` still routes every `excel-report` id to `TrackerCard`, including a wizard-face card, so the duplicate is on the actual dashboard path rather than only in a direct component fixture.

The contract is explicit. `specs/025-executive-plugin-choices.md:170-173` says a confirmed workbook instance will render the face requested by its ui-schema, and lines 258-259 say a workbook plugin that asked for a big number does not render the classic tracker face. `specs/027-one-home-screen-feedback.md:63` requires one tracker tile with one face, while lines 143-144 preserve routing so a wizard-built face still draws its schema elements.

The flagged test at `frontend/src/test/tracker-cards.test.tsx:250-266` creates a fresh `excel-report~wiz` card with `face: 'ui-schema'` and a chosen metric `Value` = `42`, then asserts only that `42` and `Value` exist. It never asserts that `.figure` or `.spark` is absent. The adjacent generic wizard test at lines 268-287 has the same gap.

### Baseline run

Command, from the read-only worktree:

```text
cd "D:/20-projects/Personal Agents/.worktrees/027-merge/frontend" && npx vitest run src/test/tracker-cards.test.tsx
```

Relevant output:

```text
✓ src/test/tracker-cards.test.tsx (9 tests) 89ms
Test Files  1 passed (1)
Tests       9 passed (9)
```

The read-only worktree stayed clean at `3540b9f`.

### Mutation proof

I created a detached worktree at `3540b9f` and installed its own frontend dependencies with `npm ci`. I then made one one-line mutation in `frontend/src/dashboard/TrackerCard.tsx`, immediately after the wizard branch opened at line 91:

```diff
       {wizardFace ? (
         <>
+          {tracker ? <TrackerFigure view={tracker} /> : null}
           {faceElements.map((element, i) => (
```

This affects only wizard-face cards and makes the reported defect plainly worse: those cards now render two classic tracker figures plus their chosen schema elements.

Mutation command, from the temporary worktree:

```text
cd "D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/P2-01/frontend" && npx vitest run src/test/tracker-cards.test.tsx
```

Relevant output:

```text
✓ src/test/tracker-cards.test.tsx (9 tests) 86ms
Test Files  1 passed (1)
Tests       9 passed (9)
```

The suite did not notice the extra classic face. This confirms that the test passes while the one-face behaviour is broken and does not protect the chosen-face contract.

### Cleanup

The temporary worktree `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/P2-01` was removed with the brief's exact `git worktree remove --force` command. The post-removal worktree list matched the pre-removal list with only P2-01 omitted. No prune was run. The read-only `027-merge` worktree remains clean at `3540b9f`.
