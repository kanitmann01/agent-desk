# P4 review: server and Python tests

## 1. Coverage

- Worktree: `D:/20-projects/Personal Agents/.worktrees/027-merge`
- Confirmed head: `3540b9f` with `git -C "D:/20-projects/Personal Agents/.worktrees/027-merge" rev-parse --short HEAD`.
- Range reviewed: `f31582a..3540b9f`.
- Partition size: 64 changed files.
- Disposition: 52 reviewed source/test files, 12 generated SPA files, 0 documentation files.
- `P4.diff` contains the complete non-generated partition diff, 7,477 lines, read in full. Generated files are listed separately below and were checked only for source consistency.
- P1 exclusions: `src/agentdesk/server/dashboard_state.py` and `tests/test_server_dashboard_api.py`.
- No odd-fit files. The instrument tests are P4 because the brief assigns every changed file under `tests/` to P4. `tests/test_ui_feedback_review.py` also contains cross-partition assertions about the P1 dashboard payload; the file remains P4 because its subject is the server feedback round.

### Reviewed files, 52

#### Source, 25

- `src/agentdesk/marketplace/api.py`
- `src/agentdesk/marketplace/catalog.py`
- `src/agentdesk/plugins/cards.py`
- `src/agentdesk/plugins/execute.py`
- `src/agentdesk/plugins/html.py`
- `src/agentdesk/plugins/runtime.py`
- `src/agentdesk/plugins/sources.py`
- `src/agentdesk/server/agents_view.py`
- `src/agentdesk/server/app.py`
- `src/agentdesk/server/audit_view.py`
- `src/agentdesk/server/capabilities_view.py`
- `src/agentdesk/server/commitments.py`
- `src/agentdesk/server/graph_view.py`
- `src/agentdesk/server/inbox_view.py`
- `src/agentdesk/server/mail_view.py`
- `src/agentdesk/server/memory_api.py`
- `src/agentdesk/server/memory_view.py`
- `src/agentdesk/server/pages.py`
- `src/agentdesk/server/peers_api.py`
- `src/agentdesk/server/peers_view.py`
- `src/agentdesk/server/research.py`
- `src/agentdesk/server/sales.py`
- `src/agentdesk/server/settings_view.py`
- `src/agentdesk/server/touches.py`
- `src/agentdesk/server/wizard_view.py`

#### Tests, 27

- `tests/test_calendar_paths.py`
- `tests/test_ci_local_tool.py`
- `tests/test_feedback_walkthrough.py`
- `tests/test_file_selection_chain.py`
- `tests/test_layout_audit.py`
- `tests/test_marketplace_fresh_desk.py`
- `tests/test_memory_retain.py`
- `tests/test_plugin_update_modes.py`
- `tests/test_presentation_packs.py`
- `tests/test_server_agents.py`
- `tests/test_server_capabilities.py`
- `tests/test_server_job_routing.py`
- `tests/test_server_keys_api.py`
- `tests/test_server_keys_health.py`
- `tests/test_server_ledger_api.py`
- `tests/test_server_mail_api.py`
- `tests/test_server_memory_api.py`
- `tests/test_server_memory_encrypt.py`
- `tests/test_server_memory_forget_all.py`
- `tests/test_server_memory_graph_api.py`
- `tests/test_server_memory_reflect.py`
- `tests/test_server_recommendations.py`
- `tests/test_server_settings_api.py`
- `tests/test_server_wizard.py`
- `tests/test_ui_feedback.py`
- `tests/test_ui_feedback_review.py`
- `tests/test_ui_text_fit.py`

### Generated files, 12

- `src/agentdesk/server/static/spa/assets/index-B08QCR_p.css` (deleted)
- `src/agentdesk/server/static/spa/assets/index-BJj0XD89.js` (deleted)
- `src/agentdesk/server/static/spa/assets/index-Bf3o3Xx2.js`
- `src/agentdesk/server/static/spa/assets/index-D8rifP0q.css`
- `src/agentdesk/server/static/spa/assets/memory-graph-BGjeuZe0.js`
- `src/agentdesk/server/static/spa/assets/memory-graph.css`
- `src/agentdesk/server/static/spa/assets/memory-graph.js`
- `src/agentdesk/server/static/spa/assets/memory-loop.css`
- `src/agentdesk/server/static/spa/assets/memory-loop.js`
- `src/agentdesk/server/static/spa/assets/useBusy-BnHbzNUF.js` (renamed from `api-Df6KFqRi.js`)
- `src/agentdesk/server/static/spa/favicon.svg`
- `src/agentdesk/server/static/spa/index.html`

Generated consistency check: `index.html` references the new hashed main JS/CSS, the `useBusy` chunk, and the new favicon. The main bundle contains the merged face name and `useBusy`; both memory entry points reference the new memory chunk. The latest bundle commit is `986a558`, `build(spa): rebuild the bundle with the agent face`, after the face source commit. No source/bundle mismatch was found by inspection. The bundle was not rebuilt during this read-only review.

## 2. Findings

### P4-01, P1: Primary server actions remain inert with JavaScript off

- **File:** `src/agentdesk/server/inbox_view.py`
- **Line:** 61, also 123 and 185
- **Title:** Primary server actions remain inert with JavaScript off
- **What:** The feedback wave promises that every server page works without script, but the inbox's Accept, Dismiss and Restore controls are bare buttons whose only behavior is attached by `APP_JS`. Sales and calendar Re-test controls and the dashboard skill-run control have the same shape. A user with JavaScript disabled can read the pages and submit the forms that were already forms, but cannot perform these main actions.
- **Why:** Spec 027 user story 50 requires every server page to work with script off, and F7 says the server pages keep their normal navigation while every form still works. Losing the main inbox decision path is a user-visible failure on a main path, not a cosmetic degradation.
- **Evidence:** By reading, `src/agentdesk/server/inbox_view.py:61` renders `<button class='btn btn-primary' data-accept='...'>`, line 123 renders Dismiss the same way, and line 185 renders Restore the same way. None is inside a form. Their POSTs exist only in `src/agentdesk/server/pages.py:1123-1133`, inside click listeners installed by `APP_JS`. The handlers already support form posts: `src/agentdesk/server/app.py:2434-2438` and `5820` dispatch accept, dismiss and restore, and the changed handlers return notices for `_is_form_submit()`. By running:

  ```text
  cd "D:/20-projects/Personal Agents/.worktrees/027-merge"
  python -m pytest -q tests/test_ui_feedback.py
  47 passed in 21.37s
  ```

  Its no-script section at `tests/test_ui_feedback.py:453-497` exercises settings toggles only, so it stays green while inbox decisions are inert without script.
- **Fix:** Render Accept, Dismiss and Restore as plain POST forms to their existing routes, then let `APP_JS` enhance those forms instead of owning the only action path. Do the same for Re-test and skill-run controls that already have POST routes. Add no-script tests that submit each form directly and assert the store change and notice, rather than testing only settings toggles.
- **Confidence:** high.

### P4-02, P1: A failed pairing puts the live pairing code in the URL

- **File:** `src/agentdesk/server/peers_api.py`
- **Line:** 404-408
- **Title:** A failed pairing puts the live pairing code in the URL
- **What:** When manual pairing fails, `_peers_refuse` appends the typed pairing code to the redirect query. The browser lands on `/peers?...&code=...`, so the credential enters browser history, the address bar, and any request logging that records query strings. `clearNoticeFromAddress` removes only `notice` and `notice_kind`, leaving the code in place. The older code-generation form path also puts a newly minted code in the notice query, so a complete fix must cover both creation and refusal.
- **Why:** The pairing code is the secret from which both desks derive the channel token. `src/agentdesk/peers/store.py:97-105` states that secrecy comes from the code. A failed connection before redemption can leave the code live for up to ten minutes, so the redirect can expose a usable credential on a failure path.
- **Evidence:** By reading, `src/agentdesk/server/peers_api.py:404-408` builds the notice query and then appends the code:

  ```python
  target = f"/peers?notice={quote(message)}"
  if keep_address:
      target += "&address=" + quote(keep_address)
  if keep_code:
      target += "&code=" + quote(keep_code)
  ```

  The pair handler passes the code on blank input, bad address, and every `PeerClientError` at lines 445-466. The code-generation form path at lines 425-431 likewise embeds `out['code']` in the notice query. `src/agentdesk/peers/store.py:215` computes `token = derive_token(code)`, and lines 177-188 give the code a ten-minute life. `src/agentdesk/server/pages.py:579-584` deletes only the two notice parameters, and only when script runs. `tests/test_ui_feedback.py:429-436` confirms the refused value is retained but never asserts that the redirect URL is free of the code.
- **Fix:** Keep the address and code out of the query on both code generation and pairing refusal. Re-render the peers page directly after a form refusal, or keep the draft in a short-lived server-side session keyed by a non-secret token. If a redirect is retained, carry only a draft id. Update the tests to assert that neither `Location` nor the final URL contains a pairing code while the page still shows it.
- **Confidence:** high.

### P4-03, P1: Workbook tracker selection never supplies the tracker figures to the deck

- **File:** `src/agentdesk/server/agents_view.py`
- **Line:** 143
- **Title:** Workbook tracker selection never supplies the tracker figures to the deck
- **What:** The presentation form selects Workbook tracker by default, but the server passes only `ExcelWatch.status()` to the presentation gather step. That status contains a delta whose added rows are lists and a bounded grid, while `gather` extracts values only from dict rows. As a result the source sent to the model contains the workbook file name and an added-row count, not the tracker's current total, change, goal, pace, or row values. The deck cannot use the figures the user selected.
- **Why:** The selected source is presented as the Workbook tracker, and the presentation pipeline replaces numbers not backed by a cited source with `[data needed]`. A normal configured workbook therefore produces a deck without its headline figures even though the source box is checked.
- **Evidence:** By reading, `src/agentdesk/server/agents_view.py:143` renders the checked Workbook tracker box. `src/agentdesk/server/app.py:3536-3544` returns `excel.status()`, and lines 3181-3185 pass it to `gather`. `src/agentdesk/excel/core.py:88-93` stores actual row lists in `Delta.added`, and lines 65-75 serialize those lists unchanged. `src/agentdesk/presentations/pipeline.py:65-79` includes only the file name, `added {len(added)}`, and values from rows that are dicts:

  ```python
  for row in added:
      if isinstance(row, dict) and row.get("value") is not None:
          bits.append(f"{row.get('region', '')} {row.get('value')}")
  ```

  The dict branch cannot run for the real `Delta` shape. The status also exposes `grid` and `examples` at `src/agentdesk/excel/watcher.py:293-294`, but `gather` does not read either. By running:

  ```text
  cd "D:/20-projects/Personal Agents/.worktrees/027-merge"
  python -m pytest -q tests/test_presentation_packs.py
  13 passed in 8.24s
  ```

  None of those tests asserts that a workbook figure reaches the prompt or deck.
- **Fix:** Build a bounded workbook source from the status's header and grid or from the tracker's configured bindings, including the current figure, change, goal and pace when present. Keep the full path out, preserve the existing number guard, and add a pipeline test with a real list-shaped delta that asserts the exact figure reaches both the fill prompt and the written deck notes.
- **Confidence:** high.

### P4-04, P2: Reset to automatic discovery cannot work while the empty calendar pin is active

- **File:** `src/agentdesk/server/pages.py`
- **Line:** 1884-1892
- **Title:** Reset to automatic discovery cannot work while the empty calendar pin is active
- **What:** The new no-calendar walkthrough state offers Reset to automatic discovery. With `AGENTDESK_CALENDAR_FILE` set to the documented empty demo pin, the reset handler clears only the stored explicit path. The environment pin still makes the candidate list empty, so the re-test remains off and the page continues to say reading is off.
- **Why:** The control promises a recovery that cannot occur in the exact boot state for which the new page was added. The user has a workaround, choosing or uploading an explicit file, but the offered reset is a dead end.
- **Evidence:** By reading, `src/agentdesk/server/pages.py:1884-1892` renders the reset button when `calendar_off` is true. `src/agentdesk/calendar/watcher.py:86-89` returns `[]` whenever the environment variable exists and is empty. `src/agentdesk/server/app.py:2383-2392` implements reset as `calendar.clear_explicit_path(); calendar.retest()`. `src/agentdesk/calendar/watcher.py:245-254` then falls through to the adapter, which still uses `default_calendar_candidates()` and therefore still returns no file. By running:

  ```text
  cd "D:/20-projects/Personal Agents/.worktrees/027-merge"
  python -m pytest -q tests/test_calendar_paths.py
  16 passed in 0.69s
  ```

  The new route test at lines 218-239 checks the 200 page and off sentence but does not press reset.
- **Fix:** When the empty environment pin is the cause, do not offer automatic reset. Explain that the boot is pinned off and offer Pick a file, Use this path, or Upload this file. If reset must be offered, define and test a server-supported way to override the pin for this desk rather than clearing only the stored path.
- **Confidence:** high.

### P4-05, P2: Invalid presentation form selections return raw JSON

- **File:** `src/agentdesk/server/app.py`
- **Line:** 3165-3179
- **Title:** Invalid presentation form selections return raw JSON
- **What:** The presentation handler now re-renders the agents page for blank and overlong topics, but an unknown template, invalid variant, missing recipe, or missing shell still calls `_send_json(400, ...)` even when the request is a browser form post.
- **Why:** A stale form, for example after a template pack is removed or renamed between page load and submit, drops the user on a raw JSON error page and loses the typed topic. This is a rare path, but it violates F5's named-cause, typed-value-preserving failure behavior.
- **Evidence:** By reading, `src/agentdesk/server/app.py:3165-3171` and `3174-3179` unconditionally call `_send_json`. The surrounding form branches at lines 3109-3145 use `_is_form_submit()` and `_send_agents_page(...)`, showing the intended form behavior. The rendered controls at `src/agentdesk/server/agents_view.py:87-109` and `132-139` normally constrain the values, so the JSON path is not reachable by an ordinary unchanged form, but it is reachable by a stale or crafted form.
- **Fix:** For `_is_form_submit()`, re-render the agents page with an alert and the typed topic, and retain the selected template, variant and recipe where possible. Keep the JSON 400 for API callers. Add a form-post test with a missing template and a missing shell.
- **Confidence:** high.

### P4-06, P3: New server motion exceeds the colour-and-background-only rule

- **File:** `src/agentdesk/server/pages.py`
- **Line:** 322, also 290-291
- **Title:** New server motion exceeds the colour-and-background-only rule
- **What:** The new skip link animates its `top` position. The new busy dot animates opacity as well as background color. Both depart from the written motion contract, whose only shape-motion exception is the agent face.
- **Why:** `docs/design-language.md:199-200` allows 120 ms motion on color and background only. The F1 rule at lines 159-165 allows the pending dot to pulse in colour only. The server changes add positional motion and opacity motion without an exception.
- **Evidence:** By reading, `src/agentdesk/server/pages.py:322` contains `.skip-link{...transition:top var(--dur) ease}` and line 323 changes `top` from `-56px` to `8px`. Lines 290-291 define `@keyframes busy-dot` with `opacity:.55` at the endpoints and `opacity:1` at the midpoint. `docs/design-language.md:199-200` states `Motion is 120ms on color and background only`, and line 165 states `A dot may pulse in colour only`. The new tests assert that the animation exists but do not assert these properties.
- **Fix:** Make the skip link appear instantly on focus, or transition only color/background. Keep the busy dot's opacity fixed and animate only its background color. Extend the CSS contract test to reject positional or opacity transitions outside the face exception.
- **Confidence:** high.

## 3. Tests that can fail

| Test file | Behavior whose removal would make it fail, or finding id |
| --- | --- |
| `tests/test_calendar_paths.py` | Empty calendar pin yields no hint and a 200 walkthrough with the honest off sentence. |
| `tests/test_ci_local_tool.py` | Pytest gate names failed tests, caps the list, and preserves a crash summary when no test line exists. |
| `tests/test_feedback_walkthrough.py` | Seven-action plan, per-rule verdicts, result readiness, metric spelling, manifest verdict, and relative photo paths. |
| `tests/test_file_selection_chain.py` | Wizard-to-live-card chain remains followable and the approved page does not expose a raw JSON status object. |
| `tests/test_layout_audit.py` | Matrix validation, coverage exits, fixture loading, pending verdicts, signatures, theme pinning, and overflow fixture shape. |
| `tests/test_marketplace_fresh_desk.py` | Every bundled plugin installs after the documented T2 policy and host allowlist are set. |
| `tests/test_memory_retain.py` | A form retain lands in the inbox and stores the visible conversation draft. |
| `tests/test_plugin_update_modes.py` | Update modes produce different reads, and the mtime tick prevents a same-tick write from looking unchanged. |
| `tests/test_presentation_packs.py` | Picker is disabled without an endpoint, a configured run records its pack choices, and a no-JS post records the choice. Workbook figure propagation is not covered; see P4-03. |
| `tests/test_server_agents.py` | Agent run and feedback form posts redirect to the agents path and persist their records. |
| `tests/test_server_capabilities.py` | Re-test runs exactly one gate and refreshes its cached result. |
| `tests/test_server_job_routing.py` | No-JS delete uses the warning and confirmation path and keeps the settings connections anchor. |
| `tests/test_server_keys_api.py` | Form save/edit and no-JS connection management work and return to the connections card. |
| `tests/test_server_keys_health.py` | Form test and deeper check work without script and update connection health. |
| `tests/test_server_ledger_api.py` | A crafted `return_to` cannot inject a response header. |
| `tests/test_server_mail_api.py` | Mail folder form save returns to settings and persists the folder. |
| `tests/test_server_memory_api.py` | Add and sweep form posts return to memory and change the intended facts. |
| `tests/test_server_memory_encrypt.py` | Confirmed encryption converts the bank, creates the key marker, and reports success. |
| `tests/test_server_memory_forget_all.py` | Exact confirmation removes facts and derived state, while an empty bank and sealed key remain safe. |
| `tests/test_server_memory_graph_api.py` | The graph island mounts on its own wide page and the memory page links to it. |
| `tests/test_server_memory_reflect.py` | A form reflect lands its observation card in the inbox. |
| `tests/test_server_recommendations.py` | Not now dismisses a recommendation and it stays gone across restart. |
| `tests/test_server_settings_api.py` | Presentation timeout and extra allowed hosts persist through form posts. |
| `tests/test_server_wizard.py` | Approve redirects to the approved screen, avoids raw JSON, and refuses a second install. |
| `tests/test_ui_feedback.py` | Busy markers, model-form regions, result notices, typed validation failures, and settings no-JS toggles. **Flagged by P4-01:** the file's script-off claim is broader than its tests, which omit inbox decisions, re-tests and skill-run controls. |
| `tests/test_ui_feedback_review.py` | Notice escaping and roles, setting forms, timer cleanup, duplicate-submit guard, watchdogs, success-only reloads, network facts, capabilities, card filtering, rail titles, and notice redirect placement. |
| `tests/test_ui_text_fit.py` | R1-R7 server CSS and markup contracts, table wrappers, timeline parity, re-test gating, and honest no-widget/source language. |

### Targeted test runs

All were run from the review worktree, one file at a time. The harness uses temporary profile/data/plugin/deck directories and an inert keychain.

| Command | Result |
| --- | --- |
| `python -m pytest -q tests/test_ui_feedback_review.py` | 38 passed in 15.96s |
| `python -m pytest -q tests/test_ui_feedback.py` | 47 passed in 21.37s |
| `python -m pytest -q tests/test_ui_text_fit.py` | 70 passed in 4.05s |
| `python -m pytest -q tests/test_calendar_paths.py` | 16 passed in 0.69s |
| `python -m pytest -q tests/test_presentation_packs.py` | 13 passed in 8.24s |
| `python -m pytest -q tests/test_feedback_walkthrough.py` | 26 passed in 0.18s |
| `python -m pytest -q tests/test_layout_audit.py` | 29 passed in 0.25s |

Total: 239 targeted tests passed. No whole gate, walk, layout audit, server start, or real data-folder/keychain access was performed.

## 4. Checked and found correct

- **Escaping:** `status_line` escapes notice text and allow-lists its role. Memory notices, peer pairing fields, assistant questions, agent briefs, mail drafts, timeout values, and wizard answers are escaped before rendering. The crafted `notice_kind` test passes and the role cannot inject markup.
- **Redirect safety:** `_form_return_to` accepts only local settings paths. `_send_notice_redirect` places the query before the fragment. Tests cover external and scheme-based return targets and header injection.
- **Plugin honesty:** `sourceReason` preserves the stable `no-transport` identity through dashboard filtering. Setup cards stay. No-widget and never-run cards no longer claim a current check time. The no-transport and no-widget reader sentences are applied on both runner paths.
- **Marketplace facts:** `deskNetwork` is derived from the live runner rather than hard-coded. Bundled catalog entries gain capability facts from their own manifests. Permission serialization drops metadata and false/empty grants for the shipped schema.
- **Server feedback mechanics:** The delegated capture submit handler, synchronous double-submit guard, 100 ms delay, 10 second phase line, three-minute watchdog, `pageshow` restore, and success-only fetch reloads are present. Reduced motion freezes the busy dot. The property-level motion defects are P4-06.
- **No-JS forms that were converted:** Settings toggles, including Check every, are real forms and flip their settings without script. Blank fact and brief failures re-render with causes. Invalid timeout and peer pairing refusals retain typed values, subject to the pairing-code exposure in P4-02.
- **Calendar 500 fix:** `default_calendar_hint` returns `None` for an empty candidate list, and the walkthrough answers 200 with the off sentence. The reset dead end is P4-04.
- **Text fit:** Server roots and text-bearing rows have the specified wrap/shrink rules. Compared values, stamps, buttons and mono cells stay whole. Server tables have local scrollers. The memory graph island uses the wide shell. Plugin tables and timelines have the new wrappers and columns.
- **Generated SPA:** New hashed assets, favicon, face marker and `useBusy` chunk are consistent with the merged source by inspection. No generated-content review was performed beyond that consistency check.
- **Known starting points in other partitions:** The agent-name guard, missing modal faces, missing background-loop signal, rail differences, evidence/ticket claims, and phone-width audit gap belong to P1, P2, P3, P5 or P6 and were not re-reviewed here. The workbook tracker starting point is confirmed as P4-03.
