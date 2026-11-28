CLEAN WITH REMARKS

Review of pull request 348, `fix/sample-client-name`, head 569aec3, against `main` (tip 2b6de32), repository `kanitmann01/agent-desk`. Reviewer: an agent that did not write the code. Read at 2026-11-26 from the pull request's worktree at `D:/20-projects/Personal Agents/.worktrees/sample-name` (head confirmed 569aec3, working tree clean).

## Remarks

### Remark 1 (P3): the pull request body says "all 23 test files", the diff changes 22

- Severity: P3 (polish, a wrong count in public text).
- File: the pull request body on GitHub, section "What changed and why" (same text in the private draft `sample-name-evidence/pr-body.md`, line 3).
- What: the body claims the name was replaced in "all 23 test files that fixture or expect the name". The diff changes 22 test files: 18 under `tests/` and 4 under `frontend/src/test/`.
- Why: nothing is missed, the claim is just off by one; my own search (check 1) confirms no occurrence of the old name remains outside the vendored asset, so 22 is the complete set, not a shortfall.
- Evidence: `git diff origin/main...HEAD --name-only | grep -c -E "(^tests/|frontend/src/test/)"` returns 22 in the pull request worktree.
- Fix: change "23" to "22" in the body (or state the counting basis), or leave and accept the inaccuracy.

### Remark 2 (P3): a fresh build makes `git status` list 8 bundle files as modified, with zero content difference

- Severity: P3 (an environment artifact of this clone, not a bundle mismatch; recorded so no future reader mistakes it for one).
- Files: `src/agentdesk/server/static/spa/assets/index-B1E1R-QO.js`, `index-D8rifP0q.css`, `memory-graph-BGjeuZe0.js`, `memory-graph.css`, `memory-graph.js`, `memory-loop.css`, `memory-loop.js`, `useBusy-BnHbzNUF.js`.
- What: in my temporary worktree (detached at 569aec3) after `npm ci` and `npm run build`, `git status --porcelain` listed exactly these 8 files as modified. `git diff` for them shows no hunks at all, only warnings ("LF will be replaced by CRLF the next time Git touches it"), and the SHA-256 of each committed blob equals the SHA-256 of the freshly built file on disk (all 8 compared and identical; for example index-B1E1R-QO.js is 4a48b3c711f6f8b9... on both sides).
- Why: this clone sets `core.autocrlf=true` in the repository config and `.gitattributes` marks the files `text=auto`, so a checkout would write CRLF into these text files while Vite writes LF. Git therefore reports the working copy as "would be rewritten by checkout", which `git status` surfaces as modified. The committed bundle matches the source byte for byte; a second build changed nothing on disk.
- Evidence: hash comparison of all 8 blobs against the built files (identical), empty `git diff`, `git config core.autocrlf` = true, `git check-attr text` = auto.
- Fix: none required for this pull request. Optionally pin the line endings of the spa assets in `.gitattributes` (for example `-text` or `eol=lf`) or note the artifact in the rebuild evidence, so a rebuild check on a Windows clone reads clean instead of listing 8 phantom modifications.

## The eight checks

### Check 1: nothing was missed

My own search over the whole tracked tree at head 569aec3, run in the pull request worktree:

- `git grep -i -c halvorsen`: one file, `.agents/skills/design-taste-frontend/assets/layout/hero-editorial.html:6`.
- Parts separately: `git grep -i -c halvor` and `git grep -i -c vorsen`: the same single file, 6 each, nothing else.
- Line break between the two words: `git grep -i -E "halvorsen[[:space:]]*$"`: no hits. `git grep -i -E "^[[:space:]]*freight"`: one hit, `docs/evidence/2026-11-22-016-08/browser-evidence.md` line 17 (`  Freight <noun>") clustered...`). Read in context, this is the second half of the new name "Harborlight Freight" split over a line break in a quoted ask wording ("What do we know about the Harborlight / Freight <noun>"), exactly where the old split occurrence was. Not an orphan; both halves are consistently the new name.
- Cross-check on the filesystem (not only tracked files), `grep -r -i -l halvorsen` excluding `.git` and `node_modules`: the same single vendored file.
- Remaining case-insensitive "freight" hits outside the known address and the bundle: all are "Harborlight Freight" text, or the third party copy "freight booking for haulage firms" in `.agents/skills/design-taste-frontend/references/sections-library.md` (a generic English word in the vendored skill's own prose, not the organization's name).

Per-area counts at head: src 0, frontend/src 0, tests 0, tools 0, docs/evidence 0, bundle 0, vendored `.agents` 1 file with 6 occurrences. This matches `count-after.txt` exactly.

The file left: `.agents/skills/design-taste-frontend/assets/layout/hero-editorial.html` ("Halvorsen Arkitekter", that skill's own fictional Oslo practice), unchanged in the diff, as the issue requires.

### Check 2: nothing else changed

I read every hunk of both replacement commits.

- `e238e9d` `fix(sample): give the sample client a fictional name`, 29 files, 193 insertions, 193 deletions: `demo_data.py` (accounts tuple slot 1, sample calendar subject, sample excerpts and facts with their entity pairs, the at-risk sentence, the observation), `insight_connect.py` (docstring example), `sampleDesk.ts` (watch name and address), 4 frontend test files, 18 test files under `tests/`, `tools/demo_readiness.py` (R28 seeded name "Harborlight Freight Group" and held-name check), `tools/demo_walkthrough.py` (expected first preview row), `tools/layout_audit.py` (seed fact), `tools/layout_fixtures/long-values.api.json` (16 rows, titles and the connect note).
- `4be6740` `docs(evidence): ...`, 5 files, 25 insertions, 16 deletions: covered under check 3.

Every changed line differs from its original only by the name: full form "Halvorsen Freight" to "Harborlight Freight", short form "Halvorsen" to "Harborlight", uppercase forms in a case-folding test, lowercase address `halvorsen-freight.example` to `harborlight-freight.example` (same shape, same `.example` domain), or renamed local identifiers (HALVORSEN to HARBORLIGHT, halvorsen to harborlight, _halvorsen to _harborlight). No punctuation, ordering, fixture value, score, amount, date or person changed. The people keep their names: Dana Ortiz, Jordan Lee, Avery Kim, Riley Chen, Sam Ortiz all appear unchanged in context lines. The pre-existing em dash escape `\u2014` in `brief.test.ts` (a deal-name separator test) is untouched context, not new.

Alphabetical order: the sample organizations tuple in `demo_data.py` is not alphabetically sorted, and "Harborlight Freight" keeps slot 1, so nothing that reads the first account moves; `demo_walkthrough.py`'s expectation that the first preview row is "<account> renewal" still holds by position. The only name-order-sensitive assertion found is `tests/test_server_memory_loop.py::test_the_graph_names_the_entity_first_on_its_observation`, which sorts observation labels and expects the organization's label first, before "Jordan Lee: "; "Harborlight" sorts before "Jordan Lee" exactly as "Halvorsen" did, so the expectation holds. No screen or test depends on alphabetical position among the sample organizations.

### Check 3: the evidence records stay honest and well formed

All five documents under `docs/evidence/` carry exactly one dated note at the top saying the sample client's name was replaced, dated 2026-11-25:

- `2026-11-22-016-08/browser-evidence.md` and `2026-11-22-016-09/browser-evidence.md`: one HTML comment line each, inserted above the first heading.
- `2026-11-22-016-09/grounded-stub.py` and `2026-11-22-016-09/stub.py`: one comment note above the module docstring, written as a single sentence wrapped over two comment lines. Still one note, one date, one statement.
- `2026-11-22-016-09/scenario-b.json`: a `"note"` member inserted as the first key. The file still parses: `python -I -c "import json; json.load(open('docs/evidence/2026-11-22-016-09/scenario-b.json', encoding='utf-8'))"` succeeds.

Apart from the note insertions, every changed line in `4be6740` is a name swap (verified hunk by hunk); no other line changed, so the records' facts, timestamps, ids and paths are untouched.

### Check 4: the tests still test the same things

Every changed test keeps the behaviour it names; only the fixture strings and derived local identifiers changed. The shape-sensitive spots:

- `brief.test.ts`: still tests that the deal name strips both the hyphen suffix and the em dash spelling of the index, via the unchanged `\u2014` escape; both assertions recomputed around "Harborlight Freight renewal".
- `tests/test_recommend_rules.py::test_fact_text_cut_at_48_becomes_the_subject`: the assertion computes `text[:48]` from the same string it feeds in, so it stays self-consistent; the cut point moved inside the sentence (the old cut ended inside "be", the new one ends after "to") but the tested behaviour, cut at 48 characters, is the same.
- `tests/test_insight_connect.py::test_the_longer_name_wins_a_span_it_shares_with_a_shorter_one`: keeps its prefix relationship, "Harborlight Freight" is a whole-word prefix of "Harborlight Freight Logistics", so the longest-match behaviour is still exercised, with the count assertions (`line.count(...) == 1`, notes == 5) intact.
- `tests/test_recommend_meetings.py::test_the_match_folds_case`: the event title is now uppercase "HARBORLIGHT FREIGHT renewal call" and the test still asserts the title keeps the event's casing while matching the held name case-insensitively.
- `tests/test_server_rank.py` and `tests/test_server_recommendations.py`: keep their negative assertions (ledger rows hold fact ids only; the name must not appear in ledger detail or subject), now asserting on "Harborlight".
- `tests/test_server_memory_loop.py`: the sort-order expectation discussed in check 2.

I also ran samples: `python -m pytest -q tests/test_insight_connect.py -p no:cacheprovider` in the pull request worktree, 13 passed (no bytecode or cache written); the four changed frontend test files (`brief.test.ts`, `brief-decisions.test.tsx`, `memory-graph.test.tsx`, `feedback-dashboard.test.tsx`) with `npx vitest run` in my temporary worktree, 4 files, 70 tests, all passed. The tests boot only the isolated harness (temporary data folders, loopback stubs); no real desk was started.

### Check 5: the bundle

In my temporary worktree `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr348`, created detached at 569aec3 from `.worktrees/027-merge` (no linking, junctioning or copying of `node_modules`):

- `npm ci` completed (3 audit findings reported by npm, pre-existing in the lockfile, not from this pull request).
- `npm run build` succeeded and produced the same hashed asset names as committed, including `index-B1E1R-QO.js`.
- `git status --porcelain` listed 8 files as modified: see Remark 2. Content-wise this is empty (`git diff` has no hunks) and byte-wise the committed blobs equal the built files, SHA-256 verified for all 8.
- A second `npm run build` changed nothing on disk; the status list and the disk hashes were identical after both builds.

Conclusion: the committed bundle matches a fresh build of the source byte for byte, and a second build changes nothing.

The temporary worktree was then removed with the exact command the brief prescribes, and `git worktree list` confirms it is gone (57 entries remain) while every other worktree is still listed, including `.worktrees/sample-name` at 569aec3 and the founder's checkout. `git worktree prune` was never run.

### Check 6: the vendored file and the screenshots

- `.agents/skills/design-taste-frontend/assets/layout/hero-editorial.html` is absent from the pull request diff (`git diff origin/main...HEAD --name-only -- .agents` is empty) and still holds its 6 occurrences.
- No README file and no image file appears in the pull request diff: the README screenshots are not retaken here, which the issue marks as expected (they are retaken once at the end of the wave).

### Check 7: the merge commit and public text

- Merge `609d7eb`, parents `4be6740` (branch side) and `2b6de32` (main's tip, equal to `origin/main`). No file differs from both parents: the intersection of `git diff 609d7eb^1 609d7eb --name-only` and `git diff 609d7eb^2 609d7eb --name-only` is empty, and the combined diff (`git diff-tree --cc -p`) has no hunks. The merge therefore resolved nothing manually and touched nothing beyond bringing main in; the bundle was handled by the separate rebuild commit `569aec3` after the merge, which replaced main's `index-DIKt6BjX.js` with `index-B1E1R-QO.js` and updated `index.html` (3 files).
- Nothing else to list: the merge's own content is exactly the union of its parents.
- Public text: the title ("fix: a fictional name for the sample client") and body contain no old name and no em or en dash; the body's names section lists Organization "Harborlight Freight", short form "Harborlight", address "harborlight-freight.example". Commit subjects follow `type(scope): subject`: `fix(sample): ...`, `docs(evidence): ...`, `build(spa): ...`; the merge message is git's default. The title uses a bare `fix:` without a scope, which matches established pull request title usage in this repository (merged pull requests 345, 271 and 270 do the same). Scans for U+2013/U+2014 and for the old name over the title, the body, all four commit messages, issue 347's comments and the pull request's comments all returned zero.

### Check 8: the issue, criterion by criterion

1. Every occurrence of the sample client's name replaced; searches recorded before and after per area: MET. My independent search leaves only the vendored asset. `count-before.txt` was recorded at head 0f622e3, which equals `e238e9d^` (verified with `git rev-parse`), and its per-file numbers match my own recount at that commit for the files I spot-checked (`demo_data.py` 11, old bundle asset 1, `test_insight_connect.py` 28, `long-values.api.json` 16, vendored 6). `count-after.txt` matches my search exactly.
2. One fictional name with a consistent short form, used everywhere; people keep their names; nothing else changes meaning; SAMPLE DATA labels intact: MET. Verified hunk by hunk (check 2); the labels come from the desk's SAMPLE DATA marking and no label line was touched; the label assertion in `brief-decisions.test.tsx` is unchanged context.
3. The vendored design-skill asset left as it is, path named in the report: MET. Untouched (check 6); the path is named in `classification.md`, `count-after.txt` and the pull request body.
4. One line at the top of each changed evidence document, dated: MET. All five carry exactly one dated note (check 3); the two Python notes wrap over two comment lines, still one note.
5. No history rewritten, no file removed, old name absent from title, body, commit messages and issue comments: MET with the disclosed exception. The rebuild necessarily deletes the old hashed bundle asset (`index-DIKt6BjX.js`), which the pull request body states explicitly; it is replaced by the rebuild the issue requires. The branch is three normal commits plus a merge; the remote head equals the reviewed head. I cannot prove from here that no force push ever happened; I can say there is no evidence of one, the history reads as a normal branch, and nothing was amended.
6. The names chosen listed in the pull request and the report: MET (body section "The names used"; `classification.md`, `pr-body.md`).
7. The bundle rebuilt once from the source, a second build changes nothing: MET (check 5), verified byte-identical by me; Remark 2 records the status display artifact on Windows clones.
8. `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`: NOT VERIFIABLE BY ME. The brief bars me from running the local gate. The pull request body reports pytest 3560 passed, 2 skipped and frontend 646 passed on this head.
9. No test starts a real desk, no walk run: PARTIALLY VERIFIED BY ME. The tests I ran isolate into temporary data folders with loopback stubs and passed; nothing in the diff weakens isolation. That no walk was performed during implementation I cannot prove from the repository; no walk artifacts are referenced by the pull request.
10. Merge only after review by an agent that did not write the code and the founder's confirmation: NOT YET APPLICABLE. The pull request is open; this document is that independent review; the founder's confirmation is outstanding.

## What I checked and found correct

- The head under review (569aec3) matches the pull request's remote head and the worktree is clean.
- My own case-insensitive search for the old name, its parts, and a split-across-lines occurrence, over the tracked tree and the filesystem, leaves exactly one file: the vendored third party asset, unchanged.
- Both replacement commits read hunk by hunk: replacements only, plus the five note lines; people, numbers, dates, scores and fixture structure untouched; the renamed test identifiers are consistent with the new name.
- The five evidence documents each carry exactly one dated note; `scenario-b.json` still parses.
- The changed tests still pin the behaviours they pinned before, including the shape-sensitive ones; the two sample runs I made (13 and 70 tests) pass.
- The committed bundle is byte-identical to a fresh build, and a second build changes nothing.
- The merge brought main in and resolved nothing; the merge's content is exactly the union of its parents.
- No em dash or en dash, and no old name, in any public text of the pull request, its commits, or the related issue comments.
- The commit and pull request structure matches the brief: one replacement commit, one evidence commit, one clean merge of main, one bundle rebuild commit, nothing else.

Reviewed by an independent agent, 2026-11-26. Nothing in the pull request or in any worktree other than the reviewer's own temporary one was changed; the temporary worktree was removed exactly as prescribed.
