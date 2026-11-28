CLEAN

PR 370, `fix/audit-new-p1-search-and-fill-button`, head `3063bdb89397810119aa7063e944b9d1a2061831`, base `3f099e0b6240cb97b72359afdaf0cb1366b3b4ea`. One commit. Reviewed in a temporary detached worktree at the head.

No blocking remarks. Two observations are recorded under checks 2 and 6; neither is a defect in this pull request.

## Check 1: F1, the empty-query search

One form serves all three catalog routes. `CatalogPage.tsx:202` renders the form, and `:94-96` chooses the discover, search or category reading of it, so there is no second catalog search form to patch (`grep -rn 'role="search"'` over `frontend/src` finds only this one).

The fix is two lines:

- `frontend/src/marketplace/CatalogPage.tsx:108`: `const emptyQuery = q.trim() === '';`
- `frontend/src/marketplace/CatalogPage.tsx:219`: `<Button tone="primary" type="submit" disabled={searching || emptyQuery}`

The trimmed question is the condition, so a field holding only spaces stays disabled. `q` is the input state (`:97`, `:215`), so typing enables the button on the same render and clearing disables it. The button also keeps its existing `pending={searchBusy}` at `:220`, so a submit that is accepted disables immediately and shows the busy state after the 100 ms `useBusy` delay.

The disabled styling is the shared disabled primary: `frontend/src/index.css:132` `button:disabled{opacity:.55;cursor:default}` dims it, and `frontend/src/index.css:513` supplies the surface-3 background, rule-strong border and muted text. That is the same styling the fill door's disabled primary uses (`DescribePlugin.tsx:153-154`), and the same styling every other disabled control on the page uses.

A click cannot start a request: the control is a real `button` with the native `disabled` attribute (`components/Button.tsx:61-64`), and the new test asserts the fetch mock gains no call (`frontend/src/test/marketplace-discover.test.tsx:110-114`). The disabled default submit button also stops implicit submission from the text field, so pressing Enter on an empty field does not reach `submit`. The `submit` handler's empty branch at `CatalogPage.tsx:151` is therefore not reachable by a click or Enter in normal use; it remains a harmless defensive path and the change does not need to touch it.

Test: `frontend/src/test/marketplace-discover.test.tsx:104-119` covers disabled at empty, no fetch on click, enabled after typing, disabled again after clearing. The test passes at the head and fails when the disabling is removed (check 3).

## Check 2: F3, the disabled primary

The rule that now dims a disabled primary is `frontend/src/index.css:132`, `button:disabled{opacity:.55;cursor:default}`. The primary's own disabled rule, `frontend/src/index.css:513`, now reads:

```
.btn-primary:disabled{background:var(--surface-3);border-color:var(--rule-strong);color:var(--muted)}
```

It no longer declares `opacity`, so the shared .55 applies. The pending exception is unchanged at `frontend/src/index.css:523`, `.btn-primary.btn-pending:disabled{opacity:1}`, so a primary that is in its own pending state keeps full opacity and its busy label.

The fill door's button is the F3 case: `frontend/src/marketplace/DescribePlugin.tsx:61` computes `const empty = description.trim() === '';` and `:153-154` renders `<Button tone="primary" ... disabled={empty}>Fill it in for me</Button>`. It has no `pending` prop, so the shared dimming is the one that applies.

### Every disabled primary in the frontend

Searched every `.tsx` for a `<Button>` or `<button>` whose tag carries `tone="primary"` or `btn-primary` plus `disabled`. There are 32 sites in 14 files:

- `frontend/src/components/InstanceWalk.tsx:373,493`
- `frontend/src/dashboard/SalesCard.tsx:155,182`
- `frontend/src/dashboard/SetupStrip.tsx:185`
- `frontend/src/dashboard/TrackerSetup.tsx:250,372`
- `frontend/src/marketplace/Admin.tsx:472,520,588`
- `frontend/src/marketplace/CatalogPage.tsx:219`
- `frontend/src/marketplace/ConsentSheet.tsx:114`
- `frontend/src/marketplace/DescribePlugin.tsx:153`
- `frontend/src/marketplace/Installed.tsx:72,483,506,525,614`
- `frontend/src/marketplace/InstanceSetupSheet.tsx:194,215,250`
- `frontend/src/marketplace/PackPage.tsx:172`
- `frontend/src/marketplace/PluginDetail.tsx:168,177,200,207,275,331,1057`
- `frontend/src/marketplace/Publishers.tsx:206`
- `frontend/src/marketplace/Studio.tsx:437,455`

The memory loop is a separate primary system: `.ml-btn-primary` in `frontend/src/memory/loop/memory-loop.css:43-44`, dimmed by its own `#memory-loop-root .ml-btn:disabled{opacity:.45}` at `memory-loop.css:42`. The changed `.btn-primary:disabled` does not reach it, and its disabled primaries already dim. The static design page `docs/design/dashboard.html` is not the application and has no disabled primary.

### Does any disabled primary have to stay fully visible?

No. The only class designed to stay at full opacity is the primary in its pending state, and `index.css:523` preserves that. The pending primaries among the 32 are `InstanceWalk.tsx:373,493`, `SalesCard.tsx:155,182`, `SetupStrip.tsx:185`, `TrackerSetup.tsx:250`, `Admin.tsx:472,520,588`, `CatalogPage.tsx:219`, `Installed.tsx:525,614` and `PluginDetail.tsx:1057`; they keep opacity 1 when their own `pending` prop is true and dim when they are merely disabled by another condition, which is the intended distinction.

The sites that are disabled while working but do not use the `pending` prop now dim too: `ConsentSheet.tsx:114` (`Working...`), `Installed.tsx:72` (`Purging...`), `PluginDetail.tsx:275` and `331` (`Purging...`, `Filing...`), `Publishers.tsx:206` (`Filing...`), `Studio.tsx:437,455` (`Installing...`, `Submitting...`) and `PackPage.tsx:172` (no working label). That is the same treatment the secondary working buttons already receive from the shared rule. Their labels still carry the wait, and none of them has a stated requirement to stay at full opacity. This is the one visible side effect of the general fix: a primary that sets `disabled` immediately and reaches `pending` only after the 100 ms `useBusy` delay dims during that window before returning to opacity 1. It reads as the disabled state rather than a wrong dim, so I do not raise it as a remark.

### Contrast

The disabled primary composites `--muted` on `--surface-3` at .55 over the page. Calculated from the three theme token blocks (`index.css:24-104`): Unkey 2.42:1 over canvas and 2.47:1 over surface; Coforge 2.36:1; Momentuum 2.10:1 over surface and 2.13:1 over canvas. That is below the 3:1 used for large text, which is normal for a disabled control, and the text remains legible at the button's 14 px bold. Nothing here is unreadable, so no P2.

## Check 3: the two tests and the mutations

Focused run in the temporary worktree after `npm ci`:

```
Test Files  2 passed (2)
     Tests  26 passed (26)
```

`frontend/src/test/marketplace-discover.test.tsx:104-119` is the F1 test, and `frontend/src/test/button-pending.test.tsx:232-241` is the F3 test. Both are small and exercise the requirement directly. The F1 test uses the existing `stubCatalog` and fixtures; the F3 test uses the existing `rule()` stylesheet helper and the existing CSS-contract pattern. The F3 test's first and third assertions pin the shared dimming and the primary's surface colour, so it fails for the right reason rather than passing on a missing selector.

Mutation A, F1. I removed `|| emptyQuery` from `CatalogPage.tsx:219` and ran `frontend/src/test/marketplace-discover.test.tsx`: `1 failed | 8 passed (9)`, failing at `marketplace-discover.test.tsx:111` with "Received element is not disabled". Restored with `git restore`; `git hash-object` equals `git rev-parse HEAD:frontend/src/marketplace/CatalogPage.tsx` (`9a2adb3aae735bfcf60d53529fe01415fd6f9087`), and `git status --porcelain` was empty.

Mutation B, F3. I restored `;opacity:1` in the `.btn-primary:disabled` block and ran `frontend/src/test/button-pending.test.tsx`: `1 failed | 16 passed (17)`, failing at `button-pending.test.tsx:239` with "expected 'background:var(--surface-3);border-co...' not to contain 'opacity'". Restored with `git restore`; the file hash equals `git rev-parse HEAD:frontend/src/index.css` (`5119e04816f86329e140fbc84a82852c85a184b4`), and `git status --porcelain` was empty.

Both tests are the smallest that fail without the change: mutation A fails the first behavioural assertion, mutation B fails the single new rule assertion. I also ran the full frontend suite (`43 files`, `649 tests passed (649)`) and `tsc --noEmit` (`exit 0`) in the same worktree.

## Check 4: the committed bundle

In the temporary worktree at the head: `npm ci` exit 0, then `npm run build` exit 0 (`built in 865ms`). After the build, `git diff` is empty (`git diff --quiet` exit 0) and `git diff --stat` prints no content changes.

`git status --porcelain` lists eight text assets:

```
src/agentdesk/server/static/spa/assets/index-D0zbps_M.js
src/agentdesk/server/static/spa/assets/index-DtqzXYGF.css
src/agentdesk/server/static/spa/assets/memory-graph-BGjeuZe0.js
src/agentdesk/server/static/spa/assets/memory-graph.css
src/agentdesk/server/static/spa/assets/memory-graph.js
src/agentdesk/server/static/spa/assets/memory-loop.css
src/agentdesk/server/static/spa/assets/memory-loop.js
src/agentdesk/server/static/spa/assets/useBusy-BnHbzNUF.js
```

That is the `core.autocrlf=true` line-ending artifact the brief allows (`git config core.autocrlf` is `true`). I did not treat it as a failure: for every one of the eight, `sha256sum` of the working file equals `git show HEAD:<path> | sha256sum`, so the committed content and the fresh build are byte-identical. The `index.html` diff points at `index-D0zbps_M.js` and `index-DtqzXYGF.css`, the new CSS bundle carries `.btn-primary:disabled{background:var(--surface-3);border-color:var(--rule-strong);color:var(--muted)}` without `opacity:1`, and the base bundle at `HEAD~` carried the old declaration with `opacity:1`. The committed bundle is a fresh build of this source.

## Check 5: documents and hygiene

The PR title, body and the commit message contain no non-ASCII character at all: a scan of `gh pr view 370 --json title,body,commits` found an empty non-ASCII list in each. So there is no em dash, and no en dash outside a numeric range.

The body has no closing keyword next to a linked issue number. It contains `issue 327` only as plain text, in "Part of the audit fix round for issue 327" and "Issue 327 is deliberately left open by this pull request", with no `#327` or `issues/327` form. The word "fix" in "fix round" is a noun phrase, not a closing keyword, and GitHub does not parse plain "issue 327" as a closing reference; the other "fix" occurrences are in "What this fixes", "fixed together" and "green with the fix". A scan for `#\d+` or `issues/\d+` found no linked issue reference in the body.

No secret is in any diff. The 132-line diff touches `frontend/src/index.css`, `frontend/src/marketplace/CatalogPage.tsx`, the two test files, the two hashed assets, the renamed CSS asset and `index.html`. A scan for private-key blocks, `AKIA`, `ghp_`, `github_pat_`, `sk-`, `xox[baprs]-`, `AIza`, and password/secret/token assignments found no match. There is no file and line to name.

The body's claims match the evidence: the F1 row numbers 13, 305 and 714 are the three empty-query rows in the findings; the F3 row 1245 and page 45 are the describe card; the bundle claim is confirmed above; the same-query rows 26, 318 and 727 are explicitly left out, and the body says so.

## Check 6: the two findings

### F1: met

The empty-query Search now has the native disabled attribute while `q.trim()` is empty (`CatalogPage.tsx:108,219`), the shared disabled styling dims it (`index.css:132,513`), and the test proves the click starts no request and that typing and clearing toggle the state (`marketplace-discover.test.tsx:104-119`). The mutation removing the condition fails the test. This is the finding's requested outcome.

The browser pass that proves it is the pending pass on page 2, `marketplace`, at fresh, plugins and full, with the search field empty. Expected after the fix: the Search button is disabled and visibly dimmed, no request is made on the click, and the empty-query Search rows (13, 305 and 714) are no longer dead. One caveat for the pass's tally: the other three rows the findings label dead (26, 318 and 727) are the same-query searches the review classifies as expected and this PR deliberately leaves enabled, so a literal "dead controls from 6 to 0" also depends on the pass treating those three as expected. This PR removes the three empty-query dead rows; it does not and should not change the same-query behaviour.

### F3: met in code and test

The primary's disabled rule no longer forces `opacity:1` (`index.css:513`), and the shared rule dims the fill door's disabled button (`index.css:132`, `DescribePlugin.tsx:153-154`). The test pins the rule and the mutation restoring `opacity:1` fails it.

The browser pass that proves it is the pending pass on page 45, `overlay-describe`, full, with the description empty. Expected after the fix: "Fill it in for me" is dimmed at the shared .55 opacity. One correction to the finding's premise: the page 45 photograph does not show a bright yellow button. I sampled the source image `walks/after-pending/20261126-213011/full/1280x800/unkey/marketplace__overlay-describe.png`: the button interior is `#16161A` (surface-3) and its brightest text pixels are `#8E8E93` (muted), which is already the disabled colour pair at full opacity. The defect was the forced opacity, not a yellow primary, and the PR body states that accurately. The pass should verify the dimming, not a colour change.

## Check 7: the smallest complete change (ponytail)

The diff is minimal and stays inside the existing structures:

- F1: one condition at `CatalogPage.tsx:219` plus one named condition at `:108` and a two-line comment at `:103-105`. There is no new component, hook, prop or option.
- F3: one declaration removed from the shared `.btn-primary:disabled` rule (`index.css:513`). This is the root cause fixed once, not a per-button override, which is the smaller and more correct option.
- Tests: one test in the existing marketplace-discover file and one block in the existing button-pending file, using the existing fixtures and the existing `rule()` helper. Neither repeats another test: the F1 test is the finding's click/no-request requirement, and the F3 test is the only check on the disabled primary rule.
- The bundle changes are required by the repository's committed-bundle convention.

The only thing smaller would be to inline `emptyQuery` at `CatalogPage.tsx:108` into the disabled expression at `:219` and delete the const, saving one line. I would not do it: the name is read once by a reader and the condition is the point of the fix. Nothing in the diff is an unneeded option, general path, helper or repeated test, and nothing blocks.

## Re-check after merging main, 2026-11-27

New head `09b33eb8f979b1b2b165bea41687b32594c3be38` on `fix/audit-new-p1-search-and-fill-button`. Main merged: `013253143e2006620c8944a9b0d30af6efcdb707` (PR 369, merge `0132531`, after PR 371, merge `3165c55`). PR 372 is open and unmerged, so main carries nothing from it. Two commits: the merge `d0424361` and the bundle rebuild `09b33eb8`.

### Conflicts and resolutions

`git merge --no-ff origin/main` conflicted in one file, `src/agentdesk/server/static/spa/index.html`, one hunk: the module script `src`, `index-D0zbps_M.js` from this branch against `index-BnUOiWv1.js` from main. Main touched neither `frontend/src/index.css` nor `frontend/src/marketplace/CatalogPage.tsx`, so no source file conflicted. PR 369's tools and tests and PR 371's `PluginCardView.tsx`, `types.ts`, `app.py` and `cards.test.tsx` merged cleanly.

The bundle was not hand-merged. I took main's side of `index.html`, committed the merge, then rebuilt. The build deleted both stale entry bundles (`index-BnUOiWv1.js` from main and `index-D0zbps_M.js` from this branch), wrote `index-BSvoylOL.js` and rewrote `index.html` to point at it. The CSS keeps the content hash `index-DtqzXYGF.css`, so main's changes do not reach the CSS.

### The diff against the new main

`git diff origin/main...HEAD --shortstat` is `8 files changed, 41 insertions(+), 9 deletions(-)`, the same totals as the reviewed diff. The four source files (`index.css`, `CatalogPage.tsx`, the two test files) are blob-identical to the reviewed head `3063bdb8`: `git rev-parse <head>:<file>` equals the reviewed value for each. The CSS bundle keeps the reviewed name, so its contents are identical; only the JS entry hash changed (`index-BSvoylOL.js` for `index-D0zbps_M.js`) because the merged build carries main's PR 371 stamp change as well as this pull request's two rules.

The two source changes, the two tests and the bundle are therefore the reviewed diff in substance. PR 371 touched no rule in `index.css` (main's diff has no CSS file at all), so its stamp change and this pull request's disabled-primary rule meet only inside the bundle and combine with no overlap. PR 372 changes the stale stamp wording in `PluginCardView.tsx`, `fmt.ts`, `app.py` and `cards.test.tsx`, and also replaces the bundle. It is unmerged, so nothing from it is here. When it merges it will meet this branch only in the bundle entry, under the same rule: take either side and rebuild.

### Gate

Rebuild: `npm ci` exit 0, `npm run build` exit 0. A second `npm run build` leaves `git diff --quiet` exit 0, `git diff --stat` empty and `git status --porcelain` empty.

Gate in a fresh detached worktree at `09b33eb8` (`mutation/pr370merge`), log at `merge-check/pr370-ci-local.log`:

```
7/7 gates passed in 127s
CI PASS
```

Frontend tests report 651 passed; the two over the reviewed 649 are main's two stamp tests. pytest: 3736 passed, 3 skipped.

### Verdict

Unchanged, CLEAN. This pull request's own behaviour did not change in the merge: the empty-query Search is still disabled through `emptyQuery`, the disabled primary still dims through the shared rule, and both tests pass at the new head. The only behaviour new to the branch is main's own stale stamp, which arrives unchanged and is not this pull request's. No reviewer action is raised for the merge.
