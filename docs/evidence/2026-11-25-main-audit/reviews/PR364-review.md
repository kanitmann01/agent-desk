CLEAN

## Remarks

None. The low remark about the missing e45bd85 gate evidence is withdrawn on 2026-11-26: `drafts/rename/docs-pr-evidence/ci_local-e45bd85.txt` names `e45bd85f3eda9e6b658c08c7b17b97abf6da0f38` and records `7/7 gates passed in 115s` and `CI PASS`.

## Checks

### 1. The file list

Pull request `kanitmann01/agent-desk#364`, branch `docs/spec-032`, head `20ed482419b489e459543f072a9b7da4e209ae82`, base `main` at `2b6de329a4c37100dcbb1e73f252acec03312016`. `git -C "D:/20-projects/Personal Agents/.worktrees/032-spec" rev-parse --short HEAD` printed `20ed482`, and `git status --short` was empty.

`git show --stat --oneline 20ed482` and `gh pr diff 364 --name-only` both list 11 added files, 426 insertions and 0 deletions:

- `specs/032-nexuus-bot-one-name-on-every-live-surface.md`
- `docs/tickets/2026-11-25-rename/01a-name-contract-as-data.md`
- `docs/tickets/2026-11-25-rename/01b-the-guard-that-reads-it.md`
- `docs/tickets/2026-11-25-rename/02-server-surfaces-say-nexuus-bot.md`
- `docs/tickets/2026-11-25-rename/03-spa-says-nexuus-bot-and-the-bundle-is-rebuilt.md`
- `docs/tickets/2026-11-25-rename/04-generated-output-says-nexuus-bot.md`
- `docs/tickets/2026-11-25-rename/05-readme-family-and-public-introduction.md`
- `docs/tickets/2026-11-25-rename/06-operator-guides-specs-and-compatibility-table.md`
- `docs/tickets/2026-11-25-rename/07-human-readable-file-properties.md`
- `docs/tickets/2026-11-25-rename/08-python-package-nexuusbot-and-the-old-import-alias.md`
- `docs/tickets/2026-11-25-rename/09-frontend-package-nexuusbot-dashboard-spa.md`

No code, bundle, parent file, index or other document. The pattern folder `docs/tickets/2026-11-25-presentation-templates/` on `origin/main` holds only its eight ticket files; it has no `00-parent.md`, `ISSUES.md` or README. The rename folder matches that shape, and the source `00-parent.md` and `ISSUES.md` are not copied.

### 2. The spec snapshot

Command: `diff -u ".scratch/wave-2026-11-25/drafts/rename/spec-032.v2.md" ".worktrees/032-spec/specs/032-nexuus-bot-one-name-on-every-live-surface.md"`. The output is exactly one changed line, the status line:

```diff
-**Status:** draft-for-founder (2026-11-25). Defaults await the seam check.
+**Status:** ready-for-agent (2026-11-26). Filed as #353. Tickets: #354, #355, #356, #357, #358, #359, #360, #361, #362, #363
```

The other 258 lines are identical, including the title line `# Spec 032: Nexuus Bot, one name on every live surface`. Both files are 259 lines.

This is the pattern's difference. On `origin/main`, `specs/031-three-presentation-templates.md` has `**Status:** ready-for-agent (2026-11-25). Filed as #322. Tickets: #337, #338, #339, #340, #341, #342, #343, #344`. The spec 031 draft at `.scratch/wave-2026-11-25/drafts/templates/spec-031.md` has `**Status:** ready-for-agent (2026-11-25). Filed as #NUMBER. Tickets: #NUMBERS.`; the diff between that draft and the `main` snapshot is exactly that status line, with the placeholders replaced and the trailing period dropped. The spec 032 snapshot applies the same form with the filed numbers and the filed date 2026-11-26. No title line was added or moved; the source already had one.

Hashes: source `spec-032.v2.md` `4cd7bb6b02b030e918f6e61a20f6e46a1bac3a4226efeb5d4901f18e617fbca4`; snapshot `6d855050ab16b254f0d4fb10630436c5979ddb9bd154a09e7ed008c2fb3bb973`; the one-line diff accounts for the difference.

File name: the source `spec-032.v2.md` becomes `specs/032-nexuus-bot-one-name-on-every-live-surface.md`, following `specs/NNN-slug.md` and spec 031's `031-three-presentation-templates.md`. This is the pattern's.

### 3. Each ticket file

All ten repository files under `docs/tickets/2026-11-25-rename/` are byte-identical to `drafts/rename/tickets/`: `diff` was empty and both SHA-256 values matched for every file.

| File | SHA-256 (source and committed) |
| --- | --- |
| 01a-name-contract-as-data.md | 55614ee09e74b7e4a1b4e6ef79eaf924a78b89ab662261634e31ac5cc338dcfd |
| 01b-the-guard-that-reads-it.md | 04a3f2bd9143040397b6b82118db51e38ea79ce8323141a0b6402b9fa09ba1dd |
| 02-server-surfaces-say-nexuus-bot.md | a4746206e8300b9649cc2c7d760bacfc7c167dc2f9390054fba2f0b9002839e9 |
| 03-spa-says-nexuus-bot-and-the-bundle-is-rebuilt.md | d5a40576dcf649751b4482f49dc81d4e767d1ec53e08f8891084e39b9a737321 |
| 04-generated-output-says-nexuus-bot.md | 59097de8d584e027177d0a61899dc2219e1979a3f22472365c54ff78f5c06a11 |
| 05-readme-family-and-public-introduction.md | d2d41c189aba628c31e41f41d8639e23370c60c192f5aeb5188eb19762858a0d |
| 06-operator-guides-specs-and-compatibility-table.md | 50087283b6af1b4db33dcad1fcc30e56fa9ad55b8d56083ff5ca73397c2cc5cc |
| 07-human-readable-file-properties.md | b83794f96f31da2bf000762037fffb72259104bcb1f081e1d06d650002b88928 |
| 08-python-package-nexuusbot-and-the-old-import-alias.md | 603bfcc61f70fb8b0caabd0fddcd66102e10076fe3ec11b2f2d4fee9fb2d65f2 |
| 09-frontend-package-nexuusbot-dashboard-spa.md | d6986e21521b3bf768bbb7107963028dcadaea93d625f89b6a7e01ac04b94e4c |

Each filed issue 354 to 363:

- Title: the repository heading `# 01a: The name contract as data` maps to issue title `032-1a: The name contract as data`; the `032-` prefix is the pattern's numbering. Spec 031's file `# 01: Workbook figures reach the deck` maps to issue `031-1: Workbook figures reach the deck`. Every one of the ten matched (verified for 354 to 363).
- `## What to build` paragraph: identical to the ticket file's `**What to build:**` paragraph for all ten.
- Acceptance criteria: identical word for word for all ten. Counts: 01a 9, 01b 8, 02 8, 03 8, 04 8, 05 11, 06 10, 07 8, 08 10, 09 7.
- Blocked by: 01a none; 01b #354 (01a); 02 to 06 #355 (01b); 07 #356 to #360 (02 to 06); 08 #356 to #361 (02 to 07); 09 #362 (08). The issue bodies carry the numbers; the ticket files carry the codes, as the pattern does.
- The issue bodies add `## Parent`, `## What to build`, `## Acceptance criteria`, `## Blocked by` and `## Rules for this ticket` with the six standard rules. Spec 031's issue 337 has the same wrappers and rules; they are the pattern's, not differences in the ticket files.

The parent issue 353 title is `Spec 032: Nexuus Bot, one name on every live surface`, the same as the spec title. The ten ticket rows in `final/ISSUES.md` whose Set is Rename match the issue numbers, titles and blocked-by counts.

### 4. The pattern

- Spec: `specs/NNN-slug.md` with `# Spec NNN: ...`, the status line and the `GLOSSARY.md` line. Match.
- Ticket folder: `docs/tickets/2026-11-25-rename/`, following `docs/tickets/2026-11-25-presentation-templates/`. File names `<code>-<slug>.md`, headings `# <code>: Title`, then `**What to build:**`, `**Blocked by:**`, `**Status:** ready-for-agent`, then `- [ ]` criteria. Match.
- No index or README: neither folder has one. Match.
- Parent link: spec 031's status line says `Filed as #322`; spec 032's says `Filed as #353`. Spec 031's documentation pull request (PR 345) closed #323, not #322; #322 remains open. PR 364's body names #353 and the ten tickets and says it does not close #353. Match.
- The codes `01a`, `01b` and `02` to `09` are the approved set's codes; the issue titles use `032-1a` and `032-1b` accordingly. This is the pattern's numbering applied to the approved set, not a missing element.

The eight spec 031 ticket files on `origin/main` are byte-identical to `.scratch/wave-2026-11-25/final/tickets/2026-11-25-presentation-templates/`, and the spec 031 snapshot on `origin/main` is byte-identical to `.scratch/wave-2026-11-25/final/specs/031-three-presentation-templates.md`, so the comparison is against the pattern as it was actually copied.

### 5. The checks on main that read these files

- `tests/test_specs_numbering.py` is the only check that reads `specs/`. Its `SPECS` is `Path(__file__).resolve().parents[1] / "specs"`. `test_every_spec_number_belongs_to_exactly_one_file` asserts every `specs/*.md` starts with a three-digit number and that no number repeats; `test_every_spec_heading_names_the_number_in_its_filename` asserts the first line contains that number, with only 001 to 004 exempt. The snapshot satisfies both: `032-nexuus-bot-one-name-on-every-live-surface.md` is the only 032 file, and its first line is `# Spec 032: ...`. I ran the one permitted file in the PR worktree: `python -m pytest -q tests/test_specs_numbering.py` printed `2 passed in 0.12s`.
- `tests/test_brand_naming.py` is the adjacent documentation check. Its `LIVE_ROOTS` are `src`, `tools`, `scripts`, `docs/ops`, `frontend/src` and `tests`; its `SCAN_FILES` are README, DEMO, frontend README, frontend package.json, frontend index.html and docs/docstrings.md. The em dash scan skips any path whose relative POSIX path starts with `docs`, and `specs` is not in the roots. It therefore does not read the spec snapshot or the ticket files. Its README and face pins read other files.
- No other test, tool or workflow reads `docs/tickets` or `specs`; `grep` over `tests`, `tools`, `scripts` and `.github` found only `test_specs_numbering.py` for `specs` and no reader of `docs/tickets`. The full pytest gate in `tools/ci_local.py` includes the numbering test.

### 6. The implementer's evidence

- `drafts/rename/docs-pr-evidence/comparison.md` records head `20ed482419b489e459543f072a9b7da4e209ae82`, all ten ticket SHA-256 pairs, the spec hashes and the one-line diff. I recomputed all ten ticket hashes and both spec hashes; they match the table; `diff -u` shows the one line.
- `drafts/rename/docs-pr-evidence/ci_local.txt` records the checkout `D:\20-projects\Personal Agents\.worktrees\032-spec`, `PASS pytest 110.7s parallel -n 8: 3560 passed, 2 skipped, 13 warnings in 105.85s`, all seven gates, and the last two lines:

```text
7/7 gates passed in 128s
CI PASS
```

The file identifies the worktree but not the SHA; the head is recorded in `comparison.md` and the PR body. `pr-body.md` is byte-identical to the live PR body.

### 7. Hygiene

- One commit: `docs(spec): add spec 032 and its ten rename tickets`, empty body. No em dash, no en dash, no `@`.
- PR title: `docs: add spec 032 and its ten rename tickets`. No em dash, no en dash, no `@`.
- PR body: no em dash, no en dash, no `@`; it lists parent #353 and tickets #354 through #363, and says it does not close #353.
- The 11 added files carry no U+2014, no U+2013, and no at-sign followed by a username.
- The worktree status was clean; no other file changed.

## Anything surprising

- Parent issue #353 is unlabeled while the ten ticket issues carry `ready-for-agent`. Spec 031's parent #322 is also unlabeled while its tickets carry the label, so this follows the pattern.
- At review time the hosted `Nuitka build + smoke` was IN_PROGRESS and the PR merge state was UNSTABLE. The local gate evidence is green; the hosted Nuitka job is outside the two gate lines in the evidence.
- The branch is one commit ahead of `origin/main` `2b6de32` and was cut before PR 349 merged. The planned merge of main into the branch will require the short re-check; the added documents do not touch the code that merge brings in.

## Re-check of the merge

Reviewed head: `e45bd85f3eda9e6b658c08c7b17b97abf6da0f38`; merged main: `e53c5919fd717fce8867b8127f85285bb1e912e7`; previous reviewed head: `20ed482419b489e459543f072a9b7da4e209ae82`.

1. Merge parents: pass. `git show -s --format=%P HEAD` printed `20ed482419b489e459543f072a9b7da4e209ae82 e53c5919fd717fce8867b8127f85285bb1e912e7`, and the subject is `merge: main into docs/spec-032`.
2. Hashes and sources: pass. All eleven PR files have identical Git blob hashes and bytes at 20ed482, e45bd85 and in the working tree. The ten ticket SHA-256 pairs still match the sources. The spec still differs from `spec-032.v2.md` only in the status line at line 3.
3. Branch diff: pass. `git diff --stat origin/main...HEAD` lists exactly the same eleven files, 426 insertions and 0 deletions; `origin/main` is `e53c591`.
4. Gate evidence: not verifiable from the specified directory. It still contains only the 20ed482 output, `7/7 gates passed in 128s` and `CI PASS`. The live PR body claims e45bd85 with `7/7 gates passed in 115s` and `CI PASS`; no such run output is present in the evidence directory. See the remark above.
5. Checks on main: pass by reading. `tests/test_specs_numbering.py` and `tests/test_brand_naming.py` are unchanged from e53c591. The numbering assertions pass on the unchanged snapshot: exactly one `032-` spec exists and its heading contains 032. The brand-naming test still skips `docs` and does not include `specs`; the search found no other reader of these files.
Gate evidence resolved on 2026-11-26: `drafts/rename/docs-pr-evidence/ci_local-e45bd85.txt` names `e45bd85f3eda9e6b658c08c7b17b97abf6da0f38` and records `7/7 gates passed in 115s` and `CI PASS`; the remark is withdrawn.
