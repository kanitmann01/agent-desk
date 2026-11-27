# Bring core home: the architecture sweep (Stage 3)

Run date: 2026-11-26. Branch: `merge/bring-core-home`. Every count below was
re-derived by grep in this tree, not taken from the plan's appendix. Each grep
runs from the repo root.

## The sweep table

| Pattern | Where core defines it | Sites core applied | Post-fork sites found | Sites applied by this run | The grep that proves it |
|---|---|---|---|---|---|
| Declared step order | `src/agentdesk/agentloop/loop.py`: `Step.order`, `STEP_ORDER_*`, `ordered_steps()` | 8 steps registered in `loop.py` and `server/app.py` with `order=` constants (deskcheck 100 through update 800) | 1: the `engine` step (PR #293, spec 023) | 0 new: already landed in Stage 1 (`STEP_ORDER_ENGINE = 900` at `loop.py:84`, engine registered with it at `app.py:8994`); this run verified the test lists all 9 names in pass order with `engine` last and the expected-pass helper iterates `ordered_steps()` | `grep -rn "register_step(Step(name=" src/` gives exactly 9 registrations, every one with `order=`; `grep -n "STEP_ORDER_ENGINE" src/agentdesk/agentloop/loop.py tests/test_agentloop.py` |
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
| agents brief | `_agents_run` path, the `server.agents is None` branch | `server/app.py:3045` | form notice kept verbatim, typed brief and agent kept |
| presentation | the presentation run path, same store read | `server/app.py:3167` | same |
| capabilities cache | `_send_capabilities_page` | `server/app.py:5248` | the merge had dropped both parents' response here (the handler answered nothing at all); the sibling restores the raw JSON 503 for callers and covers the form shape |
| mail draft | `_mail_draft`, the watcher read then the inbox read | `server/app.py:5505-5524` | the watcher read had gone through `_require_store` at merge time, which sent raw JSON to form posts and left the wave's notice branch dead behind a second send; the sibling answers once, in the caller's shape |

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
- `_memory_graph_json` (`memory_api.py:566`) and `_memory_loop_json`
  (`memory_api.py:897`): pre-fork JSON routes whose refusal shape is
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
