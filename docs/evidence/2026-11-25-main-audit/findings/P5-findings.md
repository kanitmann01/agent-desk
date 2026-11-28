# P5 findings: the instruments

## 1. Coverage

Pinned worktree confirmed before review:

```text
$ git -C "D:/20-projects/Personal Agents/.worktrees/027-merge" rev-parse --short HEAD
3540b9f
```

Reviewed: 9 files. Generated: 0. Documentation: 0. Odd fits: 0.

- `tools/ci_local.py` (modified)
- `tools/feedback_walkthrough.py` (added)
- `tools/layout_audit.py` (added)
- `tools/layout_fixtures/long-values.api.json` (added)
- `tools/layout_fixtures/overflow-widget/manifest.json` (added)
- `tools/layout_fixtures/overflow-widget/manual.json` (added)
- `tools/layout_fixtures/overflow-widget/sample.json` (added)
- `tools/layout_fixtures/overflow-widget/widget.ui.json` (added)
- `tools/mock_endpoint.py` (modified)

The complete partition diff is `D:/20-projects/Personal Agents/.scratch/wave-2026-11-25/review/P5.diff` (7,327 lines). All of it was read. No repository or worktree file was changed. No audit, walk, server, whole gate, or real data folder was run or touched.

## 2. Findings

### P5-01: P0: The default busy audit retests real machine gates and writes into real OneDrive

- **File:** `tools/layout_audit.py`
- **Line:** 2442
- **What:** The busy condition POSTs every capability gate's retest endpoint. The audit boots the server without injecting `gate_runners`, so the server uses its production real adapters. Those adapters discover the current user's OneDrive root, copy a probe file into it, call external HTTPS endpoints, install a package through uv, and list running processes. This escapes the temporary data folder and can sync a file to the user's real cloud storage.
- **Why:** The instrument's isolation promise is a security boundary. A normal unfiltered audit includes `busy` by default, so a maintainer cannot safely run the documented command without unrelated writes, network traffic, and process inspection. The OneDrive write is outside `AGENTDESK_DATA` and is not removed by temporary-folder cleanup.
- **Evidence:** By reading. `tools/layout_audit.py:272-273` includes `busy` in `ALL_CONDITIONS`; `:4386` defaults `--conditions` to all of them; `:3634-3636` calls `_seed_busy`; `:2442-2446` POSTs `/capabilities/<key>/retest`. `_boot_desk` calls `create_server` at `:2096-2098` without `gate_runners`. `src/agentdesk/server/app.py:7259` exposes the `gate_runners` injection seam, while `:8062-8064` otherwise builds `default_gate_runners`. `src/agentdesk/capabilities.py:151` selects `real_adapters` when no adapter bundle is supplied. `src/agentdesk/probe/adapters.py:123-132` discovers OneDrive from the real environment/profile, and `:152-162` wires real subprocess, urllib, filesystem, and process adapters. `src/agentdesk/probe/gates.py:303-314` copies `agentdesk-probe-<timestamp>.txt` into that real sync root; `:186-190` installs `six` through uv; `:247` calls the real Power Automate reachability check.
- **Fix:** Inject deterministic `gate_runners` when creating the audit server, or seed the capability cache directly with synthetic `GateResult` values. Do not call the production retest endpoints from the audit. Add an isolation test that fails if a gate runner invokes subprocess, urllib, `Path.home`, OneDrive discovery, or any path outside the temporary root.
- **Confidence:** high.

### P5-02: P1: Pending verdicts accept stale or unrelated page content as proof of feedback

- **File:** `tools/layout_audit.py`
- **Line:** 3047
- **What:** The pending detector marks a request as `meets` when the form's declared wait target merely exists and has text, even if that text was present before the press. It also accepts any newly visible busy-looking element anywhere in the document. On populated server pages, removing the placeholder and busy-control behavior can therefore still produce `meets`.
- **Why:** Spec 027 requires the audit to prove visible pending feedback, not merely a started request. This is a test that can stay green while the behavior it names is broken, which is explicitly a P1 condition in the review brief.
- **Evidence:** By reading. `PENDING_STATE_JS` at `tools/layout_audit.py:151-156` sets `waitVisible` from target visibility and non-empty text only; it never compares the target with its pre-click state. `:158-177` collects indicators from `document.querySelectorAll`, not from the pressed control, form, or result region. `_pending_verdict` at `:3047-3048` returns `meets` for `wait_visible` or any `new_indicators`. The busy seed saves an assistant turn at `:2411-2418` before the pending pass, so `#assistant-thread` already has content. If the delegated placeholder code in `src/agentdesk/server/pages.py` were removed, the native POST would still start, the old thread text would keep `waitVisible` true, and this verdict would still be `meets`.
- **Fix:** Capture each wait target's DOM/signature before activation and require a newly inserted placeholder or phase line in that target after activation. Scope indicator comparison to the pressed control, its form, and the declared result region. Add a planted negative fixture with pre-existing target text and an unrelated busy region; both must produce `silent` or `disabled-only`, not `meets`.
- **Confidence:** high.

### P5-03: P1: Pending audit failures disappear from coverage and can pass with zero controls checked

- **File:** `tools/layout_audit.py`
- **Line:** 3090
- **What:** Page enumeration errors are printed and skipped without a record. Per-control activation errors are recorded as `skipped`, which `_pending_fail` ignores. If `--pending-audit` is requested but every page fails before controls are enumerated, `pending_records` stays empty, no pending JSON is written, the child exits 0, and coverage is computed only from the layout matrix.
- **Why:** The acceptance claim is that every control was pressed and produced zero `silent` or `disabled-only` verdicts. A failed audit is not evidence of zero defects, but this implementation lets an unexecuted pending pass inherit a successful layout run.
- **Evidence:** By reading. `tools/layout_audit.py:3090-3094` catches page failures and continues; `:3254-3257` turns control failures into `skipped`. `:3680-3681` writes pending output only when records are nonempty, and `:3686` returns 0. `_pending_fail` at `:3987-4002` ignores `skipped` and every verdict except `silent`, `dead`, and `disabled-only`. `_merge_outputs` computes incomplete coverage at `:4337` from missing layout rows, failed layout rows, and child exits only; it does not require pending records when `--pending-audit` was requested.
- **Fix:** Track planned pending pages and controls, and make unexpected enumeration or activation errors explicit failed coverage records. Write an empty pending report when the pass was requested but executed no controls, and include pending coverage in the exit-3 decision. Reserve `skipped` for intentional cases such as absent overlays, selected controls, disabled controls, covered controls, and drag handles.
- **Confidence:** high.

### P5-04: P1: A present Describe control that fails to open its dialog is treated as an allowed skip

- **File:** `tools/layout_audit.py`
- **Line:** 3488
- **What:** The Describe overlay opener finds and clicks the real control. If the expected dialog does not appear, it returns a reason saying the control submitted the walk instead. `_measure_combo` converts every opener reason into status `skipped`, and skipped rows do not fail coverage. The pending pass likewise drops the overlay when the opener returns a reason.
- **Why:** The dialog is a spec 027 main path and the trigger was present, so this is broken behavior rather than an unreachable optional state. The audit can report complete coverage and pass while the Describe workflow no longer opens.
- **Evidence:** By reading. `tools/layout_audit.py:3412-3420` clicks the Describe control and converts a missing dialog into the reason `the describe control submitted the walk instead of opening a dialog`. `:3485-3491` maps that reason to `skipped`. `:4315-4317` excludes skipped rows from failed coverage, and `:4337` counts only missing, failed, and child failures. The pending path at `:3081-3087` also continues without a control record when an overlay opener returns a reason.
- **Fix:** Distinguish an absent trigger, which may be an intentional skip, from a present trigger whose expected overlay fails to open. Mark the latter as an error or failed overlay and make it incomplete coverage. Apply the same distinction in the pending pass.
- **Confidence:** high.

### P5-05: P2: Mixed valid and invalid condition filters silently drop the invalid condition

- **File:** `tools/layout_audit.py`
- **Line:** 4433
- **What:** `main` filters the `--conditions` list down to recognized values before `build_combos` validates it. A command such as `--conditions fresh,busy-typo` runs `fresh` and reports a complete filtered run instead of rejecting the unsupported condition. Widths and themes do reject unsupported values, so the behavior is inconsistent with the tool's own hard-error contract.
- **Why:** A typo can remove an intended condition from an evidence run while leaving a successful exit code, making the resulting coverage claim narrower than the operator requested.
- **Evidence:** By reading. `tools/layout_audit.py:4430-4436` silently filters conditions and only errors when none remain. `build_combos` at `:1855-1857` does contain a hard error for unsupported conditions, but `main` never passes the rejected token to it. The printed run line at `:4447` shows only the filtered list.
- **Fix:** Validate every requested condition before filtering. Return exit 2 and name each unsupported token, matching the width and theme validation path.
- **Confidence:** high.

## 3. Tests that can fail

No new or changed repository test file belongs to P5. There are no pytest or Vitest rows to flag.

The added instrument contains its own executable selftest, reviewed by reading but not run because the brief forbids running the layout audit:

| Instrument check | Behaviour whose removal would fail it |
| --- | --- |
| `layout_audit._selftest` detector expectations | Removing squeezed-text, clip, ellipsis, overlap, spill, broken-word, tiny-type, control-overlap, or offscreen detection would fail the corresponding planted fixture assertion. |
| `layout_audit._selftest` box expectations | Removing `_box_changed` height/width logic would fail the grow, stable, label-change, and height-only cases. |
| `layout_audit._selftest` pending expectations | Breaking SVG activation, instant/dead signatures, selected/disabled skips, query/late changes, drag/coverage detection, native validation, or held form submission would fail the matching assertion. |

The selftest does not cover P5-01 through P5-05. In particular, it has no negative case for stale wait-target text, unrelated busy indicators, pending enumeration failure, a present Describe trigger with no dialog, or mixed invalid condition filters.

## 4. Checked and found correct

- The partition is exactly the nine `tools/` files in `git diff --name-status f31582a..3540b9f`.
- `tools/ci_local.py` still has seven gates and does not wire in Playwright or the layout audit, matching specs 026 and 027.
- The pytest failure-summary helper reads `FAILED` and `ERROR` lines from captured stdout and appends up to three names to the failed gate detail.
- `tools/mock_endpoint.py` refuses non-loopback bind addresses. Its delayed JSON response sends legal leading whitespace while resetting the reader's idle timeout, then sends the complete JSON body with the correct content length.
- `feedback_walkthrough.py` uses the audit's temporary data root and file-backed keychain, saves only the loopback mock connection, and closes the browser, desk, mock, and temporary folder in `finally`.
- The layout audit pins every `AGENTDESK_*` variable read by the product before importing `agentdesk`, sets `AGENTDESK_DATA` to a fresh temporary path, injects a file-backed keychain, and binds the desk and mock to loopback. The capability-gate escape in P5-01 is the exception.
- The overflow fixture declares no filesystem, network, model, or shell permission. The long-values fixture is JSON data and contains no key, token, or password.
- The layout matrix rejects unsupported widths, themes, empty route matches, and empty plans. It distinguishes measured, skipped, and failed layout rows and exits 3 for incomplete layout coverage unless `--allow-partial` is set.
- The known phone-width starting point is confirmed: the narrowest planned width is 800 px (`tools/layout_audit.py:270`). It is not filed as a defect because spec 026 explicitly defines the accepted widths as 800, 1024, 1280, and 1920 and does not require a phone-width pass.
- The known verdict-count mismatch is confirmed on the instrument side: `_pending_verdict` can return seven verdicts, including `dead`, while README names six. README is P6, so the documentation finding is left to that partition.
