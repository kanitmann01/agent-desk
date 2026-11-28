DIFFERENCES FOUND

## Audit basis

Checked 2026-11-26 against `f31582a2591e1c860ec5aadf5e0ff3878d77cc49`, the runbooks' planned instrument head `954a31b868b2d82fb3f75ccc5df7744534e8b01a`, and current `origin/main` `e53c5919fd717fce8867b8127f85285bb1e912e7`. Pull requests 348 and 352 are now merged. The face branch is `4eee00b2613e497dca1c5d34c3cb551dd5f00cc6`, and its `tools/face_walkthrough.py` is byte-identical to the copy on current main.

No walk, instrument, selftest, gate, build, install, worktree creation, or file copy was run. Repository reads and the required report write were the only changes.

## Problems and exact corrections

### 1. Both source pins are stale, and the AFTER face overlay is obsolete

As written:

- `runbook/walk-before.md:6`: `Instrument source: remote main at 954a31b...`
- `runbook/walk-before.md:43`: `MAIN="954a31b868b2d82fb3f75ccc5df7744534e8b01a"`
- `runbook/walk-before.md:7,44,50`: face reference `4b7398aaaebecf1ba34aa32b46240c6e03896376`
- `runbook/walk-after.md:5,48,54,114,380`: audited main and recorded commit `954a31b868b2d82fb3f75ccc5df7744534e8b01a`
- `runbook/walk-after.md:6,49,55,258`: face reference `4b7398aaaebecf1ba34aa32b46240c6e03896376`
- `runbook/walk-after.md:47`: `AFTER="D:/20-projects/Personal Agents/.worktrees/audit-after-main-954a31b"`
- `runbook/walk-after.md:252-265`: copy `tools/face_walkthrough.py` from the unmerged branch and require `?? tools/face_walkthrough.py`

Should be:

- Set `MAIN="e53c5919fd717fce8867b8127f85285bb1e912e7"` in both runbooks and update every narrative, guard, recorded-commit, and hard-stop reference to that hash.
- Rename the AFTER worktree path to `D:/20-projects/Personal Agents/.worktrees/audit-after-main-e53c5919`.
- Remove the BEFORE face-branch guard because BEFORE does not use the face instrument.
- Remove the AFTER face overlay section. Current main already contains the instrument, so the overlay would modify a tracked file and the required untracked-status test would fail. Verify `tools/face_walkthrough.py` is tracked and the worktree is clean instead.
- Replace `runbook/walk-after.md:381` with a clean-worktree check before command 6.

Code and repository evidence:

- `origin/main:tools/face_walkthrough.py:1750-1797` is the parser and entry point now on main.
- `git diff 4b7398a e53c5919 -- tools/face_walkthrough.py` is empty.
- `origin/main:tools/layout_audit.py:2575-2578` and `origin/main:tools/layout_fixtures/long-values.api.json` contain the PR 348 sample-name update, so even the BEFORE copied blobs must come from `e53c5919`, not `954a31b`.

### 2. The four-second pending command does not measure a four-second model delay

As written:

- `runbook/walk-after.md:210`: `--mock-delay-ms 4000 is passed to the loopback mock, but a held pending request may never wait for a mock answer.`

Should be:

- State that the command cannot satisfy issue 326's delayed-model evidence as written. Every activated non-GET request is held before it reaches the desk, so the desk cannot call the mock endpoint. Passing `--mock-delay-ms 4000` configures a delay that the pending path does not exercise.
- Stop and replan the slow pass. The smallest viable fix is in `tools/layout_audit.py`, not the runbook: let only the deliberate model-backed request reach the isolated desk and its loopback mock, while continuing to hold capability retests and unrelated mutations. A runbook-only option change cannot fix this.

Code evidence:

- `origin/main:tools/layout_audit.py:3324-3332` holds every non-GET request and never continues it.
- `origin/main:tools/layout_audit.py:2089-2098` only sets `DELAY_MS` on the in-process mock.
- `origin/main:tools/mock_endpoint.py:327-334,384-414` applies the delay only after a POST reaches the mock.
- `origin/main:tools/layout_audit.py:2315-2342` confirms the general guard's holding behavior.

### 3. BEFORE does not explicitly preserve every possible pending verdict as a zero row

As written:

- `runbook/walk-before.md:164`: `every pending verdict count`
- `runbook/walk-after.md:349-350`: `native-validation, if present` and `error, if present`

Should be:

- In BEFORE, require all nine emitted verdict categories in the comparison record: `skipped`, `native-dialog`, `native-validation`, `dead`, `instant`, `meets`, `disabled-only`, `silent`, and `error`. Enter `0` when a category is absent.
- In AFTER, remove `if present` and fill those same nine rows, including zero, so the two runs compare like for like.

Code evidence:

- `origin/main:tools/layout_audit.py:3133-3187` emits the seven issue verdicts plus `native-validation`.
- `origin/main:tools/layout_audit.py:3212-3218,3258-3260,3278-3282,3363-3367,3455-3458` emits `skipped` and `error`.
- `origin/main:tools/layout_audit.py:4189-4195,4384-4388` counts only verdicts that occur and writes only those rows. An absent category therefore has no summary row unless the runbook supplies the zero itself.

### 4. Face exit 2 documentation promises artifacts that early failures do not create

As written:

- `runbook/walk-after.md:327`: `Exit 2: ... or options are invalid. The tool prints ... writes the incomplete manifest and photograph list, then prints the metric and FACE-WALK FAIL ... failed.`

Should be:

- Split exit 2 into two cases. Missing Playwright or invalid planned options prints `layout_audit needs Playwright: ...` or `invalid face walk options: ...` and returns 2 before creating a run folder, manifest, photograph list, metric, or verdict line. A startup failure after the run folder is created prints `face walkthrough failed to start: ...`, writes `manifest.json` and `photographs.json`, then prints `METRIC` and `FACE-WALK FAIL`.
- Treat an early exit 2 as a stop with no instrument artifacts to inspect.

Code evidence:

- `origin/main:tools/face_walkthrough.py:1768-1776` returns before `run_dir.mkdir`.
- `origin/main:tools/face_walkthrough.py:1777-1797` creates and writes artifacts only after option validation.

### 5. Hard stops omit feedback exit 1 and face exit 1

As written:

- `runbook/walk-after.md:385`: `Feedback exits 2, or a completed run lacks any of the seven actions or any of the 21 required photographs.`
- `runbook/walk-after.md:386`: `Face exits 2, leaves missing>0, or cannot produce the manifest, photograph list or planned photographs.`

Should be:

- `Feedback exits 1 or 2, reports not-met>0, or a completed run lacks any of the seven actions or any of the 21 required photographs. Stop and report.`
- `Face exits 1 or 2, prints FACE-WALK FAIL, leaves missing>0, or cannot produce the manifest, photograph list or planned photographs. Stop and report.`

Code evidence:

- `origin/main:tools/feedback_walkthrough.py:789-795` prints per-action results and `METRIC`, then returns 1 when any action is `not met`.
- `origin/main:tools/face_walkthrough.py:670-686` prints `FACE-WALK FAIL` and returns 1 for failed or missing captures.

### 6. Layout acceptance counts need exact `findings.json` filters

As written:

- `runbook/walk-after.md:154`: `real and long strings need zero findings outside the 11px class and zero broken words; every non-11px tripled-string finding must be a table cell inside its own scroller.`

Should be:

- Name `findings.json` as the row-level source. For normal rows (`stress:false`), exclude `kind:"runtime"` and `kind:"tiny-type"`; the remaining count must be 0 for real and long strings. The count of `kind:"broken-word"` must also be 0.
- For tripled rows (`stress:true`), exclude `kind:"runtime"` and `kind:"tiny-type"`. Inspect every remaining row's `selector`, `container`, `offender`, metrics, crop, and page photograph. Accept it only when the offending content is a table cell inside its own horizontal scroller; every other row is a finding. Record the accepted exception count and every rejected row.
- Keep the historical `40 at 2d00540` only as a comparison, not as the new expected count.

Code evidence:

- `origin/main:tools/layout_audit.py:574-590` defines the finding fields, including `kind`, `stress`, `selector`, `container`, `metrics`, and `rect`.
- `origin/main:tools/layout_audit.py:1202-1215` defines the tiny-type class as `tiny-type` with font size below 11 px.
- `origin/main:tools/layout_audit.py:1135-1196` defines `broken-word` and its evidence fields.
- `origin/main:tools/layout_audit.py:501-516,710-719,787-829` defines and applies the horizontal-scroller exception.
- `origin/main:tools/layout_audit.py:3474-3485` attaches `stress`, condition, width, theme, kind, severity, and metrics to each row.

## Four orchestration answers

(a) The slow run does not measure the four-second model delay. Its pending guard holds the triggering request before the desk can call the delayed mock. The smallest fix is an instrument change that continues only the deliberate model-backed request to the isolated desk while holding capability retests and unrelated mutations.

(b) Faceless-dialog photographs are the right failure evidence, not acceptance evidence, for "the two dialogs that hold the face." They prove the dialogs opened without a mounted face. `FACE-WALK PASS WITH ... SURFACES WITHOUT A FACE` cannot be treated as satisfying a criterion that requires a face in each dialog.

(c) BEFORE says "every pending verdict count," so it does not intentionally exclude `native-validation` or `error`. Strictly, though, it does not record every possible verdict as an explicit row: absent categories produce no summary row. Require all nine categories with zero for absent verdicts in both runs.

(d) The seven copied BEFORE files and their main sources are `tools/layout_audit.py`, `tools/mock_endpoint.py`, `tools/layout_fixtures/long-values.api.json`, `tools/layout_fixtures/overflow-widget/manifest.json`, `tools/layout_fixtures/overflow-widget/manual.json`, `tools/layout_fixtures/overflow-widget/sample.json`, and `tools/layout_fixtures/overflow-widget/widget.ui.json`, each from the same path on `e53c5919`. All `agentdesk` names used by the fixed instrument exist at `f31582a`, and `create_server(..., gate_runners=...)` is compatible there.

## BEFORE compatibility detail

Direct imports and names used from `agentdesk`:

- `GATES`: `f31582a:src/agentdesk/capabilities.py:48`
- `GateResult`: `f31582a:src/agentdesk/probe/core.py:74`
- `PASS`, `FAIL`, `UNKNOWN`: `f31582a:src/agentdesk/probe/core.py:12-14`
- `KeychainSecrets`: `f31582a:src/agentdesk/keys/secrets.py:50`
- `server_app.create_server`: `f31582a:src/agentdesk/server/app.py:6938`
- `gate_runners` keyword: `f31582a:src/agentdesk/server/app.py:6962`
- `keychain` and `announce_port` keywords: `f31582a:src/agentdesk/server/app.py:6971,6975`
- `server_app.SPA_DIR`, imported from `server.core.SPA_DIR`: `f31582a:src/agentdesk/server/app.py:240`; `f31582a:src/agentdesk/server/core.py:14`
- `server.settings.set("agent_loop_minutes", 0)`: `f31582a:src/agentdesk/server/app.py:838`; `f31582a:src/agentdesk/settings.py:100,179`
- `server.sessions.bootstrap_token()`: `f31582a:src/agentdesk/server/app.py:802`; `f31582a:src/agentdesk/server/auth.py:52`
- `demo_data.sample_workbook_path()`: `f31582a:src/agentdesk/server/demo_data.py:569`
- `server.capabilities_cache.save_result`: `f31582a:src/agentdesk/server/app.py:861`; `f31582a:src/agentdesk/capabilities.py:98`
- Server attributes used for clock pinning, cleanup, and seeding: `settings`, `sessions`, `excel`, `calendar`, `mail`, `plugins`, `capabilities_cache`, `inbox`, `mail_store`, `activity_log`, `memory`, `agents`, `ledger`, and `keys`: `f31582a:src/agentdesk/server/app.py:802-916`
- `server.plugins.runner._watches`: `f31582a:src/agentdesk/plugins/runtime.py:189`; `f31582a:src/agentdesk/plugins/execute.py:269`
- Seed routes used by the fixed instrument exist at `f31582a`: `f31582a:src/agentdesk/server/routes.py:196-201,217-224,240,264-265,275-309`
- The old plugin validator accepts schema version 2: `f31582a:src/agentdesk/validator/schema.py:133-139`

`tools/mock_endpoint.py` has no `agentdesk` imports. The five fixture files contain data only.

## Checked and found correct

- All 37 instrument option occurrences exist in the relevant parsers. Layout options are at `origin/main:tools/layout_audit.py:4668-4696`; feedback options at `origin/main:tools/feedback_walkthrough.py:763-770`; face options at `origin/main:tools/face_walkthrough.py:1752-1767`.
- All supplied values are accepted: layout conditions, widths, themes, `--fail-on none`, integer job counts, and delay values; face themes, widths, route substrings, and delay value.
- All working directories and repository-relative tool paths are correct. Every output base is created in preparation, and each instrument creates its timestamped child. Face API recording creates its folder at `origin/main:tools/face_walkthrough.py:1691-1694`.
- `UV_OFFLINE=1` is a uv control, and `PLAYWRIGHT_BROWSERS_PATH` is consumed by Playwright. Neither instrument overrides them. The cached Chromium executable exists locally at `%LOCALAPPDATA%/ms-playwright/chromium-1255/chrome-win64/chrome.exe`.
- Readiness has 27 checks and prints `METRIC ready=27` only on full success: `origin/main:tools/demo_readiness.py:127-128,1308-1312`. It boots a temporary data folder and file keychain, starts no capability retest, and its background polls do not retest capabilities: `origin/main:tools/demo_readiness.py:195-218,1253-1305`; `origin/main:src/agentdesk/server/app.py:8742-8782`.
- Layout boots inject inert gate runners on every path: `origin/main:tools/layout_audit.py:2120-2165`. `busy` writes synthetic capability results instead of retesting: `origin/main:tools/layout_audit.py:2453-2470,2562-2571`.
- The request guard is installed before navigation: `origin/main:tools/layout_audit.py:3859-3862`. Feedback uses the deliberate-answer guard before authentication: `origin/main:tools/feedback_walkthrough.py:706-718`. Face holds non-GET requests except its explicit research continuation and holds marketplace retests: `origin/main:tools/face_walkthrough.py:361-405`.
- Preparation and serial walk parts are separated. No walk command installs, builds, tests, or starts a second walk. `npm ci` and the face-only frontend dependencies are preparation. Vite is launched only by the face instrument, and no production build is run.
- Layout arithmetic is 1,040 combinations for the full command and 130 for each pending command. Face arithmetic is 108 photographs and 24 reduced-motion captures. Feedback has seven actions and 21 planned photographs.
- Layout outputs and exits match the runbook: `OUT`, `METRIC`, optional `SKIPPED`, coverage exit 3, and parser/Playwright exit 2: `origin/main:tools/layout_audit.py:4600-4651,4701-4727`.
- Feedback outputs and exits match apart from the missing hard stop: `origin/main:tools/feedback_walkthrough.py:497-501,531-539,761-795`.
- Face plan, metric, verdict lines, and exit codes match apart from the early-exit-2 artifact claim and missing hard stop: `origin/main:tools/face_walkthrough.py:425-583,639-686,1750-1797`.
- Production dialogs are faceless on current main: `origin/main:frontend/src/marketplace/DescribePlugin.tsx:137-197`; `origin/main:frontend/src/dashboard/TrackerSetup.tsx`; `origin/main:frontend/src/components/ModalSheet.tsx:88-95`. Server-rendered Python pages contain no face markup. The likely four faceless surfaces are therefore the two dialogs, server inbox, and phone strip.
- Paths containing spaces are quoted. Neither runbook contains an em dash or an en dash outside a numeric range.

## Counts and limits

- Command blocks checked: 17, comprising 6 BEFORE and 11 AFTER. Serial walk commands: 8, comprising 2 BEFORE and 6 AFTER.
- Instrument option occurrences checked: 37.
- Copied BEFORE artifacts checked: 7.
- Source files inspected at `f31582a` for compatibility: 14.
- Not verified by execution: actual walk outcomes, elapsed times, screenshot counts, visual findings, selected Playwright package resolution under offline uv, and runtime behavior on the founder's otherwise-idle machine. Those require the prohibited walks. Current main had already moved through both announced pull requests, so the runbooks need replanning before use.
