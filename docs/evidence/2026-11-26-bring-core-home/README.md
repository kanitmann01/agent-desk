# Bring core home: the architecture sweep (Stage 3)

Run date: 2026-11-26. Branch: `merge/bring-core-home`. Every count below was
re-derived by grep in this tree, not taken from the plan's appendix. Each grep
runs from the repo root.

## The sweep table

| Pattern | Where core defines it | Sites core applied | Post-fork sites found | Sites applied by this run | The grep that proves it |
|---|---|---|---|---|---|
| Declared step order | `src/agentdesk/agentloop/loop.py`: `Step.order`, `STEP_ORDER_*`, `ordered_steps()` | 8 steps registered in `loop.py` and `server/app.py` with `order=` constants (deskcheck 100 through update 800) | 1: the `engine` step (PR #293, spec 023) | 0 new: already landed in Stage 1 (`STEP_ORDER_ENGINE = 900` at `loop.py:84`, engine registered with it at `app.py:8998`); this run verified the test lists all 9 names in pass order with `engine` last and the expected-pass helper iterates `ordered_steps()` | `grep -rn "register_step(Step(name=" src/` gives exactly 9 registrations, every one with `order=`; `tests/test_agentloop.py:233` asserts the pass order through `ordered_steps()`, engine last |
| `_require_store` (one refusal for an optional store) | `server/app.py` `_require_store` (sends the 503 JSON itself, returns None) | 53 call sites in `server/app.py`, 11 in `server/memory_api.py` | 1 unguarded raw-503 handler (`_memory_forget_all`, `memory_api.py:301`), 6 tuple-shaped engine refusals in `server/app.py` (three groups: 2, 3, 1), 4 form-notice sites kept raw at merge time | 11: the handler guarded with `_require_store` (JSON byte-identical); the 6 engine refusals and the 4 form sites routed through the one result-returning sibling (`StoreMissing` / `_store_missing` / `_send_store_missing`) | `grep -rn '"the .* is not available"' src/agentdesk --include=*.py` now shows only the two helpers (`_require_store`, `_store_missing`) and the 2 pre-fork leftovers listed below |
| `emission_targets` (one emission spine) | `plugins/runtime.py:733` | 3 consumers, all on the spine: `layout_keys`, `widget_cards`, `record_dashboard_view` | 0 bypasses: every plugin card emission goes through the spine; outside readers only consume its results (`server/dashboard_state.py:313` calls `widget_cards()`, `server/app.py:4669` calls `record_dashboard_view()`) | 0 needed | `grep -rn "emission_targets" src/ --include=*.py` gives the definition plus exactly the three loop consumers |
| Shared safety grammar | `validator/grammar.py` (one owner of `SAFE_NAME`, `JSON_OBJECT`, `JSON_LIST`, `JSON_PATH_PART`, `WORKSPACE_ROOT`, `PLUGIN_DATA_ROOT`) | 6 importers: `plugins/config.py`, `plugins/sources.py`, `plugins/runtime.py`, `registry/index.py`, `server/peers_api.py`, `validator/lint.py` | 0 new local definitions: every surviving `_SAFE`, `_SAFE_NAME`, `_SAFE_ID`, `_PEER_SAFE_NAME`, `_JSON_OBJECT`, `_JSON_LIST`, `_JSON_PATH_PART` is an import alias of the owner, not a local regex | 0 needed | `grep -rn "from agentdesk.validator.grammar import\|from .grammar import" src/ --include=*.py` gives exactly the 6 importers; `grep -rnE "^_SAFE|^_JSON_(OBJECT|LIST|PATH_PART) =|^_PEER_SAFE_NAME = " src/ tests/ --include=*.py` gives none |
| `agentdesk/locking.py` (`store_lock`, `serialized`) | `agentdesk/locking.py` | 7 importer files: `keys/store.py`, `ledger/store.py`, `inbox/store.py`, `repetition/activity.py`, `repetition/skills.py`, `memory/store.py` (`serialized as _locked`), `server/app.py` (`store_lock`) | 0 new shared-connection stores: every store holding a `check_same_thread=False` connection predates the fork (checked against the `cfbc793` file list); the only post-fork file with a lock (`plugins/refresh.py`) holds no sqlite connection, and the feeder collectors open per-poll snapshot connections, not shared stores | 0 needed | `grep -rln "from agentdesk.locking import" src/ --include=*.py` gives exactly the 7; `grep -rn "check_same_thread=False" src/agentdesk --include=*.py` plus `git ls-tree cfbc793` shows every such store file existed at the merge base |
| `pending_diff` consent (one consent decision) | `plugins/runtime.py`: holds a widening update as `pending_update`, reports `pending_diff`, applies `consent`, drops `decline_pending` | the marketplace's `post_consent` routes accept through `runtime.consent` and reject through `runtime.pending_diff` + `decline_pending` (`marketplace/api.py:1615-1645`) | 0 bypasses, proven by reading: every other `pending_update` reader outside `runtime.py` is display-only (`marketplace/api.py:404` renders the DTO; `server/app.py:6393` and `:6417` reduce a pending update to version plus added scopes for the SPA); only `runtime.py` ever sets or clears `pending_update` | 0 needed | `grep -rn "pending_update" src/ --include=*.py` minus `plugins/runtime.py` leaves only display-only readers; the decision paths at `marketplace/api.py:1629`, `:1637`, `:1640` all call the runtime |

## The result-returning sibling

`StoreMissing` (`server/app.py`, frozen dataclass with `status`, `sentence`,
`notice`, and `as_json()`), built by `DashboardHandler._store_missing(name, *,
status=503, sentence="", notice="")` (the one decision point: the JSON sentence
defaults to `_require_store`'s exact wording) and answered by
`_send_store_missing(outcome, render=None)` (the two answer shapes: a form post
renders the caller's page with the notice, never raw JSON; every other caller
gets the raw JSON payload, byte-identical to before). The engine tool helpers
call `self._store_missing(...).as_json()` and keep returning their refusal
tuples.

The four form-notice sites, current line numbers:

| Site | Handler | Line | Note |
|---|---|---|---|
| agents brief | `_agents_run` path, the `server.agents is None` branch | `server/app.py:3046` | form notice kept verbatim, typed brief and agent kept |
| presentation | the presentation run path, same store read | `server/app.py:3168` | same |
| capabilities cache | `_send_capabilities_page` | `server/app.py:5248` | the merge had dropped both parents' response here (the handler answered nothing at all); the sibling restores the raw JSON 503 for callers and covers the form shape |
| mail draft | `_mail_draft`, the watcher read then the inbox read | `server/app.py:5508-5524` | the watcher read had gone through `_require_store` at merge time, which sent raw JSON to form posts and left the wave's notice branch dead behind a second send; the sibling answers once, in the caller's shape |

## Count notes (differences from the plan's appendix)

- Tuple-shaped engine refusals: the appendix said 7 in three groups of 2, 3
  and 1, but 2+3+1 is 6. Re-derivation finds exactly 6, in the same three
  groups: `add_card` (recommender/inbox 503, ledger 409), `propose_fact`
  (memory 503, ledger 409, inbox 503), `_engine_write_refusal` (settings
  missing or autonomy off, 409). The other refusal tuples in those helpers
  (400 validation, 409 capture off, 409 already held, 423 locked, 500 write
  failures) are not store-missing refusals and keep their own shape.
- Grammar importers: the appendix said 5; the owner has 6, because
  `validator/lint.py` imports it relatively (`from .grammar import`).
- `_require_store` unguarded handlers: the appendix expected exactly 1
  post-fork site and that is what the tree held (`_memory_forget_all`).
  Two further raw-503 store-missing sites exist in `memory_api.py`
  (`_memory_graph_json`, `_memory_loop_json`) but both predate the fork and
  core left them raw on `core/main` too; see the leftovers below.

## Left alone on purpose (core's own leftovers, reported, not fixed)

- `SAFE_PLUGIN_ID` in `validator/schema.py:80`: a local regex beside the
  grammar owner.
- Ad-hoc locks in `agents/store.py:62` and `assistant/research_store.py:55`
  (and `settings.py:164`, the rule's documented origin): pre-fork, core left
  them.
- The four wizard store reads core also left alone.
- No inventory tests exist for the unguarded patterns; the greps in the table
  above are this run's substitute proof.
- `_memory_graph_json` (`memory_api.py:567`) and `_memory_loop_json`
  (`memory_api.py:898`): pre-fork JSON routes whose refusal shape is
  `{"status": "unavailable", "error": ...}` rather than the pattern's
  `{"error": ...}`. Core saw both and left them raw on `core/main` as well;
  converting them would change their JSON bytes, so they stay.
- `seal=` / `unseal=` grep hits in `tests/test_ledger.py:205` are a false
  positive: that is the `Ledger` constructor's own parameters, not the
  removed `LearnedProfileStore` API.

## Targeted tests this run (all under the pinned, fully isolated environment)

- `tests/test_agentloop.py`, `tests/test_server_memory_api.py`,
  `tests/test_server_memory_forget_all.py`,
  `tests/test_engine_tools_route.py`: 125 passed.
- `tests/test_server_agents.py`, `tests/test_server_capabilities.py`,
  `tests/test_server_mail_api.py`: 86 passed.
- `tests/test_presentation_research.py`: 7 passed (one timing flake on a
  first run, passed on re-run and on the full-module run).
- `tests/test_ui_feedback.py`: 53 passed.
- `tests/test_server_settings_api.py`: 27 passed, 5 failed, and the 5 are
  exactly the known-red feeder-card tests that Stage 4 wires into the
  six-section Settings: `test_the_settings_page_renders_the_outlook_alerts_block`,
  `test_fetch_now_runs_the_injected_feeder_and_shows_the_manual_fallback`,
  `test_a_healthy_fetch_shows_its_count_and_coverage_window`,
  `test_a_busy_fetch_and_the_macos_cause_render_plainly`,
  `test_the_fetch_outlook_alerts_toggle_appears_once`.
- The full gate (`tools/ci_local.py`) was deliberately not run at this stage;
  the orchestrator deferred the first full gate to after Stage 4 because of
  those five known-red tests.

## Stage 4 copy pass

Every user-visible string the merge brought home from core's Outlook alert
feeder, checked against the two rules: (a) the feeder stays
platform-agnostic and alerts only, with no Graph, IMAP, EWS, Power
Automate or add-ins anywhere in what it promises; (b) where the desk
speaks to a person it says "your AI", never "endpoint". Verdicts below
are against this tree after the re-homing.

### The Settings card (settings_view.py, `_outlook_alerts_section`, now inside the sources card of the tools section)

| # | String | Verdict |
|---|---|---|
| 1 | "Outlook alerts" (block title, an h3 inside the "Workbook, calendar and mail" card) | PASS. Platform-agnostic as a feature name (the app is Outlook, the source is the OS store); no protocol promised. |
| 2 | "Alerts only, not a mailbox: while the desk is open it reads the sender and subject lines of the Outlook alerts the OS notification store kept, writes them as header-only .eml files into the mail folder above, and drops any preview. Turning alerts on also turns the mail digest on, because the alerts land in that same folder. The manual .eml folder stays the history source." | PASS. Names only the OS notification store and the manual folder. |
| 3 | "Fetch Outlook alerts" (toggle label) | PASS. |
| 4 | "Not run yet. The first pass runs with the next mail poll, or press Fetch now." | PASS. |
| 5 | "Collector <name>" / "last run <time>" / "result <result>" / "unknown" (status line parts) | PASS. The names rendered are "wpn", "mac-notifications", "manual": OS mechanisms, no protocol words. |
| 6 | "Another pass is already running; nothing new ran." | PASS. Honest busy state, no count invented. |
| 7 | "<n> alert / alerts written into the mail folder in this fetch." | PASS. Shown only in a healthy result. |
| 8 | "Coverage <from> to <to>, the oldest and newest alert in this fetch." | PASS. |
| 9 | "No alert count is shown while the fetch is not working." | PASS. |
| 10 | "On a Mac the fix is Full Disk Access for this app; the manual .eml folder works without it." | PASS. A platform-specific remedy, shown only on the macOS cause; no connector promised. |
| 11 | "No automatic collector is available on this machine, so the manual .eml folder above is the mail source." | PASS. |
| 12 | "Coverage: only the alerts the OS notification store still keeps. Windows keeps about 20 per app and macOS keeps a short history; it is a live signal, not mailbox history. The manual .eml folder is the history source." | PASS. |
| 13 | "Fetch now" (button) | PASS. |

### Routes and the mail watcher

| # | String | Verdict |
|---|---|---|
| 14 | "Outlook alerts are off." (`POST /settings/mail/fetch-now` with the feed off) | PASS. |
| 15 | "The Outlook alert fetch failed: <detail>." (watcher error wrap) | PASS. |
| 16 | "The Outlook alert fetch returned no status." (watcher error wrap) | PASS. |
| 17 | "The <collector> collector could not finish: <detail>." (runner error cause) | PASS. |

### Collector causes (contract.py, collectors/wpn.py, collectors/mac_notifications.py)

| # | Constant | Verdict |
|---|---|---|
| 18 | MANUAL_CAUSE: "No automatic Outlook collector is available on this machine. Save the messages you want with Save as into the mail folder, and the desk will read them." | PASS. |
| 19 | NOT_WINDOWS_CAUSE: "The Windows notification store is only available on Windows." | PASS. |
| 20 | MISSING_STORE_CAUSE: "No Windows notification store was found on this machine." | PASS. |
| 21 | NO_HANDLER_CAUSE: "No Outlook notification handler is registered in the Windows notification store." | PASS. |
| 22 | UNREADABLE_STORE_CAUSE: "The Windows notification store could not be read." | PASS. |
| 23 | PLATFORM_CAUSE (macOS reader off macOS) | PASS. Ends "Save messages into the .eml folder instead." |
| 24 | MISSING_CAUSE (macOS database absent) | PASS. |
| 25 | FULL_DISK_ACCESS_CAUSE (macOS permission) | PASS. Names the consent and the recovery action. |
| 26 | UNREADABLE_CAUSE (macOS read failure) | PASS. |
| 27 | NO_OUTLOOK_CAUSE (no Outlook rows in the macOS store) | PASS. |

### What this touches (server/touches.py, three lines core extended)

| # | Line | Verdict |
|---|---|---|
| 28 | "Processes started: the desk launches no separate program when it starts. While it is open and Outlook alerts are on, it reads the local OS notification store for Outlook alerts, read-only, and writes header-only .eml files into your mail folder; that helper runs only inside the app, starts no scheduled task, service or autostart entry, and stops when the app closes. ..." | PASS. The loose word "helper" names the in-app reader, and the sentence says plainly that nothing separate runs; no protocol, no persistence promised. |
| 29 | "Persistence: none. No Run key, no scheduled task, no service, no autostart entry. The app, and its local Outlook alert reader, run only while you keep it open." | PASS. |
| 30 | "Mail: ... With Outlook alerts on, the app also reads the local OS notification store for Outlook alerts while it is open: sender and subject lines only, the preview dropped, saved as header-only .eml files; the manual .eml folder stays the history source." | PASS. |

### docs/known-limitations.md, section "Mail and Outlook alerts" (nine bullets, unchanged by this stage)

| # | Claim | Verdict |
|---|---|---|
| 31 | "The automatic Outlook feed is alerts only, not a mailbox..." | PASS. States the no-Message-ID/no-folders truth. |
| 32 | "Windows keeps only a short alert history, about 20 toasts per app..." | PASS. Coverage window, not completeness. |
| 33 | "The feeder reads only while the app is open. No OS task, service, login item or autostart entry..." | PASS. |
| 34 | "On macOS, reading Notification Center needs Full Disk Access..." | PASS. |
| 35 | "Message bodies, attachments, inline images and preview lines are never read or written..." | PASS. |
| 36 | "History stays manual on both platforms..." | PASS. |
| 37 | "Turning on \"Fetch Outlook alerts\" also turns on the mail digest..." | PASS. |
| 38 | "The macOS reader is verified against a synthetic Notification Center store..." | PASS. Honest unverified claim. |
| 39 | "When the platform reader is unavailable, the Settings card shows the reader's own cause..." | PASS. The card is the sources card after the re-homing; the sentence names no card title, so it stays true. |

### README bullets (dropped by the merge per the resolution rule, re-added adapted in this stage)

| # | Bullet | Verdict |
|---|---|---|
| 40 | Quick start, "Mail folder and Outlook alerts": adapted from core's bullet; core's closing "The Settings Sources card shows the collector, the last run, the coverage window and any honest cause" now reads "The Workbook, calendar and mail card shows the collector, the last run, the coverage window and any honest cause", because the card is the sources card of the tools section, not a Sources card. | PASS. |
| 41 | Development, the `src/agentdesk/feeder/` map bullet: adapted from core's repository map (agent-desk's README has no map section, so the bullet lives under Development). | PASS. |

### Rule sweep

- Rule (a): grep for `Graph`, `IMAP`, `EWS`, `Power Automate`, `add-in`
  across `src/agentdesk/feeder/`, the card copy, the touches lines and
  `docs/known-limitations.md` gives zero hits. The only appearances are
  in `specs/028-outlook-metadata-feeder.md`, and only as the problem
  statement ("the tenant blocks app registration, Graph, IMAP, EWS,
  Power Automate and Outlook add-ins") and its non-goals list. Nothing
  promises any of them. PASS.
- Rule (b): grep for `endpoint` across `src/agentdesk/feeder/` and the
  Outlook alerts block gives zero hits; no feeder string names an
  endpoint. The touches page's "Network: only the company LLM endpoint"
  line is
  agent-desk's own pre-merge sentence, untouched by core, so it
  is out of this pass's scope. PASS.
- No fixes were required: every string passed both rules as merged.
  The one adaptation this stage made is the card home itself (the block
  now renders inside the sources card of the tools section), which no
  string contradicted: none of core's copy named a card title or a
  section name.


## Stage 4 behaviour proof

The feeder-on recipe from the brief, run as one scratch script under
pinned.py full isolation. The script and its full output live outside the
repo, under the run's scratch folder:

- Script: `.scratch\bring-core-home\evidence\feeder-behaviour-proof\feeder_behaviour_proof.py`
- Output: `.scratch\bring-core-home\evidence\feeder-behaviour-proof\proof-output.txt`
  (final line: `checks: 20/20 passed`)

How the desk was booted: the layout audit's `_boot_desk` shape, in-process
`create_server` on an ephemeral port with a file keychain, never
`python -m agentdesk.server`. The store guard ran BEFORE any toggle:
`WpnCollector()._store()` resolved to
`<sandbox>\Microsoft\Windows\Notifications\wpndatabase.db`, under the
pinned sandbox, and the script exits without toggling if that ever fails.
The synthetic store was built with the helpers of
`tests/test_feeder_wpn.py` (the same `make_store` the evidence builder
`docs/evidence/2026-11-24-outlook-feeder/synthetic_stores.py` uses). The
second desk booted on a clean sub-sandbox (`<sandbox>\clean-sandbox`,
`<sandbox>\clean-sandbox-data`), which holds no store.

What the output shows, with only sandbox paths
(`C:\Users\mannk\AppData\Local\Temp\ad-sandbox-...\...`):

1. LOCALAPPDATA, AGENTDESK_DATA and USERPROFILE are one sandbox folder;
   AGENTDESK_MAIL_FOLDER is absent from the desk process.
2. The feeder is off by default and the card reads "Not run yet".
3. Enabling with no mail folder is accepted; Fetch now then shows the
   card's honest cause ("No mail folder is configured, so the feeder has
   nowhere to write. Choose the mail folder in Settings.").
4. With the sandbox mail folder and the synthetic store, the pass writes
   `<sandbox>\outlook-feeder.json` (collector `wpn`, result `ok`,
   written 3), releases its lock, and writes three header-only
   `feeder-<hash>.eml` files into `<sandbox>\mail`. One file is printed
   in full: From, Subject, Date, Message-ID and the blank line, nothing
   else; the preview sentinel never reached any file.
5. The card names the collector, the count and the coverage window.
6. Fetch now as a no-JS form post: without `return_to` it 303s to
   `/settings#sources`; with the form's own `return_to` it 303s to
   `/settings#tools`, the tools section.
7. Turning the feeder off sets `mail_feeder` false, unwires the watcher's
   feeder, and fetch-now then answers `{"ran": false,
   "error": "Outlook alerts are off."}`.
8. On the clean sub-sandbox the card renders its unavailable cause
   ("No Windows notification store was found on this machine."), the
   manual fallback sentence, and no alert count.

## Stage 5 compatibility proof

Run date: 2026-11-26, integration head `deb95aff` on `merge/bring-core-home`.
There is no compat branch and no compat worktree: the wave landed on
`origin/main` first (2026-11-26, PRs #345, #348, #349 and the earlier wave
PRs), so the integration branch carries the wave already and the proof runs on
the integration head itself. Verified read-only: every wave branch tip
(`fix/ui-text-overflow`, `merge/026-text-fit`, `merge/027-feedback`,
`docs/026-027-closeout`, `fix/027-review-audit`, `fix/027-review-server`,
`fix/027-review-dashboard`, `fix/027-review-marketplace`,
`fix/027-review-memory`, `docs/spec-027`, `docs/026-027-evidence`) is an
ancestor of `origin/main`, and PRs #345, #348 and #349 are MERGED.

### Safety read-back (before anything ran)

- `grep -c mail_feeder tools/layout_audit.py` is 0: the audit tool never sets
  `mail_feeder`, so the audit cannot switch the feeder on.
- `tests/conftest.py` holds the Stage 1 guard: `@pytest.fixture(autouse=True)
  def sandbox_localappdata`, which points `LOCALAPPDATA` at `tmp_path` for
  every test (a desk built by the app resolves the real Windows notification
  store through it).
- The `AGENTDESK_MAIL_FOLDER` pins are in place in every test file that turns
  the mail watcher or the feeder on: `tests/test_mail_watcher.py` (three),
  `tests/test_server_mail_api.py` (one), `tests/test_server_settings_api.py`
  (two, including the feeder toggle test),
  `tests/test_ui_feedback.py` and `tests/test_ui_feedback_review.py` (one
  each).

### The gate

Command: `pinned.py --gate python tools/ci_local.py` from the worktree root.
Transcript: `.scratch\bring-core-home\evidence\gate-stage5-20261126-195505.txt`.
npm ran inside the pinned gate environment; no direct-run fallback was needed.

Result: **6/7 gates passed in 122s; FAILED gates: pytest**. pytest:
1 failed, 3687 passed, 3 skipped. The six other gates are green
(py-grammar, frontend-check, frontend-tests with 647 vitest tests including
the text-fit files, licenses, registry-ci, brand-leak).

The one failure is real, not a flake (rerun under pinned full isolation,
`.scratch\bring-core-home\evidence\gate-stage5-20261126-195505-rerun-spec-numbering.txt`,
same failure): `tests/test_specs_numbering.py::test_every_spec_number_belongs_to_exactly_one_file`
fails with `one spec number addresses several files: {'024':
['024-outlook-metadata-feeder.md', '024-tracker-charts.md']}`. This is the
known spec number collision the run documents: core's feeder spec arrived as
`024`, which collides with agent-desk's own `specs/024-tracker-charts.md`.
The fix (renumber the feeder spec to the next free number and update its
references) is deliberately scheduled as the run's last commit so it is one
commit to drop if declined. Until that commit lands, the pytest gate shows
this failure and 7/7 is not reachable on this branch; nothing else fails.

### The layout audit

Command: the brief's layout audit command under pinned full isolation (never
`--gate`; the real `LOCALAPPDATA` never reaches the audit). Exit 0, elapsed
1179.4s. Run folder:
`.scratch\bring-core-home\evidence\postmerge-audit-20261126-195751\20261126-195752`.

Coverage complete: 1040 planned, 1028 measured, 12 skipped, 0 failed.

| | Post-merge (this run) | Baseline, pre-merge `origin/main` (`68044fc3`) | Wave run `20261124-195742` |
|---|---:|---:|---:|
| Findings | 872 | 872 | 836 |
| tiny-type (stress) | 820 (86) | 820 (86) | 784 (86) |
| squeezed-text (stress) | 40 (40) | 40 (40) | 40 (40) |
| runtime | 12 | 12 | 12 |
| 4-tuple groups (condition, state, kind, stress) | 82 | 82 | 82 |
| Root-cause groups | 45 | 45 | (not compared) |
| Coverage | 1040/1028/12/0 | 1040/1028/12/0 | 1040/1028/12/0 |

- **Primary comparison** (same tool version, same machine, taken hours before
  the merge at plain `origin/main`): folder
  `.scratch\bring-core-home\evidence\baseline-audit-premerge-68044fc\20261126-182949`.
  Post minus baseline is EMPTY: zero new groups, and zero groups resolved.
  Every count above is identical.
- **Secondary comparison**: the wave's own newest run,
  `.worktrees\027-merge\build\final-layout\20261124-195742`. It used an
  OLDER tool version, so absolute differences against it are expected and do
  not count against the proof (the whole 36-finding tiny-type delta is the
  tool's tighter detector, not the merge). The 4-tuple group set is
  nonetheless identical: zero new groups against it too.
- **Outlook alerts card: zero findings.** The check: every post-merge finding
  whose route is exactly `/settings`, matched case-insensitively against
  `outlook`, `mail_feeder`, `fetch`, `alerts`, `feeder` over its
  text, selector, classes and container: 0 hits. The check is not vacuous:
  the matrix measures `/settings` 24 times (4 stress rows), every row http
  200, and the route holds zero findings of any kind; the only settings-route
  findings live on `/settings/activity` (20, identical in the baseline). The
  card therefore rendered in every audited condition (the sandbox holds no
  store, so its unavailable state) and produced nothing.

### The recipe for whoever lands core second (or replays this merge)

The wave is already on `main`, so "landing second" is exactly this replay:

1. Cut the integration branch and its worktree from the current `origin/main`;
   never merge into `main` directly.
2. `git merge --no-ff --no-commit <core/main>`.
3. Resolve the 8 conflicted files by the standing rule (agent-desk's structure
   wins, core's pattern or feature is re-applied on top):
   - `GLOSSARY.md`: union; core's `# Glossary` heading demoted to
     `## Architecture vocabulary`, no duplicate terms.
   - `README.md`: agent-desk's side; core's two feeder bullets are re-added
     adapted in the copy pass, not by the merge.
   - `src/agentdesk/memory/store.py`: core's side (`serialized` imported as
     `_locked` from `agentdesk.locking`); move agent-desk's joined-reads
     rationale into the lock comment.
   - `src/agentdesk/server/app.py`, wizard compiler hunk: agent-desk's
     block, plus `_require_store` on the compiler line.
   - `src/agentdesk/server/app.py`, step registration hunk: core's `update`
     line with `order=STEP_ORDER_UPDATE`, then agent-desk's engine block with
     `order=STEP_ORDER_ENGINE` (add the constant).
   - `src/agentdesk/server/memory_api.py`: agent-desk's docstring and
     "Forget everything" confirm parameter, plus core's `_require_store`.
   - `src/agentdesk/server/settings_view.py`, hunk 1: the union (agent-desk's
     `SETTINGS_SECTIONS` and helpers, core's `_outlook_alerts_section`).
   - `src/agentdesk/server/settings_view.py`, hunk 2: agent-desk's side only
     (core's side re-adds the flat cards spec 022 removed).
   - `tests/test_server_settings_api.py`: agent-desk's "Rank with my AI"
     assertion, core's feeder tests appended.
   - `src/agentdesk/server/static/spa/*`: clear the markers on either side,
     then rebuild from merged source (next step); never hand-merge the
     bundle.
4. The four form-notice hunks in `server/app.py` (agents brief, presentation,
   capabilities, mail draft): keep the wave's notice flow and typed value
   handling at all four, and route the store-missing answers through the
   result-returning sibling (`StoreMissing` / `_store_missing` /
   `_send_store_missing`, one decision point, two answer shapes) instead of
   applying core's raw-JSON 503 there: these handlers answer form posts, and
   a raw JSON send would replace the person's page (and strand the wave's
   notice branch behind an already-sent response). Apply `_require_store`
   only where the handler answers JSON. Give the engine's tuple-shaped
   refusals the same sibling.
5. Boot blockers before anything runs: restore the lost `import secrets` in
   `server/app.py`; declare the engine step's order and keep one
   `_active_manifest` (the one that applies the chosen face); make the
   expected-pass helper iterate `ordered_steps()`.
6. Test isolation guards before any test runs: the autouse `LOCALAPPDATA`
   fixture in `tests/conftest.py`, and `AGENTDESK_MAIL_FOLDER` +
   `AGENTDESK_DATA` pins in every test that turns `mail_enabled` or
   `mail_feeder` on (the founder's real `config.env` sets
   `AGENTDESK_MAIL_FOLDER`; the app loads it on the command-line start path).
7. Re-home the Outlook alerts card into the sources card of the tools
   section (`settings_view.py`, inside `id='sources'`, "Workbook, calendar
   and mail"), existing server-page classes only, copy rules applied.
8. Rebuild the bundle as its own commit: `cd frontend && npm ci && npm run
   build`, then commit everything that changed under
   `src/agentdesk/server/static/spa/` (the build deletes old hashed assets).
   A second build must leave `git status` empty.
9. Re-run the counted pattern sweep (the table above) against the current
   `origin/main`; the post-fork sites move as `main` moves.
10. Gate: `pinned.py --gate python tools/ci_local.py` from the worktree root.
    Expect 6/7 until step 11; the pytest failure must be the spec-numbering
    collision and nothing else.
11. Renumber the feeder spec to the next free number and update its
    references (title, the five feeder tickets, the research note, the plan
    document, the comment in `src/agentdesk/settings.py`, this README).
    This is what makes `test_specs_numbering.py` pass and the gate reach
    7/7. DONE on this branch: the spec is `specs/028-outlook-metadata-feeder.md`
    (numbered 024 in the agent-desk-core sandbox; 028 was the next free
    number on every local branch at the time). A replay from before this
    branch must redo the step and choose the next free number at that
    moment.
12. Layout audit under pinned full isolation (never `--gate`): the command in
    the brief with conditions `fresh,data,plugins,full,legacy-dashboard,
    long-values,busy`, `--fail-on none --jobs 2`. Take the baseline at plain
    pre-merge `origin/main` BEFORE the merge, then require: coverage complete
    (planned == measured + skipped, none failed), zero new
    (condition, state, kind, stress) groups against that baseline and against
    the wave's newest run, and zero findings on the Outlook alerts card.
13. Everything through `pinned.py`; full isolation for anything that imports
    `agentdesk` or boots a desk; `--gate` only for the gate; never the real
    data folder, notification store, mail folder or keychain.
