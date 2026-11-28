# P5 confirmer evidence

Pinned read-only worktree: `D:/20-projects/Personal Agents/.worktrees/027-merge`, head `3540b9f`. Citations below are relative to that worktree.

Method for all four findings: reading only, including hand evaluation of fabricated inputs. Per the partition overrides, I did not run the layout audit, the feedback walkthrough, a desk-booting test, a capability retest endpoint, or any code that imports `agentdesk` or the instrument. I made no mutation worktree and changed no worktree file. I did not list, read, or touch `%USERPROFILE%\.agent-desk`.

## P5-01: confirmed, P0

### Trace from audit selection to the server

1. `busy` is in `ALL_CONDITIONS` at `tools/layout_audit.py:271-273`, and `--conditions` defaults to that complete tuple at `tools/layout_audit.py:4386-4387`. The condition worker boots the desk at `tools/layout_audit.py:3580` and calls `_seed_busy` only for `condition == "busy"` at `tools/layout_audit.py:3633-3636`.
2. The worker creates a temporary root at `tools/layout_audit.py:3568`, starts the loopback mock for `busy` at `tools/layout_audit.py:3573-3574`, pins the product environment at `tools/layout_audit.py:3575`, and points `AGENTDESK_DATA` at the temporary data directory at `tools/layout_audit.py:2022-2041`. That pinning does not pin `OneDrive`, `OneDriveConsumer`, `OneDriveCommercial`, or `USERPROFILE`.
3. `_boot_desk` calls `create_server` at `tools/layout_audit.py:2096-2098` with a port, announce port, and file-backed keychain, but no `gate_runners`. The injection seam is declared at `src/agentdesk/server/app.py:7258-7259`.
4. Because the argument is omitted, `create_server` takes its fallback at `src/agentdesk/server/app.py:7346-7349` and calls `_default_gate_runners(settings_store)`. That function calls `default_gate_runners(default_data_dir() / "probe-run", embeddings=...)` at `src/agentdesk/server/app.py:8053-8065`. The temporary `AGENTDESK_DATA` therefore relocates the probe workdir, but does not replace the adapters.
5. The factory passes the resulting runner map into `AgentDeskServer` at `src/agentdesk/server/app.py:7387-7411`. The server stores it at `src/agentdesk/server/app.py:858-865`. The class-level fallback at `src/agentdesk/server/app.py:862-864` is not needed on this path because the factory already supplied a non-None map.
6. `default_gate_runners` selects `real_adapters()` whenever no adapter bundle is supplied at `src/agentdesk/capabilities.py:133-152`. `real_adapters` wires the real subprocess runner, uv lookup, urllib reacher, process lister, OneDrive discoverer, filesystem writer, and file copier at `src/agentdesk/probe/adapters.py:152-162`. The six closures are mapped at `src/agentdesk/capabilities.py:153-167`.

### Trace from the busy seed to each real effect

7. `_seed_busy` imports `GATES` and loops over all six entries at `tools/layout_audit.py:2438-2446`. `GATES` contains execution, uv, Power Automate, OneDrive, EDR, and embeddings at `src/agentdesk/capabilities.py:42-55`. Each iteration sends `POST /capabilities/<key>/retest` through `context.request.post` at `tools/layout_audit.py:2444-2446`. This is a browser-context API request, not a request from a routed page, so the pending pass's page interceptor cannot hold it.
8. The server accepts POST at `src/agentdesk/server/app.py:1382-1395`, authenticates and dispatches it at `src/agentdesk/server/app.py:1540-1553`, and matches `/capabilities/<key>/retest` to `_capabilities_retest` at `src/agentdesk/server/routes.py:264-265`.
9. `_capabilities_retest` looks up exactly that key in `server.gate_runners`, calls `runner()`, and caches the result at `src/agentdesk/server/app.py:5323-5343`. There is no audit-specific fake or isolation check in this path. A missing cache returns 503 before the runner, and a missing key returns 404 at `src/agentdesk/server/app.py:5328-5335`; with the normal default cache and the six `GATES` keys, each real closure is called.
10. **User-space execution:** the `exec-user-space` closure calls `gate_exec_user_space` with the real runner and writer at `src/agentdesk/capabilities.py:154-156`. The gate writes `probe_hello.py` under the temporary probe workdir and runs the current Python with `-I` at `src/agentdesk/probe/gates.py:67-96`. The real runner calls `subprocess.run` at `src/agentdesk/probe/adapters.py:24-43`.
11. **Package install and external package traffic:** the `uv-tls-bootstrap` closure calls the real uv gate at `src/agentdesk/capabilities.py:157-159`. The gate finds uv on the real `PATH`, creates a venv under the temporary probe workdir, and runs `uv pip install --python <venv python> six` at `src/agentdesk/probe/gates.py:138-190`. `find_uv` uses `shutil.which("uv")` at `src/agentdesk/probe/adapters.py:67-69`; command execution uses the real subprocess runner at `src/agentdesk/probe/adapters.py:24-43`. The install is conditional on uv being present and venv creation succeeding, but when it runs it can contact the configured external package index.
12. **External HTTPS reachability:** the `power-automate-flows` closure calls the real reacher at `src/agentdesk/capabilities.py:160`. The gate calls `reach(POWER_AUTOMATE_URL)` at `src/agentdesk/probe/gates.py:237-247`; the URL is `https://make.powerautomate.com` at `src/agentdesk/probe/core.py:30-32`. The real reacher constructs a GET and calls `urllib.request.urlopen` at `src/agentdesk/probe/adapters.py:46-64`.
13. **OneDrive discovery and probe copy:** the `onedrive-sync` closure supplies the real discoverer, writer, and copier at `src/agentdesk/capabilities.py:161-163`. On Windows the discoverer checks `OneDrive`, `OneDriveConsumer`, and `OneDriveCommercial`, then `%USERPROFILE%/OneDrive*`, at `src/agentdesk/probe/adapters.py:99-133`. The gate writes a temporary source file, constructs `agentdesk-probe-<YYYYMMDD-HHMMSS>.txt` in the discovered real root, and copies it there at `src/agentdesk/probe/gates.py:281-314`. The real copier is `shutil.copy` at `src/agentdesk/probe/adapters.py:77-79`. The destination is outside `AGENTDESK_DATA`. Worker cleanup removes only `tmp_root` at `tools/layout_audit.py:3697-3708`, so it cannot remove that destination.
14. **Process listing:** the `edr-identity` closure supplies the real process lister at `src/agentdesk/capabilities.py:164`. The gate calls it at `src/agentdesk/probe/gates.py:363-392`. On Windows the adapter runs `tasklist /svc /fo csv /nh` through the real subprocess runner at `src/agentdesk/probe/adapters.py:82-96`.
15. **Embeddings request:** the `embeddings` closure calls the settings-backed embedder at `src/agentdesk/capabilities.py:165-167` and `src/agentdesk/probe/gates.py:424-447`. The embedder resolves the effective endpoint and posts one embeddings request at `src/agentdesk/memory/embed.py:273-314`. In the busy seed, the audit pins the model base to its loopback mock at `tools/layout_audit.py:2036-2039` and saves a connection to that same mock at `tools/layout_audit.py:2391-2404`, so this sixth request is expected to be loopback rather than an external model call.
16. Each gate request has a 120-second timeout at `tools/layout_audit.py:2444-2446`. Per-gate exceptions are caught and the loop continues at `tools/layout_audit.py:2447-2455`, so one failed gate does not prevent the remaining real effects.

### Does another condition or pass reach those endpoints?

- The instrument has two explicit retest POST sites. The overflow fixture POST at `tools/layout_audit.py:2304-2320` is a different endpoint, `/api/plugins/audit-overflow/retest`, and is used for `plugins` and `full` through `OVERFLOW_CONDITIONS` at `tools/layout_audit.py:59`. The capability retest loop at `tools/layout_audit.py:2438-2455` is reached only by the busy seed at `tools/layout_audit.py:3633-3636`. There is no explicit POST to a `/check` endpoint elsewhere in the instrument.
- A normal layout visit to `/capabilities` is only a GET: the view is declared at `tools/layout_audit.py:1782`. The server's GET handler reads cached results and live status at `src/agentdesk/server/app.py:5256-5283`; it does not call a gate runner. Constructing the default runner map also probes nothing, as documented and implemented at `src/agentdesk/capabilities.py:147-168`.
- With `--pending-audit`, every condition can enumerate and activate the six server-rendered controls labelled `Re-test gate 1` through `Re-test gate 6`. Their forms point to `/capabilities/<key>/retest` at `src/agentdesk/server/capabilities_view.py:120-129`, and the instrument's generic selector includes every visible button at `tools/layout_audit.py:60` and `tools/layout_audit.py:98-114`.
- Those ordinary pending control activations are held before they reach the server. The fresh-page interceptor is installed at `tools/layout_audit.py:3181`, before the target click at `tools/layout_audit.py:3182` and activation at `tools/layout_audit.py:3198`. It continues every GET, records every non-GET, and returns without continuing or fulfilling it at `tools/layout_audit.py:3130-3138`. Held routes are aborted during cleanup at `tools/layout_audit.py:3258-3263`. Thus the capability POST is observed as `request_started` but is not dispatched to `_capabilities_retest`.
- The hold is not universal for the whole pending pass. Overlay enumeration calls `_open_overlay` before any per-control page exists at `tools/layout_audit.py:3081-3088`, and the fresh-page path also opens an overlay before installing `fresh.route` at `tools/layout_audit.py:3169-3181`. Requests caused by those opener clicks can reach the server. In particular, Describe's click first performs GET `/api/wizard/availability`, then may submit native POST `/wizard/start` when autofill is unavailable at `frontend/src/marketplace/DescribePlugin.tsx:72-90` and `frontend/src/marketplace/DescribePlugin.tsx:126-133`. That POST is before the hold. It is not a capability retest endpoint.
- The direct overlay openers are `Widget options`, `Set up` or `Edit`, `Customize`, `Install plugin`, `Set up a new instance` or `Edit`, `Purge data`, and `Describe a plugin in plain English` at `tools/layout_audit.py:3359-3421`. None is a capability gate retest. Other visible controls that can be retests or checks, including `Re-test now`, `Re-test`, `Test connection`, `Deeper check (one-token completion)`, `Check for calendar data now`, `Check the folder now`, and `Check now`, are ordinary pending controls once enumerated and are therefore covered by the non-GET hold. Examples of their rendered endpoints are `frontend/src/dashboard/CommitmentsCard.tsx:104-121`, `frontend/src/marketplace/PluginDetail.tsx:219-223`, `src/agentdesk/server/settings_view.py:783-815`, `src/agentdesk/server/pages.py:1955`, `src/agentdesk/server/mail_view.py:69-74`, and `src/agentdesk/server/settings_view.py:1080-1085`.

Answer: no other condition's seed reaches the capability retest endpoints. The pending pass can press the same controls in any condition, but its ordinary control POSTs are held before server dispatch. Overlay-opener requests and all `_seed`/`_seed_busy` context API requests are outside that hold; only `_seed_busy` sends capability retests.

### Narrow read-only OneDrive trace check

The adapter's first Windows candidate is the `OneDrive` environment variable at `src/agentdesk/probe/adapters.py:123-126`. For the current user it is set to `C:\Users\mannk\OneDrive`, and that directory exists. The adapter therefore selects this root with detection method `environment variable OneDrive`. `%USERPROFILE%/OneDrive*` also resolves to the same directory, but is not needed after the environment match.

I inspected only that root's immediate entries, selected only files named `agentdesk-probe-*.txt`, and read metadata only. I opened none of the files. Result: 27 files, each 48 bytes, newest first. Timestamps are local Eastern Standard Time (`-05:00`). These artifacts are consistent with the gate's 48-byte source text at `src/agentdesk/probe/gates.py:303-306` and repeated prior busy runs. Metadata alone does not attribute an individual file to a specific run.

| Modified timestamp | Size | File |
| --- | ---: | --- |
| 2026-11-24T21:21:45-05:00 | 48 bytes | `agentdesk-probe-20261124-212145.txt` |
| 2026-11-24T20:04:50-05:00 | 48 bytes | `agentdesk-probe-20261124-200450.txt` |
| 2026-11-24T19:56:48-05:00 | 48 bytes | `agentdesk-probe-20261124-195648.txt` |
| 2026-11-24T19:22:31-05:00 | 48 bytes | `agentdesk-probe-20261124-192231.txt` |
| 2026-11-24T18:55:02-05:00 | 48 bytes | `agentdesk-probe-20261124-185502.txt` |
| 2026-11-24T18:41:59-05:00 | 48 bytes | `agentdesk-probe-20261124-184159.txt` |
| 2026-11-24T18:36:53-05:00 | 48 bytes | `agentdesk-probe-20261124-183653.txt` |
| 2026-11-24T18:32:21-05:00 | 48 bytes | `agentdesk-probe-20261124-183221.txt` |
| 2026-11-24T18:31:09-05:00 | 48 bytes | `agentdesk-probe-20261124-183109.txt` |
| 2026-11-24T18:22:51-05:00 | 48 bytes | `agentdesk-probe-20261124-182251.txt` |
| 2026-11-24T18:04:46-05:00 | 48 bytes | `agentdesk-probe-20261124-180446.txt` |
| 2026-11-24T17:31:22-05:00 | 48 bytes | `agentdesk-probe-20261124-173122.txt` |
| 2026-11-24T17:29:50-05:00 | 48 bytes | `agentdesk-probe-20261124-172950.txt` |
| 2026-11-24T17:29:31-05:00 | 48 bytes | `agentdesk-probe-20261124-172931.txt` |
| 2026-11-24T17:23:50-05:00 | 48 bytes | `agentdesk-probe-20261124-172350.txt` |
| 2026-11-24T17:20:25-05:00 | 48 bytes | `agentdesk-probe-20261124-172025.txt` |
| 2026-11-24T17:06:20-05:00 | 48 bytes | `agentdesk-probe-20261124-170620.txt` |
| 2026-11-24T17:00:50-05:00 | 48 bytes | `agentdesk-probe-20261124-170050.txt` |
| 2026-11-24T17:00:34-05:00 | 48 bytes | `agentdesk-probe-20261124-170034.txt` |
| 2026-11-24T16:57:51-05:00 | 48 bytes | `agentdesk-probe-20261124-165751.txt` |
| 2026-11-24T16:54:32-05:00 | 48 bytes | `agentdesk-probe-20261124-165432.txt` |
| 2026-11-24T16:50:47-05:00 | 48 bytes | `agentdesk-probe-20261124-165047.txt` |
| 2026-11-24T16:38:54-05:00 | 48 bytes | `agentdesk-probe-20261124-163854.txt` |
| 2026-11-24T16:36:03-05:00 | 48 bytes | `agentdesk-probe-20261124-163603.txt` |
| 2026-11-24T16:17:18-05:00 | 48 bytes | `agentdesk-probe-20261124-161718.txt` |
| 2026-11-24T16:09:16-05:00 | 48 bytes | `agentdesk-probe-20261124-160916.txt` |
| 2026-11-24T16:06:45-05:00 | 48 bytes | `agentdesk-probe-20261124-160645.txt` |

Severity holds at P0: the default audit crosses the promised temporary-data isolation boundary and writes into the user's real OneDrive root. It also performs real subprocess, network, package-install, and process-inspection effects. The 27 existing matching files make the write path concrete on this machine.

## P5-02: confirmed, P1

### Code derivation

1. Control enumeration copies the form's `data-wait` value into `wait_target` at `tools/layout_audit.py:111-114`.
2. `PENDING_STATE_JS` sets `waitVisible` when the target exists, is visible, and has any non-empty `textContent` at `tools/layout_audit.py:151-156`. It receives no pre-click target text or DOM snapshot and performs no comparison.
3. Busy indicators are collected from the whole document with `document.querySelectorAll` at `tools/layout_audit.py:158-177`. They are not scoped to the pressed control, its form, or its wait target. The separate pre-click collector has the same document-wide selectors at `tools/layout_audit.py:2888-2922`.
4. The pre-click indicator list is captured at `tools/layout_audit.py:3178`. The control is activated at `tools/layout_audit.py:3198`, and the post-click state is read at `tools/layout_audit.py:3204-3211`. `_pending_verdict` treats a new `(path, text)` pair as a new indicator at `tools/layout_audit.py:3013-3017`.
5. Once any request has started, `_pending_verdict` returns `meets` for `aria_busy`, `wait_visible`, `label_changed`, or any new indicator at `tools/layout_audit.py:3036-3048`. It does not require that the visible feedback began after activation.
6. The busy seed posts an assistant question at `tools/layout_audit.py:2411-2418`. The server appends both user and assistant turns to the thread log at `src/agentdesk/server/app.py:2534-2537`. The Assistant page renders that log inside `#assistant-thread` and gives the Ask form `data-wait="#assistant-thread"` at `src/agentdesk/server/research.py:143-158`. Therefore the busy Assistant page has pre-existing target text before the pending pass presses Ask.

### Fabricated inputs evaluated by hand

**Stale target text produces false `meets`.** Supply `_pending_verdict` with:

- `control = {"text": "Ask", "wait_target": "#assistant-thread"}`.
- `state = {"control": {"text": "Ask", "disabled": False}, "labelChanged": False, "ariaBusy": False, "waitVisible": True, "indicators": []}`.
- `started = [{"method": "POST", "url": "http://127.0.0.1/assistant/ask"}]`.
- `before_indicators = []`, `native_dialog = False`, `page_changed = False`, `invalid_control = None`.

The target's old assistant turn already makes `waitVisible` true at `tools/layout_audit.py:151-156`. The function does not take an early skip or no-request branch at `tools/layout_audit.py:3002-3039`, the URL is not a picker at `tools/layout_audit.py:3040-3046`, and `wait_visible` alone returns `meets` at `tools/layout_audit.py:3047-3048`. No new placeholder, phase line, label, aria state, or page change is required.

**Unrelated new busy content produces false `meets`.** Use the same started POST, but set `waitVisible = False`, `ariaBusy = False`, `labelChanged = False`, `before_indicators = []`, and `state["indicators"] = [{"path": "div.unrelated-busy", "text": "Background refresh"}]`. The pair is absent from `before_keys` at `tools/layout_audit.py:3015-3017`, so `new_indicators` is non-empty and the same branch returns `meets` at `tools/layout_audit.py:3047-3048`, even though the element has no relationship to the pressed control.

Severity holds at P1: this is a main-path instrument verdict that can report visible pending feedback while the named feedback behavior is absent. The finding does not require a runtime reproduction to establish the false-positive logic.

## P5-03: confirmed, P1

### Code derivation

1. Page setup and control enumeration are inside one try. Any navigation, wait, overlay-open, or enumeration exception is printed and followed by `page.close()` and `continue` at `tools/layout_audit.py:3072-3094`. No failure record is appended.
2. A per-control record starts as `verdict: "skipped"` at `tools/layout_audit.py:3096-3109`. If activation or measurement raises, the exception handler keeps it skipped and records only an error reason at `tools/layout_audit.py:3254-3257`.
3. The child writes `pending.<condition>.json` only when `pending_records` is non-empty at `tools/layout_audit.py:3678-3683`, then returns 0 at `tools/layout_audit.py:3684-3686`. Pending verdict failures are not consulted in the child.
4. The parent reads a missing pending file as an empty list at `tools/layout_audit.py:4272-4277` and writes merged `pending.json` only when that list is non-empty at `tools/layout_audit.py:4321-4326`.
5. `_pending_fail` considers only `silent`, `dead`, and `disabled-only`; every other verdict, including `skipped`, falls through `continue` at `tools/layout_audit.py:3987-4002`.
6. Coverage incompleteness is only missing layout rows, failed layout rows, and nonzero child exits at `tools/layout_audit.py:4312-4320` and `tools/layout_audit.py:4337-4354`. There is no planned-pending-pages or planned-pending-controls count. The final pending check is guarded by `if pending` at `tools/layout_audit.py:4367-4368`, so an empty list cannot fail.
7. An additional visible consequence: `_write_summary` maps every empty pending list to the sentence `No pending audit was requested.` at `tools/layout_audit.py:4128-4132`, even when `--pending-audit` was requested and failed before producing records.

### Fabricated inputs evaluated by hand

**Every page fails before enumeration.** For each selected combo, fabricate `page.goto` raising `RuntimeError("navigation failed")`. The catch at `tools/layout_audit.py:3090-3094` prints and continues, so `controls` is never assigned and no record is appended. If this happens for every combo, `_run_pending_audit` returns `[]` at `tools/layout_audit.py:3270`. Assuming the independent layout matrix is complete and has no threshold findings, the child skips the pending file write at `tools/layout_audit.py:3680-3681` and returns 0 at `tools/layout_audit.py:3686`. The parent sees no missing/failed layout rows and no child failure, so `incomplete` is 0 at `tools/layout_audit.py:4337`; `pending` is empty, so the final check at `tools/layout_audit.py:4367` is skipped and the parent returns 0 at `tools/layout_audit.py:4369`.

**One activation fails.** Fabricate the fresh page not containing the previously enumerated control. `_pending_click` returns a falsey value at `tools/layout_audit.py:2741-2742`; the caller raises `RuntimeError("control not found on the fresh page")` at `tools/layout_audit.py:3182-3184`; the catch records `skipped` at `tools/layout_audit.py:3254-3257`. For `records = [{"verdict": "skipped"}]` and any threshold, `_pending_fail` reaches the `else: continue` at `tools/layout_audit.py:3998-3999` and returns False at `tools/layout_audit.py:4002`.

**Empty pass.** For `records = []`, `_pending_fail([], "any")` never enters its loop and returns False at `tools/layout_audit.py:4002`. This is the same result as a genuinely clean pass.

Severity holds at P1: a requested main-path audit can inherit a successful layout result without checking any pending controls, and unexpected activation errors are treated like intentional skips.

## P5-04: narrowed, P1

### Code derivation

1. The Describe overlay is planned for `data` and `full` at `tools/layout_audit.py:1827-1829`.
2. `_open_overlay` finds the real `Describe a plugin in plain English` button, returns an allowed-style reason only when the trigger is absent, clicks a present trigger, and waits for `.setup-sheet[role="dialog"]` at `tools/layout_audit.py:3412-3418`.
3. If the dialog wait times out, it returns `the describe control submitted the walk instead of opening a dialog` at `tools/layout_audit.py:3419-3420`. It does not verify a `/wizard/...` destination or distinguish a native fallback from a click that did nothing.
4. `_measure_combo` converts every non-empty opener reason to matrix status `skipped` at `tools/layout_audit.py:3485-3491`. The merger excludes skipped rows from failed coverage at `tools/layout_audit.py:4315-4317`, and its incomplete count includes only missing, failed, and child-failure rows at `tools/layout_audit.py:4337-4339`.
5. In the pending pass, the initial overlay enumeration drops the entire page without any control record when `_open_overlay` returns a reason at `tools/layout_audit.py:3081-3087`. If a trigger was already enumerated but the fresh-page opener returns a reason, that later path appends a skipped control record instead at `tools/layout_audit.py:3169-3175`. Both outcomes are ignored by `_pending_fail` at `tools/layout_audit.py:3992-4001`.
6. There is a legitimate no-dialog branch in the product: when `/api/wizard/availability` says autofill is unavailable or the probe fails, Describe submits the plain form to `/wizard/start` at `frontend/src/marketplace/DescribePlugin.tsx:72-90`. The form and label are at `frontend/src/marketplace/DescribePlugin.tsx:126-133`. Therefore absence of the AI-fill dialog is not by itself proof of a defect. The defect is that the instrument does not verify which valid branch occurred before calling the state skipped.

### Fabricated input evaluated by hand

Present the exact Describe label on `/marketplace`, let `trigger.count()` be 1, let `trigger.click()` succeed, and make no `.setup-sheet[role="dialog"]` appear within 5 seconds. The absent-trigger return at `tools/layout_audit.py:3414-3415` is not taken. The wait raises `PlaywrightTimeoutError`, which becomes the submitted-walk reason at `tools/layout_audit.py:3417-3420`. `_measure_combo` then sets `status = "skipped"` at `tools/layout_audit.py:3486-3491`. The merger omits that row from `failed` at `tools/layout_audit.py:4315-4317`, so a complete layout matrix with this skipped Describe row yields `incomplete = 0` at `tools/layout_audit.py:4337` and can exit 0. The same input can describe either a broken no-op control or the legitimate native-walk fallback; the instrument's evidence does not say which.

Restated finding: when a Describe trigger is present, failure to open the AI-fill dialog or verify the native walk is recorded as an allowed skip, so a broken no-op or broken AI-enabled dialog path can pass with complete coverage. An absent trigger or a verified no-autofill navigation may remain an intentional skip.

Severity remains P1 for the broken-path case: Describe is a planned main-path workflow, and the instrument can stay green while a present trigger does nothing. The narrowing excludes the legitimate no-autofill fallback from being called a defect merely because no dialog appears.

## Mutation and execution record

No mutation was run. No test or application was run. No temporary worktree was created, so there was no temporary worktree to remove.
