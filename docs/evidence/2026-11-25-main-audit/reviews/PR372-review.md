CLEAN

PR 372, `fix/stale-metric-live-label`, head `f6c381444f5fa24a9fe52404543d6ee527a606c8`, base main `013253143e2006620c8944a9b0d30af6efcdb707`. One commit on top of the merged PR 371 head `9c2298c9`; the pull request's three-dot diff is the eight intended files (source, two tests, bundle). Reviewed in a temporary detached worktree at the head, `mutation/pr372`.

## Check 1: the day rule on both surfaces

The SPA card builds its stamp at `frontend/src/dashboard/PluginCardView.tsx:408-409`:

    const stamp = sourceStale
      ? { fresh: false, text: card.checkedAt ? staleSince(card.checkedAt) : 'Stale' }
      : ...

`staleSince` is at `frontend/src/fmt.ts:53-59`. It compares the local calendar day at `:57` and returns `Stale since ${when}` for today; `:58` returns `Stale since ${at.getDate()} ${MONTHS[at.getMonth()].slice(0, 3)} ${at.getFullYear()}, ${when}` for an earlier day. The clock is `hhmm(at)` at `:56`, the same local wall clock `hhmmFromIso` uses (`:41-44`).

The server fallback calls `_plugin_stale_since` at `src/agentdesk/server/app.py:6390-6392`. The helper is at `:1172-1185`: `:1183-1184` returns `Stale since {at:%H:%M}` when `at.date()` equals `_local_now().date()`; `:1185` returns `Stale since {at.day} {at:%b} {at.year}, {at:%H:%M}` otherwise. `_local_now` is the machine's local zone at `:485-487`.

The date form matches the codebase's existing day-month form: the header date line is `${now.getDate()} ${MONTHS[now.getMonth()]}` (`fmt.ts:27`), and the workbook date cell is `${Number(day)} ${month}` with the three-letter month array (`frontend/src/dashboard/briefModel.ts:87-95`). The new stamp is the same form with the year and the clock appended, which is the example in the PR 371 review remark 1.

Tests: `frontend/src/test/cards.test.tsx:336-383` pins `Stale since 1 Jan 2020, 00:00` at `:357` and `Stale since 09:05` for today at `:382`. `tests/test_ui_text_fit.py:443-463` pins the same two cases at `:458` and `:463`. The behaviour is intentional and pinned on both surfaces.

One scope note, not a remark: the DESK HEALTH last-run cell still prints only the clock (`frontend/src/dashboard/Brief.tsx:354`). That is the pre-existing day-blindness for every row that the PR 371 review put out of scope; this PR does not touch it.

## Check 2: tests fail without the change

Green run at the head, after `npm ci` in `frontend` (168 packages):

- `npx vitest run src/test/cards.test.tsx`: `Test Files 1 passed (1)`, `Tests 29 passed (29)`, 2.76s.
- `python -m pytest tests/test_ui_text_fit.py -q`: `71 passed in 4.05s`.

Mutation: I restored the two label files to the merged PR 371 head, `9c2298c9`, leaving the tests at f6c38144:

- `frontend/src/dashboard/PluginCardView.tsx` hash `eb5df0acd14f71d8089f85ce66fdc7e10bab114d`
- `src/agentdesk/server/app.py` hash `95687989e38f85a2c025aecab3be6ca5d4009ab1`

With the old clock-only labels:

- `npx vitest run src/test/cards.test.tsx`: `Test Files 1 failed (1)`, `Tests 1 failed | 28 passed (29)`. The failure is at `cards.test.tsx:357`: the card renders `Stale since 00:00`, not `Stale since 1 Jan 2020, 00:00`.
- `python -m pytest tests/test_ui_text_fit.py -q`: `1 failed, 70 passed in 4.26s`. The failure is at `tests/test_ui_text_fit.py:458`: `AssertionError: assert 'Stale since 00:00' == 'Stale since 1 Jan 2020, 00:00'`.

Restored with `git checkout HEAD -- ...`. The restored hashes equal the head blobs:

- `PluginCardView.tsx` `673137694b95e359f95caa79ecc480328f5b944f`
- `app.py` `ee1b80a144e93baa47914f85e2967af1e9cea28d`

`git status --porcelain` was empty. The post-restore runs passed again: `29 passed (29)` and `71 passed`.

## Check 3: the bundle

In the temporary worktree, `cd frontend && npm ci` (168 packages, exit 0) then `npm run build` (Vite 7.3.8, `108 modules transformed`, `index-Bu133RZR.js` 250.18 kB, `built in 829ms`, exit 0).

`git diff` after the build: 0 bytes, empty. `git status --porcelain` lists eight static files under `src/agentdesk/server/static/spa/assets/`; every one is content-identical to its head blob (`git hash-object` equals `git rev-parse HEAD:<path>` for all eight; for example `index-Bu133RZR.js` is `cd316e6ee149f38b7f08cd2ebc2b14c520834c2b`). They differ only by LF versus CRLF in the working tree, which is the byte-identical case the task allows. `index.html` still references `assets/index-Bu133RZR.js`.

## Check 4: hygiene

- Title, body and commit message: 0 em dashes and 0 en dashes. Title 65 characters, body 1443, commit body 472.
- Closing keyword next to an issue number: none. The only issue reference is `issue 326` in the source note; the scan found only the words `closing keyword` in the explicit disclaimer `No closing keyword.`, with no number next to them.
- Secret in the diff: none. The added lines have zero matches for PEM private keys, AWS/GitHub/OpenAI/Slack/Google tokens, bearer tokens and credential assignments. The two assignment-shaped matches in the committed bundle are design tokens, `fillToken:"surface-2"` and `borderToken:"rule-strong"`, at `src/agentdesk/server/static/spa/assets/index-Bu133RZR.js:1`; neither is a secret.

## What I did not run

I did not run the gate, an instrument, a walk or the application, and I started no desk. I ran only the two test files and the SPA build in the temporary worktree. The heavy lock `locks/SWARM-HEAVY-RUN.LOCK` was held for the test phases and the build and removed afterwards; the browser lock was checked before each phase and was absent. The temporary worktree `mutation/pr372` was removed with `git worktree remove --force`; the other worktrees and the founder's checkout were left as they were.

## Re-check 2026-11-27: main merged in after PR 370

PR 370 merged first as `91d34c71` (main `91d34c7`), so this branch was brought up to main under the merge-main brief: one merge commit `292474d2` (`merge: main into fix/stale-metric-live-label`), then a bundle rebuild commit. New head `d7b9e6151f13c60f6e22187618e0dbd135820e91`, pushed normally.

- Conflicted file: `src/agentdesk/server/static/spa/index.html` only (`UU`). Resolved by taking main's side (`index-BSvoylOL.js`), then rebuilding. Both sides' bundle files, `index-BSvoylOL.js` and `index-Bu133RZR.js`, were removed by the build's `emptyOutDir`; the new output is `assets/index-Dx1LjW9e.js` (250.20 kB), referenced by `index.html`.
- Source and tests: the PR's own diff against the new main over the five source and test files (`PluginCardView.tsx`, `fmt.ts`, `cards.test.tsx`, `app.py`, `test_ui_text_fit.py`) is byte-identical to the reviewed diff `9c2298c9 f6c38144` (6979 bytes both, zero diff-of-diffs). Full diff against main is 8 files, the same count as the review: the five source/test files plus the three bundle paths (old bundle removed, new bundle added, `index.html` one line).
- Bundle: `npm ci` (168 packages) then `npm run build` in the worktree; a second `npm run build` left `git diff` at 0 bytes and `git status --porcelain` empty.
- Gate: `python tools/ci_local.py` in a clean temporary worktree at `d7b9e615`, `7/7 gates passed in 132s` and `CI PASS` (pytest 3736 passed, 3 skipped; vitest 651 passed). Log: `merge-check/pr372-ci-local.log`.
- Behaviour is unchanged: the reviewed source diff and its two tests are identical, so the verdict stays CLEAN. The heavy lock was held for the build and gate and removed; the temporary worktree `pr372-gate-20261127` was removed; no walk, instrument or desk was started.
