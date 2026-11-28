CLEAN WITH REMARKS

PR 371, `fix/stale-metric-live-label`, head `9c2298c93e3874bcacfa59fe43c3266bdeb1428b`, base main `3f099e0b6240cb97b72359afdaf0cb1366b3b4ea`. One commit. Reviewed in a temporary detached worktree at the head, `mutation/pr371`, removed afterwards.

The pull request does what it says: the card, the health row and the server fallback no longer call a stale source live, and the last good value stays. Two remarks follow, neither blocking. The first is the finding the task asked me to judge: the new label drops the day. The second is the API field, which still says `freshness: "fresh"`; it is a latent inconsistency outside this label change.

## Remark 1 (P2): the stale stamp drops the day, so a 2020 value reads `Stale since 00:00`

Files and lines: `frontend/src/dashboard/PluginCardView.tsx:408-410`, `src/agentdesk/server/app.py:6375-6381`.

What: the stamp is `Stale since ${hhmmFromIso(card.checkedAt)}` on the SPA card and `Stale since {hhmm}` from `datetime.fromisoformat(...).strftime("%H:%M")` on the server fallback. Both take only the clock from the timestamp.

Why: the evidence's card has `checkedAt: "2020-01-01T00:00:00"` and `payload.source.asOf: "2020-01-01T00:00:00"` (`walks/after-face-api/api-dashboard.json`). The card now reads `Stale since 00:00`, and the DESK HEALTH row's last-run cell reads `00:00` too (`Brief.tsx:354` via `fromIso`). A reader sees a time that reads as midnight today, not a value from 2020. The card no longer lies about being live, but this label misleads about the day, which is the one thing the stale stamp exists to tell. The fix's own case is the rare path: a stale value from another day.

Evidence: the head's test pins this exact output, `expect(screen.getByText('Stale since 00:00'))` at `frontend/src/test/cards.test.tsx:357`, and the server test pins `widget.freshness.stamp == "Stale since 00:00"` at `tests/test_ui_text_fit.py:458`. Both pass, so the behaviour is intentional and reproducible, not a test accident.

Fix: show the date when the value is not from today, for example `Stale since 1 Jan 2020, 00:00`, and keep `Stale since HH:MM` for a value from today. The date is already on the wire in `checkedAt` and `source.asOf`; no new API field is needed. Both surfaces need the same rule (`PluginCardView.tsx:408` and `app.py:6375-6381`); the smallest form is one `sinceLabel` helper in `fmt.ts` and its server twin, or reuse the existing day formatting if it is exposed. The health row's clock has the same day-blindness (`Brief.tsx:354`), but that is pre-existing for every row and not introduced here.

## Remark 2 (P2, out of scope for this change): the API still serves `freshness: "fresh"` for a stale source

Files and lines: `src/agentdesk/plugins/execute.py:953`, `src/agentdesk/plugins/cards.py:258`, `src/agentdesk/plugins/cards.py:288`, served through `src/agentdesk/server/dashboard_state.py:192`.

What: `_status_dict` maps only `blank` to `attention`, so a stale read keeps `status: "fresh"`; `widget_card` copies that into the card's `freshness`, and `card_to_api` serves it unchanged. The pull request does not touch any of these. The API record therefore still says `freshness: "fresh"` and `payload.status: "fresh"` while `payload.source.state` is `stale` (`walks/after-face-api/api-dashboard.json`).

Why it is a defect: `src/agentdesk/server/core.py:41-44` defines `FRESH` as "data is current", and the served field says fresh for data that is not. Any consumer that reads `freshness` alone is told the card is current. The SPA no longer does for the card or the health row, and the server fallback no longer does, so no user-facing surface in this repository still presents the stale source as live after this pull request. That makes it P2 (a wrong detail for a rare non-SPA consumer), not the P1 the finding named. It is out of scope for a label change: changing `_status_dict` to `attention` would make `fresh = card.freshness === 'fresh'` false at `PluginCardView.tsx:405`, and the `elements` gate at `:412` would hide the last good value, which ticket 06 requires. A follow-up should either separate "has a value" from "is current" in the API, or change the state mapping together with the SPA's value gate.

## Check 1: every place a stale source can reach a reader

The stale state on the wire is `payload.source.state === "stale"` (`_source_envelope`, `src/agentdesk/plugins/execute.py:967-982`; the fixture path is `sources.py:910-916`). Every reader I found:

1. Plugin card, both callers. `Dashboard.tsx:660` renders `PluginCardView` for the desk grid, and `Brief.tsx:512` renders it for the lower rows; both pass the same card. `PluginCardView.tsx:405-411` reads `sourceStale` and builds `stamp = { fresh: false, text: 'Stale since HH:MM' }` (or `Stale` when `checkedAt` is empty), and `:457` passes it to `Stamp`. The value stays because `fresh` remains true and `elements = fresh ? ...` at `:412` still renders. The stamp is amber (`Stamp.tsx` uses `stamp amber` for `fresh: false`, `index.css:328-331`) and the card chrome stays white, which is the `WidgetCard` rule that the amber pair lives on the stamp and the alert block, not the chrome (`WidgetCard.tsx:196-198`). No `live` text remains for this card.
2. DESK HEALTH row. `Brief.tsx:347-357` now computes `stale` and sets `live: card.freshness === 'fresh' && !stale` and `status: stale ? 'stale' : ...` (`:351-352`). The group count at `cells.tsx:358` and `:376` is `plugins.filter((item) => item.live)`, so the stale row is not counted live, and the row's status word is `stale`. The `CellHead` count at `Brief.tsx:372` counts only the three desk sources, not plugin rows, so it is unaffected; the plugin group has its own count.
3. Server-rendered fallback. `_plugin_widget` is called only at `app.py:2874`. It now reads the source envelope at `:6333-6337` and, for a stale source that is otherwise fresh, stamps `Stale since HH:MM` at `:6375-6381`, sets `Freshness.status` to `ATTENTION` at `:6383`, and keeps the elements because the body branch still follows the original fresh status at `:6341-6349`. No `live` stamp remains for this card.
4. Tracker card, both callers. `TrackerCard.tsx:33` still gates on `card.freshness === 'fresh'`, and `Brief.tsx:417` and `Dashboard.tsx:660` (which delegates at `PluginCardView.tsx:389`) render it. It is not reachable with `state: "stale"`: a tracker payload is built by `_tracker_payload`, whose dict has `elements`, `status` and `tracker` and no `source` (`src/agentdesk/plugins/cards.py:198-205`), and the workbook source maps a non-fresh watcher to `blank`, not `stale` (`sources.py:466-473`). So no stale source is presented as a live tracker.
5. The API JSON. `card_to_api` at `cards.py:288` still carries `freshness: "fresh"`; that is Remark 2. The SPA's other readers of `freshness` are `TrackerCard.tsx:33` (above) and `Brief.tsx:95` (`isTransportFailure`, which reads an attention card and a reason code, not a stale source). No other frontend file reads `freshness`; `grep` over `frontend/src` finds only these production sites.
6. Instruments. `tools/smoke_first_plugin.py:113` prints `freshness`, and `tools/demo_walkthrough.py:650-651` and `:767` assert `fresh` for a configured workbook. They are instruments, not user surfaces, and their cases are not stale. No change is needed for this finding.

One scope note, not a remark: `PluginCardView.tsx:445-451` still gates the card menu on `fresh`, so a stale source (whose `freshness` is still `fresh`) offers only `Manage plugins`, not `Re-test now`. `docs/PRD.md:49` R1.2 says "stale-amber with Re-test", so that half of the contract is still unmet, as the confirmation's "Why it is wrong" already said. The pull request does not claim to change the menu, and the card offered no Re-test before either, so this is a follow-up rather than a regression. If the finding is to be closed whole, key the menu on `fresh && !sourceStale` so the stale card can re-read its source.

## Check 2: the API field

Yes, the server still reports `freshness: "fresh"` for a source whose state is `stale`. The chain is `execute.py:953` (`status = "attention" if result.state == "blank" else "fresh"`), `cards.py:258` (`freshness=data.get("status", "attention")`) and `cards.py:288` (`"freshness": card["freshness"]`), and the pull request changes none of them. The evidence record still shows `freshness: "fresh"` with `payload.source.state: "stale"`.

Is leaving it a defect? Yes, as an API contract inconsistency, and it is P2, not P1: after this change no surface a user reads in this repository presents the stale source as live, but a consumer that trusts only `freshness` is still told the data is current. Is it in scope? No. The label change is the smallest change that keeps the last good value; making `_status_dict` return `attention` for stale would flip `fresh` at `PluginCardView.tsx:405` and hide the value at `:412`. The clean follow-up is a separate liveness field or a state mapping changed together with the SPA gate. I would not block this pull request on it; I would open a follow-up.

## Check 3: the label's truth, contrast and wording

What it shows for another day: for the evidence's `2020-01-01T00:00:00`, `hhmmFromIso` at `fmt.ts:41-44` returns `00:00`, so the card reads `Stale since 00:00` and the server fallback reads the same. There is no date. The DESK HEALTH row's last-run cell also reads `00:00` (`Brief.tsx:354`). That is the P2 in Remark 1.

Timezone: the evidence's timestamp is a naive ISO string with no offset. JavaScript parses a date-time without an offset as local time, so `getHours()` is 0 in every timezone and the label is the literal clock in the source string, not a conversion. Python's `datetime.fromisoformat` on the same string is naive too, and `strftime("%H:%M")` prints the same `00:00`. Both surfaces therefore agree for every current plugin source, because the plugin `as_of` values are naive local strings (`sources.py:136` `_now_iso`, `sources.py:293-298` `_mtime_iso`, `execute.py:151-159` `_iso`, and the manual file's own `updatedAt`). If a source ever stamped an offset or a trailing `Z`, the SPA would convert it to the browser's zone while the server fallback would keep the offset's clock; no current source does, so this is a note, not a finding.

Wording: `Stale since HH:MM` is the exact wording `fmt.ts:59` uses for the sales card and `sales.py:87` uses for the server sales stamp, and the pull request cites both. The server fallback uses the same string. It follows the codebase rule.

Contrast: the stamp uses the existing `.stamp.amber` pair, `color: var(--accent-text)` on `background: var(--surface-2)` (`index.css:328-331`), with the existing amber dot `.dot.amber` (`index.css:246`). Contrast ratios from the three theme token blocks: Unkey 15.79:1, Coforge 5.14:1, Momentuum 5.34:1. All pass 4.5:1 for the 12px, 600-weight stamp text, so the amber stamp follows the existing rule and is readable.

## Check 4: the three tests and their mutations

Run at the head in the temporary worktree after `npm ci`:

- `npx vitest run src/test/cards.test.tsx src/test/brief-decisions.test.tsx`: `Test Files 2 passed (2)`, `Tests 45 passed (45)`.
- `python -m pytest tests/test_ui_text_fit.py -q`: `71 passed in 4.46s`.
- `npx tsc --noEmit`: clean, no output.

The three new tests are one per surface and each exercises its own behaviour:

- `frontend/src/test/cards.test.tsx:336-361`: the PluginCardView stamp, the value kept, the amber class, no `live`.
- `frontend/src/test/brief-decisions.test.tsx:294-306`: `0 of 1 live` and the row word `stale`.
- `tests/test_ui_text_fit.py:443-461`: `status == "attention"`, the stamp, and the value in `body_html`.

Mutation A, the PluginCardView stamp. I restored the base file (`git checkout 3f099e0b -- frontend/src/dashboard/PluginCardView.tsx`) and ran the card test. It failed at `cards.test.tsx:357` on `getByText('Stale since 00:00')`: `Test Files 1 failed (1)`, `Tests 1 failed | 28 skipped (29)`. The reverted card stamps `live`, so the test fails for the right reason. Restored with `git checkout HEAD -- ...`; `git hash-object` equals `git rev-parse HEAD:frontend/src/dashboard/PluginCardView.tsx`, `eb5df0acd14f71d8089f85ce66fdc7e10bab114d`, and `git status --porcelain` was empty.

Mutation B, the Brief health row. I restored the base `Brief.tsx` and ran the brief test. It failed at `brief-decisions.test.tsx:303` on `getByText('0 of 1 live')`: `Test Files 1 failed (1)`, `Tests 1 failed | 15 skipped (16)`. The reverted row counts the stale plugin as live. Restored; the hash equals HEAD `d1a4db254cb739a3b89f85d885e59a16324fffb4`, and the status was empty.

Mutation C, the server fallback. I restored the base `app.py` and ran the server test. It failed at `tests/test_ui_text_fit.py:457` with `AssertionError: assert 'fresh' == 'attention'`, `1 failed in 0.21s`. The reverted fallback stamps a fresh card for the stale source. Restored; the hash equals HEAD `95687989e38f85a2c025aecab3be6ca5d4009ab1`, and the status was empty.

Each test is the smallest that fails without its place: one new test per surface, with no shared helper and no repeated assertion. The extra assertions in the card test and the server test pin the "last good value stays" requirement, which is part of the change, not padding.

## Check 5: the bundle

In the temporary worktree, after `npm ci` (168 packages) and `npm run build` (Vite 7.3.8, `built in 861ms`), the build wrote `assets/index-BnUOiWv1.js` (249.96 kB), the same hashed name the pull request commits.

`git diff` after the build: empty. `git status --porcelain` listed eight static files as modified; every one is content-identical to the head blob, verified with `git hash-object` equal to `git rev-parse HEAD:<path>`. The working-tree copies differ only by LF versus CRLF, which is why Git lists them and `git diff` is empty; that is the "byte-identical files" case the task allows. The committed bundle is the fresh build of the head sources.

## Check 6: documents and hygiene

- The pull request title, body and commit message: 0 em dashes, 0 en dashes. Checked the GitHub JSON for `title`, `body` and each commit's headline and body, and the counts are 0 in all three.
- No closing keyword next to an issue number. The body mentions `issue 326` twice, has no `#` reference, and ends with `No closing keyword.`, which matches. The regex for `close|fix|resolve` near `#\d+` or `issue \d+` found nothing.
- One commit, `9c2298c9 fix(dashboard): stamp a stale plugin source stale, not live`.
- No secret in any diff. I scanned the full `git diff origin/main...HEAD` for PEM private keys, AWS keys, GitHub tokens, OpenAI keys, Slack and Google keys, bearer tokens and `key/secret/password/token = "..."` assignments: zero hits. No file needs naming.

## Check 7: the smallest complete change (ponytail)

The diff reaches exactly the readers that present the card: one component shared by both callers (`PluginCardView.tsx`), the health row (`Brief.tsx`), the server fallback (`app.py`), and the type declaration the frontend needs (`types.ts:205`). It adds no module, helper, option or abstraction, and it uses the wording and stamp pair the codebase already has.

Nothing is unneeded. The `staleWhen` guard and the `Stale` fallback are one variable and one ternary; deleting them would print `Stale since ` for a card with no `checkedAt`, which is worse than the fallback. The nested ternary in `Brief.tsx:352` is two lines and cannot be removed without leaving the row `live`. The three tests are one per surface, not repeats.

The smaller alternative, one server line in `_status_dict` mapping stale to attention, would not do the whole job: `PluginCardView.tsx:405` and `:412` gate the elements on `freshness === 'fresh'`, so the card would lose the last good value and show `Re-test available` instead of `Stale since`, which the ticket forbids. The three-surface label change is the smallest complete change for what the finding requires.

No ponytail remark hides a defect. The only scope gap is the missing Re-test noted under Check 1, which the pull request does not claim and which was absent before.

## What I did not run

I did not run the local gate, the layout audit, a walk, the instrument or the application, and I did not start a desk. I ran only the three test files, `tsc --noEmit`, and the SPA build in the temporary detached worktree. The heavy lock was held for the test and build phases and removed afterwards. The temporary worktree `mutation/pr371` was removed with `git worktree remove --force`; `git worktree list` still lists the founder's checkout and the other worktrees.
