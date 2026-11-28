# P4 confirmations

## P4-01: Primary server actions remain inert with JavaScript off

- Verdict: narrowed
- Severity: P1 holds
- Methods: reading, running, mutation

### Reading

In the read-only worktree at `3540b9f`, ordinary inbox cards render their primary action as a bare `data-accept` button at `src/agentdesk/server/inbox_view.py:60-63`, Dismiss as a bare `data-dismiss` button at line 123, and dismissed-card Restore as a bare `data-restore` button at line 185. None of those controls is inside a form or names a form. The only click wiring is in `APP_JS`: `src/agentdesk/server/pages.py:1123-1134` attaches POSTs for all three selectors.

The accept and dismiss server handler can answer a form post with a notice redirect (`src/agentdesk/server/app.py:5082-5089`), but the rendered controls never submit that form path. Restore is narrower than the review claims: `_inbox_restore` always returns JSON, including after success (`src/agentdesk/server/app.py:5820-5845`), so adding a form alone would not give Restore a normal page result. The sales Re-test is also a bare button (`src/agentdesk/server/sales.py:156-166`) wired only by `APP_JS` (`src/agentdesk/server/pages.py:976-989`), the calendar re-test is bare (`src/agentdesk/server/pages.py:1953-1956`) and script-wired (`src/agentdesk/server/pages.py:991-1003`), and dashboard skill-run buttons are bare (`src/agentdesk/server/pages.py:1756-1762`) and script-wired (`src/agentdesk/server/pages.py:1278-1287`). Their handlers currently return JSON (`src/agentdesk/server/app.py:2291-2298`, `2315-2323`, and `2465-2472`).

One important exception narrows the finding: update-consent cards have a second, plain POST Accept form at `src/agentdesk/server/inbox_view.py:93-106`. That form still accepts without script even though the primary Accept button above it is inert. Ordinary cards have no such fallback.

The closest test's stated no-script coverage is limited to settings toggles: `tests/test_ui_feedback.py:453-497`. Its peer refusal test posts a form but does not exercise inbox decisions.

### Running

From the read-only worktree root, with bytecode and pytest cache disabled and with `AGENTDESK_DATA`, `AGENTDESK_TEMPLATES`, `HOME`, and `USERPROFILE` redirected to a fresh temporary folder:

```text
python -m pytest -q -p no:cacheprovider tests/test_ui_feedback.py
47 passed in 21.43s
```

The test harness injects in-memory stores and temporary profile, plugin, outbox, deck, and template roots (`tests/server_harness.py:226-332`). No real desk data folder was used.

### Mutation

In detached temporary worktree `.scratch/wave-2026-11-25/mutation/P4-01`, I deleted the update-consent POST form block from `src/agentdesk/server/inbox_view.py:93-106`. This removed the one existing no-script inbox Accept path while leaving all test assertions unchanged. The same isolated command still reported:

```text
47 passed in 21.97s
```

The test did not notice. This confirms the coverage gap, not merely the already-inert ordinary buttons.

### Restated finding

With JavaScript off, ordinary inbox cards cannot be accepted or dismissed and dismissed cards cannot be restored because those controls are script-only buttons; update-consent cards retain one separate no-script Accept form. Sales and calendar Re-test and dashboard skill-run controls are also script-only. The no-script feedback tests cover settings toggles but not these actions. P1 holds because losing the ordinary inbox decision path is a user-visible failure on a main path. A complete fix must add real forms and form-aware result handling, especially for Restore, Re-test, and skill-run routes that currently return only JSON.

## P4-02: A failed pairing puts the live pairing code in the URL

- Verdict: confirmed
- Severity: P1 holds
- Methods: reading, running, mutation

### Reading

`_peers_refuse` builds `/peers?notice=...`, then appends the typed address and pairing code at `src/agentdesk/server/peers_api.py:395-410`. `_peers_pair` passes `keep_code` for missing fields, malformed addresses, and every `PeerClientError` at lines 441-466. The peers GET handler reads that query value back into the form at `src/agentdesk/server/app.py:1621-1629`, and `src/agentdesk/server/peers_view.py:27-44` renders it in the code input. Thus the redirect itself carries the credential, independently of whether the form retains it.

The generation form has the second leak: `src/agentdesk/server/peers_api.py:412-431` puts the newly minted code inside the `notice` query value. `clearNoticeFromAddress` deletes only `notice` and `notice_kind` at `src/agentdesk/server/pages.py:579-592`, so a refusal's separate `code` parameter remains in the address and subsequent reloads. With script off, the generated-code notice also remains in the URL. With script on, the initial GET query has already reached any request logger before browser cleanup.

The credential interpretation is explicit: `src/agentdesk/peers/store.py:97-105` says secrecy comes from the pairing code and derives the channel token from it. `src/agentdesk/peers/store.py:177-188` creates a code with a ten-minute life, and lines 201-215 redeem it by deriving the same token.

### Running

The closest test file was run from the read-only worktree with the same temporary data, template, and home isolation:

```text
python -m pytest -q -p no:cacheprovider tests/test_ui_feedback.py
47 passed in 21.34s
```

`tests/test_ui_feedback.py:429-437` checks the 303 and that the address and code remain in the rendered inputs. It never checks whether `Location` or the final URL contains the secret.

### Mutation

In temporary worktree `.scratch/wave-2026-11-25/mutation/P4-02`, I deleted only `src/agentdesk/server/peers_api.py:407-408`, the two lines that append `keep_code` to the refusal redirect. This removed the refusal-path URL exposure. The test noticed the loss of its separate retention behavior:

```text
1 failed, 46 passed in 21.33s
FAILED tests/test_ui_feedback.py::test_a_peer_pairing_refusal_keeps_the_typed_address_and_code
```

The failing assertion is `tests/test_ui_feedback.py:436`, `assert 'value="ABCD2345"' in page`. No assertion failed about URL secrecy. The mutation therefore does not refute the finding; it shows that the current test enshrines URL-based retention and would require a safe server-side draft mechanism or direct re-render to preserve that behavior without the leak.

### Severity

P1 holds. This is a short-lived credential exposed on a pairing failure or generation path, with possible history and query-log exposure, but the evidence does not show actual redemption, data loss, or a stopped main path. It also meets the P1 definition of a test passing while the named security behavior is broken. A complete fix must cover both refusal and generation, not only remove `code` while leaving the generated secret in `notice`.

## P4-03: Workbook tracker selection never supplies the tracker figures to the deck

- Verdict: confirmed
- Severity: P1 holds
- Methods: reading, running, mutation

### Reading

The presentation form checks Workbook tracker by default at `src/agentdesk/server/agents_view.py:140-145`. `_presentation_sources` maps `use_workbook` to `excel-report` at `src/agentdesk/server/app.py:3497-3518`, and the run passes `_excel_status()` into `gather` at lines 3180-3185. `_excel_status` returns the watcher's status dict unchanged at lines 3536-3544.

The real watcher shape does not match what `gather` extracts. `Delta.added` contains actual worksheet row lists (`src/agentdesk/excel/core.py:47-75` and `88-104`), and `Delta.to_json` serializes those lists unchanged. The watcher also returns bounded `examples` and a header-plus-rows `grid` at `src/agentdesk/excel/watcher.py:252-261` and `286-297`.

The workbook branch of `gather` reads only the file name, the number of added rows, and values from added rows that are dictionaries with `region` and `value` keys (`src/agentdesk/presentations/pipeline.py:65-79`). It never reads `grid`, `examples`, `rowsSeen`, or configured tracker bindings. A real list-shaped added row therefore contributes only to `added {len(added)}`. The resulting source text is what `fill_prompt` sends to the model (`src/agentdesk/presentations/pipeline.py:157-177`), and `guard_numbers` replaces a deck number when no cited source contains it (`src/agentdesk/presentations/pipeline.py:85-106`). A checked workbook can consequently contribute its file name and row count without contributing the selected tracker's figures.

The closest test is `tests/test_presentation_pipeline.py`. Its workbook test at lines 277-303 supplies only `configured` and `path`, then checks that the file name appears and the full path does not. It supplies no delta rows or grid and asserts no figure in a fill prompt or deck notes. The pack test's scripted model returns generic text (`tests/test_presentation_packs.py:35-65`), and its boots use an unconfigured inert workbook (`tests/server_harness.py:151-158`), so its configured run at `tests/test_presentation_packs.py:239-267` also cannot catch this.

### Running

Both single files were run from the read-only worktree with temporary data, template, and home isolation:

```text
python -m pytest -q -p no:cacheprovider tests/test_presentation_pipeline.py
13 passed in 19.78s

python -m pytest -q -p no:cacheprovider tests/test_presentation_packs.py
13 passed in 5.08s
```

### Mutation

In temporary worktree `.scratch/wave-2026-11-25/mutation/P4-03`, I deleted `src/agentdesk/presentations/pipeline.py:73-74`, the two lines that append `added {len(added)}` to the workbook source. This removed the only numeric workbook datum that the real list-shaped delta path currently contributes. Neither test noticed:

```text
python -m pytest -q -p no:cacheprovider tests/test_presentation_pipeline.py
13 passed in 21.21s

python -m pytest -q -p no:cacheprovider tests/test_presentation_packs.py
13 passed in 6.71s
```

The passing mutation confirms that the closest pipeline test checks workbook naming and path privacy, not figure propagation, and that the pack suite has no effective workbook-figure coverage.

### Severity

P1 holds. Workbook tracker is selected by default on the main presentation path, yet a normally configured workbook's figures do not reach the model or deck. That is a user-visible wrong result on a main path and a test suite that stays green while the named behavior is broken. The evidence does not show data loss or a stopped path, so P0 is not supported.
