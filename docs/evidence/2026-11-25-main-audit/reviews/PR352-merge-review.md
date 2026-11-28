CLEAN

Scope: pull request 352 at `4eee00b2613e497dca1c5d34c3cb551dd5f00cc6`, merged with main at `68044fc3d32ff356fa74fbb7a46ab9770c932c28`. The previously reviewed head was `4b7398aaaebecf1ba34aa32b46240c6e03896376`. The pull request worktree was clean before and after the test. No application, desk, walk, instrument mode or local gate was run by me.

## 1. The merge itself

`git rev-parse --short HEAD` returned `4eee00b2`. `git show -s --format=%P` returned parents `4b7398aaaebecf1ba34aa32b46240c6e03896376` and `68044fc3d32ff356fa74fbb7a46ab9770c932c28`. Their merge base is `0dc12e73f5741aa924da28d601654eaa7045cb92`.

The two parents changed disjoint file sets. I compared the merge with each parent over that parent's complete changed-file list. `git diff --quiet 4b7398a 4eee00b -- <branch files>` and `git diff --quiet 68044fc 4eee00b -- <main files>` were both empty. The forward and reverse name lists also matched exactly, so there are no extra merge files. Because there is no overlap, this proves every hunk from each side is present and unchanged.

Branch files, each byte-identical to `4b7398a` in the merge:

- `README.md`
- `docs/tickets/2026-11-25-main-audit/03c-face-walk-script.md`
- `tests/test_face_walkthrough.py`
- `tools/face_walkthrough.py`

Main files, each byte-identical to `68044fc` in the merge:

- `docs/evidence/2026-11-22-016-08/browser-evidence.md`
- `docs/evidence/2026-11-22-016-09/browser-evidence.md`
- `docs/evidence/2026-11-22-016-09/grounded-stub.py`
- `docs/evidence/2026-11-22-016-09/scenario-b.json`
- `docs/evidence/2026-11-22-016-09/stub.py`
- `frontend/src/dashboard/sampleDesk.ts`
- `frontend/src/test/brief-decisions.test.tsx`
- `frontend/src/test/brief.test.ts`
- `frontend/src/test/feedback-dashboard.test.tsx`
- `frontend/src/test/memory-graph.test.tsx`
- `src/agentdesk/insight/insight_connect.py`
- `src/agentdesk/server/demo_data.py`
- `src/agentdesk/server/static/spa/assets/index-B1E1R-QO.js` (added)
- `src/agentdesk/server/static/spa/assets/index-DIKt6BjX.js` (deleted)
- `src/agentdesk/server/static/spa/index.html`
- `tests/test_demo_readiness.py`
- `tests/test_engine_tools_route.py`
- `tests/test_insight_connect.py`
- `tests/test_learned_profile.py`
- `tests/test_memory_loop_observations.py`
- `tests/test_profile_review.py`
- `tests/test_recommend_builder.py`
- `tests/test_recommend_meetings.py`
- `tests/test_recommend_rank.py`
- `tests/test_recommend_rules.py`
- `tests/test_recommend_step.py`
- `tests/test_server_memory_graph_api.py`
- `tests/test_server_memory_loop.py`
- `tests/test_server_profile_review.py`
- `tests/test_server_rank.py`
- `tests/test_server_recommendations.py`
- `tests/test_threat_patterns.py`
- `tests/test_ui_wave2.py`
- `tools/demo_readiness.py`
- `tools/demo_walkthrough.py`
- `tools/layout_audit.py`
- `tools/layout_fixtures/long-values.api.json`

Result: no hunk was dropped from either side.

## 2. Nothing else changed

`git log --first-parent 4b7398a..4eee00b` contains only `4eee00b2 merge(main): bring PR 349 and 348 into the face walk`. There is no post-review branch fix or unrelated branch commit.

The other reachable commits are the main-side history named by the pull request body: `68044fc3` (PR 348 merge), `a881fd47` (main merged into the sample-name branch), `954a31b8` (PR 349 merge), `569aec35` (merged-source bundle rebuild), `609d7ebf` (main merged into the sample-name branch), `4be67401` (sample-name evidence), and `e238e9d0` (sample-name implementation). Nothing else is present.

## 3. The fixture names

I read `gh pr diff 348 --repo kanitmann01/agent-desk`, including every hunk under `tools/`. PR 348 changes sample-client data in `tools/demo_readiness.py`, `tools/demo_walkthrough.py`, `tools/layout_audit.py` and `tools/layout_fixtures/long-values.api.json`. The compared old and new values were:

- `Halvorsen Freight Group` to `Harborlight Freight Group`
- `Halvorsen Freight renewal` to `Harborlight Freight renewal`
- `Halvorsen Freight expansion` to `Harborlight Freight expansion`
- `Halvorsen Freight pilot` to `Harborlight Freight pilot`
- `Halvorsen Freight renewal and expansion for the northern region` to `Harborlight Freight renewal and expansion for the northern region`
- `Review the Halvorsen Freight renewal notes, confirm the three open questions, and decide who owns the follow-up call` to the same sentence with `Harborlight`
- `The Halvorsen Freight Group renewal is settled for this quarter.` to the same sentence with `Harborlight`
- `The northern region renewal for Halvorsen Freight is expected to close before ...` to the same sentence with `Harborlight`
- `Also in your desk: Halvorsen Freight, six durable facts; Kestrel Foods, four commitments; and the northern region pipeline workbook with 1,234,567 rows.` to the same sentence with `Harborlight`

I compared all 701 string constants in `tools/face_walkthrough.py` and `tests/test_face_walkthrough.py` with the quoted values on PR 348's changed tools lines. No changed sample-client value occurs in either file. The only shared token is the unchanged JSON key `title`, not a renamed title value.

The load-bearing locators, labels and tokens I also checked were `.face-sheet-demo`, `.face-sheet-grid`, `.face-sheet-tile`, `.face-box`, `.face-eye-left`, `.face-eye-right`, `data-face-slot="rail"`, `data-mood`, `data-size`, `data-theme`, button name `working`, button name `^Step row`, `[data-face-slot="rail"] .face-box`, `.app.rail-collapsed`, `.phone-bar`, `[role="dialog"]`, `.rail .brand [data-face-slot]`, `.brief-answer`, `[role="alert"], .alert`, `textarea[aria-label="Research question"]`, `button.cmd-send`, `button[aria-label^="Widget options"]`, menuitem `Re-test now`, button `Describe a plugin in plain English`, `.setup-sheet[role="dialog"]`, `.tracker-card button`, `Set up`, `Edit`, `Close dialog`, and the `waiting in Inbox` tooltip pattern. The route and asset strings `/research`, `/api/marketplace/retest`, `/face-sheet.html`, `/face-sheet`, `/@vite/client`, `/@react-refresh`, `/src/`, `/node_modules/`, `/@vite/`, `/@id/`, `/@fs/`, and the favicon forms were likewise unchanged. Moods `idle`, `listening`, `thinking`, `reading`, `working`, `waiting`, `blocked`, `done`, themes `unkey`, `coforge`, `momentuum`, motions `normal`, `reduce`, and conditions `fresh`, `full` do not depend on the renamed client.

Result: no face-walk locator, label or string depends on a name or value changed by PR 348.

## 4. The tests

I ran once in the pull request worktree:

`PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_face_walkthrough.py -q -p no:cacheprovider`

Last line: `35 passed in 0.32s`.

The test file is the one added by `0dc12e7..4b7398a`. No real desk or browser was started.

## 5. The sheet-only run at the new head

`audit-3c-evidence/merge-main-sheet-only.txt:1-10` names `merge-main-sheet-only/20261126-183212`, prints `METRIC moods=8 themes=3 surfaces=1 photos=48 reduced-motion=24 missing=0`, then `FACE-WALK PASS`, `EXIT=0`, manifest head `4eee00b2613e497dca1c5d34c3cb551dd5f00cc6`, 48 photo files, 24 reduced-motion files and a free port after the run.

The manifest confirms the full head at line 5, `sheet_only: true` at line 31, both successful sheet readiness URLs at lines 37-40, 48 passed captures with zero missing, and the same metric and verdict at lines 2550-2561. The folder contains exactly 48 PNG files.

The earlier new-head attempt is also accurately recorded. `merge-main-sheet-only/20261126-182421/manifest.json:5` names `4eee00b`; lines 1003-1014 record zero photos, 48 missing, 48 failed and the failure verdict. `merge-main-sheet-only-port-conflict.txt:3-6` names the occupied port, prints the zero-photo metric and `FACE-WALK FAIL 48 failed`, and records exit 2. `merge-main-port.txt:4-17` identifies WSL PID 685 as Vite running from `.worktrees/029-face/frontend`, records `kill -TERM 685`, and confirms the listener and Windows port check were free. The pull request body's port-conflict paragraph is accurate against both runs and the process evidence.

Three photographs I inspected:

- `photos/sheet/unkey/normal/idle.png`: a white rounded face with two dark oval eyes on a black background.
- `photos/sheet/coforge/normal/thinking.png`: a tilted dark navy face with one narrow eye and one square eye.
- `photos/sheet/momentuum/reduce/blocked.png`: a dark navy face with two narrow slanted white eye strokes, the reduced-motion blocked pose.

## 6. The first-run paragraph and R7

The body does not claim that the first attempt ran at `9ce387f`. It correctly names `d53c89b` and says the pull request was reviewed later at `9ce387f`.

The stated cause is supported by the commit history. At `d53c89b`, `SHEET_URL` was the unprefixed `http://127.0.0.1:5199/face-sheet.html`. Vite's base was already `/static/spa/` (`frontend/vite.config.ts:32`). Commit `3f1136a` changed the host to `localhost` and introduced `SHEET_URLS` with `/static/spa/face-sheet.html` first and the unprefixed spelling second. That matches the surviving Vite readiness record and the prior review's reconstruction.

The URL fix and named exit-2 startup handling were already present at `9ce387f`; the commits from `9ce387f` to `4b7398a` preserve them while fixing the collapsed rail, holding guard, crops, verdict rules, manifest closing time and direct scroll. R7 in `PR352-fix-review.md:29` records the successful `4b7398a` run with 48 photographs, the zero-missing metric, `FACE-WALK PASS` and exit 0. R9 asked for the removed first run's cause to be documented. This paragraph supplies that cause and accurately describes the current failure behavior, so it resolves R9 without stating an unsupported cause.

## 7. Still true after the merge

- Only boot path: `tools/face_walkthrough.py:1360-1367` defines the sole boot wrapper and returns `audit._boot_desk(condition, tmp_root)`; its only call is at line 1682. `tests/test_face_walkthrough.py:142-148` pins one `audit._boot_desk(` call and no server factory.
- Guard before navigation, in holding mode: `tools/face_walkthrough.py:361-369` calls `audit._install_request_guard(..., answered=False)`. The real context installs that guard at lines 1686-1690, before the first `page.goto` at lines 1699-1700. The walk's explicit research and held-retest routes are installed at lines 401-405. The sheet context likewise installs the holding guard before its navigation at lines 962-983.
- `tools/layout_audit.py` carries only main's change: `git diff 68044fc 4eee00b -- tools/layout_audit.py` is empty, and both `68044fc:tools/layout_audit.py` and `4eee00b:tools/layout_audit.py` have blob `77aced64e2966f2817f008baa239727ff6a362be`. The branch parent's old blob is `7bf47ad699c9406d76e66fae839d71c7552f1b55`. The merged main hunk is the `Harborlight Freight` fact at `tools/layout_audit.py:2575-2578`, inside `_seed_busy`. The face walk calls `audit._seed` at line 1542; `_seed` is defined at `tools/layout_audit.py:2387-2450` and does not call `_seed_busy`.

## 8. Hygiene

Commit messages in `0dc12e7..4eee00b`, the pull request title and the pull request body contain no em dash and no en dash. A scan of every added line in the branch diff `0dc12e7..4b7398a` and merge diff `4b7398a..4eee00b` found zero matches for common AWS, GitHub, OpenAI, private-key and assigned-secret formats. There is no secret file and line to report.

Cleanup: I created only the required detached worktree at `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/mutation/pr352merge`, removed exactly that worktree with `git worktree remove --force`, and did not run `git worktree prune`. The directory is gone. A before/after comparison of `git worktree list --porcelain` shows the temporary entry removed and all other 60 worktree entries unchanged and still listed.
